"""Local, deterministic grayscale/RGB defect synthesis; no model or network required."""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from io import BytesIO
import json
import math
from pathlib import Path
import random
import re
from typing import Callable
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from vt_xml import write_vt_xml

VERSION = "6.5.0"
MAX_ROI_REGIONS = 64
MAX_TOTAL_SAMPLES = 100_000
SCHEMA = "vt-defect-lab/1"
MAX_PIXELS = 60_000_000
MAX_RECIPE_BYTES = 340_000_000  # RGB PNG + L mask, base64 and JSON overhead.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class SynthesisError(ValueError):
    pass


def load_image(path: str | Path) -> Image.Image:
    """Preserve L/RGB; expand indexed images without discarding color or alpha."""
    with Image.open(path) as source:
        if source.width * source.height > MAX_PIXELS:
            raise SynthesisError("图像超过 6000 万像素，请先裁成实际检测区域。")
        source.load()
        if 'transparency' in source.info:
            raise SynthesisError("暂不支持透明图像，请先明确合成背景并保存为 L 或 RGB 副本。")
        if source.mode == "P":
            rgb = np.asarray(source.convert("RGB"))
            if not (np.array_equal(rgb[..., 0], rgb[..., 1]) and
                    np.array_equal(rgb[..., 1], rgb[..., 2])):
                return source.convert("RGB")
            return source.convert("L")
        if source.mode not in ("L", "RGB"):
            raise SynthesisError(f"需要 8 位灰度 L 或每通道 8 位 RGB 图，当前为 {source.mode}。请先明确转换副本。")
        return source.copy()


def load_gray(path: str | Path) -> Image.Image:
    """Compatibility helper for callers that explicitly require grayscale."""
    image = load_image(path)
    if image.mode != "L":
        raise SynthesisError("此调用需要 8 位灰度图，当前为 RGB。")
    return image


@dataclass
class Asset:
    pixels: Image.Image
    mask: Image.Image
    reference_gray: float
    provenance: dict
    reference_rgb: tuple[float, float, float] | None = None


def extract_asset(image: Image.Image, points: list[tuple[float, float]],
                  source: str = "") -> Asset:
    if image.mode not in ("L", "RGB"):
        raise SynthesisError("缺陷素材需要 8 位灰度 L 或每通道 8 位 RGB 图。")
    if len(points) < 3:
        raise SynthesisError("请先画矩形，或至少点击三个顶点完成多边形。")
    if not all(math.isfinite(float(v)) for p in points for v in p):
        raise SynthesisError("选区坐标无效。")
    xy = [(max(0.0, min(float(x), image.width)),
           max(0.0, min(float(y), image.height))) for x, y in points]
    left, top = math.floor(min(p[0] for p in xy)), math.floor(min(p[1] for p in xy))
    right, bottom = math.ceil(max(p[0] for p in xy)), math.ceil(max(p[1] for p in xy))
    if right - left < 3 or bottom - top < 3:
        raise SynthesisError("缺陷选区过小，请重新圈选。")
    patch = image.crop((left, top, right, bottom))
    mask = Image.new("L", patch.size)
    ImageDraw.Draw(mask).polygon([(x-left, y-top) for x, y in xy], fill=255)
    if np.count_nonzero(np.asarray(mask)) < 4:
        raise SynthesisError("选区没有有效面积，请重新圈选。")
    margin = max(8, round(max(patch.size) * 0.12))
    context = (max(0, left-margin), max(0, top-margin),
               min(image.width, right+margin), min(image.height, bottom+margin))
    surrounding = np.asarray(image.crop(context))
    outside = np.ones(surrounding.shape[:2], dtype=bool)
    outside[top-context[1]:bottom-context[1], left-context[0]:right-context[0]] = False
    reference_rgb = None
    if image.mode == "RGB":
        samples = surrounding[outside] if outside.any() else np.asarray(patch).reshape(-1, 3)
        reference_rgb = tuple(float(max(1, v)) for v in np.percentile(samples, 65 if outside.any() else 90, axis=0))
        # Keep the old scalar field meaningful for the shared UI/manual override.
        gray_context = np.asarray(image.crop(context).convert("L"))
        gray_patch = np.asarray(patch.convert("L"))
        reference = float(np.percentile(gray_context[outside], 65)) if outside.any() else float(np.percentile(gray_patch, 90))
    else:
        reference = float(np.percentile(surrounding[outside], 65)) if outside.any() else float(np.percentile(np.asarray(patch), 90))
    return Asset(patch, mask, max(1.0, reference), {
        "source_ng": str(source), "source_size": list(image.size),
        "source_mode": image.mode,
        "source_polygon_xy": [[round(x, 3), round(y, 3)] for x, y in xy],
        "source_bbox_xyxy": [left, top, right, bottom],
    }, reference_rgb)


