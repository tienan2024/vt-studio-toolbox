"""Bounded, read-only SOL metadata/port inspection; never loads a VM module."""
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
import zipfile


class SolError(ValueError):pass
class SolPasswordError(SolError):pass


def xml_root(data):
    declaration_check=data.replace(b'\0',b'').upper()
    if b'<!DOCTYPE' in declaration_check or b'<!ENTITY' in declaration_check:raise SolError('不支持带DTD或实体的SOL元数据。')
    try:return ET.fromstring(data)
    except ET.ParseError as exc:raise SolError('SOL元数据XML无效。') from exc


def frame_records(data):
    if len(data)<8:raise SolError('SOL模块数据帧不完整。')
    version,count=struct.unpack_from('>II',data)
    layouts={5:(256,'utf-16-le'),7:(512,'utf-8')}
    if version not in layouts:raise SolError('暂不支持此SOL模块帧版本：'+str(version))
    if count>10000:raise SolError('SOL模块数量超出读取限制。')
    width,encoding=layouts[version];offset=8;records={}
    for _ in range(count):
        if offset+width+4>len(data):raise SolError('SOL模块记录头被截断。')
        try:name=data[offset:offset+width].decode(encoding).split('\0',1)[0]
        except UnicodeError as exc:raise SolError('SOL模块记录名编码错误。') from exc
        size=struct.unpack_from('>I',data,offset+width)[0];start=offset+width+4;offset=start+size
        if offset>len(data) or not name or any(ord(c)<32 for c in name) or name in records:
            raise SolError('SOL模块记录边界或名称无效。')
        records[name]=data[start:offset]
    if offset!=len(data):raise SolError('SOL模块记录总长度不一致。')
    return version,records


def _ports(data):
    result={'inputs':[],'outputs':[]}
    # Parse XML only from the named DynamicIn/OutData field, not C# text.
    for field,category,key in ((b'DynamicInData','Input','inputs'),(b'DynamicOutData','Output','outputs')):
        positions=[m.start() for m in re.finditer(re.escape(field)+b'\0',data)]
        if len(positions)!=1:raise SolError('脚本动态端口字段缺失或重复：'+category)
        section=data[positions[0]+len(field):]
        start=section.find(b'<ParamRoot>');end=section.find(b'</ParamRoot>',start)
        if start<0 or end<0 or start>4096:raise SolError('脚本端口XML字段位置无效。')
        root=xml_root(section[start:end+len(b'</ParamRoot>')])
        nodes=root.findall('./Categorys/Category')
        if len(nodes)!=1:raise SolError('脚本端口分类缺失或重复：'+category)
        for cat in nodes:
            if cat.get('Name')!=category:raise SolError('脚本端口方向不一致。')
            for node in cat.findall('.//Filter'):
                name=node.get('Name','')
                # VM user ports have %name%; built-in timestamps remain excluded.
                if len(name)<3 or not name.startswith('%') or not name.endswith('%'):continue
                name=name[1:-1];kind=node.get('ValueType','')
                if not name or any(p['name']==name for p in result[key]):raise SolError('脚本变量名为空或重复。')
                result[key].append({'name':name,'type':kind,'note':'从SOL读取','array':node.get('IsArray','false').lower()=='true'})
    return result


def read_sol_parts(path,password=None):
    path=Path(path)
    if path.stat().st_size>2_000_000_000:raise SolError('SOL文件超过2GB读取限制。')
    secret=password.encode('utf-8') if password is not None else None
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist())>30000:raise SolError('SOL条目数量超出读取限制。')
            entries={}
            for entry in archive.infolist():
                name=entry.filename.replace('\\','/')
                if name in entries:raise SolError('SOL包含重复文件条目。')
                entries[name]=entry
            def read(name,limit):
                if name not in entries:raise SolError('SOL缺少'+name)
                info=entries[name]
                if info.file_size>limit:raise SolError('SOL元数据超过读取限制。')
                try:
                    with archive.open(info,pwd=secret) as stream:data=stream.read(limit+1)
                except (RuntimeError,zipfile.BadZipFile) as exc:
                    if info.flag_bits&1:raise SolPasswordError('SOL密码缺失或不正确。') from None
                    raise SolError('SOL数据校验失败。') from exc
                if len(data)>limit:raise SolError('SOL元数据超过读取限制。')
                return data
            server=xml_root(read('SolutionFile/VmServer.xml',16*1024*1024))
            version,records=frame_records(read('SolutionFile/MoudleFrame',128*1024*1024))
    except zipfile.BadZipFile as exc:raise SolError('不是可读取的SOL容器。') from exc
    finally:secret=None
    return server,version,records


def sol_metadata(path,server,version,records):
    path=Path(path)
    modules={n.get('Index'):dict(n.attrib) for n in server.findall('.//ModuleBase/Module')}
    procedures={p.get('Index'):p.get('DisplayName','流程'+p.get('Index','')) for p in server.findall('./ProceduresInfo/ProcedureBase/Procedure')}
    owners={}
    for p in server.findall('./ProceduresInfo/ProcedureInsideModules/Procedure'):
        for child in p.findall('Inside'):owners[child.get('Index')]=p.get('Index')
    scripts=[]
    for ident,meta in modules.items():
        if meta.get('Name')!='ShellModule':continue
        name=ident+'-ShellModule.mdata'
        if name not in records:raise SolError('脚本模块数据缺失：'+ident)
        ports=_ports(records[name]);pid=owners.get(ident)
        scripts.append({'id':ident,'name':meta.get('DisplayName','脚本'+ident),
                        'flow_id':pid or '', 'flow':procedures.get(pid,'未归属流程'),**ports})
    return {'path':str(path.resolve()),'frame_version':version,'scripts':scripts,'read_only':True}


def read_sol(path,password=None):
    return sol_metadata(path,*read_sol_parts(path,password))
