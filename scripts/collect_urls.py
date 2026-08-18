"""20개 시드 쿼리를 실제 파이프라인(gpt/groq/deepseek.propose, run_single_debate가
쓰는 것과 동일한 함수)에 흘려서, 실제 후보 URL 분포를 수집한다.

이 스크립트는 `main`에서 분기한 `feat/price-probe` 브랜치에서 돈다 — PR1
(feat/score-fusion-dedup, 에이전트당 candidates 배열)은 아직 main에 없으므로
현재 코드베이스의 propose()는 에이전트당 Proposal 1개(URL 1개)만 반환한다.
그래서 이번 수집은 "에이전트당 최대 3개 후보"가 아니라 "쿼리당 에이전트 3개
+ judge decision 1개"가 URL 출처가 된다 — main에 실제로 배포돼 있는 그대로의
분포다.

모든 쿼리를 강제로 이 경로(단일 후보 propose)로 태운다(즉석밥/샴푸/프로틴/
텀블러처럼 실제 /decide였다면 bulk로 라우팅됐을 쿼리도 포함되어 있지만,
이번 조사는 run_single_debate 경로 범위이므로 의도적으로 bulk/clarify
라우팅을 우회한다).

LLM 호출 비용이 들기 때문에 쿼리당 1회만 실행하고, 원본 응답을
collected_raw.json에 캐시해 재실행 시 재사용한다(쿼리 단위로 캐시 히트).
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app import search as search_module  # noqa: E402
from app.agents import deepseek, gpt, groq  # noqa: E402

QUERIES = [
    "무선 이어폰 추천",
    "다이슨 무선청소기",
    "갤럭시 버즈3 프로",
    "스탠딩 책상 120cm",
    "기계식 키보드 적축",
    "27인치 4K 모니터",
    "아이패드 에어 11인치",
    "로지텍 MX Master 3S",
    "캡슐 커피머신",
    "공기청정기 30평",
    "전기포트 1L",
    "샴푸 대용량 1000ml",
    "프로틴 파우더 2kg",
    "고양이 모래 벤토나이트",
    "즉석밥 210g 24개",
    "라면 멀티팩",
    "아기 물티슈 100매",
    "런닝화 남성 270",
    "백팩 노트북 15인치",
    "텀블러 500ml 보온",
]

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_CACHE_PATH = SCRIPT_DIR / "collected_raw.json"
URLS_OUTPUT_PATH = SCRIPT_DIR / "urls.txt"


def _load_cache() -> dict:
    if RAW_CACHE_PATH.exists():
        return json.loads(RAW_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    RAW_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_price_string(price: str | None) -> int | None:
    """main의 Proposal.price는 LLM이 낸 자유 형식 문자열("115,711원" 등)이다.
    실제 가격과 대조하려면 숫자가 필요해서, backend/app/debate.py의
    _price_to_int()와 동일한 방식으로 이 스크립트 안에서만 파싱한다
    (backend 코드는 건드리지 않는다)."""
    digits = re.sub(r"[^\d]", "", price or "")
    return int(digits) if digits else None


async def _collect_one(query: str) -> dict:
    try:
        results = await search_module.search(query)
    except Exception as exc:
        return {"search_error": f"{type(exc).__name__}: {exc}", "agents": {}}

    gpt_p, groq_p, deepseek_p = await asyncio.gather(
        gpt.propose(query, results),
        groq.propose(query, results),
        deepseek.propose(query, results),
    )

    agents = {}
    for p in (gpt_p, groq_p, deepseek_p):
        agents[p.agent] = {
            "error": p.error,
            "product_name": p.product_name,
            "price_str": p.price,
            "price_krw_llm": _parse_price_string(p.price),
            "retailer": p.retailer,
            "url": p.url,
            "reasoning": p.reasoning,
        }
    return {"search_error": None, "agents": agents}


async def collect() -> dict:
    cache = _load_cache()

    for query in QUERIES:
        if query in cache:
            print(f"[cache] {query}")
            continue
        print(f"[fetch] {query}")
        cache[query] = await _collect_one(query)
        _save_cache(cache)  # 쿼리마다 즉시 저장 — 중간에 죽어도 이미 쓴 비용은 보존

    return cache


def extract_urls(cache: dict) -> list[str]:
    urls: list[str] = []
    for query, entry in cache.items():
        for agent_name, agent_data in entry.get("agents", {}).items():
            url = agent_data.get("url")
            if url:
                urls.append(url)
    return urls


def domain_counts(urls: list[str]) -> Counter:
    return Counter(urlsplit(u).netloc.lower() for u in urls)


def main() -> None:
    cache = asyncio.run(collect())

    urls = extract_urls(cache)
    deduped = sorted(set(urls))

    URLS_OUTPUT_PATH.write_text("\n".join(deduped) + "\n", encoding="utf-8")

    print(f"\n총 후보 URL(중복 포함): {len(urls)}개")
    print(f"중복 제거 후: {len(deduped)}개 -> {URLS_OUTPUT_PATH}")

    print("\n도메인별 개수(중복 제거 후):")
    for domain, count in domain_counts(deduped).most_common():
        print(f"  {domain}: {count}")

    if len(deduped) < 40:
        print(
            f"\n[주의] 수집된 URL이 40개 미만입니다 ({len(deduped)}개). "
            "쿼리를 늘리지 말고 이 사실 그대로 보고할 것."
        )


if __name__ == "__main__":
    main()
