"""UI control-flow smoke without Streamlit installed. Not a browser test."""
import importlib.util,sys,types,runpy
from pathlib import Path

class Rerun(BaseException):pass
class S(dict):
 def __getattr__(self,k):
  try:return self[k]
  except KeyError:raise AttributeError(k)
 def __setattr__(self,k,v):self[k]=v

class Ctx:
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def __getattr__(self,k):return getattr(st,k)

class Uploaded:
 def __init__(self,name,raw):self.name,self.raw=name,raw
 def getvalue(self):return self.raw

class FakeStreamlit(types.ModuleType):
 def __init__(self):
  super().__init__('streamlit')
  self.session_state=S();self.secrets={};self.sidebar=Ctx()
  source=Path(__file__).resolve().parents[1]/'sample_public_data.txt'
  self.upload=[Uploaded(source.name,source.read_bytes())]
  self.column_config=types.SimpleNamespace(TextColumn=lambda *a,**k:None,NumberColumn=lambda *a,**k:None,SelectboxColumn=lambda *a,**k:None)
 def __getattr__(self,k):
  if k in ('tabs','columns'):
   return lambda *a,**kw:([Ctx() for _ in (a[0] if k=='tabs' else range(a[0]))])
  if k in ('expander','spinner'):
   return lambda *a,**kw:Ctx()
  if k=='file_uploader':
   return lambda *a,**kw:None if kw.get('key')=='dataset_upload' else self.upload
  if k=='selectbox':
   def select(label,options,index=0,key=None,**kw):
    prev=self.session_state.get(key) if key else None
    val=prev if prev in options else options[index]
    if key:self.session_state[key]=val
    return val
   return select
  if k=='slider':return lambda *a,**kw:kw.get('value',kw.get('min_value',0))
  if k=='data_editor':return lambda df,*a,**kw:df
  if k=='text_input' or k=='text_area':
   def txt(label,*a,**kw):
    key=kw.get('key');v= self.session_state.get(key,kw.get('value','')) if key else kw.get('value','')
    if key:self.session_state[key]=v
    return v
   return txt
  if k=='checkbox':
   def chk(label,*a,**kw):
    key=kw.get('key');v=self.session_state.get(key,kw.get('value',False)) if key else kw.get('value',False)
    if key:self.session_state[key]=v
    return v
   return chk
  if k=='radio':return lambda label,options,**kw:options[0]
  if k=='multiselect':return lambda label,options,*a,**kw:kw.get('default',[])
  if k=='rerun':return lambda :(_ for _ in ()).throw(Rerun())
  if k=='button':return lambda *a,**kw:False
  if k=='download_button':return lambda *a,**kw:False
  if k=='metric':return lambda *a,**kw:None
  return lambda *a,**kw:None

st=FakeStreamlit();sys.modules['streamlit']=st
path=str(Path(__file__).resolve().parents[1]/'app.py')
sys.path.insert(0,str(Path(path).parent))
for tries in range(4):
 try:
  runpy.run_path(path,run_name='__main__')
  print('SUCCESS UI CONTROL FLOW, after reruns',tries,'dataset count',len(st.session_state.datasets),'domain',st.session_state.auto_domain)
  break
 except Rerun:
  print('rerun #',tries+1)
else:raise RuntimeError('infinite rerun')
