"""Reference presets and display labels; SDK values are never translated."""
PRESETS={
    'line2k':{'kind':'line','sensor_width':2048,'sensor_height':2,'pixel_pitch_um':7.0,'model':'MV-CL024-91GM','color':False,'id':9570},
    'line2k_color':{'kind':'line','sensor_width':2048,'sensor_height':3,'pixel_pitch_um':7.0,'model':'MV-CL024-91GC','color':True,'id':9576},
    'line4k':{'kind':'line','sensor_width':4096,'sensor_height':2,'pixel_pitch_um':7.0,'model':'MV-CL042-91GM','color':False,'id':7996},
    'line4k_color':{'kind':'line','sensor_width':4096,'sensor_height':2,'pixel_pitch_um':7.0,'model':'MV-CL042-91GC','color':True,'id':7997},
    'area5mp':{'kind':'area','sensor_width':2448,'sensor_height':2048,'pixel_pitch_um':3.45,'model':'MV-CS050-60GM V5','color':False,'id':12568},
    'area5mp_color':{'kind':'area','sensor_width':2448,'sensor_height':2048,'pixel_pitch_um':3.45,'model':'MV-CS050-60GC V5','color':True,'id':12567},
}
for _p in PRESETS.values():
    _p['zh']=_p['model']+' · '+('彩色' if _p['color'] else '黑白')
    _p['en']=_p['model']+' · '+('Color' if _p['color'] else 'Mono')
    _p['source']='https://www.hikrobotics.com/cn/machinevision/productdetail/?id='+str(_p['id'])

# Fixed pairings are supplied by the operator; never infer them from model order.
LENSES={
    'MVL-AF2524M-M42':{'focal_length_mm':25.0,'image_circle_mm':29.0,'min_distance_mm':150,
        'source':'https://www.hikrobotics.com/cn2/source/vision/document/2023/9/5/MVL-AF2524M-M42_20230808.pdf'},
    'MVL-KF1228M-12MP':{'focal_length_mm':12.0,'image_circle_mm':17.6,'min_distance_mm':100,
        'source':'https://www.hikrobotics.com/en2/source/vision/document/2023/9/19/MVL-KF1228M-12MP_datasheet_20221024.pdf'},
    'MVL-HF0628M-6MPE':{'focal_length_mm':6.0,'image_circle_mm':9.0,'min_distance_mm':100,
        'source':'https://www.hikrobotics.com/en2/source/vision/document/2023/9/19/MVL-HF0628M-6MPE_datasheet_20221022.pdf'},
}
for _key,_p in PRESETS.items():
    _p['lens_model']='MVL-KF1228M-12MP' if _key.startswith('line2k') else ('MVL-AF2524M-M42' if _key.startswith('line4k') else 'MVL-HF0628M-6MPE')
    _p['focal_length_mm']=LENSES[_p['lens_model']]['focal_length_mm']

LABELS={
    'material':('材料宽度 → 工作距离','Material → distance'),
    'distance':('工作距离 → 视野','Distance → FOV'),
    'cycle':('按实测周期走料匹配Y','Measured cycle travel'),
    'pitch':('按实测走料匹配Y精度','Measured sampling pitch'),
    'quick':('快速估算','Quick estimate'),'thin_lens':('专业计算','Professional'),
    'custom':('自定义 / 已连接设备','Custom / connected device'),
    'wd_to_precision':('工作距离 → 精度','Distance → precision'),
    'precision_to_wd':('精度 → 工作距离','Precision → distance'),
    'fov':('沿用实测视野','Measured field of view'),
    'precision':('已知精度','Known precision'),
    'optics':('镜头估算','Lens estimate'),
    'calibration':('产品实测标定','Product calibration'),
    'square':('方形像素规划','Square-pixel planning'),
    'legacy':('旧配置换算 · 待确认','Legacy value · confirm'),
    'RisingEdge':('上升沿','Rising edge'),'FallingEdge':('下降沿','Falling edge'),
    'Differential':('差分','Differential'),'Strobe':('频闪','Strobe'),'Output':('输出','Output'),
    'Off':('关闭','Off'),'On':('开启','On'),'':('保持现状','Keep current'),
    'AcquisitionStartActive':('采集开始有效','AcquisitionStartActive'),
    'AcquisitionStopActive':('采集停止有效','AcquisitionStopActive'),
    'CounterActive':('计数器有效','CounterActive'),'ExposureActive':('曝光有效','ExposureActive'),
    'ExposureEndActive':('曝光结束有效','ExposureEndActive'),
    'ExposureStartActive':('曝光开始有效','ExposureStartActive'),
    'FrameBurstEndActive':('帧突发结束有效','FrameBurstEndActive'),
    'FrameBurstStartActive':('帧突发开始有效','FrameBurstStartActive'),
    'HardTriggerActive':('硬触发有效','HardTriggerActive'),
    'SoftTriggerActive':('软触发有效','SoftTriggerActive'),'TimerActive':('计时器有效','TimerActive'),
}

FIELD_LABELS={
    'framing_source':'Framing','horizontal_margin_percent':'Horizontal margin','vertical_margin_percent':'Vertical margin',
    'cycle_idle_lines':'Min. cycle idle','height_rounding':'Height rounding',
    'cycle_travel_mm':'Measured Z-cycle travel','frequency_strategy':'Frequency strategy',
    'target_width_mm':'Product width','target_length_mm':'Product length',
    'working_distance_mm':'Working distance','focal_length_mm':'Focal length',
    'pixel_pitch_um':'Pixel pitch','x_mm_per_px':'Pixel precision',
    'image_horizontal_margin_mm':'Horizontal margin','image_vertical_margin_mm':'Vertical background',
    'frame_line':'Frame trigger','encoder_line':'Line trigger','frame_selector':'Trigger selector',
    'frame_edge':'Frame trigger edge','line_edge':'Line trigger edge','input_format':'Input format',
    'a_debounce_ns':'A debouncer','z_debounce_ns':'Frame debouncer','output0_enabled':'Enable output 1',
    'output4_enabled':'Enable output 2','output0_line':'Output 1 line','output4_line':'Output 2 line',
    'output0_source':'Output 1 source','output4_source':'Output 2 source','output_mode':'Output mode',
    'strobe_enable':'Strobe enable','strobe_duration_us':'Output 2 duration','exposure_us':'Exposure',
    'gain':'Gain','pixel_format':'Pixel format','compression':'HB compression','line_y_source':'Line Y source',
    'y_mm_per_px':'Y precision','sensor_width':'Sensor width','sensor_height':'Sensor height',
    'fov_width_mm':'Full X field of view','fov_height_mm':'Full Y field of view',
    'calibration_length_mm':'Calibration length','calibration_rows':'Product rows in image',
    'precision_source':'Precision source','optics_direction':'Calculation direction',
}


def option_label(value,language='zh'):
    if value in PRESETS:return PRESETS[value]['en' if language=='en' else 'zh']
    pair=LABELS.get(value)
    return pair[1 if language=='en' else 0] if pair else str(value)
