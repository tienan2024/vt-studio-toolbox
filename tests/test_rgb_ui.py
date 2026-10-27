"""Actual Qt RGB workflow with synthetic, clearly labelled fixtures."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox import ToolboxWindow
from engine import save_recipe


class RGBDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def wait(self,target):
        until=time.monotonic()+30
        while target.is_busy() and time.monotonic()<until:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(target.is_busy())

    def test_rgb_conversion_handoff_preview_export_and_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); inputs=root/'input'; inputs.mkdir()
            base=Image.new('RGB',(400,320),(180,150,115))
            ok=inputs/'TEST_ONLY_RGB_OK.bmp';base.save(ok)
            ng=Image.new('RGB',(150,150),(220,190,160))
            ImageDraw.Draw(ng).ellipse((55,50,95,95),fill=(35,65,100))
            ng_path=root/'TEST_ONLY_RGB_NG.bmp';ng.save(ng_path)
            w=ToolboxWindow();w.show()
            try:
                c=w.converter;c.set_input(str(inputs));self.wait(c)
                c.width.setValue(420);c.height.setValue(340)
                c.output_root.setText(str(root/'converted'));c.start();self.wait(c)
                self.assertEqual(len(c.results),1)
                c.send()
                d=w.defect
                self.assertEqual(d.ok_canvas.image.mode,'RGB')
                self.assertIn('24 位 RGB',d.ok_info.text())
                d.load_ng(str(ng_path))
                d.set_asset([(40,35),(110,35),(110,110),(40,110)])
                self.assertEqual(d.asset.pixels.mode,'RGB')
                self.assertIn('RGB',d.ng_info.text())
                # Thumbnail must retain distinct R/G/B values.
                thumb=d.asset_thumb.pixmap().toImage()
                color=thumb.pixelColor(thumb.width()//2,thumb.height()//2)
                self.assertNotEqual(color.red(),color.blue())
                d.samples.setValue(2);d.preview();self.wait(d)
                self.assertIsNotNone(d.preview_result,d.message.text())
                self.assertEqual(d.preview_result[0].mode,'RGB')
                d.output_path.setText(str(root/'generated'));d.export();self.wait(d)
                self.assertIsNotNone(d.last_run,d.message.text())
                run=Path(d.last_run)
                self.assertEqual(json.loads((run/'summary.json').read_text(encoding='utf-8'))['completed'],2)
                with Image.open(c.results[0]) as source:
                    source_pixels=np.asarray(source)
                for output in (run/'images').glob('*.bmp'):
                    with Image.open(output) as im, Image.open(run/'masks'/f'{output.stem}.png') as mask:
                        self.assertEqual(im.mode,'RGB')
                        self.assertEqual(im.size,(420,340))
                        np.testing.assert_array_equal(np.any(np.asarray(im)!=source_pixels,axis=2),np.asarray(mask)>0)
                recipe=root/'rgb-recipe.json'
                save_recipe(recipe,d.asset,d.settings(),d.ok_paths)
                d.apply_recipe(str(recipe))
                self.assertEqual(d.asset.pixels.mode,'RGB')
                self.assertEqual(d.ng_canvas.image.mode,'RGB')
                d.preview();self.wait(d)
                self.assertEqual(d.preview_result[0].mode,'RGB')
                w.page_title.setText('缺陷合成 · RGB 人工测试数据')
                w.resize(1440,900);self.app.processEvents()
                (ROOT/'verification').mkdir(exist_ok=True)
                self.assertTrue(w.grab().save(str(ROOT/'verification/toolbox_rgb.png')))
            finally:
                w.close();self.app.processEvents()


if __name__=='__main__':
    unittest.main(verbosity=2)
