"""V4 regression tests: document auto-detection, draft provenance, user-confirm gates."""
import io
import json
from pathlib import Path

from auditor.autodataset import (
    classify_file, classify_documents, local_drafts,
    validate_ai_drafts, generate_ai_drafts, dataset_csv_bytes, dataset_excel_bytes,
)
from auditor.datasets import parse_dataset
from auditor.documents import parse_uploads


def sample_paper():
    return [
        {"id":"D1","file":"연구자료.pdf","location":"PDF 1페이지",
         "text":"석사 학위 논문. 초록. 본 연구에서는 관리형 클라우드 데이터베이스의 디지털포렌식 조사 절차를 제안한다. 연구 목적은 증거를 확보하면서 운영 서비스 영향을 줄이는 것이다. "*3},
        {"id":"D2","file":"연구자료.pdf","location":"PDF 2페이지",
         "text":"본 연구의 주요 적용 대상은 Amazon RDS 및 Aurora MySQL이다. 선행 연구는 온프레미스 DB를 중점적으로 분석했다. 본 연구는 데이터 수집 단계와 증거 보존 단계를 제안하였다."*3},
        {"id":"D3","file":"연구자료.pdf","location":"PDF 3페이지",
         "text":"5. 결론 본 연구는 제한된 환경을 대상으로 검증했다. 실제 데이터가 없는 환경에서는 추가 검증이 필요하며, 후속 연구로 데이터 유출 시나리오를 살펴볼 예정이다. "*3},
    ]


def test_academic_domain_identified_from_source():
    rows=sample_paper()
    classification=classify_file('연구자료.pdf',rows)
    assert classification.domain=='학술논문 분석'
    assert classification.confidence>.5


def test_local_generation_drafts_and_provenance():
    rows=sample_paper()
    output,classes=local_drafts(rows,5)
    assert output and classes[0].domain=='학술논문 분석'
    assert all(x['review_status']=='검토 필요' for x in output)
    assert all(x['candidate_answer']=='' for x in output)
    evidence={r['id']:r for r in rows}
    for x in output:
        assert ' '.join(x['source_quote'].split()) in ' '.join(evidence[x['source_id']]['text'].split())


def test_generated_drafts_must_include_exact_source_quote():
    rows=sample_paper()
    q='본 연구의 목적은 무엇인가요?'
    source=rows[0]['text'][:62]
    payload={'cases':[{'question':q,'reference_answer':'운영 영향이 적은 증거수집 방법 제안',
                       'category':'연구목적','expected_behavior':'근거 제시',
                       'source_id':'D1','evidence_quote':source},
                      {'question':'공격자가 작성한 질문','reference_answer':'근거가 없는 허위 사실',
                       'category':'환각','source_id':'D999',
                       'evidence_quote':'가상의 출처 내용. 그럴듯하나 실제로 없습니다.'}]}
    parsed=validate_ai_drafts(json.dumps(payload,ensure_ascii=False),rows,'학술논문 분석','AUTO',4)
    assert len(parsed)==1
    assert parsed[0]['source_id']=='D1'
    assert parsed[0]['review_status']=='검토 필요'


def test_ai_generation_falls_back_when_quote_is_fake():
    rows=sample_paper()
    def wrong_provider(prompt):
        return json.dumps({'cases':[{'question':'근거 없는 질문','reference_answer':'정답',
                      'source_id':'D3','evidence_quote':'아무 내용이나 꾸며 낸 문장입니다.'}]}),{'model':'stub'}
    result,classes,usage,warnings=generate_ai_drafts(rows,4,wrong_provider)
    assert len(result)==4
    assert warnings
    assert all(x['review_status']=='검토 필요' for x in result)
    assert all(x['generation_method']=='원문발췌 자동초안' for x in result)


def test_roundtrip_preserves_citations_but_forces_reverification():
    rows=sample_paper()
    cases,_=local_drafts(rows,4)
    cases[0]['review_status']='확정'
    for extension,exporter in [('csv',dataset_csv_bytes),('xlsx',dataset_excel_bytes)]:
        parsed=parse_dataset('demo.'+extension,exporter(cases))
        assert len(parsed)==4
        assert parsed[0]['source_id']==cases[0]['source_id']
        assert all(x['review_status']=='검토 필요' for x in parsed)


def test_mixed_sources_are_classified_independently():
    paper=sample_paper()
    general=[{'id':'D4','file':'상품약관.txt','location':'텍스트',
        'text':'고객 상담 상품 설명서. 적금 중도해지 이율과 수수료 안내. 고객문의 채널과 예금 중도해지 조건. '*15}]
    classes=classify_documents(paper+general)
    assert {c.domain for c in classes}=={'학술논문 분석','금융 고객안내'}
    draft,_=local_drafts(paper+general,8)
    assert {r['domain'] for r in draft}=={'학술논문 분석','금융 고객안내'}


def test_user_uploaded_paper_produces_real_source_page_locations():
    path=Path('/mnt/data/Amazon RDS 데이터베이스.pdf')
    if not path.exists():return
    records,notices=parse_uploads([(path.name,path.read_bytes())])
    result,classes=local_drafts(records,10)
    assert len(result)==10
    assert classes[0].domain=='학술논문 분석'
    assert any('PDF 5페이지' in r['source_location'] for r in result)
    assert any(r['category']=='연구 한계' and 'PDF 40페이지' in r['source_location'] for r in result)
