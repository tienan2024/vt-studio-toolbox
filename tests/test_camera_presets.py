import sys,tempfile,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from camera_presets import CameraPresetStore,PAGE_KEYS
from camera_model import CameraSettings,workflow_settings,calculate,config_dict,settings_from_dict,import_mfs_text
from camera_transaction import compare,read_trigger_ios
from test_camera import FakeCamera


class PresetAndSourceTests(unittest.TestCase):
    def test_reference_slots_are_independent_and_saved_per_page(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presets.json';store=CameraPresetStore(path)
            self.assertEqual(set(store.data),set(PAGE_KEYS));self.assertFalse(path.exists())
            for slots in store.data.values():self.assertEqual(slots[0],slots[1]);self.assertEqual(len(slots),2)
            s=replace(workflow_settings(),frame_line='Line2',line_source='Software',gain=7)
            store.save('trigger',1,s);loaded=CameraPresetStore(path)
            self.assertEqual(loaded.values('trigger',1)['line_source'],'Software')
            self.assertEqual(loaded.values('trigger',0)['line_source'],'FrequencyConverter')
            self.assertNotIn('gain',loaded.values('trigger',1));self.assertNotIn('cycle_travel_mm',loaded.values('encoder',0))

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
                self.assertEqual((p.settings().auto_frequency,p.settings().multiplier,p.settings().height_override),(False,3,3200))
                self.assertEqual(p.settings().cycle_travel_mm,450)
                p.apply_page_preset('material');p.apply_page_preset('imaging')
                self.assertEqual(p.settings().camera_model_id,'MV-CL042-91GM')
                self.assertEqual((p.settings().width_override,p.settings().offset_x,p.settings().compression),(3296,500,'HB'))
                self.assertEqual(p.settings().cycle_travel_mm,450)
            finally:w.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
