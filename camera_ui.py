"""Camera workstation: calculate, inspect, compare, then explicitly write UserSet1."""
from dataclasses import asdict
import json
from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QRectF,QSize
from PySide6.QtGui import QPainter,QColor,QPen,QPixmap,QIcon,QPainterPath
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QTabWidget,
    QSplitter,QScrollArea,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,
    QPlainTextEdit,QFileDialog,QProgressBar,QMenu,QGridLayout,QSizePolicy,QToolButton,QAbstractSpinBox,QLayout,QFrame)
from styled_controls import make_combo
from camera_model import CameraSettings,CameraError,calculate,config_dict,settings_from_dict,import_mfs_text,fingerprint,workflow_settings
from camera_sdk import discover_mvs,enumerate_cameras
from camera_transaction import inspect_camera,preview_camera,write_camera
from camera_options import PRESETS,FIELD_LABELS,LABELS,option_label
from camera_constraints import resolve_fixed_values,within_precision


def value_lock_icon(locked):
    image=QPixmap(20,20);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#b5531c' if locked else '#526377'),1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawRoundedRect(QRectF(4.5,9,11,8),1.5,1.5)
    path=QPainterPath();path.moveTo(7,9);path.lineTo(7,6)
    path.cubicTo(7,1.5,14,1.5,14,6);path.lineTo(14,9 if locked else 6)
    painter.drawPath(path);painter.drawLine(10,12,10,14);painter.end()
    return QIcon(image)


class CameraJob(QThread):
    result=Signal(str,object)
    failed=Signal(str,object)
    progress=Signal(str)

    def __init__(self,action,payload,sdk,parent):super().__init__(parent);self.action=action;self.payload=payload;self.sdk=sdk
    def run(self):
        try:
            if self.action=='scan':data=enumerate_cameras(self.sdk)
            elif self.action=='inspect':data=inspect_camera(self.payload['uid'],self.sdk)
            elif self.action=='compare':data=preview_camera(self.payload['uid'],settings_from_dict(self.payload['settings']),self.sdk)
            else:data=write_camera(self.payload,self.sdk,self.progress.emit)
            self.result.emit(self.action,data)
        except Exception as exc:self.failed.emit(str(exc),getattr(exc,'report',None))


class FramePreview(QWidget):
    """Physical coverage illustration, not a simulated captured image."""
    def __init__(self):
        super().__init__();self.plan=None;self.setMinimumHeight(160);self.setMaximumHeight(270)

    def paintEvent(self,event):
        if not self.plan:return
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s=self.plan['settings'];m=self.plan['metrics'];w=m['width']*m['x_mm_per_px'];h=m['height']*m['y_mm_per_px']
        scale=min((self.width()-70)/max(w,s['target_width_mm']),(self.height()-44)/max(h,s['target_length_mm']))
        rect=QRectF((self.width()-w*scale)/2,24,w*scale,h*scale)
        p.setPen(QPen(QColor('#c8d1dd'),1));p.setBrush(QColor('#e8eef4'));p.drawRect(rect)
        product=QRectF(rect.center().x()-s['target_width_mm']*scale/2,rect.center().y()-s['target_length_mm']*scale/2,s['target_width_mm']*scale,s['target_length_mm']*scale)
        p.setBrush(QColor('#f5e4d8'));p.setPen(QPen(QColor('#b5531c'),1));p.drawRect(product)
        p.setPen(QColor('#263548'))
        text='材料\nW '+format(s['target_width_mm'],'.6g')+' mm\nL '+format(s['target_length_mm'],'.6g')+' mm'
        label=QRectF(product.right()+8,product.center().y()-35,150,80) if product.width()<140 else product
        p.drawText(label,Qt.AlignmentFlag.AlignCenter,text)
        p.setPen(QColor('#526377'));p.drawText(QRectF(0,0,self.width(),20),Qt.AlignmentFlag.AlignCenter,'居中示意 · 产品前后位置由下位机相位决定')
        p.end()


class PropertyForm:
    """MVS-style parameter/value/unit grid, retaining real typed Qt editors."""
    def __init__(self,page,title):
        self.table=page.table(['参数','设置值','单位']);self.rows={}
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(0,126)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(2,70)
        widget=QWidget();layout=QVBoxLayout(widget);layout.setContentsMargins(8,10,8,10);layout.addWidget(self.table);layout.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget)
        page.form_tabs.addTab(scroll,title);page.property_forms.append(self)

    def addRow(self,caption,widget=None):
        row=self.table.rowCount();self.table.insertRow(row);self.table.setRowHeight(row,36)
        if widget is None:
            if isinstance(caption,QCheckBox):
                widget=caption;caption=QLabel(widget.text());widget.setText('')
            else:
                self.table.setSpan(row,0,1,3);self.table.setCellWidget(row,0,caption);self.table.setRowHeight(row,54);self.fit();return
        text=caption.text();name,_,unit=text.partition(' / ');caption.setText(name)
        self.table.setCellWidget(row,0,caption);self.table.setCellWidget(row,1,widget)
        self.table.setItem(row,2,QTableWidgetItem(unit));self.rows[widget]=row;self.fit()
        return caption

    def setRowVisible(self,widget,visible):
        self.table.setRowHidden(self.rows[widget],not visible);self.fit()

    def isRowHidden(self,widget):
        return self.table.isRowHidden(self.rows[widget])

    def fit(self):
        self.table.setFixedHeight(max(30,self.table.horizontalHeader().sizeHint().height())+sum(self.table.rowHeight(i) for i in range(self.table.rowCount()) if not self.table.isRowHidden(i))+4)


