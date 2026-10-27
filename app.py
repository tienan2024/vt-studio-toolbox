"""Windows desktop workflow for local defect synthesis."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
import sys
import uuid

from PIL import Image
from PySide6.QtCore import Qt, QPointF, QRectF, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QImage,
                           QPainter, QPainterPath, QPen, QPixmap, QIcon)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QGraphicsPathItem, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget, QAbstractSpinBox)

from engine import (Asset, Settings, SynthesisError, VERSION, MAX_TOTAL_SAMPLES, MAX_ROI_REGIONS, extract_asset,
                    generate_batch, load_image, load_recipe, save_recipe, synthesize)
from pool import (PoolEntry, MAX_POOL_ENTRIES, choose_sample, generate_pool_batch,
                  save_pool_recipe, load_pool_recipe)
from ui_controls import ModeStrip

IMAGE_FILTER = "灰度 / RGB 图 (*.bmp *.png *.tif *.tiff);;所有文件 (*)"


@dataclass
class NGDocument:
    path: str
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    asset: Asset | None = None
    roi: tuple = (0.,0.,1.,1.)
    roi_origin: str = "全图"
    rois: tuple = ()


class AdaptiveImageList(QListWidget):
    MIN_HEIGHT,MAX_HEIGHT=80,180

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for signal in (self.model().rowsInserted,self.model().rowsRemoved,self.model().modelReset,self.model().dataChanged):
            signal.connect(self.schedule_height)
        self.schedule_height()

    def schedule_height(self,*_):
        QTimer.singleShot(0,self.update_height)

    def update_height(self):
        row=max((self.sizeHintForRow(i) for i in range(min(self.count(),6))),default=self.fontMetrics().height()+18)
        desired=self.count()*max(1,row)+2*self.frameWidth()+12
        self.setFixedHeight(max(self.MIN_HEIGHT,min(self.MAX_HEIGHT,desired)))

    def changeEvent(self,event):
        super().changeEvent(event)
        self.schedule_height()


def pixmap(image: Image.Image) -> QPixmap:
    if image.mode == "L":
        raw = image.tobytes()
        qimage = QImage(raw, image.width, image.height, image.width, QImage.Format.Format_Grayscale8).copy()
    else:
        image = image.convert("RGBA")
        raw = image.tobytes()
        qimage = QImage(raw, image.width, image.height, image.width*4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class Canvas(QGraphicsView):
    selection_changed = Signal(list)
    zoom_changed = Signal(str)

    def __init__(self, empty_text):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#202b30"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(240, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.image = None
        self.mode = "view"
        self.points = []
        self.draft = []
        self.anchor = None
        self.pan = None
        self.pan_origin = None
        self.pan_dragged = False
        self.selection_item = None
        self.guides = {}
        self.selection_color = "#39dbc4"
        self.overlay = None
        self.auto_fit = True
        self.set_empty(empty_text)

    def set_empty(self, empty_text):
        self.scene().clear()
        self.image = None
        self.selection_item = None
        self.guides = {}
        self.overlay = None
        self.points, self.draft, self.anchor = [], [], None
        self.pan,self.pan_origin,self.pan_dragged = None,None,False
        self.auto_fit = True
        self.resetTransform()
        self.setBackgroundBrush(QColor('#eef1f5'))
        card=QPainterPath();card.addRoundedRect(QRectF(0,0,320,180),10,10)
        panel=self.scene().addPath(card,QPen(QColor('#d5dde7')),QColor('#ffffff'))
        title=self.scene().addText('尚未选择图像',QFont('Microsoft YaHei UI',13))
        title.setDefaultTextColor(QColor('#263548'));title.setPos(28,35)
        text = self.scene().addText(empty_text.replace('，','\n',1), QFont("Microsoft YaHei UI", 10))
        text.setTextWidth(264);text.setPos(28,80)
        text.setDefaultTextColor(QColor("#58687b"))
        self.scene().setSceneRect(QRectF(-8,-8,336,196))
        self.fit_image()

    def set_image(self, image, points=None):
        self.image = image
        self.setBackgroundBrush(QColor('#202b30'))
        self.scene().clear()
        self.selection_item = None
        self.guides = {}
        self.overlay = None
        self.points, self.draft, self.anchor = [], [], None
        self.pan,self.pan_origin,self.pan_dragged = None,None,False
        self.scene().addPixmap(pixmap(image))
        self.scene().setSceneRect(QRectF(0, 0, image.width, image.height))
        if points:
            self.points = [tuple(p) for p in points]
            self._draw(self.points, True)
        self.fit_image()

    def fit_image(self):
        if self.image:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.centerOn(self.sceneRect().center())
            self.auto_fit = True
            self.zoom_changed.emit(f"{self.transform().m11()*100:.0f}%")
        else:
            self.resetTransform()
            scale=min(1.,max(.4,(self.viewport().width()-24)/336),max(.4,(self.viewport().height()-24)/196))
            self.scale(scale,scale)
            self.centerOn(self.sceneRect().center())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_image()
            QTimer.singleShot(0, self._refit_after_layout)

    def _refit_after_layout(self):
        if self.auto_fit:
            self.fit_image()

    def set_mode(self, mode):
        self.mode, self.draft, self.anchor = mode, [], None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if mode == "view" else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if mode == "view" else Qt.CursorShape.CrossCursor)

    def set_selection(self, points):
        self.clear_selection(emit=False)
        self.points = [tuple(p) for p in points]
        if self.points:
            self._draw(self.points, True)

    def set_guide(self, name, box=None, color="#72b8ed", dashed=True):
        old = self.guides.pop(name, None)
        if old is not None:
            self.scene().removeItem(old)
        if box is None or self.image is None:
            return
        l,t,r,b = box
        path = QPainterPath()
        path.addRect(QRectF(l,t,r-l,b-t))
        item = QGraphicsPathItem(path)
        pen = QPen(QColor(color),2)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setZValue(3)
        self.scene().addItem(item)
        self.guides[name] = item

    def clear_selection(self, emit=True):
        self.points, self.draft, self.anchor = [], [], None
        if self.selection_item is not None:
            self.scene().removeItem(self.selection_item)
            self.selection_item = None
        if emit:
            self.selection_changed.emit([])

    def _point(self, pos):
        pt = self.mapToScene(pos)
        return (max(0, min(self.image.width, pt.x())), max(0, min(self.image.height, pt.y())))

    def _draw(self, points, closed=False):
        if self.selection_item is not None:
            self.scene().removeItem(self.selection_item)
        path = QPainterPath()
        if points:
            path.moveTo(QPointF(*points[0]))
            for pt in points[1:]:
                path.lineTo(QPointF(*pt))
            if closed:
                path.closeSubpath()
        self.selection_item = QGraphicsPathItem(path)
        pen = QPen(QColor(self.selection_color), 2)
        pen.setCosmetic(True)
        self.selection_item.setPen(pen)
        brush = QColor(self.selection_color)
        brush.setAlpha(35)
        self.selection_item.setBrush(brush)
        self.selection_item.setZValue(2)
        self.scene().addItem(self.selection_item)

    def _finish_polygon(self):
        if len(self.draft) >= 3:
            self.points = list(self.draft)
            self.draft = []
            self._draw(self.points, True)
            self.selection_changed.emit(self.points)

    def mousePressEvent(self, event):
        if not self.image:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.RightButton:
            self.pan = event.position().toPoint()
            self.pan_origin = self.pan
            self.pan_dragged = False
            return
        if event.button() == Qt.MouseButton.LeftButton and self.mode in ("rectangle", "polygon", "roi"):
            self.setFocus()
            pt = self._point(event.position().toPoint())
            if self.mode in ("rectangle", "roi"):
                self.anchor = pt
            else:
                self.draft.append(pt)
                self._draw(self.draft)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pan is not None:
            here = event.position().toPoint()
            if not self.pan_dragged:
                if (here-self.pan_origin).manhattanLength() < QApplication.startDragDistance():
                    return
                self.pan_dragged = True
                self.auto_fit = False
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            delta = here-self.pan
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-delta.y())
            self.pan = here
            return
        if self.image and self.anchor is not None:
            x, y = self.anchor
            xx, yy = self._point(event.position().toPoint())
            self._draw([(x, y), (xx, y), (xx, yy), (x, yy)], True)
            return
        if self.image and self.draft:
            self._draw(self.draft+[self._point(event.position().toPoint())])
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            click = (self.pan_origin is not None and not self.pan_dragged and
                     (event.position().toPoint()-self.pan_origin).manhattanLength() < QApplication.startDragDistance())
            self.pan,self.pan_origin,self.pan_dragged = None,None,False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if self.mode == 'view' else Qt.CursorShape.CrossCursor)
            if click and self.mode == 'polygon':
                self._finish_polygon()
            return
        if self.image and self.anchor is not None and event.button() == Qt.MouseButton.LeftButton:
            x, y = self.anchor
            xx, yy = self._point(event.position().toPoint())
            self.anchor = None
            if abs(x-xx) >= 3 and abs(y-yy) >= 3:
                x1, x2 = sorted((x, xx))
                y1, y2 = sorted((y, yy))
                self.points = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                self._draw(self.points, True)
                self.selection_changed.emit(self.points)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.mode == "polygon":
            self._finish_polygon()
        elif event.key() == Qt.Key.Key_Escape:
            self.clear_selection()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        event.accept()  # Right-button canvas gestures are handled above.

    def wheelEvent(self, event):
        if self.image:
            factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
            zoom = self.transform().m11()*factor
            if 0.02 <= zoom <= 8:
                self.scale(factor, factor)
                self.auto_fit = False
                self.zoom_changed.emit(f"{zoom*100:.0f}%")
            event.accept()

    def set_mask_overlay(self, mask, visible):
        if self.overlay is not None:
            self.scene().removeItem(self.overlay)
            self.overlay = None
        if visible and mask is not None:
            tinted = Image.new("RGBA", mask.size, (255, 120, 64, 0))
            tinted.putalpha(mask.point(lambda n: int(n*0.42)))
            self.overlay = self.scene().addPixmap(pixmap(tinted))
            self.overlay.setZValue(1)


class Worker(QThread):
    progress = Signal(int, int, str)
    result = Signal(object)
    failed = Signal(object)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self))
        except Exception as exc:
            self.failed.emit(exc)


from theme import THEME as STYLE


class MainWindow(QMainWindow):
    def __init__(self, embedded=False):
        super().__init__()
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("VT 缺陷合成工具")
        self.resize(1360, 900)
        if not embedded:
            self.setMinimumSize(1060, 720)
        self.ok_paths = []
        self.ng_path = ""
        self.ng_image = None
        self.asset = None
        self.worker = None
        self.preview_result = None
        self.preview_signature = None
        self.last_run = None
        self.roi = (0.0, 0.0, 1.0, 1.0)
        self.roi_origin = "全图"
        self.rois=[]
        self.selected_roi_index=-1
        self.ng_selection_kind = "asset"
        self.ng_documents = []
        self.current_ng_index = -1
        self.seed_offset = 0
        self._build()
        for field in self.findChildren(QAbstractSpinBox):
            field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setStyleSheet(STYLE)
        if embedded:
            self.statusBar().hide()
        icon_path = Path(__file__).with_name("app.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        if self.embedded:
            outer.setContentsMargins(12, 6, 12, 8)
        else:
            outer.setContentsMargins(22, 18, 22, 14)
        outer.setSpacing(12)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("VT 缺陷合成工具")
        title.setObjectName("Title")
        titles.addWidget(title)
        sub = QLabel("现场素材迁移 · 原尺寸灰度 / RGB BMP · 合成位置可追溯")
        sub.setObjectName("Subtle")
        titles.addWidget(sub)
        if not self.embedded:
            header.addLayout(titles)
        else:
            title.hide()
            sub.hide()
            header.addWidget(QLabel("素材圈选与合成参数"))
        header.addStretch()
        self.save_btn = self.button("保存配方", self.save_current_recipe)
        self.load_btn = self.button("加载配方", self.load_current_recipe)
        header.addWidget(self.save_btn)
        header.addWidget(self.load_btn)
        header.addWidget(self.button("使用说明", self.help))
        outer.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(330)
        scroll.setMaximumWidth(440)
        self.controls = QWidget()
        left = QVBoxLayout(self.controls)
        left.setContentsMargins(0, 0, 14, 0)
        left.setSpacing(8)
        scroll.setWidget(self.controls)
        splitter.addWidget(scroll)

        group = QGroupBox("1  导入 OK 底图")
        g = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(self.button("选择图片", self.open_ok))
        row.addWidget(self.button("选择文件夹", self.open_ok_folder))
        row.addWidget(self.button("移除", self.remove_ok))
        g.addLayout(row)
        self.ok_list = AdaptiveImageList()
        self.ok_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.ok_list.currentRowChanged.connect(self.show_ok)
        g.addWidget(self.ok_list)
        self.ok_info = QLabel("导入同款产品的真实 OK 图，支持多选。")
        self.ok_info.setObjectName("Subtle")
        self.ok_info.setWordWrap(True)
        g.addWidget(self.ok_info)
        left.addWidget(group)

        group = QGroupBox("2  NG 素材池 · 逐张圈选")
        g = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(self.button("选择图片",self.open_ng))
        row.addWidget(self.button("选择文件夹",self.open_ng_folder))
        row.addWidget(self.button("移除",self.remove_ng))
        g.addLayout(row)
        self.ng_list = AdaptiveImageList()
        self.ng_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.ng_list.currentRowChanged.connect(self.show_ng)
        g.addWidget(self.ng_list)
        self.pool_info = QLabel("仅导入同款、位置对应的NG。未圈选素材不参与生成。")
        self.pool_info.setObjectName("Subtle")
        self.pool_info.setWordWrap(True)
        g.addWidget(self.pool_info)
        self.ng_info = QLabel("先打开 NG 图，再用矩形或多边形圈出缺陷。")
        self.ng_info.setObjectName("Subtle")
        self.ng_info.setWordWrap(True)
        g.addWidget(self.ng_info)
        self.asset_thumb = QLabel("圈选后显示缺陷素材")
        self.asset_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.asset_thumb.setFixedHeight(55)
        self.asset_thumb.setStyleSheet("background: #e5ebf2; border-radius: 5px; color: #53647a;")
        g.addWidget(self.asset_thumb)
        left.addWidget(group)

        group = QGroupBox("3  缺陷生成范围")
        g = QVBoxLayout(group)
        self.ng_roi_btn = self.button("在 NG 上框生成范围", self.begin_ng_roi)
        g.addWidget(self.ng_roi_btn)
        row = QHBoxLayout()
        self.ok_roi_btn = self.button("在 OK 上追加", self.begin_ok_roi)
        self.reset_roi_btn = self.button("恢复全图", self.reset_roi)
        row.addWidget(self.ok_roi_btn)
        row.addWidget(self.reset_roi_btn)
        g.addLayout(row)
        self.roi_list=QListWidget()
        self.roi_list.setMinimumHeight(48);self.roi_list.setMaximumHeight(94)
        self.roi_list.currentRowChanged.connect(self.select_roi)
        g.addWidget(self.roi_list)
        roi_actions=QHBoxLayout()
        roi_actions.addWidget(self.button('删除选中范围',self.remove_roi))
        roi_actions.addWidget(self.button('撤销上一框',self.undo_roi))
        g.addLayout(roi_actions)
        self.roi_info = QLabel("当前：全图。请在 NG 上框出相同材料允许出现缺陷的区域。")
        self.roi_info.setObjectName("Subtle")
        self.roi_info.setWordWrap(True)
        g.addWidget(self.roi_info)
        self.source_guide_check = QCheckBox("显示原 NG 缺陷位置参考")
        self.source_guide_check.setChecked(True)
        self.source_guide_check.toggled.connect(self.refresh_spatial_guides)
        g.addWidget(self.source_guide_check)
        legend = QLabel("绿色框：允许范围；蓝色虚框：原缺陷位置。")
        legend.setWordWrap(True)
        legend.setObjectName("Subtle")
        g.addWidget(legend)
        left.addWidget(group)

        group = QGroupBox("4  调整合成参数")
        form = QFormLayout(group)
        form.setVerticalSpacing(9)
        self.method = QComboBox()
        self.method.addItem("暗缺陷迁移 · 保留底图纹理", "darken")
        self.method.addItem("纹理粘贴 · 复制素材外观", "texture")
        self.method.setMinimumWidth(0)
        self.method.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.method.setMinimumContentsLength(12)
        self.method.setToolTip("暗缺陷迁移：灰度按亮度、RGB 按各通道背景估计衰减，只加暗；纹理粘贴：保留素材颜色并按强度混合。")
        form.addRow("合成方式", self.method)
        self.class_name = QLineEdit("脏污")
        self.class_name.setMaxLength(80)
        self.class_name.setToolTip("本素材池统一使用此缺陷类别；不同产品或不同缺陷类别请分池生成。")
        form.addRow("缺陷类别", self.class_name)
        self.scale_min = self.decimal(0.02, 5, 0.65, 0.05)
        self.scale_max = self.decimal(0.02, 5, 1.10, 0.05)
        form.addRow("尺寸倍率", self.range_row(self.scale_min, self.scale_max))
        self.strength_min = self.decimal(0.01, 1, 0.55, 0.05)
        self.strength_max = self.decimal(0.01, 1, 0.95, 0.05)
        form.addRow("混合强度", self.range_row(self.strength_min, self.strength_max))
        self.rotation = self.decimal(0, 180, 12, 1)
        self.rotation.setSuffix(" °")
        form.addRow("旋转 ±", self.rotation)
        self.feather = self.decimal(0, 100, 6, 1)
        self.feather.setSuffix(" px")
        form.addRow("边缘羽化", self.feather)
        self.reference = QSpinBox()
        self.reference.setRange(1,255)
        self.reference.setValue(190)
        self.auto_reference=QCheckBox('自动')
        self.auto_reference.setChecked(True)
        self.reference.setEnabled(False)
        self.reference.setToolTip('手动背景参考值1～255；自动模式按NG周边估计，RGB分别估计各通道。')
        reference_row=QWidget();reference_layout=QHBoxLayout(reference_row)
        reference_layout.setContentsMargins(0,0,0,0)
        reference_layout.addWidget(self.reference,1)
        automatic_half=QWidget();automatic_layout=QHBoxLayout(automatic_half)
        automatic_layout.setContentsMargins(0,0,0,0)
        automatic_layout.addWidget(self.auto_reference);automatic_layout.addStretch()
        reference_layout.addWidget(automatic_half,1)
        form.addRow("素材背景参考值",reference_row)
        self.auto_reference.toggled.connect(lambda checked:self.reference.setEnabled(not checked))
        self.auto_reference.toggled.connect(self.invalidate_preview)
        self.samples = QSpinBox()
        self.samples.setRange(1, 1000)
        self.samples.setValue(5)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(20261026)
        form.addRow("随机种子", self.seed)
        hint = QLabel("尺寸倍率相对缺陷素材。生成范围在 NG 上另框，可在 OK 上微调，按比例应用到全部底图。")
        hint.setWordWrap(True)
        hint.setObjectName("Subtle")
        form.addRow(hint)
        left.addWidget(group)
        left.addStretch()

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(8, 0, 0, 0)
        right.setSpacing(10)
        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)
        self.ok_canvas = Canvas("导入 OK 底图，在此设置缺陷允许出现的区域。")
        self.ng_canvas = Canvas("打开 NG 图，在此圈选要迁移的真实缺陷。")
        self.preview_canvas = Canvas("完成底图与缺陷圈选后，点击「生成预览」。")
        if self.embedded:
            for canvas in (self.ok_canvas, self.ng_canvas, self.preview_canvas):
                canvas.setMinimumHeight(160)
        self.ok_canvas.selection_changed.connect(self.set_roi)
        self.ng_canvas.selection_changed.connect(self.on_ng_selection)
        self.ng_canvas.selection_color = "#72b8ed"
        self.ng_canvas.set_mode("rectangle")
        self.ok_canvas.set_mode("rectangle")
        self._canvas_tab("OK 底图 / 允许区域", self.ok_canvas, "rectangle",
                         "绿色框内允许生成整个缺陷；蓝色虚框是原 NG 缺陷位置参考。")
        self._canvas_tab("NG 图 / 缺陷圈选", self.ng_canvas, "polygon",
                         "取缺陷与范围分别框选。点击「生成范围」后拖动可连续追加；右键拖动平移。")
        self._canvas_tab("合成预览", self.preview_canvas, "view",
                         "滚轮缩放，右键按住拖动平移。橙色覆盖层表示实际发生像素变化的区域。")
        self.tabs.currentChanged.connect(lambda _: self._update_message_for_tab())

        preview_row = QHBoxLayout()
        self.preview_btn = self.button("生成预览", self.preview)
        self.next_btn = self.button("换一张预览", lambda: self.preview(True))
        self.overlay_check = QCheckBox("显示修改区域",self)
        self.overlay_check.toggled.connect(self.refresh_overlay)
        self.overlay_check.toggled.connect(lambda checked:self.preview_mode_picker.setCurrentIndex(1 if checked else 0))
        self.overlay_check.setVisible(False)
        preview_row.addWidget(self.preview_btn)
        preview_row.addWidget(self.next_btn)
        preview_row.addStretch()
        self.preview_info = QLabel("尚未生成预览")
        self.preview_info.setObjectName("Subtle")
        preview_row.addWidget(self.preview_info)
        right.addLayout(preview_row)

        export_box = QGroupBox("5  批量导出")
        export_layout = QVBoxLayout(export_box)
        quantity_row=QHBoxLayout()
        quantity_row.addWidget(QLabel('生成数量'))
        self.quantity_mode=QComboBox()
        self.quantity_mode.addItem('每张 OK 生成','per_ok')
        self.quantity_mode.addItem('本批生成总数','total')
        quantity_row.addWidget(self.quantity_mode)
        self.samples.setSuffix(' 张')
        quantity_row.addWidget(self.samples)
        self.batch_total=QSpinBox()
        self.batch_total.setRange(1,MAX_TOTAL_SAMPLES)
        self.batch_total.setValue(100)
        self.batch_total.setSuffix(' 张')
        quantity_row.addWidget(self.batch_total)
        self.quantity_info=QLabel()
        self.quantity_info.setObjectName('Subtle')
        quantity_row.addStretch()
        quantity_row.addWidget(self.quantity_info)
        self.vt_xml_check=QCheckBox('VT XML')
        self.vt_xml_check.setChecked(True)
        self.vt_xml_check.setToolTip('VisionTrain 2.2.x 缺陷检测的原生矩形XML，与BMP同名；框为实际改动像素外接框，像素掩膜另存PNG。')
        quantity_row.addWidget(self.vt_xml_check)
        export_layout.addLayout(quantity_row)
        self.quantity_mode.currentIndexChanged.connect(self.refresh_quantity_plan)
        self.samples.valueChanged.connect(self.refresh_quantity_plan)
        self.batch_total.valueChanged.connect(self.refresh_quantity_plan)
        self.refresh_quantity_plan()
        output_row = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("选择输出文件夹，每次生成独立批次")
        output_row.addWidget(self.output_path, 1)
        self.output_btn = self.button("选择文件夹", self.choose_output)
        output_row.addWidget(self.output_btn)
        export_layout.addLayout(output_row)
        action_row = QHBoxLayout()
        self.export_info = QLabel("图像 / VT XML / 掩膜 / JSON")
        self.export_info.setObjectName("Subtle")
        action_row.addWidget(self.export_info, 1)
        self.cancel_btn = self.button("取消生成", self.cancel)
        self.cancel_btn.setEnabled(False)
        self.export_btn = self.button("批量生成", self.export, primary=True)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.export_btn)
        self.open_output_btn = self.button("打开结果", self.open_output)
        self.open_output_btn.setEnabled(False)
        action_row.addWidget(self.open_output_btn)
        export_layout.addLayout(action_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        export_layout.addWidget(self.progress)
        right.addWidget(export_box)
        self.message = QLabel("请导入 OK 底图，选择 NG 素材并圈选缺陷。")
        self.message.setObjectName("Message")
        self.message.setWordWrap(True)
        right.addWidget(self.message)
        splitter.addWidget(right_widget)
        splitter.setSizes([350, 960])
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage(f"v{VERSION}  |  灰度 / RGB  |  VT 缺陷矩形 XML、PNG 掩膜与 JSON")
        for control in (self.scale_min, self.scale_max, self.strength_min, self.strength_max,
                        self.rotation, self.feather, self.reference, self.seed):
            control.valueChanged.connect(self.invalidate_preview)
        self.method.currentIndexChanged.connect(self.invalidate_preview)
        self.class_name.textChanged.connect(self.invalidate_preview)

        for text, shortcut, callback in [("打开 OK 图", "Ctrl+O", self.open_ok),
                ("保存配方", "Ctrl+S", self.save_current_recipe),
                ("生成预览", "Ctrl+P", self.preview)]:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def _canvas_tab(self, name, canvas, modes, hint):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setContentsMargins(10, 8, 10, 4)
        picker=ModeStrip()
        if canvas != self.preview_canvas:
            picker.addItem("矩形素材" if canvas == self.ng_canvas else "生成范围", "rectangle")
            if canvas == self.ng_canvas:
                picker.addItem("多边形素材", "polygon")
                picker.addItem("生成范围", "roi")
            picker.addItem("浏览平移", "view")
            picker.currentIndexChanged.connect(lambda _, c=canvas, p=picker: self.set_canvas_mode(c,p.currentData()))
            if canvas == self.ng_canvas:
                self.ng_mode_picker = picker
            else:
                self.ok_mode_picker = picker
        else:
            self.preview_mode_picker=picker
            picker.addItem('查看图像','view');picker.addItem('改动区域','changes')
            picker.currentIndexChanged.connect(lambda _:self.set_preview_mode(picker.currentData()))
        row.addWidget(picker,1)
        if canvas!=self.preview_canvas:
            row.addWidget(self.button("清除" if canvas == self.ng_canvas else "清空范围", lambda: canvas.clear_selection()))
        row.addStretch()
        zoom = QLabel("适应窗口")
        zoom.setObjectName("Subtle")
        row.addWidget(zoom)
        canvas.zoom_changed.connect(zoom.setText)
        fit=self.button("适应",canvas.fit_image)
        fit.setToolTip('适应窗口显示完整图像')
        row.addWidget(fit)
        layout.addLayout(row)
        layout.addWidget(canvas, 1)
        label = QLabel(hint)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        label.setObjectName("Subtle")
        label.setContentsMargins(10, 5, 10, 8)
        layout.addWidget(label)
        self.tabs.addTab(tab, name)

    @staticmethod
    def button(text, slot, primary=False):
        b = QPushButton(text)
        b.clicked.connect(lambda checked=False: slot())
        if primary:
            b.setObjectName("Primary")
        return b

    @staticmethod
    def decimal(low, high, value, step):
        s = QDoubleSpinBox()
        s.setRange(low, high)
        s.setDecimals(2)
        s.setSingleStep(step)
        s.setValue(value)
        return s

    @staticmethod
    def range_row(first, second):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(first)
        layout.addWidget(QLabel("至"))
        layout.addWidget(second)
        return widget

    def notify(self, text, error=False):
        self.message.setText(text)
        self.message.setProperty("error", error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def refresh_quantity_plan(self, *_):
        total_mode=self.quantity_mode.currentData()=='total'
        self.samples.setVisible(not total_mode)
        self.batch_total.setVisible(total_mode)
        n=len(self.ok_paths)
        total=self.batch_total.value() if total_mode else n*self.samples.value()
        self.quantity_info.setText(f'合计 {total:,} 张')
        self.quantity_info.setToolTip(f'本批使用OK：{min(n,total) if total_mode else n}张；按列表顺序均匀分配。')

    def _update_message_for_tab(self):
        pass  # Tab hints live beside the canvas and do not erase job/error status.

    def add_ok(self, paths):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.ok_paths}
        rejected = []
        for p in paths:
            p = str(Path(p).resolve())
            if os.path.normcase(p) in existing:
                continue
            try:
                load_image(p)
                self.ok_paths.append(p)
                existing.add(os.path.normcase(p))
                self.ok_list.addItem(Path(p).name)
                self.ok_list.item(self.ok_list.count()-1).setToolTip(p)
            except Exception as exc:
                rejected.append(f"{Path(p).name}：{exc}")
        if self.ok_paths:
            self.ok_list.setCurrentRow(self.ok_list.count()-1)
        self.refresh_quantity_plan()
        self.notify("；".join(rejected[:3]) if rejected else f"已导入 {len(self.ok_paths)} 张 OK 底图。请打开 NG 图并圈选缺陷。", bool(rejected))

    def open_ok(self):
        if self.is_busy():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择真实 OK 图（灰度 / RGB）", "", IMAGE_FILTER)
        if paths:
            self.add_ok(paths)
            self.tabs.setCurrentIndex(0)

    def open_ok_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择 OK 图片文件夹（仅当前层）")
        if folder:
            paths = sorted(str(p) for p in Path(folder).iterdir() if p.suffix.lower() in (".bmp", ".png", ".tif", ".tiff"))
            if not paths:
                self.notify("文件夹当前层未找到 BMP、PNG 或 TIFF 图像。", True)
            else:
                self.add_ok(paths)
                self.tabs.setCurrentIndex(0)

    def remove_ok(self):
        for idx in sorted((self.ok_list.row(item) for item in self.ok_list.selectedItems()), reverse=True):
            self.ok_list.takeItem(idx)
            self.ok_paths.pop(idx)
        if self.ok_paths:
            self.ok_list.setCurrentRow(0)
        else:
            self.ok_canvas.set_empty("导入 OK 底图，在此查看映射后的生成范围。")
            self.ok_info.setText("请导入真实 OK 底图。")
        self.refresh_spatial_guides()
        self.refresh_quantity_plan()
        self.invalidate_preview()

    def show_ok(self, row):
        if not 0 <= row < len(self.ok_paths):
            return
        try:
            im = load_image(self.ok_paths[row])
            pts = None
            if tuple(self.roi) != (0, 0, 1, 1):
                l, t, r, b = self.roi
                pts = [(l*im.width, t*im.height), (r*im.width, t*im.height), (r*im.width, b*im.height), (l*im.width, b*im.height)]
            self.ok_canvas.set_image(im, pts)
            mode_name = "24 位 RGB" if im.mode == "RGB" else "8 位灰度"
            self.ok_info.setText(f"{len(self.ok_paths)} 张底图 · 当前 {im.width} × {im.height} · {mode_name}")
            self.refresh_spatial_guides()
            self.invalidate_preview()
        except Exception as exc:
            self.notify(f"底图读取失败：{exc}", True)

    def open_ng(self):
        if self.is_busy():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "多选同款 NG 图，逐张圈选缺陷与范围", "", IMAGE_FILTER)
        if paths:
            self.add_ng(paths)

    def load_ng(self, path):
        self.add_ng([path])

    def open_ng_folder(self):
        if self.is_busy():
            return
        folder=QFileDialog.getExistingDirectory(self,"选择同款NG图片文件夹（仅当前层）")
        if folder:
            paths=sorted(str(p) for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in ('.bmp','.png','.tif','.tiff'))
            self.add_ng(paths)

    def _stash_ng(self):
        if 0<=self.current_ng_index<len(self.ng_documents):
            doc=self.ng_documents[self.current_ng_index]
            doc.asset,doc.roi,doc.roi_origin=self.asset,tuple(self.roi),self.roi_origin
            doc.rois=tuple(tuple(r) for r in self.rois)
        self._update_pool_labels()

    def _update_pool_labels(self):
        for index,doc in enumerate(self.ng_documents):
            item=self.ng_list.item(index)
            if item is not None:
                status='已圈选 '+doc.asset.pixels.mode if doc.asset is not None else '待圈选'
                item.setText(f'[{status}] {Path(doc.path).name}')
                item.setToolTip(f'{doc.path}\n生成范围：{doc.roi}')
        ready=sum(doc.asset is not None for doc in self.ng_documents)
        self.pool_info.setText(f'同款素材池：{ready}/{len(self.ng_documents)} 张已圈选；未圈选不参与。每张单独保留生成范围。')

    def add_ng(self, paths):
        if self.is_busy():
            return
        self._stash_ng()
        existing={os.path.normcase(doc.path):i for i,doc in enumerate(self.ng_documents)}
        rejected=[];last=None
        for path in paths:
            path=str(Path(path).resolve())
            key=os.path.normcase(path)
            if key in existing:
                last=existing[key];continue
            try:
                if len(self.ng_documents)>=MAX_POOL_ENTRIES:
                    raise SynthesisError(f'每池最多{MAX_POOL_ENTRIES}张NG，请分池处理。')
                load_image(path)
                last=len(self.ng_documents)
                self.ng_documents.append(NGDocument(path))
                self.ng_list.addItem(Path(path).name)
                existing[key]=last
            except Exception as exc:
                rejected.append(f'{Path(path).name}：{exc}')
        self._update_pool_labels()
        if last is not None:
            self.ng_list.setCurrentRow(last)
            self.tabs.setCurrentIndex(1)
        if rejected:
            self.notify('；'.join(rejected[:3]),True)
        elif last is not None:
            self.notify('NG已加入素材池。逐张点击列表圈选缺陷，再另框各自的生成范围。')

    def show_ng(self, row):
        if not 0<=row<len(self.ng_documents):
            return
        self._stash_ng()
        self.current_ng_index=row
        doc=self.ng_documents[row]
        self.asset,self.roi,self.roi_origin=doc.asset,tuple(doc.roi),doc.roi_origin
        self.rois=[tuple(r) for r in doc.rois]
        self.selected_roi_index=-1
        self.ng_path,self.ng_image=doc.path,None
        warning=''
        try:
            im=load_image(doc.path)
            if doc.asset is not None and (list(im.size)!=doc.asset.provenance.get('source_size') or im.mode!=doc.asset.pixels.mode):
                raise SynthesisError('原NG尺寸或颜色模式已改变，使用已保存素材；需重新圈选时请移除并重新导入。')
            self.ng_image=im
            self.ng_canvas.set_image(im)
        except Exception as exc:
            warning=str(exc)
            if doc.asset is not None:
                self.ng_image=doc.asset.pixels.copy()
                self.ng_path=f'embedded_recipe:{doc.entry_id}'
                self.ng_canvas.set_image(self.ng_image)
            else:
                self.ng_canvas.set_empty('当前NG不可读取，请移除后重新导入。')
        self.ng_mode_picker.setCurrentIndex(self.ng_mode_picker.findData('rectangle'))
        self.set_canvas_mode(self.ng_canvas,'rectangle')
        if self.asset is not None:
            self.display_asset()
        else:
            self.asset_thumb.clear()
            self.asset_thumb.setText('在右侧NG图上圈选缺陷')
            self.ng_info.setText(Path(doc.path).name+'\n等待圈选缺陷素材')
        self.invalidate_preview();self.refresh_spatial_guides()
        if warning:
            self.notify('当前NG原图不可用：'+warning,True)

    def remove_ng(self):
        if self.is_busy():
            return
        self._stash_ng()
        rows=sorted((self.ng_list.row(item) for item in self.ng_list.selectedItems()),reverse=True)
        self.ng_list.blockSignals(True)
        for row in rows:
            self.ng_list.takeItem(row);self.ng_documents.pop(row)
        self.current_ng_index=-1
        self.ng_list.blockSignals(False)
        if self.ng_documents:
            self.ng_list.setCurrentRow(0)
            self.show_ng(0)
        else:
            self.asset,self.ng_image,self.ng_path=None,None,''
            self.roi,self.roi_origin=(0.,0.,1.,1.),'全图'
            self.rois=[]
            self.ng_canvas.set_empty('导入同款NG图，逐张圈选缺陷。')
            self.asset_thumb.clear();self.asset_thumb.setText('尚无NG素材')
            self.ng_info.setText('请导入NG图。')
            self.preview_canvas.set_empty('导入并圈选NG素材后，再生成预览。')
            self.preview_result=None
            self.refresh_spatial_guides()
        self._update_pool_labels();self.invalidate_preview()

    def ready_entries(self):
        self._stash_ng()
        return [PoolEntry(d.entry_id,Path(d.path).name,d.asset,tuple(d.roi),tuple(d.rois))
                for d in self.ng_documents if d.asset is not None]

    def set_asset(self, points):
        if not points:
            self.asset = None
            self.asset_thumb.clear()
            self.asset_thumb.setText("选区已清除，请重新圈选")
            self.ng_info.setText("尚未圈选缺陷素材")
            self._stash_ng()
            self.refresh_spatial_guides()
            self.invalidate_preview()
            return
        if self.ng_image is None:
            return
        if self.ng_path.startswith('embedded_recipe:'):
            self.notify('当前仅有配方内素材裁图。重新圈选请打开原NG；已有素材及范围仍可用于生成。',True)
            return
        try:
            asset = extract_asset(self.ng_image, points, self.ng_path)
            self.asset = asset
            self._stash_ng()
            self.display_asset()
            self.refresh_spatial_guides()
            self.invalidate_preview()
            self.notify("缺陷素材已提取。点击「在 NG 上框生成范围」，另框相似材料的合理区域。")
        except Exception as exc:
            self.asset = None
            self._stash_ng()
            self.notify(f"圈选无效：{exc}", True)

    def display_asset(self):
        asset = self.asset
        tile = Image.new(asset.pixels.mode, asset.pixels.size, (225, 225, 225) if asset.pixels.mode == "RGB" else 225)
        tile.paste(asset.pixels, mask=asset.mask)
        pm = pixmap(tile)
        self.asset_thumb.setPixmap(pm.scaled(max(80, self.asset_thumb.width()-12), max(30,self.asset_thumb.height()-8), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        reference = ("RGB " + "/".join(f"{v:.0f}" for v in asset.reference_rgb)
                     if asset.reference_rgb is not None else f"{asset.reference_gray:.0f} / 255")
        self.ng_info.setText(f"素材 {asset.pixels.width} × {asset.pixels.height} px · {asset.pixels.mode}\n周边背景估计：{reference}")

    def _has_full_ng(self):
        return self.ng_image is not None and not self.ng_path.startswith("embedded_recipe:")

    @staticmethod
    def _roi_box(roi, size):
        w,h = size
        return (roi[0]*w,roi[1]*h,roi[2]*w,roi[3]*h)

    @classmethod
    def _roi_points(cls, roi, size):
        l,t,r,b = cls._roi_box(roi,size)
        return [(l,t),(r,t),(r,b),(l,b)]

    @staticmethod
    def _source_box(provenance, target_size):
        try:
            w,h = [float(v) for v in provenance['source_size']]
            l,t,r,b = [float(v) for v in provenance['source_bbox_xyxy']]
            if (not all(math.isfinite(v) for v in (w,h,l,t,r,b)) or
                    w <= 0 or h <= 0 or not 0 <= l < r <= w or not 0 <= t < b <= h):
                return None
            tw,th = target_size
            return (l/w*tw,t/h*th,r/w*tw,b/h*th)
        except (KeyError, TypeError, ValueError):
            return None

    def set_canvas_mode(self, canvas, mode):
        if canvas == self.ng_canvas and mode == 'roi' and not self._has_full_ng():
            self.ng_mode_picker.blockSignals(True)
            self.ng_mode_picker.setCurrentIndex(self.ng_mode_picker.findData('view'))
            self.ng_mode_picker.blockSignals(False)
            canvas.set_mode('view')
            self.notify("请先打开完整 NG 图，再框生成范围；配方内的素材裁图不能代替原图坐标。",True)
            return
        canvas.set_mode(mode)
        if canvas == self.ng_canvas:
            if mode in ('rectangle','polygon','roi'):
                self.ng_selection_kind = 'roi' if mode == 'roi' else 'asset'
            canvas.selection_color = '#39dbc4' if self.ng_selection_kind == 'roi' else '#72b8ed'
            if mode == 'roi':
                canvas.set_selection([] if tuple(self.roi)==(0,0,1,1) else self._roi_points(self.roi,canvas.image.size))
            elif mode in ('rectangle','polygon'):
                points = (self.asset.provenance.get('source_polygon_xy',[])
                          if self.asset is not None and self._has_full_ng() else [])
                canvas.set_selection(points)

    def begin_ng_roi(self):
        if self.is_busy():
            return
        if not self._has_full_ng():
            self.notify("请先打开完整 NG 图，再框生成范围。",True)
            return
        self.tabs.setCurrentIndex(1)
        self.ng_mode_picker.setCurrentIndex(self.ng_mode_picker.findData('roi'))
        self.set_canvas_mode(self.ng_canvas,'roi')
        self.notify("在 NG 上另框允许生成的材料区域；缺陷素材不会被重新提取，绿色范围会映射到 OK。")

    def begin_ok_roi(self):
        if self.is_busy():
            return
        if self.ok_canvas.image is None:
            self.notify("请先导入 OK 底图。",True)
            return
        self.tabs.setCurrentIndex(0)
        self.ok_mode_picker.setCurrentIndex(self.ok_mode_picker.findData('rectangle'))
        self.ok_canvas.set_mode('rectangle')
        self.notify("在 OK 上拖动绿色矩形调整生成范围，蓝色虚框仅作原缺陷位置参考。")

    def on_ng_selection(self, points):
        if self.ng_selection_kind == 'roi':
            if not points:
                self.reset_roi()
            elif self._has_full_ng():
                self._set_roi_from_points(points,self.ng_image.size,"NG 框选")
        else:
            self.set_asset(points)

    def _set_roi_from_points(self, points, size, origin):
        w,h = size
        xs,ys = [p[0] for p in points],[p[1] for p in points]
        roi = (min(xs)/w,min(ys)/h,max(xs)/w,max(ys)/h)
        try:
            Settings(roi=roi).validate()
        except SynthesisError as exc:
            self.notify(str(exc),True)
            return
        regions=self.roi_regions()
        if len(regions)>=MAX_ROI_REGIONS:
            self.notify('每份素材最多64个范围，请先删除不需要的框。',True);return
        if roi not in regions:
            regions.append(roi)
        self.rois=regions
        self.selected_roi_index=len(regions)-1
        self.roi,self.roi_origin = regions[0],origin
        self._stash_ng()
        self.refresh_spatial_guides()
        self.invalidate_preview()
        self.notify(f"已保存{len(regions)}个允许范围。可继续拖动添加；生成时选择一个可放入完整缺陷的框。")

    def set_roi(self, points):
        if not points:
            self.reset_roi()
        elif self.ok_canvas.image is not None:
            self._set_roi_from_points(points,self.ok_canvas.image.size,"OK 微调")

    def reset_roi(self):
        if self.is_busy():
            return
        self.roi,self.roi_origin = (0.,0.,1.,1.),"全图"
        self.rois=[]
        self.selected_roi_index=-1
        self._stash_ng()
        if self.ng_selection_kind == 'roi':
            self.ng_canvas.set_selection([])
        self.refresh_spatial_guides()
        self.invalidate_preview()
        self.notify("允许范围已恢复为全图，缺陷素材保持不变。")

    def roi_regions(self):
        return list(self.rois) if self.rois else ([] if tuple(self.roi)==(0,0,1,1) else [tuple(self.roi)])

    def select_roi(self,index):
        self.selected_roi_index=index
        regions=self.roi_regions()
        if not 0<=index<len(regions):
            return
        for canvas in (self.ok_canvas,self.ng_canvas):
            if canvas.image is not None and (canvas==self.ok_canvas or (self.ng_selection_kind=='roi' and self._has_full_ng())):
                canvas.set_selection(self._roi_points(regions[index],canvas.image.size))

    def remove_roi(self):
        if self.is_busy():
            return
        regions=self.roi_regions();index=self.roi_list.currentRow()
        if not 0<=index<len(regions):
            return
        regions.pop(index);self._replace_regions(regions)

    def undo_roi(self):
        if self.is_busy():
            return
        regions=self.roi_regions()
        if regions:
            regions.pop();self._replace_regions(regions)

    def _replace_regions(self,regions):
        self.rois=regions
        self.roi=regions[0] if regions else (0.,0.,1.,1.)
        self.roi_origin='多框范围' if regions else '全图'
        self._stash_ng();self.refresh_spatial_guides();self.invalidate_preview()

    def refresh_spatial_guides(self, *_):
        regions=self.roi_regions()
        full = not regions
        ok,ng = self.ok_canvas,self.ng_canvas
        for canvas in (ok,ng):
            for key in list(canvas.guides):
                if key=='roi' or key.startswith('roi-'):
                    canvas.set_guide(key)
        if ok.image is not None:
            ok.set_selection([] if full else self._roi_points(regions[-1],ok.image.size))
            for index,region in enumerate(regions):
                ok.set_guide(f'roi-{index}',self._roi_box(region,ok.image.size),'#39dbc4',False)
        if ng.image is not None:
            ng.set_guide('roi',None if full or not self._has_full_ng() else self._roi_box(self.roi,ng.image.size), '#39dbc4',False)
            if self._has_full_ng():
                for index,region in enumerate(regions):
                    ng.set_guide(f'roi-{index}',self._roi_box(region,ng.image.size),'#39dbc4',False)
            if self.ng_selection_kind == 'roi' and self._has_full_ng():
                ng.set_selection([] if full else self._roi_points(regions[-1],ng.image.size))
        provenance = self.asset.provenance if self.asset is not None and self.source_guide_check.isChecked() else {}
        for canvas in (ok,ng):
            box = self._source_box(provenance,canvas.image.size) if canvas.image is not None else None
            if canvas == ng and not self._has_full_ng():
                box = None
            canvas.set_guide('source',box)
        if self.preview_result is not None and self.preview_canvas.image is not None:
            record = self.preview_result[2]
            source = record.get('source_defect',{}) if self.source_guide_check.isChecked() else {}
            self.preview_canvas.set_guide('source',self._source_box(source,self.preview_canvas.image.size))
        text = f"当前：{self.roi_origin}"
        self.roi_list.blockSignals(True)
        self.roi_list.clear()
        for index,region in enumerate(regions):
            coords=self._roi_box(region,ok.image.size) if ok.image is not None else [v*100 for v in region]
            unit='px' if ok.image is not None else '%'
            self.roi_list.addItem(f'范围 {index+1}：'+', '.join(f'{v:.0f}' for v in coords)+' '+unit)
        self.roi_list.blockSignals(False)
        if regions:
            self.roi_list.setCurrentRow(min(max(0,self.selected_roi_index),len(regions)-1))
            text+=f' · {len(regions)}个框'
        if full:
            text += " · 全图"
        elif len(regions)>1:
            text+='\n各框已映射到OK；每次随机选择一个可用框。'
        elif ok.image is not None:
            l,t,r,b = self._roi_box(self.roi,ok.image.size)
            text += f"\nOK 范围：({l:.0f}, {t:.0f}) → ({r:.0f}, {b:.0f}) px"
        else:
            text += " · 已记录比例，导入 OK 后显示映射范围"
        self.roi_info.setText(text.replace('当前：','当前NG：',1))

    def settings(self):
        s = Settings(mode=self.method.currentData(), scale_min=self.scale_min.value(), scale_max=self.scale_max.value(),
            strength_min=self.strength_min.value(), strength_max=self.strength_max.value(),
            rotation=self.rotation.value(), feather=self.feather.value(), reference_gray=0 if self.auto_reference.isChecked() else self.reference.value(),
            samples_per_ok=self.samples.value(), seed=self.seed.value(), class_name=self.class_name.text(), roi=self.roi,
            total_samples=self.batch_total.value() if self.quantity_mode.currentData()=='total' else 0,rois=tuple(self.rois),
            export_vt_xml=self.vt_xml_check.isChecked())
        s.validate()
        return s

    def invalidate_preview(self, *_):
        self.preview_signature = None
        self.preview_info.setText("点击生成，预览当前设置")

    def is_busy(self):
        return self.worker is not None

    def _busy(self, busy, batch=False):
        self.controls.setEnabled(not busy)
        self.save_btn.setEnabled(not busy)
        self.load_btn.setEnabled(not busy)
        self.preview_btn.setEnabled(not busy)
        self.next_btn.setEnabled(not busy)
        self.export_btn.setEnabled(not busy)
        self.output_btn.setEnabled(not busy)
        self.output_path.setEnabled(not busy)
        self.quantity_mode.setEnabled(not busy)
        self.samples.setEnabled(not busy)
        self.batch_total.setEnabled(not busy)
        self.vt_xml_check.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy and batch)

    def _start(self, operation, on_result, batch=False):
        self._busy(True, batch)
        self.worker = Worker(operation, self)
        self.worker.result.connect(on_result)
        self.worker.failed.connect(self.on_failure)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _finished(self):
        worker = self.worker
        self.worker = None
        self._busy(False)
        self.open_output_btn.setEnabled(self.last_run is not None)
        if worker:
            worker.deleteLater()

    def on_failure(self, error):
        if getattr(error, "run_dir", None):
            self.last_run = error.run_dir
            self.export_info.setText(f"生成失败 · 已完成 {error.completed} / {error.total} 张")
        else:
            self.export_info.setText("处理未完成，请查看下方提示")
        self.notify(str(error), True)

    def preview(self, next_sample=False):
        if self.is_busy():
            return
        try:
            entries=self.ready_entries()
            if not entries or self.ok_canvas.image is None:
                raise SynthesisError("请先导入 OK 底图，并在 NG 图上圈选缺陷素材。")
            settings = self.settings()
            self.seed_offset = self.seed_offset+1 if next_sample else 0
            sample_seed = settings.seed+self.seed_offset
            base = self.ok_canvas.image.copy()
            self.notify("正在生成原尺寸预览…")
            self._start(lambda worker: choose_sample(base,entries,settings,sample_seed,worker.isInterruptionRequested), self.on_preview)
        except Exception as exc:
            self.notify(str(exc), True)

    def on_preview(self, result):
        image, mask, record = result
        self.preview_result = result
        self.preview_canvas.set_image(image)
        for index,box in enumerate(record.get('allowed_rois_xyxy',[])):
            self.preview_canvas.set_guide(f'roi-{index}',box,'#39dbc4',True)
        self.preview_canvas.set_guide('roi',record['allowed_roi_xyxy'],'#39dbc4',False)
        self.refresh_spatial_guides()
        self.refresh_overlay()
        self.tabs.setCurrentIndex(2)
        self.preview_info.setText(f"{image.width} × {image.height} · 种子 {record['seed']}")
        donor=record.get('pool_entry_name','当前素材')
        self.preview_info.setToolTip(f"NG来源：{donor}")
        self.notify(f"预览完成：NG「{donor[:24]}」，修改 {record['changed_pixel_count']:,} 像素。请检查后再批量导出。")

    def refresh_overlay(self):
        if self.preview_result:
            self.preview_canvas.set_mask_overlay(self.preview_result[1], self.overlay_check.isChecked())

    def set_preview_mode(self,mode):
        self.preview_canvas.set_mode('view')
        self.overlay_check.setChecked(mode=='changes')

    def choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出根文件夹", self.output_path.text())
        if folder:
            self.output_path.setText(folder)

    def export(self):
        if self.is_busy():
            return
        try:
            entries=self.ready_entries()
            if not entries or not self.ok_paths:
                raise SynthesisError("请先导入 OK 底图并圈选 NG 缺陷。")
            s = self.settings()
            out = self.output_path.text().strip()
            if not out:
                self.choose_output()
                out = self.output_path.text().strip()
            if not out:
                return
            self.progress.setRange(0, s.total_samples or len(self.ok_paths)*s.samples_per_ok)
            self.progress.setValue(0)
            self.export_info.setText("正在检查底图格式与素材是否能放入选区…")
            paths = list(self.ok_paths)
            self.notify("批次生成中；取消会保留已经完成的样本。")
            self._start(lambda worker: generate_pool_batch(paths, entries, s, out,
                        progress=worker.progress.emit, cancelled=worker.isInterruptionRequested), self.on_batch, True)
        except Exception as exc:
            self.notify(str(exc), True)

    def on_progress(self, done, total, name):
        self.progress.setValue(done)
        self.export_info.setText(f"已完成 {done} / {total} 张")

    def on_batch(self, summary):
        if summary.get("run_dir"):
            self.last_run = summary["run_dir"]
        done, total = summary["completed"], summary["total"]
        state = "已取消" if summary["status"] == "cancelled" else "生成完成"
        self.export_info.setText(f"{state} · {done} / {total} 张")
        self.message.setToolTip(self.last_run or "")
        self.notify(f"{state}。完成 {done}/{total} 张；每张包含 BMP、掩膜和通用 JSON。" + ("点击「打开结果」查看。" if summary.get("run_dir") else ""))

    def cancel(self):
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_btn.setEnabled(False)
            self.notify("正在取消，将在当前样本处理完成后停止…")

    def open_output(self):
        if self.last_run:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_run))

    def save_current_recipe(self):
        if self.is_busy():
            return
        try:
            entries=self.ready_entries()
            if not entries:
                raise SynthesisError("请先圈选缺陷素材，再保存配方。")
            settings = self.settings()
            path, _ = QFileDialog.getSaveFileName(self, "保存配方（包含缺陷素材）", "缺陷合成配方.json", "配方文件 (*.json)")
            if path:
                self.save_recipe_to(path)
                self.notify(f"素材池配方已保存，包含{len(entries)}份素材、各自范围、参数及底图路径。")
        except Exception as exc:
            self.notify(f"配方保存失败：{exc}", True)

    def save_recipe_to(self, path):
        entries=self.ready_entries()
        save_pool_recipe(path,entries,self.settings(),self.ok_paths,
                         [{'path':d.path,'id':d.entry_id,'roi':list(d.roi),'rois':[list(r) for r in d.rois]} for d in self.ng_documents if d.asset is None])

    def load_current_recipe(self):
        if self.is_busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, "加载配方", "", "配方文件 (*.json)")
        if path:
            self.apply_recipe(path)

    def apply_recipe(self, path):
        try:
            entries, s, paths, pending = load_pool_recipe(path)
            missing = [p for p in paths if not Path(p).is_file()]
            self.current_ng_index=-1
            self.ng_documents=[]
            self.asset=None
            self.ng_list.blockSignals(True)
            self.ng_list.clear()
            for entry in entries:
                source=entry.asset.provenance.get('source_ng') or ('embedded_pool/'+entry.name)
                self.ng_documents.append(NGDocument(source,entry.entry_id,entry.asset,tuple(entry.roi),'配方范围',entry.rois))
                self.ng_list.addItem(entry.name)
            known={os.path.normcase(d.path) for d in self.ng_documents}
            for item in pending:
                source=item['path']
                if os.path.normcase(source) not in known:
                    self.ng_documents.append(NGDocument(source,item['id'],None,tuple(item['roi']),'配方范围',tuple(tuple(r) for r in item.get('rois',()))))
                    self.ng_list.addItem(Path(source).name)
                    known.add(os.path.normcase(source))
            self.ng_list.blockSignals(False)
            self.roi = tuple(s.roi)
            self.roi_origin = "配方范围"
            self.ok_paths.clear()
            self.ok_list.clear()
            self.ok_canvas.set_empty("请导入真实 OK 底图，查看配方的生成范围。")
            self.ok_info.setText("请导入真实 OK 底图。")
            self.add_ok([p for p in paths if Path(p).is_file()])
            self.ng_list.setCurrentRow(0)
            self._update_pool_labels()
            self.method.setCurrentIndex(self.method.findData(s.mode))
            for widget, value in [(self.scale_min, s.scale_min), (self.scale_max, s.scale_max),
                    (self.strength_min, s.strength_min), (self.strength_max, s.strength_max),
                    (self.rotation, s.rotation), (self.feather, s.feather),
                    (self.samples, s.samples_per_ok), (self.seed, s.seed)]:
                widget.setValue(value)
            if s.reference_gray:
                self.reference.setValue(round(s.reference_gray))
            self.auto_reference.setChecked(s.reference_gray==0)
            self.reference.setEnabled(s.reference_gray!=0)
            self.class_name.setText(s.class_name)
            self.vt_xml_check.setChecked(s.export_vt_xml)
            self.batch_total.setValue(s.total_samples or 100)
            self.quantity_mode.setCurrentIndex(self.quantity_mode.findData('total' if s.total_samples else 'per_ok'))
            self.refresh_quantity_plan()
            self.tabs.setCurrentIndex(1)
            self.invalidate_preview()
            self.notify(f"配方已加载，缺陷素材已恢复。{len(missing)} 张底图路径失效，请重新导入。" if missing else "配方已加载。可直接预览，或重新打开 NG 图更换素材。")
        except Exception as exc:
            self.notify(f"配方加载失败：{exc}", True)

    def help(self):
        QMessageBox.information(self, "使用说明", "1. 导入同款产品的真实 OK 图，支持灰度 L 或 RGB。\n"
            "2. 多选同款同类 NG 图，逐张圈选缺陷；每张单独保留范围。\n"
            "3. 点击「在 NG 上框生成范围」，另框合理材料区域，按比例映射至全部 OK。\n"
            "4. 调整参数、生成预览，检查后再批量导出。\n\n"
            "暗缺陷迁移保留底图纹理，只叠加变暗效果；纹理粘贴复制素材外观。\n"
            "OK 与 NG 素材颜色模式须一致；RGB 输出保持彩色，灰度输出保持灰度。\n"
            "绿色框限制整个缺陷；蓝色虚框参考原 NG 位置。可在 OK 上微调，过小范围会拒绝生成。\n"
            "生成时从已圈选NG中按颜色模式、范围和尺寸匹配随机选用；未圈选项不参与。\n"
            "滚轮缩放，右键按住拖动平移。多边形按 Enter 或右键单击完成，Esc 清除。\n"
            "保存配方可保留素材和参数。原图不会被覆盖。\n\n"
            "VT XML使用本机VisionTrain缺陷检测的原生矩形结构，框为实际变化像素的外接框。"
            "PNG掩膜保留精细像素范围，JSON记录来源与参数。请按源OK图分组划分数据。")

    def closeEvent(self, event):
        if self.is_busy():
            self.notify("仍在处理图片。请先取消批次并等待当前样本完成，再关闭窗口。", True)
            event.ignore()
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="VT STUDIO 图像工具箱")
    parser.add_argument("--ng", nargs='+', help="启动时批量导入 NG 图，不自动圈选")
    parser.add_argument("--ok", nargs="*", help="启动时导入 OK 底图")
    parser.add_argument("--recipe", help="启动时加载配方")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("VTStudioToolbox")
    app.setOrganizationName("LocalVisionTools")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    from toolbox import ToolboxWindow
    window = ToolboxWindow()
    window.show()
    if args.recipe:
        window.select_page(1)
        QTimer.singleShot(0, lambda: window.defect.apply_recipe(args.recipe))
    else:
        if args.ok:
            window.select_page(1)
            QTimer.singleShot(0, lambda: window.defect.add_ok(args.ok))
        if args.ng:
            window.select_page(1)
            QTimer.singleShot(0, lambda: window.defect.add_ng(args.ng))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
