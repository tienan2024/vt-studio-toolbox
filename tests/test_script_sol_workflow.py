import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication
from toolbox import ToolboxWindow
from test_sol_reader import fixture


class SolMainWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.w=ToolboxWindow();self.w.resize(1180,720);self.w.show();self.w.select_page(2);self.p=self.w.script
        for _ in range(6):self.app.processEvents()

    def tearDown(self):self.w.close();self.app.processEvents()

    def test_sol_actions_are_outside_tabs_and_empty_target_cannot_apply(self):
        p=self.p;v=p.variables
        self.assertFalse(v.isAncestorOf(v.open_button))
        for tab in range(p.tabs.count()):
            p.tabs.setCurrentIndex(tab);self.app.processEvents()
            self.assertTrue(v.open_button.isVisible());self.assertTrue(v.write_button.isVisible());self.assertTrue(v.selectors.isVisible())
            self.assertFalse(v.write_button.isEnabled())
        p.review_sol_application(None);self.assertIn('请先打开 SOL',p.message.text())

    def test_read_and_apply_target_do_not_require_variable_reference_tab(self):
        p=self.p;v=p.variables
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'TEST_ONLY.sol';fixture(path);before=path.read_bytes()
            p.tabs.setCurrentIndex(0)
            with patch('script_variables.QFileDialog.getOpenFileName',return_value=(str(path),'')):
                v.open_button.click()
            self.assertFalse(v.open_button.isEnabled());self.assertFalse(v.write_button.isEnabled())
            deadline=time.monotonic()+5
            while p.is_busy() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
            self.app.processEvents();self.assertFalse(p.is_busy());self.assertEqual(p.tabs.currentIndex(),0)
            self.assertEqual(v.path_display.text(),str(path));self.assertEqual(v.selected_module()['id'],'9')
            v.source.setCurrentIndex(0);self.app.processEvents()
            self.assertTrue(v.write_button.isEnabled());self.assertTrue(v.selectors.isVisible())
            with patch('script_ui.SolApplyDialog') as dialog:
                dialog.return_value.exec.return_value=False;v.write_button.click()
                self.assertEqual(dialog.call_count,1);self.assertEqual(dialog.call_args.args[0],str(path))
                self.assertEqual(dialog.call_args.args[1]['id'],'9')
            self.assertEqual(path.read_bytes(),before)
