import json
from pathlib import Path
import sys
import time
import unittest
import numpy as np
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox import ToolboxWindow


class ToolboxWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.folder=ROOT/'verification/toolbox_test_only'
        cls.inputs=cls.folder/'inputs'
        cls.inputs.mkdir(parents=True,exist_ok=True)
        yy,xx=np.indices((1500,1200),dtype=np.float32)
        data=190+7*np.sin(xx/7)*np.cos(yy/8)
        data[:,450:750]-=18
        data[:,:120]+=25
        data[:,-120:]+=25
        base=Image.fromarray(np.clip(data,0,255).astype(np.uint8))
        draw=ImageDraw.Draw(base)
        draw.line((250,0,250,1500),fill=135,width=3)
        draw.line((950,0,950,1500),fill=135,width=3)
        base.save(cls.inputs/'TEST_ONLY_示例底图.bmp')
        ng=Image.new('L',(300,300),190)
        ImageDraw.Draw(ng).ellipse((90,80,210,205),fill=50)
        cls.ng_path=cls.folder/'TEST_ONLY_污渍素材.bmp'
        ng.save(cls.ng_path)

    def wait(self,target):
        end=time.monotonic()+40
        while target.is_busy() and time.monotonic()<end:
            QTest.qWait(30)
        self.assertFalse(target.is_busy(),'后台任务未结束')

    def test_unified_conversion_handoff_and_defect_export(self):
        w=ToolboxWindow()
        w.show()
        QTest.qWait(100)
        c=w.converter
        c.set_input(str(self.inputs))
        self.wait(c)
        self.assertEqual(len(c.paths),1)
        c.width.setValue(1240)
        c.height.setValue(1540)
        c.fill.setCurrentIndex(1)
        c.output_root.setText(str(self.folder/'converted'))
        QTest.mouseClick(c.start_button,Qt.MouseButton.LeftButton)
        self.wait(c)
        self.assertEqual(len(c.results),1,c.message.text())
        with Image.open(c.results[0]) as converted:
            self.assertEqual(converted.size,(1240,1540))
        for size in [(1440,900),(1180,760)]:
            w.resize(*size)
            w.page_title.setText('尺寸与原点 · 测试数据')
            QTest.qWait(100)
            self.assertTrue(w.grab().save(str(ROOT/f'verification/toolbox_converter_{size[0]}.png')))
        QTest.mouseClick(c.send_button,Qt.MouseButton.LeftButton)
        self.assertEqual(w.pages.currentIndex(),1)
        self.assertIn(c.results[0],w.defect.ok_paths)
        d=w.defect
        d.load_ng(str(self.ng_path))
        d.set_asset([(75,65),(225,65),(225,220),(75,220)])
        d.preview()
        self.wait(d)
        self.assertIsNotNone(d.preview_result,d.message.text())
        d.output_path.setText(str(self.folder/'defects'))
        d.samples.setValue(2)
        d.export()
        self.wait(d)
        summary=json.loads((Path(d.last_run)/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['completed'],2)
        for size in [(1440,900),(1180,760)]:
            w.resize(*size)
            w.page_title.setText('缺陷合成 · 测试数据')
            QTest.qWait(100)
            # The hint and canvas must remain separate even at the small size.
            page = d.tabs.widget(2)
            labels = [label for label in page.findChildren(QLabel)
                      if label.text().startswith('滚轮缩放')]
            self.assertEqual(len(labels),1)
            canvas_bottom = d.preview_canvas.mapToGlobal(d.preview_canvas.rect().bottomLeft()).y()
            hint_top = labels[0].mapToGlobal(labels[0].rect().topLeft()).y()
            self.assertLessEqual(canvas_bottom,hint_top)
            self.assertTrue(w.grab().save(str(ROOT/f'verification/toolbox_defect_{size[0]}.png')))
        # Switching modules retains the selected input, parameters and donor.
        QTest.mouseClick(w.convert_nav,Qt.MouseButton.LeftButton)
        self.assertEqual(c.width.value(),1240)
        QTest.mouseClick(w.defect_nav,Qt.MouseButton.LeftButton)
        self.assertIsNotNone(d.asset)
        # Old material must never remain on screen after an empty/broken new input.
        empty=self.folder/'empty_input'
        empty.mkdir(exist_ok=True)
        c.set_input(str(empty))
        self.wait(c)
        self.assertIsNone(c.range_canvas.image)
        self.assertIsNone(c.output_canvas.image)
        self.assertEqual(c.results,[])
        broken=self.folder/'broken_input'
        broken.mkdir(exist_ok=True)
        (broken/'invalid.bmp').write_bytes(b'not a bitmap')
        c.set_input(str(broken))
        self.wait(c)
        self.assertIsNone(c.range_canvas.image)
        self.assertIsNone(c.output_canvas.image)
        self.assertIn('预览读取失败',c.message.text())
        w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
