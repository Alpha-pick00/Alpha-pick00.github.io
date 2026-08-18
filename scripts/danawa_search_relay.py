"""다나와 검색(search.danawa.com) 우회 릴레이(2026-08-18) - AWS IP가 이
엔드포인트에서 403으로 차단당한다(실측: 데이터센터/클라우드 IP 대역 자체를
막는 것으로 보임 - CDN/WAF 흔적 없이 다나와 자체 서버가 즉시 커스텀 403
페이지를 돌려주고, prod.danawa.com은 같은 IP에서 정상 응답한다). 이 스크립트를
막히지 않은 로컬 회선에서 띄워두고, AWS 쪽 fetchers/danawa_search.py가
DANAWA_SEARCH_RELAY_URL 환경변수로 이 엔드포인트를 거쳐가게 한다.

search.danawa.com 요청을 그대로 대리 수행해 상태코드/본문을 그대로 돌려줄
뿐이다(투명한 프록시) - HTML 파싱은 여전히 호출자(AWS) 쪽 코드가 담당하므로
새 프로토콜을 정의할 필요가 없다.

이 릴레이가 도는 회선 자체가 다나와의 10초 Crawl-delay 대상이다 - AWS 쪽
스로틀과 별개로 여기서도 직접 지킨다(안 그러면 이 회선마저 차단당할 수
있다).

실행: .venv/bin/uvicorn scripts.danawa_search_relay:app --host 0.0.0.0 --port 8788
(리포 루트에서, backend/.venv 재사용 - httpx/fastapi/uvicorn 이미 설치돼 있음)
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("danawa_search_relay")

app = FastAPI()

_UPSTREAM_URL = "https://search.danawa.com/dsearch.php"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CRAWL_DELAY_SEC = 10.0
_REQUEST_TIMEOUT = 10.0

_lock = asyncio.Lock()
_last_request_at: float | None = None


async def _wait_for_crawl_delay() -> None:
    global _last_request_at
    async with _lock:
        now = time.monotonic()
        if _last_request_at is not None:
            remaining = _CRAWL_DELAY_SEC - (now - _last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        _last_request_at = time.monotonic()


@app.get("/danawa-search")
async def danawa_search_relay(query: str = Query(...)) -> Response:
    await _wait_for_crawl_delay()
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(_UPSTREAM_URL, params={"query": query})
        except httpx.HTTPError as exc:
            logger.exception("relay upstream request failed: query=%r", query)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info("relayed query=%r -> status=%s", query, resp.status_code)
    return Response(content=resp.content, status_code=resp.status_code, media_type="text/html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
