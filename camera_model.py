"""Physical calculation and typed, selector-aware camera plans; no SDK dependency."""
from dataclasses import dataclass,asdict,fields,replace
import hashlib
import json
import math
import re

SCHEMA='vt-camera-config/2'


class CameraError(ValueError):pass


@dataclass
class CameraSettings:
    kind:str='line'
    camera_model_id:str=''
    optics_method:str='quick'
    principal_plane_offset_mm:float=0
    auto_frequency:bool=False
    encoder_travel_mm_per_rev:float=0
    frequency_tolerance_percent:float=1
    framing_source:str='legacy'
    horizontal_margin_percent:float=10
    vertical_margin_percent:float=-1
    frequency_strategy:str='pitch'
    height_rounding:int=100
    cycle_idle_lines:int=100
    cycle_travel_mm:float=0
    working_distance_mm:float=400
    sensor_width:int=4096
    sensor_height:int=2048
    precision_source:str='fov'
    optics_direction:str='wd_to_precision'
    focal_length_mm:float=0
    pixel_pitch_um:float=0
    fov_width_mm:float=400
    fov_height_mm:float=200
    x_mm_per_px:float=.1
    y_mm_per_px:float=.1
    line_y_source:str='precision'
    calibration_length_mm:float=300
    calibration_rows:int=3000
    target_width_mm:float=320
    target_length_mm:float=300
    image_horizontal_margin_mm:float=0
    image_vertical_margin_mm:float=0
    ppr:int=1000
    edge_factor:int=1
    encoder_revs:float=1
    pre_divider:int=1
    multiplier:int=3
    post_divider:int=1
    products_per_minute:float=800
    rate_margin_percent:float=12.5
    line_rate_override:float=0
    limit_line_rate:bool=False
    width_override:int=0
    height_override:int=0
    centered_x:bool=True
    offset_x:int=0
    offset_y:int=0
    require_square:bool=False
    square_tolerance_percent:float=2
    frame_selector:str='FrameBurstStart'
    frame_line:str='Line3'
    frame_edge:str='RisingEdge'
    encoder_line:str='Line1'
    line_source:str='FrequencyConverter'
    line_edge:str='FallingEdge'
    input_format:str='Differential'
    a_debounce_ns:int=300
    z_debounce_ns:int=1000
    output0_enabled:bool=True
    output0_line:str='Line0'
    output0_source:str='ExposureStartActive'
    output4_enabled:bool=False
    output4_line:str='Line4'
    output4_source:str='SoftTriggerActive'
    output_mode:str='Strobe'
    strobe_enable:bool=True
    strobe_duration_us:int=25000
    exposure_us:float=19
    gain:float=2.9079
    digital_shift:int=-1
    preamp_gain:str=''
    compression:str=''
    pixel_format:str='Mono8'
    reverse_x:bool=False
    black_level:float=-1
    device_name:str=''

    def validate(self):
        for field in fields(self):
            value=getattr(self,field.name)
            if field.type is bool:
                if type(value) is not bool:raise CameraError(field.name+' 必须为布尔值。')
            elif field.type is int:
                if type(value) is not int or abs(value)>2_147_483_647:raise CameraError(field.name+' 必须为32位整数。')
            elif field.type is float:
                if type(value) not in (int,float) or not math.isfinite(value):raise CameraError(field.name+' 必须为有限数值。')
            elif not isinstance(value,str) or len(value)>128 or any(ord(c)<32 for c in value):raise CameraError(field.name+' 文字无效。')
        if self.kind not in ('line','area') or self.precision_source not in ('fov','precision','optics') or self.line_y_source not in ('precision','calibration','square','legacy'):raise CameraError('相机类型或精度来源无效。')
        for name in ('working_distance_mm','sensor_width','sensor_height','target_width_mm','target_length_mm',
                     'fov_width_mm','fov_height_mm','x_mm_per_px','y_mm_per_px','calibration_length_mm','calibration_rows','ppr','encoder_revs',
                     'pre_divider','multiplier','post_divider','products_per_minute','exposure_us'):
            if getattr(self,name)<=0:raise CameraError(name+' 必须大于0。')
        if self.edge_factor not in (1,2,4):raise CameraError('计数倍率应为1、2或4，以相机实际计数为准。')
        if self.kind=='line' and not self.auto_frequency and any(not 1<=getattr(self,k)<=5 for k in ('pre_divider','multiplier','post_divider')):
            raise CameraError('预分频、倍频、后分频必须分别在1～5以内。')
        if self.optics_direction not in ('wd_to_precision','precision_to_wd'):raise CameraError('工作距离与精度的计算方向无效。')
        if self.optics_method not in ('quick','thin_lens'):raise CameraError('光学计算模式无效。')
        if self.framing_source not in ('legacy','material','distance') or self.frequency_strategy not in ('pitch','cycle'):raise CameraError('视野或倍分频计算方式无效。')
        margin_valid=(self.horizontal_margin_percent>=-100 if self.framing_source=='distance' else
                      self.horizontal_margin_percent>-100 if self.framing_source=='material' else 0<=self.horizontal_margin_percent<=1000)
        if not margin_valid or self.height_rounding<1 or self.cycle_idle_lines<0 or self.cycle_travel_mm<0:raise CameraError('余量、图高步长或周期参数无效。')
        if self.vertical_margin_percent!=-1 and not 0<=self.vertical_margin_percent<=1000:raise CameraError('纵向余量应在0～1000%，旧配置兼容值为-1。')
        if self.kind=='line' and self.frequency_strategy=='cycle' and self.cycle_idle_lines<1:raise CameraError('周期方案必须预留至少1行的采集空档。')
        if self.framing_source!='legacy' and (self.pixel_pitch_um<=0 or self.focal_length_mm<=0):raise CameraError('视野计算需要有效的像元尺寸和焦距。')
        if self.kind=='line' and self.line_source=='FrequencyConverter' and self.auto_frequency and self.frequency_strategy=='pitch' and self.encoder_travel_mm_per_rev<=0:raise CameraError('按走料精度计算倍分频需要填写编码器每圈对应的实际走料长度。')
        if not 0<=self.frequency_tolerance_percent<=100:raise CameraError('采样误差容差应在0～100%。')
        inverse=self.framing_source=='material' or (self.framing_source=='legacy' and self.optics_direction=='precision_to_wd')
        optical_wd=self.x_mm_per_px*self.focal_length_mm/(self.pixel_pitch_um/1000) if self.pixel_pitch_um>0 and inverse else self.working_distance_mm
        if self.framing_source=='material':optical_wd=_material_pitch(self)*self.focal_length_mm/(self.pixel_pitch_um/1000)
        if self.optics_method=='thin_lens':
            optical_wd=optical_wd+self.focal_length_mm if inverse else optical_wd+self.principal_plane_offset_mm
            if (self.precision_source=='optics' or self.framing_source!='legacy') and inverse and optical_wd-self.principal_plane_offset_mm<=0:raise CameraError('反算工作距离必须大于0，请核对主平面偏移。')
        if (self.precision_source=='optics' or self.framing_source!='legacy') and (self.focal_length_mm<=0 or self.pixel_pitch_um<=0 or optical_wd<=self.focal_length_mm):
            raise CameraError('镜头估算需填写焦距、像元尺寸，且工作距离应大于焦距；实际精度请用实测视野校准。')
        if not 0<=self.rate_margin_percent<=100 or not 0<=self.square_tolerance_percent<=100:raise CameraError('余量/精度容差应在0～100%。')
        for name in ('width_override','height_override','offset_x','offset_y','a_debounce_ns','z_debounce_ns','strobe_duration_us','line_rate_override','gain','image_horizontal_margin_mm','image_vertical_margin_mm','focal_length_mm','pixel_pitch_um'):
            if getattr(self,name)<0:raise CameraError(name+' 不能为负数。')
        if self.digital_shift < -1 or self.black_level < -1:raise CameraError('未设置增益/黑电平用-1，设置值不能为负。')
        if self.frame_selector not in ('FrameStart','FrameBurstStart') or self.frame_edge not in ('RisingEdge','FallingEdge') or self.line_edge not in ('RisingEdge','FallingEdge'):raise CameraError('触发选择器或边沿无效。')
        line_input=self.encoder_line if self.line_source in ('FrequencyConverter','EncoderModuleOut') else self.line_source if re.fullmatch(r'Line\d+',self.line_source) else None
        if not self.line_source or len(self.line_source)>128:raise CameraError('行触发源不能为空或过长。')
        used=[self.frame_line]+([line_input] if self.kind=='line' and line_input else [])
        if self.output0_enabled:used.append(self.output0_line)
        if self.output4_enabled:used.append(self.output4_line)
        if any(not re.fullmatch(r'Line\d{1,2}',line) for line in used) or len(used)!=len(set(used)):raise CameraError('帧、编码器和输出IO须使用不同的有效Line。')
        if self.device_name and (not self.device_name.isascii() or not all(32<=ord(c)<127 for c in self.device_name)):raise CameraError('DeviceUserID使用可打印ASCII名称，字节长度以设备读回为准。')
        return self


