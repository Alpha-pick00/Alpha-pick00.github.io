"""그라운딩 정확도 회귀 테스트(2026-08-16, "그라운딩/환각 방지을 향상시켜야해") -
알려진 답이 있는 질의 세트로 실제 라이브 파이프라인(adk_pipeline)을 정기적으로
때려서, 사용자 리포트로만 버그를 찾던 방식(README "한계점 및 향후 과제": "정량적
지표 기반의 자동화된 평가 체계는 부재")을 보완한다.

카테고리별 50개 파일럿 세트(10 카테고리 x 5개, 2026-08-16 - "1000개 데이터 정도
카테고리 별로 100개 정도" 요청의 1차 파일럿으로 규모를 좁혔다: 실비용/시간이 드는
라이브 API 호출이라 전체 1000개를 바로 돌리기 전에 먼저 이 정도 규모로 하네스와
실패 패턴 자체를 검증한다). "정답"은 사람이 매긴 정확한 가격/상품이 아니라 구조적
검증만 자동 채점한다(아래 3가지 기준) - 실제 정답을 이 스크립트가 스스로 지어내면
그 정답 자체가 검증 안 된 추측이라 오히려 또 다른 환각 데이터가 되기 때문이다.

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

결과는 매 실행마다 scripts/grounding_regression_results.json에 통째로 남긴다 -
실패 패턴을 프롬프트/임계값 보정에 쓰려면 터미널 출력을 다시 파싱하는 것보다
정형 데이터로 남기는 편이 낫다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import debate  # noqa: E402
from app.price_table import DANAWA_ROOT_DOMAIN, _is_danawa_bridge_passthrough  # noqa: E402
from app.schemas import ClarifyResponse  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent / "grounding_regression_results.json"


@dataclass
class Case:
    category: str
    query: str
    expect_keywords: tuple[str, ...] = field(default_factory=tuple)


# 브랜드/모델을 구체적으로 적어 애매함 없이 특정 상품 하나로 수렴하도록 고른
# 질의 세트 - clarify(되묻기)로 안 빠지고 바로 결정까지 가는 게 정상 경로다.
# 카테고리는 이 프로젝트의 category.py 16종 분류와 1:1로 맞추지 않았다 - 이
# 파일럿은 "다양한 상품군에서 그라운딩이 골고루 버티는가"를 보는 게 목적이라
# 사람이 읽기 쉬운 대분류 10개로 묶었다.
CASES: list[Case] = [
    # 가전/디지털
    Case("가전/디지털", "삼성전자 비스포크 냉장고 4도어", ("비스포크", "냉장고")),
    Case("가전/디지털", "LG 트롬 세탁기 24kg", ("트롬", "세탁기")),
    Case("가전/디지털", "다이슨 에어랩 컴플리트", ("다이슨", "에어랩")),
    Case("가전/디지털", "필립스 에어프라이어 XXL", ("필립스", "에어프라이어")),
    Case("가전/디지털", "위닉스 뽀송 제습기 16L", ("위닉스", "제습기")),
    # 컴퓨터/주변기기
    Case("컴퓨터/주변기기", "로지텍 MX Master 3S 무선마우스", ("로지텍", "MX", "Master")),
    Case("컴퓨터/주변기기", "삼성전자 오디세이 G9 모니터", ("오디세이", "G9")),
    Case("컴퓨터/주변기기", "애플 매직키보드", ("매직키보드", "애플")),
    # "데스에더"는 실제 상품명에 로마자 "DeathAdder"로만 표기되는 경우가 많아
    # (2026-08-16 파일럿에서 확인: "Razer DeathAdder V3 (정품)"는 정답인데 한글
    # 키워드만으로 오탐 처리됨) 로마자 표기도 함께 허용한다.
    Case("컴퓨터/주변기기", "레이저 데스에더 V3 게이밍마우스", ("레이저", "Razer", "데스에더", "DeathAdder")),
    Case("컴퓨터/주변기기", "LG 그램 16인치 2024", ("그램", "16")),
    # 모바일/웨어러블
    Case("모바일/웨어러블", "아이폰 16 프로 256GB", ("아이폰", "16")),
    Case("모바일/웨어러블", "갤럭시 워치7 44mm", ("갤럭시", "워치")),
    Case("모바일/웨어러블", "애플워치 시리즈10", ("애플워치", "시리즈")),
    Case("모바일/웨어러블", "갤럭시 버즈3 프로", ("갤럭시", "버즈")),
    Case("모바일/웨어러블", "샤오미 미밴드9", ("샤오미", "미밴드")),
    # 뷰티/화장품
    Case("뷰티/화장품", "설화수 자음생크림", ("설화수", "자음생")),
    Case("뷰티/화장품", "랑콤 제니피끄 세럼", ("랑콤", "제니피끄")),
    Case("뷰티/화장품", "아이오페 레티놀 엑스퍼트", ("아이오페", "레티놀")),
    Case("뷰티/화장품", "헤라 블랙쿠션", ("헤라", "블랙쿠션")),
    Case("뷰티/화장품", "조성아뷰티 파운데이션", ("조성아", "파운데이션")),
    # 식품/음료
    Case("식품/음료", "햇반 백미 210g 24개", ("햇반",)),
    Case("식품/음료", "농심 신라면 멀티팩 40개", ("신라면",)),
    Case("식품/음료", "남양 프렌치카페 카누", ("카누",)),
    Case("식품/음료", "동서 맥심 모카골드 커피믹스", ("맥심", "모카골드")),
    Case("식품/음료", "오뚜기 진라면 순한맛", ("진라면",)),
    # 생활용품/주방
    Case("생활용품/주방", "락앤락 밀폐용기 세트", ("락앤락", "밀폐용기")),
    Case("생활용품/주방", "테팔 인덕션 프라이팬", ("테팔", "프라이팬")),
    Case("생활용품/주방", "쿠쿠 전기밥솥 10인용", ("쿠쿠", "밥솥")),
    Case("생활용품/주방", "다우니 섬유유연제 대용량", ("다우니",)),
    Case("생활용품/주방", "3M 극세사 걸레", ("3M", "극세사")),
    # 패션/의류
    Case("패션/의류", "노스페이스 눕시 패딩", ("노스페이스", "눕시")),
    Case("패션/의류", "나이키 에어포스1", ("나이키", "에어포스")),
    Case("패션/의류", "아디다스 삼바 운동화", ("아디다스", "삼바")),
    Case("패션/의류", "유니클로 히트텍 이너웨어", ("유니클로", "히트텍")),
    Case("패션/의류", "뉴발란스 993", ("뉴발란스", "993")),
    # 유아동/출산
    Case("유아동/출산", "하기스 매직컴포트 기저귀", ("하기스", "매직컴포트")),
    Case("유아동/출산", "궁중비책 로얄 기저귀", ("궁중비책",)),
    Case("유아동/출산", "페리페라 유아용 물티슈", ("페리페라", "물티슈")),
    Case("유아동/출산", "아프리카 버클 카시트", ("카시트",)),
    Case("유아동/출산", "닥터브라운 젖병", ("닥터브라운", "젖병")),
    # 스포츠/레저
    Case("스포츠/레저", "데카트론 요가매트", ("데카트론", "요가매트")),
    Case("스포츠/레저", "윌슨 테니스라켓", ("윌슨", "테니스")),
    Case("스포츠/레저", "코베아 캠핑 버너", ("코베아", "버너")),
    Case("스포츠/레저", "스캇 자전거 헬멧", ("스캇", "헬멧")),
    Case("스포츠/레저", "언더아머 러닝화", ("언더아머", "러닝화")),
    # 반려동물용품
    Case("반려동물용품", "로얄캐닌 강아지사료", ("로얄캐닌",)),
    Case("반려동물용품", "하림펫푸드 고양이간식", ("하림", "고양이")),
    Case("반려동물용품", "국민사료 츄르", ("츄르",)),
    Case("반려동물용품", "페티벨 강아지 배변패드", ("배변패드",)),
    Case("반려동물용품", "캐치웰 고양이모래", ("캐치웰", "고양이모래")),
]


def _is_price_comparison_url(url: str) -> bool:
    if _is_danawa_bridge_passthrough(url):
        return False
    host = urlsplit(url).netloc.lower()
    return host == DANAWA_ROOT_DOMAIN or host.endswith("." + DANAWA_ROOT_DOMAIN)


async def run_case(case: Case) -> dict:
    result = await debate.run_single_debate(case.query)
    if isinstance(result, ClarifyResponse):
        return {
            "category": case.category,
            "query": case.query,
            "failures": ["단일 결정 대신 clarify(되묻기)로 빠짐 - 질의를 더 구체화 필요"],
        }

    decision = result.decision
    failures: list[str] = []

    if not decision.url or _is_price_comparison_url(decision.url):
        failures.append(f"URL이 비어있거나 가격비교 사이트 자체를 가리킴: {decision.url!r}")

    if decision.verified is False:
        failures.append("challenge 검증에서 명시적으로 탈락한 답이 최종 응답으로 노출됨 (verified=False)")

    if case.expect_keywords:
        haystack = decision.product_name or ""
        if not any(kw in haystack for kw in case.expect_keywords):
            failures.append(
                f"product_name({haystack!r})에 기대 키워드({case.expect_keywords}) 중 어느 것도 없음"
            )

    return {
        "category": case.category,
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
        print(f"=== [{i + 1}/{len(CASES)}] ({case.category}) {case.query} ===", flush=True)
        try:
            r = await run_case(case)
        except Exception as exc:
            r = {"category": case.category, "query": case.query, "failures": [f"예외 발생: {type(exc).__name__}: {exc}"]}
        results.append(r)
        for k, v in r.items():
            print(f"  {k}: {v}", flush=True)
        print(flush=True)

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    failed = [r for r in results if r["failures"]]
    print(f"전체 요약: {len(results)}건 중 {len(results) - len(failed)}건 통과, {len(failed)}건 실패")
    print(f"결과 파일: {RESULTS_PATH}")

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)
    print("-" * 70)
    print("카테고리별 통과율:")
    for category, rows in by_category.items():
        cat_failed = [r for r in rows if r["failures"]]
        print(f"  {category}: {len(rows) - len(cat_failed)}/{len(rows)}")
    print("-" * 70)

    if failed:
        print("실패 상세:")
        for r in failed:
            print(f"  [FAIL] ({r['category']}) {r['query']}: {r['failures']}")
    print("=" * 70)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
