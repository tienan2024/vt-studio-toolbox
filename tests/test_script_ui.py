from pathlib import Path
import sys
import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from toolbox import ToolboxWindow
from script_generator import default_config


class ScriptDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([]);cls.app.setStyle('Fusion')
        (ROOT/'verification').mkdir(exist_ok=True)

    def wait(self,p):
        deadline=time.monotonic()+25
        while p.is_busy() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        self.app.processEvents();self.assertFalse(p.is_busy(),p.message.text())

    def test_product_workflow_real_csharp_four_outputs_and_regression(self):
        w=ToolboxWindow();w.show();w.select_page(2);p=w.script;self.app.processEvents()
        try:
            self.assertTrue(w.script_nav.isChecked());self.assertEqual(w.pages.count(),4)
            p.tabs.setCurrentIndex(1);p.ai_result.setCurrentIndex(1);p.labels.setPlainText('污点，胶滴，接头')
            p.start_test('frame');self.assertTrue(p.is_busy());self.assertFalse(p.save_cs_button.isEnabled())
            # Closing during a compiler job must leave the window and worker alive.
            w.close();self.assertTrue(w.isVisible());self.wait(p)
            self.assertEqual(p.output_values.item(0,2).text(),'0|0|1|1|1')
            self.assertEqual(p.output_values.item(1,2).text(),'污点')
            self.assertIn('True',p.test_status.text());self.assertEqual(p.output_values.rowCount(),4)
            p.start_test('regression');self.wait(p);self.assertIn('18 / 18',p.test_status.text())
            for width,height,name in ((1440,900,'1440'),(1180,760,'1180')):
                w.resize(width,height);self.app.processEvents();p.test_scroll.verticalScrollBar().setValue(0);self.app.processEvents()
                self.assertTrue(w.grab().save(str(ROOT/f'verification/script_test_{name}.png')))
                self.assertLess(p.labels.geometry().bottom(),p.speed.parentWidget().geometry().height())
            p.tabs.setCurrentIndex(0);w.resize(1440,900);self.app.processEvents()
            w.grab().save(str(ROOT/'verification/script_config_1440.png'))
        finally:w.close();self.app.processEvents()

    def test_no_ai_custom_product_reorder_config_and_export(self):
        w=ToolboxWindow();w.show();w.select_page(2);p=w.script
        try:
            c=default_config();c['product']='无AI产品';c['use_ai']=False;c['types']=['折角','污点'];c['aliases']=[]
            c['signals']=[{'name':'折角Result','type':'折角'}];p.load_config(c)
            self.assertFalse(p.labels.isEnabled());self.assertIn('aiResult',p.sources['UserProperty.cs'])
            p.signal_values.cellWidget(0,1).setCurrentIndex(1);p.tabs.setCurrentIndex(1)
            p.start_test('frame');self.wait(p);self.assertEqual(p.output_values.item(0,2).text(),'0|1')
            self.assertIn('0 次',p.test_status.text())
            p.ngtype_text.setText(' 污点 - 折角 ');p.refresh()
            self.assertEqual(p.config['types'],['污点','折角'])
            self.assertEqual(p.output_values.item(0,2).text(),'等待测试')
            with tempfile.TemporaryDirectory() as folder:
                p.save_cs(str(Path(folder)/'UserScript.cs'))
                self.assertEqual([f.name for f in Path(folder).iterdir()],['UserScript.cs'])
            p.signals.item(0,0).setText('aiResult');self.assertIsNone(p.refresh());self.assertEqual(p.sources,{})
        finally:w.close();self.app.processEvents()
