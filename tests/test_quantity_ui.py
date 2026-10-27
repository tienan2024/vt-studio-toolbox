import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from toolbox import ToolboxWindow


class QuantityDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'verification').mkdir(exist_ok=True)
        cls.app=QApplication.instance() or QApplication([])

    def wait(self,d):
        until=time.monotonic()+30
        while d.is_busy() and time.monotonic()<until:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(d.is_busy())

    def test_total_widget_exact_export_preview_preserved_and_recipe(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(2):
                p=root/f'TEST_ONLY_OK_{i}.bmp';Image.new('L',(400,320),180).save(p);paths.append(str(p))
            ng=root/'TEST_ONLY_NG.bmp';image=Image.new('L',(100,100),190)
            ImageDraw.Draw(image).ellipse((35,35,65,65),fill=40);image.save(ng)
            w=ToolboxWindow();w.show();w.select_page(1);d=w.defect
            try:
                d.add_ok(paths);d.load_ng(str(ng));d.set_asset([(30,30),(70,30),(70,70),(30,70)])
                self.assertEqual(d.quantity_mode.currentData(),'per_ok')
                d.samples.setValue(2);self.assertIn('4',d.quantity_info.text())
                d.preview();self.wait(d);preview=d.preview_result
                d.quantity_mode.setCurrentIndex(d.quantity_mode.findData('total'))
                d.batch_total.setValue(5)
                self.assertIs(d.preview_result,preview)
                self.assertIn('5',d.quantity_info.text())
                d.output_path.setText(str(root/'output'));d.export();self.wait(d)
                run=Path(d.last_run);summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
                self.assertEqual(summary['completed'],5)
                self.assertEqual(summary['total'],5)
                self.assertEqual([p['count'] for p in summary['planned_ok_counts']],[3,2])
                self.assertEqual(d.progress.maximum(),5)
                self.assertEqual(len(list((run/'images').glob('*.bmp'))),5)
                recipe=root/'quantity.json';d.save_recipe_to(recipe)
                d.quantity_mode.setCurrentIndex(d.quantity_mode.findData('per_ok'))
                d.apply_recipe(str(recipe))
                self.assertEqual(d.quantity_mode.currentData(),'total')
                self.assertEqual(d.batch_total.value(),5)
                w.page_title.setText('批量生成数量 · 人工测试数据')
                for size in ((1440,900),(1180,760)):
                    w.resize(*size);self.app.processEvents()
                    self.assertTrue(w.grab().save(str(ROOT/f'verification/quantity_ui_{size[0]}.png')))
                    self.assertTrue(d.batch_total.isVisible())
                    self.assertFalse(d.samples.isVisible())
            finally:
                w.close();self.app.processEvents()


if __name__=='__main__':
    unittest.main(verbosity=2)
