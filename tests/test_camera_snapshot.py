import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_model import CameraSettings,node_id,config_dict
from camera_presets import CameraPresetStore
from camera_snapshot import read_snapshot,compare_presets
from camera_transaction import inspect_camera,compare,apply_comparison
from test_camera import FakeCamera
from camera_sdk import NodeUnavailable


class CameraSnapshotTests(unittest.TestCase):
    def test_selector_banks_are_separate_and_reading_changes_no_configuration(self):
        camera=FakeCamera();before=copy.deepcopy(camera.values);bank=copy.deepcopy(camera.selectors)
        snapshot=read_snapshot(camera,camera.geometry())
        actual={node_id(r['entry']):r for r in snapshot['rows']}
        for selector,expected in (('FrameBurstStart','Line3'),('LineStart','FrequencyConverter')):
            self.assertEqual(actual[node_id({'key':'TriggerSource','selectors':{'TriggerSelector':selector}})]['value'],expected)
        self.assertEqual(camera.values,before);self.assertEqual(camera.selectors,bank)
        self.assertTrue(all(k in bank for k,_,_ in camera.writes))
        inaccessible=actual[node_id({'key':'LineSource','selectors':{'LineSelector':'Line0'}})]
        self.assertEqual(inaccessible['status'],'当前条件不可读');self.assertIsNone(inaccessible['value'])

    def test_raw_preset_comparison_needs_no_material_or_cycle_calculation(self):
        camera=FakeCamera();snapshot=read_snapshot(camera,camera.geometry())
        pages={'trigger':{'slot':1,'values':{'frame_selector':'FrameBurstStart','frame_line':'Line2','line_source':'FrequencyConverter'}}}
        rows=compare_presets(snapshot,pages);by={r['field']:r for r in rows}
        self.assertEqual((by['frame_line']['before'],by['frame_line']['value'],by['frame_line']['status']),('Line3','Line2','不同'))
        self.assertEqual(by['line_source']['status'],'一致');self.assertEqual(by['encoder_line']['status'],'预设未设置')
        self.assertNotIn('cycle_travel_mm',str(pages));self.assertEqual(rows[0]['slot'],1)
        missing=compare_presets(snapshot,{'trigger':{'slot':0,'values':{'frame_line':'Line2'}}})
        self.assertEqual(next(r for r in missing if r['field']=='frame_line')['status'],'预设未设置')
        intrinsic=compare_presets(None,{'material':{'slot':0,'values':{'sensor_width':2048,'focal_length_mm':12}}})
        by={r['field']:r for r in intrinsic}
        self.assertEqual(by['sensor_width']['status'],'未读取');self.assertEqual(by['focal_length_mm']['status'],'工位计算项')

    def test_unreadable_unsupported_and_out_of_range_are_never_marked_equal(self):
        camera=FakeCamera();snapshot=read_snapshot(camera,camera.geometry())
        rows=compare_presets(snapshot,{'io':{'slot':0,'values':{'output0_enabled':True,'output0_line':'Line0','output0_source':'ExposureStartActive'}}})
        self.assertEqual(next(r for r in rows if r['field']=='output0_source')['status'],'当前条件不可读')
        rows=compare_presets(snapshot,{'imaging':{'slot':0,'values':{'gain':-10,'pixel_format':'NOT_SUPPORTED'}}})
        self.assertTrue(all(r['status']=='预设超范围' for r in rows if r['field'] in ('gain','pixel_format')))
        rows=compare_presets(snapshot,{'imaging':{'slot':0,'values':{'preamp_gain':'gain_1400x'}}})
        self.assertEqual(next(r for r in rows if r['field']=='preamp_gain')['status'],'设备不支持')
        read=camera.read
        def unavailable_selector(key,kind):
            if key=='TriggerSelector':raise NodeUnavailable(key,1)
            return read(key,kind)
        with patch.object(camera,'read',side_effect=unavailable_selector):partial=read_snapshot(camera,camera.geometry())
        rows=compare_presets(partial,{'trigger':{'slot':0,'values':{'frame_selector':'FrameBurstStart','frame_line':'Line3'}}})
        self.assertEqual(next(r for r in rows if r['field']=='frame_line')['status'],'当前条件不可读')


class CameraSnapshotDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_read_preserves_draft_locks_and_preset_selection_and_exposes_workflow(self):
        from toolbox import ToolboxWindow
        from PySide6.QtTest import QTest
        with tempfile.TemporaryDirectory() as folder:
            w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;p.preset_store=CameraPresetStore(Path(folder)/'p.json')
            try:
                p.controls['gain'].setValue(7);p.lock_buttons['working_distance_mm'].click();p.recalculate()
                p.page_preset_controls['trigger'][0].setCurrentIndex(1)
                original=config_dict(p.settings(validate=False));locks=dict(p.fixed_values);presets=copy.deepcopy(p.preset_store.data)
                camera=FakeCamera();p.device.addItem('SIMULATED CAMERA',camera.device['uid']);p.device.setCurrentIndex(1)
                with patch('camera_transaction.open_camera') as opened:
                    opened.return_value.__enter__.return_value=camera;data=inspect_camera(camera.device['uid'])
                p.finished_result('inspect',data);p.update_actions();QTest.qWait(220)
                self.assertEqual(config_dict(p.settings(validate=False)),original);self.assertEqual(p.fixed_values,locks)
                self.assertEqual(p.preset_store.data,presets);self.assertEqual(p.page_preset_controls['trigger'][0].currentIndex(),1)
                self.assertEqual(p.result_tabs.currentIndex(),1);self.assertFalse(p.device_actions.isHidden())
                self.assertFalse(p.write_button.isEnabled());self.assertIn('SIMULATED CAMERA',p.device_status.text())
                p.load_settings(CameraSettings());preview=compare(camera,p.settings());self.assertTrue(preview['ready'])
                p.finished_result('compare',preview);p.update_actions()
                self.assertEqual(p.result_tabs.currentIndex(),2);self.assertTrue(p.write_button.isEnabled())
                p.controls['gain'].setValue(4);self.assertFalse(p.write_button.isEnabled());self.assertEqual(p.compare_table.rowCount(),0)
                p.recalculate();preview=compare(camera,p.settings());p.finished_result('compare',preview);p.update_actions()
                with patch.object(p,'launch') as launch:p.start_write();launch.assert_called_once_with('write',preview)
                report=apply_comparison(camera,preview);self.assertEqual(report['status'],'passed')
                self.assertEqual(camera.commands,['UserSetSave','UserSetLoad'])
                self.assertEqual(camera.read('UserSetDefault','enum')['value'],'UserSet1')
            finally:w.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
