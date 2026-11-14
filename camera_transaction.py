"""Selector-aware comparison, ordered writes, readback and honest rollback reporting."""
from contextlib import contextmanager
from dataclasses import replace
import math
from camera_model import (CameraError,calculate,settings_from_dict,node_id,fingerprint)
from camera_sdk import open_camera,NodeUnavailable


class CameraWriteError(CameraError):
    def __init__(self,message,report):super().__init__(message);self.report=report


def same(a,b):
    if isinstance(a,(float,int)) and not isinstance(a,bool) and isinstance(b,(float,int)):
        return math.isclose(a,b,rel_tol=1e-5,abs_tol=1e-6)
    return a==b


class Selectors:
    def __init__(self,camera):self.camera=camera;self.original={}
    def select(self,values):
        for key,value in values.items():
            cap=self.camera.read(key,'enum')
            if key not in self.original:self.original[key]=cap['value']
            if cap['value']!=value:self.camera.write(key,'enum',value)
    def restore(self):
        errors=[]
        for key,value in reversed(list(self.original.items())):
            try:
                if self.camera.read(key,'enum')['value']!=value:self.camera.write(key,'enum',value)
            except Exception as exc:errors.append(str(exc))
        if errors:raise CameraError('选择器恢复失败：'+'；'.join(errors))


@contextmanager
def selectors(camera):
    selected=Selectors(camera);primary=None
    try:yield selected
    except BaseException as exc:primary=exc;raise
    finally:
        try:selected.restore()
        except Exception as restore:
            if primary is None:raise
            primary.args=(str(primary)+'；'+str(restore),)
            if isinstance(primary,CameraWriteError):
                primary.report.setdefault('rollback_errors',[]).append(str(restore));primary.report['runtime_restored']=False


def _dependent(entry):
    return (bool(entry['selectors']) and entry['key']!='LineMode') or entry['key'] in ('ExposureMode','ExposureAuto','GainAuto','ExposureTime','Gain','DigitalShift','BlackLevel')


def validate_value(entry,cap,geometry):
    value=entry['value'];kind=cap['kind'];key=entry['key']
    if kind in ('int','float'):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise CameraError(key+'需要有限数值。')
        if kind=='int' and (int(value)!=value or (value-cap.get('min',0))%cap.get('inc',1)!=0):raise CameraError(key+'不符合整数/步长要求。')
        maximum=cap.get('max',math.inf)
        if key=='Width':maximum=max(maximum,geometry['sensor_width'])
        if key=='Height' and geometry.get('area'):maximum=max(maximum,geometry['sensor_height'])
        if not cap.get('min',-math.inf)<=value<=maximum:raise CameraError(key+'超出设备范围。')
    elif kind=='enum' and value not in cap['choices']:raise CameraError(key+'不支持枚举值 '+str(value))
    elif kind=='string' and len(value.encode('ascii'))>cap.get('max_length',0):raise CameraError(key+'超过设备名称长度。')
    elif kind=='bool' and type(value) is not bool:raise CameraError(key+'需要布尔值。')
    if not cap['writable'] and not same(cap['value'],value):raise CameraError(key+'当前只读。')


def observe_trigger_state(camera,frame_selector='FrameBurstStart',line=True):
    """Read extra timing state without guessing units or changing its settings."""
    frame={'TriggerSelector':frame_selector};line_context={'TriggerSelector':'LineStart'}
    entries=[('FrameTimeoutEnable','bool',{}),('FrameTimeoutTime','float',{}),
        ('PartialFrameDiscard','bool',{}),('AbandonExtraImage','bool',{}),
        ('BinningHorizontal','int',{}),('BinningVertical','int',{}),
        ('TriggerDelay','float',frame),('TriggerCacheEnable','bool',frame)]
    if line:entries += [('TDIMode','enum',{}),('LineDelayEnable','bool',frame),
        ('TriggerDelay','float',line_context),('LineTriggerCacheEnable','bool',line_context),
        ('TriggerLineRate','float',{}),('ResultingTriggerLineRate','float',{}),('ResultingLineRate','float',{})]
    result=[]
    with selectors(camera) as select:
        for key,kind,context in entries:
            row={'key':key,'kind':kind,'selectors':context,'value':None,'status':'未读取'}
            try:
                select.select(context);cap=camera.read(key,kind)
                row.update(kind=cap['kind'],value=cap['value'],status='已读取')
            except Exception as exc:row.update(status='不可读或不支持',detail=str(exc))
            result.append(row)
    return result


