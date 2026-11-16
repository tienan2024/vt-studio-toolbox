"""Selecting physical hardware must not leave a different model in the calculation."""
import copy,sys,tempfile,unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from camera_ui import CameraPage
from camera_model import CameraSettings,config_dict
from camera_options import PRESETS,model_preset
from camera_presets import CameraPresetStore
from camera_transaction import compare
from test_camera import FakeCamera


class CameraDeviceMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    @staticmethod
    def device(model,uid='test:mono'):
        return {'model':model,'uid':uid,'serial':'TEST','transport':'GigE','virtual':True}

    def scan(self,page,*devices):
        page.finished_result('scan',{'sdk_version':'TEST','devices':list(devices)})

    def test_enumeration_and_switch_follow_device_keep_inputs_and_selected_uid(self):
        p=CameraPage()
        try:
            p.controls['target_width_mm'].setValue(210);p.controls['cycle_travel_mm'].setValue(600)
            p.controls['gain'].setValue(2.9079);p.recalculate();p.toggle_value_lock('target_width_mm',True)
            mono=self.device('MV-CL024-91GM');area=self.device('MV-CS050-60GC V5','test:area')
            self.scan(p,mono,area)
            self.assertEqual(p.camera_type.currentData(),'line2k');self.assertFalse(p.camera_type.isEnabled())
            self.assertEqual(p.settings(False).sensor_height,2)
            self.assertEqual(p.controls['target_width_mm'].value(),210);self.assertIn('target_width_mm',p.fixed_values)
            self.assertEqual(p.controls['cycle_travel_mm'].value(),600);self.assertEqual(p.controls['gain'].value(),2.9079)
            p.device.setCurrentIndex(1)
            self.assertEqual(p.camera_type.currentData(),'area5mp_color');self.assertFalse(p.form_tabs.isTabVisible(1))
            self.assertEqual(p.settings(False).frame_selector,'FrameStart');self.assertEqual(p.settings(False).focal_length_mm,6)
            self.scan(p,area,mono)
            self.assertEqual(p.selected_uid(),area['uid']);self.assertEqual(p.camera_type.currentData(),'area5mp_color')
            self.assertIsNone(p.preview);self.assertFalse(p.write_button.isEnabled())
            self.scan(p)
            self.assertIsNone(p.selected_uid());self.assertTrue(p.camera_type.isEnabled())
        finally:p.close()

    def test_presets_and_configs_cannot_replace_selected_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            p=CameraPage();p.preset_store=CameraPresetStore(Path(folder)/'presets.json')
            try:
                self.scan(p,self.device('MV-CL024-91GM'))
                saved=copy.deepcopy(p.preset_store.data);p.apply_page_preset('material')
                self.assertEqual(p.camera_type.currentData(),'line2k');self.assertEqual(p.preset_store.data,saved)
                p.load_settings(replace(p.settings(False),camera_model_id='MV-CL042-91GM',sensor_width=4096,focal_length_mm=25,target_length_mm=450))
                self.assertEqual(p.camera_type.currentData(),'line2k');self.assertEqual(p.settings(False).sensor_width,2048)
                self.assertEqual(p.settings(False).focal_length_mm,12);self.assertEqual(p.settings(False).target_length_mm,450)
            finally:p.close()

    def test_readback_uses_sensor_geometry_not_roi_and_preserves_draft(self):
        p=CameraPage()
        try:
            p.controls['pixel_format'].setCurrentText('Mono8');p.controls['gain'].setValue(2.9079)
            self.scan(p,self.device('MV-CL024-91GM'))
            data={'device':self.device('MV-CL024-91GM'),'sensor_width':2048,'sensor_height':65535,
                  'scan_type':'Linescan','limits':{},'pixel_format':{'value':'Mono8','choices':['Mono8']},
                  'snapshot':None,'trigger_io_choices':{},'output_source_choices':{}}
            p.finished_result('inspect',data)
            self.assertEqual(p.camera_type.currentData(),'line2k');self.assertEqual(p.settings(False).sensor_height,2)
            self.assertEqual(p.controls['gain'].value(),2.9079);self.assertEqual(p.controls['pixel_format'].currentData(),'Mono8')
            self.assertEqual(p.result_tabs.currentIndex(),1);self.assertFalse(p.write_button.isEnabled())
            self.assertEqual(p.geometry['sensor_width'],2048)
        finally:p.close()

    def test_unknown_device_never_inherits_previous_lens_or_version_guess(self):
        p=CameraPage()
        try:
            self.assertIsNone(model_preset('MV-CS050-60GM'))
            for preset in PRESETS.values():self.assertIs(model_preset(' '+preset['model'].lower()+' '),preset)
            unknown=self.device('Unknown Model V6');self.scan(p,unknown)
            self.assertEqual(p.camera_type.currentData(),'custom');self.assertIn('Unknown Model V6',p.camera_type.currentText())
            self.assertEqual(p.settings(False).camera_model_id,'Unknown Model V6')
            self.assertEqual(p.settings(False).pixel_pitch_um,0);self.assertEqual(p.settings(False).focal_length_mm,0)
            p.controls['pixel_pitch_um'].setValue(5);p.controls['focal_length_mm'].setValue(16)
            self.scan(p,unknown)
            self.assertEqual(p.settings(False).pixel_pitch_um,5);self.assertEqual(p.settings(False).focal_length_mm,16)
        finally:p.close()

    def test_write_plan_rejects_different_model_even_at_same_resolution(self):
        camera=FakeCamera();camera.device['model']='MV-CL024-91GM'
        result=compare(camera,replace(CameraSettings(),camera_model_id='MV-CL024-91GC'))
        self.assertFalse(result['ready']);self.assertTrue(any('配置机型' in e for e in result['errors']))
        self.assertFalse(camera.commands)


if __name__=='__main__':unittest.main()
