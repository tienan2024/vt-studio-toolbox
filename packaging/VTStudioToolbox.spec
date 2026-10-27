# Build from this checked-in specification so host PATH cannot shadow Windows ICU.
from pathlib import Path
import os

project = Path(SPECPATH).parent
system_icu = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'icuuc.dll'
if not system_icu.is_file():
    raise RuntimeError('This portable build requires Windows system ICU (Windows 10/11).')

a = Analysis(
    [str(project / 'launcher.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / 'app.ico'), '.'), (str(project / 'legacy' / 'vt-engine.exe'), 'legacy'),
           (str(project / 'legacy' / 'README.md'), 'legacy'),
           (str(project / 'legacy' / 'provenance.json'), 'legacy'),
           (str(project / 'assets' / 'check.svg'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['torch', 'cv2', 'matplotlib', 'tkinter',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
    noarchive=False,
)
# Qt 6.11 uses Microsoft's unversioned ICU API from System32. The build host's
# Poppler PATH ships another icuuc.dll exporting *_78 instead. Never ship that
# shadow DLL (nor another unversioned Windows ICU DLL); let Windows resolve it.
windows_icu_names = {'icuuc.dll', 'icuin.dll', 'icu.dll'}
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in windows_icu_names]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VTStudioToolbox',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(project / 'app.ico'))
cli_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='VTStudioCLI',
              debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              console=True, icon=str(project / 'app.ico'))
coll = COLLECT(exe, cli_exe, a.binaries, a.datas, strip=False, upx=False, name='VTStudioToolbox')
