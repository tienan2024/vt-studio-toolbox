from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from PySide6.QtWidgets import QApplication,QDialog
from sol_apply_ui import SolApplyDialog
from sol_apply import SolApplyError,discover_vm
from script_ui import ScriptPage
from script_generator import default_config
from test_sol_apply import module


class SolApplicationDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_review_shows_target_and_rejects_original_or_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'original.sol';path.write_bytes(b'TEST_ONLY')
            dialog=SolApplyDialog(str(path),module(),default_config())
            try:
                self.assertEqual(len(dialog.plan['preserved']),12);self.assertEqual(dialog.plan['module_id'],'9')
                with patch('sol_apply_ui.sdk_apps'):
                    dialog.output.setText(str(path));dialog.accept_valid()
                self.assertNotEqual(dialog.result(),QDialog.DialogCode.Accepted);self.assertIn('不能覆盖',dialog.error.text())
                self.assertEqual(path.read_bytes(),b'TEST_ONLY')
            finally:dialog.deleteLater();self.app.processEvents()

    def test_apply_failure_restores_controls_and_discards_transient_credential(self):
        p=ScriptPage();request={'password':'SIMULATED_CREDENTIAL'}
        try:
            def fail(**kwargs):time.sleep(.02);raise SolApplyError('SIMULATED SDK failure')
            with patch('sol_apply_ui.apply_script',side_effect=fail):
                p.start_sol_application(request);self.assertFalse(p.variables.isEnabled())
                end=time.monotonic()+5
                while p.is_busy() and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
            self.app.processEvents();self.assertFalse(p.is_busy());self.assertTrue(p.variables.isEnabled())
            self.assertIsNone(request['password']);self.assertIn('SIMULATED SDK failure',p.message.text())
            self.assertNotIn('SIMULATED_CREDENTIAL',p.message.text())
        finally:p.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