@dataclass
class Settings:
    mode: str = "darken"
    scale_min: float = 0.65
    scale_max: float = 1.10
    rotation: float = 12.0
    strength_min: float = 0.55
    strength_max: float = 0.95
    feather: float = 6.0
    reference_gray: float = 0.0  # zero = use donor context estimate
    samples_per_ok: int = 5
    seed: int = 20261026
    class_name: str = "脏污"
    roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    total_samples: int = 0  # zero preserves the original per-OK count policy
    rois: tuple = ()  # Empty preserves legacy single-roi behavior.
    export_vt_xml: bool = True

    def validate(self):
        if type(self.export_vt_xml) is not bool:
            raise SynthesisError('VT XML导出选项须为布尔值。')
        if self.mode not in ("darken", "texture"):
            raise SynthesisError("不支持的合成方式。")
        numeric = [self.scale_min, self.scale_max, self.rotation, self.strength_min,
                   self.strength_max, self.feather, self.reference_gray, *self.roi]
        if not all(isinstance(n, (int, float)) and math.isfinite(n) for n in numeric):
            raise SynthesisError("参数必须为有限数值。")
        if not 0.02 <= self.scale_min <= self.scale_max <= 5:
            raise SynthesisError("缩放范围须满足 0.02 ≤ 最小值 ≤ 最大值 ≤ 5。")
        if not 0 < self.strength_min <= self.strength_max <= 1:
            raise SynthesisError("强度范围须满足 0 < 最小值 ≤ 最大值 ≤ 1。")
        if not 0 <= self.rotation <= 180 or not 0 <= self.feather <= 100:
            raise SynthesisError("旋转应为 0～180 度，羽化应为 0～100 像素。")
        if not 0 <= self.reference_gray <= 255:
            raise SynthesisError("背景灰度应为 0（自动）或 1～255。")
        if type(self.samples_per_ok) is not int or not 1 <= self.samples_per_ok <= 1000:
            raise SynthesisError("每张底图生成数量须为 1～1000 的整数。")
        if type(self.total_samples) is not int or not 0 <= self.total_samples <= MAX_TOTAL_SAMPLES:
            raise SynthesisError("本批总数应为1～100000的整数；0表示使用每张OK数量。")
        if type(self.seed) is not int or not 0 <= self.seed <= 2_147_483_647:
            raise SynthesisError("随机种子应为 0～2147483647 的整数。")
        if not isinstance(self.class_name, str) or not self.class_name.strip() or len(self.class_name) > 80:
            raise SynthesisError("请填写不超过 80 字的缺陷类别。")
        if self.export_vt_xml and any(ord(c)<32 for c in self.class_name):
            raise SynthesisError('VT XML类别名称不能包含控制字符。')
        if len(self.roi) != 4 or not 0 <= self.roi[0] < self.roi[2] <= 1 or not 0 <= self.roi[1] < self.roi[3] <= 1:
            raise SynthesisError("允许区域应为图像范围内的有效矩形。")
        if not isinstance(self.rois,(list,tuple)) or len(self.rois)>MAX_ROI_REGIONS:
            raise SynthesisError('每份素材最多设置64个允许范围。')
        for region in self.rois:
            if (not isinstance(region,(list,tuple)) or len(region)!=4 or
                    not all(isinstance(v,(int,float)) and math.isfinite(v) for v in region) or
                    not 0<=region[0]<region[2]<=1 or not 0<=region[1]<region[3]<=1):
                raise SynthesisError('多个允许范围须为0～1比例的有效矩形。')


def generation_counts(num_ok: int, settings: Settings) -> list[int]:
    settings.validate()
    if type(num_ok) is not int or num_ok < 1:
        raise SynthesisError("请先导入至少一张真实OK底图。")
    if settings.total_samples:
        quotient,remainder=divmod(settings.total_samples,num_ok)
        return [quotient+(i<remainder) for i in range(num_ok)]
    return [settings.samples_per_ok]*num_ok


