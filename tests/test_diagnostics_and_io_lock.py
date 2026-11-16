import copy,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_model import CameraSettings,node_id,CameraError
from camera_transaction import compare,apply_comparison,CameraWriteError
from test_camera import FakeCamera
from diagnostic_log import DiagnosticStore,redact


class TriggerLockedCamera(FakeCamera):
    def triggers_on(self):return any(self.values[node_id({'key':'TriggerMode','selectors':{'TriggerSelector':s}})]=='On' for s in ('FrameBurstStart','LineStart'))
    def read(self,key,kind):
        cap=super().read(key,kind)
        if key=='LineMode' and self.triggers_on():cap.update(writable=False,choices=[cap['value']])
        return cap
    def write(self,key,kind,value):
        if key=='LineMode' and self.triggers_on():raise CameraError('TEST: trigger still locks IO')
        return super().write(key,kind,value)


class TriggerLockTests(unittest.TestCase):
    def test_locked_io_is_deferred_then_both_triggers_off_before_line_mode(self):
        camera=TriggerLockedCamera();preview=compare(camera,CameraSettings())
        self.assertTrue(preview['ready'],preview['errors'])
        row=next(r for r in preview['rows'] if r['entry']['key']=='LineMode' and r['entry']['selectors'].get('LineSelector')=='Line0')
        self.assertEqual(row['status'],'依赖模式切换后校验');self.assertIn('关闭帧/行触发',row['detail'])
        result=apply_comparison(camera,preview);self.assertEqual(result['status'],'passed')
        mode=next(i for i,(key,_,_) in enumerate(camera.writes) if key=='LineMode')
        off={c['TriggerSelector'] for key,value,c in camera.writes[:mode] if key=='TriggerMode' and value=='Off'}
        self.assertEqual(off,{'FrameBurstStart','LineStart'})
        self.assertTrue(camera.triggers_on());self.assertEqual(camera.commands,['UserSetSave','UserSetLoad'])

    def test_failure_before_save_restores_io_before_original_triggers(self):
        camera=TriggerLockedCamera();preview=compare(camera,CameraSettings());before=copy.deepcopy(camera.values)
        camera.fail_key='Gain'
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,preview)
        self.assertFalse(camera.commands);self.assertEqual(camera.values,before)
        self.assertTrue(any('切换模式前不可读' in e for e in raised.exception.report['rollback_errors']))

    def test_permanently_readonly_line_is_not_forced_or_saved(self):
        camera=TriggerLockedCamera();original=camera.read
        def fixed(key,kind):
            cap=original(key,kind)
            if key=='LineMode':cap['writable']=False
            return cap
        camera.read=fixed;preview=compare(camera,CameraSettings())
        with self.assertRaises(CameraWriteError) as raised:apply_comparison(camera,preview)
        self.assertIn('LineSelector=Line0',str(raised.exception));self.assertIn('只读',str(raised.exception))
        self.assertFalse(any(k=='LineMode' for k,_,_ in camera.writes));self.assertFalse(camera.commands)

    def test_external_io_change_after_preview_is_rejected(self):
        camera=TriggerLockedCamera();preview=compare(camera,CameraSettings())
        camera.values[node_id({'key':'LineMode','selectors':{'LineSelector':'Line0'}})]='Output'
        with self.assertRaisesRegex(CameraError,'对比后已被修改'):apply_comparison(camera,preview)
        self.assertFalse(any(k=='LineMode' for k,_,_ in camera.writes));self.assertFalse(camera.commands)


class DiagnosticsTests(unittest.TestCase):
    def test_logs_snapshots_and_bundle_mask_credentials_and_preserve_context(self):
        secret='SYNTHETIC'+'-ONLY-12345'
        with tempfile.TemporaryDirectory() as folder:
            store=DiagnosticStore(Path(folder)/'logs')
            try:
                data={'password':secret,'nested':{'api_key':secret},'text':'token='+secret,'LineSelector':'Line0','LineMode':'Input'}
                store.event('test','failure',**data);path=store.snapshot('test',data)
                result=json.loads(path.read_text(encoding='utf-8'));self.assertEqual(result['data']['password'],'<redacted>')
                self.assertNotIn(secret,store.tail());self.assertEqual(result['data']['LineSelector'],'Line0')
                bundle=store.export(Path(folder)/'debug.zip')
                with zipfile.ZipFile(bundle) as archive:
                    self.assertIn('manifest.json',archive.namelist())
                    self.assertNotIn(secret,b'\n'.join(archive.read(n) for n in archive.namelist()).decode('utf-8'))
                self.assertEqual(redact('Bearer '+secret),'Bearer <redacted>')
                self.assertNotIn(secret,redact('password="'+secret+' with spaces"'))
                with self.assertRaises(FileExistsError):store.export(bundle)
            finally:store.handler.close();store.logger.removeHandler(store.handler)

    def test_global_error_snapshot_and_manual_capture_are_available_from_toolbox(self):
        from PySide6.QtWidgets import QApplication
        from toolbox import ToolboxWindow
        import diagnostic_log
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            store=DiagnosticStore(folder)
            try:
                with patch.object(diagnostic_log,'_store',store):
                    w=ToolboxWindow();w.show();w.select_page(3)
                    try:
                        w.camera.output_caps={'Line0':{'mode':{'status':'readable','value':'Input','choices':['Input'],'writable':False}}}
                        w.camera.refresh_output_choices()
                        self.assertGreaterEqual(w.camera.controls['output_mode'].findData('Output'),0)
                        self.assertGreaterEqual(w.camera.controls['output_mode'].findData('Strobe'),0)
                        w.camera.notify('TEST IO read only',True)
                        files=list(Path(folder).glob('snapshot-*.json'));self.assertTrue(files)
                        state=json.loads(files[-1].read_text(encoding='utf-8'))['data']['state']
                        self.assertEqual(state['page'],3);self.assertIn('settings',state['camera'])
                        w.open_diagnostics();w.diagnostic_dialog.capture();app.processEvents()
                        self.assertTrue(list(Path(folder).glob('snapshot-*.png')))
                        self.assertIn('已保存',w.diagnostic_dialog.status.text())
                    finally:w.close();app.processEvents()
            finally:store.handler.close();store.logger.removeHandler(store.handler)


if __name__=='__main__':unittest.main()
