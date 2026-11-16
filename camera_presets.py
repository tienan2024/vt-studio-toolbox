"""Two named presets per page and complete camera model; no cross-model fallback."""
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime
import json,os,tempfile
from pathlib import Path
from camera_model import CameraSettings,CameraError
from camera_options import model_identity,model_preset

SCHEMA='vt-camera-page-presets/2'

PAGE_KEYS={
    'material':('kind','camera_model_id','sensor_width','sensor_height','pixel_pitch_um','focal_length_mm','optics_method','working_distance_mm','principal_plane_offset_mm','framing_source','precision_source','horizontal_margin_percent','vertical_margin_percent','target_width_mm','target_length_mm','image_horizontal_margin_mm','image_vertical_margin_mm'),
    'encoder':('auto_frequency','cycle_travel_mm','ppr','edge_factor','encoder_revs','height_override','cycle_idle_lines','pre_divider','multiplier','post_divider'),
    'trigger':('frame_line','frame_selector','line_source','encoder_line'),
    'io':('frame_edge','line_edge','input_format','a_debounce_ns','z_debounce_ns','output0_enabled','output0_line','output0_source','output4_enabled','output4_line','output4_source','output_mode','strobe_enable','strobe_duration_us'),
    'calibration':('optics_direction','fov_width_mm','fov_height_mm','x_mm_per_px','line_y_source','y_mm_per_px','calibration_length_mm','calibration_rows','encoder_travel_mm_per_rev','frequency_tolerance_percent','frequency_strategy','height_rounding'),
    'imaging':('device_name','products_per_minute','exposure_us','gain','compression','digital_shift','preamp_gain','pixel_format','reverse_x','black_level','width_override','centered_x','offset_x','offset_y','line_rate_override','limit_line_rate','require_square','square_tolerance_percent'),
}

def model_name(model):
    preset=model_preset(model)
    return preset['model'] if preset else ' '.join(str(model or '').split())


def model_key(model):return model_identity(model) or 'custom'


def defaults(model):
    """Adapt shared wiring, but only the actual CL042 mono owns its MFS image values."""
    preset=model_preset(model)
    if not preset:return {page:[{'name':name,'values':{}} for name in ('基础配置','备用配置')] for page in PAGE_KEYS}
    line=preset['kind']=='line'
    values={
        'material':{key:preset[key] for key in ('kind','sensor_width','sensor_height','pixel_pitch_um','focal_length_mm')},
        'encoder':dict(auto_frequency=True,height_override=0,pre_divider=1,multiplier=1,post_divider=1) if line else {},
        'trigger':dict(frame_line='Line3',frame_selector='FrameBurstStart',line_source='FrequencyConverter',encoder_line='Line1') if line else dict(frame_line='Line0',frame_selector='FrameStart'),
        'io':dict(frame_edge='RisingEdge',line_edge='FallingEdge',input_format='Differential',a_debounce_ns=300,z_debounce_ns=1000,output0_enabled=True,output0_line='Line0',output0_source='ExposureStartActive',output4_enabled=True,output4_line='Line4',output4_source='SoftTriggerActive',output_mode='Strobe',strobe_enable=True,strobe_duration_us=25000),
        'calibration':dict(frequency_tolerance_percent=15,frequency_strategy='cycle',height_rounding=100),
        'imaging':dict(width_override=0,offset_x=0,offset_y=0,centered_x=True,pixel_format='' if preset['color'] else 'Mono8',reverse_x=False,exposure_us=19,gain=0,preamp_gain='',digital_shift=-1,black_level=-1,compression='',line_rate_override=0,limit_line_rate=False),
    }
    values['material']['camera_model_id']=preset['model']
    if not line:
        values['io']=dict(frame_edge='RisingEdge',input_format='',z_debounce_ns=1000,output0_enabled=False,output4_enabled=False)
        values['calibration']={}
    if preset['model']=='MV-CL042-91GM':
        values['encoder']=dict(auto_frequency=False,pre_divider=1,multiplier=3,post_divider=1,height_override=3200)
        values['imaging']=dict(width_override=3296,offset_x=500,centered_x=False,pixel_format='Mono8',reverse_x=False,exposure_us=19,gain=2.9079,preamp_gain='gain_1400x',digital_shift=-1,black_level=30,compression='HB',line_rate_override=30000,limit_line_rate=False)
    names=('参考工位配置','备用配置') if preset['model']=='MV-CL042-91GM' else ('基础配置','备用配置')
    return {page:[{'name':name,'values':deepcopy(data)} for name in names] for page,data in values.items()}

class CameraPresetStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VTStudioToolbox'/'camera-page-presets.json'
        self.data={};self.legacy_pages=None;self.load_error='';self.load_notice='';self._backup_needed=False
        if self.path.is_file():
            try:
                if self.path.stat().st_size>1_000_000:raise CameraError('预设文件超过1MB。')
                raw=json.loads(self.path.read_text(encoding='utf-8'))
                if raw.get('schema')=='vt-camera-page-presets/1':
                    self.validate_legacy(raw['pages']);self.legacy_pages=raw['pages'];self._backup_needed=True
                    self.load_notice='旧版通用预设已保留，未混入各机型预设；保存时会另留原文件备份。'
                elif raw.get('schema')==SCHEMA:
                    if not isinstance(raw.get('models'),dict):raise CameraError('机型预设格式无效。')
                    for key,record in raw['models'].items():
                        if not isinstance(record,dict) or key!=model_key(record['model']):raise CameraError('预设所属机型无效。')
                        if set(record['pages'])!=set(PAGE_KEYS):raise CameraError('预设页面不完整。')
                        for page,slots in record['pages'].items():
                            if not isinstance(slots,list) or len(slots)!=2:raise CameraError('每个机型的每页必须有两个预设。')
                            for slot in slots:self.validate_name(slot['name']);self.validate(page,slot['values'],record['model'])
                    if raw.get('legacy_pages') is not None:self.validate_legacy(raw['legacy_pages'])
                    self.data=raw['models'];self.legacy_pages=raw.get('legacy_pages')
                else:raise CameraError('预设格式无效。')
            except Exception as exc:self.load_error=str(exc);self._backup_needed=True

    @staticmethod
    def validate(page,data,model=None):
        if not isinstance(data,dict) or set(data)-set(PAGE_KEYS[page]):raise CameraError('预设包含其他页面字段。')
        if model is not None:
            if 'camera_model_id' in data and model_key(data['camera_model_id'])!=model_key(model):raise CameraError('预设内容与所属机型不一致。')
            preset=model_preset(model)
            if preset:
                for key in ('kind','sensor_width','sensor_height','pixel_pitch_um','focal_length_mm'):
                    if key in data and data[key]!=preset[key]:raise CameraError('预设硬件参数与所属机型不一致：'+key)
                if data.get('width_override',0)+data.get('offset_x',0)>preset['sensor_width']:raise CameraError('预设ROI超出所属机型宽度。')
        unused=[f'Line{i}' for i in range(99,-1,-1) if f'Line{i}' not in data.values()]
        base=CameraSettings(frame_line=unused[0],encoder_line=unused[1],output0_enabled=False,output4_enabled=False,frequency_strategy='cycle')
        replace(base,**data).validate()

    @classmethod
    def validate_legacy(cls,pages):
        if not isinstance(pages,dict) or set(pages)!=set(PAGE_KEYS):raise CameraError('旧预设页面无效。')
        for page,slots in pages.items():
            if not isinstance(slots,list) or len(slots)!=2:raise CameraError('旧预设数量无效。')
            for data in slots:cls.validate(page,data)

    @staticmethod
    def validate_name(name):
        if not isinstance(name,str) or not name.strip() or len(name)>40 or any(ord(c)<32 for c in name):raise CameraError('预设名称需为1～40个可见字符。')

    def _record(self,model):
        key=model_key(model)
        if key not in self.data:self.data[key]={'model':model_name(model),'pages':defaults(model)}
        return self.data[key]

    def values(self,page,slot,model):return deepcopy(self._record(model)['pages'][page][slot]['values'])

    def name(self,page,slot,model):return self._record(model)['pages'][page][slot]['name']

    def label(self,page,slot,model):return (model_name(model) or '自定义机型')+' · '+self.name(page,slot,model)

    def save(self,page,slot,settings,model):
        if model_key(settings.camera_model_id)!=model_key(model):raise CameraError('当前设置与预设所属机型不同，不能保存。')
        values=asdict(settings);data={k:values[k] for k in PAGE_KEYS[page]};self.validate(page,data,model)
        self._record(model);updated=deepcopy(self.data);updated[model_key(model)]['pages'][page][slot]['values']=data
        self._persist(updated)

    def rename(self,page,slot,model,name):
        self.validate_name(name);self._record(model);updated=deepcopy(self.data)
        updated[model_key(model)]['pages'][page][slot]['name']=name.strip();self._persist(updated)

    def _persist(self,updated):
        payload=json.dumps({'schema':SCHEMA,'models':updated,'legacy_pages':self.legacy_pages},ensure_ascii=False,indent=2)
        if len(payload.encode('utf-8'))>1_000_000:raise CameraError('预设总量超过1MB，未覆盖原文件。')
        self.path.parent.mkdir(parents=True,exist_ok=True);temporary=None
        if self._backup_needed and self.path.exists():
            backup=self.path.with_name(self.path.stem+'.legacy-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
            with backup.open('xb') as f:f.write(self.path.read_bytes())
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.path.parent,delete=False,suffix='.tmp') as f:
                temporary=Path(f.name);f.write(payload)
            os.replace(temporary,self.path);self.data=updated;self._backup_needed=False
        finally:
            if temporary and temporary.exists():temporary.unlink()
