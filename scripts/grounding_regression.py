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

2026-08-17("앞으로는 테스트할 때 토큰 다 쓰면 나한테 말하고 중지해줘 - LLM
모델 하나라도 빠지면 실험하는게 의미가 없어") - 50개를 재검증하던 도중
Qwen(DashScope) 무료 티어가 완전히 소진됐는데 나머지 49개를 그대로 끝까지
돌려서, 통과율이 실제 코드 품질이 아니라 인프라 상태를 반영하는 왜곡된
숫자(17/50 -> 6/50)가 나왔다. 이제 (1) 실행 전 Qwen/DeepSeek/Groq/Tavily
4개를 최소 호출로 헬스체크해 하나라도 죽어있으면 아예 시작하지 않고,
(2) 도중에 연속 2건이 실패하면 즉시 제공자 헬스체크로 재확인 후 확정되면
중단한다(부분 결과는 저장) - 우연한 1회성 오류로 끝까지 못 도는 일은
피하되, 진짜 소진이면 나머지를 억지로 안 돈다.

2026-08-17(같은 날 재발) - qwen-plus로 다운그레이드해 재실행했을 때 Groq
일일 토큰 한도와 OpenAI 크레딧이 실행 초반부터 거의 즉시 바닥났는데도
헬스체크가 통과됐다는 이유로 50개를 그대로 끝까지 돌아 2/50이라는 왜곡된
숫자가 나왔다 - 파이프라인(`debate.run_single_debate`)이 provider의 원본
429/insufficient_quota 예외를 내부에서 잡아 "적절한 상품 후보를 찾지
못했습니다"류의 일반 RuntimeError나 ClarifyResponse로 바꿔버려서,
`case_text`(케이스 결과 문자열)에 원본 에러 문구가 전혀 안 남았기 때문이다
(`_looks_like_quota_exhaustion`가 case_text를 아무리 뒤져도 매칭될 문자열
자체가 없었음). 원본 예외 문구에 의존하는 문자열 매칭은 파이프라인이 내부
예외를 어떻게 감싸는지에 따라 언제든 다시 뚫릴 수 있는 구조적 약점이라,
"케이스 결과 텍스트에 소진 신호가 보이는가" 대신 "케이스가 (사유 불문)
연속으로 실패했는가"로 트리거 조건을 바꿨다 - 실패 사유를 해석하려 하지
않고, 실패가 반복되면 그냥 제공자 상태를 직접 재확인한다.

2026-08-18("통과율이 코드 품질이 아니라 API 쿼터 상태를 반영하고 있다") -
history를 보면 통과율이 17/50 -> 6/50 -> 5/50으로 떨어졌지만 세 실행 모두
infra_note에 "제공자 토큰 한도 소진"이 적혀 있었다. 근본 원인은 실패를 한
버킷(failures)에 다 몰아넣고 그 버킷 크기로 통과율 분모를 잡았던 것 -
"진짜 그라운딩 실패"와 "인프라 예외"와 "clarify로 빠짐(애초에 채점 대상이
아님)"이 전부 같은 숫자로 섞였다. 네 가지를 고쳤다:
1. 결과를 failures(그라운딩 실패)/errors(인프라 예외)/skipped(clarify 등
   채점 제외)로 분리하고, 통과율은 failures 기준(passed / (passed+failed))
   으로만 계산한다 - errors/skipped는 분모에서 뺀다.
2. clarify로 빠지는 걸 skipped로 처리하는 것과 별개로, run_case가
   `skip_clarify=True`로 호출해 애초에 안 빠지게 한다(CASES는 전부
   브랜드·모델이 구체적이라 되묻기 없이 결정까지 가는 게 정상 경로 -
   되묻기로 빠지면 API 비용만 쓰고 채점 데이터가 0건이 된다).
