"""Atomic fail-closed daily quota using Upstash Redis REST. No per-user tracking."""
from __future__ import annotations

import json
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LUA = """
local k=KEYS[1]
local max=tonumber(ARGV[1])
local ttl=tonumber(ARGV[2])
local n=tonumber(redis.call('GET',k) or '0')
if n >= max then return -1 end
if n == 0 then redis.call('SET', k, 1, 'EX', ttl) else redis.call('INCR', k) end
return n+1
"""


def take_demo_credit(url: str, token: str, daily_limit: int = 30) -> int:
    """Spend one credit for every vendor request, atomically across app replicas."""
    if not url.startswith("https://") or not token:
        raise RuntimeError("운영자 체험에는 HTTPS Redis REST 설정이 필요합니다.")
    date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    payload = json.dumps(["EVAL", LUA, "1", f"auditor:demo:{date}", str(daily_limit), "90000"]).encode()
    req = Request(url.rstrip("/") , data=payload, method="POST",
                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(req, timeout=9) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError("체험 한도 확인에 실패했습니다.")
    count = int(result.get("result", -1))
    if count < 0:
        raise RuntimeError("오늘의 무료 체험 요청 한도에 도달했습니다. 개인 API 키를 사용해 주세요.")
    return count
