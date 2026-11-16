"""Local rotating logs and bounded, redacted diagnostic artifacts. No network uploads."""
from datetime import datetime,timezone
import json,logging,os,platform,re,struct,sys,threading,traceback,uuid,weakref,zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

_store=None
_provider=None
_qt_handler=None
_secret_key=re.compile(r'password|passwd|secret|token|api.?key|authorization|credential|private.?key|密码|口令',re.I)
_secret_text=re.compile(r'((?:password|passwd|secret|token|api[_-]?key|authorization|密码|口令)[\"\x27]?\s*[:=]\s*[\"\x27]?)([^\s,;\"\x27}]+)',re.I)
_quoted_secret=re.compile(r'((?:password|passwd|secret|token|api[_-]?key|authorization|密码|口令)[\"\x27]?\s*[:=]\s*)([\"\x27])(.*?)\2',re.I|re.S)


def redact_text(value):
    value=_quoted_secret.sub(r'\1\2<redacted>\2',value)
    value=_secret_text.sub(r'\1<redacted>',value)
    value=re.sub(r'(?i)\bBearer\s+\S+','Bearer <redacted>',value)
    return re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----','<redacted private key>',value,flags=re.S)


def redact(value,depth=0):
    if depth>18:return '<depth limit>'
    if isinstance(value,dict):return {str(k):'<redacted>' if _secret_key.search(str(k)) else redact(v,depth+1) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [redact(v,depth+1) for v in value[:5000]]
    if isinstance(value,str):
        return redact_text(value)[:48000]
    if value is None or isinstance(value,(bool,int,float)):return value
    return redact(str(value),depth+1)


class RedactingFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))