3. product_name 판정 기본값을 문자열 `in` 검사(expect_keywords)에서
   프로덕션이 실제로 쓰는 `price_table._product_name_matches`(rapidfuzz
   유사도 + 모델/수량 충돌 가드 + 배타 토큰 가드)로 바꿨다 - "레이저
   데스에더 V3"가 "Razer DeathAdder V3 (정품)"로 나오면 정답인데 표기
   차이만으로 오답 처리되던 문제(테스트 기준과 프로덕션 매칭 기준이
   달랐던 게 원인). expect_keywords는 지우지 않고 남겨두되, 명시된
   케이스에서만 보조 확인(비채점 참고용 note)으로만 쓴다.
4. 실행마다 결과를 scripts/results/{YYYYMMDD_HHMM}.json으로 쌓고(기존
   grounding_regression_results.json은 최신 실행의 복사본으로 유지해 다른
   스크립트가 안 깨지게 한다), 덮어쓰기 전에 직전 결과를 읽어 REGRESSION/
   FIXED 쿼리 목록을 출력한다 - "몇 건 통과했는지"만으로는 어떤 케이스가
   새로 깨졌는지 알 수 없었다. errors/skipped로 분류된 케이스는 인프라
   문제를 회귀로 착각하지 않도록 이 비교에서 제외한다.

검사 기준은 3가지 - 전부 이번 세션에서 실제로 겪은 버그 클래스를 겨냥한다:
1. URL이 비어있거나 가격비교 사이트(다나와) 자체를 가리키면 안 된다 - "구매링크를
   안띄워주는거야" 버그(다나와 페이지 자체가 최종 URL로 노출됨)의 재발 감지.
2. decision.verified가 명시적으로 False면 안 된다 - challenge가 이미 "그라운딩
   근거 없음"으로 판정한 답을 그대로 서빙하면 안 된다는, 이번에 하드닝한 원칙
   자체의 회귀 감지(특히 relaxed fallback 경로).
3. product_name이 질의와 동일 상품으로 매칭되지 않으면 안 된다 -
   `price_table._product_name_matches`(rapidfuzz token_set_ratio + 모델/수량
   충돌 가드 + 배타 토큰 가드)로 판정한다 - 완전히 다른 상품을 그럴듯하게
   골라오는(환각) 경우의 감지이면서, 동시에 프로덕션이 실제 다나와 실측가를
   대조할 때 쓰는 것과 같은 기준이라 "표기만 다른 정답"을 오답으로 잘못 잡지
   않는다. expect_keywords가 명시된 케이스는 추가로 보조 확인(비채점)도 같이
   기록한다.

결과는 매 실행마다 scripts/results/{YYYYMMDD_HHMM}.json에 통째로 남기고,
scripts/grounding_regression_results.json은 항상 최신 실행의 복사본으로
유지한다 - 실패 패턴을 프롬프트/임계값 보정에 쓰려면 터미널 출력을 다시
파싱하는 것보다 정형 데이터로 남기는 편이 낫다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import debate  # noqa: E402
from app.agents import deepseek as deepseek_module  # noqa: E402
from app.agents import gpt as gpt_module  # noqa: E402
from app.config import settings  # noqa: E402
from app.price_table import (  # noqa: E402
    DANAWA_ROOT_DOMAIN,
    _is_danawa_bridge_passthrough,
    _product_name_matches,
)
from app.schemas import ClarifyResponse  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parent / "grounding_regression_results.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
HISTORY_PATH = Path(__file__).resolve().parent / "grounding_regression_history.json"
README_PATH = Path(__file__).resolve().parent.parent / "README.md"
README_HISTORY_START = "<!-- GROUNDING_HISTORY_START -->"
README_HISTORY_END = "<!-- GROUNDING_HISTORY_END -->"

