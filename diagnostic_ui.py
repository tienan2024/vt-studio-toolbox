"""A shared diagnostics panel for all four toolbox workspaces."""
from datetime import datetime
from PySide6.QtCore import QTimer,QUrl,Qt
from PySide6.QtGui import QDesktopServices,QFontDatabase
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QPlainTextEdit,QFileDialog
from diagnostic_log import setup_logging,snapshot,event


class DiagnosticDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.store=setup_logging()
        self.setWindowTitle('调试日志与快照');self.resize(850,580)
        layout=QVBoxLayout(self)
        label=QLabel(str(self.store.directory) if self.store else '调试目录不可写，请检查用户目录权限。');label.setWordWrap(True);layout.addWidget(label)
        actions=QHBoxLayout();layout.addLayout(actions)
        for text,callback in (('刷新日志',self.refresh),('保存快照',self.capture),('导出调试包',self.export),('打开日志目录',self.open_folder)):
            button=QPushButton(text);button.clicked.connect(callback);actions.addWidget(button);button.setEnabled(self.store is not None)
        actions.addStretch()
        self.view=QPlainTextEdit();self.view.setReadOnly(True)
        font=QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont);font.setPointSize(10);self.view.setFont(font)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);layout.addWidget(self.view,1)
        self.status=QLabel();self.status.setTextFormat(Qt.TextFormat.PlainText);self.status.setWordWrap(True);layout.addWidget(self.status)
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.refresh);self.timer.start();self.refresh()

    def refresh(self):
        if not self.store:return
        try:
            text=self.store.tail()
            if self.view.toPlainText()!=text:
                bar=self.view.verticalScrollBar();at_end=bar.value()>=bar.maximum();position=bar.value()
                self.view.setPlainText(text);bar.setValue(bar.maximum() if at_end else position)
        except OSError as exc:self.status.setText(str(exc))

    def capture(self):
        try:
            path=snapshot('manual',screen=self.window.grab())
            self.status.setText('已保存状态JSON与当前工具箱截图：'+str(path));self.refresh()
        except Exception as exc:self.status.setText('快照保存失败：'+str(exc))

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出本地调试包','VTStudio-debug-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip','ZIP (*.zip)')
        if not path:return
        try:
            snapshot('debug_export');self.store.export(path)
            self.status.setText('已导出：'+path);event('diagnostics','bundle_exported',path=path)
        except Exception as exc:self.status.setText('导出失败：'+str(exc))

    def open_folder(self):
        if self.store:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory)))

    def showEvent(self,event):
        super().showEvent(event);self.timer.start();self.refresh()

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
