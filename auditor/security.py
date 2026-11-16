"""Minimal PII guardrails. Pattern detection is advisory, not a DLP replacement."""
from __future__ import annotations

import re
from typing import Dict, List

_PATTERNS = {
    "주민등록번호 추정": re.compile(r"(?<!\d)\d{6}\s*[- ]?\s*[1-8]\d{6}(?!\d)"),
    "이메일": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "전화번호": re.compile(r"(?<!\d)(?:01[016789]|02|0[3-6][1-5])[- .]?\d{3,4}[- .]?\d{4}(?!\d)"),
    "카드번호 추정": re.compile(r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)"),
}
_INTERNAL = re.compile(r"대외비|내부\s*전용|사내\s*비밀|영업\s*비밀|기밀\s*자료", re.I)


def detect_sensitive(text: str) -> List[str]:
    found = [label for label, rx in _PATTERNS.items() if rx.search(text)]
    if _INTERNAL.search(text):
        found.append("내부 전용 표시")
    return found


def redact_pii(text: str) -> str:
    result = text
    for label, rx in _PATTERNS.items():
        result = rx.sub(f"[{label} 마스킹]", result)
    return result


def redact_records(records: List[Dict]) -> List[Dict]:
    return [{**r, "text": redact_pii(r["text"])} for r in records]
