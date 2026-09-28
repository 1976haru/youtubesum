# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
datas=[]; binaries=[]; hiddenimports=[]
for package in ('cv2','PIL'):
    d,b,h=collect_all(package); datas+=d; binaries+=b; hiddenimports+=h
ffmpeg_bins=list(Path('vendor/ffmpeg/bin').glob('*.dll'))
ffmpeg_exe=Path('vendor/ffmpeg/bin/ffmpeg.exe')
if not ffmpeg_exe.is_file() or not ffmpeg_bins:
    raise SystemExit('Pinned LGPL FFmpeg bundle missing. Run scripts\\prepare_ffmpeg.ps1 first.')
binaries += [(str(path),'ydts_ffmpeg') for path in ffmpeg_bins]
binaries.append((str(ffmpeg_exe),'ydts_ffmpeg'))
for license_file in (Path('vendor/ffmpeg/LICENSE.txt'), Path('vendor/ffmpeg/COPYING.GPLv3')):
    if license_file.is_file(): datas.append((str(license_file),'third_party'))
datas.append(('THIRD_PARTY_NOTICES.txt','third_party'))
a=Analysis(['app.py'],pathex=[],binaries=binaries,datas=datas,hiddenimports=hiddenimports,noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='YouTubeDynamicThumbnailStudio',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
