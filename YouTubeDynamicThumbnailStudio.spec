# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from importlib.metadata import distribution
from PyInstaller.utils.hooks import collect_all, collect_submodules
datas=[]; binaries=[]; hiddenimports=[]
for package in ('cv2','PIL','uharfbuzz','uniseg','tkinterdnd2'):
    d,b,h=collect_all(package); datas+=d; binaries+=b; hiddenimports+=h
# fontTools' full package collection also pulls optional scipy/matplotlib tooling.
# Runtime font metadata inspection only needs TTFont/TTCollection and their tables.
hiddenimports += collect_submodules('fontTools.ttLib')
for package in ('skia-python','uharfbuzz','fonttools','uniseg','tkinterdnd2'):
    dist=distribution(package)
    for item in dist.files or ():
        if 'license' in str(item).casefold() or 'notice' in str(item).casefold():
            source=dist.locate_file(item)
            if source.is_file(): datas.append((str(source),f'third_party/python/{package}'))
ffmpeg_bins=list(Path('vendor/ffmpeg/bin').glob('*.dll'))
ffmpeg_exe=Path('vendor/ffmpeg/bin/ffmpeg.exe')
if not ffmpeg_exe.is_file() or not ffmpeg_bins:
    raise SystemExit('Pinned LGPL FFmpeg bundle missing. Run scripts\\prepare_ffmpeg.ps1 first.')
# Motion launches FFmpeg as a separate process; keep its runtime together as data
# so PyInstaller does not duplicate each DLL both beside the app and in ydts_ffmpeg.
datas += [(str(path),'ydts_ffmpeg') for path in ffmpeg_bins]
datas.append((str(ffmpeg_exe),'ydts_ffmpeg'))
for license_file in (Path('vendor/ffmpeg/LICENSE.txt'), Path('vendor/ffmpeg/COPYING.GPLv3')):
    if license_file.is_file(): datas.append((str(license_file),'third_party'))
datas.append(('THIRD_PARTY_NOTICES.txt','third_party'))
a=Analysis(['app.py'],pathex=[],binaries=binaries,datas=datas,hiddenimports=hiddenimports,noarchive=False)
# Analysis also discovers the FFmpeg DLLs as top-level dependencies. The external
# ffmpeg.exe loads the colocated copies in ydts_ffmpeg, so keep only that bundle.
ffmpeg_paths={path.resolve() for path in ffmpeg_bins}
a.binaries=[entry for entry in a.binaries
            if not (Path(entry[1]).resolve() in ffmpeg_paths and Path(entry[0]).parent == Path('.'))]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='YouTubeDynamicThumbnailStudio',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='YouTubeDynamicThumbnailStudio')
