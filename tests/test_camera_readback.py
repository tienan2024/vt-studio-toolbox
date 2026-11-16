import sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_model import CameraSettings,CameraError
from camera_sdk import Camera
from camera_transaction import compare,apply_comparison,CameraWriteError
from test_camera import FakeCamera


class CameraReadbackTests(unittest.TestCase):
    def test_sdk_cache_refresh_is_checked_and_old_wrappers_remain_supported(self):
        calls=[];handle=SimpleNamespace(MV_CC_InvalidateNodes=lambda:calls.append('invalidate') or 0)
        camera=Camera(handle,None,None,{})
        self.assertTrue(camera.invalidate_nodes());self.assertEqual(calls,['invalidate'])
        self.assertFalse(Camera(SimpleNamespace(),None,None,{}).invalidate_nodes())
        handle.MV_CC_InvalidateNodes=lambda:0x80000001
        with self.assertRaises(CameraError):camera.invalidate_nodes()

    def test_reload_reads_fresh_height_and_reports_both_phases(self):
        class CachedCamera(FakeCamera):
            stale=False;refreshes=0
            def read(self,key,kind):
                cap=super().read(key,kind)
                if key=='Height' and self.stale:cap['value']=480
                return cap
            def command(self,key):
                super().command(key)
                if key=='UserSetLoad':self.stale=True
            def invalidate_nodes(self):self.stale=False;self.refreshes+=1;return True
        camera=CachedCamera();report=apply_comparison(camera,compare(camera,CameraSettings()))
        self.assertEqual(camera.refreshes,4);self.assertEqual(report['status'],'passed')
        self.assertEqual([r['phase'] for r in report['readbacks']],['before_save','after_reload'])
        self.assertTrue(all(r['cache_invalidated'] and r['verified'] for r in report['readbacks']))

    def test_real_height_reset_after_reload_is_not_hidden_or_rewritten(self):
        class ResetCamera(FakeCamera):
            def command(self,key):
                super().command(key)
                if key=='UserSetLoad':self._set_plain('Height',480)
            def invalidate_nodes(self):return True
        camera=ResetCamera();preview=compare(camera,CameraSettings())
        with self.assertRaises(CameraWriteError) as caught:apply_comparison(camera,preview)
        report=caught.exception.report;reading=report['readbacks'][-1]
        height=next(r for r in reading['rows'] if r['node']['key']=='Height')
        self.assertEqual(reading['phase'],'after_reload');self.assertEqual(height['actual'],480)
        self.assertFalse(height['verified']);self.assertIn('目标 '+str(height['expected']),report['error'])
        self.assertIn('实际 480',report['error']);self.assertIn('重载UserSet1后',report['error'])
        self.assertTrue(report['persistent_may_have_changed']);self.assertFalse(report['runtime_restored'])
        self.assertEqual(camera.read('Height','int')['value'],480)


class CameraIORowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_two_row_presets_fit_io_grid_at_both_window_sizes_and_languages(self):
        from toolbox import ToolboxWindow
        from PySide6.QtTest import QTest
        w=ToolboxWindow();w.show();w.select_page(3);p=w.camera
        try:
            p.advanced_button.setChecked(True);p.form_tabs.setCurrentIndex(3)
            for width,height,language in ((1440,900,'zh'),(1180,760,'en')):
                w.resize(width,height);p.language_box.setCurrentIndex(p.language_box.findData(language));QTest.qWait(120)
                p.fit_metrics();self.app.processEvents()
                cell=p.io_table.cellWidget(0,0);choice,apply,save=p.page_preset_controls['io']
                self.assertGreaterEqual(p.io_table.rowHeight(0),cell.minimumSizeHint().height()+2)
                for button in (choice,apply,save,p.preset_rename_buttons['io']):
                    self.assertLess(button.mapTo(cell,button.rect().bottomRight()).y(),cell.height())
                    bottom=button.mapTo(p.io_table.viewport(),button.rect().bottomRight()).y()
                    self.assertLess(bottom,p.io_table.rowViewportPosition(1))
        finally:w.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