def _stable_observations(rows):
    live={'TriggerLineRate','ResultingTriggerLineRate','ResultingLineRate'}
    return [(node_id(r),r['value'],r['status']) for r in rows if r['key'] not in live]


def _verify_capacity(camera,settings):
    rows=observe_trigger_state(camera,settings.frame_selector,settings.kind=='line')
    values={r['key']:r['value'] for r in rows if r['status']=='已读取'}
    maximum=values.get('ResultingLineRate');external=values.get('ResultingTriggerLineRate')
    if settings.kind=='line' and isinstance(maximum,(int,float)) and maximum>0:
        expected=calculate(replace(settings,auto_frequency=False))['metrics']['required_line_rate_hz']
        required=max(expected,external if isinstance(external,(int,float)) and external>0 else 0)
        if required>maximum+1e-6:raise CameraError('目标成像设置允许的行频低于预计/已观测外部触发行频，请调整曝光、ROI或压缩并重新对比。')
    return rows


def compare(camera,settings):
    geometry=camera.geometry();geometry['area']=settings.kind=='area'
    plan=calculate(settings,geometry['limits']);errors=list(plan['blocking']);rows=[]
    if settings.kind=='line' and settings.auto_frequency and not plan['metrics']['frequency_pending'] and (not plan['metrics']['frequency_solution'] or not plan['metrics']['frequency_solution']['limits_verified']):
        errors.append('自动倍分频缺少设备的完整范围，请读取设备或核对节点支持。')
    if settings.sensor_width!=geometry['sensor_width']:errors.append('配置传感器宽度与设备不同，请先读取设备尺寸。')
    if settings.kind=='area' and settings.sensor_height!=geometry['sensor_height']:errors.append('配置传感器高度与设备不同，请先读取设备尺寸。')
    with selectors(camera) as select:
        for entry in plan['nodes']:
            row={'entry':entry,'before':None,'capability':None,'status':'待校验','error':''}
            try:
                select.select(entry['selectors']);cap=camera.read(entry['key'],entry['kind']);row['before']=cap['value'];row['capability']=cap
                if not cap['writable'] and not same(cap['value'],entry['value']) and _dependent(entry):
                    row['status']='依赖模式切换后校验'
                else:
                    validate_value(entry,cap,geometry);row['status']='保持' if same(cap['value'],entry['value']) else '修改'
            except NodeUnavailable as exc:
                if entry.get('optional') and exc.access==0:row['status']='设备无此可选功能'
                elif exc.access==1 and _dependent(entry):row['status']='依赖模式切换后校验'
                else:row['status']='不支持';row['error']=str(exc);errors.append(str(exc))
            except Exception as exc:row['status']='不支持';row['error']=str(exc);errors.append(str(exc))
            rows.append(row)
        persistence={}
        try:
            select.select({'UserSetSelector':'UserSet1'})
            camera.command_ready('UserSetSave');camera.command_ready('UserSetLoad')
            cap=camera.read('UserSetDefault','enum')
            validate_value({'key':'UserSetDefault','value':'UserSet1'},cap,geometry)
            persistence={'default':cap['value'],'user_set':'UserSet1','selector_before':select.original.get('UserSetSelector')}
        except Exception as exc:errors.append(str(exc))
    observed=observe_trigger_state(camera,settings.frame_selector,settings.kind=='line')
    return {'schema':'vt-camera-comparison/1','device':camera.device,'geometry':geometry,'plan':plan,'observed_trigger_state':observed,
            'settings_fingerprint':fingerprint(plan['settings']),'rows':rows,'errors':list(dict.fromkeys(errors)),
            'persistence':persistence,'ready':not errors}


def preview_camera(uid,settings,directory=None):
    with open_camera(uid,directory) as camera:return compare(camera,settings)


def inspect_camera(uid,directory=None):
    with open_camera(uid,directory) as camera:
        geometry=camera.geometry();line='area' not in geometry.get('scan_type','').lower()
        return {'device':camera.device,**geometry,'observed_trigger_state':observe_trigger_state(camera,line=line),
                'output_source_choices':read_output_sources(camera),'trigger_io_choices':read_trigger_ios(camera,line)}


