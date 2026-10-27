"""Native converter workspace backed by VT Studio's original conversion executable."""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPen, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QSpinBox, QFileDialog, QListWidget, QSplitter, QGroupBox,
    QFormLayout, QComboBox, QTabWidget, QScrollArea, QProgressBar, QPlainTextEdit, QAbstractSpinBox)

from app import Canvas, Worker, MainWindow
from engine import SynthesisError
from legacy_bridge import ConversionSettings, scan_images, convert_batch, preview_conversion


class ConverterPage(QWidget):
    send_to_defects = Signal(list)
    job_finished = Signal(object)

    def __init__(self):
        super().__init__()
        self.worker = None
        self.paths = []
        self.source = None
        self.last_run = None
        self.results = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        library = QWidget()
        library.setMinimumWidth(180)
        library.setMaximumWidth(275)
        lib = QVBoxLayout(library)
        lib.setContentsMargins(0, 0, 10, 0)
        title = QLabel('图片素材')
        title.setStyleSheet('font-size: 15px; font-weight: 600;')
        lib.addWidget(title)
        self.folder_button = MainWindow.button('选择图片文件夹', self.choose_input)
        lib.addWidget(self.folder_button)
        self.input_path = QLineEdit()
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText('尚未选择图片文件夹')
        lib.addWidget(self.input_path)
        self.recursive = QCheckBox('包含子文件夹')
        self.recursive.setChecked(True)
        self.recursive.toggled.connect(self.reload)
        lib.addWidget(self.recursive)
        self.files = QListWidget()
        self.files.setWordWrap(True)
        self.files.currentRowChanged.connect(self.select_image)
        lib.addWidget(self.files, 1)
        self.file_info = QLabel('支持 BMP / PNG\n文件名保持不变')
        self.file_info.setObjectName('Subtle')
        self.file_info.setWordWrap(True)
        lib.addWidget(self.file_info)
        splitter.addWidget(library)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(9)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('左上角 (0, 0) 固定'))
        tools.addStretch()
        tools.addWidget(MainWindow.button('适应窗口', self.fit_canvases))
        middle_layout.addLayout(tools)
        self.tabs = QTabWidget()
        self.range_canvas = Canvas('选择左侧图片，预览原图与目标范围。')
        self.output_canvas = Canvas('选择图片并设置目标尺寸，预览输出效果。')
        self.range_canvas.setMinimumSize(300, 240)
        self.output_canvas.setMinimumSize(300, 240)
        self.range_canvas.set_mode('view')
        self.output_canvas.set_mode('view')
        self.tabs.addTab(self.range_canvas, '裁切 / 填充范围')
        self.tabs.addTab(self.output_canvas, '输出预览')
        self.tabs.currentChanged.connect(lambda _: self.fit_canvases())
        middle_layout.addWidget(self.tabs, 1)
        self.preview_info = QLabel('橙框：输出范围   蓝框：原图边界   滚轮缩放 / 右键拖动平移')
        self.preview_info.setObjectName('Subtle')
        self.preview_info.setWordWrap(True)
        middle_layout.addWidget(self.preview_info)
        splitter.addWidget(middle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(250)
        scroll.setMaximumWidth(305)
        self.settings_panel = QWidget()
        opts = QVBoxLayout(self.settings_panel)
        opts.setContentsMargins(12, 0, 0, 0)
        opts.setSpacing(12)
        group = QGroupBox('目标尺寸')
        form = QFormLayout(group)
        self.width = QSpinBox()
        self.height = QSpinBox()
        for field, value in [(self.width,3200),(self.height,3960)]:
            field.setRange(1,200000)
            field.setValue(value)
            field.setSuffix(' px')
            field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            field.valueChanged.connect(self.refresh_preview)
        form.addRow('宽度 W', self.width)
        form.addRow('高度 H', self.height)
        self.original_button = MainWindow.button('使用当前图片尺寸', self.use_original)
        form.addRow(self.original_button)
        opts.addWidget(group)
        group = QGroupBox('填充与坐标')
        g = QVBoxLayout(group)
        self.fill = QComboBox()
        self.fill.addItem('黑色填充 · 灰度 0', False)
        self.fill.addItem('白色填充 · 灰度 255', True)
        self.fill.currentIndexChanged.connect(self.refresh_preview)
        g.addWidget(self.fill)
        rule = QLabel('原图不拉伸。\n仅裁切或填充右侧与下方，保持左上角坐标。')
        rule.setObjectName('Rule')
        rule.setWordWrap(True)
        g.addWidget(rule)
        opts.addWidget(group)
        group = QGroupBox('点集与标注保护')
        g = QVBoxLayout(group)
        self.copy_xml = QCheckBox('原样复制 XML')
        self.copy_xml.setChecked(True)
        self.allow_clip = QCheckBox('允许裁切触及标注区域')
        self.allow_clip.setChecked(False)
        g.addWidget(self.copy_xml)
        g.addWidget(self.allow_clip)
        text = QLabel('沿用 VT Studio 5.0 原核心。XML 内容与图片路径不改写，点集坐标不转换。')
        text.setWordWrap(True)
        text.setObjectName('Subtle')
        g.addWidget(text)
        opts.addWidget(group)
        opts.addStretch()
        scroll.setWidget(self.settings_panel)
        splitter.addWidget(scroll)
        splitter.setSizes([220, 660, 275])
        splitter.setStretchFactor(1, 1)

        export = QGroupBox('批量输出')
        box = QVBoxLayout(export)
        row = QHBoxLayout()
        self.output_root = QLineEdit()
        self.output_root.setPlaceholderText('选择独立输出位置，每个批次单独保存')
        row.addWidget(self.output_root, 1)
        self.choose_output_button = MainWindow.button('选择输出位置', self.choose_output)
        row.addWidget(self.choose_output_button)
        box.addLayout(row)
        row = QHBoxLayout()
        self.progress_text = QLabel('未开始转换')
        self.progress_text.setObjectName('Subtle')
        row.addWidget(self.progress_text, 1)
        self.cancel_button = MainWindow.button('停止转换', self.cancel)
        self.cancel_button.setEnabled(False)
        self.start_button = MainWindow.button('开始转换', self.start, primary=True)
        self.open_button = MainWindow.button('打开结果', self.open_results)
        self.open_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        row.addWidget(self.open_button)
        box.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        box.addWidget(self.progress)
        outer.addWidget(export)
        row = QHBoxLayout()
        self.log_toggle = QPushButton('显示处理记录')
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self.toggle_log)
        row.addWidget(self.log_toggle)
        row.addStretch()
        self.send_button = MainWindow.button('作为 OK 底图送往缺陷合成', self.send)
        self.send_button.setToolTip('仅当本批转换结果是正常 OK 图时使用；由操作者确认。')
        self.send_button.setEnabled(False)
        row.addWidget(self.send_button)
        outer.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMaximumHeight(110)
        self.log.hide()
        outer.addWidget(self.log)
        self.message = QLabel('先选择图片文件夹，再设置目标宽高。转换使用 VT Studio 5.0 原核心。')
        self.message.setObjectName('Message')
        self.message.setWordWrap(True)
        outer.addWidget(self.message)

    def is_busy(self):
        return self.worker is not None

    def notify(self, text, error=False):
        self.message.setText(text)
        self.message.setProperty('error', error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def choose_input(self):
        path = QFileDialog.getExistingDirectory(self, '选择待转换的图片文件夹', self.input_path.text())
        if path:
            self.set_input(path)

    def set_input(self, path):
        self.input_path.setText(str(Path(path).resolve()))
        self.reload()

    def reload(self, *_):
        if self.is_busy() or not self.input_path.text():
            return
        self.paths = []
        self.source = None
        self.files.clear()
        self.results = []
        self.last_run = None
        self.open_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress_text.setText('未开始转换')
        self.clear_preview('正在扫描图片文件夹…')
        folder, recursive = self.input_path.text(), self.recursive.isChecked()
        self.notify('正在扫描图片…')
        self._start_worker(lambda _: scan_images(folder,recursive), self.on_scanned)

    def on_scanned(self, paths):
        self.paths = paths
        self.files.clear()
        self.source = None
        for path in paths:
            self.files.addItem(path.name)
            self.files.item(self.files.count()-1).setToolTip(str(path))
        if paths:
            self.files.setCurrentRow(0)
            if self.source is not None:
                self.notify(f'已找到 {len(paths)} 张图片。设置尺寸后可查看输出预览。')
        else:
            self.clear_preview('文件夹中没有 BMP / PNG 图片。\n请选择其他图片文件夹。')
            self.notify('未找到 BMP / PNG 图片，请检查目录与子文件夹选项。', True)
        self.file_info.setText(f'{len(paths)} 张 BMP / PNG\n保留原文件名 · 集中输出')

    def select_image(self, row):
        if not 0 <= row < len(self.paths):
            return
        try:
            self.clear_preview('正在读取图片…')
            with Image.open(self.paths[row]) as im:
                if im.width*im.height > 60_000_000:
                    raise SynthesisError('图片过大，暂不显示预览；转换仍由原核心处理。')
                self.source = im.convert('L' if im.mode == 'L' else 'RGB')
            self.refresh_preview()
        except Exception as exc:
            self.source = None
            self.clear_preview('当前图片无法预览。\n请选择有效的 BMP / PNG 图片。')
            self.notify(f'预览读取失败：{exc}', True)

    def clear_preview(self, text):
        self.source = None
        self.range_canvas.set_empty(text)
        self.output_canvas.set_empty(text)
        self.preview_info.setText('尚未显示图片；选择有效素材后生成当前预览。')

    def use_original(self):
        if self.source:
            self.width.setValue(self.source.width)
            self.height.setValue(self.source.height)

    def refresh_preview(self, *_):
        if self.source is None:
            return
        try:
            width, height = self.width.value(), self.height.value()
            white = self.fill.currentData()
            result, ratio = preview_conversion(self.source, width, height, white)
            self.output_canvas.set_image(result)
            sw, sh = self.source.size
            union_w, union_h = max(sw, width), max(sh, height)
            scale = min(1, 1600/max(union_w,union_h))
            board = Image.new('RGB', (max(1,round(union_w*scale)),max(1,round(union_h*scale))), '#263242')
            from PIL import ImageDraw
            draw = ImageDraw.Draw(board)
            target = (0,0,max(1,round(width*scale))-1,max(1,round(height*scale))-1)
            draw.rectangle(target, fill='#ffffff' if white else '#000000')
            image = self.source.convert('RGB').resize((max(1,round(sw*scale)),max(1,round(sh*scale))), Image.Resampling.LANCZOS)
            board.paste(image,(0,0))
            self.range_canvas.set_image(board)
            blue = QPen(QColor('#72b8ed'),2)
            orange = QPen(QColor('#f2ac68'),2)
            blue.setCosmetic(True)
            orange.setCosmetic(True)
            self.range_canvas.scene().addRect(QRectF(0,0,sw*scale,sh*scale), blue)
            self.range_canvas.scene().addRect(QRectF(0,0,width*scale,height*scale), orange)
            self.range_canvas.fit_image()
            self.preview_info.setText(f'原图 {sw} × {sh} → 输出 {width} × {height} px  |  橙框：输出 / 蓝框：原图')
        except Exception as exc:
            self.notify(f'预览失败：{exc}', True)

    def fit_canvases(self):
        self.range_canvas.fit_image()
        self.output_canvas.fit_image()

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, '选择独立的输出位置', self.output_root.text())
        if folder:
            self.output_root.setText(folder)

    def settings(self):
        return ConversionSettings(self.input_path.text(),self.output_root.text(),self.width.value(),
            self.height.value(),bool(self.fill.currentData()),self.recursive.isChecked(),
            self.copy_xml.isChecked(),self.allow_clip.isChecked())

    def _start_worker(self, operation, callback, converting=False):
        self.folder_button.setEnabled(False)
        self.recursive.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.files.setEnabled(False)
        self.start_button.setEnabled(False)
        self.output_root.setEnabled(False)
        self.choose_output_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.cancel_button.setEnabled(converting)
        self.worker = Worker(operation, self)
        self.worker.result.connect(callback)
        self.worker.failed.connect(self.on_failed)
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def worker_finished(self):
        old, self.worker = self.worker, None
        for control in (self.folder_button,self.recursive,self.settings_panel,self.files,
                        self.start_button,self.output_root,self.choose_output_button):
            control.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.send_button.setEnabled(bool(self.results))
        self.open_button.setEnabled(bool(self.last_run))
        if old:
            old.deleteLater()

    def on_failed(self, exc):
        if self.source is None:
            self.clear_preview('未能读取当前素材。\n请检查目录和文件，再重新选择。')
        if getattr(exc,'run_dir',None):
            self.last_run = exc.run_dir
        self.progress_text.setText('任务未完成，请查看提示')
        self.notify(str(exc),True)

    def start(self):
        if self.is_busy():
            return
        try:
            settings = self.settings()
            settings.validate()
            self.results = []
            self.log.clear()
            self.progress.setRange(0,max(1,len(self.paths)))
            self.progress.setValue(0)
            self.progress_text.setText('正在检查并启动 VT Studio 转换核心…')
            self.notify('转换进行中。停止会保留已经完成的输出。')
            def run(worker):
                def event(event):
                    report = event.get('report')
                    if report:
                        done = report['OK']+report['Skipped']+report['Failed']
                        worker.progress.emit(done,report['Total'],f"成功 {report['OK']} / 跳过 {report['Skipped']} / 失败 {report['Failed']}")
                    elif event.get('message'):
                        worker.progress.emit(-1,0,event['message'])
                return convert_batch(settings,event,worker.isInterruptionRequested)
            self._start_worker(run,self.on_done,True)
        except Exception as exc:
            self.notify(str(exc),True)

    def on_worker_progress(self, done, total, message):
        if done >= 0:
            self.progress.setRange(0,max(1,total))
            self.progress.setValue(done)
            self.progress_text.setText(message)
        else:
            self.log.appendPlainText(message)

    def on_done(self, result):
        self.last_run = result.get('run_dir')
        self.results = result.get('images',[])
        state = {'complete':'转换完成','partial':'完成，部分图片被跳过或失败','cancelled':'已停止'}[result['status']]
        self.notify(f"{state}，成功 {result['completed']} / {result['total']} 张。原文件名、左上角原点保持不变。")
        self.progress_text.setText(state)
        self.job_finished.emit(result)

    def cancel(self):
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.notify('正在停止转换，请等待当前图片处理完成…')

    def toggle_log(self, checked):
        self.log.setVisible(checked)
        self.log_toggle.setText('收起处理记录' if checked else '显示处理记录')

    def open_results(self):
        if self.last_run:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_run))

    def send(self):
        if self.results:
            self.send_to_defects.emit(list(self.results))
