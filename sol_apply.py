"""Apply generated C# through the installed VM SDK; publish a verified new SOL."""
import csv
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from script_generator import validate_config,generate_sources,variable_rows,port_name,compiler_path
from sol_reader import read_sol_parts,sol_metadata,frame_records,SolError


class SolApplyError(ValueError):pass


def sdk_apps(directory):
    path=Path(directory).expanduser().resolve()
    if (path/'Applications').is_dir():path=path/'Applications'
    required=('myLibs/VM.Core.dll','myLibs/Apps.Interface.dll','PublicFile/x64/VM.PlatformSDKCS.dll',
              'Module(sp)/x64/Logic/ShellModule/ShellModuleControl.dll','3rdLib/NPOI/ICSharpCode.SharpZipLib.dll')
    if not all((path/r).is_file() for r in required):raise SolApplyError('请选择完整 VisionMaster 安装目录或 Applications 文件夹（需要 x64 SDK）。')
    return path


def discover_vm():
    candidates=[os.environ.get('VT_VM_APPLICATIONS',''),'D:/VM/VisionMaster4.4.0/Applications']
    if os.name=='nt':
        import winreg
        for base in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,base) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key,winreg.EnumKey(key,index)) as sub:
                                name=winreg.QueryValueEx(sub,'DisplayName')[0]
                                if 'VisionMaster' in name:candidates.append(winreg.QueryValueEx(sub,'InstallLocation')[0])
                        except OSError:pass
            except OSError:pass
    for candidate in candidates:
        if not candidate:continue
        try:return str(sdk_apps(candidate))
        except SolApplyError:pass
    return ''


def check_vm_closed():
    if os.name!='nt':raise SolApplyError('自动应用需要 Windows 和本机 VisionMaster x64 SDK。')
    result=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise SolApplyError('无法确认VisionMaster进程状态，未启动SDK应用。')
    names={row[0].lower() for row in csv.reader(io.StringIO(result.stdout.decode('mbcs',errors='replace'))) if row}
    if names & {'visionmaster.exe','visionmasterui.exe','vmmaster.exe'}:
        raise SolApplyError('请先保存并关闭 VisionMaster，再自动应用；SDK需要独占脚本编译环境。')


def plan_application(config,module):
    c=validate_config(config);rows=variable_rows(c)
    if not module or not str(module.get('id','')).isdigit():raise SolApplyError('请先选择 SOL 中的脚本模块。')
    additions=[];preserved=[]
    optional={port_name(c,n) for n in ('aiResult','Label_name')} if not c['use_ai'] else set()
    for key,direction in (('inputs','输入'),('outputs','输出')):
        existing={r['name']:r for r in module[key]};expected={r['name']:r for r in rows if r['direction']==direction}
        if key=='outputs' and existing and set(existing)!=set(expected):
            raise SolApplyError('输出名称与目标模块不一致，会影响下游绑定。请按 SOL 原输出名修改变量清单后再应用。')
        for name,row in expected.items():
            if name in existing:
                if row['type']!=existing[name]['type'] or (existing[name].get('array') and name!=port_name(c,'Label_name')):
                    raise SolApplyError('目标变量类型不一致：'+name)
                preserved.append({'direction':direction,'name':name,'type':row['type']})
            else:
                if key=='inputs' and name not in optional:
                    raise SolApplyError('缺少必需输入 '+name+'，无法猜测其上游绑定。请先使用此模块变量或在VM建立正确绑定。')
                additions.append({'direction':direction,'name':name,'type':row['type']})
    return {'module_id':module['id'],'flow':module['flow'],'module':module['name'],
            'preserved':preserved,'added':additions,'inputs':[r for r in rows if r['direction']=='输入'],
            'outputs':[r for r in rows if r['direction']=='输出']}


def _hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _tree(node):
    return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),tuple(_tree(c) for c in node))


