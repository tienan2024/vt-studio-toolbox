import sys,tempfile,unittest,json,copy
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_presets import CameraPresetStore,PAGE_KEYS,defaults,model_key,SCHEMA
from camera_options import PRESETS
from camera_model import CameraError
from camera_snapshot import read_snapshot,compare_presets
from camera_model import CameraSettings,workflow_settings,calculate,config_dict,settings_from_dict,import_mfs_text
from camera_transaction import compare,read_trigger_ios
from test_camera import FakeCamera


class PresetAndSourceTests(unittest.TestCase):
    def test_reference_slots_are_independent_and_saved_per_page(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presets.json';store=CameraPresetStore(path)
            model='MV-CL024-91GC';self.assertFalse(path.exists())
            for preset in PRESETS.values():
                pages=defaults(preset['model']);self.assertEqual(set(pages),set(PAGE_KEYS))
                for slots in pages.values():
                    self.assertEqual(slots[0]['values'],slots[1]['values']);self.assertEqual(len(slots),2)
                self.assertEqual(pages['material'][0]['values']['sensor_width'],preset['sensor_width'])
                if preset['model']!='MV-CL042-91GM':
                    image=pages['imaging'][0]['values']
                    self.assertEqual((image['width_override'],image['offset_x'],image['gain'],image['preamp_gain']),(0,0,0,''))
                    self.assertEqual(image['pixel_format'],'' if preset['color'] else 'Mono8')
            s=replace(workflow_settings(),frame_line='Line2',line_source='Software',gain=7)
            store.save('trigger',1,s,model);store.rename('trigger',1,model,'高速工位');loaded=CameraPresetStore(path)
            self.assertEqual(loaded.values('trigger',1,model)['line_source'],'Software')
            self.assertEqual(loaded.name('trigger',1,model),'高速工位')
            self.assertEqual(loaded.values('trigger',0,model)['line_source'],'FrequencyConverter')
            self.assertEqual(loaded.values('trigger',1,'MV-CL042-91GM')['line_source'],'FrequencyConverter')
            self.assertNotIn('gain',loaded.values('trigger',1,model));self.assertNotIn('cycle_travel_mm',loaded.values('encoder',0,model))

    def test_legacy_presets_are_archived_not_assigned_to_024(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presets.json'
            pages={p:[s['values'] for s in slots] for p,slots in defaults('MV-CL042-91GM').items()}
            original=json.dumps({'schema':'vt-camera-page-presets/1','pages':pages}).encode()
            path.write_bytes(original);store=CameraPresetStore(path)
            self.assertEqual(store.legacy_pages,pages);self.assertTrue(store.load_notice)
            self.assertEqual(store.values('imaging',0,'MV-CL024-91GM')['gain'],0)
            self.assertEqual(path.read_bytes(),original)
            store.rename('imaging',1,'MV-CL024-91GM','夜班配置')
            backups=list(path.parent.glob('*.legacy-*.json'));self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_bytes(),original)
            raw=json.loads(path.read_text(encoding='utf-8'));self.assertEqual(raw['schema'],SCHEMA)
            self.assertEqual(raw['legacy_pages'],pages)
            self.assertEqual(CameraPresetStore(path).name('imaging',1,'MV-CL024-91GM'),'夜班配置')

    def test_foreign_model_and_invalid_roi_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CameraPresetStore(Path(folder)/'p.json');s=workflow_settings()
            with self.assertRaises(CameraError):store.save('material',0,s,'MV-CL042-91GM')
            with self.assertRaises(CameraError):store.save('imaging',0,replace(s,width_override=3296,offset_x=500),s.camera_model_id)
            self.assertFalse(store.path.exists())
            camera=FakeCamera();camera.device['model']='MV-CL024-91GM';snapshot=read_snapshot(camera,camera.geometry())
            rows=compare_presets(snapshot,{'imaging':{'slot':0,'model':'MV-CL042-91GM','values':{'gain':2.9079}}})
            self.assertTrue(all(r['status']=='预设机型不匹配' for r in rows))

    def test_alternate_source_is_written_and_frequency_math_is_not_claimed(self):
        s=replace(CameraSettings(),auto_frequency=True,line_source='Software')
        p=calculate(s);self.assertFalse(p['blocking']);m=p['metrics']
        self.assertIsNone(m['line_triggers_per_cycle']);self.assertIsNone(m['frequency_solution'])
        self.assertIsNone(m['actual_y_mm_per_px'])
        self.assertFalse({'PreDivider','EncoderSourceA'} & {n['key'] for n in p['nodes']})
        self.assertEqual(next(n['value'] for n in p['nodes'] if n['key']=='TriggerSource' and n['selectors'].get('TriggerSelector')=='LineStart'),'Software')
        self.assertEqual(settings_from_dict(config_dict(s)),s)
        c=FakeCamera(s);self.assertTrue(compare(c,s)['ready'])
        self.assertIn('Software',read_trigger_ios(c,True)['line_source'])

    def test_mfs_preserves_line_source_and_old_configs_default_to_converter(self):
        s,_=import_mfs_text('TriggerSelector\tLineStart\nTriggerSource\tSoftware\nTriggerActivation\tRisingEdge\n')
        self.assertEqual(s.line_source,'Software');self.assertEqual(s.line_edge,'RisingEdge')
        old=config_dict(CameraSettings());old.pop('line_source')
        self.assertEqual(settings_from_dict(old).line_source,'FrequencyConverter')


class PresetDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_explicit_apply_and_scoped_persistence(self):
        from toolbox import ToolboxWindow
        with tempfile.TemporaryDirectory() as folder:
            w=ToolboxWindow();w.show();w.select_page(3);p=w.camera;p.preset_store=CameraPresetStore(Path(folder)/'p.json')
            try:
                self.assertEqual(len(p.page_preset_controls),6)
                p.controls['gain'].setValue(6);p.controls['cycle_travel_mm'].setValue(450)
                p.controls['frame_line'].setCurrentIndex(p.controls['frame_line'].findData('Line2'));p.recalculate()
                choice,apply,save=p.page_preset_controls['trigger'];choice.setCurrentIndex(1)
                self.assertEqual(p.settings().frame_line,'Line2')
                save.click();p.controls['frame_line'].setCurrentIndex(p.controls['frame_line'].findData('Line4'));p.recalculate();apply.click()
                self.assertEqual(p.settings().frame_line,'Line2');self.assertEqual(p.settings().gain,6)
                p.line_trigger_source.setCurrentIndex(p.line_trigger_source.findData('Software'));p.recalculate()
                self.assertIsNotNone(p.plan,p.message.text());self.assertEqual(p.metrics.item(5,1).text(),'不使用')
                apply.click();self.assertEqual(p.settings().line_source,'FrequencyConverter')
                p.apply_page_preset('encoder')
                self.assertEqual((p.settings().auto_frequency,p.settings().multiplier,p.settings().height_override),(True,4,0))
                self.assertEqual(p.settings().cycle_travel_mm,450)
                p.apply_page_preset('material');p.apply_page_preset('imaging')
                self.assertEqual(p.settings().camera_model_id,'MV-CL024-91GC')
                self.assertEqual((p.settings().width_override,p.settings().offset_x,p.settings().gain),(0,0,0))
                self.assertEqual(p.settings().cycle_travel_mm,450)
            finally:w.close();self.app.processEvents()

    def test_connected_models_switch_names_saved_values_and_comparison_together(self):
        from toolbox import ToolboxWindow
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            w=ToolboxWindow();p=w.camera;p.preset_store=CameraPresetStore(Path(folder)/'p.json')
            try:
                devices=[{'uid':'test:024','model':'MV-CL024-91GM','serial':'TEST','transport':'GigE'},
                         {'uid':'test:042','model':'MV-CL042-91GM','serial':'TEST','transport':'GigE'}]
                p.finished_result('scan',{'sdk_version':'TEST','devices':devices})
                choice,apply,save=p.page_preset_controls['imaging'];choice.setCurrentIndex(1)
                self.assertIn('MV-CL024-91GM',choice.currentText())
                p.controls['gain'].setValue(6);p.recalculate();apply.click();self.assertEqual(p.settings().gain,0)
                p.controls['exposure_us'].setValue(23);p.recalculate();save.click()
                with patch('PySide6.QtWidgets.QInputDialog.getText',return_value=('高速工位',True)):p.rename_page_preset('imaging')
                p.device.setCurrentIndex(1);self.assertIn('MV-CL042-91GM',choice.currentText())
                self.assertEqual(choice.currentIndex(),0);apply.click();self.assertEqual(p.settings().gain,2.9079)
                p.device.setCurrentIndex(0);self.assertEqual(choice.currentIndex(),1);self.assertIn('高速工位',choice.currentText())
                apply.click();self.assertEqual(p.settings().gain,0);self.assertEqual(p.settings().exposure_us,23)
                report=p.preset_comparison_report
                self.assertEqual(report['model'],'MV-CL024-91GM');self.assertEqual(report['selected_presets']['imaging']['name'],'高速工位')
                self.assertEqual(report['selected_presets']['imaging']['values']['gain'],0)
                self.assertFalse(p.write_button.isEnabled());self.assertEqual(CameraPresetStore(p.preset_store.path).name('imaging',1,'MV-CL024-91GM'),'高速工位')
            finally:w.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
