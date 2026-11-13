import ctypes
from types import SimpleNamespace
import unittest
from camera_sdk import _devices


class CameraEnumerationTests(unittest.TestCase):
    def test_virtual_transports_have_separate_uids_and_correct_information_bank(self):
        class Info(ctypes.Structure):
            _fields_=[('chSerialNumber',ctypes.c_char*32),('chModelName',ctypes.c_char*32),
                      ('chUserDefinedName',ctypes.c_char*32),('nCurrentIp',ctypes.c_uint)]
        class Special(ctypes.Structure):
            _fields_=[('stGigEInfo',Info),('stUsb3VInfo',Info)]
        class Device(ctypes.Structure):
            _fields_=[('nTLayerType',ctypes.c_uint),('SpecialInfo',Special)]
        class Devices(ctypes.Structure):
            _fields_=[('nDeviceNum',ctypes.c_uint),('pDeviceInfo',ctypes.POINTER(Device)*5)]
        originals=[]
        for layer in (1,4,16,32,128):
            d=Device();d.nTLayerType=layer
            bank=d.SpecialInfo.stGigEInfo if layer in (1,16) else d.SpecialInfo.stUsb3VInfo
            bank.chSerialNumber=b'SAME';bank.chModelName=b'TEST';bank.nCurrentIp=0x7f000001
            originals.append(d)
        def enum(mask,items):
            self.assertEqual(mask,0x35);items.nDeviceNum=len(originals)
            for i,d in enumerate(originals):items.pDeviceInfo[i]=ctypes.pointer(d)
            return 0
        sdk=SimpleNamespace(MvCamera=SimpleNamespace(MV_CC_EnumDevices=enum))
        params=SimpleNamespace(MV_CC_DEVICE_INFO=Device,MV_CC_DEVICE_INFO_LIST=Devices)
        records=[r for r,_ in _devices(sdk,params)]
        self.assertEqual([r['uid'] for r in records],['GigE:SAME','USB3:SAME','VirtualGigE:SAME','VirtualUSB3:SAME'])
        self.assertEqual([r['virtual'] for r in records],[False,False,True,True])
        self.assertEqual(records[2]['ip'],'127.0.0.1');self.assertNotIn('ip',records[3])
