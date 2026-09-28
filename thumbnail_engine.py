from __future__ import annotations
from pathlib import Path
import json, csv, time
import cv2, numpy as np

STRATEGIES={
 'Tokyo Chill':[
  ('A_PERSON','인물 중심','close'),('B_EMOTION','감정/메시지 중심','medium'),('C_STORY','상황/세계관 중심','wide')],
 'OLD POP LOUNGE':[
  ('A_PERSON','인물 중심','close'),('B_MEMORY','추억/감정 중심','medium'),('C_SCENERY','풍경/계절 중심','wide')],
}

def _read(path):
 im=cv2.imread(str(path),cv2.IMREAD_COLOR)
 if im is None: raise ValueError('이미지를 읽을 수 없습니다.')
 return im

def _cover(im,w=1280,h=720,scale=1.0,x_bias=0.5,y_bias=0.5):
 ih,iw=im.shape[:2]; s=max(w/iw,h/ih)*scale; nw,nh=max(w,int(iw*s)),max(h,int(ih*s))
 z=cv2.resize(im,(nw,nh),interpolation=cv2.INTER_LANCZOS4)
 maxx,maxy=nw-w,nh-h; x=int(maxx*x_bias); y=int(maxy*y_bias)
 x=max(0,min(maxx,x)); y=max(0,min(maxy,y)); return z[y:y+h,x:x+w].copy()

def _grade(im,mode):
 f=im.astype(np.float32)
 if mode=='close':
  # subject candidate: slightly stronger local presence, no generative edits
  f=(f-127.5)*1.035+127.5
 elif mode=='medium':
  f[:,:,2]*=1.025; f[:,:,0]*=.99
 else:
  f=(f-127.5)*.97+127.5
 return np.clip(f,0,255).astype(np.uint8)

def generate_candidates(src,out_dir,channel):
 src=Path(src); out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); im=_read(src)
 specs=STRATEGIES[channel]; made=[]
 # Non-generative A/B/C: distinct framing and visual emphasis. User can later replace with separate source images.
 params={'close':(1.16,.5,.45),'medium':(1.06,.5,.48),'wide':(1.0,.5,.5)}
 for code,label,mode in specs:
  scale,xb,yb=params[mode]; x=_grade(_cover(im,scale=scale,x_bias=xb,y_bias=yb),mode)
  p=out/f'{src.stem}_{code}.jpg'; cv2.imwrite(str(p),x,[int(cv2.IMWRITE_JPEG_QUALITY),95]); made.append((code,label,str(p)))
 manifest={'version':'0.2','channel':channel,'source':str(src),'created_at':time.strftime('%Y-%m-%d %H:%M:%S'),
           'candidates':[{'code':a,'strategy':b,'file':c} for a,b,c in made],
           'note':'후보는 단순 색상 변경이 아니라 프레이밍/메시지 역할을 분리한다. v0.2는 원본 보존형이며 생성형 AI를 사용하지 않는다.'}
 (out/f'{src.stem}_dynamic_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 return made

def record_test(db_path,episode,channel,a,b,c,winner,notes=''):
 db=Path(db_path); db.parent.mkdir(parents=True,exist_ok=True); exists=db.exists()
 with db.open('a',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f)
  if not exists:w.writerow(['timestamp','episode','channel','A','B','C','winner','notes'])
  w.writerow([time.strftime('%Y-%m-%d %H:%M:%S'),episode,channel,a,b,c,winner,notes])

def summarize(db_path,channel=None):
 p=Path(db_path)
 if not p.exists(): return '아직 기록된 테스트가 없습니다.'
 rows=list(csv.DictReader(p.open(encoding='utf-8-sig')))
 if channel: rows=[r for r in rows if r['channel']==channel]
 if not rows:return '해당 채널 기록이 없습니다.'
 wins={}; sums={'A':0.0,'B':0.0,'C':0.0}; n=0
 for r in rows:
  wins[r['winner']]=wins.get(r['winner'],0)+1
  try:
   for k in sums:sums[k]+=float(r[k] or 0)
   n+=1
  except ValueError: pass
 avgs={k:(v/n if n else 0) for k,v in sums.items()}
 return f"기록 {len(rows)}회 | 승자 A/B/C: {wins.get('A',0)}/{wins.get('B',0)}/{wins.get('C',0)} | 평균 입력값 A/B/C: {avgs['A']:.1f}/{avgs['B']:.1f}/{avgs['C']:.1f}"
