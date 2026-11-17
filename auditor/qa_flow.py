"""Question-and-answer form synchronization for reviewed evaluation datasets.

A dataset reference is filled into the QA form without automatically becoming
verified. Only a dataset entry whose review_status is explicitly "확정" can
carry verification into the QA form; the signature binds the exact question
and reference answer. The candidate answer is independent of the reference.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Mapping, MutableMapping


def reference_signature(question: str, answer: str) -> str:
    """Bind approval to the exact question and gold answer pair."""
    return sha256((question.strip() + "\x00" + answer.strip()).encode("utf-8")).hexdigest()


def is_reference_verified(state: Mapping[str, object]) -> bool:
    answer = str(state.get("manual_reference", "") or "").strip()
    question = str(state.get("question", "") or "").strip()
    return bool(answer and question and
                state.get("manual_reference_verified_sig") == reference_signature(question, answer))


def apply_case_to_qa(state: MutableMapping[str, object], case: Mapping[str, object]) -> None:
    """Load ② dataset case into ③ fields, preserving draft-vs-reviewed status.

    Call before rendering the Streamlit text-area widgets in the current run.
    A new case must clear model-generated answers for the preceding question.
    """
    question = str(case.get("question", "") or "").strip()
    reference = str(case.get("reference_answer", "") or "").strip()
    if not question:
        raise ValueError("평가 사례에 질문이 없습니다.")
    reviewed = case.get("review_status") == "확정" and bool(reference)
    state["selected_case"] = dict(case)
    state["selected_case_id"] = str(case.get("case_id", "") or "")
    state["question"] = question
    state["external_response"] = str(case.get("candidate_answer", "") or "")
    state["manual_reference"] = reference
    state["manual_reference_verified_sig"] = reference_signature(question, reference) if reviewed else ""
    state["dataset_reference_confirmed"] = reviewed
    state["answers"] = {}


def can_use_reviewed_case_reference(
    case: Mapping[str, object], question: str, reference: str, opted_in: bool,
) -> bool:
    """Avoid using stale gold answers if the QA form was manually edited."""
    return bool(opted_in and case.get("review_status") == "확정" and
                str(case.get("question", "") or "").strip() == question.strip() and
                str(case.get("reference_answer", "") or "").strip() == reference.strip() and
                reference.strip())


def confirm_loaded_case_if_matching(state: MutableMapping[str, object], case: Mapping[str, object]) -> bool:
    """Propagate a *newly* reviewed ② case to ③ if user did not alter its text."""
    if (str(state.get("selected_case_id", "")) != str(case.get("case_id", "")) or
        str(state.get("question", "") or "").strip() != str(case.get("question", "") or "").strip() or
        str(state.get("manual_reference", "") or "").strip() != str(case.get("reference_answer", "") or "").strip()):
        return False
    state["selected_case"] = dict(case)
    if case.get("review_status") == "확정":
        state["manual_reference_verified_sig"] = reference_signature(
            str(case["question"]), str(case["reference_answer"]))
        state["dataset_reference_confirmed"] = True
        return True
    return False
