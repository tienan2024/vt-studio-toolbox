"""A concrete preview of the target and port changes before SDK application."""
from pathlib import Path
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QLineEdit,QPushButton,QDialogButtonBox,QFileDialog,QPlainTextEdit)
from sol_apply import apply_script,plan_application,discover_vm,sdk_apps,SolApplyError


class SolApplyJob(QThread):
    result=Signal(str,object)
    failed=Signal(str)
    progress=Signal(str)
    action='apply'

    def __init__(self,request,parent=None):super().__init__(parent);self.request=request

    def run(self):
        try:self.result.emit('apply',apply_script(**self.request,progress=self.progress.emit))
        except Exception as exc:self.failed.emit(str(exc))
        finally:self.request['password']=None


class SolApplyDialog(QDialog):
    def __init__(self,path,module,config,parent=None):
        super().__init__(parent);self.setWindowTitle('应用脚本到 SOL');self.resize(720,490)
        self.plan=plan_application(config,module);self.path=Path(path)
        root=QVBoxLayout(self);root.setSpacing(12)
        title=QLabel(module['flow']+' / '+module['name']+' · ID '+module['id']);title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText);title.setStyleSheet('font-size:16px;font-weight:600;');root.addWidget(title)
        info=QLabel('将当前生成代码导入所选模块，使用 VM 编译后另存新方案，再独立重载校验。原方案保留。')
        info.setWordWrap(True);root.addWidget(info)
        form=QFormLayout();self.sdk=QLineEdit(discover_vm());sdk_row=QHBoxLayout();sdk_row.addWidget(self.sdk,1)
        browse=QPushButton('选择目录');browse.clicked.connect(self.browse_sdk);sdk_row.addWidget(browse);form.addRow('VisionMaster',sdk_row)
        output=self.path.with_name(self.path.stem+'_脚本已应用.sol');index=2
        while output.exists():output=self.path.with_name(self.path.stem+'_脚本已应用_'+str(index)+'.sol');index+=1
        self.output=QLineEdit(str(output));out_row=QHBoxLayout();out_row.addWidget(self.output,1)
        choose=QPushButton('另存位置');choose.clicked.connect(self.browse_output);out_row.addWidget(choose);form.addRow('新方案',out_row)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('受保护方案填写密码，仅用于本次应用');form.addRow('方案密码',self.password);root.addLayout(form)
        summary=QPlainTextEdit();summary.setReadOnly(True)
        lines=['沿用已有变量与原绑定：'+str(len(self.plan['preserved']))+' 项']
        lines+=['  '+r['direction']+'  '+r['name']+' ('+r['type']+')' for r in self.plan['preserved']]
        lines+=['新增变量：'+str(len(self.plan['added']))+' 项（原变量不删除、不重命名）']
        lines+=['  '+r['direction']+'  '+r['name']+' ('+r['type']+')' for r in self.plan['added']]
        lines+=['不会运行检测流程。新方案保持原密码；替换所选模块的全部脚本源码。']
        summary.setPlainText('\n'.join(lines));root.addWidget(summary,1)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setTextFormat(Qt.TextFormat.PlainText);root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('编译并另存方案');buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('Primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept_valid);buttons.rejected.connect(self.reject);root.addWidget(buttons)

    def browse_sdk(self):
        path=QFileDialog.getExistingDirectory(self,'选择 VisionMaster 安装目录',self.sdk.text())
        if path:self.sdk.setText(path)

    def browse_output(self):
        path,_=QFileDialog.getSaveFileName(self,'保存为新方案',self.output.text(),'VisionMaster (*.sol)')
        if path:self.output.setText(path if Path(path).suffix else path+'.sol')

    def accept_valid(self):
        try:
            sdk_apps(self.sdk.text());output=Path(self.output.text()).resolve()
            if output==self.path.resolve() or output.exists():raise SolApplyError('请选择新文件名；原方案和已有文件不能覆盖。')
            if output.suffix.lower()!='.sol' or not output.parent.is_dir():raise SolApplyError('请选择有效的新 .sol 路径。')
            self.accept()
        except Exception as exc:self.error.setText(str(exc))
