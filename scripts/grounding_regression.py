"""그라운딩 정확도 회귀 테스트(2026-08-16, "그라운딩/환각 방지을 향상시켜야해") -
알려진 답이 있는 질의 세트로 실제 라이브 파이프라인(adk_pipeline)을 정기적으로
때려서, 사용자 리포트로만 버그를 찾던 방식(README "한계점 및 향후 과제": "정량적
지표 기반의 자동화된 평가 체계는 부재")을 보완한다.

pytest 스위트에 넣지 않는다 - Tavily/Qwen/Groq/DeepSeek/다나와 전부 진짜 네트워크
요청이라 비용이 들고(수십 초, API 호출 수십 건), 외부 서비스 상태에 따라 결과가
흔들릴 수 있다(live_smoke_test.py와 동일한 원칙). 수동으로 주기적으로 돌리거나
릴리스 전 체크리스트로 쓴다.

검사 기준은 3가지 - 전부 이번 세션에서 실제로 겪은 버그 클래스를 겨냥한다:
1. URL이 비어있거나 가격비교 사이트(다나와) 자체를 가리키면 안 된다 - "구매링크를
   안띄워주는거야" 버그(다나와 페이지 자체가 최종 URL로 노출됨)의 재발 감지.
2. decision.verified가 명시적으로 False면 안 된다 - challenge가 이미 "그라운딩
   근거 없음"으로 판정한 답을 그대로 서빙하면 안 된다는, 이번에 하드닝한 원칙
   자체의 회귀 감지(특히 relaxed fallback 경로).
3. product_name에 질의의 핵심 키워드가 하나도 안 보이면 안 된다 - 완전히 다른
   상품을 그럴듯하게 골라오는(환각) 경우의 대략적 감지(느슨한 휴리스틱이라
   "탐지 실패"의 반대 방향, 즉 오탐 쪽으로 관대하게 잡았다 - 정확한 상품 매칭
   여부까지 판단하려면 사람이 최종 확인해야 한다).
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import debate  # noqa: E402
from app.price_table import DANAWA_ROOT_DOMAIN, _is_danawa_bridge_passthrough  # noqa: E402
from app.schemas import ClarifyResponse  # noqa: E402


@dataclass
class Case:
    query: str
    expect_keywords: tuple[str, ...] = field(default_factory=tuple)


# 브랜드/모델을 구체적으로 적어 애매함 없이 특정 상품 하나로 수렴하도록 고른
# 질의 세트 - clarify(되묻기)로 안 빠지고 바로 결정까지 가는 게 정상 경로다.
CASES: list[Case] = [
    Case("삼성전자 갤럭시 버즈3 프로", ("갤럭시", "버즈")),
    Case("다이슨 V15 디텍트 무선청소기", ("다이슨", "V15")),
    Case("로지텍 MX Master 3S 무선마우스", ("로지텍", "MX", "Master")),
    Case("애플 에어팟 프로 2세대", ("에어팟", "프로")),
    Case("햇반 백미 210g 24개", ("햇반",)),
]


def _is_price_comparison_url(url: str) -> bool:
    if _is_danawa_bridge_passthrough(url):
        return False
    host = urlsplit(url).netloc.lower()
    return host == DANAWA_ROOT_DOMAIN or host.endswith("." + DANAWA_ROOT_DOMAIN)


async def run_case(case: Case) -> dict:
    result = await debate.run_single_debate(case.query)
    if isinstance(result, ClarifyResponse):
        return {"query": case.query, "failures": ["단일 결정 대신 clarify(되묻기)로 빠짐 - 질의를 더 구체화 필요"]}

    decision = result.decision
    failures: list[str] = []

    if not decision.url or _is_price_comparison_url(decision.url):
        failures.append(f"URL이 비어있거나 가격비교 사이트 자체를 가리킴: {decision.url!r}")

    if decision.verified is False:
        failures.append(f"challenge 검증에서 명시적으로 탈락한 답이 최종 응답으로 노출됨 (verified=False)")

    if case.expect_keywords:
        haystack = decision.product_name or ""
        if not any(kw in haystack for kw in case.expect_keywords):
            failures.append(
                f"product_name({haystack!r})에 기대 키워드({case.expect_keywords}) 중 어느 것도 없음"
            )

    return {
        "query": case.query,
        "product_name": decision.product_name,
        "retailer": decision.retailer,
        "price": decision.price,
        "url": decision.url,
        "verified": decision.verified,
        "price_source": decision.price_source,
        "failures": failures,
    }


async def main() -> None:
    results = []
    for i, case in enumerate(CASES):
        if i > 0:
            await asyncio.sleep(2)  # 다나와 crawl-delay 등 연속 호출 부담을 줄인다.
        print(f"=== [{i + 1}/{len(CASES)}] {case.query} ===", flush=True)
        try:
            r = await run_case(case)
        except Exception as exc:
            r = {"query": case.query, "failures": [f"예외 발생: {type(exc).__name__}: {exc}"]}
        results.append(r)
        for k, v in r.items():
            print(f"  {k}: {v}", flush=True)
        print(flush=True)

    print("=" * 70)
    failed = [r for r in results if r["failures"]]
    print(f"요약: {len(results)}건 중 {len(results) - len(failed)}건 통과, {len(failed)}건 실패")
    for r in failed:
        print(f"  [FAIL] {r['query']}: {r['failures']}")
    print("=" * 70)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
