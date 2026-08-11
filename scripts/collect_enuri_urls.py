"""PART 4-3 사전 조사 1단계 - enuri.com이 RETAILER_DOMAINS에 추가된 뒤,
소수 쿼리(5개 이하)만 재검색해서 에누리 URL을 모은다. 100개를 다시 돌리지
않는다 - search()만 호출한다(LLM/다나와 없음)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import search as search_module  # noqa: E402

# queries_100.json에 이미 있던 것들은 6시간 TTL 캐시(app/search_cache.py,
# sqlite)에 걸려 재검색이 아니라 캐시된(enuri.com 추가 전) 결과를 그대로
# 돌려준다 - 그래서 겹치지 않는 새 쿼리로 고른다. 에누리가 전통적으로
# 강세인 PC부품/전자 위주로 구성.
QUERIES = [
    "인텔 코어 i5 14600K",
    "RTX 4070 그래픽카드",
    "삼성 오디세이 모니터 27인치",
    "노트북 파우치 15인치",
    "블루투스 스피커 추천",
]

OUTPUT_PATH = Path(__file__).resolve().parent / "enuri_urls.json"


async def main() -> None:
    enuri_urls: list[str] = []
    for i, query in enumerate(QUERIES):
        if i > 0:
            await asyncio.sleep(1)
        results = await search_module.search(query)
        found = [r.url for r in results if urlsplit(r.url).netloc.lower() in ("enuri.com", "www.enuri.com")]
        print(f"[{query}] 전체 {len(results)}건, enuri {len(found)}건")
        for u in found:
            print(f"  {u}")
        enuri_urls.extend(found)

    enuri_urls = list(dict.fromkeys(enuri_urls))  # 중복 제거, 순서 유지
    print(f"\n총 enuri URL (중복 제거): {len(enuri_urls)}건")
    OUTPUT_PATH.write_text(json.dumps(enuri_urls, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
