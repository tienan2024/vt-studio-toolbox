"""Explicit same-device UserSet1 restore using vendor FileAccess, with backup and byte verification."""
import hashlib,json,os,time,uuid
from datetime import datetime
from pathlib import Path
from camera_model import CameraError
from camera_sdk import open_camera
from camera_snapshot import read_snapshot
from diagnostic_log import event,snapshot

MAGIC=bytes.fromhex('55aa5a5a')
LIMIT=16*1024*1024

class MfaImportError(CameraError):
    def __init__(self,message,report):super().__init__(message);self.report=report

def read_mfa(path):
    path=Path(path)
    if path.suffix.lower()!='.mfa' or not 32<=path.stat().st_size<=LIMIT:raise CameraError('请选择有效的MFA文件（32字节～16MB）。')
    data=path.read_bytes()
    if data[:4]!=MAGIC:raise CameraError('未识别的MFA头，不会尝试作为用户集写入。')
    return data

def import_mfa(uid,path,expected_hash,directory=None,progress=None,backup_root=None):
    data=read_mfa(path);digest=hashlib.sha256(data).hexdigest();notify=progress or (lambda text:None)
    if digest!=expected_hash:raise CameraError('MFA在预览后已改变，请重新选择。')
    root=Path(backup_root) if backup_root else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VTStudioToolbox'/'camera-backups'
    folder=root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
    report={'schema':'vt-camera-mfa-import/1','status':'failed','source':str(path),'sha256':digest,'backup_directory':str(folder),
            'persistent_may_have_changed':False,'file_verified':False,'load_complete_verified':False,'default_user_set_written':False}
    try:
        with open_camera(uid,directory,write=True) as camera:
            report['device']=camera.device
            expected=camera.device['model']+'_'+camera.device['serial']+'_User Set 1.mfa'
            if Path(path).name.casefold()!=expected.casefold():raise CameraError('此试用入口仅接受所选设备原名导出的User Set 1文件：'+expected)
            notify('正在备份设备UserSet1…')
            original=camera.device_file('UserSet1');(folder/'UserSet1-before.mfa').write_bytes(original)
            # Establish that this SDK/device uses the same file envelope before touching NVM.
            if original[:8]!=data[:8]:raise CameraError('SDK导出的用户集格式与MFA不一致，已备份但未写入；请使用MVS文件存取导入。')
            camera.invalidate_nodes();report['before']=read_snapshot(camera,camera.geometry())
            notify('正在通过FileAccess导入MFA到UserSet1…')
            report['persistent_may_have_changed']=True;camera.device_file('UserSet1',data)
            actual=camera.device_file('UserSet1');(folder/'UserSet1-after.mfa').write_bytes(actual)
            if actual!=data:raise CameraError('用户集文件写后读回不一致，未执行加载；可用备份通过MVS恢复。')
            report['file_verified']=True
            camera.write('UserSetSelector','enum','UserSet1')
            if camera.read('UserSetSelector','enum')['value']!='UserSet1':raise CameraError('用户集选择读回不一致，未加载。')
            camera.command('UserSetLoad');report['load_command_sent']=True
            # This SDK exposes command execution, not a documented IsDone API. Do not claim completion.
            time.sleep(.3);camera.invalidate_nodes();report['after']=read_snapshot(camera,camera.geometry())
            report['status']='file_verified'
        event('camera.mfa','import_file_verified',report=report)
        return report
    except Exception as exc:
        report['error']=str(exc);event('camera.mfa','import_failed',report=report,error_event=True)
        raise MfaImportError('MFA导入未完成：'+str(exc)+'；备份/记录：'+str(folder),report) from exc
    finally:
        try:(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except OSError as exc:event('camera.mfa','report_save_failed',error=str(exc),error_event=True)
        try:snapshot('camera-mfa-import',report)
        except OSError:pass
