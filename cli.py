"""AI-friendly, headless command API. stdout is one JSON result; stderr is optional progress."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import signal
import sys
import threading

from PIL import Image

from engine import (VERSION, Settings, SynthesisError, extract_asset, asset_dict,
    asset_from_dict, load_image, load_recipe, generate_batch, MAX_RECIPE_BYTES, MAX_TOTAL_SAMPLES)
from legacy_bridge import ConversionSettings, convert_batch, engine_path, ENGINE_SHA256
from pool import (PoolEntry, POOL_SCHEMA, MATCH_POLICY, load_pool_recipe, generate_pool_batch)

CLI_SCHEMA = 'vt-toolbox-cli/1'
ASSET_SCHEMA = 'vt-defect-asset/1'


class CLIUsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIUsageError(message)


def parser():
    p = Parser(prog='VTStudioCLI',description='VT Studio 图像工具箱：无界面批处理，默认输出 UTF-8 JSON。')
    p.add_argument('--version',action='version',version=VERSION)
    p.add_argument('--json-out',help='额外保存最终 JSON；文件必须不存在。全局参数放在子命令前。')
    p.add_argument('--progress',action='store_true',help='将 JSON 行进度写入 stderr；stdout 仍只有最终结果。')
    sub = p.add_subparsers(dest='command',required=True,parser_class=Parser)
    sub.add_parser('info',help='工具能力与版本')
    sub.add_parser('schema',help='机器可读的命令契约、参数单位和退出码')
    inspect = sub.add_parser('inspect',help='查看图像格式、尺寸与灰度/RGB兼容性')
    inspect.add_argument('image')
    conv = sub.add_parser('convert',help='复用 VT Studio 5.0 原核心，裁切/补边，保持左上角原点')
    conv.add_argument('--input',required=True,help='输入 BMP/PNG 文件夹')
    conv.add_argument('--output',required=True,help='独立输出根目录')
    conv.add_argument('--width',type=int,required=True)
    conv.add_argument('--height',type=int,required=True)
    conv.add_argument('--fill',choices=['black','white'],default='black')
    conv.add_argument('--recursive',action=argparse.BooleanOptionalAction,default=True)
    conv.add_argument('--copy-xml',action=argparse.BooleanOptionalAction,default=True)
    conv.add_argument('--allow-annotation-clip',action='store_true')
    asset = sub.add_parser('extract-asset',help='通过明确给定的矩形/多边形，从 NG 图提取素材')
    asset.add_argument('--ng',required=True)
    shape = asset.add_mutually_exclusive_group(required=True)
    shape.add_argument('--rect',help='原图像素 left,top,right,bottom，右下边界不包含')
    shape.add_argument('--polygon',help='原图像素 x,y;x,y;x,y;... 至少3个顶点')
    asset.add_argument('--output',required=True,help='新素材 JSON 文件（含无损素材和掩膜）')
    asset_roi=asset.add_mutually_exclusive_group()
    asset_roi.add_argument('--roi-normalized',help='此NG的生成范围 left,top,right,bottom，0～1；不改变素材选区')
    asset_roi.add_argument('--roi-regions',help='多个允许框，按分号分隔各组left,top,right,bottom；均为0～1比例')
    syn = sub.add_parser('synthesize',help='按素材或 GUI 保存的配方，批量生成缺陷 BMP')
    kind = syn.add_mutually_exclusive_group(required=True)
    kind.add_argument('--recipe',help='GUI/批次保存的 recipe.json')
    kind.add_argument('--asset',help='extract-asset 生成的素材 JSON')
    kind.add_argument('--assets',nargs='+',help='多份素材JSON，按颜色/范围/尺寸随机匹配；各自可携带生成范围')
    source = syn.add_mutually_exclusive_group()
    source.add_argument('--ok',nargs='+',help='明确作为 OK 底图的文件列表')
    source.add_argument('--input-folder',help='OK 底图文件夹，仅当前层，不递归')
    syn.add_argument('--output',required=True)
    quantity=syn.add_mutually_exclusive_group()
    quantity.add_argument('--count',type=int,help='每张 OK 生成数量，1～1000；覆盖配方总数模式')
    quantity.add_argument('--total',type=int,help='本批精确总数，1～100000；按OK顺序均匀分配')
    syn.add_argument('--seed',type=int)
    syn.add_argument('--mode',choices=['darken','texture'])
    syn.add_argument('--class-name')
    syn_roi=syn.add_mutually_exclusive_group()
    syn_roi.add_argument('--roi-normalized',help='允许区域 left,top,right,bottom；范围 0～1')
    syn_roi.add_argument('--roi-regions',help='多个允许框，分号分隔；替换各素材原有范围')
    syn.add_argument('--xml',choices=['vt-flaw','none'],help='VT原生缺陷矩形XML或关闭；默认沿用配方/开启')
    for name in ['scale-min','scale-max','strength-min','strength-max','rotation','feather','reference-gray']:
        syn.add_argument('--'+name,type=float)
    validate = sub.add_parser('validate-recipe',help='检查配方，返回参数、素材信息与底图路径状态')
    validate.add_argument('recipe')
    return p


def numbers(text, count=None):
    try:
        values = tuple(float(x.strip()) for x in text.split(','))
    except ValueError as exc:
        raise SynthesisError('坐标须为逗号分隔的数值。') from exc
    if count is not None and len(values) != count:
        raise SynthesisError(f'需要 {count} 个坐标数值。')
    if not all(math.isfinite(x) for x in values):
        raise SynthesisError('坐标必须为有限数值。')
    return values


def save_new_json(path, data):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    return str(path)


def roi_regions(text):
    regions=tuple(numbers(part,4) for part in text.split(';'))
    Settings(rois=regions).validate()
    return regions


def read_asset_document(path):
    p = Path(path)
    if p.stat().st_size > MAX_RECIPE_BYTES:
        raise SynthesisError('素材文件过大。')
    value = json.loads(p.read_text(encoding='utf-8'))
    if value.get('schema') != ASSET_SCHEMA:
        raise SynthesisError('不支持的素材文件版本。')
    return value


def read_asset(path):
    return asset_from_dict(read_asset_document(path)['asset'])


def read_asset_entry(path, entry_id):
    data=read_asset_document(path)
    asset=asset_from_dict(data['asset'])
    roi=tuple(data.get('roi_normalized',(0.,0.,1.,1.)))
    regions=tuple(tuple(r) for r in data.get('roi_regions_normalized',()))
    Settings(roi=roi,rois=regions).validate()
    name=Path(asset.provenance.get('source_ng','')).name or Path(path).name
    return PoolEntry(entry_id,name,asset,roi,regions)


def command_schema():
    return {
        'schema': CLI_SCHEMA, 'tool_version': VERSION, 'input_encoding': 'UTF-8',
        'result': 'one JSON object on stdout; no interactive prompts',
        'global_options': {'--json-out':'new file, before subcommand; refuses overwrite',
                           '--progress':'JSONL stderr only, before subcommand'},
        'exit_codes': {'0':'success','1':'validation or processing error','2':'argument error',
                       '3':'partial conversion (skipped/failed files)','130':'cancelled'},
        'commands': {
            'info': {}, 'schema': {}, 'inspect': {'image':'path'},
            'convert': {'--input':'BMP/PNG folder','--output':'independent output root',
                        '--width':'integer 1..200000 px','--height':'integer 1..200000 px',
                        '--fill':['black','white'],'--recursive':'default true; --no-recursive disables',
                        '--copy-xml':'default true; --no-copy-xml disables',
                        '--allow-annotation-clip':'default false; original core annotation policy'},
            'extract-asset': {'--ng':'8-bit grayscale L or 8-bit/channel RGB path','--output':'new JSON file',
                              '--rect':'left,top,right,bottom pixels; half-open',
                              '--polygon':'x,y;x,y;...; mutually exclusive with rect',
                              '--roi-normalized':'optional per-NG generation bounds 0..1; default full image'},
            'synthesize': {'--recipe':'GUI single/pool recipe OR --asset OR --assets',
                           '--assets':'one or more asset JSONs; seeded same-product pool matching',
                           '--ok':'one or more explicitly OK files; overrides recipe paths',
                           '--input-folder':'top-level OK images; mutually exclusive with --ok',
                           '--output':'output root; creates unique batch',
                           '--count':'per OK image 1..1000', '--mode':['darken','texture'],
                           '--total':'exact batch total 1..100000; mutually exclusive with --count; balanced in OK input order',
                           '--class-name':'1..80 characters', '--seed':'0..2147483647',
                           '--scale-min':'0.02..5', '--scale-max':'0.02..5; >= minimum',
                           '--strength-min':'>0..1', '--strength-max':'>0..1; >= minimum',
                           '--rotation':'0..180 degrees; sampled +/-', '--feather':'0..100 output pixels',
                           '--reference-gray':'0 automatic (RGB per channel) or 1..255 shared by all channels',
                           '--roi-normalized':'left,top,right,bottom 0..1; default full image'},
            'validate-recipe': {'recipe':'path'},
        },
        'coordinate_convention':'zero-based, top-left origin, x right/y down, right/bottom excluded',
        'multi_region_options':{'--roi-regions':'up to64 boxes l,t,r,b;l,t,r,b in0..1; exclusive with --roi-normalized',
                                'placement':'whole transformed patch must fit one box; never use the union bounding box'},
        'xml_option':{'--xml':['vt-flaw','none'],'default':'enabled unless recipe disables',
                      'profile':'VisionTrain 2.2.x FlawTrainData rectangle; XML beside BMP, exact mask is separate PNG'},
        'default_synthesis_settings': asdict(Settings()),
        'compatibility':'vt-defect-lab/1 single recipes; vt-defect-pool/1 pool recipes; vt-defect-asset/1 assets',
        'pool_policy': {'matching':MATCH_POLICY,'per_ng_roi':True,'max_entries':200,
                        'no_match':'fail before creating a batch if any OK has no usable donor',
                        'product_material_identity':'operator supplies same-product pool; no semantic material recognition'},
        'color_policy': {'input_modes':['L','RGB'], 'indexed_images':'expand to L or RGB; transparency rejected',
                         'output':'BMP preserving base mode: L 8-bit or RGB 24-bit',
                         'matching':'OK images and NG asset must have the same mode',
                         'mask':'L, 255 if any output channel changed; otherwise 0',
                         'rgb_recipe_min_tool_version':'6.1.0'},
        'side_effects':'local files only; originals read-only; never train a model or upload images',
    }


def execute(args, cancel):
    def progress(event):
        if args.progress and sys.stderr is not None:
            print(json.dumps(event,ensure_ascii=False),file=sys.stderr,flush=True)
    if args.command == 'schema':
        return command_schema(),0
    if args.command == 'info':
        path = engine_path()
        return {'tool':'VT STUDIO 图像工具箱','version':VERSION,'cli_schema':CLI_SCHEMA,
                'headless':True,'gpu_required':False,'network_required':False,
                'defect_input_modes':['L','RGB'],
                'multi_ng_pool':True,'matching_policy':MATCH_POLICY,
                'legacy_engine_sha256':ENGINE_SHA256,'legacy_engine':str(path),
                'commands':list(command_schema()['commands'])},0
    if args.command == 'inspect':
        path = Path(args.image).expanduser().resolve()
        with Image.open(path) as im:
            data = {'path':str(path),'width':im.width,'height':im.height,'mode':im.mode,'format':im.format}
        try:
            effective = load_image(path)
            data['defect_input_compatible'] = True
            data['effective_mode'] = effective.mode
        except Exception as exc:
            data.update(defect_input_compatible=False,reason=str(exc))
        return data,0
    if args.command == 'convert':
        settings = ConversionSettings(args.input,args.output,args.width,args.height,
            args.fill=='white',args.recursive,args.copy_xml,args.allow_annotation_clip)
        result = convert_batch(settings,progress,cancel.is_set)
        code = 130 if result['status']=='cancelled' else 3 if result['status']=='partial' else 0
        return result,code
    if args.command == 'extract-asset':
        image = load_image(args.ng)
        if args.rect:
            l,t,r,b = numbers(args.rect,4)
            if not l<r or not t<b:
                raise SynthesisError('矩形需要 left < right 且 top < bottom。')
            points = [(l,t),(r,t),(r,b),(l,b)]
        else:
            points = [numbers(part,2) for part in args.polygon.split(';') if part.strip()]
        if not all(0<=x<=image.width and 0<=y<=image.height for x,y in points):
            raise SynthesisError('圈选坐标超出 NG 图像范围。')
        asset = extract_asset(image,points,str(Path(args.ng).resolve()))
        roi=numbers(args.roi_normalized,4) if args.roi_normalized else (0.,0.,1.,1.)
        regions=roi_regions(args.roi_regions) if args.roi_regions else ()
        if regions:
            roi=regions[0]
        Settings(roi=roi,rois=regions).validate()
        saved = save_new_json(args.output,{'schema':ASSET_SCHEMA,'asset':asset_dict(asset),'roi_normalized':list(roi),
                                          'roi_regions_normalized':[list(r) for r in regions]})
        return {'asset_file':saved,'size':list(asset.pixels.size),'image_mode':asset.pixels.mode,
                'reference_gray':asset.reference_gray,'reference_rgb':asset.reference_rgb,
                'provenance':asset.provenance,'roi_normalized':list(roi),'roi_regions_normalized':[list(r) for r in regions]},0
    if args.command == 'validate-recipe':
        entries,settings,paths,pending = load_pool_recipe(args.recipe)
        asset=entries[0].asset
        return {'valid':True,'settings':asdict(settings),'asset_size':list(asset.pixels.size),
                'asset_mode':asset.pixels.mode,'reference_rgb':asset.reference_rgb,
                'source_ng':asset.provenance.get('source_ng'),
                'pool_entries':len(entries),'matching_policy':MATCH_POLICY,'pending_ng_paths':[p['path'] for p in pending],
                'entries':[{'id':e.entry_id,'name':e.name,'mode':e.asset.pixels.mode,'roi_normalized':list(e.roi),'roi_regions_normalized':[list(r) for r in e.rois],
                            'source_ng':e.asset.provenance.get('source_ng')} for e in entries],
                'ok_paths':[{'path':p,'exists':Path(p).is_file()} for p in paths]},0
    if args.command == 'synthesize':
        entries=None
        if args.recipe:
            entries,settings,paths,_ = load_pool_recipe(args.recipe)
        elif args.assets:
            entries=[read_asset_entry(p,f'asset-{i:03d}') for i,p in enumerate(args.assets,1)]
            settings,paths=Settings(),[]
        else:
            entry=read_asset_entry(args.asset,'single-asset')
            asset,settings,paths = entry.asset,Settings(roi=entry.roi,rois=entry.rois),[]
        if args.ok:
            paths = args.ok
        elif args.input_folder:
            folder = Path(args.input_folder).resolve()
            if not folder.is_dir():
                raise SynthesisError('OK 图片文件夹不存在。')
            paths = [str(p) for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in ('.bmp','.png','.tif','.tiff')]
        if not paths:
            raise SynthesisError('请提供 --ok、--input-folder，或在配方中保存有效底图路径。')
        for field in ['mode','class_name','seed','scale_min','scale_max','strength_min','strength_max',
                      'rotation','feather','reference_gray']:
            value = getattr(args,field)
            if value is not None:
                setattr(settings,field,value)
        if args.count is not None:
            settings.samples_per_ok = args.count
            settings.total_samples = 0
        if args.total is not None:
            if not 1<=args.total<=MAX_TOTAL_SAMPLES:
                raise SynthesisError('本批生成总数须为1～100000的整数。')
            settings.total_samples=args.total
        if args.roi_normalized:
            settings.roi = numbers(args.roi_normalized,4)
            settings.rois=()
            if entries is not None:
                for entry in entries:
                    entry.roi=tuple(settings.roi)
                    entry.rois=()
        if args.roi_regions:
            settings.rois=roi_regions(args.roi_regions)
            settings.roi=settings.rois[0]
            if entries is not None:
                for entry in entries:
                    entry.roi=settings.roi;entry.rois=settings.rois
        if args.xml is not None:
            settings.export_vt_xml=args.xml=='vt-flaw'
        settings.validate()
        generator=generate_pool_batch if entries is not None else generate_batch
        result = generator(paths,entries if entries is not None else asset,settings,args.output,
            lambda done,total,name:progress({'type':'progress','completed':done,'total':total,'sample':name}),
            cancel.is_set)
        return result,130 if result['status']=='cancelled' else 0
    raise CLIUsageError('Unsupported command')


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args,code,envelope = None,0,None
    cancelled = threading.Event()
    old_handler = signal.getsignal(signal.SIGINT)
    try:
        args = parser().parse_args(argv)
        if sys.stdout is None and not args.json_out:
            return 2  # GUI entry requires --json-out; use VTStudioCLI.exe for stdout.
        if args.json_out and Path(args.json_out).exists():
            raise SynthesisError('JSON 报告文件已存在，请指定新文件名。')
        signal.signal(signal.SIGINT,lambda *_:cancelled.set())
        data,code = execute(args,cancelled)
        envelope = {'schema':CLI_SCHEMA,'ok':code==0,'command':args.command,'exit_code':code,'data':data}
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        code = 2 if isinstance(exc,CLIUsageError) else 1
        envelope = {'schema':CLI_SCHEMA,'ok':False,'command':getattr(args,'command',None),
                    'exit_code':code,'error':str(exc),'error_type':type(exc).__name__}
        if getattr(exc,'run_dir',None):
            envelope['run_dir'] = exc.run_dir
    finally:
        signal.signal(signal.SIGINT,old_handler)
    if args and args.json_out:
        try:
            save_new_json(args.json_out,envelope)
        except Exception as exc:
            if code==0:
                code=1
                envelope={'schema':CLI_SCHEMA,'ok':False,'command':args.command,'exit_code':code,
                          'error':f'结果已处理，但 JSON 报告保存失败：{exc}','data':envelope.get('data')}
    if sys.stdout is not None:
        print(json.dumps(envelope,ensure_ascii=False),flush=True)
    return code


if __name__=='__main__':
    sys.exit(main())