def verify_saved(original,saved,ident,source):
    before_server,_,before_records=original;server,_,records=saved
    target=str(ident)+'-ShellModule.mdata'
    # Native serialization may normalize the container, but topology/bindings cannot change.
    if _tree(before_server)!=_tree(server):raise SolApplyError('保存后方案拓扑或绑定元数据发生变化，未交付该副本。')
    if set(before_records)!=set(records):raise SolApplyError('保存后模块记录数量发生变化。')
    changed=[name for name in records if name!=target and before_records[name]!=records[name]]
    if changed:raise SolApplyError('非目标模块数据发生变化，未交付该副本：'+', '.join(changed[:8]))
    normalized=records[target].replace(b'\r\n',b'\n')
    if source.replace('\r\n','\n').encode('utf-8') not in normalized:raise SolApplyError('保存后的目标模块没有完整生成代码。')
    return {'source_verified':True,'other_records_unchanged':True,'bindings_unchanged':True}


def replace_native_record(original,native,ident):
    """Outer framing only: the selected parameter record is wholly SDK-produced."""
    _,version,records=original;target=str(ident)+'-ShellModule.mdata'
    if version!=7:raise SolApplyError('自动应用暂支持已实测的模块帧版本7；其他版本仍可读取变量。')
    if target not in records or target not in native[2]:raise SolApplyError('目标模块序列化记录缺失。')
    updated=dict(records);updated[target]=native[2][target]
    chunks=[struct.pack('>II',version,len(updated))]
    for name,data in updated.items():
        encoded=name.encode('utf-8')
        if len(encoded)>=512:raise SolApplyError('模块记录名称过长。')
        chunks.extend((encoded.ljust(512,b'\0'),struct.pack('>I',len(data)),data))
    frame=b''.join(chunks)
    if frame_records(frame)!=(version,updated):raise SolApplyError('模块记录边界校验失败。')
    return frame


def verify_archive_payloads(source,output):
    def entries(path):
        with zipfile.ZipFile(path) as archive:
            return {e.filename.replace('\\','/'):(e.CRC,e.file_size,bool(e.flag_bits&1)) for e in archive.infolist()}
    before,after=entries(source),entries(output)
    if set(before)!=set(after):raise SolApplyError('封装后的方案条目不完整。')
    if any(before[n]!=after[n] for n in before if n!='SolutionFile/MoudleFrame'):
        raise SolApplyError('封装后的非模块文件或密码保护状态发生变化。')
    if before['SolutionFile/MoudleFrame'][2]!=after['SolutionFile/MoudleFrame'][2]:raise SolApplyError('方案密码保护状态发生变化。')


def compile_host(apps,work):
    executable=Path(work)/'SolScriptHost.exe';source=Path(__file__).resolve().parent/'vm_bridge/SolScriptHost.cs'
    command=[str(compiler_path()),'/nologo','/platform:x64','/r:System.Core.dll','/r:System.Web.Extensions.dll',
             '/r:'+str(apps/'myLibs/Apps.Interface.dll'),'/out:'+str(executable),str(source)]
    compiled=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if compiled.returncode:raise SolApplyError('VM适配器编译失败：'+compiled.stdout+compiled.stderr)
    return executable


