import ctypes,hashlib,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_mfa import import_mfa,read_mfa,MfaImportError,MAGIC
from camera_sdk import Camera
from camera_model import CameraError

class FileStruct(ctypes.Structure):
    _fields_=[('pUserFileBuf',ctypes.POINTER(ctypes.c_char)),('pFileBufSize',ctypes.c_uint),('pFileBufLen',ctypes.c_uint),('pDevFileName',ctypes.c_char_p)]

class Device:
    device={'model':'TEST-MODEL','serial':'TEST','uid':'test:1'}
    def __init__(self,bad=False):self.data=MAGIC+b'\1\0\0\0'+b'old'*20;self.bad=bad;self.commands=[];self.writes=[]
    def device_file(self,name,data=None):
        if data is None:return self.data
        self.data=data+(b'wrong' if self.bad else b'')
    def invalidate_nodes(self):return True
    def geometry(self):return {}
    def write(self,key,kind,value):self.writes.append((key,value))
    def read(self,key,kind):return {'value':'UserSet1'}
    def command(self,key):self.commands.append(key)

class MfaTests(unittest.TestCase):
    def test_gui_confirmation_launches_import_independently_of_calculation(self):
        from PySide6.QtWidgets import QApplication,QMessageBox
        from camera_ui import CameraPage
        app=QApplication.instance() or QApplication([]);page=CameraPage()
        try:
            page.finished_result('scan',{'sdk_version':'TEST','devices':[dict(Device.device,transport='GigE')]})
            with tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/'TEST-MODEL_TEST_User Set 1.mfa';source.write_bytes(MAGIC+b'x'*40)
                with patch('camera_ui.QFileDialog.getOpenFileName',return_value=(str(source),'')),patch('camera_ui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes),patch.object(page,'launch') as launch:
                    page.open_mfa();self.assertEqual(launch.call_args.args[0],'mfa')
                    self.assertEqual(launch.call_args.args[1]['uid'],'test:1')
        finally:page.deleteLater();app.processEvents()

    def test_sdk_buffer_read_and_write_use_raw_file_bytes(self):
        data=b'test-user-set';captured=[]
        def read(request):
            self.assertEqual(request.pDevFileName,b'UserSet1');ctypes.memmove(request.pUserFileBuf,data,len(data));request.pFileBufLen=len(data);return 0
        def write(request):captured.append(ctypes.string_at(request.pUserFileBuf,request.pFileBufLen));return 0
        cam=Camera(SimpleNamespace(MV_CC_FileAccessReadEx=read,MV_CC_FileAccessWriteEx=write),None,SimpleNamespace(MV_CC_FILE_ACCESS_EX=FileStruct),{})
        self.assertEqual(cam.device_file('UserSet1'),data);cam.device_file('UserSet1',data);self.assertEqual(captured,[data])
        with self.assertRaises(CameraError):Camera(SimpleNamespace(),None,None,{}).device_file('UserSet1')

    def run_import(self,bad=False,foreign=False):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'TEST-MODEL_TEST_User Set 1.mfa';data=MAGIC+b'\1\0\0\0'+b'new'*20;p.write_bytes(data)
            camera=Device(bad);original=camera.data
            if foreign:camera.data=b'RAW_FORMAT'+b'old'*20
            with patch('camera_mfa.open_camera') as opened,patch('camera_mfa.read_snapshot',return_value={'rows':[]}),patch('camera_mfa.time.sleep'):
                opened.return_value.__enter__.return_value=camera
                if bad or foreign:
                    with self.assertRaises(MfaImportError) as caught:import_mfa('test:1',p,hashlib.sha256(data).hexdigest(),backup_root=Path(folder)/'backups')
                    report=caught.exception.report;self.assertFalse(camera.commands)
                    self.assertEqual(report['persistent_may_have_changed'],not foreign)
                else:
                    report=import_mfa('test:1',p,hashlib.sha256(data).hexdigest(),backup_root=Path(folder)/'backups')
                    self.assertEqual(camera.commands,['UserSetLoad']);self.assertTrue(report['file_verified'])
                    self.assertFalse(report['load_complete_verified']);self.assertFalse(report['default_user_set_written'])
                    self.assertEqual((Path(report['backup_directory'])/'UserSet1-before.mfa').read_bytes(),original)
            self.assertTrue((Path(report['backup_directory'])/'report.json').is_file())

    def test_backup_transfer_readback_and_load_are_separate(self):self.run_import()
    def test_bad_readback_never_loads(self):self.run_import(bad=True)
    def test_raw_device_format_mismatch_never_writes(self):self.run_import(foreign=True)

    def test_source_change_before_import_rejects_without_opening_camera(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.mfa';p.write_bytes(MAGIC+b'x'*32)
            with patch('camera_mfa.open_camera') as opened:
                with self.assertRaises(CameraError):import_mfa('test:1',p,'wrong')
                opened.assert_not_called()
            p.write_bytes(b'not-an-mfa')
            with self.assertRaises(CameraError):read_mfa(p)

if __name__=='__main__':unittest.main()
