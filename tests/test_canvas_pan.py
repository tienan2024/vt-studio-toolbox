from pathlib import Path
import sys
import unittest

from PIL import Image
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Canvas


class CanvasRightPanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas=Canvas('TEST_ONLY')
        self.canvas.resize(500,400);self.canvas.show()
        self.canvas.set_image(Image.new('L',(1200,1000),180))
        self.app.processEvents()
        self.canvas.resetTransform();self.canvas.scale(1.5,1.5)
        self.canvas.centerOn(600,500);self.canvas.auto_fit=False
        self.events=[]
        self.canvas.selection_changed.connect(self.events.append)

    def tearDown(self):
        self.canvas.close();self.app.processEvents()

    def test_right_drag_pans_in_all_selection_modes_without_changing_selection(self):
        for mode in ('view','rectangle','polygon','roi'):
            with self.subTest(mode=mode):
                self.canvas.set_mode(mode)
                points=[(500,400),(700,400),(700,600),(500,600)]
                self.canvas.set_selection(points)
                before=(self.canvas.horizontalScrollBar().value(),self.canvas.verticalScrollBar().value())
                start=QPoint(240,190);end=QPoint(300,230)
                QTest.mousePress(self.canvas.viewport(),Qt.MouseButton.RightButton,pos=start)
                QTest.mouseMove(self.canvas.viewport(),end,20)
                QTest.mouseRelease(self.canvas.viewport(),Qt.MouseButton.RightButton,pos=end)
                after=(self.canvas.horizontalScrollBar().value(),self.canvas.verticalScrollBar().value())
                self.assertEqual(after,(before[0]-60,before[1]-40))
                self.assertEqual(self.canvas.points,points)
        self.assertEqual(self.events,[])

    def test_polygon_right_click_finishes_and_drag_preserves_draft(self):
        self.canvas.set_mode('polygon')
        draft=[(500,400),(700,400),(600,600)]
        self.canvas.draft=list(draft)
        QTest.mousePress(self.canvas.viewport(),Qt.MouseButton.RightButton,pos=QPoint(220,180))
        QTest.mouseMove(self.canvas.viewport(),QPoint(280,220),20)
        QTest.mouseRelease(self.canvas.viewport(),Qt.MouseButton.RightButton,pos=QPoint(280,220))
        self.assertEqual(self.canvas.draft,draft)
        self.assertEqual(self.events,[])
        QTest.mouseClick(self.canvas.viewport(),Qt.MouseButton.RightButton,pos=QPoint(220,180))
        self.assertEqual(self.events,[draft])
        self.assertEqual(self.canvas.draft,[])

    def test_middle_button_no_longer_performs_canvas_pan(self):
        self.canvas.set_mode('rectangle')
        before=(self.canvas.horizontalScrollBar().value(),self.canvas.verticalScrollBar().value())
        QTest.mousePress(self.canvas.viewport(),Qt.MouseButton.MiddleButton,pos=QPoint(220,180))
        QTest.mouseMove(self.canvas.viewport(),QPoint(280,220),20)
        QTest.mouseRelease(self.canvas.viewport(),Qt.MouseButton.MiddleButton,pos=QPoint(280,220))
        self.assertEqual(before,(self.canvas.horizontalScrollBar().value(),self.canvas.verticalScrollBar().value()))
        self.assertEqual(self.events,[])


if __name__=='__main__':
    unittest.main(verbosity=2)
