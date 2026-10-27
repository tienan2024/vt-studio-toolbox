"""Exercise our own Qt widgets and background export, with explicitly artificial fixtures."""
import json
from pathlib import Path
import sys
import time
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import MainWindow
from engine import load_gray, save_recipe, Settings


class DesktopWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.output = ROOT/'verification'
        cls.output.mkdir(exist_ok=True)
        cls.fixtures = cls.output/'test_only_fixtures'
        cls.fixtures.mkdir(exist_ok=True)
        rng = np.random.default_rng(7)
        w, h = 3200, 3960
        yy, xx = np.indices((h,w), dtype=np.float32)
        texture = 188 + 5*np.sin(xx/7) * np.cos(yy/8) + rng.normal(0, 2, (h,w))
        texture[:, :420] += 25
        texture[:, -420:] += 25
        texture[:, 1240:1960] -= 17
        base = Image.fromarray(np.clip(texture,0,255).astype(np.uint8))
        draw = ImageDraw.Draw(base)
        for x in (650,2550):
            draw.line((x,0,x,h),fill=145,width=8)
            draw.rectangle((x-35,550,x+35,620),fill=110)
        cls.ok_path = cls.fixtures/'TEST_ONLY_人工底图_非生产OK.bmp'
        base.save(cls.ok_path)
        donor = Image.fromarray(np.clip(185+rng.normal(0,3,(650,650)),0,255).astype(np.uint8))
        stain = Image.new('L',donor.size)
        d = ImageDraw.Draw(stain)
        d.polygon([(180,160),(280,120),(400,175),(460,240),(425,330),(440,410),(320,450),(200,390),(135,310)],fill=180)
        stain = stain.filter(ImageFilter.GaussianBlur(6))
        dark = np.asarray(donor,dtype=np.float32)*(1-np.asarray(stain,dtype=np.float32)/255)
        donor=Image.fromarray(dark.astype(np.uint8))
        cls.ng_path = cls.fixtures/'TEST_ONLY_人工污渍.bmp'
        donor.save(cls.ng_path)

    def wait_worker(self, window):
        deadline=time.monotonic()+40
        while window.is_busy() and time.monotonic()<deadline:
            QTest.qWait(30)
        self.assertFalse(window.is_busy(),'后台任务未在40秒内完成')

    def test_complete_desktop_workflow(self):
        w=MainWindow()
        w.findChild(QLabel,'Title').setText('VT 缺陷合成工具 · 测试数据')
        w.show()
        QTest.qWait(100)
        w.add_ok([str(self.ok_path)])
        w.load_ng(str(self.ng_path))
        QTest.qWait(100)
        canvas=w.ng_canvas
        points=[(110,110),(480,110),(480,470),(110,470)]
        # Draw through widget events; do not call the extraction slot directly.
        canvas.set_mode('polygon')
        for point in points:
            pos=canvas.mapFromScene(QPointF(*point))
            QTest.mouseClick(canvas.viewport(),Qt.MouseButton.LeftButton,pos=pos)
        QTest.keyClick(canvas,Qt.Key.Key_Return)
        self.assertIsNotNone(w.asset)
        # View pixels quantize scene coordinates at fit-to-window zoom.
        self.assertLessEqual(abs(w.asset.pixels.width-370),2)
        self.assertLessEqual(abs(w.asset.pixels.height-360),2)
        w.tabs.setCurrentIndex(0)
        self.app.processEvents()
        c=w.ok_canvas
        a=c.mapFromScene(QPointF(850,800))
        b=c.mapFromScene(QPointF(2350,3200))
        QTest.mousePress(c.viewport(),Qt.MouseButton.LeftButton,pos=a)
        QTest.mouseMove(c.viewport(),b)
        QTest.mouseRelease(c.viewport(),Qt.MouseButton.LeftButton,pos=b)
        self.assertGreater(w.roi[0],0.2)
        self.assertLess(w.roi[2],0.8)
        QTest.mouseClick(w.preview_btn,Qt.MouseButton.LeftButton)
        self.wait_worker(w)
        self.assertIsNotNone(w.preview_result,w.message.text())
        out,mask,info=w.preview_result
        self.assertEqual(out.size,(3200,3960))
        self.assertEqual(w.tabs.currentIndex(),2)
        self.assertTrue(info['changed_pixel_count']>0)
        w.overlay_check.setChecked(True)
        self.app.processEvents()
        self.assertIsNotNone(w.preview_canvas.overlay)
        w.resize(1360,900)
        QTest.qWait(80)
        self.assertTrue(w.grab().save(str(self.output/'desktop_1360.png')))
        w.resize(1060,720)
        QTest.qWait(80)
        visible=w.preview_canvas.mapToScene(w.preview_canvas.viewport().rect()).boundingRect()
        self.assertTrue(visible.contains(w.preview_canvas.sceneRect()),'适应窗口应完整显示整张图片')
        self.assertTrue(w.grab().save(str(self.output/'desktop_1060.png')))
        w.output_path.setText(str(self.output/'ui_export'))
        w.samples.setValue(2)
        QTest.mouseClick(w.export_btn,Qt.MouseButton.LeftButton)
        self.wait_worker(w)
        self.assertIsNotNone(w.last_run,w.message.text())
        run=Path(w.last_run)
        summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['status'],'complete')
        self.assertEqual(summary['completed'],2)
        for p in (run/'images').glob('*.bmp'):
            self.assertEqual(load_gray(p).size,(3200,3960))
        # Portable embedded recipe works, and missing OKs must clear the old canvas.
        recipe=self.output/'missing_paths_recipe.json'
        save_recipe(recipe,w.asset,w.settings(),['Z:/not_a_real_path/missing.bmp'])
        w.apply_recipe(str(recipe))
        self.assertEqual(w.ok_paths,[])
        self.assertIsNone(w.ok_canvas.image)
        self.assertIsNotNone(w.asset)
        w.ng_canvas.clear_selection()
        self.assertIsNone(w.asset)
        w.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
