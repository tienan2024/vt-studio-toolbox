import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_model import CameraSettings
from camera_transaction import compare,apply_comparison,CameraWriteError,USER_SET_SAVE_DELAY_S
from test_camera import FakeCamera

class DelayedFlashCamera(FakeCamera):
    def __init__(self,required=3):
        super().__init__();self._set_plain('Height',480);self._set_plain('ExposureTime',50.)
        self.saved=(copy.deepcopy(self.values),copy.deepcopy(self.selectors));self.required=required;self.order=[]
    def command(self,key):
        self.order.append(key)
        if key=='UserSetSave':
            self.commands.append(key);self.pending=(copy.deepcopy(self.values),copy.deepcopy(self.selectors))
        else:super().command(key)
    def wait(self,seconds):
        self.order.append(('wait',seconds))
        if seconds>=self.required:self.saved=self.pending

class SaveTimingTests(unittest.TestCase):
    def test_production_delay_is_three_and_precedes_load(self):
        self.assertEqual(USER_SET_SAVE_DELAY_S,3.)
        camera=DelayedFlashCamera();preview=compare(camera,CameraSettings())
        with patch('camera_transaction.time.sleep',side_effect=camera.wait):report=apply_comparison(camera,preview)
        self.assertEqual(camera.order,['UserSetSave',('wait',3.),'UserSetLoad'])
        self.assertEqual(report['status'],'passed');self.assertEqual(report['user_set_save_delay_s'],3.)
        self.assertTrue(report['readbacks'][-1]['verified'])

    def test_slower_device_still_fails_readback_honestly(self):
        camera=DelayedFlashCamera(required=4);preview=compare(camera,CameraSettings())
        with patch('camera_transaction.time.sleep',side_effect=camera.wait):
            with self.assertRaises(CameraWriteError) as caught:apply_comparison(camera,preview)
        report=caught.exception.report
        self.assertIn('实际 480',report['error']);self.assertTrue(report['persistent_may_have_changed'])
        self.assertFalse(report['runtime_restored']);self.assertNotEqual(camera.read('UserSetDefault','enum')['value'],'UserSet1')

    def test_save_command_failure_never_loads_or_waits(self):
        camera=DelayedFlashCamera();preview=compare(camera,CameraSettings());command=camera.command
        def fail(key):
            if key=='UserSetSave':raise RuntimeError('SIMULATED save failure')
            command(key)
        with patch.object(camera,'command',side_effect=fail),patch('camera_transaction.time.sleep') as wait:
            with self.assertRaises(CameraWriteError):apply_comparison(camera,preview)
        wait.assert_not_called();self.assertNotIn('UserSetLoad',camera.order)

if __name__=='__main__':unittest.main()