def settings_payload(settings: Settings):
    data=asdict(settings)
    if not settings.total_samples:
        data.pop('total_samples')  # Per-OK recipes keep the original Settings fields.
    if not settings.rois:
        data.pop('rois')
    if settings.export_vt_xml:
        data.pop('export_vt_xml')
    return data


def pixel_roi(size: tuple[int, int], roi) -> tuple[int, int, int, int]:
    w, h = size
    return (math.floor(roi[0]*w), math.floor(roi[1]*h),
            math.ceil(roi[2]*w), math.ceil(roi[3]*h))


def _feather(mask: Image.Image, radius: float) -> np.ndarray:
    hard = np.asarray(mask, dtype=np.float32) / 255
    if radius == 0:
        return hard
    # Padding prevents Pillow's edge extension from leaving hard rectangular seams.
    pad = math.ceil(radius * 3) + 2
    padded = Image.new("L", (mask.width+2*pad, mask.height+2*pad))
    padded.paste(mask, (pad, pad))
    blurred = padded.filter(ImageFilter.GaussianBlur(radius)).crop((pad, pad, pad+mask.width, pad+mask.height))
    soft = np.clip((np.asarray(blurred, dtype=np.float32)/255 - 0.5)*2, 0, 1)
    return soft * hard


def synthesize(base: Image.Image, asset: Asset, settings: Settings, seed: int):
    settings.validate()
    if settings.rois:
        order=list(enumerate(settings.rois));random.Random(seed).shuffle(order)
        last_error=None
        for index,region in order:
            try:
                output,mask,record=synthesize(base,asset,replace(settings,roi=tuple(region),rois=()),seed)
            except SynthesisError as exc:
                last_error=exc;continue
            record.update(allowed_rois_xyxy=[list(pixel_roi(base.size,r)) for r in settings.rois],selected_roi_index=index)
            return output,mask,record
        raise SynthesisError(f'所有允许范围均无法放置有效缺陷。最后原因：{last_error}')
    if base.mode not in ("L", "RGB") or asset.pixels.mode not in ("L", "RGB"):
        raise SynthesisError("底图和素材需要 8 位灰度 L 或每通道 8 位 RGB 图。")
    if base.mode != asset.pixels.mode:
        raise SynthesisError(f"OK 底图模式 {base.mode} 与 NG 素材模式 {asset.pixels.mode} 不一致。请使用相同颜色模式的 OK/NG 图，分批处理灰度与 RGB。")
    if asset.mask.mode != "L" or asset.pixels.size != asset.mask.size:
        raise SynthesisError("素材掩膜必须为 L 模式，且与素材尺寸匹配。")
    if not math.isfinite(asset.reference_gray) or not 1 <= asset.reference_gray <= 255:
        raise SynthesisError("素材背景灰度无效。")
    if asset.reference_rgb is not None and (asset.pixels.mode != "RGB" or len(asset.reference_rgb) != 3 or
            not all(math.isfinite(v) and 1 <= v <= 255 for v in asset.reference_rgb)):
        raise SynthesisError("素材 RGB 背景值无效。")
    rng = random.Random(seed)
    roi = pixel_roi(base.size, settings.roi)
    region_w, region_h = roi[2]-roi[0], roi[3]-roi[1]
    fit_found = False
    for _ in range(80):
        scale = rng.uniform(settings.scale_min, settings.scale_max)
        angle = rng.uniform(-settings.rotation, settings.rotation)
        strength = rng.uniform(settings.strength_min, settings.strength_max)
        w, h = max(1, round(asset.pixels.width*scale)), max(1, round(asset.pixels.height*scale))
        # Bound allocation before resizing an arbitrarily oversized donor.
        rad = math.radians(angle)
        projected_w = abs(w*math.cos(rad))+abs(h*math.sin(rad))
        projected_h = abs(w*math.sin(rad))+abs(h*math.cos(rad))
        if projected_w > region_w+2 or projected_h > region_h+2:
            continue
        ref = settings.reference_gray or asset.reference_gray
        rgb_ref = ((ref, ref, ref) if settings.reference_gray or asset.reference_rgb is None
                   else asset.reference_rgb) if base.mode == "RGB" else None
        reference = np.asarray(rgb_ref, dtype=np.float32) if rgb_ref is not None else max(1, ref)
        patch = asset.pixels.resize((w, h), Image.Resampling.BICUBIC)
        mask = asset.mask.resize((w, h), Image.Resampling.NEAREST)
        fill = tuple(round(v) for v in rgb_ref) if rgb_ref is not None else round(ref)
        patch = patch.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor=fill)
        mask = mask.rotate(angle, Image.Resampling.NEAREST, expand=True, fillcolor=0)
        if patch.width > region_w or patch.height > region_h:
            continue
        fit_found = True
        x = rng.randint(roi[0], roi[2]-patch.width)
        y = rng.randint(roi[1], roi[3]-patch.height)
        rect = (x, y, x+patch.width, y+patch.height)
        original = np.asarray(base.crop(rect), dtype=np.float32)
        donor = np.asarray(patch, dtype=np.float32)
        alpha = _feather(mask, settings.feather) * strength
        if base.mode == "RGB":
            alpha = alpha[..., None]
        if settings.mode == "darken":
            transferred = original * np.clip(donor/reference, 0, 1)
        else:
            transferred = donor
        result = np.rint(np.clip(original*(1-alpha)+transferred*alpha, 0, 255)).astype(np.uint8)
        changed = result != original.astype(np.uint8)
        if base.mode == "RGB":
            changed = np.any(changed, axis=2)
        if not changed.any():
            continue
        ys, xs = np.nonzero(changed)
        bbox = [x+int(xs.min()), y+int(ys.min()), x+int(xs.max())+1, y+int(ys.max())+1]
        output = base.copy()
        output.paste(Image.fromarray(result), (x, y))
        full_mask = Image.new("L", base.size)
        full_mask.paste(Image.fromarray(changed.astype(np.uint8)*255), (x, y))
        record = {
            "schema": SCHEMA, "tool_version": VERSION, "synthetic": True,
            "class_name": settings.class_name.strip(), "image_size": list(base.size),
            "image_mode": base.mode, "seed": seed, "mode": settings.mode,
            "scale": scale, "angle_degrees": angle, "strength": strength,
            "feather_px": settings.feather, "reference_gray": ref,
            "placement_xyxy": list(rect), "bbox_xyxy": bbox,
            "bbox_convention": "zero_based_half_open",
            "allowed_roi_xyxy": list(roi), "changed_pixel_count": int(changed.sum()),
            "mask_definition": "255 = pixel changed after 8-bit quantization; 0 = unchanged",
            "source_defect": asset.provenance,
        }
        if rgb_ref is not None:
            record["reference_rgb"] = list(rgb_ref)
        return output, full_mask, record
    if not fit_found:
        raise SynthesisError("素材放不进允许区域。请减小缩放上限/下限、缩小旋转范围，或扩大允许区域。")
    raise SynthesisError("未产生有效像素变化。请检查素材是否有缺陷，增大强度、减小羽化，或改用纹理粘贴。")