def read_output_sources(camera):
    result={}
    try:lines=camera.read('LineSelector','enum')['choices']
    except CameraError:return result
    with selectors(camera) as select:
        for line in lines:
            try:
                select.select({'LineSelector':line});cap=camera.read('LineSource','enum')
                result[line]={'status':'readable','choices':cap['choices'],'value':cap['value'],'writable':cap['writable']}
            except CameraError as exc:result[line]={'status':'unavailable','detail':str(exc)}
    return result


def read_trigger_ios(camera,line):
    result={}
    with selectors(camera) as select:
        try:
            select.select({'TriggerSelector':'FrameBurstStart' if line else 'FrameStart'})
            cap=camera.read('TriggerSource','enum');result['frame_line']=[v for v in cap['choices'] if v.startswith('Line') and v[4:].isdigit()]
        except CameraError:pass
        if line:
            try:result['encoder_line']=camera.read('EncoderSourceA','enum')['choices']
            except CameraError:pass
    return result


def _ordered(rows):
    def priority(row):
        entry=row['entry'];key=entry['key']
        if key=='AcquisitionMode':return -10
        if key in ('GainAuto','DigitalShiftEnable','BlackLevelEnable'):return 0
        if key=='LineMode':return 1
        if key=='LineFormat':return 2
        if key=='TDIMode':return 2
        if key=='PixelFormat':return 3
        if key in ('Width','Height'):return 4
        if key in ('OffsetX','OffsetY'):return 5
        if key=='TriggerMode':return 70 if entry['selectors'].get('TriggerSelector')=='LineStart' else 100
        if key=='ExposureMode':return 80
        if key=='ExposureAuto':return 81
        if key=='ExposureTime':return 82
        return 10
    return sorted(rows,key=priority)


