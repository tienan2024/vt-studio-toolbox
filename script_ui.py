"""Product script builder and compiled C# test bench inside the toolbox."""
import json
from pathlib import Path
import re

from PySide6.QtCore import Qt,QThread,Signal,QTimer,QEvent
from code_preview import CSharpPreview
from script_variables import VariablesPanel
from sol_apply_ui import SolApplyDialog,SolApplyJob
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QLineEdit,QCheckBox,QPushButton,QSplitter,QScrollArea,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView,QTabWidget,QPlainTextEdit,
    QFileDialog,QApplication,QSpinBox,QComboBox,QGroupBox,QProgressBar,QLayout,QDialog,QDialogButtonBox)

from script_generator import (default_config,validate_config,generate_sources,variable_rows,
    save_script,run_cases,run_regression,user_regions,parse_ngtype,ScriptError,
    port_name,physical_inputs,rename_identifiers,FIXED_INPUTS,OUTPUTS)


class AdaptiveRuleTable(QTableWidget):
    """Grow with visible row heights; keep large products within the sidebar."""
    MIN_HEIGHT=96
    MAX_HEIGHT=380

    def __init__(self):
        super().__init__()
        self.height_timer=QTimer(self);self.height_timer.setSingleShot(True)
        self.height_timer.timeout.connect(self.update_height)
        for signal in (self.model().rowsInserted,self.model().rowsRemoved,self.model().modelReset,
                       self.horizontalHeader().geometriesChanged,self.verticalHeader().geometriesChanged,
                       self.verticalHeader().sectionResized):signal.connect(self.schedule_height)
        self.schedule_height()

    def schedule_height(self,*args):self.height_timer.start(0)

    def update_height(self):
        content=self.horizontalHeader().height()+self.verticalHeader().length()+2*self.frameWidth()
        if self.horizontalScrollBar().isVisible():content+=self.horizontalScrollBar().height()
        target=max(self.MIN_HEIGHT,min(self.MAX_HEIGHT,content))
        if self.height()!=target:self.setFixedHeight(target)

    def changeEvent(self,event):
        super().changeEvent(event)
        if hasattr(self,'height_timer') and event.type() in (QEvent.Type.FontChange,QEvent.Type.StyleChange):self.schedule_height()


class ScriptJob(QThread):
    result=Signal(str,object)
    failed=Signal(str)

    def __init__(self,action,config,case,previous,parent=None):
        super().__init__(parent);self.action=action;self.config=config;self.case=case;self.previous=previous

    def run(self):
        try:
            result=(run_cases(self.config,[self.case],self.previous) if self.action=='frame'
                    else run_regression(self.config,self.previous))
            self.result.emit(self.action,result)
        except Exception as exc:self.failed.emit(str(exc))