# 2026-08-17("앞으로는 테스트할 때 토큰 다 쓰면 나한테 말하고 중지해줘 - LLM
# 모델 하나라도 빠지면 실험하는게 의미가 없어") - 50개 재검증 파일럿 도중
# Qwen(DashScope) 무료 티어가 완전히 소진됐는데 스크립트가 그대로 끝까지
# 돌아서, 통과율이 실제 코드 품질이 아니라 인프라 상태를 반영하는 왜곡된
# 숫자가 나왔다(17/50 -> 6/50, 고친 코드 때문이 아니라 3개 제공자 중 사실상
# DeepSeek만 남았던 탓). 실행 전 4개 제공자를 모두 가볍게 확인하고, 하나라도
# 죽어있으면 아예 시작하지 않는다.


async def _ping_qwen() -> str | None:
    try:
        client = gpt_module._client()
        await client.chat.completions.create(
            model=settings.qwen_model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        return None
    except Exception as exc:
        return f"Qwen(gpt): {exc}"


async def _ping_deepseek() -> str | None:
    try:
        client = deepseek_module._client()
        await client.chat.completions.create(
            model=settings.deepseek_model, messages=[{"role": "user", "content": "ping"}], max_tokens=1
        )
        return None
    except Exception as exc:
        return f"DeepSeek: {exc}"


async def _ping_groq() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.groq_api_base}/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={"model": settings.groq_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            )
            resp.raise_for_status()
        return None
    except Exception as exc:
        return f"Groq: {exc}"


async def _ping_tavily() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": "ping",
                    "search_depth": "basic",
                    "max_results": 1,
                    "include_domains": ["danawa.com"],
                },
            )
            resp.raise_for_status()
        return None
    except Exception as exc:
        return f"Tavily: {exc}"


async def check_providers_healthy() -> list[str]:
    """4개 제공자를 최소 호출로 확인한다 - 실패 메시지 목록을 돌려주며, 빈
    리스트면 전부 정상이다. Qwen/DeepSeek/Groq는 propose·challenge·judge에
    전부 관여하고, Tavily는 검색 자체를 담당해 하나라도 죽으면 50개 전체의
    신뢰도가 무너진다."""
    results = await asyncio.gather(_ping_qwen(), _ping_deepseek(), _ping_groq(), _ping_tavily())
    return [r for r in results if r is not None]


@dataclass
class Case:
    category: str
    query: str
    # 기본 판정은 _product_name_matches(프로덕션과 동일 기준)가 담당한다 -
    # 이 필드는 지우지 않되, 명시된 케이스에서만 보조 확인(비채점 참고용)으로
    # 쓴다(2026-08-18).
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


def _case_result(case: Case, status: str, **extra) -> dict:
    """status: "passed" | "failed" | "error" | "skipped". 세 종류의 채점 제외
    사유(error/skipped)를 failures와 섞지 않기 위한 공통 생성자(2026-08-18)."""
    return {"category": case.category, "query": case.query, "status": status, **extra}


# --- 실험 기록(2026-08-17, "앞으로 진행되는 모든 실험들도 그래프로 성능 지표 -----
# Readme로 추가해주고 계속해서 업데이트해줘") - 완주한 실행마다 여기 기록을
# 남기고 README의 마커 구간을 재생성한다. 중간에 쿼터 소진으로 중단된 실행은
# "완주한 실험"이 아니므로 기록하지 않는다(추세 그래프를 의미 없는 부분 실행
# 데이터로 흐리지 않기 위함) - main()에서 사전 헬스체크 실패/도중 중단 시엔
# sys.exit()가 먼저 실행돼 아래 기록 로직에 도달하지 않는다.


def _load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def _append_history(entry: dict) -> list[dict]:
    history = _load_history()
    history.append(entry)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return history


