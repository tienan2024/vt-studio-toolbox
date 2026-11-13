"""Focused regressions for annotation deletion, tall images and preview focus."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import CanvasArea
from toolbox import ToolboxWindow


class CanvasEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        ok, ng = root/'OK.bmp', root/'NG.bmp'
        Image.new('L', (400, 900), 190).save(ok)
        image = Image.new('L', (400, 900), 190)
        ImageDraw.Draw(image).ellipse((80, 100, 110, 130), fill=30)
        image.save(ng)
        self.window = ToolboxWindow()
        self.window.resize(1280, 800)
        self.window.show()
        self.window.select_page(1)
        self.d = self.window.defect
        self.d.add_ok([str(ok)])
        self.d.load_ng(str(ng))
        self.d.set_asset([(70, 90), (120, 90), (120, 140), (70, 140)])
        for _ in range(8):
            self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def delete_at(self, canvas, point, text):
        point = canvas.mapFromScene(QPointF(*point))
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.RightButton, pos=point)
        self.app.processEvents()
        menu = QApplication.activePopupWidget()
        self.assertIsInstance(menu, QMenu)
        action = next(a for a in menu.actions() if a.text() == text)
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        self.app.processEvents()

    def test_delete_individual_overlapping_annotations_and_persist_recipe(self):
        d = self.d
        d._set_roi_from_points([(20, 40), (180, 40), (180, 240), (20, 240)], (400, 900), 'NG 框选')
        d._set_roi_from_points([(50, 60), (220, 60), (220, 260), (50, 260)], (400, 900), 'NG 框选')
        d.tabs.setCurrentIndex(0)
        self.app.processEvents()
        asset = d.asset
        self.delete_at(d.ok_canvas, (100, 110), '删除生成范围 1')
        self.assertEqual(len(d.roi_regions()), 1)
        self.assertIs(d.asset, asset)
        recipe = Path(self.temp.name)/'recipe.json'
        d.save_recipe_to(recipe)
        d.apply_recipe(str(recipe))
        self.assertEqual(len(d.roi_regions()), 1)
        d.tabs.setCurrentIndex(1)
        d.ng_mode_picker.setCurrentIndex(d.ng_mode_picker.findData('roi'))
        self.app.processEvents()
        self.delete_at(d.ng_canvas, (100, 110), '删除缺陷轮廓')
        self.assertIsNone(d.asset)
        self.assertEqual(len(d.roi_regions()), 1)
        self.assertIsNone(d.ng_documents[d.current_ng_index].asset)
        self.assertEqual(d.ng_documents[d.current_ng_index].rois, tuple(d.rois))
        self.delete_at(d.ng_canvas, (60, 70), '删除生成范围 1')
        self.assertEqual(d.roi_regions(), [])
        self.assertEqual(d.roi, (0., 0., 1., 1.))
        self.assertFalse(any(b.text() == '撤销上一框' for b in d.findChildren(QPushButton)))

    def test_tall_canvas_and_right_drag_polygon_finish(self):
        d = self.d
        canvas = d.ng_canvas
        area = next(a for a in d.findChildren(CanvasArea) if a.canvas == canvas)
        self.assertGreater(canvas.height(), area.viewport().height())
        self.assertGreater(area.verticalScrollBar().maximum(), 0)
        self.assertAlmostEqual(canvas.height()/canvas.width(), 900/400, delta=.08)
        self.assertEqual(canvas.image.size, (400, 900))
        area.verticalScrollBar().setValue(80)
        canvas.set_mode('polygon')
        canvas.draft = [(50, 50), (100, 50), (90, 80)]
        start = canvas.mapFromScene(QPointF(60, 60))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.RightButton, pos=start)
        QTest.mouseMove(canvas.viewport(), start + QPointF(45, 45).toPoint(), 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.RightButton, pos=start + QPointF(45, 45).toPoint())
        self.assertEqual(len(canvas.draft), 3)
        self.assertLess(area.verticalScrollBar().value(), 80)
        self.assertIsNone(QApplication.activePopupWidget())
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.RightButton, pos=start)
        self.assertEqual(canvas.draft, [])
        self.assertIsNone(QApplication.activePopupWidget())
        canvas.set_empty('导入图像')
        for _ in range(5):self.app.processEvents()
        self.assertEqual(canvas.minimumHeight(), 180)
        self.assertEqual(area.verticalScrollBar().maximum(), 0)

    def test_preview_keeps_focus_in_defect_tool(self):
        d = self.d
        d.preview_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        d.preview()
        self.app.processEvents()
        focus = QApplication.focusWidget()
        self.assertTrue(focus is d or (focus is not None and d.isAncestorOf(focus)))
        deadline = time.monotonic()+20
        while d.is_busy() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(d.is_busy())
        self.assertIsNotNone(d.preview_result)
        self.assertFalse(self.window.convert_nav.hasFocus())
        self.assertTrue(d.preview_btn.hasFocus())


if __name__ == '__main__':
    unittest.main()
