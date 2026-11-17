import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_model import CameraSettings,node_id,config_dict
from camera_presets import CameraPresetStore,PAGE_KEYS
from camera_snapshot import read_snapshot,compare_presets,device_preset_metadata,DEVICE_FIELDS
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
        self.assertEqual(by['sensor_width']['status'],'未读取');self.assertNotIn('focal_length_mm',by)

    def test_site_inputs_and_automatic_targets_are_absent_from_device_comparison_rows(self):
        camera=FakeCamera();snapshot=read_snapshot(camera,camera.geometry())
        settings=config_dict(CameraSettings())
        settings.update(require_square=True,encoder_travel_mm_per_rev=400,cycle_travel_mm=600,
                        auto_frequency=True,height_override=0,width_override=0,centered_x=True)
        pages={page:{'slot':0,'values':{key:settings[key] for key in keys}} for page,keys in PAGE_KEYS.items()}
        before=copy.deepcopy(pages);rows=compare_presets(snapshot,pages)
        fields={r['field'] for r in rows}
        self.assertEqual(pages,before)
        self.assertTrue(fields<=DEVICE_FIELDS)
        self.assertTrue({'frame_line','line_source','encoder_line','gain','exposure_us'}<=fields)
        self.assertTrue(fields.isdisjoint({'encoder_travel_mm_per_rev','require_square','cycle_travel_mm','ppr',
                                          'height_override','width_override','offset_x','pre_divider','multiplier','post_divider'}))
        self.assertFalse(any(r['page']=='calibration' for r in rows))
        metadata=device_preset_metadata(pages,rows)
        self.assertEqual(pages,before)
        exported_values={key:value for page in metadata.values() for key,value in page['values'].items()}
        self.assertNotIn('require_square',exported_values);self.assertNotIn('encoder_travel_mm_per_rev',exported_values)
        self.assertNotIn('cycle_travel_mm',exported_values);self.assertNotIn('pre_divider',exported_values)
        self.assertEqual(exported_values['frame_selector'],'FrameBurstStart')
        self.assertEqual(exported_values['output0_line'],'Line0')
        self.assertEqual(metadata['calibration']['values'],{})
        unspecified=compare_presets(snapshot,{'io':{'slot':0,'values':{'input_format':''}}})
        self.assertFalse(any(r['field']=='input_format' for r in unspecified))
        # The generated/exported row data has no pseudo "device" item, even
        # when a preset belongs to another model or has not been read yet.
        for snapshot_value in (None,snapshot):
            calibration=compare_presets(snapshot_value,{'calibration':{'slot':0,'model':'OTHER CAMERA',
                'values':{'encoder_travel_mm_per_rev':400,'x_mm_per_px':0.1}}})
            self.assertEqual(calibration,[])

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

    def test_device_only_scope_is_shared_by_table_counts_and_export(self):
        from camera_ui import CameraPage
        with tempfile.TemporaryDirectory() as folder:
            store=CameraPresetStore(Path(folder)/'presets.json')
            with patch('camera_ui.CameraPresetStore',return_value=store):p=CameraPage()
            try:
                model=p.preset_model();camera=FakeCamera();camera.device['model']=model
                p.snapshot=read_snapshot(camera,camera.geometry());p.last_report=p.snapshot;p.result_tabs.setCurrentIndex(1)
                p.diff_scope.setCurrentIndex(1);p.refresh_preset_comparison()
                rows=p.preset_comparison_report['rows']
                expected=sum(r['status'] in ('不同','预设超范围','预设机型不匹配') for r in rows)
                self.assertIn(str(expected)+' 项差异',p.diff_summary.text())
                self.assertEqual(p.preset_table.rowCount(),len(rows))
                self.assertTrue(all(r['field'] in DEVICE_FIELDS for r in rows))
                p.diff_only.setChecked(True)
                self.assertEqual(p.preset_table.rowCount(),sum(r['status']!='一致' for r in rows))
                p.diff_scope.setCurrentIndex(0);p.form_tabs.setCurrentIndex(4)
                self.assertEqual(p.preset_table.rowCount(),0)
                self.assertIn('本页无可对比的相机参数',p.diff_summary.text())
                output=Path(folder)/'device-comparison.json'
                with patch('camera_ui.QFileDialog.getSaveFileName',return_value=(str(output),'')):p.export_report()
                exported=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(exported['rows'],rows)
                self.assertEqual(exported['selected_presets']['calibration']['values'],{})
                self.assertNotIn('require_square',exported['selected_presets']['imaging']['values'])
            finally:p.close();self.app.processEvents()

    def test_read_preserves_draft_locks_and_preset_selection_and_exposes_workflow(self):
        from toolbox import ToolboxWindow
        from PySide6.QtTest import QTest
        with tempfile.TemporaryDirectory() as folder:
            w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;p.preset_store=CameraPresetStore(Path(folder)/'p.json')
            try:
                p.controls['gain'].setValue(7);p.lock_buttons['working_distance_mm'].click();p.recalculate()
                p.page_preset_controls['trigger'][0].setCurrentIndex(1)
                original=config_dict(p.settings(validate=False));locks=dict(p.fixed_values);presets=copy.deepcopy(p.preset_store.data)
                camera=FakeCamera();camera.device['model']=original['camera_model_id']
                geometry=camera.geometry();geometry['sensor_width']=original['sensor_width']
                camera.geometry=lambda:copy.deepcopy(geometry)
                p.device.addItem('SIMULATED CAMERA',camera.device['uid']);p.device.setCurrentIndex(1)
                with patch('camera_transaction.open_camera') as opened:
                    opened.return_value.__enter__.return_value=camera;data=inspect_camera(camera.device['uid'])
                p.finished_result('inspect',data);p.update_actions();QTest.qWait(220)
                self.assertEqual(config_dict(p.settings(validate=False)),original);self.assertEqual(p.fixed_values,locks)
                self.assertEqual(p.preset_store.data,presets);self.assertEqual(p.page_preset_controls['trigger'][0].currentIndex(),1)
                self.assertEqual(p.result_tabs.currentIndex(),1);self.assertFalse(p.device_actions.isHidden())
                self.assertFalse(p.write_button.isEnabled());self.assertIn(camera.device['model'],p.device_status.text())
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
