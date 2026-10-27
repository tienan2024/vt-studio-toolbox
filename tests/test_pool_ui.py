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


class PoolDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'verification').mkdir(exist_ok=True)
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.ng=[]
        for i,mode in enumerate(('L','L','RGB','L')):
            image=Image.new(mode,(100,100),190 if mode=='L' else (210,190,170))
            ImageDraw.Draw(image).ellipse((35,35,65,65),fill=40+i*15 if mode=='L' else (35,65,90))
            path=self.root/f'TEST_ONLY_NG_{i}_{mode}.bmp';image.save(path);self.ng.append(path)
        self.ok=[]
        for mode in ('L','RGB'):
            path=self.root/f'TEST_ONLY_OK_{mode}.bmp'
            Image.new(mode,(400,320),180 if mode=='L' else (180,150,120)).save(path);self.ok.append(path)
        self.w=ToolboxWindow();self.w.show();self.w.select_page(1)
        self.d=self.w.defect
        self.d.add_ok([str(p) for p in self.ok]);self.d.add_ng([str(p) for p in self.ng])

    def tearDown(self):
        self.w.close();self.app.processEvents();self.temp.cleanup()

    def wait(self):
        until=time.monotonic()+30
        while self.d.is_busy() and time.monotonic()<until:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(self.d.is_busy())

    def prepare(self,row,roi):
        self.d.ng_list.setCurrentRow(row)
        self.d.set_asset([(30,30),(70,30),(70,70),(30,70)])
        self.d.begin_ng_roi()
        l,t,r,b=roi
        self.d.ng_canvas.selection_changed.emit([(l*100,t*100),(r*100,t*100),(r*100,b*100),(l*100,b*100)])

    def test_multiple_ng_states_matching_export_and_embedded_pool_recipe(self):
        self.prepare(0,(.1,.1,.7,.7));asset_a=self.d.asset
        self.prepare(1,(.3,.3,.9,.9));asset_b=self.d.asset
        self.prepare(2,(.2,.2,.8,.8))
        self.d.ng_list.setCurrentRow(0)
        self.assertIs(self.d.asset,asset_a)
        self.assertEqual(tuple(self.d.roi),(.1,.1,.7,.7))
        self.d.ng_list.setCurrentRow(1)
        self.assertIs(self.d.asset,asset_b)
        self.assertEqual(tuple(self.d.roi),(.3,.3,.9,.9))
        self.assertIn('3/4',self.d.pool_info.text())
        # An unfinished selected NG must not prevent using the other ready donors.
        self.d.ng_list.setCurrentRow(3);self.d.begin_ng_roi()
        self.d.ng_canvas.selection_changed.emit([(40,40),(90,40),(90,90),(40,90)])
        self.assertIsNone(self.d.asset)
        self.d.ok_list.setCurrentRow(0)
        self.d.samples.setValue(8)
        self.d.output_path.setText(str(self.root/'output'));self.d.export();self.wait()
        self.assertIsNotNone(self.d.last_run,self.d.message.text())
        run=Path(self.d.last_run)
        records=[json.loads(line) for line in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(records),16)
        entries={e.entry_id:e for e in self.d.ready_entries()}
        used=set()
        for record in records:
            entry=entries[record['pool_entry_id']];used.add(entry.entry_id)
            self.assertEqual(record['image_mode'],entry.asset.pixels.mode)
            self.assertEqual(record['source_roi_normalized'],list(entry.roi))
            l,t,r,b=record['placement_xyxy'];rl,rt,rr,rb=record['allowed_roi_xyxy']
            self.assertTrue(rl<=l<r<=rr and rt<=t<b<=rb)
            self.assertEqual(record['source_defect'],entry.asset.provenance)
        self.assertEqual(used,set(entries))
        self.d.ng_list.setCurrentRow(0)
        self.w.page_title.setText('多 NG 素材池 · 人工测试数据')
        self.d.tabs.setCurrentIndex(1)
        for size in ((1440,900),(1180,760)):
            self.w.resize(*size);self.app.processEvents()
            self.assertTrue(self.w.grab().save(str(ROOT/f'verification/pool_ui_{size[0]}.png')))
        recipe=self.root/'pool.json';self.d.save_recipe_to(recipe)
        for path in self.ng[:3]:
            path.unlink()
        self.d.apply_recipe(str(recipe))
        self.assertEqual(len(self.d.ng_documents),4)
        self.assertEqual(len(self.d.ready_entries()),3)
        self.assertEqual(self.d.ng_documents[3].roi,(.4,.4,.9,.9))
        self.assertFalse(self.d._has_full_ng())
        embedded=self.d.asset
        self.d.set_asset([(1,1),(20,1),(20,20),(1,20)])
        self.assertIs(self.d.asset,embedded)
        self.assertIn('原NG',self.d.message.text())
        self.d.preview();self.wait()
        self.assertIsNotNone(self.d.preview_result,self.d.message.text())
        self.assertIn(self.d.preview_result[2]['pool_entry_id'],entries)

    def test_remove_multiple_ng_and_invalid_new_source_never_show_old_material(self):
        self.prepare(0,(.1,.1,.7,.7))
        self.prepare(1,(.3,.3,.9,.9))
        self.d.ng_list.clearSelection()
        self.d.ng_list.item(0).setSelected(True)
        self.d.ng_list.item(1).setSelected(True)
        self.d.remove_ng()
        self.assertEqual(len(self.d.ng_documents),2)
        self.assertIsNone(self.d.asset)
        self.ng[3].unlink()
        self.d.ng_list.setCurrentRow(1)
        self.assertIsNone(self.d.ng_canvas.image)
        self.assertIsNone(self.d.ng_image)
        self.assertIn('不可用',self.d.message.text())
        self.d.ng_list.selectAll();self.d.remove_ng()
        self.assertEqual(self.d.ng_documents,[])
        self.assertIsNone(self.d.asset)
        self.assertIsNone(self.d.preview_canvas.image)


if __name__=='__main__':
    unittest.main(verbosity=2)
