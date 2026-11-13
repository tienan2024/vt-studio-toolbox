"""Reference presets and display labels; SDK values are never translated."""
PRESETS={
    'line2k':{'zh':'2K 线扫相机','en':'2K line scan','kind':'line','sensor_width':2048,'sensor_height':1,'pixel_pitch_um':14.0,'model':'MV-CL022-91GM'},
    'line4k':{'zh':'4K 线扫相机','en':'4K line scan','kind':'line','sensor_width':4096,'sensor_height':2,'pixel_pitch_um':7.0,'model':'MV-CL042-91GM'},
    'area5mp':{'zh':'500万 面阵相机','en':'5MP area scan','kind':'area','sensor_width':2448,'sensor_height':2048,'pixel_pitch_um':3.45,'model':'MV-CS050-60GC'},
}

LABELS={
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