def _image_encode(im):
    buf = BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_decode(value, modes=("L", "RGB")):
    encoded_limit = 245_000_000 if "RGB" in modes else 85_000_000
    if not isinstance(value, str) or len(value) > encoded_limit:
        raise SynthesisError("素材数据无效或过大。")
    data = base64.b64decode(value, validate=True)
    with Image.open(BytesIO(data)) as im:
        if im.mode not in modes or 'transparency' in im.info or im.width*im.height > MAX_PIXELS:
            raise SynthesisError("素材必须为 L/RGB、掩膜必须为 L，且不透明、不超过 6000 万像素。")
        return im.copy()


def asset_dict(asset: Asset):
    data = {"pixels_png": _image_encode(asset.pixels), "mask_png": _image_encode(asset.mask),
            "reference_gray": asset.reference_gray, "provenance": asset.provenance}
    if asset.reference_rgb is not None:
        data["reference_rgb"] = list(asset.reference_rgb)
    return data


def asset_from_dict(data):
    pixels, mask = _image_decode(data["pixels_png"]), _image_decode(data["mask_png"], ("L",))
    ref = float(data["reference_gray"])
    if pixels.size != mask.size or not np.any(np.asarray(mask)) or not math.isfinite(ref) or not 1 <= ref <= 255:
        raise SynthesisError("素材掩膜或背景灰度无效。")
    if not isinstance(data.get("provenance"), dict):
        raise SynthesisError("素材来源信息无效。")
    rgb = data.get("reference_rgb")
    if rgb is not None:
        if (pixels.mode != "RGB" or not isinstance(rgb, list) or len(rgb) != 3 or
                not all(isinstance(v, (int, float)) and math.isfinite(v) and 1 <= v <= 255 for v in rgb)):
            raise SynthesisError("素材 RGB 背景值无效。")
        rgb = tuple(float(v) for v in rgb)
    return Asset(pixels, mask, ref, data["provenance"], rgb)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_recipe(path, asset, settings, ok_paths):
    settings.validate()
    write_json(path, {"schema": SCHEMA, "settings": settings_payload(settings),
                     "asset": asset_dict(asset), "ok_paths": [str(p) for p in ok_paths]})


