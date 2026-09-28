from __future__ import annotations
import math, random, subprocess, shutil
from pathlib import Path
import cv2, numpy as np

PRESETS={
 'Tokyo Chill - Rain':dict(zoom=0.045,pan=0.012,rain=.55,snow=0,bokeh=.28,grain=.018,warm=0),
 'Tokyo Chill - Neon':dict(zoom=0.035,pan=0.018,rain=.15,snow=0,bokeh=.48,grain=.02,warm=0),
 'Old Pop - First Snow':dict(zoom=0.018,pan=.004,rain=0,snow=.55,bokeh=.16,grain=.012,warm=.05),
 'Old Pop - Cafe':dict(zoom=0.015,pan=.006,rain=.22,snow=0,bokeh=.18,grain=.012,warm=.08),
 'Old Pop - Autumn':dict(zoom=0.014,pan=.005,rain=0,snow=0,bokeh=.12,grain=.014,warm=.09),
}

def _cover(img,w,h):
    ih,iw=img.shape[:2]; s=max(w/iw,h/ih); nw,nh=int(iw*s),int(ih*s)
    x=cv2.resize(img,(nw,nh),interpolation=cv2.INTER_LANCZOS4)
    x0=(nw-w)//2; y0=(nh-h)//2
    return x[y0:y0+h,x0:x0+w].copy()

def _camera(base,t,p):
    h,w=base.shape[:2]; ease=.5-.5*math.cos(math.pi*t)
    scale=1+p['zoom']*ease
    rw,rh=int(w*scale),int(h*scale)
    z=cv2.resize(base,(rw,rh),interpolation=cv2.INTER_CUBIC)
    maxx=max(0,rw-w); maxy=max(0,rh-h)
    drift=p['pan']*math.sin(math.pi*t)
    cx=int(maxx/2 + drift*w); cy=int(maxy/2 - .12*math.sin(math.pi*t)*maxy)
    cx=max(0,min(maxx,cx)); cy=max(0,min(maxy,cy))
    return z[cy:cy+h,cx:cx+w].copy()

def _rain(frame,seed,amount,t):
    if amount<=0:return frame
    rng=random.Random(seed); h,w=frame.shape[:2]; layer=np.zeros_like(frame)
    n=int(110*amount)
    for i in range(n):
        x=(rng.randint(-w//5,w)+int(t*180*(.5+rng.random())))% (w+80)-40
        y=(rng.randint(-h,h)+int(t*h*2.2*(.5+rng.random())))%(h+100)-50
        L=rng.randint(18,50); cv2.line(layer,(x,y),(x-7,y+L),(150,170,185),rng.choice([1,1,2]),cv2.LINE_AA)
    return cv2.addWeighted(frame,1,layer,.28,0)

def _snow(frame,seed,amount,t):
    if amount<=0:return frame
    rng=random.Random(seed); h,w=frame.shape[:2]; layer=np.zeros_like(frame)
    for i in range(int(90*amount)):
        r=rng.choice([1,1,2,2,3]); x=(rng.randint(0,w)+int(math.sin(t*6+i)*20))%w
        y=(rng.randint(-h,h)+int(t*h*(.25+rng.random()*.55)))%(h+40)-20
        cv2.circle(layer,(x,y),r,(245,245,245),-1,cv2.LINE_AA)
    return cv2.addWeighted(frame,1,layer,.62,0)

def _bokeh(frame,seed,amount,t):
    if amount<=0:return frame
    rng=random.Random(seed); h,w=frame.shape[:2]; layer=np.zeros_like(frame)
    for i in range(int(18*amount+2)):
        x=rng.randint(0,w); y=rng.randint(0,h); r=rng.randint(8,35)
        pulse=.45+.25*math.sin(2*math.pi*t+rng.random()*6.28)
        v=int(190*pulse); cv2.circle(layer,(x,y),r,(v,v,v),-1,cv2.LINE_AA)
    layer=cv2.GaussianBlur(layer,(0,0),12)
    return cv2.addWeighted(frame,1,layer,.22,0)

def _finish(frame,p,t,seed):
    if p['warm']:
        f=frame.astype(np.float32); f[:,:,2]*=1+p['warm']; f[:,:,0]*=1-p['warm']*.35; frame=np.clip(f,0,255).astype(np.uint8)
    if p['grain']:
        rng=np.random.default_rng(seed); noise=rng.normal(0,255*p['grain'],frame.shape[:2]).astype(np.float32)
        f=frame.astype(np.float32); f += noise[:,:,None]; frame=np.clip(f,0,255).astype(np.uint8)
    return frame

def _read_unicode(path):
    try:
        data=np.fromfile(str(path),dtype=np.uint8)
        img=cv2.imdecode(data,cv2.IMREAD_COLOR)
    except Exception as e:
        raise ValueError(f'이미지를 읽을 수 없습니다: {path}\n{e}') from e
    if img is None: raise ValueError(f'이미지를 읽을 수 없습니다: {path}')
    return img

def render(input_path, output_path, preset, duration=8, fps=30, width=1920,height=1080,intensity=1.0):
    img=_read_unicode(input_path)
    base=_cover(img,width,height); p=PRESETS[preset].copy()
    for k in ('zoom','pan','rain','snow','bokeh','grain','warm'): p[k]*=intensity
    temp=Path(output_path).with_suffix('.silent.mp4')
    fourcc=cv2.VideoWriter_fourcc(*'mp4v'); out=cv2.VideoWriter(str(temp),fourcc,fps,(width,height))
    total=max(1,int(duration*fps))
    for i in range(total):
        # smooth forward/back cycle so loop boundary is visually gentle
        phase=i/(total-1) if total>1 else 0; loop_t=.5-.5*math.cos(2*math.pi*phase)
        f=_camera(base,loop_t,p); f=_bokeh(f,31,p['bokeh'],phase); f=_rain(f,17,p['rain'],phase); f=_snow(f,23,p['snow'],phase); f=_finish(f,p,phase,i+99)
        out.write(f)
    out.release()
    ff=shutil.which('ffmpeg')
    if ff:
        cmd=[ff,'-y','-i',str(temp),'-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(output_path)]
        subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True); temp.unlink(missing_ok=True)
    else: shutil.move(str(temp),str(output_path))
    return str(output_path)
