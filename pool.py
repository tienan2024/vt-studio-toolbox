"""Seeded same-product donor pool; matching never relaxes color or ROI constraints."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import random
import re
import uuid
from vt_xml import write_vt_xml

from engine import (Asset, Settings, SynthesisError, VERSION, MAX_RECIPE_BYTES,
                    asset_dict, asset_from_dict, load_image, load_recipe,
                    synthesize, write_json, SCHEMA, generation_counts, settings_payload)

POOL_SCHEMA = 'vt-defect-pool/1'
MAX_POOL_ENTRIES = 200
MATCH_POLICY = 'same_mode_roi_fit_seeded'


@dataclass
class PoolEntry:
    entry_id: str
    name: str
    asset: Asset
    roi: tuple = (0.,0.,1.,1.)
    rois: tuple = ()


def validate_entries(entries):
    if not entries or len(entries) > MAX_POOL_ENTRIES:
        raise SynthesisError(f'素材池需要1～{MAX_POOL_ENTRIES}份已圈选NG素材。')
    seen=set()
    for entry in entries:
        if (not isinstance(entry.entry_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',entry.entry_id)
                or entry.entry_id in seen):
            raise SynthesisError('素材ID无效或重复。')
        seen.add(entry.entry_id)
        if not isinstance(entry.name,str) or not entry.name or len(entry.name)>300:
            raise SynthesisError('素材名称无效。')
        Settings(roi=entry.roi,rois=entry.rois).validate()


def pending_records(pending, entries):
    if not isinstance(pending,(list,tuple)) or len(pending)+len(entries)>MAX_POOL_ENTRIES:
        raise SynthesisError('素材池NG数量无效。')
    seen={entry.entry_id for entry in entries}
    records=[]
    for item in pending:
        if isinstance(item,str):
            item={'path':item,'id':uuid.uuid4().hex,'roi':[0.,0.,1.,1.]}
        if (not isinstance(item,dict) or not isinstance(item.get('path'),str) or
                not isinstance(item.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',item['id']) or item['id'] in seen):
            raise SynthesisError('未圈选NG状态无效。')
        Settings(roi=item.get('roi',()),rois=item.get('rois',())).validate()
        seen.add(item['id'])
        record={'path':item['path'],'id':item['id'],'roi':list(item['roi'])}
        if item.get('rois'):
            record['rois']=[list(r) for r in item['rois']]
        records.append(record)
    return records


def choose_sample(base, entries, settings, seed, cancelled=None):
    """Randomize donors, then use the first that generates a valid bounded sample."""
    settings.validate()
    validate_entries(entries)
    order=list(entries)
    random.Random(seed).shuffle(order)
    reasons=[]
    for entry in order:
        if cancelled and cancelled():
            raise InterruptedError('已取消素材匹配。')
        if entry.asset.pixels.mode != base.mode:
            reasons.append(f'{entry.name}: 颜色模式{entry.asset.pixels.mode}与OK的{base.mode}不一致')
            continue
        try:
            result=synthesize(base,entry.asset,replace(settings,roi=tuple(entry.roi),rois=entry.rois),seed)
        except SynthesisError as exc:
            reasons.append(f'{entry.name}: {exc}')
            continue
        result[2].update(pool_entry_id=entry.entry_id,pool_entry_name=entry.name,
                         matching_policy=MATCH_POLICY,source_roi_normalized=list(entry.roi))
        if entry.rois:
            result[2]['source_rois_normalized']=[list(r) for r in entry.rois]
        return result
    raise SynthesisError('当前OK没有可用NG素材（颜色/范围/尺寸或有效变化不匹配）。'+'；'.join(reasons[:5]))


def save_pool_recipe(path, entries, settings, ok_paths, pending_ng_paths=()):
    settings.validate()
    validate_entries(entries)
    pending=pending_records(pending_ng_paths,entries)
    data={'schema':POOL_SCHEMA,'tool_version':VERSION,'matching_policy':MATCH_POLICY,
          'settings':settings_payload(settings),'ok_paths':[str(p) for p in ok_paths],
          'pending_ng':pending,
          'entries':[{'id':e.entry_id,'name':e.name,'roi':list(e.roi),'asset':asset_dict(e.asset),
                      **({'rois':[list(r) for r in e.rois]} if e.rois else {})} for e in entries]}
    encoded=json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
    if len(encoded)>MAX_RECIPE_BYTES:
        raise SynthesisError('素材池配方超过340MB，请分池保存或缩小圈选素材。')
    Path(path).write_bytes(encoded)


def load_pool_recipe(path):
    path=Path(path)
    if path.stat().st_size>MAX_RECIPE_BYTES:
        raise SynthesisError('配方文件过大。')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')==SCHEMA:
        asset,settings,paths=load_recipe(path)
        name=Path(asset.provenance.get('source_ng','')).name or '旧配方素材'
        return [PoolEntry('legacy-0',name,asset,tuple(settings.roi),tuple(tuple(r) for r in settings.rois))],settings,paths,[]
    if data.get('schema')!=POOL_SCHEMA or data.get('matching_policy')!=MATCH_POLICY:
        raise SynthesisError('不支持的素材池配方或匹配策略。')
    raw=data.get('entries')
    if not isinstance(raw,list) or not 1<=len(raw)<=MAX_POOL_ENTRIES:
        raise SynthesisError('素材池条目数量无效。')
    settings=Settings(**data['settings']);settings.validate()
    paths=data.get('ok_paths',[])
    if not isinstance(paths,list) or not all(isinstance(p,str) for p in paths):
        raise SynthesisError('配方图像路径列表无效。')
    entries=[PoolEntry(e['id'],e['name'],asset_from_dict(e['asset']),tuple(e['roi']),tuple(tuple(r) for r in e.get('rois',()))) for e in raw]
    validate_entries(entries)
    pending=pending_records(data.get('pending_ng',[]),entries)
    return entries,settings,paths,pending


def generate_pool_batch(ok_paths, entries, settings, output_root, progress=None, cancelled=None):
    settings.validate();validate_entries(entries)
    resolved=[Path(p).resolve() for p in ok_paths]
    if not resolved or len(set(resolved))!=len(resolved):
        raise SynthesisError('请提供非空且不重复的OK底图列表。')
    counts=generation_counts(len(resolved),settings)
    total=sum(counts)
    # Refuse the whole job before creating output if even one OK has no match.
    for path,count in zip(resolved,counts):
        if not count:
            continue
        if cancelled and cancelled():
            return {'status':'cancelled','completed':0,'total':total,'run_dir':None}
        try:
            choose_sample(load_image(path),entries,settings,settings.seed,cancelled)
        except InterruptedError:
            return {'status':'cancelled','completed':0,'total':total,'run_dir':None}
        except SynthesisError as exc:
            raise SynthesisError(f'OK「{path.name}」匹配失败：{exc}') from exc
    root=Path(output_root).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    run=root/('run_'+datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    run.mkdir(exist_ok=False)
    for name in ('images','masks','annotations','assets'):
        (run/name).mkdir()
    summary={'schema':POOL_SCHEMA,'tool_version':VERSION,'status':'running','completed':0,'total':total,
             'run_dir':str(run),'synthetic':True,'matching_policy':MATCH_POLICY,
             'pool_entries':len(entries),'donor_usage':{e.entry_id:0 for e in entries}}
    summary.update(quantity_mode='total' if settings.total_samples else 'per_ok',
                   planned_ok_counts=[{'source_ok':str(p),'count':n} for p,n in zip(resolved,counts)])
    write_json(run/'summary.json',summary)
    done=0
    try:
        save_pool_recipe(run/'recipe.json',entries,settings,[str(p) for p in resolved])
        for entry in entries:
            entry.asset.pixels.save(run/'assets'/f'{entry.entry_id}.png')
            entry.asset.mask.save(run/'assets'/f'{entry.entry_id}_mask.png')
        with (run/'manifest.jsonl').open('w',encoding='utf-8') as manifest:
            for path,count in zip(resolved,counts):
                if not count:
                    continue
                base=load_image(path)
                for _ in range(count):
                    if cancelled and cancelled():
                        summary['status']='cancelled';return summary
                    try:
                        output,mask,record=choose_sample(base,entries,settings,settings.seed+done,cancelled)
                    except InterruptedError:
                        summary['status']='cancelled';return summary
                    stem=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',path.stem)[:80]
                    name=f'{stem}_syn_{done+1:06d}'
                    record.update(source_ok=str(path),split_group=str(path),image=f'images/{name}.bmp',
                                  mask=f'masks/{name}.png',annotation=f'annotations/{name}.json')
                    output.save(run/record['image'],format='BMP')
                    mask.save(run/record['mask'],format='PNG')
                    if settings.export_vt_xml:
                        record['vt_xml']=f'images/{name}.xml'
                        record['vt_xml_profile']='visiontrain-2.2-flaw-rectangle'
                        write_vt_xml(run/record['vt_xml'],run/record['image'],record)
                    write_json(run/record['annotation'],record)
                    manifest.write(json.dumps(record,ensure_ascii=False)+'\n');manifest.flush()
                    done+=1;summary['completed']=done
                    summary['donor_usage'][record['pool_entry_id']]+=1
                    if progress:
                        progress(done,total,name)
        summary['status']='complete';return summary
    except Exception as exc:
        summary.update(status='failed',error=str(exc))
        error=SynthesisError(f'素材池批次失败，已完成{done}/{total}张，已保留于{run}。原因：{exc}')
        error.run_dir,error.completed,error.total=str(run),done,total
        raise error from exc
    finally:
        write_json(run/'summary.json',summary)
