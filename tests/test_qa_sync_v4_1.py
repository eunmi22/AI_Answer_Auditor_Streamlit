"""Auto-transfer QA fields without silently approving generated references."""
from auditor.qa_flow import (
    apply_case_to_qa, can_use_reviewed_case_reference, confirm_loaded_case_if_matching,
    is_reference_verified, reference_signature,
)


def row(**overrides):
    case={
        "case_id": "PAPER-001", "question": "연구의 한계는 무엇인가요?",
        "reference_answer": "스냅숏 방식은 원시 파일의 삭제 레코드를 복구하지 못한다.",
        "candidate_answer": "본 논문은 모든 DB에서 삭제된 데이터를 복구할 수 있다.",
        "review_status": "검토 필요", "domain": "학술논문 분석",
    }
    return {**case, **overrides}


def test_draft_autofilled_into_qa_but_unverified():
    state={"answers": {"GPT": "예전 질문에 대한 답변"}}
    case=row()
    apply_case_to_qa(state,case)
    assert state["question"]==case["question"]
    assert state["manual_reference"]==case["reference_answer"]
    assert state["external_response"]==case["candidate_answer"]
    assert state["selected_case_id"]==case["case_id"]
    assert state["answers"] == {}
    assert not state["dataset_reference_confirmed"]
    assert not is_reference_verified(state)
    assert not can_use_reviewed_case_reference(case,state["question"],state["manual_reference"],True)


def test_confirming_in_step2_propagates_to_step3():
    state={}
    case=row()
    apply_case_to_qa(state,case)
    case["review_status"]="확정"
    assert confirm_loaded_case_if_matching(state,case)
    assert state["dataset_reference_confirmed"]
    assert is_reference_verified(state)
    assert can_use_reviewed_case_reference(case,state["question"],state["manual_reference"],True)


def test_load_already_confirmed_autofills_and_verifies():
    state={}
    case=row(review_status="확정")
    apply_case_to_qa(state,case)
    assert is_reference_verified(state)
    assert state["manual_reference_verified_sig"]==reference_signature(case["question"],case["reference_answer"])


def test_edit_gold_or_question_invalidates_verification():
    state={}
    case=row(review_status="확정")
    apply_case_to_qa(state,case)
    state["manual_reference"]="수정한 답변"
    assert not is_reference_verified(state)
    assert not can_use_reviewed_case_reference(case,state["question"],state["manual_reference"],True)
    state["manual_reference"]=case["reference_answer"]
    state["question"]="변경된 다른 질문"
    assert not is_reference_verified(state)
    assert not can_use_reviewed_case_reference(case,state["question"],state["manual_reference"],True)


def test_rejected_review_propagation_when_qa_was_edited():
    state={}
    case=row()
    apply_case_to_qa(state,case)
    state["manual_reference"]="새로 작성한 별도 답변"
    case["review_status"]="확정"
    assert not confirm_loaded_case_if_matching(state,case)
    assert not is_reference_verified(state)


def test_switch_case_does_not_inherit_old_approval():
    state={}
    apply_case_to_qa(state,row(review_status="확정"))
    assert is_reference_verified(state)
    next_case=row(case_id="PAPER-002",question="적용 대상은?",reference_answer="Aurora와 RDS 일부 엔진.",candidate_answer="",review_status="검토 필요")
    apply_case_to_qa(state,next_case)
    assert not is_reference_verified(state)
    assert not state["dataset_reference_confirmed"]
