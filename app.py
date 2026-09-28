import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from motion_engine import render,PRESETS
from thumbnail_engine import generate_candidates,record_test,summarize

class App(tk.Tk):
 def __init__(self):
  super().__init__(); self.title('YouTube Dynamic Thumbnail Studio v0.2'); self.geometry('780x650'); self.resizable(False,False)
  self.src=tk.StringVar(); self.channel=tk.StringVar(value='Tokyo Chill'); self.preset=tk.StringVar(value='Tokyo Chill - Rain')
  self.duration=tk.IntVar(value=8); self.intensity=tk.DoubleVar(value=1.0); self.status=tk.StringVar(value='이미지를 선택하세요.')
  self.episode=tk.StringVar(value='EP001'); self.a=tk.StringVar();self.b=tk.StringVar();self.c=tk.StringVar();self.winner=tk.StringVar(value='B')
  self.db=Path.home()/'MotionThumbnailStudio'/'youtube_test_history.csv'
  ttk.Label(self,text='YOUTUBE DYNAMIC THUMBNAIL STUDIO',font=('Segoe UI',18,'bold')).pack(pady=(18,4))
  ttk.Label(self,text='YouTube 3후보 전략 + Motion Intro · 원본 보존형',foreground='#555').pack()
  nb=ttk.Notebook(self);nb.pack(fill='both',expand=True,padx=16,pady=12)
  self._tab_candidates(nb);self._tab_motion(nb);self._tab_history(nb)
  ttk.Label(self,textvariable=self.status,wraplength=730).pack(pady=(0,10))
 def source_row(self,parent):
  f=ttk.Frame(parent);f.pack(fill='x',padx=16,pady=10);ttk.Entry(f,textvariable=self.src,width=72).pack(side='left',fill='x',expand=True);ttk.Button(f,text='이미지 선택',command=self.pick).pack(side='left',padx=8)
 def pick(self):
  p=filedialog.askopenfilename(filetypes=[('Images','*.jpg *.jpeg *.png *.webp')]);
  if p:self.src.set(p);self.status.set('준비 완료: '+Path(p).name)
 def _tab_candidates(self,nb):
  t=ttk.Frame(nb);nb.add(t,text='① 3후보 만들기');self.source_row(t)
  f=ttk.Frame(t);f.pack(fill='x',padx=16,pady=8);ttk.Label(f,text='채널',width=14).pack(side='left');ttk.Combobox(f,textvariable=self.channel,values=['Tokyo Chill','OLD POP LOUNGE'],state='readonly',width=28).pack(side='left')
  ttk.Label(t,text='A = 인물 중심   ·   B = 감정/추억 중심   ·   C = 스토리/풍경 중심',font=('Segoe UI',11,'bold')).pack(pady=18)
  ttk.Label(t,text='v0.2는 AI 재생성 없이 원본을 보존하면서 프레이밍과 역할이 다른 3개 후보를 만듭니다.\nYouTube Studio의 썸네일 테스트/동적 썸네일 후보로 사용합니다.',justify='center').pack(pady=6)
  ttk.Button(t,text='★ A/B/C 3개 생성',command=self.make3).pack(pady=28,ipadx=30,ipady=8)
 def make3(self):
  if not self.src.get():return messagebox.showwarning('확인','이미지를 선택하세요.')
  src=Path(self.src.get()); out=filedialog.askdirectory(initialdir=src.parent,title='3개 후보 저장 폴더')
  if not out:return
  try:
   made=generate_candidates(src,out,self.channel.get());self.status.set('3후보 완료: '+' | '.join(Path(x[2]).name for x in made));messagebox.showinfo('완료','A/B/C 후보 3개와 manifest JSON을 만들었습니다.')
  except Exception as e:messagebox.showerror('오류',str(e))
 def _tab_motion(self,nb):
  t=ttk.Frame(nb);nb.add(t,text='② Motion Intro');self.source_row(t)
  for label,var,vals in [('프리셋',self.preset,list(PRESETS)),('길이(초)',self.duration,[6,8,10,12])]:
   f=ttk.Frame(t);f.pack(fill='x',padx=16,pady=8);ttk.Label(f,text=label,width=14).pack(side='left');ttk.Combobox(f,textvariable=var,values=vals,state='readonly',width=35).pack(side='left')
  f=ttk.Frame(t);f.pack(fill='x',padx=16,pady=8);ttk.Label(f,text='움직임 강도',width=14).pack(side='left');ttk.Scale(f,from_=.5,to=1.5,variable=self.intensity,orient='horizontal',length=360).pack(side='left')
  ttk.Button(t,text='★ MP4 만들기',command=self.go_motion).pack(pady=24,ipadx=35,ipady=9)
  ttk.Label(t,text='1920×1080 · 30fps · H.264(FFmpeg 설치 시) · 얼굴 AI 재생성 없음',foreground='#555').pack()
 def go_motion(self):
  if not self.src.get():return messagebox.showwarning('확인','이미지를 선택하세요.')
  src=Path(self.src.get());out=filedialog.asksaveasfilename(initialdir=src.parent,initialfile=src.stem+'_MOTION.mp4',defaultextension='.mp4',filetypes=[('MP4','*.mp4')])
  if not out:return
  self.status.set('렌더링 중...');self.update_idletasks()
  try:render(src,out,self.preset.get(),self.duration.get(),intensity=self.intensity.get());self.status.set('완료: '+out);messagebox.showinfo('완료','Motion Intro 생성 완료')
  except Exception as e:messagebox.showerror('오류',str(e))
 def _tab_history(self,nb):
  t=ttk.Frame(nb);nb.add(t,text='③ 테스트 기록')
  fields=[('영상/회차',self.episode),('A 결과',self.a),('B 결과',self.b),('C 결과',self.c)]
  for label,var in fields:
   f=ttk.Frame(t);f.pack(fill='x',padx=20,pady=7);ttk.Label(f,text=label,width=14).pack(side='left');ttk.Entry(f,textvariable=var,width=24).pack(side='left')
  f=ttk.Frame(t);f.pack(fill='x',padx=20,pady=7);ttk.Label(f,text='승자',width=14).pack(side='left');ttk.Combobox(f,textvariable=self.winner,values=['A','B','C','판정없음'],state='readonly',width=21).pack(side='left')
  ttk.Button(t,text='테스트 결과 저장',command=self.save_history).pack(pady=18,ipadx=24,ipady=6)
  self.summary=tk.StringVar(value='아직 요약하지 않았습니다.');ttk.Label(t,textvariable=self.summary,wraplength=680,justify='center').pack(padx=20,pady=12)
  ttk.Button(t,text='현재 채널 누적 요약',command=lambda:self.summary.set(summarize(self.db,self.channel.get()))).pack()
  ttk.Label(t,text='※ A/B/C 값은 YouTube Studio에서 확인한 비교 지표를 그대로 기록하세요.\n이 프로그램은 임의로 CTR/시청시간을 승자로 판단하지 않습니다.',foreground='#555',justify='center').pack(pady=20)
 def save_history(self):
  try:record_test(self.db,self.episode.get(),self.channel.get(),self.a.get(),self.b.get(),self.c.get(),self.winner.get());self.summary.set(summarize(self.db,self.channel.get()));self.status.set('테스트 기록 저장: '+str(self.db))
  except Exception as e:messagebox.showerror('오류',str(e))
if __name__=='__main__':App().mainloop()
