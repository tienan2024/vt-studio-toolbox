import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QEvent
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtTest import QTest
from toolbox import ToolboxWindow


class StartupWindowTests(unittest.TestCase):
    def test_construction_and_page_changes_never_show_temporary_top_level_windows(self):
        app=QApplication.instance() or QApplication([]);shows=[]
        class Probe(QObject):
            def eventFilter(self,obj,event):
                if isinstance(obj,QWidget) and obj.isWindow() and event.type()==QEvent.Type.Show:shows.append(obj.metaObject().className())
                return False
        probe=Probe();app.installEventFilter(probe);w=None
        try:
            w=ToolboxWindow();self.assertEqual(shows,[])
            for _,cell,_ in w.camera.parameter_form.entries:self.assertIs(cell.parentWidget(),w.camera.parameter_form.widget)
            w.show()
            for page in (0,3,1,2):w.select_page(page);QTest.qWait(100)
            self.assertEqual(shows,['ToolboxWindow'])
        finally:
            app.removeEventFilter(probe)
            if w:w.close();app.processEvents()


if __name__=='__main__':unittest.main()
