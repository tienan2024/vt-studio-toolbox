"""NG material-region selection is independent from donor extraction."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox import ToolboxWindow
from engine import save_recipe, pixel_roi


class NGRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'verification').mkdir(exist_ok=True)
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.ng=self.root/'TEST_ONLY_NG_material.bmp'
        self.ok=self.root/'TEST_ONLY_OK_material.bmp'
        ng=Image.new('RGB',(400,320),(205,190,170))
        draw=ImageDraw.Draw(ng)
        draw.rectangle((80,0,320,319),fill=(185,165,140))
        draw.ellipse((180,140,220,180),fill=(35,65,90))
        ng.save(self.ng)
        ok=Image.new('RGB',(800,640),(205,190,170))
        ImageDraw.Draw(ok).rectangle((160,0,640,639),fill=(185,165,140))
        ok.save(self.ok)
        self.w=ToolboxWindow();self.w.show();self.w.select_page(1)
        self.d=self.w.defect
        self.d.add_ok([str(self.ok)]);self.d.load_ng(str(self.ng))
        self.app.processEvents()

    def tearDown(self):
        self.w.close();self.app.processEvents()
        self.temp.cleanup()

    def wait(self):
        until=time.monotonic()+30
        while self.d.is_busy() and time.monotonic()<until:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(self.d.is_busy())

    def drag(self,canvas,box):
        canvas.fit_image();self.app.processEvents()
        l,t,r,b=box
        first=canvas.mapFromScene(QPointF(l,t));last=canvas.mapFromScene(QPointF(r,b))
        QTest.mousePress(canvas.viewport(),Qt.MouseButton.LeftButton,pos=first)
        QTest.mouseMove(canvas.viewport(),last,20)
        QTest.mouseRelease(canvas.viewport(),Qt.MouseButton.LeftButton,pos=last)
        self.app.processEvents()

    def test_ng_region_maps_to_ok_batch_recipe_and_missing_original(self):
        self.drag(self.d.ng_canvas,(165,125,235,195))
        asset=self.d.asset
        self.assertIsNotNone(asset)
        before=asset.pixels.tobytes()
        bbox=list(asset.provenance['source_bbox_xyxy'])
        QTest.mouseClick(self.d.ng_roi_btn,Qt.MouseButton.LeftButton)
        self.assertEqual(self.d.ng_canvas.mode,'roi')
        self.drag(self.d.ng_canvas,(100,80,300,240))
        self.assertIs(self.d.asset,asset)
        self.assertEqual(asset.pixels.tobytes(),before)
        self.assertEqual(asset.provenance['source_bbox_xyxy'],bbox)
        np.testing.assert_allclose(self.d.roi,(.25,.25,.75,.75),atol=.006)
        self.assertIn('NG 框选',self.d.roi_info.text())
        mapped=self.d._roi_box(self.d.roi,(800,640))
        np.testing.assert_allclose(self.d.ok_canvas.points[0],mapped[:2])
        self.assertIn('source',self.d.ok_canvas.guides)
        reference=self.d.ok_canvas.guides['source'].path().boundingRect()
        np.testing.assert_allclose([reference.left(),reference.top(),reference.right(),reference.bottom()],np.array(bbox)*2)
        self.assertIn('roi',self.d.ng_canvas.guides)
        self.d.source_guide_check.setChecked(False)
        self.assertNotIn('source',self.d.ok_canvas.guides)
        self.d.source_guide_check.setChecked(True)
        self.d.preview();self.wait()
        self.assertIsNotNone(self.d.preview_result,self.d.message.text())
        self.d.samples.setValue(12)
        self.d.output_path.setText(str(self.root/'generated'))
        self.d.export();self.wait()
        run=Path(self.d.last_run)
        records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records),12)
        roi=pixel_roi((800,640),self.d.roi)
        for item in records:
            self.assertEqual(item['allowed_roi_xyxy'],list(roi))
            l,t,r,b=item['placement_xyxy']
            self.assertTrue(roi[0]<=l<r<=roi[2] and roi[1]<=t<b<=roi[3])
            with Image.open(run/item['mask']) as mask:
                ys,xs=np.nonzero(np.asarray(mask))
                self.assertTrue(np.all((xs>=roi[0])&(xs<roi[2])&(ys>=roi[1])&(ys<roi[3])))
        # Inspect both the NG selection and its mapped OK region at shipped sizes.
        self.w.page_title.setText('NG 生成范围映射 · 人工测试数据')
        for size in ((1440,900),(1180,760)):
            self.w.resize(*size)
            for index,name in ((1,'ng'),(0,'ok')):
                self.d.tabs.setCurrentIndex(index)
                self.app.processEvents()
                self.assertTrue(self.w.grab().save(str(ROOT/f'verification/roi_{name}_{size[0]}.png')))
        recipe=self.root/'region-recipe.json'
        save_recipe(recipe,self.d.asset,self.d.settings(),self.d.ok_paths)
        expected=tuple(self.d.roi)
        self.ng.unlink()
        self.d.apply_recipe(str(recipe))
        self.assertEqual(tuple(self.d.roi),expected)
        self.assertFalse(self.d._has_full_ng())
        self.assertIsNotNone(self.d.asset)
        # A cropped embedded donor must not masquerade as a full-image coordinate system.
        self.d.begin_ng_roi()
        self.assertIn('完整 NG',self.d.message.text())
        self.assertEqual(tuple(self.d.roi),expected)
        self.d.begin_ok_roi()
        self.assertEqual(self.d.tabs.currentIndex(),0)
        self.d.ok_canvas.clear_selection()
        self.assertEqual(tuple(self.d.roi),(0,0,1,1))
        self.assertIsNotNone(self.d.asset)

    def test_region_before_asset_and_reset_keep_separate_state(self):
        self.d.begin_ng_roi()
        self.drag(self.d.ng_canvas,(100,80,300,240))
        self.assertIsNone(self.d.asset)
        roi=tuple(self.d.roi)
        self.d.ng_mode_picker.setCurrentIndex(self.d.ng_mode_picker.findData('rectangle'))
        self.drag(self.d.ng_canvas,(165,125,235,195))
        self.assertIsNotNone(self.d.asset)
        self.assertEqual(tuple(self.d.roi),roi)
        asset=self.d.asset
        self.d.begin_ng_roi()
        self.d.ng_mode_picker.setCurrentIndex(self.d.ng_mode_picker.findData('view'))
        self.d.ng_canvas.clear_selection()
        self.assertEqual(tuple(self.d.roi),(0,0,1,1))
        self.assertIs(self.d.asset,asset)
        self.assertNotIn('roi',self.d.ng_canvas.guides)
        self.d.begin_ng_roi()
        self.drag(self.d.ng_canvas,(10,10,20,20))
        self.d.preview();self.wait()
        self.assertIn('放不进',self.d.message.text())
        self.assertIs(self.d.asset,asset)


if __name__=='__main__':
    unittest.main(verbosity=2)
