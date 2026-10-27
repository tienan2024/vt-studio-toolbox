"""Unified VT Studio toolbox shell; both tools share one process and one window."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QMessageBox)

from app import MainWindow
from converter_ui import ConverterPage
from engine import VERSION
from theme import THEME


def nav_icon(kind):
    pm = QPixmap(40,40)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#d6e1ee'),2.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if kind == 'resize':
        p.drawRoundedRect(8,8,24,24,3,3)
        p.drawLine(12,27,27,12)
        p.drawLine(19,12,27,12)
        p.drawLine(27,12,27,20)
    elif kind == 'defect':
        p.drawRoundedRect(7,7,26,26,3,3)
        p.drawEllipse(16,15,11,11)
        p.drawLine(13,12,13,14)
        p.drawLine(28,28,30,30)
    else:
        p.drawEllipse(8,8,24,24)
        p.drawLine(20,17,20,27)
        p.drawPoint(20,12)
    p.end()
    return QIcon(pm)


class ToolboxWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('VT STUDIO · 图像工具箱')
        self.setMinimumSize(1180,720)
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1440,area.width()-60),min(900,area.height()-60))
        self.setStyleSheet(THEME)
        icon = Path(__file__).with_name('app.ico')
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(176)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16,25,16,18)
        side.setSpacing(10)
        mark = QLabel('VT')
        mark.setObjectName('BrandMark')
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40,40)
        side.addWidget(mark)
        brand = QLabel('VT STUDIO')
        brand.setObjectName('Brand')
        side.addWidget(brand)
        subtitle = QLabel('图像处理工具箱')
        side.addWidget(subtitle)
        side.addSpacing(27)
        self.convert_nav = self.nav_button('尺寸与原点','resize',lambda:self.select_page(0))
        self.defect_nav = self.nav_button('缺陷合成','defect',lambda:self.select_page(1))
        side.addWidget(self.convert_nav)
        side.addWidget(self.defect_nav)
        side.addStretch()
        help_button = QPushButton('使用说明')
        help_button.setIcon(nav_icon('help'))
        help_button.setIconSize(QSize(20,20))
        help_button.clicked.connect(self.help)
        side.addWidget(help_button)
        side.addSpacing(12)
        footer = QLabel(f'VT STUDIO  {VERSION}')
        footer.setStyleSheet('font-size: 11px; color: #b1c0d1; line-height: 1.6;')
        side.addWidget(footer)
        root.addWidget(sidebar)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(18,0,18,12)
        body.setSpacing(10)
        header = QWidget()
        header.setObjectName('Header')
        top = QHBoxLayout(header)
        top.setContentsMargins(12,21,12,17)
        title_column = QVBoxLayout()
        title_column.setSpacing(5)
        self.page_title = QLabel()
        self.page_title.setObjectName('PageTitle')
        self.page_description = QLabel()
        self.page_description.setObjectName('Subtle')
        title_column.addWidget(self.page_title)
        title_column.addWidget(self.page_description)
        top.addLayout(title_column,1)
        body.addWidget(header)
        self.pages = QStackedWidget()
        self.converter = ConverterPage()
        self.defect = MainWindow(embedded=True)
        self.pages.addWidget(self.converter)
        self.pages.addWidget(self.defect)
        self.converter.send_to_defects.connect(self.receive_ok)
        body.addWidget(self.pages,1)
        root.addWidget(content,1)
        self.select_page(0)

    def nav_button(self, text, icon, action):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setIcon(nav_icon(icon))
        b.setIconSize(QSize(20,20))
        b.clicked.connect(action)
        return b

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        self.convert_nav.setChecked(index==0)
        self.defect_nav.setChecked(index==1)
        if index == 0:
            self.page_title.setText('尺寸与原点')
            self.page_description.setText('统一图像尺寸，保持像素比例与左上角坐标。')
        else:
            self.page_title.setText('缺陷合成')
            self.page_description.setText('从真实 NG 素材制作训练补充图，预览后批量导出。')

    def receive_ok(self, paths):
        if self.defect.is_busy():
            self.converter.notify('缺陷合成正在处理任务，请完成或停止后再传入底图。',True)
            return
        self.defect.add_ok(paths)
        self.select_page(1)
        self.defect.tabs.setCurrentIndex(0)

    def help(self):
        QMessageBox.information(self,'VT STUDIO 图像工具箱',
            '尺寸与原点\n选择图片文件夹 → 设置目标宽高和填充颜色 → 检查预览 → 开始转换。\n'
            '沿用 VT Studio 5.0 原转换核心，固定左上角 (0,0)，仅处理右侧与下方。\n'
            'XML 可原样复制，点集坐标不会转换。\n\n'
            '缺陷合成\n导入 OK → 打开 NG 并圈选 → 设置允许区域和参数 → 预览 → 批量生成。\n'
            '可将转换结果明确作为 OK 底图送入缺陷合成。\n\n'
            '原图不覆盖，每个批次单独保存。\n'
            '支持VT缺陷检测原生矩形XML；PNG掩膜保留精细像素，JSON保留来源。')

    def closeEvent(self, event):
        if self.converter.is_busy() or self.defect.is_busy():
            if self.converter.is_busy():
                self.select_page(0)
                self.converter.notify('仍在处理图片，请停止当前任务并等待结束后再关闭。',True)
            else:
                self.select_page(1)
                self.defect.notify('仍在处理图片，请取消当前任务并等待结束后再关闭。',True)
            event.ignore()
        else:
            event.accept()