def load_recipe(path):
    path = Path(path)
    if path.stat().st_size > MAX_RECIPE_BYTES:
        raise SynthesisError("配方文件过大。")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise SynthesisError("配方版本不支持。")
    settings = Settings(**data["settings"])
    settings.validate()
    paths = data.get("ok_paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise SynthesisError("配方中的底图列表无效。")
    return asset_from_dict(data["asset"]), settings, paths


def generate_batch(ok_paths: list[str], asset: Asset, settings: Settings,
                   output_root: str, progress: Callable | None = None,
                   cancelled: Callable | None = None) -> dict:
    settings.validate()
    if not ok_paths:
        raise SynthesisError("请先导入至少一张真实 OK 底图。")
    resolved = [Path(p).resolve() for p in ok_paths]
    if len(set(resolved)) != len(resolved):
        raise SynthesisError("底图列表包含重复文件，请移除重复项。")
    counts=generation_counts(len(resolved),settings)
    total=sum(counts)
    # Check source modes and fit before creating output, never substitute an NG image.
    for p,count in zip(resolved,counts):
        if not count:
            continue
        if cancelled and cancelled():
            return {"status": "cancelled", "completed": 0, "total": total, "run_dir": None}
        check = load_image(p)
        synthesize(check, asset, settings, settings.seed)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_file():
        raise SynthesisError("输出位置需要是文件夹。")
    run = root / ("run_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    run.mkdir(exist_ok=False)
    for name in ("images", "masks", "annotations"):
        (run/name).mkdir()
    asset.pixels.save(run/"defect_asset.png")
    asset.mask.save(run/"defect_asset_mask.png")
    save_recipe(run/"recipe.json", asset, settings, [str(p) for p in resolved])
    done = 0
    summary = {"schema": SCHEMA, "tool_version": VERSION, "status": "running", "completed": 0,
               "total": total, "run_dir": str(run), "synthetic": True,
               "quantity_mode":"total" if settings.total_samples else "per_ok",
               "planned_ok_counts":[{"source_ok":str(p),"count":n} for p,n in zip(resolved,counts)],
               "note": "Training supplements. Masks/JSON are generic, not VT proprietary annotations."}
    write_json(run/"summary.json", summary)
    try:
        with (run/"manifest.jsonl").open("w", encoding="utf-8") as manifest:
            for base_path,count in zip(resolved,counts):
                if not count:
                    continue
                base = load_image(base_path)
                for _ in range(count):
                    if cancelled and cancelled():
                        summary["status"] = "cancelled"
                        return summary
                    sample_seed = settings.seed + done
                    output, mask, record = synthesize(base, asset, settings, sample_seed)
                    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base_path.stem)[:80]
                    name = f"{safe_stem}_syn_{done+1:06d}"
                    record.update({"source_ok": str(base_path), "split_group": str(base_path),
                                   "image": f"images/{name}.bmp", "mask": f"masks/{name}.png",
                                   "annotation": f"annotations/{name}.json"})
                    output.save(run/record["image"], format="BMP")
                    mask.save(run/record["mask"], format="PNG")
                    if settings.export_vt_xml:
                        record['vt_xml']=f'images/{name}.xml'
                        record['vt_xml_profile']='visiontrain-2.2-flaw-rectangle'
                        write_vt_xml(run/record['vt_xml'],run/record['image'],record)
                    write_json(run/record["annotation"], record)
                    manifest.write(json.dumps(record, ensure_ascii=False)+"\n")
                    manifest.flush()
                    done += 1
                    summary["completed"] = done
                    if progress:
                        progress(done, total, name)
        summary["status"] = "complete"
        return summary
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        error = SynthesisError(f"批次生成失败，已完成 {done}/{total} 张。已完成数据保留于 {run}。原因：{exc}")
        error.run_dir, error.completed, error.total = str(run), done, total
        raise error from exc
    finally:
        summary["completed"] = done
        write_json(run/"summary.json", summary)