def _render_history_section(history: list[dict]) -> str:
    """README에 그대로 끼워 넣을 마크다운(표 + mermaid xychart-beta)을 만든다.
    순수 함수 - 파일 I/O 없이 테스트/미리보기 가능.

    2026-08-18: 통과율 분모를 total에서 scored(= total - errors - skipped)로
    바꿨다 - 옛 기록(scored/errors/skipped 필드가 없음)은 당시엔 이 구분이
    없었으므로 scored=total로 간주해 그대로 해석한다(과거 기록의 의미를
    바꾸지 않으면서 이후 기록부터 더 정확해진다)."""
    lines = [
        "실행할 때마다 이 표/그래프가 자동으로 갱신된다(`scripts/grounding_regression.py`가",
        "`scripts/grounding_regression_history.json`에 결과를 추가하고 이 구간을 재생성한다 -",
        "수동으로 이 마커(`GROUNDING_HISTORY_START`/`_END`) 사이를 직접 편집하지 말 것,",
        "다음 실행 때 덮어써진다).",
        "",
        "통과율은 채점 대상(scored = 전체 - 오류 - 제외)만 분모로 삼는다 - 제공자 쿼터",
        "소진 같은 인프라 예외(오류)와 clarify로 빠진 케이스(제외)는 그라운딩 품질과",
        "무관하므로 분모에서 뺀다.",
        "",
        "| 날짜 | 통과율 | 통과/채점 | 전체 · 오류 · 제외 | 내용 | 인프라 참고 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for h in history:
        scored = h.get("scored", h["total"])
        errors = h.get("errors", 0)
        skipped = h.get("skipped", 0)
        rate = round(h["passed"] / scored * 100) if scored else 0
        lines.append(
            f"| {h['date']} | {rate}% | {h['passed']}/{scored} | "
            f"{h['total']} · {errors} · {skipped} | {h['context']} | {h.get('infra_note') or '-'} |"
        )

    if history:
        dates = ", ".join(f'"{h["date"]}"' for h in history)
        rates = ", ".join(
            str(round(h["passed"] / h.get("scored", h["total"]) * 100)) if h.get("scored", h["total"]) else "0"
            for h in history
        )
        lines += [
            "",
            "```mermaid",
            "xychart-beta",
            '    title "그라운딩 회귀 파일럿 통과율 추이(%, 채점 대상 기준)"',
            f"    x-axis [{dates}]",
            '    y-axis "통과율 (%)" 0 --> 100',
            f"    bar [{rates}]",
            f"    line [{rates}]",
            "```",
            "",
            "그래프의 특정 지점이 유독 낮다고 코드가 나빠졌다는 뜻은 아닐 수 있다 -",
            "표의 \"인프라 참고\" 칸에 그 실행에서 제공자 쿼터 문제가 있었는지 항상 같이 본다.",
        ]
    return "\n".join(lines)


def update_readme_history_section(history: list[dict]) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    if README_HISTORY_START not in content or README_HISTORY_END not in content:
        print(f"경고: README.md에 {README_HISTORY_START}/{README_HISTORY_END} 마커가 없어 자동 갱신 건너뜀", flush=True)
        return
    before, rest = content.split(README_HISTORY_START, 1)
    _, after = rest.split(README_HISTORY_END, 1)
    section = _render_history_section(history)
    README_PATH.write_text(f"{before}{README_HISTORY_START}\n{section}\n{README_HISTORY_END}{after}", encoding="utf-8")
    print(f"README.md 그라운딩 실험 기록 섹션 갱신 완료 ({len(history)}건)", flush=True)


def _save_results(results: list[dict]) -> Path:
    """실행마다 scripts/results/{YYYYMMDD_HHMM}.json으로 쌓는다(2026-08-18) -
    기존 RESULTS_PATH는 계속 "최신 실행의 복사본"으로 유지해, 이 경로를 직접
    읽는 다른 스크립트가 있어도 깨지지 않게 한다."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamped_path = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    stamped_path.write_text(payload, encoding="utf-8")
    RESULTS_PATH.write_text(payload, encoding="utf-8")
    return stamped_path


def _load_previous_results() -> list[dict] | None:
    if not RESULTS_PATH.exists():
        return None
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _legacy_status(entry: dict) -> str:
    """이 스키마 변경 전에 저장된 결과 항목(status 필드 없음)의 상태를
    최선의 추정으로 되살린다 - 그때는 clarify/예외/진짜 실패가 전부 하나의
    failures 리스트에 섞여 있었으므로, "failures가 있으면 failed"까지만
    복원 가능하다(정확한 error/skipped 구분은 옛 데이터엔 없음)."""
    if "status" in entry:
        return entry["status"]
    return "failed" if entry.get("failures") else "passed"


def diff_against_previous(
    prev_results: list[dict] | None, curr_results: list[dict]
) -> tuple[list[str], list[str], int]:
    """이전 실행 대비 REGRESSION(이전 통과 -> 이번 실패)/FIXED(이전 실패 -> 이번
    통과) 쿼리 목록과 변동 없음 건수를 돌려준다(2026-08-18). 이번 실행 또는
    이전 실행에서 error/skipped였던 케이스는 인프라 문제를 회귀로 착각하지
    않도록 비교에서 제외한다."""
    if not prev_results:
        return [], [], 0

    prev_by_query = {r["query"]: _legacy_status(r) for r in prev_results}
    regressions: list[str] = []
    fixed: list[str] = []
    unchanged = 0
    for r in curr_results:
        if r["status"] not in ("passed", "failed"):
            continue
        prev_status = prev_by_query.get(r["query"])
        if prev_status not in ("passed", "failed"):
            continue
        if prev_status == "passed" and r["status"] == "failed":
            regressions.append(r["query"])
        elif prev_status == "failed" and r["status"] == "passed":
            fixed.append(r["query"])
        else:
            unchanged += 1
    return regressions, fixed, unchanged


def _print_diff_report(prev_results: list[dict] | None, curr_results: list[dict]) -> None:
    regressions, fixed, unchanged = diff_against_previous(prev_results, curr_results)
    print("-" * 70)
    print("이전 실행 대비 비교 (오류/제외 케이스는 비교에서 제외):")
    if prev_results is None:
        print("  이전 결과 파일이 없어 비교 불가(최초 실행)")
    else:
        print(f"  REGRESSION (이전 통과 -> 이번 실패, {len(regressions)}건): {regressions}")
        print(f"  FIXED      (이전 실패 -> 이번 통과, {len(fixed)}건): {fixed}")
        print(f"  변동 없음: {unchanged}건")


async def run_case(case: Case) -> dict:
    # skip_clarify=True(2026-08-18) - CASES는 전부 브랜드·모델이 구체적인
    # 질의라 되묻기 없이 결정까지 가는 게 정상 경로다. 이 플래그 없이는
    # 파이프라인 내부 애매함 판정이 clarify로 빠뜨릴 수 있어(app/debate.py의
    # run_single_debate, adk_pipeline.run이 이미 지원) API 비용만 쓰고
    # 채점 데이터가 0건이 된다.
    result = await debate.run_single_debate(case.query, skip_clarify=True)
    if isinstance(result, ClarifyResponse):
        # clarify(되묻기)는 그라운딩 실패가 아니라 채점 제외 대상이다 -
        # skip_clarify=True를 줬는데도 여기로 빠졌다면 안전망 clarify(완전히
        # 후보가 없을 때)가 동작한 것으로, 파이프라인 자체의 결함이라기보다
        # "이 케이스가 채점 목적에 안 맞는다"는 신호에 가깝다.
        return _case_result(
            case,
            "skipped",
            skip_reason="clarify(되묻기)로 빠짐 - skip_clarify=True인데도 단일 결정에 도달하지 못함",
        )

    decision = result.decision
    failures: list[str] = []

    if not decision.url or _is_price_comparison_url(decision.url):
        failures.append(f"URL이 비어있거나 가격비교 사이트 자체를 가리킴: {decision.url!r}")

    if decision.verified is False:
        failures.append("challenge 검증에서 명시적으로 탈락한 답이 최종 응답으로 노출됨 (verified=False)")

    haystack = decision.product_name or ""
    # 기본 판정: 프로덕션(app/price_table.enrich_decision, app/adk_pipeline.py의
    # 다나와 후보 채택)이 실제로 쓰는 것과 동일한 _product_name_matches -
    # rapidfuzz 유사도 + 모델/수량 충돌 가드 + 배타 토큰 가드. 단순 부분 문자열
    # 검사(예전 expect_keywords 방식)는 "Razer DeathAdder V3 (정품)"처럼 표기만
    # 다른 정답을 오답으로 잘못 잡았다(2026-08-18).
    if not _product_name_matches(case.query, haystack):
        failures.append(
            f"product_name({haystack!r})이 질의({case.query!r})와 동일 상품으로 매칭되지 않음 "
            "(_product_name_matches 기준: 상품명 유사도 + 모델/수량 충돌 가드 + 배타 토큰 가드)"
        )

    extra: dict = {
        "product_name": decision.product_name,
        "retailer": decision.retailer,
        "price": decision.price,
        "url": decision.url,
        "verified": decision.verified,
        "price_source": decision.price_source,
    }

    # expect_keywords는 명시된 케이스에서만 보조 확인으로 쓴다 - 채점(failures)에는
    # 반영하지 않는다. _product_name_matches가 이미 정답으로 인정한 걸 표기 차이로
    # 다시 오답 취급하지 않기 위함(위 코멘트의 데스에더 사례가 정확히 이 경우).
    if case.expect_keywords and not any(kw in haystack for kw in case.expect_keywords):
        extra["keyword_check_note"] = (
            f"참고(보조 확인, 채점 미반영): 기대 키워드 {case.expect_keywords} 중 "
            f"product_name({haystack!r})에 없음"
        )

    if failures:
        return _case_result(case, "failed", failures=failures, **extra)
    return _case_result(case, "passed", **extra)


async def main() -> None:
    # 실행 맥락 한 줄(예: "PR #27 적용 후 재검증") - README 표에 그대로 실린다.
    # 생략하면 일반적인 정기 실행으로 표시된다: python scripts/grounding_regression.py "설명"
    run_context = sys.argv[1] if len(sys.argv) > 1 else "정기 재검증"

    print("사전 헬스체크: Qwen/DeepSeek/Groq/Tavily...", flush=True)
    unhealthy = await check_providers_healthy()
    if unhealthy:
        print("=" * 70)
        print("중단: 실행 전 헬스체크에서 제공자가 이미 죽어있음 - 이 상태로 돌리면")
        print("통과율이 코드 품질이 아니라 인프라 상태를 반영하게 되어 의미가 없다.")
        for msg in unhealthy:
            print(f"  - {msg}")
        print("=" * 70)
        sys.exit(1)
    print("헬스체크 통과 - 4개 제공자 모두 정상. 50개 실행 시작.\n", flush=True)

    # 덮어쓰기 전에 직전 실행 결과를 읽어둔다(2026-08-18) - 이번 실행이 끝난
    # 뒤 REGRESSION/FIXED 비교에 쓴다.
    prev_results = _load_previous_results()

    results: list[dict] = []
    consecutive_failures = 0
    for i, case in enumerate(CASES):
        if i > 0:
            await asyncio.sleep(2)  # 다나와 crawl-delay 등 연속 호출 부담을 줄인다.
        print(f"=== [{i + 1}/{len(CASES)}] ({case.category}) {case.query} ===", flush=True)
        try:
            r = await run_case(case)
        except Exception as exc:
            case_text = f"{type(exc).__name__}: {exc}"
            r = _case_result(case, "error", error=case_text)
        results.append(r)
        for k, v in r.items():
            print(f"  {k}: {v}", flush=True)
        print(flush=True)

        # 실패 사유 문자열을 신뢰하지 않는다 - 파이프라인이 provider의 원본
        # 429/insufficient_quota 예외를 내부에서 잡아 일반 RuntimeError나
        # clarify로 바꿔버리면 실패 텍스트에 소진 신호가 전혀 안 남는다(실제
        # 겪은 사례). 대신 "사유 불문 연속으로 passed가 아님"을 트리거로 삼고
        # (failed/error/skipped 전부 포함 - 셋 중 어느 것으로 나타날지 알 수
        # 없으므로 2026-08-18 스키마 분리 후에도 이 폭은 좁히지 않는다), 실제
        # 소진 여부는 항상 헬스체크로 직접 재확인한다.
        if r["status"] != "passed":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        # 연속 2건이 실패하면(우연한 1회성 실패가 아니라 진짜 인프라 문제일
        # 가능성이 높음) 즉시 제공자 헬스체크로 재확인하고, 확정되면 중단한다
        # - 나머지를 끝까지 돌려봐야 전부 왜곡된 데이터만 쌓인다. 헬스체크가
        # 정상으로 나오면(즉 실패가 진짜 코드/그라운딩 이슈였다면) 카운터만
        # 리셋하고 계속 돈다.
        if consecutive_failures >= 2:
            still_unhealthy = await check_providers_healthy()
            if still_unhealthy:
                stamped_path = _save_results(results)
                print("=" * 70)
                print(f"중단: {i + 1}/{len(CASES)}건까지 실행 후 제공자 쿼터 소진 확인 - 여기서 멈춘다.")
                for msg in still_unhealthy:
                    print(f"  - {msg}")
                print(f"부분 결과 저장: {stamped_path} (최신 복사본: {RESULTS_PATH})")
                _print_diff_report(prev_results, results)
                print("=" * 70)
                sys.exit(1)
            consecutive_failures = 0

    stamped_path = _save_results(results)

    passed_results = [r for r in results if r["status"] == "passed"]
    failed_results = [r for r in results if r["status"] == "failed"]
    error_results = [r for r in results if r["status"] == "error"]
    skipped_results = [r for r in results if r["status"] == "skipped"]
    scored = len(passed_results) + len(failed_results)
    rate = round(len(passed_results) / scored * 100) if scored else 0

    print("=" * 70)
    print(
        f"전체 요약: {len(results)}건 시도 - 통과 {len(passed_results)} / 실패 {len(failed_results)} "
        f"(채점 {scored}건 기준 통과율 {rate}%), 오류 {len(error_results)}건, 제외(clarify 등) {len(skipped_results)}건"
    )
    print(f"결과 파일: {stamped_path} (최신 복사본: {RESULTS_PATH})")

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)
    print("-" * 70)
    print("카테고리별 통과율(채점된 케이스 기준):")
    for category, rows in by_category.items():
        cat_scored = [r for r in rows if r["status"] in ("passed", "failed")]
        cat_passed = [r for r in cat_scored if r["status"] == "passed"]
        cat_extra_n = len(rows) - len(cat_scored)
        extra_note = f" (오류/제외 {cat_extra_n}건 별도)" if cat_extra_n else ""
        if cat_scored:
            print(f"  {category}: {len(cat_passed)}/{len(cat_scored)}{extra_note}")
        else:
            print(f"  {category}: 채점 0건{extra_note}")
    print("-" * 70)

    if failed_results:
        print("실패 상세:")
        for r in failed_results:
            print(f"  [FAIL] ({r['category']}) {r['query']}: {r['failures']}")
    if error_results:
        print("오류 상세:")
        for r in error_results:
            print(f"  [ERROR] ({r['category']}) {r['query']}: {r['error']}")
    if skipped_results:
        print("제외 상세:")
        for r in skipped_results:
            print(f"  [SKIP] ({r['category']}) {r['query']}: {r['skip_reason']}")

    _print_diff_report(prev_results, results)
    print("=" * 70)

    history = _append_history(
        {
            "date": date.today().isoformat(),
            "total": len(results),
            "scored": scored,
            "passed": len(passed_results),
            "errors": len(error_results),
            "skipped": len(skipped_results),
            "context": run_context,
            "infra_note": "",
        }
    )
    update_readme_history_section(history)

    if failed_results:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
