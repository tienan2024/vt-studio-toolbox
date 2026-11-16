"""Read-only device snapshots and raw page-preset comparison, independent of calculation."""
from datetime import datetime, timezone
import re
from camera_model import node_id
from camera_sdk import NodeUnavailable
from camera_presets import PAGE_KEYS
from camera_options import model_identity
from camera_transaction import selectors, same, validate_value

PAGE_NAMES=dict(zip(PAGE_KEYS,('材料与视野','编码器与图高','采集触发','数字 IO','专业标定','成像')))
PLAIN={'Width':'int','Height':'int','OffsetX':'int','OffsetY':'int','PixelFormat':'enum',
    'AcquisitionMode':'enum','ExposureMode':'enum','ExposureAuto':'enum','ExposureTime':'float',
    'GainAuto':'enum','Gain':'float','ReverseX':'bool','DigitalShiftEnable':'bool','DigitalShift':'int',
    'PreampGain':'enum','ImageCompressionMode':'enum','BlackLevelEnable':'bool','BlackLevel':'float',
    'DeviceUserID':'string','EncoderSourceA':'enum','EncoderSourceB':'enum','EncoderOutputMode':'enum',
    'EncoderCounterMode':'enum','InputSource':'enum','SignalAlignment':'enum','PreDivider':'int',
    'Multiplier':'int','PostDivider':'int','AcquisitionLineRateEnable':'bool','AcquisitionLineRate':'int','TDIMode':'enum'}
SIMPLE={'height_override':('Height','int'),'width_override':('Width','int'),'offset_x':('OffsetX','int'),
    'offset_y':('OffsetY','int'),'pixel_format':('PixelFormat','enum'),'exposure_us':('ExposureTime','float'),
    'gain':('Gain','float'),'reverse_x':('ReverseX','bool'),'digital_shift':('DigitalShift','int'),
    'preamp_gain':('PreampGain','enum'),'compression':('ImageCompressionMode','enum'),
    'black_level':('BlackLevel','float'),'device_name':('DeviceUserID','string'),
    'encoder_line':('EncoderSourceA','enum'),'pre_divider':('PreDivider','int'),
    'multiplier':('Multiplier','int'),'post_divider':('PostDivider','int'),
    'limit_line_rate':('AcquisitionLineRateEnable','bool'),'line_rate_override':('AcquisitionLineRate','int')}


