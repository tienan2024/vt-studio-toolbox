"""Two explicit, locally saved presets per camera settings page."""
from copy import deepcopy
from dataclasses import asdict,replace
import json,os,tempfile
from pathlib import Path
from camera_model import CameraSettings,CameraError

PAGE_KEYS={
    'material':('kind','camera_model_id','sensor_width','sensor_height','pixel_pitch_um','focal_length_mm','optics_method','working_distance_mm','principal_plane_offset_mm','framing_source','precision_source','horizontal_margin_percent','vertical_margin_percent','target_width_mm','target_length_mm','image_horizontal_margin_mm','image_vertical_margin_mm'),
    'encoder':('auto_frequency','cycle_travel_mm','ppr','edge_factor','encoder_revs','height_override','cycle_idle_lines','pre_divider','multiplier','post_divider'),
    'trigger':('frame_line','frame_selector','line_source','encoder_line'),
    'io':('frame_edge','line_edge','input_format','a_debounce_ns','z_debounce_ns','output0_enabled','output0_line','output0_source','output4_enabled','output4_line','output4_source','output_mode','strobe_enable','strobe_duration_us'),
    'calibration':('optics_direction','fov_width_mm','fov_height_mm','x_mm_per_px','line_y_source','y_mm_per_px','calibration_length_mm','calibration_rows','encoder_travel_mm_per_rev','frequency_tolerance_percent','frequency_strategy','height_rounding'),
    'imaging':('device_name','products_per_minute','exposure_us','gain','compression','digital_shift','preamp_gain','pixel_format','reverse_x','black_level','width_override','centered_x','offset_x','offset_y','line_rate_override','limit_line_rate','require_square','square_tolerance_percent'),
}

def defaults():
    # Values explicitly recorded in the supplied MFS excerpt. Unknown site measurements stay untouched.
    values={
        'material':dict(kind='line',camera_model_id='MV-CL042-91GM',sensor_width=4096,sensor_height=2,pixel_pitch_um=7,focal_length_mm=25),
        'encoder':dict(auto_frequency=False,pre_divider=1,multiplier=3,post_divider=1,height_override=3200),
        'trigger':dict(frame_line='Line3',frame_selector='FrameBurstStart',line_source='FrequencyConverter',encoder_line='Line1'),
        'io':dict(frame_edge='RisingEdge',line_edge='FallingEdge',input_format='Differential',a_debounce_ns=300,z_debounce_ns=1000,output0_enabled=True,output0_line='Line0',output0_source='ExposureStartActive',output4_enabled=True,output4_line='Line4',output4_source='SoftTriggerActive',output_mode='Strobe',strobe_enable=True,strobe_duration_us=25000),
        'calibration':dict(frequency_tolerance_percent=15,frequency_strategy='cycle',height_rounding=100),
        'imaging':dict(width_override=3296,offset_x=500,centered_x=False,pixel_format='Mono8',reverse_x=False,exposure_us=19,gain=2.9079,preamp_gain='gain_1400x',digital_shift=-1,black_level=30,compression='HB',line_rate_override=30000,limit_line_rate=False),
    }
    return {page:[deepcopy(data),deepcopy(data)] for page,data in values.items()}

class CameraPresetStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VTStudioToolbox'/'camera-page-presets.json'
        self.data=defaults();self.load_error=''
        if self.path.is_file():
            try:
                if self.path.stat().st_size>1_000_000:raise CameraError('预设文件超过1MB。')
                raw=json.loads(self.path.read_text(encoding='utf-8'))
                if raw.get('schema')!='vt-camera-page-presets/1' or set(raw['pages'])!=set(PAGE_KEYS):raise CameraError('预设格式无效。')
                for page,slots in raw['pages'].items():
                    if not isinstance(slots,list) or len(slots)!=2:raise CameraError('每页必须有两个预设。')
                    for data in slots:self.validate(page,data)
                self.data=raw['pages']
            except Exception as exc:self.load_error=str(exc)

    @staticmethod
    def validate(page,data):
        if not isinstance(data,dict) or set(data)-set(PAGE_KEYS[page]):raise CameraError('预设包含其他页面字段。')
        unused=[f'Line{i}' for i in range(99,-1,-1) if f'Line{i}' not in data.values()]
        base=CameraSettings(frame_line=unused[0],encoder_line=unused[1],output0_enabled=False,output4_enabled=False)
        replace(base,**data).validate()

    def values(self,page,slot):return deepcopy(self.data[page][slot])

    def save(self,page,slot,settings):
        values=asdict(settings);data={k:values[k] for k in PAGE_KEYS[page]};self.validate(page,data)
        updated=deepcopy(self.data);updated[page][slot]=data
        self.path.parent.mkdir(parents=True,exist_ok=True);temporary=None
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.path.parent,delete=False,suffix='.tmp') as f:
                temporary=Path(f.name);json.dump({'schema':'vt-camera-page-presets/1','pages':updated},f,ensure_ascii=False,indent=2)
            os.replace(temporary,self.path);self.data=updated
        finally:
            if temporary and temporary.exists():temporary.unlink()
