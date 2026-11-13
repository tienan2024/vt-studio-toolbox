"""Load the locally installed MVS Python SDK; no vendor code is redistributed."""
from contextlib import contextmanager
import ctypes
import importlib
import os
from pathlib import Path
import sys
import threading

from camera_model import CameraError

_lock=threading.RLock()
_runtime_handles=[]


class NodeUnavailable(CameraError):
    def __init__(self,key,access):
        super().__init__('节点当前不可读或未实现：'+key);self.access=access


def discover_mvs(directory=None):
    candidates=[directory,os.environ.get('VT_MVS_DIR'),os.environ.get('MVCAM_COMMON_RUNENV'),
                'D:/MVS/MVS','C:/Program Files (x86)/MVS','C:/Program Files/MVS']
    for candidate in candidates:
        if not candidate:continue
        root=Path(candidate)
        for path in (root,root/'Samples/Python/MvImport',root/'Development/Samples/Python/MvImport'):
            if (path/'MvCameraControl_class.py').is_file():return str(path.resolve())
    if directory:raise CameraError('未找到MVS Python封装，请选择完整MVS安装目录或MvImport目录。')
    return ''


def _check(code,action):
    if code:raise CameraError(action+' 失败，MVS错误码 0x'+format(code&0xffffffff,'08X'))


def _text(raw):
    data=bytes(raw).split(b'\0',1)[0]
    try:return data.decode('utf-8')
    except UnicodeError:return data.decode('gb18030',errors='replace')


def _load_runtime():
    if os.name!='nt' or _runtime_handles:return
    roots=[os.environ.get('VT_MVS_RUNTIME',''),
        str(Path(os.environ.get('CommonProgramFiles(x86)','C:/Program Files (x86)/Common Files'))/'MVS/Runtime/Win64_x64'),
        str(Path(os.environ.get('CommonProgramFiles','C:/Program Files/Common Files'))/'MVS/Runtime/Win64_x64')]
    for root in roots:
        if not root:continue
        path=Path(root);library=path if path.suffix.lower()=='.dll' else path/'MvCameraControl.dll'
        if not library.is_file():continue
        directory=str(library.parent.resolve())
        # PyInstaller sets a private DLL search directory. Load the installed SDK
        # by absolute path and make its dependencies visible only in this process.
        handle=os.add_dll_directory(directory) if hasattr(os,'add_dll_directory') else None
        previous=os.environ.get('PATH','');os.environ['PATH']=directory+os.pathsep+previous
        try:
            loaded=ctypes.WinDLL(str(library.resolve()),winmode=0x1100)
        except Exception:
            os.environ['PATH']=previous
            if handle:handle.close()
            raise
        _runtime_handles.extend([item for item in (handle,loaded) if item is not None]);return


@contextmanager
def runtime(directory=None):
    with _lock:
        path=discover_mvs(directory)
        if not path:raise CameraError('未安装可用的MVS Python SDK；计算与配置导出仍可使用。')
        if path not in sys.path:sys.path.insert(0,path)
        try:
            _load_runtime()
            sdk=importlib.import_module('MvCameraControl_class')
            params=importlib.import_module('CameraParams_header')
            if Path(sdk.__file__).resolve().parent!=Path(path).resolve():raise CameraError('当前进程已加载另一目录的MVS封装；切换版本后请重启工具箱。')
        except Exception as exc:
            root=exc
            while root.__cause__ or root.__context__:root=root.__cause__ or root.__context__
            raise CameraError('MVS运行时加载失败，请安装匹配的x64运行库：'+str(root)) from exc
        _check(sdk.MvCamera.MV_CC_Initialize(),'初始化MVS')
        try:yield sdk,params
        finally:sdk.MvCamera.MV_CC_Finalize()


def _devices(sdk,p):
    items=p.MV_CC_DEVICE_INFO_LIST();_check(sdk.MvCamera.MV_CC_EnumDevices(5,items),'枚举GigE/USB3相机')
    result=[]
    if items.nDeviceNum>256:raise CameraError('设备枚举数量无效。')
    for i in range(items.nDeviceNum):
        if not items.pDeviceInfo[i]:raise CameraError('SDK返回了无效的设备指针。')
        info=p.MV_CC_DEVICE_INFO();ctypes.memmove(ctypes.byref(info),items.pDeviceInfo[i],ctypes.sizeof(info))
        if info.nTLayerType not in (1,4):continue
        transport='GigE' if info.nTLayerType==1 else 'USB3'
        data=info.SpecialInfo.stGigEInfo if transport=='GigE' else info.SpecialInfo.stUsb3VInfo
        serial=_text(data.chSerialNumber)
        if not serial:continue
        record={'uid':transport+':'+serial,'serial':serial,'transport':transport,'model':_text(data.chModelName),
                'name':_text(data.chUserDefinedName)}
        if transport=='GigE':record['ip']='.'.join(str((data.nCurrentIp>>shift)&255) for shift in (24,16,8,0))
        result.append((record,info))
    return result


def enumerate_cameras(directory=None):
    with runtime(directory) as (sdk,p):
        return {'sdk_version':hex(sdk.MvCamera.MV_CC_GetSDKVersion()),'devices':[d for d,info in _devices(sdk,p)]}