def read_snapshot(camera,geometry):
    entries=[{'key':k,'kind':v,'selectors':{}} for k,v in PLAIN.items()]
    selector_caps={}
    # Enumerate selector banks, without changing TriggerMode, LineMode or exposure modes.
    for selector,fields in (
        ('TriggerSelector',{'TriggerMode':'enum','TriggerSource':'enum','TriggerActivation':'enum','ExposureMode':'enum','AcquisitionBurstFrameCount':'int'}),
        ('LineSelector',{'LineMode':'enum','LineFormat':'enum','LineSource':'enum','LineDebouncerTimeNs':'int','StrobeEnable':'bool','StrobeLineDuration':'int'})):
        try:
            choices=camera.read(selector,'enum')['choices'];selector_caps[selector]={'status':'已读取','choices':choices,'detail':''}
        except NodeUnavailable as exc:
            choices=[];selector_caps[selector]={'status':'设备不支持' if exc.access==0 else '当前条件不可读','detail':str(exc)}
        except Exception as exc:
            choices=[];selector_caps[selector]={'status':'读取失败','detail':str(exc)}
        if selector=='TriggerSelector':choices=[v for v in choices if v in ('FrameBurstStart','FrameStart','LineStart')]
        else:choices=[v for v in choices if re.fullmatch(r'Line\d+',v)]
        for choice in choices:
            entries.extend({'key':k,'kind':v,'selectors':{selector:choice}} for k,v in fields.items())
    rows=[]
    with selectors(camera) as select:
        for entry in entries:
            row={'entry':entry,'value':None,'capability':None,'status':'未读取','detail':''}
            try:
                select.select(entry['selectors']);cap=camera.read(entry['key'],entry['kind'])
                row.update(value=cap['value'],capability=cap,status='已读取')
            except NodeUnavailable as exc:
                row.update(status='设备不支持' if exc.access==0 else '当前条件不可读',detail=str(exc))
            except Exception as exc:row.update(status='读取失败',detail=str(exc))
            rows.append(row)
    return {'schema':'vt-camera-snapshot/1','device':dict(camera.device),
        'read_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'geometry':geometry,'rows':rows,'selector_capabilities':selector_caps}


def preset_entries(field,value,data):
    """Map only explicit stored values. None denotes a site/computed field; [] a skipped field."""
    def entry(key,kind,context=None):return {'key':key,'kind':kind,'selectors':context or {},'value':value}
    frame={'TriggerSelector':data.get('frame_selector')};line={'TriggerSelector':'LineStart'}
    if field in ('frame_line','frame_edge'):return [entry('TriggerSource' if field=='frame_line' else 'TriggerActivation','enum',frame)]
    if field=='line_source':return [entry('TriggerSource','enum',line)]
    if field=='line_edge':
        result=[entry('TriggerActivation','enum',line)]
        if data.get('line_source')=='FrequencyConverter':result.append(entry('SignalAlignment','enum'))
        return result
    if field in ('input_format','a_debounce_ns','z_debounce_ns'):
        lines=[data.get('frame_line'),data.get('encoder_line')] if field=='input_format' else [data.get('encoder_line' if field=='a_debounce_ns' else 'frame_line')]
        return [entry('LineFormat' if field=='input_format' else 'LineDebouncerTimeNs','enum' if field=='input_format' else 'int',{'LineSelector':v}) for v in dict.fromkeys(lines)]
    if field in ('output0_source','output4_source','output_mode','strobe_enable','strobe_duration_us'):
        prefixes=('output0','output4') if field in ('output_mode','strobe_enable') else ('output4',) if field in ('output4_source','strobe_duration_us') else ('output0',)
        key,kind=('LineMode','enum') if field=='output_mode' else ('StrobeEnable','bool') if field=='strobe_enable' else ('StrobeLineDuration','int') if field=='strobe_duration_us' else ('LineSource','enum')
        return [entry(key,kind,{'LineSelector':data.get(p+'_line')}) for p in prefixes if data.get(p+'_enabled') is True]
    if field in SIMPLE:
        if field in ('height_override','width_override','line_rate_override') and value==0:return []
        if field in ('digital_shift','black_level') and value<0:return []
        if field=='offset_x' and data.get('centered_x') is True:return []
        if field in ('pre_divider','multiplier','post_divider') and data.get('auto_frequency') is True:return []
        if field=='line_rate_override' and data.get('limit_line_rate') is not True:return []
        if value=='':return []
        return [entry(*SIMPLE[field])]
    return None


def compare_presets(snapshot,pages):
    """pages maps page -> {slot: 0|1, values: original stored dict}. Never fill from draft."""
    stored={k:v for spec in pages.values() for k,v in spec['values'].items()}
    actual={node_id(r['entry']):r for r in snapshot.get('rows',[])} if snapshot else {}
    rows=[]
    for page,spec in pages.items():
        for field in PAGE_KEYS[page]:
            row={'page':page,'slot':spec['slot'],'field':field,'entry':None,'before':None,
                'value':spec['values'].get(field),'status':'预设未设置','detail':''}
            if snapshot and spec.get('model') and model_identity(spec['model'])!=model_identity(snapshot['device'].get('model')):
                row.update(status='预设机型不匹配',detail='预设属于 '+spec['model']+'，设备为 '+str(snapshot['device'].get('model')))
                rows.append(row);continue
            if field not in spec['values']:rows.append(row);continue
            value=row['value'];entries=preset_entries(field,value,stored)
            if entries is None:
                # Intrinsic sensor information is readable; physical/site values are not camera nodes.
                if field in ('kind','camera_model_id','sensor_width','sensor_height'):
                    if not snapshot:row['status']='未读取'
                    else:
                        scan=snapshot['geometry'].get('scan_type','').lower()
                        observed=('line' if 'line' in scan else 'area' if 'area' in scan else None) if field=='kind' else snapshot['device'].get('model') if field=='camera_model_id' else snapshot['geometry'].get(field)
                        row.update(before=observed,status=('一致' if same(observed,value) else '不同') if observed is not None else '读取失败')
                else:row['status']='工位计算项'
                rows.append(row);continue
            if not entries:row['status']='计算或未启用';rows.append(row);continue
            for entry in entries:
                r=dict(row,entry=entry)
                if any(v is None for v in entry['selectors'].values()):r.update(status='预设未设置',detail='缺少选择器/接线预设，未从当前编辑值补齐。')
                elif not snapshot:r['status']='未读取'
                else:
                    read=actual.get(node_id(entry))
                    if not read:
                        unavailable=next((snapshot.get('selector_capabilities',{}).get(k) for k in entry['selectors']
                            if snapshot.get('selector_capabilities',{}).get(k,{}).get('status') not in (None,'已读取')),None)
                        if unavailable:r.update(status=unavailable['status'],detail=unavailable['detail'])
                        else:r['status']='设备不支持'
                    elif read['status']!='已读取':r.update(status=read['status'],detail=read['detail'])
                    else:
                        r['before']=read['value'];cap=dict(read['capability'],writable=True)
                        try:
                            validate_value(entry,cap,snapshot['geometry'])
                            r['status']='一致' if same(r['before'],value) else '不同'
                        except Exception as exc:r.update(status='预设超范围',detail=str(exc))
                rows.append(r)
    return rows
