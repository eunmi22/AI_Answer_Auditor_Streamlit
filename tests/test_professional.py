"""Offline deterministic tests: do not use API keys or network."""
import io
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from auditor.frameworks import CONTROLS, RISK_WEIGHTS, controls_summary, calculate_residual_risk
from auditor.datasets import SAMPLE_CASES, template_csv, parse_dataset
from auditor.pro_reports import professional_report
from auditor.evaluation import normalize_rubric, build_prompt, validate_result
from auditor.security import detect_sensitive, redact_pii


def frows():
    return [{**r,'상태':'미평가','증적':'','판단사유':''} for r in CONTROLS]

def rrows():
    return [{'id':i,'부문':part,'항목':name,'배점':weight,'경감수준':'미평가','증적':'','판단사유':''}
            for i,part,name,weight in RISK_WEIGHTS]

def test_controllers_exact_structure():
    assert len(CONTROLS)==28
    assert len({r['id'] for r in CONTROLS})==28
    assert len([c for c in CONTROLS if c['평가계층']=='안전성'])==12
    assert len([c for c in CONTROLS if c['평가계층']=='신뢰성'])==16
    assert len(set(r['평가영역'] for r in CONTROLS))==10

def test_not_assessed_does_not_count_as_pass():
    s=controls_summary(frows())
    assert s['not_reviewed']==28 and s['reviewed']==0 and not s['all_reviewed']

def test_conformity_requires_evidence():
    r=frows(); r[0]['상태']='충족'
    with pytest.raises(ValueError,match='증적'):controls_summary(r)
    r[0]['증적']='검증로그-2026-01'
    assert controls_summary(r)['fully_met']==1

def test_na_requires_rationale():
    r=frows();r[0]['상태']='해당없음'
    with pytest.raises(ValueError,match='근거'):controls_summary(r)
    r[0]['판단사유']='이 서비스는 외부 모델을 사용하지 않음'
    assert controls_summary(r)['na']==1

def test_residual_missing_does_not_get_zero():
    r=calculate_residual_risk(rrows()); assert r['score'] is None and r['grade']=='평가 보류'

def test_residual_risk_all_unmitigated_is_100():
    rows=rrows()
    for row in rows:row['경감수준']='미이행'
    assert calculate_residual_risk(rows)['score']==100
    assert calculate_residual_risk(rows)['grade']=='출시 재검토'

def test_residual_all_mitigated_is_zero():
    rows=rrows()
    for row in rows:row['경감수준']='완료';row['증적']='승인된 통제 시험결과'
    assert calculate_residual_risk(rows)['score']==0
    assert calculate_residual_risk(rows)['grade']=='저위험(관리)'

def test_residual_some_missing_evidence_holds_grade():
    rows=rrows()
    for row in rows:row['경감수준']='완료';row['증적']='승인서'
    rows[0]['증적']=''
    assert calculate_residual_risk(rows)['score'] is None

def test_override_highimpact():
    rows=rrows()
    for row in rows:row['경감수준']='완료';row['증적']='로그'
    assert calculate_residual_risk(rows,high_impact=True)['grade']=='고위험(관리)'
    assert calculate_residual_risk(rows,financial_stability=True)['grade']=='출시 재검토'

def test_dataset_template_and_import():
    records=parse_dataset('case.csv',template_csv())
    assert len(records)==len(SAMPLE_CASES)
    assert records[0]['question'].startswith('첨부된')

def test_dataset_requires_question():
    with pytest.raises(ValueError,match='질문'):
        parse_dataset('empty.csv',b'case_id,question\nID1,\n')

def test_dataset_duplicate_case():
    with pytest.raises(ValueError,match='중복'):
        parse_dataset('cases.csv',b'case_id,question\nA,one\nA,two\n')

def test_pii_redaction():
    data='test@example.com 010-1234-5678'
    assert '이메일' in detect_sensitive(data)
    assert 'test@example.com' not in redact_pii(data)

def test_expected_behavior_not_ground_truth():
    text=build_prompt('질문','답변','[D1] 증거','',[],[{'name':'정확성','weight':100}],expected_behavior='추측하면 안 됨')
    assert '정답/법적 사실로 간주하지 말 것' in text

def test_export_all_sheets():
    payload=professional_report([],frows(),rrows(),{'서비스명':'공개 가상 테스트'},SAMPLE_CASES)
    from openpyxl import load_workbook
    workbook=load_workbook(io.BytesIO(payload),read_only=True)
    try:
        assert len(workbook.sheetnames)==8
        assert workbook['안전성 신뢰성 28'].max_row==29
        assert workbook['잔여위험 16'].max_row==17
        assert workbook['평가 데이터셋'].max_row==len(SAMPLE_CASES)+1
    finally:workbook.close()
