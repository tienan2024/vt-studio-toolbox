"""Adapter for the unmodified conversion core embedded in the user's VT Studio 5.0."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

from PIL import Image

from engine import SynthesisError, write_json

ENGINE_SHA256 = '94a015245345ea11fe6da2f87a1be28733218d890ad2b8b1bf130006a5a6675e'


@dataclass
class ConversionSettings:
    input_folder: str
    output_root: str
    width: int = 3200
    height: int = 3960
    white: bool = False
    recursive: bool = True
    copy_xml: bool = True
    allow_annotation_clip: bool = False

    def validate(self):
        if type(self.width) is not int or type(self.height) is not int or not 1 <= self.width <= 200000 or not 1 <= self.height <= 200000:
            raise SynthesisError('目标宽高须为 1～200000 的整数。')
        source = Path(self.input_folder).expanduser().resolve()
        if not source.is_dir():
            raise SynthesisError('请选择存在的输入图片文件夹。')
        if not self.output_root.strip():
            raise SynthesisError('请选择输出文件夹。')
        destination = Path(self.output_root).expanduser().resolve()
        # A recursive input cannot include newly written outputs or prior batch outputs.
        if destination == source or source in destination.parents:
            raise SynthesisError('输出位置不能是输入文件夹本身或其子文件夹，请选择独立目录。')
        if destination.exists() and not destination.is_dir():
            raise SynthesisError('输出位置需要是文件夹。')


def scan_images(folder: str, recursive: bool = True) -> list[Path]:
    root = Path(folder).resolve()
    if not root.is_dir():
        raise SynthesisError('输入文件夹不存在。')
    files = root.rglob('*') if recursive else root.iterdir()
    images = sorted((p.resolve() for p in files if p.is_file() and p.suffix.lower() in ('.bmp', '.png')),
                    key=lambda p: str(p).casefold())
    # The legacy engine flattens its outputs. Reject ambiguous names, do not rename.
    names = {}
    for p in images:
        key = p.name.casefold()
        if key in names:
            raise SynthesisError(f'存在同名图片 {p.name}。集中输出且保留文件名时不能合并，请分批处理。')
        names[key] = p
    return images


def engine_path() -> Path:
    path = Path(__file__).with_name('legacy')/'vt-engine.exe'
    if not path.is_file():
        raise SynthesisError('缺少 VT Studio 原转换核心，请保留完整工具箱文件夹。')
    if hashlib.sha256(path.read_bytes()).hexdigest() != ENGINE_SHA256:
        raise SynthesisError('VT Studio 转换核心校验失败，请使用完整发布包恢复。')
    return path


def _stream_reader(stream, events, kind):
    try:
        for line in stream:
            events.put((kind, line))
    except (OSError, ValueError):
        pass  # Process teardown may close a pipe while a reader reaches EOF.
    finally:
        events.put((kind, None))


def run_legacy(settings: ConversionSettings, destination: Path, notify=None, cancelled=None):
    payload = {
        'Input': str(Path(settings.input_folder).resolve()), 'Output': str(destination.resolve()),
        'Width': settings.width, 'Height': settings.height, 'White': settings.white,
        'Recursive': settings.recursive, 'CopyXML': settings.copy_xml,
        'AllowClip': settings.allow_annotation_clip,
    }
    events = queue.Queue()
    process = subprocess.Popen([str(engine_path())], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        errors='replace', bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    threads = [threading.Thread(target=_stream_reader, args=(process.stdout, events, 'out'), daemon=True),
               threading.Thread(target=_stream_reader, args=(process.stderr, events, 'err'), daemon=True)]
    for t in threads:
        t.start()
    result, errors, stopped, cancelled_at, closed = None, [], False, None, set()
    try:
        process.stdin.write(json.dumps(payload, ensure_ascii=False)+'\n')
        process.stdin.flush()
        while True:
            if cancelled and cancelled() and not stopped and process.poll() is None:
                process.stdin.write('stop\n')
                process.stdin.flush()
                stopped, cancelled_at = True, time.monotonic()
            if cancelled_at and time.monotonic()-cancelled_at > 10 and process.poll() is None:
                process.terminate()
                raise SynthesisError('已停止转换核心；请检查批次记录，未完成样本不会计为成功。')
            try:
                kind, line = events.get(timeout=0.1)
            except queue.Empty:
                if process.poll() is not None and len(closed) == 2:
                    break
                continue
            if line is None:
                closed.add(kind)
                if process.poll() is not None and len(closed) == 2 and events.empty():
                    break
                continue
            if kind == 'err':
                errors.append(line[:2000])
                errors = errors[-20:]
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SynthesisError('原转换核心返回了无法解析的消息。') from exc
            if notify:
                notify(event)
            if event.get('type') == 'fatal':
                raise SynthesisError(event.get('message') or '原转换核心拒绝了任务。')
            if event.get('type') == 'done':
                result = event.get('report')
                break
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        process.wait(timeout=15)
        if result is None or process.returncode > 1:
            raise SynthesisError(f'原转换核心未正常结束（代码 {process.returncode}）。'+''.join(errors)[-2000:])
        return result
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
        for t in threads:
            t.join(timeout=1)


def convert_batch(settings: ConversionSettings, notify=None, cancelled=None):
    settings.validate()
    images = scan_images(settings.input_folder, settings.recursive)
    if not images:
        raise SynthesisError('输入目录未找到 BMP / PNG 图片。')
    if settings.copy_xml:
        xml_names = {}
        for image in images:
            xml = image.with_suffix('.xml')
            if xml.is_file():
                key = xml.name.casefold()
                if key in xml_names and xml_names[key] != xml.resolve():
                    raise SynthesisError(f'存在同名 XML 点集 {xml.name}。请分批处理，避免集中输出覆盖。')
                xml_names[key] = xml.resolve()
    if cancelled and cancelled():
        return {'status': 'cancelled', 'run_dir': None, 'images': [], 'completed': 0, 'total': len(images)}
    root = Path(settings.output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = root/('convert_'+datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    run.mkdir(exist_ok=False)
    output = run/'images'
    output.mkdir()
    record = {'schema': 'vt-toolbox-conversion/1', 'settings': asdict(settings),
              'engine_sha256': ENGINE_SHA256, 'engine_origin': 'VT Studio 5.0 embedded Windows engine',
              'anchor': 'top_left', 'pointsets': 'copied byte-for-byte when enabled; never transformed',
              'status': 'running', 'run_dir': str(run), 'completed': 0, 'total': len(images)}
    write_json(run/'summary.json', record)
    try:
        with (run/'events.jsonl').open('w', encoding='utf-8') as log:
            def event_callback(event):
                log.write(json.dumps(event, ensure_ascii=False)+'\n')
                log.flush()
                if event.get('type') == 'progress' and event.get('report'):
                    report = event['report']
                    record['completed'] = report['OK']
                if notify:
                    notify(event)
            report = run_legacy(settings, output, event_callback, cancelled)
        record['legacy_report'] = report
        record['completed'] = report['OK']
        record['status'] = ('cancelled' if report['Cancelled'] else
                            'partial' if report['Failed'] or report['Skipped'] else 'complete')
        record['images'] = [str(p.resolve()) for p in sorted(output.iterdir()) if p.suffix.lower() in ('.bmp','.png')]
        return record
    except Exception as exc:
        record.update(status='failed', error=str(exc))
        error = SynthesisError(f'转换未完成。批次记录位于 {run}。原因：{exc}')
        error.run_dir = str(run)
        raise error from exc
    finally:
        write_json(run/'summary.json', record)


def preview_conversion(source: Image.Image, width: int, height: int, white=False, limit=1600):
    """Display-only approximation; output uses the untouched legacy engine."""
    if width < 1 or height < 1:
        raise SynthesisError('预览宽高应大于 0。')
    ratio = min(1.0, limit/max(source.width, source.height, width, height))
    sw, sh = max(1, round(source.width*ratio)), max(1, round(source.height*ratio))
    tw, th = max(1, round(width*ratio)), max(1, round(height*ratio))
    mode = 'L' if source.mode == 'L' else 'RGB'
    background = 255 if white else 0
    resized = source.convert(mode).resize((sw,sh), Image.Resampling.LANCZOS) if ratio != 1 else source.convert(mode).copy()
    output = Image.new(mode, (tw, th), background if mode == 'L' else (background,)*3)
    output.paste(resized.crop((0, 0, min(sw,tw), min(sh,th))), (0,0))
    return output, ratio