class DiagnosticStore:
    def __init__(self,directory=None):
        from engine import VERSION
        self.version=VERSION
        self.directory=Path(directory) if directory else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VTStudioToolbox'/'diagnostics'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.session=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())+'-'+uuid.uuid4().hex[:6]
        self.log_path=self.directory/('session-'+self.session+'.log')
        self.handler=RotatingFileHandler(self.log_path,maxBytes=2_000_000,backupCount=2,encoding='utf-8')
        self.handler.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger=logging.getLogger('vt.'+self.session);self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler);self.logger.propagate=False
        self._prune('session-*.log*',20)

    def _prune(self,pattern,keep):
        files=sorted(self.directory.glob(pattern),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in files[keep:]:
            try:path.unlink()
            except OSError:pass

    def event(self,component,event,log_level=logging.INFO,**data):
        self.logger.log(log_level,'%s %s',component,json.dumps(redact({'event':event,**data}),ensure_ascii=False,default=str))

    def snapshot(self,reason,data,screen=None):
        name='snapshot-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:6]
        path=self.directory/(name+'.json')
        artifact={'schema':'vt-debug-snapshot/1','version':self.version,'session':self.session,
            'created_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
            'reason':reason,'data':redact(data)}
        if screen is not None:
            picture=self.directory/(name+'.png')
            if screen.save(str(picture),'PNG'):artifact['screenshot']=picture.name
        encoded=json.dumps(artifact,ensure_ascii=False,indent=2,default=str)
        if len(encoded.encode('utf-8'))>4_000_000:
            artifact['data']={'error':'Snapshot exceeded 4MB; inspect the session log.'}
            encoded=json.dumps(artifact,ensure_ascii=False,indent=2)
        path.write_text(encoded,encoding='utf-8');self._prune('snapshot-*.json',20)
        # Remove only orphan screenshots produced by this feature.
        for png in self.directory.glob('snapshot-*.png'):
            if not png.with_suffix('.json').exists():
                try:png.unlink()
                except OSError:pass
        self.event('diagnostics','snapshot_saved',reason=reason,path=path.name)
        return path

    def tail(self):
        self.handler.flush()
        with self.log_path.open('rb') as stream:
            stream.seek(max(0,self.log_path.stat().st_size-96000));return redact(stream.read().decode('utf-8',errors='replace'))

    def export(self,path):
        self.handler.flush();selected=[];skipped=[];total=0
        files=sorted([*self.directory.glob('session-*.log*'),*self.directory.glob('snapshot-*.json'),*self.directory.glob('snapshot-*.png')],key=lambda p:p.stat().st_mtime,reverse=True)
        for source in files:
            size=source.stat().st_size
            if size>12_000_000 or total+size>32_000_000:skipped.append(source.name);continue
            selected.append(source);total+=size
        manifest={'schema':'vt-debug-bundle/1','version':self.version,'session':self.session,
            'created_at':datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
            'files':[p.name for p in selected],'skipped':skipped,'automatic_upload':False}
        with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            for source in selected:
                # Reapply redaction when exporting text, including files from previous sessions.
                if source.suffix=='.png':data=source.read_bytes()
                elif source.suffix=='.json':
                    raw=source.read_text(encoding='utf-8',errors='replace')
                    try:data=json.dumps(redact(json.loads(raw)),ensure_ascii=False,indent=2).encode('utf-8')
                    except ValueError:data=redact_text(raw).encode('utf-8')
                else:data=redact_text(source.read_text(encoding='utf-8',errors='replace')).encode('utf-8')
                archive.writestr(source.name,data)
        return Path(path)


def setup_logging(directory=None):
    global _store
    if _store is not None:return _store
    try:
        _store=DiagnosticStore(directory)
        logging.getLogger().addHandler(_store.handler);logging.getLogger().setLevel(logging.INFO)
        logging.captureWarnings(True)
        old_hook=sys.excepthook
        def exception_hook(kind,value,tb):
            event('runtime','unhandled_exception',error=''.join(traceback.format_exception(kind,value,tb)),error_event=True)
            if sys.stderr is not None:old_hook(kind,value,tb)
        sys.excepthook=exception_hook
        old_thread=threading.excepthook
        def thread_hook(args):
            exception_hook(args.exc_type,args.exc_value,args.exc_traceback)
            if sys.stderr is not None:old_thread(args)
        threading.excepthook=thread_hook
        system='Windows '+'.'.join(str(v) for v in sys.getwindowsversion()[:3]) if hasattr(sys,'getwindowsversion') else platform.system()
        _store.event('runtime','startup',version=_store.version,python=sys.version.split()[0],system=system,architecture=str(struct.calcsize('P')*8)+'bit')
    except OSError:
        # A read-only profile must not prevent the toolbox itself from starting.
        _store=None
    return _store


def set_state_provider(provider):
    global _provider
    _provider=weakref.WeakMethod(provider)


def current_state():
    callback=_provider() if _provider else None
    if callback and threading.current_thread() is threading.main_thread():
        try:return redact(callback())
        except Exception as exc:return {'snapshot_error':redact(str(exc))}
    return {}


def event(component,name,error_event=False,**data):
    store=setup_logging()
    if not store:return
    try:
        store.event(component,name,log_level=logging.ERROR if error_event else logging.INFO,**data)
        if error_event:store.snapshot(component+'.'+name,{'event':data,'state':current_state()})
    except (OSError,ValueError):pass


def snapshot(reason,data=None,screen=None):
    store=setup_logging()
    if not store:raise OSError('无法创建本地调试目录，请检查用户目录写入权限。')
    return store.snapshot(reason,{'state':current_state(),'details':data},screen)


def exception(component,name,exc,**data):
    event(component,name,error=str(exc),traceback=traceback.format_exc(),error_event=True,**data)


def setup_qt_logging():
    global _qt_handler
    if _qt_handler is not None:return
    from PySide6.QtCore import qInstallMessageHandler,QtMsgType
    def handler(kind,context,message):
        store=setup_logging()
        if store:store.logger.log(logging.DEBUG if kind==QtMsgType.QtDebugMsg else logging.WARNING,'Qt %s',message)
    _qt_handler=handler;qInstallMessageHandler(handler)
