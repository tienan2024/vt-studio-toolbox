import ctypes,importlib.util,sys,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera_sdk import Camera,discover_mvs
from camera_model import CameraError

class EnumValue(ctypes.Structure):
    _fields_=[('nCurValue',ctypes.c_uint),('nSupportedNum',ctypes.c_uint),('nSupportValue',ctypes.c_uint*4)]
class EnumEntry(ctypes.Structure):
    _fields_=[('nValue',ctypes.c_longlong),('chSymbolic',ctypes.c_char*64)]

class StandardEnumHandle:
    def __init__(self,params,status=0,invalid_count=False):self.p=params;self.status=status;self.invalid_count=invalid_count
    def MV_XML_GetNodeAccessMode(self,key,value):value.value=self.p.AM_RW;return 0
    def MV_XML_GetNodeInterfaceType(self,key,value):value.value=self.p.IFT_IEnumeration;return 0
    def MV_CC_GetEnumValue(self,key,value):
        if not isinstance(value,self.p.MVCC_ENUMVALUE):raise AssertionError('Wrong SDK enum structure')
        value.nCurValue=2;value.nSupportedNum=len(value.nSupportValue)+1 if self.invalid_count else 2
        value.nSupportValue[0]=2;value.nSupportValue[1]=4;return self.status
    def MV_CC_GetEnumEntrySymbolic(self,key,entry):
        raw={2:b'Mono8',4:b'RGB8Packed'}[entry.nValue]
        ctypes.memmove(ctypes.addressof(entry)+self.p.MVCC_ENUMENTRY.chSymbolic.offset,raw,len(raw));return 0

class CameraEnumAPITests(unittest.TestCase):
    def params(self):
        return SimpleNamespace(AM_RO=1,AM_RW=2,IFT_IInteger=1,IFT_IFloat=2,IFT_IBoolean=3,IFT_IString=4,IFT_IEnumeration=5,
            MVCC_ENUMVALUE=EnumValue,MVCC_ENUMENTRY=EnumEntry)

    def test_standard_sdk_without_ex_type_reads_current_and_choices(self):
        p=self.params();result=Camera(StandardEnumHandle(p),None,p,{}).read('PixelFormat','enum')
        self.assertEqual(result,{'kind':'enum','writable':True,'value':'Mono8','choices':['Mono8','RGB8Packed']})

    def test_invalid_count_and_sdk_failure_are_not_ignored(self):
        p=self.params()
        for handle in (StandardEnumHandle(p,invalid_count=True),StandardEnumHandle(p,status=0x80000001)):
            with self.assertRaises(CameraError):Camera(handle,None,p,{}).read('PixelFormat','enum')

    def test_actual_installed_mvs_header_with_simulated_getter(self):
        directory=discover_mvs()
        if not directory:self.skipTest('Local MVS Python header not installed')
        sys.path.insert(0,directory)
        try:
            spec=importlib.util.spec_from_file_location('test_only_mvs_header',Path(directory)/'CameraParams_header.py')
            p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
            result=Camera(StandardEnumHandle(p),None,p,{}).read('PixelFormat','enum')
            self.assertEqual(result['value'],'Mono8');self.assertEqual(result['choices'],['Mono8','RGB8Packed'])
        finally:sys.path.remove(directory)

if __name__=='__main__':unittest.main()
