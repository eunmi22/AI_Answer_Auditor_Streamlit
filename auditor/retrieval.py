"""Simple deterministic Korean-friendly character-n-gram retrieval (no remote index)."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List


def _grams(text: str) -> Counter:
    text = re.sub(r"\s+", " ", text.casefold()).strip()
    # Korean, Latin and digit 2/3-grams; handles unspaced Korean documents.
    s = re.sub(r"[^가-힣a-z0-9]", "", text)
    return Counter(s[i:i+n] for n in (2,3) for i in range(max(0,len(s)-n+1)))


def find_evidence(records: List[Dict], query: str, limit: int = 9, max_chars: int = 13000) -> List[Dict]:
    query_vec = _grams(query)
    if not records:
        return []
    if not query_vec:
        return records[:limit]
    query_norm = math.sqrt(sum(v*v for v in query_vec.values())) or 1.0
    ranked = []
    for item in records:
        v = _grams(item["text"])
        numerator = sum(n * v.get(g, 0) for g, n in query_vec.items())
        denominator = (math.sqrt(sum(x*x for x in v.values())) or 1.0) * query_norm
        score = numerator / denominator
        ranked.append((score, item))
    ranked.sort(key=lambda p: p[0], reverse=True)
    selected: List[Dict] = []
    size = 0
    for similarity, item in ranked:
        if len(selected) >= limit or size + len(item["text"]) > max_chars:
            break
        selected.append({**item, "similarity": round(similarity, 3)})
        size += len(item["text"])
    return selected


def format_evidence(records: List[Dict]) -> str:
    return "\n\n".join(
        f"[{r['id']}] 파일: {r['file']} / 위치: {r['location']}\n{r['text']}" for r in records
    )
