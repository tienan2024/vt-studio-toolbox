"""Shared native controls. Keep models, delegates, signals and business state intact."""
import weakref
from PySide6.QtCore import QObject,QEvent,QTimer
from shiboken6 import isValid
from PySide6.QtWidgets import (QApplication,QWidget,QComboBox,QAbstractSpinBox,
    QSpinBox,QDoubleSpinBox,QLineEdit,QAbstractItemView,QListView,QStyleFactory)
from theme import SHARED_POPUP

_fusion=None
_types=(QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit)


def _inside(widget,kind):
    parent=widget.parentWidget()
    while parent is not None:
        if isinstance(parent,kind):return True
        parent=parent.parentWidget()
    return False


def style_control(widget):
    global _fusion
    if not isinstance(widget,_types):return
    if isinstance(widget,QLineEdit) and isinstance(widget.parentWidget(),(QComboBox,QAbstractSpinBox)):
        return
    if not widget.property('vtSharedReady'):
        widget.setProperty('vtSharedReady',True)
        if isinstance(widget,QComboBox):
            if QApplication.instance().style().objectName().lower()!='fusion':
                if _fusion is None:_fusion=QStyleFactory.create('Fusion')
                widget.setStyle(_fusion)
            widget.setMaxVisibleItems(8)
            view=widget.view()
            if view.metaObject().className()=='QComboBoxListView' and view.itemDelegate().metaObject().className() in ('QComboBoxDelegate','QComboMenuDelegate'):
                view=QListView();widget.setView(view)
            view.setStyleSheet(SHARED_POPUP)
            if isinstance(view,QListView):view.setSpacing(2)
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            popup=view.window();popup.setObjectName('ToolboxPopup')
            popup.setStyleSheet('QWidget#ToolboxPopup { background:#ffffff; color:#263548; border:0; }')
    compact=_inside(widget,QAbstractItemView) or widget.maximumWidth()<=140
    if isinstance(widget,QAbstractSpinBox):
        no_buttons=widget.buttonSymbols()==QAbstractSpinBox.ButtonSymbols.NoButtons
        if widget.property('vtNoButtons')!=no_buttons:
            widget.setProperty('vtNoButtons',no_buttons);widget.style().unpolish(widget);widget.style().polish(widget)
    if widget.property('vtCompact')!=compact:
        widget.setProperty('vtCompact',compact);widget.style().unpolish(widget);widget.style().polish(widget)
    target=28 if compact else 36
    if widget.minimumHeight()!=target or widget.maximumHeight()!=target:widget.setFixedHeight(target)


def make_combo():
    widget=QComboBox();style_control(widget);return widget


class SharedControls(QObject):
    def __init__(self,root):
        super().__init__(root);self.root=weakref.ref(root);self.active=False;self.pending=set()
        QApplication.instance().installEventFilter(self)
        for widget in root.findChildren(QWidget):style_control(widget)

    def eventFilter(self,obj,event):
        if not self.active and event.type() in (QEvent.Type.Show,QEvent.Type.ParentChange):
            root=self.root()
            if root is not None and isinstance(obj,_types) and root.isAncestorOf(obj):
                if obj not in self.pending:
                    self.pending.add(obj);QTimer.singleShot(0,lambda widget=obj:self.apply_pending(widget))
        return False

    def apply_pending(self,widget):
        self.pending.discard(widget)
        if not isValid(self) or not isValid(widget):return
        self.active=True
        try:style_control(widget)
        finally:self.active=False


def install_shared_controls(root):
    existing=getattr(root,'_shared_controls',None)
    if existing is None:
        app=QApplication.instance()
        if app.style().objectName().lower()!='fusion':app.setStyle('Fusion')
        root._shared_controls=SharedControls(root)
    return root._shared_controls