def _host(executable,request):
    # The JSON request, including credentials, is never written to a file/argv.
    try:
        result=subprocess.run([str(executable)],input=json.dumps(request,ensure_ascii=False)+'\n',capture_output=True,
            encoding='utf-8',errors='replace',timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:raise SolApplyError('VM加载、编译或保存超过120秒，未交付方案。') from None
    marker=next((line[len('VT_RESULT:'):] for line in reversed(result.stdout.splitlines()) if line.startswith('VT_RESULT:')),None)
    if marker is None:raise SolApplyError('VM适配器未正常返回（退出码 '+str(result.returncode)+'）。')
    data=json.loads(marker)
    if result.returncode or not data.get('ok'):raise SolApplyError('VM应用失败：'+data.get('error','未知错误'))
    return data


@contextmanager
def vm_session_lock():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Local\\VTStudioApplyWorkflow')
    if not handle:raise SolApplyError('无法建立VM应用任务锁。')
    acquired=kernel.WaitForSingleObject(handle,0) in (0,0x80)
    try:
        if not acquired:raise SolApplyError('另一个工具箱正在应用脚本，请等待其完成。')
        yield
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def apply_script(path,module_id,config,output,password=None,applications=None,previous=None,progress=None):
    check_vm_closed()
    with vm_session_lock():
        return _apply_script(path,module_id,config,output,password,applications,previous,progress)


def _apply_script(path,module_id,config,output,password=None,applications=None,previous=None,progress=None):
    check_vm_closed();apps=sdk_apps(applications or discover_vm());c=validate_config(config)
    path=Path(path).resolve();output=Path(output).resolve()
    if path==output or output.exists():raise SolApplyError('请使用新的 SOL 文件名，不能覆盖原方案或已有文件。')
    if output.suffix.lower()!='.sol' or not output.parent.is_dir():raise SolApplyError('输出必须是已有文件夹内的新 .sol 文件。')
    before_hash=_hash(path);original=read_sol_parts(path,password);metadata=sol_metadata(path,*original)
    module=next((m for m in metadata['scripts'] if m['id']==str(module_id)),None)
    plan=plan_application(c,module);source=generate_sources(c,previous)['UserScript.cs']
    notify=progress or (lambda message:None)
    required_space=max(256*1024*1024,path.stat().st_size*5+128*1024*1024)
    temp_base=os.environ.get('VT_TOOLBOX_TEMP')
    if not temp_base and shutil.disk_usage(tempfile.gettempdir()).free<required_space:
        temp_base=str(Path(apps.anchor)/'VTStudioToolboxTemp')
    if temp_base:
        Path(temp_base).mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(temp_base).free<required_space:raise SolApplyError('方案临时目录空间不足，请调整VT_TOOLBOX_TEMP或释放磁盘空间。')
    with tempfile.TemporaryDirectory(prefix='vt_sol_apply_',dir=temp_base) as folder:
        work=Path(folder);staging=work/'input.sol';shutil.copy2(path,staging)
        if _hash(staging)!=before_hash:raise SolApplyError('读取期间原方案发生变化，请重新打开。')
        executable=compile_host(apps,work)
        request={'apps':str(apps),'input':str(staging),'output':str(work/'applied.sol'),'work':str(work),
                 'password':password or '','module_id':module_id,'source':source,'action':'apply',
                 'inputs':plan['inputs'],'outputs':plan['outputs']}
        try:
            notify('正在由 VM 导入并编译脚本…');native=_host(executable,request)
            saved=read_sol_parts(work/'applied.sol',password)
            # VM full-save normalizes unrelated resource paths/UI caches. Keep only its
            # complete native target record and retain every other original payload.
            (work/'frame.bin').write_bytes(replace_native_record(original,saved,module_id))
            notify('正在保留原方案其他模块并封装副本…')
            request.update(input=str(staging),output=str(work/'packaged.sol'),frame=str(work/'frame.bin'),action='package')
            _host(executable,request)
            packaged=read_sol_parts(work/'packaged.sol',password)
            verification=verify_saved(original,packaged,module_id,source)
            verify_archive_payloads(staging,work/'packaged.sol')
            notify('正在独立重载并核对保存结果…')
            request.update(input=str(work/'packaged.sol'),output=str(work/'reloaded.sol'),action='verify')
            _host(executable,request)
            reloaded=read_sol_parts(work/'reloaded.sol',password)
            target=str(module_id)+'-ShellModule.mdata'
            if source.replace('\r\n','\n').encode('utf-8') not in reloaded[2][target].replace(b'\r\n',b'\n'):
                raise SolApplyError('VM独立重载后源码发生变化。')
            final_meta=sol_metadata(output,*reloaded);final=next(m for m in final_meta['scripts'] if m['id']==str(module_id))
            plan_application(c,final)
            if _hash(path)!=before_hash:raise SolApplyError('执行期间原方案已改变，未交付副本。')
            # Exclusive creation also protects a file created while the SDK was busy.
            created=False
            try:
                with output.open('xb') as stream:
                    created=True
                    with (work/'packaged.sol').open('rb') as src:shutil.copyfileobj(src,stream)
            except FileExistsError:raise SolApplyError('输出文件已存在，请选择新文件名。') from None
            except Exception:
                if created:output.unlink(missing_ok=True)
                raise
        finally:request['password']=None;password=None
    return {'output':str(output),'module_id':str(module_id),'flow':module['flow'],'module':module['name'],
            'compile':native['compile'],'reloaded':True,'source_unchanged':True,'flows_run':False,
            'added_ports':plan['added'],**verification}
