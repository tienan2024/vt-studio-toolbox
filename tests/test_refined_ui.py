import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from PIL import Image,ImageDraw
from PySide6.QtCore import Qt,QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLabel,QScrollArea
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import AdaptiveImageList
from toolbox import ToolboxWindow


class RefinedDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'verification').mkdir(exist_ok=True)
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def wait(self,d):
        end=time.monotonic()+30
        while d.is_busy() and time.monotonic()<end:
            self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(d.is_busy())

    def test_image_list_auto_height_with_bounds(self):
        widget=AdaptiveImageList();widget.show();self.app.processEvents()
        self.assertEqual(widget.height(),80)
        widget.addItems([f'image-{i}.bmp' for i in range(20)]);self.app.processEvents()
        self.assertEqual(widget.height(),180)
        widget.clear();self.app.processEvents()
        self.assertEqual(widget.height(),80)
        widget.close()

    def test_manual_auto_reference_multi_frames_toolbar_and_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);ok=base/'TEST_ONLY_OK.bmp';ng=base/'TEST_ONLY_NG.bmp'
            Image.new('L',(500,400),180).save(ok)
            donor=Image.new('L',(100,100),190);ImageDraw.Draw(donor).ellipse((40,40,60,60),fill=40);donor.save(ng)
            w=ToolboxWindow();w.show();w.select_page(1);d=w.defect
            try:
                self.assertTrue(d.auto_reference.isChecked());self.assertFalse(d.reference.isEnabled())
                self.assertEqual(d.settings().reference_gray,0)
                d.auto_reference.setChecked(False);d.reference.setValue(173)
                self.assertTrue(d.reference.isEnabled());self.assertEqual(d.settings().reference_gray,173)
                d.auto_reference.setChecked(True)
                self.assertEqual(d.reference.value(),173);self.assertEqual(d.settings().reference_gray,0)
                self.assertFalse(any(label.text().strip() in ('本地离线','本地处理 · 无需 GPU') for label in w.findChildren(QLabel)))
                self.assertLessEqual(d.ng_canvas.sceneRect().width(),340)
                w.page_title.setText('空画布 · 界面测试');w.resize(1440,900);self.app.processEvents()
                w.grab().save(str(ROOT/'verification/refined_empty.png'))
                d.add_ok([str(ok)]);d.load_ng(str(ng));d.set_asset([(35,35),(65,35),(65,65),(35,65)])
                asset=d.asset
                picker=d.ng_mode_picker
                QTest.mouseClick(picker.group.button(picker.findData('roi')),Qt.MouseButton.LeftButton)
                QTest.qWait(20)
                self.assertEqual(d.ng_canvas.mode,'roi')
                self.assertTrue(picker.group.button(picker.findData('roi')).isChecked())
                self.assertEqual(picker.animation.duration(),150)
                self.assertEqual(picker.animation.state(),QAbstractAnimation.State.Running)
                for points in ([(5,10),(35,10),(35,40),(5,40)],[(65,60),(95,60),(95,90),(65,90)]):
                    d.ng_canvas.selection_changed.emit(points)
                self.assertEqual(len(d.rois),2);self.assertEqual(d.roi_list.count(),2)
                self.assertIs(d.asset,asset)
                self.assertIn('roi-1',d.ok_canvas.guides)
                d.samples.setValue(12);d.output_path.setText(str(base/'output'));d.export();self.wait(d)
                run=Path(d.last_run)
                records=[json.loads(s) for s in (run/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(len(records),12)
                self.assertEqual({r['selected_roi_index'] for r in records},{0,1})
                self.assertEqual(len(list((run/'images').glob('*.xml'))),12)
                d.preview();self.wait(d)
                d.preview_mode_picker.setCurrentIndex(d.preview_mode_picker.findData('changes'))
                self.assertIsNotNone(d.preview_canvas.overlay)
                d.auto_reference.setChecked(False);d.reference.setValue(173)
                recipe=base/'recipe.json';d.save_recipe_to(recipe);d.auto_reference.setChecked(True)
                d.apply_recipe(str(recipe))
                self.assertFalse(d.auto_reference.isChecked());self.assertTrue(d.reference.isEnabled())
                self.assertEqual(d.reference.value(),173);self.assertEqual(len(d.rois),2)
                w.page_title.setText('多范围与平铺工具 · 人工测试数据')
                for size in ((1440,900),(1180,760)):
                    w.resize(*size);d.tabs.setCurrentIndex(1);self.app.processEvents()
                    w.grab().save(str(ROOT/f'verification/refined_loaded_{size[0]}.png'))
                d.auto_reference.setChecked(True)
                for scroll in d.findChildren(QScrollArea):
                    if scroll.widget()==d.controls:
                        scroll.ensureWidgetVisible(d.reference)
                self.app.processEvents()
                w.grab().save(str(ROOT/'verification/refined_auto_reference.png'))
                d.undo_roi();self.assertEqual(len(d.rois),1)
                d.remove_roi();self.assertEqual(d.rois,[]);self.assertIsNotNone(d.asset)
            finally:
                w.close();self.app.processEvents()