def config_dict(settings):return {'schema':SCHEMA,**asdict(settings)}


def workflow_settings():
    """Operator example; physical motion calibration is deliberately unspecified."""
    return CameraSettings(camera_model_id='MV-CL024-91GC',sensor_width=2048,sensor_height=3,
        focal_length_mm=12,pixel_pitch_um=7,precision_source='optics',
        framing_source='material',horizontal_margin_percent=10,vertical_margin_percent=2,target_width_mm=200,target_length_mm=400,
        frequency_strategy='cycle',auto_frequency=True,line_y_source='square',height_rounding=100,
        cycle_idle_lines=100,ppr=1000,edge_factor=1,encoder_revs=1,pixel_format='',products_per_minute=300,frequency_tolerance_percent=15)


def settings_from_dict(value):
    if not isinstance(value,dict) or value.get('schema') not in (SCHEMA,'vt-camera-config/1'):raise CameraError('相机配置格式应为'+SCHEMA)
    allowed={f.name for f in fields(CameraSettings)}
    if value['schema']=='vt-camera-config/1':
        legacy={'product_pitch_mm','image_top_margin_mm','image_bottom_margin_mm','allow_overheight'}
        added={'line_source','line_y_source','calibration_length_mm','calibration_rows','image_horizontal_margin_mm','image_vertical_margin_mm','optics_direction','camera_model_id','optics_method','principal_plane_offset_mm','auto_frequency','encoder_travel_mm_per_rev','frequency_tolerance_percent','framing_source','horizontal_margin_percent','vertical_margin_percent','frequency_strategy','height_rounding','cycle_idle_lines','cycle_travel_mm'}
        if set(value)-(allowed-added)-legacy-{'schema'}:raise CameraError('旧相机配置含未知字段。')
        def old_number(key,default,positive=False):
            number=value.get(key,default)
            if type(number) not in (int,float) or not math.isfinite(number) or (number<=0 if positive else number<0):raise CameraError('旧相机配置的'+key+'数值无效。')
            return number
        migrated={k:v for k,v in value.items() if k in allowed}
        migrated['image_vertical_margin_mm']=old_number('image_top_margin_mm',0)+old_number('image_bottom_margin_mm',0)
        settings=CameraSettings(**migrated).validate()
        if settings.kind=='line':
            cycle=settings.ppr*settings.edge_factor*settings.encoder_revs*settings.multiplier/(settings.pre_divider*settings.post_divider)
            settings.y_mm_per_px=old_number('product_pitch_mm',300,True)/cycle
            settings.line_y_source='legacy'
        return settings.validate()
    if set(value)-allowed-{'schema'}:raise CameraError('相机配置含未知字段。')
    return CameraSettings(**{k:v for k,v in value.items() if k in allowed}).validate()


