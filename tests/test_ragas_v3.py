"""Offline regression tests: skip API / real RAGAS network calls."""
import io
import sys
import types
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from auditor.ragas_engine import (RAGAS_NON_LLM, selected_judges, run_ragas,
                                  merge_assessment_status)
from auditor.reports import excel_report
from auditor.pro_reports import professional_report
from auditor.frameworks import CONTROLS, RISK_WEIGHTS


def test_four_selection_modes():
    assert selected_judges(False,False)==[]
    assert selected_judges(True,False)==['GPT']
    assert selected_judges(False,True)==['Gemini']
    assert selected_judges(True,True)==['GPT','Gemini']


def test_no_metrics_run_is_not_a_zero():
    x={'metrics':[{'status':'미실시','score':None}]}
    assert '평가 보류' in merge_assessment_status(x,{})


def test_no_ragas_package_is_not_falsely_pass(monkeypatch):
    # Force true import failure even if a developer installs ragas later.
    sys.modules.pop('ragas',None)
    import builtins
    real_import=builtins.__import__
    def blocked(name,*args,**kwargs):
        if name=='ragas' or name.startswith('ragas.'):
            raise ImportError('test missing')
        return real_import(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',blocked)
    result=run_ragas('질문','답변',['근거'],reference='답변')
    assert result['metrics']
    assert all(x['score'] is None for x in result['metrics'])
    assert result['warnings']


def _fake_ragas(monkeypatch):
    ragas=types.ModuleType('ragas')
    ragas.__path__=[];ragas.__version__='0.4.4-test'
    sub=types.ModuleType('ragas.metrics')
    sub.__path__=[]
    collections=types.ModuleType('ragas.metrics.collections')
    class FakeMetric:
        def __init__(self,**kwargs): pass
        def score(self,**kwargs):return SimpleNamespace(value=0.75)
    for cls in ('ExactMatch','NonLLMStringSimilarity','Faithfulness','FactualCorrectness','AnswerRelevancy','ContextPrecision','ContextRecall'):
        setattr(collections,cls,FakeMetric)
    collections.DistanceMeasure=SimpleNamespace(LEVENSHTEIN='levenshtein')
    sub.collections=collections
    monkeypatch.setitem(sys.modules,'ragas',ragas)
    monkeypatch.setitem(sys.modules,'ragas.metrics',sub)
    monkeypatch.setitem(sys.modules,'ragas.metrics.collections',collections)


def test_gpt_gemini_off_ragas_off_reference_available(monkeypatch):
    _fake_ragas(monkeypatch)
    got=run_ragas('시행일은?', '시행일은 10월입니다.', ['시행일 10월'],reference='시행일은 10월입니다.',
                  use_llm=False,enabled_metrics=list(RAGAS_NON_LLM))
    assert got['llm_enabled'] is False
    assert all(x['status']=='완료' and x['score']==.75 for x in got['metrics'])
    assert merge_assessment_status(got,{})=='RAGAS 단독 평가(정량 항목만)'


def test_no_reference_skips_only_reference_dependent_metrics(monkeypatch):
    _fake_ragas(monkeypatch)
    got=run_ragas('어디?', '여기', ['문서'],reference='',use_llm=False)
    assert all(x['status']=='미실시' for x in got['metrics'])
    assert all(x['score'] is None for x in got['metrics'])


def test_unchecked_llm_does_not_invoke_api(monkeypatch):
    _fake_ragas(monkeypatch)
    got=run_ragas('질문?', '답변', ['근거'],reference='정답',
                  use_llm=False,api_key='should-not-be-used',enabled_metrics=['Faithfulness'])
    assert got['metrics'][0]['status']=='미실시'
    assert got['metrics'][0]['score'] is None


def test_single_report_without_judges_has_no_false_risk():
    from openpyxl import load_workbook
    report={"timestamp":"2026-11-17 08:00","question":"어디?","answer":"여기","target":"외부 답변",
        "mode":"파일","sources":[],"web_urls":[],"judges":{},"selected_judges":[],
        "ragas":{"version":"0.4.4","metrics":[{"metric":"Exact Match","status":"완료","score":0.0}]},
        "disagreements":[]}
    workbook=load_workbook(io.BytesIO(excel_report(report)),read_only=True)
    vals=list(workbook['개요'].values)
    assert any(row[0]=='LLM 심사 평균' and row[1]=='미실시' for row in vals)
    assert any(row[0]=='잠정 위험등급' and row[1]=='판정 보류' for row in vals)
    assert 'RAGAS정량지표' in workbook.sheetnames
    assert workbook['RAGAS정량지표']['C2'].value==0
    workbook.close()


def test_professional_report_ragas_worksheet():
    from openpyxl import load_workbook
    row={**CONTROLS[0],"상태":"미평가","증적":"","판단사유":""}
    frows=[{**c,"상태":"미평가","증적":"","판단사유":""} for c in CONTROLS]
    rrows=[{"id":i,"부문":p,"항목":n,"배점":w,"경감수준":"미평가","증적":"","판단사유":""} for i,p,n,w in RISK_WEIGHTS]
    report={"timestamp":"2026-11-17","question":"질문","target":"외부","judges":{},
        "ragas":{"version":"0.4.4","metrics":[{"metric":"Faithfulness","score":None,"status":"미실시","reason":"no llm"}]},
        "assessment_status":"평가 보류"}
    data=professional_report([report],frows,rrows,{},[])
    book=load_workbook(io.BytesIO(data),read_only=True)
    assert book['RAGAS 지표']['E2'].value=='미실시'
    assert book['RAGAS 지표']['F2'].value in ('', None)
    assert book['답변 평가목록']['K2'].value=='평가 보류'
    book.close()


def test_ragas_llm_adapter_calls_official_collection(monkeypatch):
    _fake_ragas(monkeypatch)
    fake_openai=types.ModuleType('openai')
    fake_openai.AsyncOpenAI=lambda **k: object()
    monkeypatch.setitem(sys.modules,'openai',fake_openai)
    llms=types.ModuleType('ragas.llms')
    llms.llm_factory=lambda name,client: object()
    monkeypatch.setitem(sys.modules,'ragas.llms',llms)
    result=run_ragas('보관 기간?', '3년입니다.', ['보관 기간은 3년'],
                      use_llm=True,api_key='fake-test-key',enabled_metrics=['Faithfulness'])
    assert result['metrics'][0]['metric']=='Faithfulness'
    assert result['metrics'][0]['status']=='완료'
    assert result['metrics'][0]['score']==0.75
    assert result['llm_enabled']


def test_ragas_reference_score_with_mock_llm(monkeypatch):
    _fake_ragas(monkeypatch)
    fake_openai=types.ModuleType('openai')
    fake_openai.AsyncOpenAI=lambda **k: object()
    monkeypatch.setitem(sys.modules,'openai',fake_openai)
    llms=types.ModuleType('ragas.llms');llms.llm_factory=lambda name,client: object()
    monkeypatch.setitem(sys.modules,'ragas.llms',llms)
    result=run_ragas('질문', '대답', ['근거'],reference='정답',
                      use_llm=True,api_key='fake-test-key',enabled_metrics=['Factual Correctness'])
    assert result['metrics'][0]['status']=='완료'
