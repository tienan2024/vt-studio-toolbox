"""Editable template ports and read-only SOL port reference, without VM runtime."""
from pathlib import Path
from PySide6.QtCore import Qt,QThread,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QGroupBox,QTableWidgetItem,QScrollArea,QInputDialog,QLineEdit,
    QFileDialog,QHeaderView,QAbstractItemView,QSplitter)
from sol_reader import read_sol,SolPasswordError


class SolJob(QThread):
    result=Signal(object)
    failed=Signal(str,bool)

    def __init__(self,path,password,parent):
        super().__init__(parent);self.path=path;self.password=password

    def run(self):
        try:self.result.emit(read_sol(self.path,self.password))
        except SolPasswordError as exc:self.failed.emit(str(exc),True)
        except Exception as exc:self.failed.emit('SOL读取失败：'+str(exc),False)
        finally:self.password=None


class VariablesPanel(QWidget):
    edited=Signal(str,str,str)
    apply_requested=Signal(object)
    write_requested=Signal(object)

    def __init__(self,factory,parent=None):
        super().__init__(parent);self.job=None;self.metadata=None;self.rows=[];self.template_rows=[];self._loading=False
        self.pending_password=False;self.last_error='';self.path=''
        layout=QVBoxLayout(self);layout.setContentsMargins(12,12,12,12);layout.setSpacing(12)
        actions=QHBoxLayout();self.source=QComboBox();self.source.addItem('当前生成脚本');actions.addWidget(self.source,1)
        self.open_button=QPushButton('打开 SOL');actions.addWidget(self.open_button);layout.addLayout(actions)
        self.selectors=QWidget();select=QHBoxLayout(self.selectors);select.setContentsMargins(0,0,0,0)
        select.addWidget(QLabel('流程'));self.flow=QComboBox();select.addWidget(self.flow,1)
        select.addWidget(QLabel('脚本'));self.module=QComboBox();select.addWidget(self.module,1)
        self.apply_button=QPushButton('使用此模块变量');select.addWidget(self.apply_button);layout.addWidget(self.selectors);self.selectors.hide()
        self.write_bar=QWidget();write=QHBoxLayout(self.write_bar);write.setContentsMargins(0,0,0,0)
        hint=QLabel('将当前生成脚本应用到所选模块，另存为新方案。');hint.setWordWrap(True);write.addWidget(hint,1)
        self.write_button=QPushButton('应用脚本到 SOL');self.write_button.setObjectName('Primary');write.addWidget(self.write_button)
        layout.addWidget(self.write_bar);self.write_bar.hide()
        self.info=QLabel('双击变量名或说明即可编辑；类型由脚本用途确定。修改会同步到代码与离线测试。')
        self.info.setObjectName('Subtle');self.info.setWordWrap(True);self.info.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.info)
        groups=QSplitter(Qt.Orientation.Vertical);groups.setChildrenCollapsible(False);groups.setHandleWidth(12)
        self.tables={};self.groups={}
        for direction in ('输入','输出'):
            group=QGroupBox(direction+'变量');box=QVBoxLayout(group);box.setContentsMargins(12,10,12,12)
            table=factory(['用途','变量名','VM 类型','说明']);table.setMinimumHeight(75)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
            table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked|QAbstractItemView.EditTrigger.EditKeyPressed)
            table.verticalHeader().hide();table.setWordWrap(False)
            table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setMinimumSectionSize(65)
            table.itemChanged.connect(self.cell_changed);box.addWidget(table);groups.addWidget(group)
            self.groups[direction]=group;self.tables[direction]=table
        groups.setSizes([320,200]);groups.setStretchFactor(0,3);groups.setStretchFactor(1,2);layout.addWidget(groups,1)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        self.open_button.clicked.connect(self.open_sol);self.source.currentIndexChanged.connect(self.show_source)
        self.flow.currentIndexChanged.connect(self.select_flow);self.module.currentIndexChanged.connect(self.show_source)
        self.apply_button.clicked.connect(lambda:self.apply_requested.emit(self.selected_module()))
        self.write_button.clicked.connect(lambda:self.write_requested.emit(self.selected_module()))

    def set_template(self,rows):
        self.template_rows=rows
        if self.source.currentIndex()==0:self.render(rows,True)

    def render(self,rows,editable):
        self._loading=True;self.rows=rows
        for direction,table in self.tables.items():
            subset=[r for r in rows if r['direction']==direction];table.setRowCount(len(subset))
            table.setColumnHidden(0,not editable)
            self.groups[direction].setTitle(direction+'变量 · '+str(len(subset))+' 项')
            for i,row in enumerate(subset):
                for j,value in enumerate((row.get('role','SOL端口'),row['name'],row['type'],row.get('note',''))):
                    item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,row.get('key',''))
                    if not editable or j not in (1,3):item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    item.setToolTip(value+('；类型由用途决定' if j==2 and editable else ''))
                    table.setItem(i,j,item)
        self._loading=False

    def cell_changed(self,item):
        if self._loading or self.source.currentIndex()!=0:return
        table=item.tableWidget();row=item.row()
        self.edited.emit(item.data(Qt.ItemDataRole.UserRole),table.item(row,1).text().strip(),table.item(row,3).text().strip())

    def show_source(self,*args):
        reference=self.source.currentIndex()!=0
        self.selectors.setVisible(reference)
        self.write_bar.setVisible(reference)
        if not reference:
            self.info.setText('双击变量名或说明即可编辑；类型由脚本用途确定。修改会同步到代码与离线测试。')
            self.render(self.template_rows,True)
        else:
            module=self.selected_module();rows=[]
            if module:
                for key,direction in (('inputs','输入'),('outputs','输出')):
                    rows.extend(dict(p,direction=direction,role='SOL端口') for p in module[key])
            self.info.setText('SOL 原始变量只读显示。应用到当前 NG 模板后可编辑名称；原方案不会被修改。')
            self.render(rows,False)
        self.apply_button.setEnabled(reference and self.selected_module() is not None and not self.is_busy())
        self.write_button.setEnabled(reference and self.selected_module() is not None and not self.is_busy())

    def selected_module(self):
        ident=self.module.currentData()
        return next((s for s in (self.metadata or {}).get('scripts',[]) if s['id']==ident),None)

    def select_flow(self,*args):
        self.module.blockSignals(True);self.module.clear()
        for script in (self.metadata or {}).get('scripts',[]):
            if script['flow_id']==self.flow.currentData():self.module.addItem(script['name']+' · ID '+script['id'],script['id'])
        self.module.blockSignals(False);self.show_source()

    def set_metadata(self,data):
        self.metadata=data;self.flow.blockSignals(True);self.flow.clear();seen=set()
        for script in data['scripts']:
            if script['flow_id'] not in seen:self.flow.addItem(script['flow'],script['flow_id']);seen.add(script['flow_id'])
        self.flow.blockSignals(False)
        self.source.blockSignals(True)
        if self.source.count()==1:self.source.addItem('SOL：'+Path(data['path']).name)
        else:self.source.setItemText(1,'SOL：'+Path(data['path']).name)
        self.source.setCurrentIndex(1);self.source.blockSignals(False);self.select_flow()
        self.status.setText('已读取 '+str(len(data['scripts']))+' 个脚本模块；未运行或保存原 SOL。')

    def open_sol(self):
        if self.is_busy():return
        path,_=QFileDialog.getOpenFileName(self,'读取流程中的脚本变量','','VisionMaster (*.sol)')
        if path:self.start_read(path)

    def start_read(self,path,password=None):
        if self.is_busy():return
        self.path=path;self.pending_password=False;self.last_error='';self.job=SolJob(path,password,self)
        self.job.result.connect(self.set_metadata);self.job.failed.connect(self.read_failed);self.job.finished.connect(self.read_stopped)
        self.set_controls(False);self.status.setText('正在只读提取 SOL 元数据…');self.job.start()

    def read_failed(self,text,needs_password):
        self.last_error=text;self.pending_password=needs_password;self.status.setText(text)

    def read_stopped(self):
        job=self.job;self.job=None;job.deleteLater();self.set_controls(True)
        if self.pending_password:
            self.pending_password=False
            password,ok=QInputDialog.getText(self,'SOL 方案密码','仅用于本次只读提取，不保存密码：',QLineEdit.EchoMode.Password)
            if ok and password:self.start_read(self.path,password)
            else:self.status.setText('已取消密码输入；当前清单保持不变。')

    def set_controls(self,enabled):
        for widget in (self.source,self.flow,self.module,self.open_button):widget.setEnabled(enabled)
        self.apply_button.setEnabled(enabled and self.source.currentIndex()!=0 and self.selected_module() is not None)
        self.write_button.setEnabled(enabled and self.source.currentIndex()!=0 and self.selected_module() is not None)

    def is_busy(self):return self.job is not None