def apply_comparison(camera,preview,progress=None):
    notify=progress or (lambda message:None)
    if camera.device['uid']!=preview['device']['uid'] or not preview.get('ready'):raise CameraError('目标相机或参数对比无效，请重新读取。')
    settings=settings_from_dict(preview['plan']['settings'])
    current=compare(camera,settings)
    if not current['ready']:raise CameraError('相机当前状态不满足写入：'+'；'.join(current['errors']))
    if fingerprint(current['plan'])!=fingerprint(preview['plan']):raise CameraError('设备范围或计算计划已变化，请重新对比。')
    def stable_values(rows):
        return [(None if r['status']=='依赖模式切换后校验' else r['before'],r['status']) for r in rows]
    if stable_values(current['rows'])!=stable_values(preview['rows']):raise CameraError('相机参数在对比后已被修改，请重新对比。')
    if current['persistence']!=preview['persistence']:raise CameraError('用户集状态已变化，请重新对比。')
    if _stable_observations(current['observed_trigger_state'])!=_stable_observations(preview.get('observed_trigger_state',[])):
        raise CameraError('相机延时、缓存或超时状态已变化，请重新对比。')
    report={'schema':'vt-camera-write/1','device':camera.device,'status':'running','events':[],
            'persistent_may_have_changed':False,'runtime_restored':False,'settings':preview['plan']['settings'],
            'before':[],'persistence_before':current['persistence']}
    originals={};changed=[];persist_started=False
    # Snapshot every readable planned value before a mode/format setter can change
    # dependent nodes implicitly, even if its own SDK call then reports failure.
    for row in current['rows']:
        if row['capability'] is not None:
            entry=row['entry'];originals[node_id(entry)]=(entry,row['before'],row['capability']['kind'])
            report['before'].append({'node':entry,'value':row['before'],'kind':row['capability']['kind'],'phase':'before_write'})
    unknown_before=[r['entry']['key'] for r in current['rows'] if r['status']=='依赖模式切换后校验' and r['before'] is None]
    with selectors(camera) as select:
        def remember(entry,cap):
            ident=node_id(entry)
            if ident not in originals:
                originals[ident]=(entry,cap['value'],cap['kind'])
                report['before'].append({'node':entry,'value':cap['value'],'kind':cap['kind'],'phase':'after_mode_change'})
        def write(entry,value=None):
            select.select(entry['selectors']);cap=camera.read(entry['key'],entry['kind']);remember(entry,cap)
            desired=entry['value'] if value is None else value
            candidate=dict(entry,value=desired);validate_value(candidate,cap,current['geometry'])
            ident=node_id(entry)
            if not same(cap['value'],desired):
                # Include failed writes too: an SDK error may follow a partial device update.
                if ident not in changed:changed.append(ident)
                camera.write(entry['key'],cap['kind'],desired)
            after=camera.read(entry['key'],cap['kind'])['value']
            if not same(after,desired):raise CameraError(entry['key']+'写入后读回不一致。')
            report['events'].append({'node':entry,'value':desired,'verified':True})
        def verify_all():
            for row in current['rows']:
                if row['status']=='设备无此可选功能':continue
                entry=row['entry'];select.select(entry['selectors'])
                if not same(camera.read(entry['key'],entry['kind'])['value'],entry['value']):raise CameraError(entry['key']+'最终读回不一致。')
        try:
            notify('正在关闭触发并写入运行参数…')
            rows=[r for r in current['rows'] if r['status']!='设备无此可选功能']
            triggers=[r['entry'] for r in rows if r['entry']['key']=='TriggerMode']
            for entry in triggers:write(entry,'Off')
            for key in ('OffsetX','OffsetY'):
                row=next((r for r in rows if r['entry']['key']==key),None)
                if row:write(row['entry'],row['capability'].get('min',0))
            for row in _ordered(rows):write(row['entry'])
            verify_all();report['observed_before_save']=_verify_capacity(camera,settings);select.restore();select.original.clear()
            notify('运行参数已读回，正在保存 UserSet1…')
            camera.write('UserSetSelector','enum','UserSet1');persist_started=True;report['persistent_may_have_changed']=True
            camera.command('UserSetSave');camera.command('UserSetLoad');verify_all();report['observed_after_reload']=_verify_capacity(camera,settings)
            select.restore();select.original.clear()
            camera.write('UserSetDefault','enum','UserSet1')
            if camera.read('UserSetDefault','enum')['value']!='UserSet1':raise CameraError('默认用户集读回不一致。')
            report.update(status='passed',user_set='UserSet1',default_user_set='UserSet1',readback_verified=True)
            return report
        except Exception as exc:
            failures=[]
            # Restore using safe geometry order, then dependent nodes, then original triggers.
            if not persist_started:
                try:
                    for entry in [r['entry'] for r in current['rows'] if r['entry']['key']=='TriggerMode']:write(entry,'Off')
                    for key in ('OffsetX','OffsetY'):
                        saved=next((v for v in originals.values() if v[0]['key']==key),None)
                        if saved:
                            select.select(saved[0]['selectors']);minimum=camera.read(key,saved[2]).get('min',0);camera.write(key,saved[2],minimum)
                except Exception as error:failures.append(str(error))
                restore_rows=list(originals.values())
                def restore_priority(row):
                    key=row[0]['key']
                    if key=='TDIMode':return -1
                    if key=='PixelFormat':return 0
                    if key in ('Width','Height'):return 10
                    if key in ('OffsetX','OffsetY'):return 20
                    if key=='ExposureMode':return 30
                    if key=='ExposureAuto':return 31
                    if key=='ExposureTime':return 32
                    if key in ('LineMode','DigitalShiftEnable','BlackLevelEnable'):return 80
                    if key in ('ExposureAuto','GainAuto'):return 90
                    if key=='TriggerMode':return 100
                    return 30
                restore_rows.sort(key=restore_priority)
                for entry,value,kind in restore_rows:
                    try:
                        if settings.kind=='line' and entry['key'] in ('ExposureMode','ExposureAuto','ExposureTime'):
                            select.select({'TriggerSelector':'LineStart'})
                            if camera.read('TriggerMode','enum')['value']!='On':camera.write('TriggerMode','enum','On')
                        select.select(entry['selectors'])
                        if not same(camera.read(entry['key'],kind)['value'],value):camera.write(entry['key'],kind,value)
                        if not same(camera.read(entry['key'],kind)['value'],value):raise CameraError('恢复读回不一致：'+entry['key'])
                    except Exception as error:failures.append(str(error))
                if unknown_before:
                    failures.append('以下节点切换模式前不可读，无法核实原始值：'+', '.join(unknown_before))
                report['runtime_restored']=not failures
            report.update(status='failed',error=str(exc),rollback_errors=failures)
            message='写入失败：'+str(exc)
            if persist_started:message+='；用户集可能已改变，需检查相机状态。'
            elif failures:message+='；恢复未能全部核实，请检查执行记录。'
            else:message+='；运行参数已恢复，未执行用户集保存。'
            raise CameraWriteError(message,report) from exc


def write_camera(preview,directory=None,progress=None):
    with open_camera(preview['device']['uid'],directory,write=True) as camera:return apply_comparison(camera,preview,progress)
