"""Compact native tool strips with an animated selection marker."""
from PySide6.QtCore import Signal,QPropertyAnimation,QEasingCurve,QRect,QTimer,QAbstractAnimation
from PySide6.QtWidgets import QWidget,QPushButton,QHBoxLayout,QButtonGroup


class ModeStrip(QWidget):
    currentIndexChanged=Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._index=-1;self._items=[]
        self.row=QHBoxLayout(self);self.row.setContentsMargins(0,0,0,4);self.row.setSpacing(5)
        self.row.addStretch()
        self.group=QButtonGroup(self);self.group.setExclusive(True)
        self.marker=QWidget(self);self.marker.setStyleSheet('background:#b5531c;border-radius:1px;')
        self.animation=QPropertyAnimation(self.marker,b'geometry',self)
        self.animation.setDuration(150);self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.group.idClicked.connect(self.setCurrentIndex)

    def addItem(self,label,data):
        button=QPushButton(label,self);button.setCheckable(True);button.setObjectName('CanvasTool')
        button.setMinimumWidth(0)
        self.group.addButton(button,len(self._items));self.row.insertWidget(len(self._items),button)
        self._items.append((data,button))
        if self._index<0:
            self.setCurrentIndex(0)

    def currentData(self):
        return self._items[self._index][0] if self._index>=0 else None

    def findData(self,value):
        return next((i for i,(data,_) in enumerate(self._items) if data==value),-1)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self,index):
        if not 0<=index<len(self._items):
            return
        changed=index!=self._index
        self._index=index;self._items[index][1].setChecked(True)
        self._move_marker(changed)
        if changed:
            self.currentIndexChanged.emit(index)

    def _move_marker(self,animate=False):
        if self._index<0:
            return
        button=self._items[self._index][1]
        target=QRect(button.x()+8,self.height()-3,max(8,button.width()-16),2)
        if not animate and self.animation.state()==QAbstractAnimation.State.Running:
            self.animation.setEndValue(target)
            return
        self.animation.stop()
        if animate and self.isVisible() and self.marker.geometry().width()>1:
            self.animation.setStartValue(self.marker.geometry());self.animation.setEndValue(target);self.animation.start()
        else:
            self.marker.setGeometry(target)
        self.marker.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        QTimer.singleShot(0,lambda:self._move_marker(False))