def node(key,kind,value,selectors=None):
    return {'key':key,'kind':kind,'value':value,'selectors':selectors or {}}


def node_id(entry):return json.dumps([entry.get('selectors',{}),entry['key']],sort_keys=True,ensure_ascii=False)


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _target_fov(s):
    if s.framing_source!='legacy':
        return (s.target_width_mm*(1+s.horizontal_margin_percent/100),
                s.target_length_mm*(1+s.vertical_margin_percent/100) if s.vertical_margin_percent>=0
                else s.target_length_mm+s.image_vertical_margin_mm)
    return s.target_width_mm+s.image_horizontal_margin_mm,s.target_length_mm+s.image_vertical_margin_mm


def _material_pitch(s):
    width,height=_target_fov(s)
    pitch=width/s.sensor_width
    if s.kind=='area' and s.vertical_margin_percent>=0:
        pitch=max(pitch,height/s.sensor_height)
    return pitch


def calculate(settings,limits=None):
    s=settings.validate();warnings=[];blocking=[]
    dx=s.fov_width_mm/s.sensor_width if s.precision_source=='fov' else s.x_mm_per_px
    if s.precision_source=='optics':
        dx=s.x_mm_per_px if s.optics_direction=='precision_to_wd' else s.pixel_pitch_um/1000*s.working_distance_mm/s.focal_length_mm
        if s.optics_method=='thin_lens':
            if s.optics_direction=='wd_to_precision':dx=s.pixel_pitch_um/1000*(s.working_distance_mm+s.principal_plane_offset_mm-s.focal_length_mm)/s.focal_length_mm
            warnings.append('薄透镜近轴模型，物距从前主平面计；主平面未知、畸变及对焦变化须用实测视野校准，不是测量精度保证。')
        else:warnings.append('镜头参数为远距近似估算，请用实测视野校准；线扫Y精度仍由编码器决定。' if s.kind=='line' else '镜头参数按方形像元作远距近似估算，请用实测视野校准。')
    target_fov_w,target_fov_h=_target_fov(s)
    if s.framing_source=='material':dx=_material_pitch(s)
    elif s.framing_source=='distance':
        object_distance=s.working_distance_mm+(s.principal_plane_offset_mm-s.focal_length_mm if s.optics_method=='thin_lens' else 0)
        if object_distance<=0:raise CameraError('工作距离及主平面偏移不能形成有效视野。')
        dx=s.pixel_pitch_um/1000*object_distance/s.focal_length_mm
    fov_x=dx*s.sensor_width
    if s.framing_source=='distance':target_fov_w=fov_x
    cycle=s.kind=='line' and s.frequency_strategy=='cycle'
    converter=s.line_source=='FrequencyConverter'
    cycle_calibrated=cycle and converter and s.cycle_travel_mm>0
    cycle_pending=cycle and s.auto_frequency and not cycle_calibrated
    counts=s.ppr*s.edge_factor*s.encoder_revs if s.kind=='line' else None
    lines=s.ppr*s.edge_factor*s.encoder_revs*s.multiplier/(s.pre_divider*s.post_divider) if s.kind=='line' else None
    if not converter:lines=None;cycle_pending=False
    dy=s.y_mm_per_px if s.kind=='line' else (s.fov_height_mm/s.sensor_height if s.precision_source=='fov' else s.y_mm_per_px)
    if s.kind=='line':
        if s.line_y_source=='calibration':dy=s.calibration_length_mm/s.calibration_rows
        elif s.line_y_source=='square':
            dy=dx
            if not cycle_calibrated:warnings.append('Y精度按方形像素规划，尚未证明编码器实际采样一致；请用原始产品图标定核对。')
        elif s.line_y_source=='legacy':blocking.append('旧配置已迁移：Y精度来自旧产品节距换算，请在工位标定中选择并确认新的Y精度来源后再写入。')
    if cycle:dy=dx
    frequency_solution=None;target_dy=dy
    if cycle and converter:
        if cycle_calibrated:
            if s.auto_frequency:
                from camera_frequency import solve_frequency
                frequency_solution=solve_frequency(s.cycle_travel_mm/(counts*target_dy),limits)
                frequency_solution['strategy']='measured_cycle'
                s=replace(s,**{key:frequency_solution[key] for key in ('pre_divider','multiplier','post_divider')})
                lines=counts*frequency_solution['ratio']
                if not frequency_solution['limits_verified']:warnings.append('倍分频使用离线参考范围，连接后按设备范围核对。')
            dy=s.cycle_travel_mm/lines
            if abs(100*(dy/target_dy-1))>s.frequency_tolerance_percent+1e-9:
                blocking.append('设备倍分频不能满足目标纵向精度，请调整因子或光学精度；不能为凑够周期行数而改变采样比例。')
        else:
            blocking.append('请填写每周期实际走料距离，才能计算或校验倍分频及纵向精度。')
            if cycle_pending:lines=None
    if s.kind=='line' and s.auto_frequency and not cycle and converter:
        from camera_frequency import solve_frequency
        frequency_solution=solve_frequency(s.encoder_travel_mm_per_rev/(s.ppr*s.edge_factor*dy),limits)
        s=replace(s,**{key:frequency_solution[key] for key in ('pre_divider','multiplier','post_divider')})
        dy=s.encoder_travel_mm_per_rev/(s.ppr*s.edge_factor*frequency_solution['ratio'])
        lines=s.ppr*s.edge_factor*s.encoder_revs*frequency_solution['ratio']
        if abs(100*(dy/target_dy-1))>s.frequency_tolerance_percent+1e-9:blocking.append('设备整数倍分频无法满足目标Y采样容差，请调整工位或目标精度。')
        if not frequency_solution['limits_verified']:warnings.append('倍分频使用1～5规划范围，连接相机后须按设备范围重算；不是设备支持保证。')
    if s.kind=='line' and not converter:
        warnings.append('当前行触发源为'+s.line_source+'，倍分频不参与此行触发链；图高按输入精度规划，实际行节拍及采样请按该信号源核对。')
        if s.limit_line_rate and not s.line_rate_override:blocking.append('当前行触发源不能自动估算行频，请填写手动行频上限或关闭行频限制。')
    if s.kind=='area' and (s.precision_source=='optics' or s.framing_source!='legacy'):dy=dx
    product_h=math.ceil(s.target_length_mm/dy-1e-10)
    material_w=math.ceil(s.target_width_mm/dx-1e-10)
    target_mode=s.framing_source!='legacy' and s.vertical_margin_percent>=0
    margin_h=math.ceil((target_fov_h-s.target_length_mm)/dy-1e-10)
    needed_w=s.sensor_width if s.framing_source!='legacy' else math.ceil(target_fov_w/dx-1e-10)
    needed_h=math.ceil(target_fov_h/dy-1e-10) if target_mode else product_h+margin_h
    width=s.width_override or needed_w;height=s.height_override or needed_h
    if cycle and not s.height_override:height=math.ceil(needed_h/s.height_rounding)*s.height_rounding
    limits=limits or {}
    def align(value,key,up=True):
        cap=limits.get(key,{});minimum=cap.get('min',0);step=max(1,cap.get('inc',1))
        return int(minimum+(math.ceil if up else math.floor)((value-minimum)/step)*step)
    if not s.width_override:width=align(width,'Width')
    if not s.height_override:height=align(height,'Height')
    if cycle and lines is not None:
        if math.floor(lines+1e-8)-height<s.cycle_idle_lines:
            blocking.append('按实际采样计算的周期行触发数不足以容纳图高和预留空档，请调整留白、图高取整、空档或工位周期；不要直接增大倍频。')
    if s.framing_source!='legacy' and fov_x<s.target_width_mm-1e-8:blocking.append('当前工作距离对应视野小于材料宽度。')
    offset_x=(s.sensor_width-width)//2 if s.centered_x else s.offset_x
    if s.centered_x:offset_x=align(offset_x,'OffsetX',False)
    if width<needed_w or height<needed_h:blocking.append('手动ROI不足以覆盖所需检测范围。')
    if width>s.sensor_width or offset_x<0 or offset_x+width>s.sensor_width:blocking.append('X方向视野或ROI不足，需调整镜头/实测精度/检测宽度。')
    if s.kind=='area' and (height+s.offset_y>s.sensor_height):blocking.append('面阵Y方向视野不足或ROI越界。')
    if margin_h:warnings.append('纵向留白表示整帧预留背景；前后分配由下位机帧相位和实际图像确认，不自动控制下位机。')
    aspect=100*(dy/dx-1)
    if abs(aspect)>s.square_tolerance_percent:
        text='X/Y精度差异 '+format(aspect,'.2f')+'%，编码器链不会自动反推修改。'
        (blocking if s.require_square else warnings).append(text)
    required=s.products_per_minute/60*lines if lines is not None else None
    recommended=math.ceil(required*(1+s.rate_margin_percent/100)/1000)*1000 if required is not None else None
    rate=s.line_rate_override or recommended
    if lines is not None:
        integer_cycle=math.isclose(lines,round(lines),abs_tol=1e-8,rel_tol=0)
        if not integer_cycle:warnings.append('帧间总行触发数为周期平均值，边界计数/分频相位需现场核对，不因平均值非整数自动修改固定倍分频。')
        if height>math.floor(lines+1e-8):
            (blocking if integer_cycle else warnings).append('本帧Height超过相邻帧触发间预计可用行数；下一帧可能在本帧采满前到达，请核对帧/行节拍及忙帧处理。')
        if s.limit_line_rate and rate<required-1e-8:blocking.append('已启用的手动行频上限低于预计外部行触发频率。')
        if s.limit_line_rate and rate<recommended and rate>=required:warnings.append('手动行频上限满足预计触发频率，但少于能力预留建议值。')
        if s.exposure_us>1_000_000/required:blocking.append('曝光时间超过预计外部行触发间隔；请按最高实际行频核对。')
    elif s.kind=='area':
        if s.exposure_us>60_000_000/s.products_per_minute:blocking.append('曝光时间超过产品帧周期。')
    blur=required*dy*s.exposure_us/1_000_000 if required is not None else None
    if cycle:blur=required*s.cycle_travel_mm/lines*s.exposure_us/1_000_000 if cycle_calibrated else None
    entries=[node('OffsetX','int',offset_x),node('Width','int',width),node('Height','int',height)]
    entries.extend([node('AcquisitionMode','enum','Continuous'),node('ExposureMode','enum','Timed',{'TriggerSelector':'LineStart'} if s.kind=='line' else {})])
    if s.frame_selector=='FrameBurstStart':entries.append(node('AcquisitionBurstFrameCount','int',1,{'TriggerSelector':s.frame_selector}))
    if s.kind=='area':entries.append(node('OffsetY','int',s.offset_y))
    if s.pixel_format:entries.append(node('PixelFormat','enum',s.pixel_format))
    for key in ('ExposureAuto','GainAuto'):
        entry=node(key,'enum','Off');entry['optional']=True;entries.append(entry)
    entries.extend([node('ReverseX','bool',s.reverse_x),node('ExposureTime','float',s.exposure_us),node('Gain','float',s.gain)])
    if s.digital_shift>=0:entries.extend([node('DigitalShiftEnable','bool',True),node('DigitalShift','int',s.digital_shift)])
    if s.preamp_gain:entries.append(node('PreampGain','enum',s.preamp_gain))
    if s.compression:entries.append(node('ImageCompressionMode','enum',s.compression))
    if s.black_level>=0:entries.extend([node('BlackLevelEnable','bool',True),node('BlackLevel','float',s.black_level)])
    if s.device_name:entries.append(node('DeviceUserID','string',s.device_name))
    frame={'TriggerSelector':s.frame_selector}
    entries.extend([node('TriggerSource','enum',s.frame_line,frame),node('TriggerActivation','enum',s.frame_edge,frame),node('TriggerMode','enum','On',frame)])
    line_input=s.encoder_line if s.line_source in ('FrequencyConverter','EncoderModuleOut') else s.line_source if re.fullmatch(r'Line\d+',s.line_source) else None
    for line,debounce in [(s.frame_line,s.z_debounce_ns)]+([(line_input,s.a_debounce_ns)] if s.kind=='line' and line_input else []):
        context={'LineSelector':line};entries.append(node('LineMode','enum','Input',context))
        if s.input_format:entries.append(node('LineFormat','enum',s.input_format,context))
        entries.append(node('LineDebouncerTimeNs','int',debounce,context))
    if s.kind=='line':
        tdi=node('TDIMode','enum','Line_1');tdi['optional']=True;entries.append(tdi)
        if s.line_source in ('FrequencyConverter','EncoderModuleOut'):entries.extend([node('EncoderSourceA','enum',s.encoder_line),node('EncoderSourceB','enum','NA'),
            node('EncoderOutputMode','enum','AnyDirection'),node('EncoderCounterMode','enum','IgnoreDirection'),
            ])
        entries.append(node('AcquisitionLineRateEnable','bool',s.limit_line_rate))
        if converter:entries.extend([node('InputSource','enum','EncoderModuleOut'),node('SignalAlignment','enum',s.line_edge)])
        if converter and not cycle_pending:entries.extend([node('PreDivider','int',s.pre_divider),node('Multiplier','int',s.multiplier),node('PostDivider','int',s.post_divider)])
        if s.limit_line_rate and rate is not None:entries.append(node('AcquisitionLineRate','int',int(rate)))
        context={'TriggerSelector':'LineStart'}
        entries.extend([node('TriggerSource','enum',s.line_source,context),node('TriggerActivation','enum',s.line_edge,context),node('TriggerMode','enum','On',context)])
    for enabled,line,source in ((s.output0_enabled,s.output0_line,s.output0_source),(s.output4_enabled,s.output4_line,s.output4_source)):
        if enabled:
            context={'LineSelector':line};entries.extend([node('LineMode','enum',s.output_mode,context),node('LineSource','enum',source,context)])
            if s.strobe_enable:entries.append(node('StrobeEnable','bool',True,context))
            if line==s.output4_line and s.output4_enabled:entries.append(node('StrobeLineDuration','int',s.strobe_duration_us,context))
    if len({node_id(n) for n in entries})!=len(entries):raise CameraError('配置产生了重复或冲突节点。')
    return {'schema':'vt-camera-plan/1','settings':config_dict(s),'metrics':{
        'x_mm_per_px':dx,'y_mm_per_px':dy,'fov_width_mm':fov_x,'xy_difference_percent':aspect,
        'target_fov_width_mm':target_fov_w,'target_fov_height_mm':target_fov_h,
        'coverage_width_mm':width*dx,'coverage_height_mm':height*dy,
        'working_distance_mm':dx*s.focal_length_mm/(s.pixel_pitch_um/1000)+(s.focal_length_mm-s.principal_plane_offset_mm if s.optics_method=='thin_lens' else 0) if s.precision_source=='optics' or s.framing_source!='legacy' else s.working_distance_mm,
        'sensor_active_width_mm':s.sensor_width*s.pixel_pitch_um/1000,
        'optical_magnification':s.pixel_pitch_um/1000/dx if s.pixel_pitch_um>0 else None,
        'optics_method':s.optics_method if s.precision_source=='optics' else s.precision_source,
        'frequency_solution':frequency_solution,'target_y_mm_per_px':target_dy,
        'y_sampling_error_percent':100*(dy/target_dy-1) if cycle_calibrated or (s.kind=='line' and converter and s.auto_frequency and not cycle) else None,
        'cycle_calibrated':cycle_calibrated,'frequency_pending':cycle_pending,
        'input_counts_per_cycle':counts,
        'encoder_counts_per_mm':counts/s.cycle_travel_mm if cycle_calibrated else None,
        'material_cycle_fraction':s.target_length_mm/s.cycle_travel_mm if cycle_calibrated else None,
        'material_encoder_counts':counts*s.target_length_mm/s.cycle_travel_mm if cycle_calibrated else None,
        'target_cycle_line_count':s.cycle_travel_mm/target_dy if cycle_calibrated else None,
        'cycle_idle_available':math.floor(lines+1e-8)-height if lines is not None else None,
        'cycle_travel_for_square_mm':lines*dx if lines is not None else None,
        'actual_y_mm_per_px':s.cycle_travel_mm/lines if cycle_calibrated else None,
        'actual_product_height_lines':math.ceil(s.target_length_mm*lines/s.cycle_travel_mm-1e-10) if cycle_calibrated else None,
        'horizontal_margin_percent_actual':100*(fov_x/s.target_width_mm-1),
        'effective_counts_per_product':counts,
        'line_triggers_per_cycle':lines,'lines_per_product':lines,'required_line_rate_hz':required,'recommended_line_rate_hz':recommended,
        'product_height_lines':product_h,'vertical_margin_lines':margin_h,'background_height_lines':max(0,height-product_h),
        'material_width_px':material_w,'material_height_px':product_h,'material_pixel_count':material_w*product_h,
        'average_image_line_rate_hz':s.products_per_minute/60*height,'line_y_source':s.line_y_source if s.kind=='line' else 'optical',
        'square_pixel_product_lines':math.ceil(s.target_length_mm/dx-1e-10),'required_image_height':needed_h,
        'width':width,'height':height,'offset_x':offset_x,'offset_y':s.offset_y if s.kind=='area' else 0,
        'motion_during_exposure_mm':blur,'frame_rate_hz':s.products_per_minute/60},
        'nodes':entries,'warnings':warnings,'blocking':blocking}