class Camera:
    def __init__(self,handle,sdk,params,device):self.handle=handle;self.sdk=sdk;self.p=params;self.device=device

    def read(self,key,kind):
        access=ctypes.c_int();_check(self.handle.MV_XML_GetNodeAccessMode(key,access),'读取'+key+'访问权限')
        if access.value not in (self.p.AM_RO,self.p.AM_RW):raise NodeUnavailable(key,access.value)
        interface=ctypes.c_int();_check(self.handle.MV_XML_GetNodeInterfaceType(key,interface),'读取'+key+'类型')
        types={self.p.IFT_IInteger:'int',self.p.IFT_IFloat:'float',self.p.IFT_IBoolean:'bool',
               self.p.IFT_IString:'string',self.p.IFT_IEnumeration:'enum'}
        actual=types.get(interface.value)
        if actual is None:raise CameraError('不支持的节点类型：'+key)
        if actual!=kind and {actual,kind}!={'int','float'}:raise CameraError('节点类型与计划不同：'+key+' ('+actual+')')
        kind=actual;result={'kind':kind,'writable':access.value==self.p.AM_RW}
        if kind=='int':
            value=self.p.MVCC_INTVALUE_EX();_check(self.handle.MV_CC_GetIntValueEx(key,value),'读取'+key)
            result.update(value=int(value.nCurValue),min=int(value.nMin),max=int(value.nMax),inc=max(1,int(value.nInc)))
        elif kind=='float':
            value=self.p.MVCC_FLOATVALUE();_check(self.handle.MV_CC_GetFloatValue(key,value),'读取'+key)
            result.update(value=float(value.fCurValue),min=float(value.fMin),max=float(value.fMax))
        elif kind=='bool':
            value=ctypes.c_bool();_check(self.handle.MV_CC_GetBoolValue(key,value),'读取'+key);result['value']=value.value
        elif kind=='string':
            value=self.p.MVCC_STRINGVALUE();_check(self.handle.MV_CC_GetStringValue(key,value),'读取'+key)
            result.update(value=_text(value.chCurValue),max_length=int(value.nMaxLength))
        else:
            value=self.p.MVCC_ENUMVALUE_EX();_check(self.handle.MV_CC_GetEnumValueEx(key,value),'读取'+key)
            if value.nSupportedNum>len(value.nSupportValue):raise CameraError('枚举值数量无效：'+key)
            def symbol(number):
                entry=self.p.MVCC_ENUMENTRY();entry.nValue=number
                _check(self.handle.MV_CC_GetEnumEntrySymbolic(key,entry),'读取'+key+'枚举符号')
                return _text(entry.chSymbolic)
            result.update(value=symbol(value.nCurValue),choices=[symbol(n) for n in value.nSupportValue[:value.nSupportedNum]])
        return result

    def write(self,key,kind,value):
        if kind=='int':code=self.handle.MV_CC_SetIntValueEx(key,int(value))
        elif kind=='float':code=self.handle.MV_CC_SetFloatValue(key,float(value))
        elif kind=='bool':code=self.handle.MV_CC_SetBoolValue(key,bool(value))
        elif kind=='enum':code=self.handle.MV_CC_SetEnumValueByString(key,str(value))
        elif kind=='string':code=self.handle.MV_CC_SetStringValue(key,str(value))
        else:raise CameraError('不能写入的节点类型：'+kind)
        _check(code,'设置'+key)

    def command(self,key):_check(self.handle.MV_CC_SetCommandValue(key),'执行'+key)

    def command_ready(self,key):
        access=ctypes.c_int();_check(self.handle.MV_XML_GetNodeAccessMode(key,access),'读取'+key+'访问权限')
        if access.value not in (self.p.AM_WO,self.p.AM_RW):raise CameraError('命令不可执行：'+key)

    def geometry(self):
        limits={key:self.read(key,'int') for key in ('Width','Height','OffsetX')}
        try:limits['OffsetY']=self.read('OffsetY','int')
        except CameraError:pass
        def dimension(keys,fallback):
            for key in keys:
                try:return self.read(key,'int')['value']
                except CameraError:pass
            return fallback
        width=dimension(('SensorWidth','WidthMax'),limits['Width']['max'])
        height=dimension(('SensorHeight','HeightMax'),limits['Height']['max'])
        try:scan=self.read('DeviceScanType','enum')['value']
        except CameraError:scan=''
        try:pixel=self.read('PixelFormat','enum')
        except CameraError:pixel={}
        return {'sensor_width':width,'sensor_height':height,'limits':limits,'scan_type':scan,'pixel_format':pixel}


@contextmanager
def open_camera(uid,directory=None,write=False):
    with runtime(directory) as (sdk,p):
        matches=[(d,info) for d,info in _devices(sdk,p) if d['uid']==uid]
        if len(matches)!=1:raise CameraError('目标相机不在当前设备列表或序列号不唯一，请重新枚举。')
        device,info=matches[0];handle=sdk.MvCamera();_check(handle.MV_CC_CreateHandle(info),'创建相机句柄')
        opened=False
        try:
            # Never use access modes that steal another application's control.
            _check(handle.MV_CC_OpenDevice(1 if write else 3,0),'打开相机（请确认未被其他软件占用）');opened=True
            yield Camera(handle,sdk,p,device)
        finally:
            if opened:handle.MV_CC_CloseDevice()
            handle.MV_CC_DestroyHandle()
