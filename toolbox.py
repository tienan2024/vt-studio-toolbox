"""Unified VT Studio toolbox shell; all tools share one process and one window."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QMessageBox)

from app import MainWindow
from converter_ui import ConverterPage
from script_ui import ScriptPage
from camera_ui import CameraPage
from engine import VERSION
from theme import THEME
from styled_controls import install_shared_controls


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
    elif kind == 'script':
        p.drawLine(15,12,8,20);p.drawLine(8,20,15,28)
        p.drawLine(25,12,32,20);p.drawLine(32,20,25,28)
        p.drawLine(22,10,18,30)
    elif kind == 'camera':
        p.drawRoundedRect(6,12,28,21,3,3);p.drawEllipse(14,16,12,12)
        p.drawLine(12,12,15,7);p.drawLine(15,7,25,7);p.drawLine(25,7,28,12)
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
        self.shared_controls=install_shared_controls(self)
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
        subtitle = QLabel('视觉工程工具箱')
        side.addWidget(subtitle)
        side.addSpacing(27)
        self.convert_nav = self.nav_button('尺寸与原点','resize',lambda:self.select_page(0))
        self.defect_nav = self.nav_button('缺陷合成','defect',lambda:self.select_page(1))
        self.script_nav = self.nav_button('脚本生成与测试','script',lambda:self.select_page(2))
        self.camera_nav = self.nav_button('相机参数','camera',lambda:self.select_page(3))
        side.addWidget(self.convert_nav)
        side.addWidget(self.defect_nav)
        side.addWidget(self.script_nav)
        side.addWidget(self.camera_nav)
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
        self.script = ScriptPage()
        self.camera = CameraPage()
        self.pages.addWidget(self.converter)
        self.pages.addWidget(self.defect)
        self.pages.addWidget(self.script)
        self.pages.addWidget(self.camera)
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
        self.script_nav.setChecked(index==2)
        self.camera_nav.setChecked(index==3)
        if index == 0:
            self.page_title.setText('尺寸与原点')
            self.page_description.setText('统一图像尺寸，保持像素比例与左上角坐标。')
        elif index == 1:
            self.page_title.setText('缺陷合成')
            self.page_description.setText('从真实 NG 素材制作训练补充图，预览后批量导出。')
        elif index == 2:
            self.page_title.setText('脚本生成与测试')
            self.page_description.setText('配置产品判定规则，生成 VM 脚本，并编译验证每一项输出。')
        else:
            self.page_title.setText('相机参数')
            self.page_description.setText('材料尺寸 → 视野与工作距离 → 取图高度 → 编码器倍频。')

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
            '脚本生成与测试\n配置 NG 类型、独立信号与标签归一化 → 查看代码 → 离线编译测试 → 复制脚本或保存 .cs。\n'
            '可读取SOL变量并自动应用到方案副本，或按清单手工配置。\n\n'
            '相机参数\n选择相机及固定镜头 → 填材料宽长与横向总余量 → 计算视野/工作距离及规划精度 → 推荐图高与周期整数倍频。\n'
            '图高与Z周期总行触发数分开，并保留周期空档。周期行数够用不代表实际无拉伸，需原始产品图或周期走料标定。专业标定/IO/成像在更多参数中；设备写入仍需有效对比。\n\n'
            '原图不覆盖，每个批次单独保存。\n'
            '支持VT缺陷检测原生多边形XML；轮廓与PNG掩膜对应，JSON保留来源。')

    def closeEvent(self, event):
        if self.converter.is_busy() or self.defect.is_busy() or self.script.is_busy() or self.camera.is_busy():
            if self.converter.is_busy():
                self.select_page(0)
                self.converter.notify('仍在处理图片，请停止当前任务并等待结束后再关闭。',True)
            elif self.defect.is_busy():
                self.select_page(1)
                self.defect.notify('仍在处理图片，请取消当前任务并等待结束后再关闭。',True)
            elif self.script.is_busy():
                self.select_page(2)
                self.script.notify('脚本测试或 SOL 操作正在执行，完成后再关闭窗口。',True)
            else:
                self.select_page(3)
                self.camera.notify('相机操作正在执行，请等待完成后再关闭窗口。',True)
            event.ignore()
        else:
            event.accept()
