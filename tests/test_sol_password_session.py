import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from PySide6.QtWidgets import QApplication,QDialog
from script_ui import ScriptPage
from sol_apply_ui import SolApplyDialog
from sol_reader import SolPasswordError
from script_generator import default_config
from test_sol_apply import module


class SolPasswordSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):self.p=ScriptPage();self.secret='SYNTHETIC_SESSION_ONLY'
    def tearDown(self):self.p.variables.clear_session_password();self.p.deleteLater();self.app.processEvents()
    def metadata(self,path):return {'path':str(path),'scripts':[dict(module(),flow_id='1')]}
    def drain(self):
        deadline=time.monotonic()+5
        while self.p.is_busy() and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.app.processEvents();self.assertFalse(self.p.is_busy())

    def test_successful_read_reuses_password_without_exporting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'protected.sol';metadata=self.metadata(path);calls=[]
            def read(target,password):
                calls.append(password)
                if password!=self.secret:raise SolPasswordError('TEST password needed')
                return metadata
            with patch('script_variables.read_sol',side_effect=read),patch('script_variables.QInputDialog.getText',return_value=(self.secret,True)) as prompt:
                self.p.variables.start_read(str(path));self.drain()
                self.p.variables.start_read(str(path));self.drain()
            self.assertEqual(calls,[None,self.secret,self.secret]);self.assertEqual(prompt.call_count,1)
            self.assertEqual(self.p.variables.session_password(str(path)),self.secret)
            self.assertNotIn(self.secret,json.dumps(self.p.variables.metadata))
            self.assertNotIn(self.secret,self.p.variables.status.text())

    def test_review_prefills_masked_password_and_cancel_clears_dialog(self):
        metadata=self.metadata('first.sol');self.p.variables.set_metadata(metadata)
        self.p.variables.remember_password('first.sol',self.secret);dialogs=[]
        def review(*args,**kwargs):
            with patch('sol_apply_ui.discover_vm',return_value=''):dialog=SolApplyDialog(*args,**kwargs)
            dialogs.append(dialog)
            def cancel():
                self.assertEqual(dialog.password.text(),self.secret)
                self.assertEqual(dialog.password.echoMode(),dialog.password.EchoMode.Password)
                return QDialog.DialogCode.Rejected
            dialog.exec=cancel;return dialog
        with patch('script_ui.SolApplyDialog',side_effect=review):self.p.review_sol_application(metadata['scripts'][0])
        self.assertEqual(dialogs[0].password.text(),'')
        self.assertEqual(self.p.variables.session_password('first.sol'),self.secret)

    def test_successful_application_keeps_password_for_next_verified_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source=str(Path(folder)/'first.sol');output=str(Path(folder)/'second.sol')
            self.p.variables.set_metadata(self.metadata(source));self.p.variables.remember_password(source,self.secret)
            request={'path':source,'password':self.secret}
            result={'output':output,'module_id':'9','metadata':self.metadata(output)}
            with patch('sol_apply_ui.apply_script',return_value=result):self.p.start_sol_application(request);self.drain()
            self.assertIsNone(request['password']);self.assertIsNone(self.p._apply_password)
            self.assertEqual(self.p.variables.session_password(output),self.secret)
            self.assertIsNone(self.p.variables.session_password(source))
            self.p.variables.set_metadata(self.metadata(str(Path(folder)/'unrelated.sol')))
            self.assertIsNone(self.p.variables.session_password())

    def test_failed_apply_discards_candidate_but_keeps_verified_session(self):
        self.p.variables.set_metadata(self.metadata('first.sol'));self.p.variables.remember_password('first.sol',self.secret)
        request={'password':'SYNTHETIC_BAD_CANDIDATE'}
        with patch('sol_apply_ui.apply_script',side_effect=RuntimeError('TEST compile failure')):
            self.p.start_sol_application(request);self.drain()
        self.assertIsNone(request['password']);self.assertIsNone(self.p._apply_password)
        self.assertEqual(self.p.variables.session_password('first.sol'),self.secret)

    def test_toolbox_close_clears_password_even_when_widget_remains_alive(self):
        from toolbox import ToolboxWindow
        window=ToolboxWindow()
        try:
            window.script.variables.remember_password('first.sol',self.secret)
            window.close();self.app.processEvents()
            self.assertIsNone(window.script.variables.session_password('first.sol'))
        finally:window.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