def import_mfs_text(text,current=None):
    """Read ordered GenApi persistence rows, never execute or load them into a camera."""
    if len(text)>1_000_000:raise CameraError('MFS文件超过1MB。')
    settings=CameraSettings(**asdict(current or CameraSettings()));selectors={};values={}
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):continue
        parts=line.split(None,1)
        if len(parts)!=2:raise CameraError('不是支持的GenApi文本MFS格式。')
        key,value=parts
        if key in ('TriggerSelector','LineSelector'):selectors[key]=value;continue
        values[(tuple(sorted(selectors.items())) if key.startswith(('Trigger','Line','Strobe')) else (),key)]=value
    if not values:raise CameraError('MFS没有可读取的参数。')
    plain={key:value for (context,key),value in values.items() if not context}
    mapping={'Width':('width_override',int),'Height':('height_override',int),'OffsetX':('offset_x',int),
        'OffsetY':('offset_y',int),'ExposureTime':('exposure_us',float),'Gain':('gain',float),
        'PreDivider':('pre_divider',int),'Multiplier':('multiplier',int),'PostDivider':('post_divider',int),
        'PixelFormat':('pixel_format',str),'ImageCompressionMode':('compression',str),'DeviceUserID':('device_name',str),
        'AcquisitionLineRate':('line_rate_override',float),'PreampGain':('preamp_gain',str)}
    try:
        for key,(field,convert) in mapping.items():
            if key in plain:setattr(settings,field,convert(plain[key]))
        if 'OffsetX' in plain:settings.centered_x=False
        if 'AcquisitionLineRateEnable' in plain:settings.limit_line_rate=plain['AcquisitionLineRateEnable'].lower() in ('1','true')
        if 'ReverseX' in plain:settings.reverse_x=plain['ReverseX'].lower() in ('1','true')
        for (context,key),value in values.items():
            context=dict(context);trigger=context.get('TriggerSelector')
            if trigger in ('FrameStart','FrameBurstStart'):
                settings.frame_selector=trigger
                if key=='TriggerSource':settings.frame_line=value
                elif key=='TriggerActivation':settings.frame_edge=value
            elif trigger=='LineStart':
                if key=='TriggerActivation':settings.line_edge=value
                elif key=='TriggerSource':settings.line_source=value
        if 'EncoderSourceA' in plain:settings.encoder_line=plain['EncoderSourceA']
    except ValueError as exc:raise CameraError('MFS中的数值格式无效。') from exc
    return settings.validate(),len(values)
