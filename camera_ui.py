"""Camera workstation: calculate, inspect, compare, then explicitly write UserSet1."""
from dataclasses import asdict
import json
from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QRectF
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QTabWidget,
    QSplitter,QScrollArea,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,
    QPlainTextEdit,QFileDialog,QProgressBar,QMenu)
from styled_controls import make_combo
from camera_model import CameraSettings,CameraError,calculate,config_dict,settings_from_dict,import_mfs_text,fingerprint
from camera_sdk import discover_mvs,enumerate_cameras
from camera_transaction import inspect_camera,preview_camera,write_camera


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
        p.setPen(QColor('#263548'));p.drawText(product,Qt.AlignmentFlag.AlignCenter,'产品\n'+format(s['target_width_mm'],'.6g')+' × '+format(s['target_length_mm'],'.6g')+' mm')
        p.setPen(QColor('#526377'));p.drawText(QRectF(0,0,self.width(),20),Qt.AlignmentFlag.AlignCenter,'居中示意 · 产品前后位置由下位机相位决定')
        p.end()


class CameraPage(QWidget):
    def __init__(self):
        super().__init__();self.setObjectName('CameraPage')
        self.worker=None;self.preview=None;self.last_report=None;self.geometry=None;self.plan=None;self._loading=False
        self.controls={};self.labels={};self.sdk=discover_mvs();root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        tools=QHBoxLayout();tools.addStretch()
        self.connection_button=self.button('连接与写入相机',lambda:None,tools);self.connection_button.setCheckable(True)
        more=self.button('配置与文件',lambda:None,tools);self.files_button=more;menu=QMenu(more)
        for title,action in [('打开配置',self.open_config),('保存配置',self.save_config),('读取 MFS',self.open_mfs),('设置 MVS 目录',self.choose_sdk)]:menu.addAction(title,action)
        more.setMenu(menu);root.addLayout(tools)
        self.devices_bar=QWidget();bar=QHBoxLayout(self.devices_bar);bar.setContentsMargins(0,0,0,0)
        self.device=self.styled_combo();self.device.addItem('尚未枚举相机',None);bar.addWidget(self.device,1)
        self.scan_button=self.button('枚举相机',lambda:self.start_job('scan'),bar)
        self.inspect_button=self.button('读取设备尺寸',lambda:self.start_job('inspect'),bar)
        root.addWidget(self.devices_bar);self.devices_bar.hide()
        split=QSplitter(Qt.Orientation.Horizontal);root.addWidget(split,1)
        self.form_panel=QWidget();left=QVBoxLayout(self.form_panel);left.setContentsMargins(0,0,10,0);left.setSpacing(10)
        self.form_tabs=QTabWidget();left.addWidget(self.form_tabs,1)
        station=self.form_tab('产品画面');calibration=self.form_tab('工位标定');encoder=self.form_tab('编码器');image=self.form_tab('成像');io=self.form_tab('接线')
        self.combo(station,'kind','相机类型',[('线扫','line'),('面阵','area')])
        self.number(station,'target_width_mm','产品宽度 / mm',.001,100000,3)
        self.number(station,'target_length_mm','产品长度 / mm',.001,100000,3)
        self.number(station,'image_horizontal_margin_mm','左右总留边 / mm',0,100000,3)
        self.number(station,'image_vertical_margin_mm','前后总留白 / mm',0,100000,3)
        self.number(station,'exposure_us','曝光 / μs',.01,100000000,3)
        self.number(station,'gain','增益 Gain',0,10000,4)
        self.combo(station,'compression','HB 压缩',[('保持现状',''),('关闭 Off','Off'),('HB','HB')])
        self.note(station,'帧触发开始采集，采满 Height 行结束。前后留白的位置由下位机相位调整。')
        self.combo(calibration,'precision_source','X 精度来源',[('实测视野','fov'),('已知像素精度','precision'),('镜头参数估算','optics')])
        self.integer(calibration,'sensor_width','传感器宽度 / px',1,65536)
        self.integer(calibration,'sensor_height','传感器高度 / px',1,65536)
        self.number(calibration,'working_distance_mm','工作距离 / mm',.001,100000,3)
        self.number(calibration,'focal_length_mm','镜头焦距 / mm',0,1000,3,special='请填写')
        self.number(calibration,'pixel_pitch_um','传感器像元 / μm',0,1000,3,special='请填写')
        self.number(calibration,'fov_width_mm','全幅 X 视野 / mm',.001,100000,3)
        self.number(calibration,'fov_height_mm','全幅 Y 视野 / mm',.001,100000,3)
        self.number(calibration,'x_mm_per_px','X 精度 / mm/px',.000001,1000,6)
        self.combo(calibration,'line_y_source','线扫 Y 精度来源',[('已知纵向精度','precision'),('产品实测标定','calibration'),('方形像素规划','square')])
        self.number(calibration,'y_mm_per_px','Y 精度 / mm/行',.000001,1000,6)
        self.number(calibration,'calibration_length_mm','标定产品长度 / mm',.001,100000,3)
        self.integer(calibration,'calibration_rows','图中产品占用行数',1,1000000)
        self.note(calibration,'标定使用未缩放的原始采集图。工位设置随配置保存，换产品时可复用；方形像素模式仅提供规划值。')
        self.number(encoder,'products_per_minute','最高产能 / 片/分',.01,100000,2)
        self.integer(encoder,'ppr','编码器 P/R',1,10000000)
        self.combo(encoder,'edge_factor','实际计数倍率',[('×1',1),('×2',2),('×4',4)])
        self.number(encoder,'encoder_revs','每产品编码器转数',.000001,1000,6)
        self.integer(encoder,'pre_divider','预分频 PreDivider',1,1000000)
        self.integer(encoder,'multiplier','倍频 Multiplier',1,1000000)
        self.integer(encoder,'post_divider','后分频 PostDivider',1,1000000)
        self.number(encoder,'rate_margin_percent','行频能力预留 / %',0,100,1)
        self.note(encoder,'固定编码器与倍分频决定行触发节奏。图高独立设置；每周期总行节拍不等于产品在图中占用的行数。')
        self.combo(io,'frame_selector','帧触发选择器',[('FrameBurstStart','FrameBurstStart'),('FrameStart','FrameStart')])
        lines=[('Line'+str(i),'Line'+str(i)) for i in range(16)]
        self.combo(io,'frame_line','Z 相输入',lines);self.combo(io,'frame_edge','帧触发边沿',[('上升沿','RisingEdge'),('下降沿','FallingEdge')])
        self.combo(io,'encoder_line','A 相输入',lines)
        self.combo(io,'line_edge','行触发/信号对齐',[('下降沿','FallingEdge'),('上升沿','RisingEdge')])
        self.combo(io,'input_format','输入电气格式',[('保持现状',''),('Differential','Differential')],editable=True)
        self.integer(io,'a_debounce_ns','A 相消抖 / ns',0,100000000)
        self.integer(io,'z_debounce_ns','Z 相消抖 / ns',0,100000000)
        self.check(io,'output0_enabled','配置输出 IO 1');self.combo(io,'output0_line','输出 IO 1',lines)
        self.text(io,'output0_source','输出 1 信号源')
        self.check(io,'output4_enabled','配置输出 IO 2');self.combo(io,'output4_line','输出 IO 2',lines)
        self.text(io,'output4_source','输出 2 信号源')
        self.combo(io,'output_mode','输出模式',[('Strobe','Strobe'),('Output','Output')])
        self.check(io,'strobe_enable','启用 StrobeEnable 节点')
        self.integer(io,'strobe_duration_us','输出 2 频闪时长 / μs',0,100000000)
        self.text(io,'device_name','相机名称 DeviceUserID')
        self.note(io,'文档参考接线：Z→Line3，A→Line1；输出→Line0 / Line4。以现场接线和设备支持项为准。名称使用 ASCII。')
        self.integer(image,'digital_shift','DigitalShift',-1,32,special='保持现状')
        self.text(image,'preamp_gain','PreampGain（空=保持）')
        self.combo(image,'pixel_format','像素格式',[('保持现状',''),('Mono8','Mono8'),('BayerRG8','BayerRG8'),('RGB8Packed','RGB8Packed'),('BGR8Packed','BGR8Packed')],editable=True)
        self.check(image,'reverse_x','水平翻转 ReverseX')
        self.number(image,'black_level','黑电平（-1=保持）',-1,65535,2)
        self.integer(image,'width_override','Width / px',0,65536,special='自动计算并对齐步长')
        self.integer(image,'height_override','Height / px',0,1000000,special='自动计算并对齐步长')
        self.check(image,'centered_x','X 方向居中');self.integer(image,'offset_x','OffsetX / px',0,65536)
        self.integer(image,'offset_y','OffsetY / px',0,65536)
        self.number(image,'line_rate_override','设置行频 / Hz',0,100000000,0,special='按产能与余量计算')
        self.check(image,'limit_line_rate','启用 AcquisitionLineRateEnable')
        self.check(image,'require_square','要求方形像素');self.number(image,'square_tolerance_percent','X/Y 允许差异 / %',0,100,2)
        self.note(image,'Gain、DigitalShift 与 PreampGain 分别设置；不把它们混为“数字增益”。选定非保持项时，设备必须支持该节点。')
        self.advanced_button=self.button('展开高级设置',lambda:None,left);self.advanced_button.setCheckable(True);self.advanced_button.toggled.connect(self.toggle_advanced)
        self.toggle_advanced(False)
        split.addWidget(self.form_panel)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(8,0,0,0);right_layout.setSpacing(10)
        title=QLabel('计算结果');title.setFixedHeight(28);title.setStyleSheet('font-size:18px;font-weight:600;');right_layout.addWidget(title)
        self.metrics=self.table(['计算项','结果','单位']);self.metrics.setFixedHeight(204);right_layout.addWidget(self.metrics)
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
        split.addWidget(right);split.setStretchFactor(0,0);split.setStretchFactor(1,1);split.setSizes([430,730])
        self.form_panel.setMinimumWidth(390)
        self.progress=QProgressBar();self.progress.setFixedHeight(5);self.progress.setTextVisible(False);self.progress.hide();root.addWidget(self.progress)
        self.message=QLabel();self.message.setObjectName('Message');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);root.addWidget(self.message)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.recalculate)
        self.device.currentIndexChanged.connect(self.device_changed)
        self.load_settings(CameraSettings());self.notify('当前为示例参数，请按实际工位修改。')

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
        self.controls[key]=widget;caption=QLabel(label);caption.setWordWrap(True);self.labels[key]=caption;form.addRow(caption,widget)
        return widget

    def number(self,form,key,label,low,high,decimals,special=None):
        widget=QDoubleSpinBox();widget.setDecimals(decimals);widget.setRange(low,high);widget.setKeyboardTracking(False)
        if special:widget.setSpecialValueText(special)
        self.register(form,key,label,widget);widget.valueChanged.connect(self.changed)

    def integer(self,form,key,label,low,high,special=None):
        widget=QSpinBox();widget.setRange(low,high);widget.setKeyboardTracking(False)
        if special:widget.setSpecialValueText(special)
        self.register(form,key,label,widget);widget.valueChanged.connect(self.changed)

    def combo(self,form,key,label,items,editable=False):
        widget=self.styled_combo();widget.setEditable(editable)
        for text,value in items:widget.addItem(text,value)
        self.register(form,key,label,widget);widget.currentIndexChanged.connect(self.changed)
        if editable:widget.editTextChanged.connect(self.changed)

    @staticmethod
    def styled_combo():
        return make_combo()

    def text(self,form,key,label):
        widget=QLineEdit();self.register(form,key,label,widget);widget.textChanged.connect(self.changed)

    def check(self,form,key,label):
        widget=QCheckBox(label);widget.setMinimumHeight(28);self.controls[key]=widget;form.addRow(widget);widget.toggled.connect(self.changed)

    @staticmethod
    def note(form,text):
        label=QLabel(text);label.setWordWrap(True);label.setObjectName('Subtle');form.addRow(label)

    def load_settings(self,settings):
        settings.validate();self._loading=True
        for key,value in asdict(settings).items():
            widget=self.controls[key]
            if isinstance(widget,QCheckBox):widget.setChecked(value)
            elif isinstance(widget,QComboBox):
                index=widget.findData(value)
                if index<0:widget.addItem('旧配置换算值 · 待确认' if key=='line_y_source' and value=='legacy' else str(value),value);index=widget.count()-1
                widget.setCurrentIndex(index)
            elif isinstance(widget,QLineEdit):widget.setText(value)
            else:widget.setValue(value)
        self._loading=False;self.recalculate()

    def settings(self):
        values={}
        for key,widget in self.controls.items():
            if isinstance(widget,QCheckBox):value=widget.isChecked()
            elif isinstance(widget,QComboBox):value=widget.currentData() if widget.currentIndex()>=0 and widget.currentText()==widget.itemText(widget.currentIndex()) else widget.currentText().strip()
            elif isinstance(widget,QLineEdit):value=widget.text().strip()
            else:value=widget.value()
            values[key]=value
        return CameraSettings(**values).validate()

    def changed(self,*args):
        if self._loading:return
        self.preview=None;self.write_button.setEnabled(False);self.timer.start(180)

    def enable_fields(self):
        line=self.controls['kind'].currentData()=='line';source=self.controls['precision_source'].currentData();fov=source=='fov';optics=source=='optics'
        line_only=('ppr','edge_factor','encoder_revs','pre_divider','multiplier','post_divider','rate_margin_percent',
                   'encoder_line','line_edge','a_debounce_ns','line_rate_override','limit_line_rate','line_y_source')
        for key in line_only:self.controls[key].setEnabled(line)
        self.controls['sensor_height'].setEnabled(not line);self.controls['offset_y'].setEnabled(not line)
        self.controls['fov_width_mm'].setEnabled(fov);self.controls['fov_height_mm'].setEnabled(fov and not line)
        ysource=self.controls['line_y_source'].currentData()
        y_visible=(line and ysource in ('precision','legacy')) or (not line and source=='precision')
        self.controls['x_mm_per_px'].setEnabled(source=='precision');self.controls['y_mm_per_px'].setEnabled(y_visible)
        self.controls['line_rate_override'].setEnabled(line and self.controls['limit_line_rate'].isChecked())
        for key,visible in {'sensor_height':not line,'fov_width_mm':fov,'fov_height_mm':fov and not line,
                            'x_mm_per_px':source=='precision','y_mm_per_px':y_visible,'line_y_source':line,
                            'calibration_length_mm':line and ysource=='calibration','calibration_rows':line and ysource=='calibration',
                            'working_distance_mm':optics,'focal_length_mm':optics,'pixel_pitch_um':optics}.items():
            widget=self.controls[key];form=widget.parentWidget().layout();form.setRowVisible(widget,visible)
        self.controls['offset_x'].setEnabled(not self.controls['centered_x'].isChecked())
        for prefix in ('output0','output4'):
            for suffix in ('line','source'):self.controls[prefix+'_'+suffix].setEnabled(self.controls[prefix+'_enabled'].isChecked())
        self.controls['strobe_duration_us'].setEnabled(self.controls['output4_enabled'].isChecked())

    def toggle_advanced(self,expanded):
        self.form_tabs.setCurrentIndex(0)
        for i in range(1,self.form_tabs.count()):self.form_tabs.setTabVisible(i,expanded)
        self.form_tabs.tabBar().setVisible(expanded)
        self.advanced_button.setText('收起高级设置' if expanded else '展开高级设置')
        if expanded:self.form_tabs.setCurrentIndex(1)

    def toggle_details(self,expanded):
        self.tabs.setVisible(expanded);self.frame_preview.setVisible(not expanded)
        self.result_space.setVisible(not expanded)
        self.details_button.setText('收起参数明细' if expanded else '查看参数明细')

    def toggle_connection(self,expanded):
        self.devices_bar.setVisible(expanded);self.device_actions.setVisible(expanded)

    def showEvent(self,event):
        super().showEvent(event);QTimer.singleShot(0,self.fit_metrics)

    def fit_metrics(self):
        header=self.metrics.horizontalHeader();header.ensurePolished()
        self.metrics.setFixedHeight(max(header.height(),header.sizeHint().height())+sum(self.metrics.rowHeight(i) for i in range(self.metrics.rowCount()))+2*self.metrics.frameWidth()+4)

    @staticmethod
    def fill(table,rows):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):
                text=str(value);item=QTableWidgetItem(text);item.setToolTip(text);table.setItem(i,j,item)

    def render_plan(self,plan):
        self.plan=plan;m=plan['metrics']
        metrics=[('整张图宽 × 高',str(m['width'])+' × '+str(m['height']),'px'),
            ('产品高度',str(m['product_height_lines']),'行'),
            ('前后背景行数',str(m['background_height_lines']),'行'),
            ('X / Y 精度',format(m['x_mm_per_px'],'.6f')+' / '+format(m['y_mm_per_px'],'.6f'),'mm/px')]
        if m['line_triggers_per_cycle'] is not None:metrics.append(('预计外部行频',format(m['required_line_rate_hz'],'.0f'),'Hz'))
        else:metrics.append(('产品帧频',format(m['frame_rate_hz'],'.3f'),'Hz'))
        self.fill(self.metrics,metrics)
        self.fit_metrics()
        self.frame_preview.plan=plan;self.frame_preview.update()
        self.fill(self.node_table,[[', '.join(n['selectors'].values()) or '全局',n['key'],n['value']] for n in plan['nodes']])
        if plan['blocking']:text='；'.join(plan['blocking'])
        elif plan['settings']['kind']=='line':text='帧触发后采满 '+str(m['height'])+' 行出图；产品预计占 '+str(m['product_height_lines'])+' 行。'
        else:text='按当前视野计算，产品和留白均在取图范围内。'
        if plan['settings']['precision_source']=='optics':text+=' 镜头估算值需用实测视野校准。'
        if plan['settings']['kind']=='line' and plan['settings']['line_y_source']=='square':text+=' Y 精度为方形像素规划值。'
        if plan['settings']['kind']=='line' and plan['settings']['line_y_source']=='legacy':text+=' 请在工位标定中确认旧配置的 Y 精度。'
        self.summary.setText(text);self.summary.setToolTip('\n'.join(plan['blocking']+plan['warnings']))

    def recalculate(self):
        self.timer.stop();self.preview=None;self.write_button.setEnabled(False)
        try:
            self.enable_fields();limits=self.geometry.get('limits') if self.geometry else None
            self.render_plan(calculate(self.settings(),limits));self.update_actions()
            self.notify('；'.join(self.plan['blocking']) if self.plan['blocking'] else '',bool(self.plan['blocking']))
            return self.plan
        except Exception as exc:
            self.plan=None;self.metrics.setRowCount(0);self.frame_preview.plan=None;self.frame_preview.update();self.summary.clear()
            self.notify(str(exc),True);self.update_actions();return None

    def selected_uid(self):return self.device.currentData()

    def update_actions(self):
        selected=bool(self.selected_uid());busy=self.is_busy()
        self.inspect_button.setEnabled(selected and not busy);self.compare_button.setEnabled(selected and self.plan is not None and not busy)
        self.write_button.setEnabled(bool(self.preview and self.preview.get('ready')) and not busy)
        self.export_button.setEnabled(self.last_report is not None and not busy)

    def device_changed(self,*args):
        self.geometry=None;self.preview=None;self.last_report=None
        if hasattr(self,'write_button'):self.update_actions()

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
        self.files_button.setEnabled(False);self.connection_button.setEnabled(False)
        self.compare_button.setEnabled(False);self.write_button.setEnabled(False);self.export_button.setEnabled(False)
        self.progress.setRange(0,0);self.progress.show();self.notify({'scan':'正在枚举相机…','inspect':'正在读取设备尺寸与范围…','compare':'正在读取选择器分组并对比参数…','write':'正在写入所选相机…'}[action]);self.worker.start()

    def finished_result(self,action,data):
        if action=='scan':
            self.device.clear()
            if not data['devices']:self.device.addItem('未发现 GigE / USB3 相机',None)
            for d in data['devices']:self.device.addItem(d['model']+' · '+d['serial']+' · '+d.get('ip',d['transport']),d['uid'])
            self.notify('MVS '+data['sdk_version']+'：发现 '+str(len(data['devices']))+' 台相机。'+('请检查供电、网络与设备连接。' if not data['devices'] else '请选择目标后读取设备尺寸。'))
            self.last_report=data
        elif action=='inspect':
            self.geometry=data;s=self.settings();s.sensor_width=data['sensor_width']
            scan=data.get('scan_type','').lower()
            if 'line' in scan:s.kind='line'
            elif 'area' in scan:s.kind='area';s.frame_selector='FrameStart'
            if s.kind=='area':s.sensor_height=data['sensor_height']
            if data.get('pixel_format'):s.pixel_format=data['pixel_format']['value']
            self.load_settings(s);self.notify('已读取 '+data['device']['model']+' / '+data['device']['serial']+'；精度标定沿用工位配置。')
            self.log.setPlainText(json.dumps(data,ensure_ascii=False,indent=2))
            self.last_report=data
        elif action=='compare':
            self.preview=data;self.last_report=data;self.geometry=data['geometry'];self.render_plan(data['plan'])
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
        self.files_button.setEnabled(True);self.connection_button.setEnabled(True)

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