class ConditionForm:
    """Working-condition editors; reuse the existing typed controls and signals."""
    def __init__(self,page,title):
        self.page=page;self.entries=[];self.rows={};self.order=[]
        self.widget=QWidget();self.grid=QGridLayout(self.widget)
        self.grid.setContentsMargins(12,14,12,14)
        self.grid.setHorizontalSpacing(14);self.grid.setVerticalSpacing(14)
        self.grid.setColumnStretch(0,1);self.grid.setColumnStretch(1,1)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setWidget(self.widget)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page.form_tabs.addTab(self.scroll,title);page.input_forms.append(self)

    def addRow(self,caption,widget=None):
        cell=QWidget();layout=QVBoxLayout(cell);layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        if widget is None:
            widget=caption;caption=None
        if caption is not None:
            caption.setWordWrap(True)
            layout.addWidget(caption)
            caption.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        if isinstance(widget,QComboBox):
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(8)
        editor=(self.page.lockable_number(widget) if self is getattr(self.page,'parameter_form',None)
                and isinstance(widget,QAbstractSpinBox) else widget)
        layout.addWidget(editor)
        span=2 if caption is None else 1
        self.entries.append((widget,cell,span));self.rows[widget]=True
        self.fit()

    def arrange(self,widgets,wide=()):
        self.order=list(widgets)
        self.entries=[(widget,cell,2 if widget in wide else span) for widget,cell,span in self.entries]
        self.fit()

    def setRowVisible(self,widget,visible):
        if self.rows[widget]!=visible:
            self.rows[widget]=visible;self.fit()
        widget.setVisible(visible)

    def isRowHidden(self,widget):
        return not self.rows[widget]

    def content_height(self):
        margins=self.grid.contentsMargins()
        width=self.scroll.contentsRect().width()-self.scroll.verticalScrollBar().sizeHint().width()-margins.left()-margins.right()
        column_width=max(1,(width-self.grid.horizontalSpacing())//2)
        heights={}
        for index in range(self.grid.count()):
            item=self.grid.itemAt(index);row,_,_,span=self.grid.getItemPosition(index)
            cell=item.widget();layout=cell.layout()
            height=layout.heightForWidth(column_width*span+self.grid.horizontalSpacing()*(span-1))
            if height<0:height=layout.sizeHint().height()
            cell.setMinimumHeight(height)
            heights[row]=max(heights.get(row,0),height)
        return sum(heights.values())+max(0,len(heights)-1)*self.grid.verticalSpacing()+margins.top()+margins.bottom()

    def fit(self):
        while self.grid.count():self.grid.takeAt(0)
        entries=sorted(self.entries,key=lambda entry:self.order.index(entry[0]) if entry[0] in self.order else len(self.order))
        row=column=0
        for widget,cell,span in entries:
            visible=self.rows[widget];cell.setVisible(visible)
            if not visible:continue
            if span==2 and column:row+=1;column=0
            self.grid.addWidget(cell,row,column,1,span)
            column+=span
            if column>=2:row+=1;column=0
        self.grid.invalidate()
        if hasattr(self.page,'advanced_button'):self.page.schedule_input_fit()


class CameraPage(QWidget):
    def __init__(self):
        super().__init__();self.setObjectName('CameraPage')
        self.worker=None;self.preview=None;self.last_report=None;self.geometry=None;self.plan=None;self._loading=False
        self.controls={};self.labels={};self.field_forms={};self.field_titles={};self.property_forms=[];self.input_forms=[];self._input_fit_pending=False;self.language='zh';self.output_caps={}
        self.fixed_values={};self.lock_buttons={}
        self.sdk=discover_mvs();root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        tools=QHBoxLayout();tools.addStretch()
        self.language_box=self.styled_combo();self.language_box.addItem('中文','zh');self.language_box.addItem('English','en')
        tools.addWidget(self.language_box)
        self.connection_button=self.button('连接与写入相机',lambda:None,tools);self.connection_button.setCheckable(True)
        self.files_button=self.button('配置与文件',lambda:None,tools);menu=QMenu(self.files_button)
        for title,action in [('打开配置',self.open_config),('保存配置',self.save_config),('读取 MFS',self.open_mfs),('设置 MVS 目录',self.choose_sdk)]:menu.addAction(title,action)
        self.files_button.setMenu(menu);root.addLayout(tools)
        for widget in (self.language_box,self.connection_button,self.files_button):widget.setFixedSize(152,36)
        self.devices_bar=QWidget();bar=QHBoxLayout(self.devices_bar);bar.setContentsMargins(0,0,0,0)
        self.device=self.styled_combo();self.device.addItem('尚未枚举相机',None);bar.addWidget(self.device,1)
        self.scan_button=self.button('枚举相机',lambda:self.start_job('scan'),bar)
        self.inspect_button=self.button('读取设备尺寸',lambda:self.start_job('inspect'),bar)
        root.addWidget(self.devices_bar);self.devices_bar.hide()
        split=QSplitter(Qt.Orientation.Horizontal);root.addWidget(split,1)
        self.form_panel=QWidget();left=QVBoxLayout(self.form_panel);left.setContentsMargins(0,0,10,0);left.setSpacing(8)
        self.camera_type=self.styled_combo()
        for key,preset in PRESETS.items():self.camera_type.addItem(preset['zh'],key)
        self.camera_type.addItem('自定义 / 已连接设备','custom')
        left.addWidget(self.camera_type);self.camera_info=QLabel();self.camera_info.setObjectName('Subtle');self.camera_info.setWordWrap(True);left.addWidget(self.camera_info)
        self.form_tabs=QTabWidget();left.addWidget(self.form_tabs)
        station=ConditionForm(self,'材料与视野');self.parameter_form=station
        encoder=ConditionForm(self,'编码器与图高');trigger=self.form_tab('采集触发')
        io=PropertyForm(self,'数字 IO');self.io_table=io.table
        calibration=self.form_tab('专业标定');image=self.form_tab('成像')
        self.basic_tab_count=3
        self.combo(station,'optics_method','计算模式',[(option_label(v),v) for v in ('quick','thin_lens')])
        self.number(station,'target_width_mm','材料宽度 / mm',.001,100000,3)
        self.number(station,'target_length_mm','材料长度 / mm',.001,100000,3)
        self.combo(station,'framing_source','计算方向',[('材料宽度 → 工作距离','material'),('工作距离 → 视野','distance'),('原有计算配置','legacy')])
        self.number(station,'horizontal_margin_percent','横向总余量 / %',0,1000,2)
        self.number(station,'vertical_margin_percent','纵向总余量 / %',-1,1000,2,special='沿用原毫米留白')
        self.target_fov_fields={};self.target_fov_labels={}
        for key,title in (('target_fov_width_mm','视野宽度（目标宽度） / mm'),('target_fov_height_mm','视野长度（目标长度） / mm')):
            field=QLineEdit();field.setReadOnly(True);field.setStyleSheet('background:#edf0f5; color:#526377;')
            caption=QLabel(title);station.addRow(caption,field)
            self.target_fov_fields[key]=field;self.target_fov_labels[key]=caption
        self.optical_mode=self.styled_combo()
        for value in ('wd_to_precision','precision_to_wd','fov'):self.optical_mode.addItem(option_label(value),value)
        self.optical_mode_label=QLabel('原计算方向');calibration.addRow(self.optical_mode_label,self.optical_mode)
        self.number(station,'working_distance_mm','工作距离 / mm',.001,100000,3)
        self.number(station,'focal_length_mm','镜头焦距 / mm',0,1000,3,special='请填写')
        self.number(station,'pixel_pitch_um','像元尺寸 / μm',0,1000,3,special='请填写')
        self.number(station,'principal_plane_offset_mm','主平面偏移 / mm',-10000,10000,3)
        self.controls['principal_plane_offset_mm'].setToolTip('u = 工作距离 + 偏移。若WD从镜头前端量起，主平面在前端后方时填正值；未知填0，仅作模型估算。')
        self.number(calibration,'fov_width_mm','实测全幅 X / mm',.001,100000,3)
        self.number(calibration,'fov_height_mm','实测全幅 Y / mm',.001,100000,3)
        self.number(calibration,'x_mm_per_px','横向精度 / mm/px',.000001,1000,6)
        self.controls['x_mm_per_px'].setToolTip('线扫为横向光学精度；纵向由工位Y标定决定。镜头参数为近似估算。')
        self.number(station,'image_horizontal_margin_mm','左右总留边 / mm',0,100000,3)
        self.number(station,'image_vertical_margin_mm','前后总留白 / mm',0,100000,3)
        self.frame_trigger_group=self.trigger_group(trigger,'frame_line','帧触发','Line3')
        self.line_trigger_group=QWidget();line_layout=QVBoxLayout(self.line_trigger_group);line_layout.setContentsMargins(0,6,0,10);line_layout.setSpacing(8)
        self.line_trigger_title=QLabel('行触发');self.line_trigger_title.setStyleSheet('font-weight:600;');line_layout.addWidget(self.line_trigger_title)
        self.line_trigger_source=self.styled_combo();self.line_trigger_source.addItem('频率转换器输出','FrequencyConverter');self.line_trigger_source.setEnabled(False)
        line_layout.addWidget(self.line_trigger_source);trigger.addRow(self.line_trigger_group)
        self.encoder_trigger_group=self.trigger_group(trigger,'encoder_line','编码器 A 相输入','Line1')
        self.trigger_help=QLabel();self.trigger_help.setWordWrap(True);self.trigger_help.setObjectName('Subtle');trigger.addRow(self.trigger_help)
        self.combo(calibration,'kind','相机类型',[('线扫','line'),('面阵','area')])
        self.combo(calibration,'precision_source','精度来源',[('实测视野','fov'),('已知精度','precision'),('镜头估算','optics')])
        self.combo(calibration,'optics_direction','计算方向',[('工作距离 → 精度','wd_to_precision'),('精度 → 工作距离','precision_to_wd')])
        self.integer(calibration,'sensor_width','传感器宽度 / px',1,65536)
        self.integer(calibration,'sensor_height','传感器高度 / px',1,65536)
        self.text(calibration,'camera_model_id','型号记录')
        self.combo(calibration,'line_y_source','线扫 Y 精度来源',[('已知纵向精度','precision'),('产品实测标定','calibration'),('方形像素规划','square')])
        self.number(calibration,'y_mm_per_px','Y 精度 / mm/行',.000001,1000,6)
        self.number(calibration,'calibration_length_mm','标定产品长度 / mm',.001,100000,3)
        self.integer(calibration,'calibration_rows','图中产品占用行数',1,1000000)
        self.note(calibration,'线扫Y精度由行采样决定，可用未缩放产品图标定。镜头估算需用实测视野校准。')
        self.number(image,'products_per_minute','最高产能 / 片/分',.01,100000,2)
        self.check(encoder,'auto_frequency','自动计算倍分频')
        self.number(calibration,'encoder_travel_mm_per_rev','编码器每圈走料 / mm',0,1000000,4,special='填写实测长度')
        self.number(calibration,'frequency_tolerance_percent','Y 采样允许误差 / %',0,100,3)
        self.controls['encoder_travel_mm_per_rev'].setToolTip('编码器轴实际旋转一圈，对应材料行进的距离；通过实测或传动机构计算，不能用产品长度代替。')
        self.integer(encoder,'ppr','编码器 P/R',1,10000000)
        self.combo(encoder,'edge_factor','实际计数倍率',[('×1',1),('×2',2),('×4',4)])
        self.controls['edge_factor'].setToolTip('×1示例为A相上升沿；倍率应与设备实际有效计数一致，本选项不自动改变硬件计数模式。')
        self.number(encoder,'encoder_revs','每帧间隔圈数',.000001,1000,6)
        self.integer(encoder,'pre_divider','预分频 PreDivider',1,5)
        self.integer(encoder,'multiplier','倍频 Multiplier',1,5)
        self.integer(encoder,'post_divider','后分频 PostDivider',1,5)
        self.number(image,'rate_margin_percent','行频能力预留 / %',0,100,1)
        self.combo(io,'frame_selector','帧触发选择器',[('FrameBurstStart','FrameBurstStart'),('FrameStart','FrameStart')])
        self.combo(io,'frame_edge','帧触发边沿',[('上升沿','RisingEdge'),('下降沿','FallingEdge')])
        self.combo(io,'line_edge','行触发边沿',[('下降沿','FallingEdge'),('上升沿','RisingEdge')])
        self.combo(io,'input_format','输入电气格式',[('保持现状',''),('差分','Differential')],editable=False)
        self.integer(io,'a_debounce_ns','A 相消抖 / ns',0,100000000)
        self.integer(io,'z_debounce_ns','帧触发消抖 / ns',0,100000000)
        lines=[('Line'+str(i),'Line'+str(i)) for i in range(5)]
        self.check(io,'output0_enabled','启用输出 1');self.combo(io,'output0_line','输出 1 信号线',lines)
        self.combo(io,'output0_source','输出 1 信号源',[(option_label(v),v) for v in ('ExposureStartActive','SoftTriggerActive')])
        self.check(io,'output4_enabled','启用输出 2');self.combo(io,'output4_line','输出 2 信号线',lines)
        self.combo(io,'output4_source','输出 2 信号源',[(option_label(v),v) for v in ('ExposureStartActive','SoftTriggerActive')])
        self.combo(io,'output_mode','输出模式',[('频闪','Strobe'),('输出','Output')])
        self.check(io,'strobe_enable','启用频闪')
        self.integer(io,'strobe_duration_us','输出 2 脉宽 / μs',0,100000000)
        self.text(image,'device_name','相机名称 DeviceUserID')
        self.number(image,'exposure_us','曝光 / μs',.01,100000000,3)
        self.number(image,'gain','增益 Gain',0,10000,4)
        self.combo(image,'compression','HB 压缩',[('保持现状',''),('关闭','Off'),('HB','HB')])
        self.integer(image,'digital_shift','数字位移',-1,32,special='保持现状')
        self.text(image,'preamp_gain','前置增益（空=保持）')
        self.combo(image,'pixel_format','像素格式',[('保持现状',''),('Mono8','Mono8'),('BayerRG8','BayerRG8'),('RGB8Packed','RGB8Packed'),('BGR8Packed','BGR8Packed')],editable=False)
        self.check(image,'reverse_x','水平翻转')
        self.number(image,'black_level','黑电平（-1=保持）',-1,65535,2)
        self.integer(image,'width_override','Width / px',0,65536,special='自动计算')
        self.integer(encoder,'height_override','取图高度 / 行',0,1000000,special='自动建议')
        self.integer(encoder,'cycle_idle_lines','最少周期空档 / 行',1,1000000)
        self.integer(calibration,'height_rounding','图高取整步长 / 行',1,100000)
        self.number(encoder,'cycle_travel_mm','每周期实际走料 / mm',0,1000000,6,special='请填写实测距离')
        self.controls['cycle_travel_mm'].setToolTip('测量相邻帧周期之间材料实际行进距离；结合P/R、有效计数倍率和每帧间隔圈数计算脉冲/mm。')
        self.combo(calibration,'frequency_strategy','倍分频算法',[('按实测周期走料匹配Y','cycle'),('按实测每圈走料匹配Y','pitch')])
        self.check(image,'centered_x','X 居中');self.integer(image,'offset_x','OffsetX / px',0,65536)
        self.integer(image,'offset_y','OffsetY / px',0,65536)
        self.number(image,'line_rate_override','手动行频 / Hz',0,100000000,0,special='按产能计算')
        self.check(image,'limit_line_rate','启用手动行频')
        self.check(image,'require_square','要求方形像素');self.number(image,'square_tolerance_percent','X/Y 允许差异 / %',0,100,2)
        self.advanced_button=self.button('更多参数',lambda:None,left);self.advanced_button.setCheckable(True);self.advanced_button.toggled.connect(self.toggle_advanced)
        station.arrange([self.controls[key] for key in ('optics_method','working_distance_mm','target_width_mm','target_length_mm',
            'horizontal_margin_percent','vertical_margin_percent')]+list(self.target_fov_fields.values())+
            [self.controls[key] for key in ('focal_length_mm','pixel_pitch_um','principal_plane_offset_mm')])
        encoder.arrange([self.controls[key] for key in ('auto_frequency','cycle_travel_mm','ppr','edge_factor','encoder_revs',
            'height_override','cycle_idle_lines','pre_divider','multiplier','post_divider')])
        left.addStretch(1)
        self.form_tabs.currentChanged.connect(self.schedule_input_fit)
        self.toggle_advanced(False)
        self.camera_type.currentIndexChanged.connect(self.preset_changed)
        self.optical_mode.currentIndexChanged.connect(self.optical_mode_changed)
        self.language_box.currentIndexChanged.connect(self.language_changed)
        split.addWidget(self.form_panel)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(8,0,0,0);right_layout.setSpacing(10)
        right_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        title=QLabel('计算结果');title.setFixedHeight(28);title.setStyleSheet('font-size:18px;font-weight:600;');right_layout.addWidget(title)
        self.metrics=self.table(['计算项','结果','单位']);self.metrics.setFixedHeight(204);right_layout.addWidget(self.metrics)
        self.optics_summary=QLabel();self.optics_summary.setWordWrap(True);self.optics_summary.setObjectName('Subtle');right_layout.addWidget(self.optics_summary)
        self.frame_preview=FramePreview();right_layout.addWidget(self.frame_preview,1)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setObjectName('Subtle');right_layout.addWidget(self.summary)
        self.result_space=QWidget();right_layout.addWidget(self.result_space,1)
        self.details_button=self.button('查看参数明细',lambda:None,right_layout);self.details_button.setCheckable(True)
        self.tabs=QTabWidget();right_layout.addWidget(self.tabs,1);self.tabs.hide();self.details_button.toggled.connect(self.toggle_details)
        self.node_table=self.table(['选择器 / 上下文','节点','计划值']);self.tabs.addTab(self.node_table,'节点计划')
        self.compare_table=self.table(['上下文 / 节点','当前值','目标值','状态']);self.tabs.addTab(self.compare_table,'相机对比')
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.tabs.addTab(self.log,'执行记录')
        self.device_actions=QWidget();actions=QHBoxLayout(self.device_actions);actions.setContentsMargins(0,0,0,0);self.compare_button=self.button('对比相机参数',lambda:self.start_job('compare'),actions)
        self.export_button=self.button('保存记录',self.export_report,actions);actions.addStretch()
        self.write_button=self.button('写入并保存 UserSet1',self.start_write,actions);self.write_button.setObjectName('Primary');right_layout.addWidget(self.device_actions);self.device_actions.hide()
        self.connection_button.toggled.connect(self.toggle_connection)
        self.result_scroll=QScrollArea();self.result_scroll.setWidgetResizable(True);self.result_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.result_scroll.setWidget(right)
        split.addWidget(self.result_scroll);split.setStretchFactor(0,0);split.setStretchFactor(1,1);split.setSizes([455,705])
        self.form_panel.setMinimumWidth(450)
        self.progress=QProgressBar();self.progress.setFixedHeight(5);self.progress.setTextVisible(False);self.progress.hide();root.addWidget(self.progress)
        self.message=QLabel();self.message.setObjectName('Message');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);root.addWidget(self.message)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.recalculate)
        self.device.currentIndexChanged.connect(self.device_changed)
        self.load_settings(workflow_settings());self.notify('按材料尺寸规划；实际无拉伸需用原始产品图或周期走料标定。')

    @staticmethod
    def button(text,slot,layout):
        result=QPushButton(text);result.clicked.connect(slot);layout.addWidget(result);return result

    @staticmethod
    def table(headers):
        table=QTableWidget(0,len(headers));table.setHorizontalHeaderLabels(headers);table.verticalHeader().hide()
        table.setObjectName('ScriptTable')
        table.setAlternatingRowColors(True);table.setWordWrap(False);table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);return table

    def form_tab(self,title):
        widget=QWidget();form=QFormLayout(widget);form.setContentsMargins(10,12,12,12);form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget);self.form_tabs.addTab(scroll,title);return form

    def register(self,form,key,label,widget):
        self.controls[key]=widget;self.field_forms[key]=form;self.field_titles[key]=label
        caption=QLabel(label);caption.setWordWrap(True);self.labels[key]=caption;form.addRow(caption,widget)
        return widget

    def lockable_number(self,editor):
        key=next(key for key,widget in self.controls.items() if widget is editor)
        editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        editor.setStyleSheet('QAbstractSpinBox {border-top-right-radius:0; border-bottom-right-radius:0;}'
                             'QAbstractSpinBox[vtValueLocked="true"] {background:#edf0f5; color:#526377;}')
        wrapper=QWidget();wrapper.setMinimumWidth(0)
        row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0);row.setSpacing(0)
        row.addWidget(editor,1)
        button=QToolButton();button.setCheckable(True);button.setFixedSize(34,36);button.setIconSize(QSize(20,20))
        button.setStyleSheet('QToolButton {background:#f5f7fa; border:1px solid #c8d1dd; border-left:0;'
                            'border-top-right-radius:7px; border-bottom-right-radius:7px;}'
                            'QToolButton:hover {background:#e8eef4;} QToolButton:checked {background:#fff0e4;}'
                            'QToolButton:focus {border-color:#b5531c;}')
        self.lock_buttons[key]=button;row.addWidget(button)
        button.toggled.connect(lambda checked,key=key:self.toggle_value_lock(key,checked))
        button.setIcon(value_lock_icon(False))
        return wrapper

    def refresh_value_locks(self):
        for key,button in self.lock_buttons.items():
            locked=key in self.fixed_values;editor=self.controls[key]
            editor.setReadOnly(locked)
            if editor.property('vtValueLocked')!=locked:
                editor.setProperty('vtValueLocked',locked);editor.style().unpolish(editor);editor.style().polish(editor)
            button.setIcon(value_lock_icon(locked))
            name=FIELD_LABELS.get(key,key) if self.language=='en' else self.field_titles[key].split(' / ')[0]
            text=(('Unlock ' if locked else 'Fix ')+name) if self.language=='en' else (('解除固定：' if locked else '固定数值：')+name)
            button.setToolTip(text);button.setAccessibleName(text)

    def toggle_value_lock(self,key,locked):
        if self._loading:return
        if locked:
            self.controls[key].interpretText();self.fixed_values[key]=self.controls[key].value()
        else:self.fixed_values.pop(key,None)
        self.refresh_value_locks();self.recalculate()

    def clear_value_locks(self):
        self.fixed_values.clear()
        for button in self.lock_buttons.values():
            blocked=button.blockSignals(True);button.setChecked(False);button.blockSignals(blocked)
        self.refresh_value_locks()

    def set_calculated_value(self,key,value):
        widget=self.controls[key]
        if key in self.fixed_values:
            decimals={key:widget.decimals()}
            if not within_precision(key,value,self.fixed_values[key],decimals):
                raise CameraError('固定值冲突：'+self.field_titles[key].split(' / ')[0]+'不能随计算改变，请解除锁定或调整其他条件。')
            return
        if not widget.minimum()<=value<=widget.maximum():raise CameraError('计算结果超出输入范围：'+self.field_titles[key])
        blocked=widget.blockSignals(True);widget.setValue(value);widget.blockSignals(blocked)

    def number(self,form,key,label,low,high,decimals,special=None):
        widget=QDoubleSpinBox();widget.setDecimals(decimals);widget.setRange(low,high);widget.setKeyboardTracking(False)
        if special:widget.setSpecialValueText(special)
        self.register(form,key,label,widget);widget.valueChanged.connect(lambda _,key=key:self.parameter_changed(key))

    def integer(self,form,key,label,low,high,special=None):
        widget=QSpinBox();widget.setRange(low,high);widget.setKeyboardTracking(False)
        if special:widget.setSpecialValueText(special)
        self.register(form,key,label,widget);widget.valueChanged.connect(lambda _,key=key:self.parameter_changed(key))

    def combo(self,form,key,label,items,editable=False):
        widget=self.styled_combo();widget.setEditable(editable)
        for text,value in items:widget.addItem(text,value)
        self.register(form,key,label,widget);widget.currentIndexChanged.connect(lambda _,key=key:self.parameter_changed(key))
        if editable:widget.editTextChanged.connect(self.changed)

    @staticmethod
    def styled_combo():
        return make_combo()

    def text(self,form,key,label):
        widget=QLineEdit();self.register(form,key,label,widget);widget.textChanged.connect(self.changed)

    def check(self,form,key,label):
        widget=QCheckBox(label);widget.setMinimumHeight(28);self.controls[key]=widget;self.field_forms[key]=form;self.field_titles[key]=label
        caption=form.addRow(widget)
        if isinstance(caption,QLabel):self.labels[key]=caption
        widget.toggled.connect(self.changed)

    def trigger_group(self,form,key,title,default):
        group=QWidget();layout=QVBoxLayout(group);layout.setContentsMargins(0,6,0,10);layout.setSpacing(8)
        label=QLabel(title);label.setStyleSheet('font-weight:600;');layout.addWidget(label)
        choice=self.styled_combo()
        for i in range(5):choice.addItem('Line'+str(i),'Line'+str(i))
        choice.setCurrentIndex(choice.findData(default));layout.addWidget(choice);choice.currentIndexChanged.connect(self.changed)
        self.controls[key]=choice;self.labels[key]=label;self.field_titles[key]=title
        form.addRow(group);return group

    def preset_changed(self,*args):
        if self._loading:return
        preset=PRESETS.get(self.camera_type.currentData())
        if not preset:
            s=self.settings(validate=False);s.camera_model_id='';self.load_settings(s,preserve_locks=True);return
        s=self.settings(validate=False)
        if s.framing_source!='legacy':s.framing_source='material'
        for key in ('kind','sensor_width','sensor_height','pixel_pitch_um'):setattr(s,key,preset[key])
        s.camera_model_id=preset['model'];s.focal_length_mm=preset['focal_length_mm'];s.pixel_format='Mono8' if not preset['color'] else ''
        s.width_override=s.height_override=0;s.centered_x=True;s.offset_x=s.offset_y=0
        s.frame_selector='FrameBurstStart' if s.kind=='line' else 'FrameStart'
        s.frame_line='Line3' if s.kind=='line' else 'Line0';s.frame_edge='RisingEdge'
        if s.kind=='line':
            s.encoder_line='Line1';s.line_edge='FallingEdge';s.input_format='Differential'
            s.a_debounce_ns=300;s.z_debounce_ns=1000;s.pre_divider=1;s.multiplier=3;s.post_divider=1
            s.output0_enabled=True;s.output0_line='Line0';s.output0_source='ExposureStartActive'
            s.output4_enabled=False;s.output4_line='Line4';s.output4_source='SoftTriggerActive'
        else:
            s.input_format='';s.output0_enabled=False;s.output4_enabled=False;s.pixel_format='';s.compression=''
        for key,value in self.fixed_values.items():
            if not within_precision(key,getattr(s,key),value,{key:self.controls[key].decimals()}):
                self.sync_preset();self.preview=None;self.update_actions()
                self.notify('新相机参数与固定值冲突，请先解除'+self.field_titles[key].split(' / ')[0]+'锁定。',True);return
        self.geometry=None;self.output_caps={};self.load_settings(s,preserve_locks=True)

    def sync_preset(self):
        kind=self.controls['kind'].currentData();width=self.controls['sensor_width'].value();height=self.controls['sensor_height'].value()
        key=next((name for name,p in PRESETS.items() if p['model']==self.controls['camera_model_id'].text() and p['kind']==kind and p['sensor_width']==width and p['sensor_height']==height and abs(p['pixel_pitch_um']-self.controls['pixel_pitch_um'].value())<.0001),'custom')
        if self.camera_type.findData(key)<0:self.camera_type.addItem(option_label(key,self.language),key)
        previous=self.camera_type.blockSignals(True);self.camera_type.setCurrentIndex(self.camera_type.findData(key));self.camera_type.blockSignals(previous)
        preset=PRESETS.get(key);spec=str(width)+(' × '+str(height) if kind=='area' else '')+' px'
        self.camera_info.setText(spec+' · '+str(self.controls['pixel_pitch_um'].value())+' μm'+('\n'+preset['lens_model']+' · '+str(preset['focal_length_mm'])+' mm' if preset else ' · 自定义 / 设备读回'))
        self.camera_info.setToolTip(preset['source'] if preset else '配置未匹配完整型号；固定参数可在工位标定中编辑。')

    def optical_mode_changed(self,*args):
        if self._loading:return
        value=self.optical_mode.currentData();self._loading=True
        self.controls['framing_source'].setCurrentIndex(self.controls['framing_source'].findData('legacy'))
        source=value if value in ('fov','precision') else 'optics'
        self.controls['precision_source'].setCurrentIndex(self.controls['precision_source'].findData(source))
        if source=='optics':self.controls['optics_direction'].setCurrentIndex(self.controls['optics_direction'].findData(value))
        self._loading=False;self.changed()

    def language_changed(self,*args):
        self.language=self.language_box.currentData() or 'zh';self.translate_options();self.enable_fields()
        QTimer.singleShot(0,self.fit_result_text)

    def translate_options(self):
        en=self.language=='en'
        for key,label in self.labels.items():
            original=self.field_titles.get(key,label.text());is_table=isinstance(self.field_forms.get(key),PropertyForm)
            name,_,unit=original.partition(' / ')
            text=FIELD_LABELS.get(key,key.replace('_',' ').title()) if en else (name if is_table else original)
            if en and unit and not is_table:text+=' / '+unit.replace('片/分','parts/min').replace('行','line')
            label.setText(text)
        for key,widget in self.controls.items():
            if isinstance(widget,QCheckBox) and key not in self.labels:widget.setText(FIELD_LABELS.get(key,key.replace('_',' ').title()) if en else self.field_titles[key])
        for widget in [self.camera_type,self.optical_mode,*[w for w in self.controls.values() if isinstance(w,QComboBox)]]:
            blocked=widget.blockSignals(True)
            for i in range(widget.count()):
                value=widget.itemData(i)
                if value in LABELS or value in PRESETS:widget.setItemText(i,option_label(value,self.language))
            widget.blockSignals(blocked)
        names=['Material & FOV','Encoder & Height','Trigger','Digital IO','Calibration','Imaging'] if en else ['材料与视野','编码器与图高','采集触发','数字 IO','专业标定','成像']
        for i,name in enumerate(names):self.form_tabs.setTabText(i,name)
        self.optical_mode_label.setText('Calculate' if en else '计算方向')
        for form in self.property_forms:form.table.setHorizontalHeaderLabels(['Parameter','Value','Unit'] if en else ['参数','设置值','单位'])
        for key,caption in self.target_fov_labels.items():
            caption.setText(('Target FOV width / mm' if key=='target_fov_width_mm' else 'Target FOV length / mm') if en else
                            ('视野宽度（目标宽度） / mm' if key=='target_fov_width_mm' else '视野长度（目标长度） / mm'))
        self.sync_preset();self.refresh_output_choices()

    def refresh_output_choices(self):
        for prefix in ('output0','output4'):
            widget=self.controls[prefix+'_source'];current=widget.currentData();line=self.controls[prefix+'_line'].currentData()
            cap=self.output_caps.get(line,{})
            choices=cap.get('choices',[]) if cap.get('status')=='readable' else ['ExposureStartActive','SoftTriggerActive']
            choices=list(dict.fromkeys([*choices,*([current] if current is not None else [])]))
            blocked=widget.blockSignals(True);widget.clear()
            for value in choices:widget.addItem(option_label(value,self.language),value)
            widget.setCurrentIndex(widget.findData(current));widget.blockSignals(blocked)
            widget.setToolTip(('Read from camera' if self.language=='en' else '已从相机读取支持的枚举') if cap.get('status')=='readable' else ('Reference values; confirm on device' if self.language=='en' else '参考配置选项；连接后按设备能力核对'))
            if cap.get('status')=='readable' and current not in cap.get('choices',[]):
                widget.setToolTip('Configured value is not supported; select a device option.' if self.language=='en' else '当前配置值不在设备支持列表中，请选择设备选项。')

    def apply_enum_choices(self,key,choices):
        if not choices:return
        widget=self.controls[key];current=widget.currentData();blocked=widget.blockSignals(True);widget.clear()
        for value in dict.fromkeys([*choices,*([current] if current is not None else [])]):widget.addItem(option_label(value,self.language),value)
        widget.setCurrentIndex(widget.findData(current));widget.blockSignals(blocked)

    @staticmethod
    def note(form,text):
        label=QLabel(text);label.setWordWrap(True);label.setObjectName('Subtle');form.addRow(label)

    def load_settings(self,settings,preserve_locks=False):
        if settings.kind=='line' and not settings.auto_frequency and any(not 1<=getattr(settings,k)<=5 for k in ('pre_divider','multiplier','post_divider')):
            raise CameraError('旧配置的手动倍分频超出1～5，请先修正配置后导入。')
        self._loading=True
        if not preserve_locks:self.clear_value_locks()
        for key,value in asdict(settings).items():
            widget=self.controls[key]
            if isinstance(widget,QCheckBox):widget.setChecked(value)
            elif isinstance(widget,QComboBox):
                index=widget.findData(value)
                if index<0:widget.addItem('旧配置换算值 · 待确认' if key=='line_y_source' and value=='legacy' else str(value),value);index=widget.count()-1
                widget.setCurrentIndex(index)
            elif isinstance(widget,QLineEdit):widget.setText(value)
            else:widget.setValue(value)
        source=settings.precision_source;mode=settings.optics_direction if source=='optics' else source
        if self.optical_mode.findData(mode)<0:self.optical_mode.addItem(option_label(mode,self.language),mode)
        self.optical_mode.setCurrentIndex(self.optical_mode.findData(mode))
        self._loading=False;self.translate_options();self.recalculate()

    def settings(self,validate=True):
        values={}
        for key,widget in self.controls.items():
            if isinstance(widget,QCheckBox):value=widget.isChecked()
            elif isinstance(widget,QComboBox):value=widget.currentData() if widget.currentIndex()>=0 and widget.currentText()==widget.itemText(widget.currentIndex()) else widget.currentText().strip()
            elif isinstance(widget,QLineEdit):value=widget.text().strip()
            else:value=widget.value()
            values[key]=value
        result=CameraSettings(**values)
        return result.validate() if validate else result

    def parameter_changed(self,key):
        if self._loading:return
        if key in self.fixed_values:
            widget=self.controls[key];blocked=widget.blockSignals(True)
            widget.setValue(self.fixed_values[key]);widget.blockSignals(blocked);return
        selector=self.controls['framing_source']
        if selector.currentData()!='legacy':
            source=('distance' if key=='working_distance_mm' else 'material' if key in
                    ('target_width_mm','target_length_mm','horizontal_margin_percent','vertical_margin_percent',
                     'optics_method','focal_length_mm','pixel_pitch_um','principal_plane_offset_mm','sensor_width','sensor_height') else None)
            if source is not None:
                blocked=selector.blockSignals(True);selector.setCurrentIndex(selector.findData(source));selector.blockSignals(blocked)
        self.changed()

    def changed(self,*args):
        if self._loading:return
        self.preview=None;self.write_button.setEnabled(False);self.timer.start(180)

    def enable_fields(self):
        line=self.controls['kind'].currentData()=='line';source=self.controls['precision_source'].currentData();fov=source=='fov';optics=source=='optics'
        line_only=('auto_frequency','encoder_travel_mm_per_rev','frequency_tolerance_percent','ppr','edge_factor','encoder_revs','pre_divider','multiplier','post_divider','rate_margin_percent',
                   'line_edge','a_debounce_ns','line_rate_override','limit_line_rate','line_y_source')
        for key in line_only:
            self.controls[key].setEnabled(line);self.field_forms[key].setRowVisible(self.controls[key],line)
        self.line_trigger_group.setVisible(line);self.encoder_trigger_group.setVisible(line);self.controls['encoder_line'].setEnabled(line)
        self.line_trigger_title.setText('Line trigger' if self.language=='en' else '行触发')
        self.line_trigger_source.setItemText(0,'Frequency converter output' if self.language=='en' else '频率转换器输出')
        self.controls['sensor_height'].setEnabled(not line);self.controls['offset_y'].setEnabled(not line)
        self.controls['fov_width_mm'].setEnabled(fov);self.controls['fov_height_mm'].setEnabled(fov and not line)
        ysource=self.controls['line_y_source'].currentData()
        y_visible=(line and ysource in ('precision','legacy')) or (not line and source=='precision')
        inverse=self.controls['optics_direction'].currentData()=='precision_to_wd'
        self.controls['x_mm_per_px'].setEnabled(source=='precision' or (optics and inverse));self.controls['y_mm_per_px'].setEnabled(y_visible)
        self.controls['working_distance_mm'].setEnabled(optics and not inverse)
        known=self.camera_type.currentData() in PRESETS
        self.controls['focal_length_mm'].setEnabled(optics and not known);self.controls['pixel_pitch_um'].setEnabled(optics and not known)
        automatic=line and self.controls['auto_frequency'].isChecked()
        self.controls['encoder_travel_mm_per_rev'].setEnabled(automatic)
        for key in ('pre_divider','multiplier','post_divider'):self.controls[key].setEnabled(line and not automatic)
        self.controls['sensor_width'].setEnabled(not known);self.controls['sensor_height'].setEnabled(not known and not line)
        self.controls['camera_model_id'].setReadOnly(True)
        for key,visible in {'pixel_pitch_um':not known,'working_distance_mm':source!='fov','focal_length_mm':source!='fov'}.items():
            self.field_forms[key].setRowVisible(self.controls[key],visible)
        self.field_forms['principal_plane_offset_mm'].setRowVisible(self.controls['principal_plane_offset_mm'],optics and self.controls['optics_method'].currentData()=='thin_lens')
        self.controls['line_rate_override'].setEnabled(line and self.controls['limit_line_rate'].isChecked())
        for key,visible in {'sensor_height':not line,'fov_width_mm':fov,'fov_height_mm':fov and not line,
                            'y_mm_per_px':y_visible,'line_y_source':line,
                            'calibration_length_mm':line and ysource=='calibration','calibration_rows':line and ysource=='calibration',
                            'kind':False,'precision_source':False,'optics_direction':False,'frame_selector':False}.items():
            self.field_forms[key].setRowVisible(self.controls[key],visible)
        self.controls['offset_x'].setEnabled(not self.controls['centered_x'].isChecked())
        for prefix in ('output0','output4'):
            for suffix in ('line','source'):self.controls[prefix+'_'+suffix].setEnabled(self.controls[prefix+'_enabled'].isChecked())
        self.controls['strobe_duration_us'].setEnabled(self.controls['output4_enabled'].isChecked())
        self.trigger_help.setText(('Frame trigger only.' if self.language=='en' else '面阵仅使用帧触发。') if not line else ('Encoder A → FrequencyConverter → LineStart.' if self.language=='en' else '编码器 A 相 → 频率转换器 → 行触发。'))
        framing=self.controls['framing_source'].currentData();workflow=framing!='legacy';cycle=line and self.controls['frequency_strategy'].currentData()=='cycle'
        self.field_forms['framing_source'].setRowVisible(self.controls['framing_source'],False)
        margin=self.controls['horizontal_margin_percent'];blocked=margin.blockSignals(True)
        margin.setRange(-100 if workflow else 0,1e15 if workflow else 1000)
        margin.blockSignals(blocked)
        self.controls['working_distance_mm'].setEnabled(workflow or (optics and not inverse))
        self.controls['horizontal_margin_percent'].setEnabled(workflow)
        self.field_forms['horizontal_margin_percent'].setRowVisible(self.controls['horizontal_margin_percent'],workflow)
        self.field_forms['vertical_margin_percent'].setRowVisible(self.controls['vertical_margin_percent'],workflow)
        for field in self.target_fov_fields.values():self.parameter_form.setRowVisible(field,workflow)
        for key in ('image_horizontal_margin_mm','image_vertical_margin_mm'):
            self.field_forms[key].setRowVisible(self.controls[key],not workflow)
        if workflow:
            self.field_forms['working_distance_mm'].setRowVisible(self.controls['working_distance_mm'],True)
            self.field_forms['focal_length_mm'].setRowVisible(self.controls['focal_length_mm'],not known)
            self.controls['x_mm_per_px'].setEnabled(False)
        self.field_forms['encoder_travel_mm_per_rev'].setRowVisible(self.controls['encoder_travel_mm_per_rev'],line and not cycle)
        self.field_forms['cycle_travel_mm'].setRowVisible(self.controls['cycle_travel_mm'],cycle)
        for key in ('pre_divider','multiplier','post_divider'):
            self.field_forms[key].setRowVisible(self.controls[key],line and not self.controls['auto_frequency'].isChecked())
        for key in ('cycle_idle_lines','height_rounding'):self.field_forms[key].setRowVisible(self.controls[key],cycle)
        if cycle:
            for key in ('line_y_source','y_mm_per_px','calibration_length_mm','calibration_rows'):
                self.field_forms[key].setRowVisible(self.controls[key],False)
        self.sync_preset();self.refresh_output_choices()
        self.form_tabs.setTabVisible(1,line)
        self.refresh_value_locks()

    def toggle_advanced(self,expanded):
        if not expanded and self.form_tabs.currentIndex()>=self.basic_tab_count:self.form_tabs.setCurrentIndex(0)
        for i in range(self.basic_tab_count,self.form_tabs.count()):self.form_tabs.setTabVisible(i,expanded)
        if self.controls['kind'].currentData()=='area':self.form_tabs.setTabVisible(1,False)
        self.form_tabs.tabBar().show()
        self.advanced_button.setText(('Less' if expanded else 'More settings') if self.language=='en' else ('收起更多' if expanded else '更多参数'))
        if expanded:self.form_tabs.setCurrentIndex(4)

    def toggle_details(self,expanded):
        self.tabs.setVisible(expanded);self.frame_preview.setVisible(not expanded and self.height()>=680)
        self.result_space.setVisible(not expanded)
        self.details_button.setText('收起参数明细' if expanded else '查看参数明细')
        QTimer.singleShot(0,self.fit_result_text)

    def toggle_connection(self,expanded):
        self.devices_bar.setVisible(expanded);self.device_actions.setVisible(expanded)
        QTimer.singleShot(0,self.fit_result_text)

    def showEvent(self,event):
        super().showEvent(event);QTimer.singleShot(0,self.fit_metrics)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'details_button'):
            self.frame_preview.setVisible(not self.details_button.isChecked() and self.height()>=680)
            QTimer.singleShot(0,self.fit_metrics)

    def fit_result_text(self):
        for label in (self.optics_summary,self.summary):
            width=max(100,label.width())
            label.setFixedHeight(max(label.fontMetrics().height(),label.heightForWidth(width)))

    def schedule_input_fit(self,*_):
        if not self._input_fit_pending:
            self._input_fit_pending=True;QTimer.singleShot(0,self.fit_input_panel)

    def fit_input_panel(self):
        self._input_fit_pending=False
        content=self.form_tabs.currentWidget().widget()
        if content is None:return
        content.layout().activate()
        form=next((form for form in self.input_forms if form.widget is content),None)
        content_height=form.content_height() if form is not None else content.layout().sizeHint().height()
        if form is not None:content.setMinimumHeight(content_height)
        desired=content_height+self.form_tabs.tabBar().sizeHint().height()+16
        available=self.form_panel.height()-self.camera_type.height()-self.camera_info.sizeHint().height()-self.advanced_button.sizeHint().height()-38
        self.form_tabs.setFixedHeight(min(max(180,desired),max(180,available)))

    def fit_metrics(self):
        header=self.metrics.horizontalHeader();header.ensurePolished()
        self.metrics.setFixedHeight(max(header.height(),header.sizeHint().height())+sum(self.metrics.rowHeight(i) for i in range(self.metrics.rowCount()))+2*self.metrics.frameWidth()+4)
        for form in self.property_forms:form.fit()
        self.schedule_input_fit()
        QTimer.singleShot(0,self.fit_result_text)

    @staticmethod
    def fill(table,rows):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):
                text=str(value);item=QTableWidgetItem(text);item.setToolTip(text);table.setItem(i,j,item)

    @staticmethod
    def material_pixels_row(metrics):
        return ('材料像素（宽 × 高）',str(metrics['material_width_px'])+' × '+str(metrics['material_height_px']),'px')

    def set_material_pixels_tooltip(self,row,metrics):
        text=('按材料宽长除以当前X/Y精度后向上取整，不含余量；矩形规划共 '+format(metrics['material_pixel_count'],',')+
              ' 像素。线扫Y未标定时为规划值。')
        for column in range(3):self.metrics.item(row,column).setToolTip(text)

    def render_plan(self,plan):
        if plan['settings']['framing_source']!='legacy':return self.render_workflow(plan)
        self.plan=plan;m=plan['metrics']
        metrics=[('整张图宽 × 高',str(m['width'])+' × '+str(m['height']),'px'),
            ('产品高度',str(m['product_height_lines']),'行'),
            ('前后背景行数',str(m['background_height_lines']),'行'),
            ('X / Y 精度',format(m['x_mm_per_px'],'.6f')+' / '+format(m['y_mm_per_px'],'.6f'),'mm/px')]
        if m['line_triggers_per_cycle'] is not None:metrics.append(('预计外部行频',format(m['required_line_rate_hz'],'.0f'),'Hz'))
        elif plan['settings']['kind']=='line':metrics.append(('预计外部行频','待测量','Hz'))
        else:metrics.append(('产品帧频',format(m['frame_rate_hz'],'.3f'),'Hz'))
        metrics.append(self.material_pixels_row(m))
        self.fill(self.metrics,metrics)
        self.set_material_pixels_tooltip(len(metrics)-1,m)
        self.fit_metrics()
        self.frame_preview.plan=plan;self.frame_preview.update()
        self.fill(self.node_table,[[', '.join(n['selectors'].values()) or '全局',n['key'],n['value']] for n in plan['nodes']])
        if plan['blocking']:text='；'.join(plan['blocking'])
        elif plan['settings']['kind']=='line':text='帧触发后采满 '+str(m['height'])+' 行出图；产品预计占 '+str(m['product_height_lines'])+' 行。'
        else:text='按当前视野计算，产品和留白均在取图范围内。'
        if plan['settings']['precision_source']=='optics':text+=(' 薄透镜模型：主平面未知时仍需实测校准。' if plan['settings']['optics_method']=='thin_lens' else ' 快速估算值需用实测视野校准。')
        elif plan['settings']['precision_source']=='fov':text+=' 按未缩放全幅视野标定；此模式不反算机械工作距离。'
        if plan['settings']['kind']=='line' and plan['settings']['line_y_source']=='square':text+=' Y 精度为方形像素规划值。'
        if plan['settings']['kind']=='line' and plan['settings']['line_y_source']=='legacy':text+=' 请在工位标定中确认旧配置的 Y 精度。'
        self.summary.setText(text);self.summary.setToolTip('\n'.join(plan['blocking']+plan['warnings']))
        self.optics_summary.setVisible(plan['settings']['optics_method']=='thin_lens' or plan['settings']['precision_source']=='fov')
        self.optics_summary.setText('有效感光宽度 '+format(m['sensor_active_width_mm'],'.4f')+' mm · 横向视野 '+format(m['fov_width_mm'],'.3f')+' mm'+('\n光学倍率 '+format(m['optical_magnification'],'.5f')+' ×' if m['optical_magnification'] else ''))
        if m['frequency_solution'] and m['y_sampling_error_percent'] is not None:
            solution=m['frequency_solution'];self.optics_summary.show()
            self.optics_summary.setText(self.optics_summary.text()+'\n预分频 / 倍频 / 后分频：'+str(solution['pre_divider'])+' / '+str(solution['multiplier'])+' / '+str(solution['post_divider'])+' · Y采样误差 '+format(m['y_sampling_error_percent'],'.4f')+'%'+(' · 设备范围已核对' if solution['limits_verified'] else ' · 离线建议，待设备核对'))

    def render_workflow(self,plan):
        self.plan=plan;s=plan['settings'];m=plan['metrics'];line=s['kind']=='line'
        pending=m['frequency_pending'];measured=m['cycle_calibrated']
        rows=[('视野宽 / 工作距离',format(m['fov_width_mm'],'.3f')+' / '+format(m['working_distance_mm'],'.3f'),'mm'),
              ('实际精度 X / Y' if measured else '方形像素规划' if line else '光学像素精度',
               format(m['x_mm_per_px'],'.6f')+' / '+format(m['y_mm_per_px'],'.6f') if measured else format(m['x_mm_per_px'],'.9f'),'mm/px'),
              ('材料目标行数' if line else '产品最少行数',str(m['square_pixel_product_lines'] if line else m['product_height_lines']),'行'),
              self.material_pixels_row(m),
              ('取图宽 × 高',str(m['width'])+' × '+str(m['height']),'px')]
        if line:
            rows.extend([('预分 / 倍频 / 后分','待测量' if pending else str(s['pre_divider'])+' / '+str(s['multiplier'])+' / '+str(s['post_divider']),''),
                         ('周期总行触发','待测量' if pending else format(m['line_triggers_per_cycle'],'.6g'),'次'),
                         ('周期剩余空档','待测量' if pending else str(m['cycle_idle_available']),'行')])
        else:rows.append(('产品帧频',format(m['frame_rate_hz'],'.3f'),'Hz'))
        self.fill(self.metrics,rows);self.set_material_pixels_tooltip(3,m);self.fit_metrics();self.frame_preview.plan=plan;self.frame_preview.update()
        self.fill(self.node_table,[[', '.join(n['selectors'].values()) or '全局',n['key'],n['value']] for n in plan['nodes']])
        self.optics_summary.show()
        text=('规划覆盖 ' if line and s['frequency_strategy']=='cycle' and not measured else '实际覆盖 ')+format(m['coverage_width_mm'],'.3f')+' × '+format(m['coverage_height_mm'],'.3f')+' mm · 图内背景 '+str(m['background_height_lines'])+' 行'
        if measured:text+='\n材料占周期 '+format(m['material_cycle_fraction']*100,'.2f')+'% · 输入 '+format(m['encoder_counts_per_mm'],'.3f')+' 脉冲/mm · 预计行频 '+format(m['required_line_rate_hz'],'.0f')+' Hz'
        elif pending:text+='\n填写实测周期走料后，自动计算脉冲/mm和倍分频。'
        elif line:text+=' · 预计行频 '+format(m['required_line_rate_hz'],'.0f')+' Hz'
        self.optics_summary.setText(text)
        if plan['blocking']:message='；'.join(plan['blocking'])
        elif measured:
            message='Y 采样偏差 '+format(m['y_sampling_error_percent'],'+.2f')+'% · 允许 ±'+format(s['frequency_tolerance_percent'],'.3g')+'% · 前后位置由下位机相位调整。'
        else:message='按当前视野计算；镜头模型值请用实测视野核对。'
        self.summary.setText(message);self.summary.setToolTip('\n'.join(plan['blocking']+plan['warnings']))

    def recalculate(self):
        self.timer.stop();self.preview=None;self.write_button.setEnabled(False)
        try:
            self.enable_fields();limits=self.geometry.get('limits') if self.geometry else None
            if self.fixed_values:
                settings=resolve_fixed_values(self.settings(),self.fixed_values,
                    {key:widget.decimals() for key,widget in self.controls.items() if isinstance(widget,QDoubleSpinBox)},limits)
                selector=self.controls['framing_source'];blocked=selector.blockSignals(True)
                selector.setCurrentIndex(selector.findData(settings.framing_source));selector.blockSignals(blocked)
                for key in ('target_width_mm','working_distance_mm','horizontal_margin_percent'):
                    self.set_calculated_value(key,getattr(settings,key))
            plan=calculate(self.settings(),limits)
            if plan['settings']['framing_source']!='legacy':
                key='working_distance_mm' if plan['settings']['framing_source']=='material' else 'x_mm_per_px'
                widget=self.controls[key];value=plan['metrics'][key]
                if not widget.minimum()<=value<=widget.maximum():raise CameraError('计算结果超出输入范围，请调整视野或镜头参数。')
                self.set_calculated_value(key,value)
                if plan['settings']['framing_source']=='distance':
                    self.set_calculated_value('horizontal_margin_percent',plan['metrics']['horizontal_margin_percent_actual'])
                plan=calculate(self.settings(),limits)
            elif plan['settings']['precision_source']=='optics':
                key='working_distance_mm' if plan['settings']['optics_direction']=='precision_to_wd' else 'x_mm_per_px'
                value=plan['metrics'][key];widget=self.controls[key]
                if not widget.minimum()<=value<=widget.maximum():raise CameraError('计算结果超出输入控件范围，请调整镜头或目标精度。')
                self.set_calculated_value(key,value)
                plan=calculate(self.settings(),limits)
            elif plan['settings']['precision_source']=='fov':
                widget=self.controls['x_mm_per_px'];blocked=widget.blockSignals(True)
                widget.setValue(plan['metrics']['x_mm_per_px']);widget.blockSignals(blocked)
                plan=calculate(self.settings(),limits)
            if plan['metrics']['frequency_solution']:
                self.sync_frequency(plan);plan=calculate(self.settings(),limits)
            for key,field in self.target_fov_fields.items():field.setText(format(plan['metrics'][key],'.3f'))
            self.render_plan(plan);self.update_actions()
            self.notify('；'.join(self.plan['blocking']) if self.plan['blocking'] else '',bool(self.plan['blocking']) and not (
                self.plan['metrics']['frequency_pending'] and len(self.plan['blocking'])==1))
            return self.plan
        except Exception as exc:
            self.plan=None;self.metrics.setRowCount(0);self.frame_preview.plan=None;self.frame_preview.update();self.summary.clear();self.optics_summary.clear()
            for field in self.target_fov_fields.values():field.clear()
            self.notify(str(exc),True);self.update_actions();return None

    def selected_uid(self):return self.device.currentData()

    def sync_frequency(self,plan):
        for key in ('pre_divider','multiplier','post_divider'):
            widget=self.controls[key];blocked=widget.blockSignals(True);widget.setValue(plan['settings'][key]);widget.blockSignals(blocked)

    def update_actions(self):
        selected=bool(self.selected_uid());busy=self.is_busy()
        self.inspect_button.setEnabled(selected and not busy);self.compare_button.setEnabled(selected and self.plan is not None and not busy)
        self.write_button.setEnabled(bool(self.preview and self.preview.get('ready')) and not busy)
        self.export_button.setEnabled(self.last_report is not None and not busy)

    def device_changed(self,*args):
        self.geometry=None;self.preview=None;self.last_report=None;self.output_caps={}
        if hasattr(self,'write_button'):self.refresh_output_choices();self.update_actions()

    def choose_sdk(self):
        path=QFileDialog.getExistingDirectory(self,'选择MVS安装目录或MvImport目录',self.sdk)
        if path:
            try:self.sdk=discover_mvs(path);self.device.clear();self.device.addItem('请重新枚举相机',None);self.notify('MVS目录已更新。')
            except Exception as exc:self.notify(str(exc),True)

    def start_job(self,action):
        if self.is_busy():return
        if action!='scan' and not self.selected_uid():self.notify('请先枚举并选择目标相机。',True);return
        try:
            if action=='scan':payload={}
            elif action=='inspect':payload={'uid':self.selected_uid()}
            else:
                settings=self.settings();self.preview=None;payload={'uid':self.selected_uid(),'settings':config_dict(settings)}
            self.launch(action,payload)
        except Exception as exc:self.notify(str(exc),True)

    def start_write(self):
        if self.is_busy() or not self.preview or not self.preview['ready']:return
        if fingerprint(config_dict(self.settings()))!=self.preview['settings_fingerprint']:
            self.preview=None;self.update_actions();self.notify('配置已变化，请重新对比。',True);return
        self.launch('write',self.preview)

    def launch(self,action,payload):
        self.worker=CameraJob(action,payload,self.sdk,self);self.worker.result.connect(self.finished_result)
        self.worker.failed.connect(self.failed);self.worker.progress.connect(self.notify);self.worker.finished.connect(self.stopped)
        self.form_panel.setEnabled(False);self.devices_bar.setEnabled(False)
        self.files_button.setEnabled(False);self.connection_button.setEnabled(False);self.language_box.setEnabled(False)
        self.compare_button.setEnabled(False);self.write_button.setEnabled(False);self.export_button.setEnabled(False)
        self.progress.setRange(0,0);self.progress.show();self.notify({'scan':'正在枚举相机…','inspect':'正在读取设备尺寸与范围…','compare':'正在读取选择器分组并对比参数…','write':'正在写入所选相机…'}[action]);self.worker.start()

    def finished_result(self,action,data):
        if action=='scan':
            self.device.clear()
            if not data['devices']:self.device.addItem('未发现 GigE / USB3 或对应虚拟相机',None)
            for d in data['devices']:self.device.addItem(d['model']+' · '+d['serial']+' · '+d.get('ip',d['transport']),d['uid'])
            self.notify('MVS '+data['sdk_version']+'：发现 '+str(len(data['devices']))+' 台相机。'+('请检查供电、网络与设备连接。' if not data['devices'] else '请选择目标后读取设备尺寸。'))
            self.last_report=data
        elif action=='inspect':
            self.geometry=data;self.output_caps=data.get('output_source_choices',{});s=self.settings(validate=False);s.sensor_width=data['sensor_width']
            scan=data.get('scan_type','').lower()
            if 'line' in scan:s.kind='line'
            elif 'area' in scan:s.kind='area';s.frame_selector='FrameStart'
            if s.kind=='area':s.sensor_height=data['sensor_height']
            model=data['device'].get('model','');matched=next((p for p in PRESETS.values() if model==p['model']),None)
            s.camera_model_id=matched['model'] if matched else ''
            if matched:
                s.pixel_pitch_um=matched['pixel_pitch_um']
                s.focal_length_mm=matched['focal_length_mm']
                if s.kind=='line':s.sensor_height=matched['sensor_height']
            elif s.precision_source=='optics':s.pixel_pitch_um=0
            if data.get('pixel_format'):s.pixel_format=data['pixel_format']['value']
            self.load_settings(s);self.notify('已读取 '+data['device']['model']+' / '+data['device']['serial']+'；'+('请核对镜头像元与工位标定。' if not matched else '精度标定沿用工位配置。'))
            self.apply_enum_choices('pixel_format',['',*data.get('pixel_format',{}).get('choices',[])])
            for key,choices in data.get('trigger_io_choices',{}).items():self.apply_enum_choices(key,choices)
            self.log.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
            self.last_report=data
        elif action=='compare':
            self.sync_frequency(data['plan'])
            self.preview=data;self.last_report=data;self.geometry=data['geometry'];self.render_plan(data['plan'])
            for row in data['rows']:
                if row['entry']['key']=='LineSource' and row.get('capability'):
                    cap=row['capability'];line=row['entry']['selectors'].get('LineSelector')
                    self.output_caps[line]={'status':'readable','choices':cap.get('choices',[]),'value':cap['value'],'writable':cap['writable']}
                if row.get('capability'):
                    key=row['entry']['key'];choices=row['capability'].get('choices',[])
                    if key=='PixelFormat':self.apply_enum_choices('pixel_format',['',*choices])
                    elif key=='EncoderSourceA':self.apply_enum_choices('encoder_line',choices)
                    elif key=='TriggerSource' and row['entry']['selectors'].get('TriggerSelector')==data['plan']['settings']['frame_selector']:
                        self.apply_enum_choices('frame_line',[v for v in choices if v.startswith('Line') and v[4:].isdigit()])
            self.refresh_output_choices()
            self.log.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
            def context(e):return ','.join(e['selectors'].values())+' / '+e['key'] if e['selectors'] else e['key']
            self.fill(self.compare_table,[[context(r['entry']),'模式切换后读取' if r['before'] is None else r['before'],r['entry']['value'],r['error'] or r['status']] for r in data['rows']])
            self.details_button.setChecked(True);self.tabs.setCurrentIndex(1)
            self.notify('参数对比完成，可写入并保存 UserSet1。' if data['ready'] else '暂不能写入：'+'；'.join(data['errors']),not data['ready'])
        else:
            self.last_report=data;self.preview=None;self.log.setPlainText(json.dumps(data,ensure_ascii=False,indent=2));self.details_button.setChecked(True);self.tabs.setCurrentIndex(2)
            self.notify('写入及读回完成；已保存 UserSet1、重新加载核对，并设为默认用户集。')

    def failed(self,text,report):
        self.preview=None
        if report:self.last_report=report;self.log.setPlainText(json.dumps(report,ensure_ascii=False,indent=2));self.details_button.setChecked(True);self.tabs.setCurrentIndex(2)
        self.notify(text,True)

    def stopped(self):
        job=self.worker;self.worker=None;job.deleteLater();self.form_panel.setEnabled(True);self.devices_bar.setEnabled(True);self.progress.hide();self.enable_fields();self.update_actions()
        self.files_button.setEnabled(True);self.connection_button.setEnabled(True);self.language_box.setEnabled(True)

    def notify(self,text,error=False):
        self.message.setText(text);self.message.setVisible(bool(text));self.message.setProperty('error',error);self.message.style().unpolish(self.message);self.message.style().polish(self.message)

    def is_busy(self):return self.worker is not None

    def open_config(self):
        path,_=QFileDialog.getOpenFileName(self,'打开相机配置','','JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>1_000_000:raise CameraError('配置文件超过1MB。')
            self.load_settings(settings_from_dict(json.loads(Path(path).read_text(encoding='utf-8-sig'))))
            if self.settings().line_y_source=='legacy':self.advanced_button.setChecked(True)
        except Exception as exc:self.notify(str(exc),True)

    def save_config(self):
        try:
            data=config_dict(self.settings());path,_=QFileDialog.getSaveFileName(self,'保存相机配置','camera-config.json','JSON (*.json)')
            if path:Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');self.notify('相机配置已保存。')
        except Exception as exc:self.notify(str(exc),True)

    def open_mfs(self):
        path,_=QFileDialog.getOpenFileName(self,'只读取参考MFS到当前配置','','GenApi (*.mfs *.pfs)')
        if not path:return
        try:
            if Path(path).stat().st_size>1_000_000:raise CameraError('MFS超过1MB。')
            s,count=import_mfs_text(Path(path).read_text(encoding='utf-8-sig'),self.settings());self.load_settings(s)
            self.notify('已解析 '+str(count)+' 项参考记录；只采用已支持字段。P/R、FOV、计数倍率和工位尺寸仍需现场给定。')
        except Exception as exc:self.notify(str(exc),True)

    def export_report(self):
        if self.last_report is None:return
        path,_=QFileDialog.getSaveFileName(self,'保存参数对比或执行记录','camera-record.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(self.last_report,ensure_ascii=False,indent=2),encoding='utf-8');self.notify('记录已保存：'+path)
            except Exception as exc:self.notify(str(exc),True)