class ScriptPage(QWidget):
    def __init__(self):
        super().__init__();self.worker=None;self.previous=None;self.sources={};self.config=None;self._loading=False;self.ports={};self.variable_notes={}
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(10)
        split=QSplitter(Qt.Orientation.Horizontal);root.addWidget(split,1)
        self.config_panel=QWidget();left=QVBoxLayout(self.config_panel);left.setContentsMargins(4,0,12,4);left.setSpacing(10)
        self.product=QLineEdit();self.product.setPlaceholderText('例如：女童内装 / 成人纸尿裤')
        form=QFormLayout();form.addRow('产品名称',self.product);left.addLayout(form)
        self.use_ai=QCheckBox('此产品启用 AI 类别判定');self.use_ai.setMinimumHeight(28);left.addWidget(self.use_ai)
        fixed=QLabel('固定输入保留 aiResult、NGtype、Label_name、speed、起始存图速度。关闭 AI 后仅由独立信号判定。')
        fixed.setObjectName('Subtle');fixed.setWordWrap(True);left.addWidget(fixed)
        files=QHBoxLayout()
        self.open_button=self.button('打开产品配置',self.open_config,files)
        self.save_button=self.button('保存产品配置',self.save_config,files);left.addLayout(files)
        left.addWidget(self.section('NGtype · 直接粘贴 VM 中的整行内容'))
        self.ngtype_text=QLineEdit();self.ngtype_text.setPlaceholderText('污点-接头-内装折角-导流层缺失')
        self.ngtype_text.setToolTip('自动按-拆分，顺序就是输出位顺序；无需逐项建立类型。');left.addWidget(self.ngtype_text)
        self.type_summary=QLabel();self.type_summary.setObjectName('Subtle');self.type_summary.setWordWrap(True)
        self.type_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);left.addWidget(self.type_summary)
        left.addWidget(self.section('产品独立信号 · 0 异常 / 1 正常'))
        self.signals=self.table(['输入变量名（XXXResult）','对应 NG 类型'],adaptive=True);left.addWidget(self.signals)
        actions=QHBoxLayout();self.button('添加信号',lambda:self.add_signal(),actions)
        self.button('删除信号',lambda:self.delete_row(self.signals),actions);actions.addStretch();left.addLayout(actions)
        left.addWidget(self.section('AI 标签归一化 · 首条匹配生效'))
        self.aliases=self.table(['匹配方式','原标签文字','归入 NG 类型'],adaptive=True);left.addWidget(self.aliases)
        actions=QHBoxLayout();self.add_alias_button=self.button('添加规则',lambda:self.add_alias(),actions)
        self.delete_alias_button=self.button('删除规则',lambda:self.delete_row(self.aliases),actions);actions.addStretch();left.addLayout(actions)
        self.imported=QLabel('生成代码包含两个 USER CODE 保留区。');self.imported.setWordWrap(True);self.imported.setObjectName('Subtle');left.addWidget(self.imported)
        actions=QHBoxLayout();self.button('导入用户区域',self.import_regions,actions)
        self.clear_regions_button=self.button('恢复表格生成',self.clear_regions,actions);left.addLayout(actions)
        left.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.config_panel)
        column=QWidget();column.setMinimumWidth(355);column_layout=QVBoxLayout(column);column_layout.setContentsMargins(0,0,0,0)
        column_layout.addWidget(scroll,1);split.addWidget(column)
        right=QWidget();right_layout=QVBoxLayout(right);right_layout.setContentsMargins(8,0,0,0);right_layout.setSpacing(8)
        toolbar=QHBoxLayout();note=QLabel('可复制到 VM，也可在变量清单中自动应用到 SOL。');note.setObjectName('Subtle');note.setWordWrap(True);toolbar.addWidget(note,1)
        self.copy_button=self.button('复制脚本',self.copy_code,toolbar);self.copy_button.setObjectName('Primary');self.save_cs_button=self.button('保存 .cs',self.save_cs,toolbar);right_layout.addLayout(toolbar)
        self.tabs=QTabWidget();right_layout.addWidget(self.tabs,1);self.code_views=[]
        for filename in ('脚本代码',):
            view=CSharpPreview()
            self.code_views.append(view);self.tabs.addTab(view,filename)
        self.make_test_panel();self.variables=VariablesPanel(self.table,self)
        self.variables.edited.connect(self.edit_variable);self.variables.apply_requested.connect(self.choose_sol_mapping)
        self.variables.write_requested.connect(self.review_sol_application)
        self.tabs.addTab(self.variables,'变量清单')
        split.addWidget(right);split.setStretchFactor(0,0);split.setStretchFactor(1,1);split.setSizes([400,800])
        self.progress=QProgressBar();self.progress.setTextVisible(False);self.progress.setFixedHeight(5);self.progress.hide();root.addWidget(self.progress)
        self.message=QLabel('粘贴 NGtype 后生成脚本；复制或保存 .cs，在 VM 中按变量清单手工配置端口。');self.message.setObjectName('Message');self.message.setWordWrap(True);root.addWidget(self.message)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.refresh)
        self.product.textChanged.connect(self.changed);self.use_ai.toggled.connect(self.changed)
        self.ngtype_text.textChanged.connect(self.changed)
        for table in (self.signals,self.aliases):table.itemChanged.connect(self.changed)
        self.load_config(default_config())

    @staticmethod
    def section(text):
        label=QLabel(text);label.setStyleSheet('font-weight:600;margin-top:8px;');return label

    @staticmethod
    def table(headers,adaptive=False):
        table=AdaptiveRuleTable() if adaptive else QTableWidget()
        table.setColumnCount(len(headers));table.setHorizontalHeaderLabels(headers)
        table.setObjectName('ScriptTable')
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setDefaultSectionSize(36);table.setAlternatingRowColors(True)
        return table

    @staticmethod
    def button(text,slot,layout):
        button=QPushButton(text);button.clicked.connect(slot);layout.addWidget(button);return button

    @staticmethod
    def fill(table,rows):
        table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row):table.setItem(i,j,QTableWidgetItem(str(value)))

    @staticmethod
    def text(table,i,j):
        item=table.item(i,j);return item.text().strip() if item else ''

    def changed(self,*args):
        if not self._loading:self.timer.start(200)

    def read_config(self):
        note_keys=set(dict(FIXED_INPUTS+OUTPUTS))|{'signal:'+self.text(self.signals,i,0) for i in range(self.signals.rowCount())}
        return validate_config({'schema':'vt-script-product/1','product':self.product.text(),'use_ai':self.use_ai.isChecked(),
            'types':parse_ngtype(self.ngtype_text.text()),'ports':self.ports,'variable_notes':{k:v for k,v in self.variable_notes.items() if k in note_keys},
            'signals':[{'name':self.text(self.signals,i,0),'type':self.target_value(self.signals,i,1)} for i in range(self.signals.rowCount())],
            'aliases':[{'match':{'包含':'contains','等于':'exact'}.get(self.text(self.aliases,i,0),self.text(self.aliases,i,0)),
                        'value':self.text(self.aliases,i,1),'type':self.target_value(self.aliases,i,2)} for i in range(self.aliases.rowCount())]})

    @staticmethod
    def target_value(table,row,column):
        widget=table.cellWidget(row,column)
        return widget.currentData() if widget else ScriptPage.text(table,row,column)

    def sync_targets(self,types):
        loading=self._loading;self._loading=True
        for table,column in ((self.signals,1),(self.aliases,2)):
            for row in range(table.rowCount()):
                old=self.target_value(table,row,column)
                choice=QComboBox()
                if old and old not in types:
                    choice.addItem('未匹配：'+old,old);choice.model().item(0).setEnabled(False)
                for name in types:choice.addItem(name,name)
                index=choice.findData(old);choice.setCurrentIndex(max(0,index))
                choice.setToolTip('目标类型由 NGtype 自动解析。')
                table.setCellWidget(row,column,choice);choice.currentIndexChanged.connect(self.changed)
        self._loading=loading

    def load_config(self,config):
        c=validate_config(config);self._loading=True
        self.ports=dict(c.get('ports',{}));self.variable_notes=dict(c.get('variable_notes',{}))
        self.product.setText(c['product']);self.use_ai.setChecked(c['use_ai'])
        self.ngtype_text.setText('-'.join(c['types']))
        self.signals.clearContents();self.aliases.clearContents()
        self.fill(self.signals,[[r['name'],r['type']] for r in c['signals']])
        self.fill(self.aliases,[[{'contains':'包含','exact':'等于'}[r['match']],r['value'],r['type']] for r in c['aliases']])
        self.previous=None;self._loading=False;self.refresh()

    def refresh(self):
        self.timer.stop()
        try:
            types=parse_ngtype(self.ngtype_text.text())
            self.type_summary.setText('已解析 '+str(len(types))+' 类；输出位顺序与 NGtype 一致。')
            self.sync_targets(types)
            c=self.read_config();sources=generate_sources(c,self.previous)
            old_types='-'.join(self.config['types']) if self.config else None
            changed=self.sources!=sources or self.config!=c
            self.config=c;self.sources=sources
            for view,name in zip(self.code_views,('UserScript.cs',)):view.set_source(sources[name])
            self.variables.set_template(variable_rows(c))
            if old_types is None or self.runtime_types.text()==old_types:self.runtime_types.setText('-'.join(c['types']))
            previous={self.text(self.signal_values,i,0):self.signal_values.cellWidget(i,1).currentIndex() for i in range(self.signal_values.rowCount())}
            self.signal_values.setRowCount(len(c['signals']))
            for i,row in enumerate(c['signals']):
                item=QTableWidgetItem(row['name']);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.signal_values.setItem(i,0,item)
                choice=QComboBox();choice.addItems(['1 · 正常','0 · 异常']);choice.setCurrentIndex(previous.get(row['name'],0));self.signal_values.setCellWidget(i,1,choice)
            self.signal_values.setFixedHeight(min(170,max(65,35+len(c['signals'])*36)))
            self.aliases.setEnabled(c['use_ai'] and self.previous is None)
            self.add_alias_button.setEnabled(c['use_ai'] and self.previous is None);self.delete_alias_button.setEnabled(c['use_ai'] and self.previous is None)
            self.signals.setEnabled(True)
            self.imported.setText('已保留导入的两个 USER CODE 区；代码内容优先于映射表。' if self.previous else '生成代码包含 IndependentJudge / LabelNormalize 两个 USER CODE 区。')
            self.clear_regions_button.setEnabled(self.previous is not None)
            self.ai_result.setEnabled(c['use_ai']);self.labels.setEnabled(c['use_ai']);self.array_state.setEnabled(c['use_ai'])
            if changed:
                self.test_status.setText('代码已更新，请重新运行测试。')
                self.regression_values.setRowCount(0)
                self.fill(self.output_values,[[r['name'],r['type'],'等待测试'] for r in variable_rows(c) if r['direction']=='输出'])
            self.notify('代码与变量清单已更新。'+('无 AI 模式：保留兼容输入，不读取标签。' if not c['use_ai'] else 'Label_name 使用数组 API 整组读取。'))
            return c
        except Exception as exc:
            self.sources={}
            for view in self.code_views:view.setPlainText('// 配置不完整，修正后自动生成代码。')
            self.notify(str(exc),True);return None

    def add_signal(self):
        try:target=parse_ngtype(self.ngtype_text.text())[0]
        except ScriptError:target=''
        i=self.signals.rowCount();self.signals.insertRow(i);self.signals.setItem(i,0,QTableWidgetItem('新信号Result'));self.signals.setItem(i,1,QTableWidgetItem(target));self.changed()

    def edit_variable(self,key,name,note):
        try:
            c=self.read_config();old=port_name(c,key)
            if key.startswith('signal:'):
                old=key[7:]
                for row in c['signals']:
                    if row['name']==old:row['name']=name
                notes=c.setdefault('variable_notes',{});notes.pop(key,None);notes['signal:'+name]=note
            else:
                c.setdefault('ports',{})[key]=name;c.setdefault('variable_notes',{})[key]=note
            c=validate_config(c)
            previous=rename_identifiers(self.previous,{old:name}) if self.previous else None
            self.load_config(c);self.previous=previous
            if previous:self.refresh()
        except Exception as exc:
            if self.config:self.variables.set_template(variable_rows(self.config))
            self.notify(str(exc),True)

    def sol_signals(self,module):
        if not module:raise ScriptError('请先选择脚本模块。')
        inputs={r['name']:r for r in module['inputs']};outputs={r['name']:r for r in module['outputs']}
        for name,kind in FIXED_INPUTS:
            if name=='aiResult' and name not in inputs:continue
            if name not in inputs or inputs[name]['type']!=kind:raise ScriptError('此模块无法直接套用 NG 模板：缺少标准输入 '+name+' 或类型不同。可继续查看原始清单。')
        if set(outputs)!=set(dict(OUTPUTS)) or any(outputs[n]['type']!=t for n,t in OUTPUTS):raise ScriptError('此模块输出不符合 NG 模板的四项标准输出；原始变量仍可查看。')
        signals=[r for r in module['inputs'] if r['name'] not in dict(FIXED_INPUTS)]
        if any(r['type']!='int' or not r['name'].endswith('Result') or r.get('array') for r in signals):raise ScriptError('存在 NG 模板不支持的输入；请使用原始清单参考，不自动推断其逻辑。')
        return signals

    def choose_sol_mapping(self,module):
        try:
            signals=self.sol_signals(module);c=self.read_config()
            dialog=QDialog(self);dialog.setWindowTitle('将 SOL 变量用于当前 NG 模板');dialog.resize(520,400)
            layout=QVBoxLayout(dialog);info=QLabel('变量已自动读取。请确认各独立信号对应的 NG 类型；将使用当前模板生成逻辑，原 SOL 不变。')
            info.setWordWrap(True);layout.addWidget(info)
            content=QWidget();form=QFormLayout(content);choices={};existing={r['name']:r['type'] for r in c['signals']}
            for signal in signals:
                choice=QComboBox();choice.addItem('请选择对应类型','')
                for target in c['types']:choice.addItem(target,target)
                choice.setCurrentIndex(max(0,choice.findData(existing.get(signal['name'],''))))
                form.addRow(signal['name'],choice);choices[signal['name']]=choice
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(content);layout.addWidget(scroll,1)
            error=QLabel();error.setWordWrap(True);layout.addWidget(error)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
            def accept():
                if any(not q.currentData() for q in choices.values()):error.setText('请为每个独立信号选择类型。');return
                dialog.accept()
            buttons.accepted.connect(accept);buttons.rejected.connect(dialog.reject)
            if dialog.exec():self.apply_sol_module(module,{n:q.currentData() for n,q in choices.items()})
        except Exception as exc:self.notify(str(exc),True)

    def apply_sol_module(self,module,mappings):
        signals=self.sol_signals(module);c=self.read_config()
        c['signals']=[{'name':r['name'],'type':mappings.get(r['name'],'')} for r in signals]
        missing=not any(r['name']=='aiResult' for r in module['inputs'])
        if missing:c['use_ai']=False
        c.pop('ports',None);c.pop('variable_notes',None);self.load_config(c)
        self.variables.source.setCurrentIndex(0)
        self.notify('已应用 '+module['flow']+' / '+module['name']+' 的变量，使用当前 NG 模板生成逻辑。'+('已补充 aiResult 兼容输入并关闭 AI 判定。' if missing else '请确认本产品 AI 规则。'))

    def review_sol_application(self,module):
        if self.is_busy():return
        c=self.refresh()
        if c is None:return
        try:
            dialog=SolApplyDialog(self.variables.metadata['path'],module,c,self)
            if not dialog.exec():return
            request={'path':self.variables.metadata['path'],'module_id':module['id'],'config':c,
                     'output':dialog.output.text(),'password':dialog.password.text(),
                     'applications':dialog.sdk.text(),'previous':self.previous}
            dialog.password.clear();self.start_sol_application(request)
        except Exception as exc:self.notify(str(exc),True)

    def start_sol_application(self,request):
        if self.is_busy():return
        self.worker=SolApplyJob(request,self);self.worker.result.connect(self.test_finished)
        self.worker.failed.connect(self.test_failed);self.worker.finished.connect(self.job_stopped)
        self.worker.progress.connect(self.notify)
        for widget in (self.config_panel,self.test_inputs,self.run_button,self.regression_button,self.save_cs_button,self.variables):widget.setEnabled(False)
        self.progress.setRange(0,0);self.progress.show();self.notify('正在准备 VM 编译与方案另存…');self.worker.start()

    def add_alias(self):
        i=self.aliases.rowCount();self.aliases.insertRow(i)
        try:target=parse_ngtype(self.ngtype_text.text())[0]
        except ScriptError:target=''
        for j,value in enumerate(('包含','新标签',target)):self.aliases.setItem(i,j,QTableWidgetItem(value))
        self.changed()

    def delete_row(self,table):
        if table.currentRow()>=0:table.removeRow(table.currentRow());self.changed()

    def notify(self,text,error=False):
        self.message.setText(text);self.message.setProperty('error',error)
        self.message.style().unpolish(self.message);self.message.style().polish(self.message)

    def open_config(self):
        path,_=QFileDialog.getOpenFileName(self,'打开产品配置','','JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>1_000_000:raise ScriptError('产品配置文件超过1MB。')
            self.load_config(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            self.notify('已打开产品配置：'+path)
        except Exception as exc:self.notify(str(exc),True)

    def save_config(self):
        c=self.refresh()
        if c is None:return
        path,_=QFileDialog.getSaveFileName(self,'保存产品配置',c['product']+'.json','JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8');self.notify('已保存配置；导入的用户代码请通过“保存 .cs”保存。')
            except Exception as exc:self.notify('配置保存失败：'+str(exc),True)

    def import_regions(self):
        path,_=QFileDialog.getOpenFileName(self,'导入已有 UserScript.cs 的两个 USER CODE 区','','C# (*.cs)')
        if not path:return
        try:
            if Path(path).stat().st_size>1_000_000:raise ScriptError('脚本超过1MB。')
            source=Path(path).read_text(encoding='utf-8-sig');user_regions(source);self.previous=source;self.refresh()
        except Exception as exc:self.notify(str(exc),True)

    def clear_regions(self):self.previous=None;self.refresh()

    def save_cs(self,path=None):
        c=self.refresh()
        if c is None:return
        if not path:
            dialog=QFileDialog(self,'保存可导入VM的脚本','UserScript.cs','C# (*.cs)')
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave);dialog.setDefaultSuffix('cs')
            if not dialog.exec():return
            path=dialog.selectedFiles()[0]
        try:
            result=save_script(c,path,self.previous,overwrite=True)
            self.notify('已保存单个脚本：'+result['output']+'；VM中的输入、输出变量仍需手工配置。')
        except Exception as exc:self.notify(str(exc),True)

    def copy_code(self):
        if self.refresh() is not None:
            QApplication.clipboard().setText(self.sources['UserScript.cs'])
            self.notify('已复制脚本。粘贴到 VM 脚本模块后，请按变量清单手工配置输入、输出。')

    def make_test_panel(self):
        test=QWidget();layout=QVBoxLayout(test);layout.setContentsMargins(12,12,12,12);layout.setSpacing(10)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        info=QLabel('编译并执行当前生成的 C#；使用离线 VM 输入输出替身，不运行现有视觉方案。')
        info.setWordWrap(True);info.setObjectName('Subtle');layout.addWidget(info)
        self.test_inputs=QGroupBox('当前测试帧');form=QFormLayout(self.test_inputs)
        form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.runtime_types=QLineEdit();form.addRow('NGtype',self.runtime_types)
        row=QHBoxLayout();self.ai_result=QComboBox();self.ai_result.addItems(['1 · AI 正常','0 · AI 异常']);row.addWidget(self.ai_result)
        self.array_state=QComboBox();self.array_state.addItems(['正常标签数组','模拟读取失败','模拟数组缺失','模拟负数量','模拟超容量']);row.addWidget(self.array_state,1);form.addRow('AI 输入',row)
        self.labels=QPlainTextEdit();self.labels.setObjectName('ScriptLabels');self.labels.setFixedHeight(70);self.labels.setPlaceholderText('每行一个标签，也可用逗号分隔，例如：污点，胶滴，接头');form.addRow('Label_name',self.labels)
        speedrow=QHBoxLayout();self.speed=QSpinBox();self.speed.setRange(-2147483648,2147483647);self.speed.setValue(100)
        self.save_speed=QSpinBox();self.save_speed.setRange(-2147483648,2147483647);self.save_speed.setValue(80)
        speedrow.addWidget(self.speed);speedrow.addWidget(QLabel('起始存图速度'));speedrow.addWidget(self.save_speed);form.addRow('speed',speedrow)
        self.signal_values=self.table(['独立信号输入','当前值']);form.addRow(self.signal_values);layout.addWidget(self.test_inputs)
        actions=QHBoxLayout();self.run_button=self.button('编译并测试当前帧',lambda:self.start_test('frame'),actions);self.run_button.setObjectName('Primary')
        self.regression_button=self.button('运行预设回归',lambda:self.start_test('regression'),actions);actions.addStretch();layout.addLayout(actions)
        self.test_status=QLabel('尚未运行。Process 返回值与四项输出会显示在下面。');self.test_status.setWordWrap(True);layout.addWidget(self.test_status)
        self.test_status.setTextFormat(Qt.TextFormat.PlainText)
        self.result_tabs=QTabWidget();self.result_tabs.setMinimumHeight(235);layout.addWidget(self.result_tabs,1)
        self.output_values=self.table(['输出变量','类型','最近一次测试值']);self.output_values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.output_values.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.output_values.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        self.fill(self.output_values,[[r['name'],r['type'],'等待测试'] for r in variable_rows(default_config()) if r['direction']=='输出'])
        self.result_tabs.addTab(self.output_values,'四项输出')
        self.regression_values=self.table(['用例','预期位串','实际位串','返回值','结果']);self.regression_values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.regression_values,'预设回归结果')
        self.test_scroll=QScrollArea();self.test_scroll.setWidgetResizable(True);self.test_scroll.setWidget(test);self.tabs.addTab(self.test_scroll,'离线测试')

    def current_case(self):
        data={'NGtype':self.runtime_types.text(),'aiResult':1-self.ai_result.currentIndex(),
              'Label_name':[v.strip() for v in re.split('[,，\r\n]',self.labels.toPlainText()) if v.strip()],
              'speed':self.speed.value(),'起始存图速度':self.save_speed.value()}
        for i in range(self.signal_values.rowCount()):data[self.text(self.signal_values,i,0)]=1-self.signal_values.cellWidget(i,1).currentIndex()
        state=self.array_state.currentIndex()
        if state==1:data['label_read_status']=1
        elif state==2:data['Label_name']=None
        elif state==3:data['label_count']=-1
        elif state==4:data['label_count']=4097
        return physical_inputs(self.config or {},data)

    def start_test(self,action):
        if self.is_busy():return
        c=self.refresh()
        if c is None:return
        if action=='frame':self.fill(self.output_values,[[r['name'],r['type'],'正在测试…'] for r in variable_rows(c) if r['direction']=='输出'])
        self.worker=ScriptJob(action,c,self.current_case(),self.previous,self)
        self.worker.result.connect(self.test_finished);self.worker.failed.connect(self.test_failed);self.worker.finished.connect(self.job_stopped)
        self.config_panel.setEnabled(False);self.test_inputs.setEnabled(False);self.run_button.setEnabled(False);self.regression_button.setEnabled(False)
        self.save_cs_button.setEnabled(False)
        self.variables.setEnabled(False)
        self.progress.setRange(0,0);self.progress.show();self.test_status.setText('正在编译并执行 C#…');self.notify('正在编译生成的源码并运行离线用例…');self.worker.start()

    def test_failed(self,text):
        self.notify(text,True)
        if getattr(self.worker,'action','')!='apply':self.test_status.setText('测试未完成：'+text)

    def test_finished(self,action,data):
        if action=='apply':
            self.variables.status.setText('应用完成：'+data['output'])
            self.notify('VM 编译、另存和独立重载校验完成：'+data['output']+'。检测流程未运行。')
            return
        if action=='frame':
            row=data['results'][0];outputs=row['outputs']
            self.fill(self.output_values,[[r['name'],r['type'],outputs[r['name']]] for r in variable_rows(self.config) if r['direction']=='输出'])
            self.output_values.resizeRowsToContents();self.result_tabs.setCurrentIndex(0)
            self.test_status.setText('Process 返回：'+str(row['process_return'])+'    标签数组读取：'+str(row['label_read_calls'])+' 次')
            self.notify('C# 编译与执行完成。'+('存在分类或配置异常，请检查 NG_name。' if not row['process_return'] else '业务 NG 通过输出位判断。'),not row['process_return'])
        else:
            self.fill(self.regression_values,[[r['name'],r['expected_bits'],r['actual']['outputs'][port_name(self.config,'outResult_index')],r['actual']['process_return'],'通过' if r['passed'] else '不一致'] for r in data['cases']])
            self.result_tabs.setCurrentIndex(1);self.test_status.setText('预设回归：'+str(data['passed'])+' / '+str(data['total'])+' 通过')
            self.notify('预设回归完成：'+str(data['passed'])+' / '+str(data['total'])+' 通过。',data['passed']!=data['total'])
        self.test_scroll.ensureWidgetVisible(self.result_tabs)

    def job_stopped(self):
        self.config_panel.setEnabled(True);self.test_inputs.setEnabled(True);self.run_button.setEnabled(True);self.regression_button.setEnabled(True);self.progress.hide()
        self.save_cs_button.setEnabled(True)
        self.variables.setEnabled(True)
        job=self.worker;self.worker=None;job.deleteLater()

    def is_busy(self):return self.worker is not None or self.variables.is_busy()
