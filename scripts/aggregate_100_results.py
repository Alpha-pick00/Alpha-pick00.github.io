"""PART 2 집계 - scripts/results_100.json(이미 완료된 배치 실행 결과)만
읽는다. 네트워크 요청 없음.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from rapidfuzz import fuzz  # noqa: E402

RESULTS_PATH = SCRIPT_DIR / "results_100.json"
SIDE_DATA_PATH = SCRIPT_DIR / "results_100_side_data.json"

# 기존 20개 각각이 실제로 속하는 카테고리(수동 분류, build_100_queries.py 설계 당시 근거).
EXISTING_20_CATEGORY = {
    "무선 이어폰 추천": "디지털/PC",
    "다이슨 무선청소기": "가전",
    "갤럭시 버즈3 프로": "디지털/PC",
    "스탠딩 책상 120cm": "생활/주방",
    "기계식 키보드 적축": "디지털/PC",
    "27인치 4K 모니터": "디지털/PC",
    "아이패드 에어 11인치": "디지털/PC",
    "로지텍 MX Master 3S": "디지털/PC",
    "캡슐 커피머신": "가전",
    "공기청정기 30평": "가전",
    "전기포트 1L": "가전",
    "샴푸 대용량 1000ml": "뷰티",
    "프로틴 파우더 2kg": "식품·생필품",
    "고양이 모래 벤토나이트": "생활/주방",
    "즉석밥 210g 24개": "식품·생필품",
    "라면 멀티팩": "식품·생필품",
    "아기 물티슈 100매": "생활/주방",
    "런닝화 남성 270": "패션/기타",
    "백팩 노트북 15인치": "패션/기타",
    "텀블러 500ml 보온": "생활/주방",
}


def _real_category(item: dict) -> str:
    if item["category"] == "기존20":
        return EXISTING_20_CATEGORY.get(item["query"], "기존20")
    return item["category"]


def _price_to_int(price: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", price or "")
    return int(digits) if digits else None


def main() -> None:
    items = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    side = json.loads(SIDE_DATA_PATH.read_text(encoding="utf-8")) if SIDE_DATA_PATH.exists() else {}

    total = len(items)
    errored = [i for i in items if "error" in i]
    ok = [i for i in items if "error" not in i]

    print(f"총 쿼리: {total}건 (에러 {len(errored)}건)")
    for e in errored:
        print(f"  ERROR: {e['query']} -> {e.get('error')}")

    # 1) 매칭율
    matched = [i for i in ok if i["decision"]["price_source"] == "danawa_offer"]
    print("\n" + "=" * 70)
    print(f"1) 매칭율: {len(matched)}/{len(ok)} ({len(matched) / len(ok):.1%})")
    print("=" * 70)

    # 2) 다나와 미보유율 (카테고리별)
    print("\n" + "=" * 70)
    print("2) 다나와 미보유율 (price_table=None), 카테고리별")
    print("=" * 70)
    by_cat_total: Counter = Counter()
    by_cat_missing: Counter = Counter()
    for i in ok:
        cat = _real_category(i)
        by_cat_total[cat] += 1
        if i["price_table"] is None:
            by_cat_missing[cat] += 1
    for cat in sorted(by_cat_total, key=lambda c: -by_cat_total[c]):
        n_total = by_cat_total[cat]
        n_missing = by_cat_missing.get(cat, 0)
        print(f"  {cat:12s} {n_missing:>3d}/{n_total:<3d} ({n_missing / n_total:.1%})")
    overall_missing = sum(1 for i in ok if i["price_table"] is None)
    print(f"  {'전체':12s} {overall_missing:>3d}/{len(ok):<3d} ({overall_missing / len(ok):.1%})")

    # 3) 오매칭 후보 - 매칭 성공 건 전부, LLM 상품명 vs 다나와 상품명, ratio
    print("\n" + "=" * 70)
    print("3) 매칭 성공 건 상품명 대조 (유사도 85~95 구간은 [주의] 표시)")
    print("=" * 70)
    for i in matched:
        llm_name = (i.get("llm_original") or {}).get("product_name") or i["decision"]["product_name"]
        danawa_name = i["price_table"]["product_name"] if i["price_table"] else None
        ratio = fuzz.token_set_ratio(llm_name, danawa_name) if danawa_name else None
        flag = " [주의: 85~95 구간]" if ratio is not None and 85 <= ratio < 95 else ""
        print(f"  [{i['category']}] ratio={ratio}{flag}")
        print(f"    LLM: {llm_name}")
        print(f"    다나와: {danawa_name}")

    # 4) 가격 변동 방향
    print("\n" + "=" * 70)
    print("4) 가격 변동 방향 (교체 전 LLM 가격 -> 교체 후 다나와 가격)")
    print("=" * 70)
    up = down = same = unknown = 0
    for i in matched:
        before = _price_to_int((i.get("llm_original") or {}).get("price"))
        after = _price_to_int(i["decision"]["price"])
        if before is None or after is None:
            unknown += 1
            continue
        if after > before:
            up += 1
        elif after < before:
            down += 1
        else:
            same += 1
        print(f"  [{i['category']}] {i['query']}: {before:,} -> {after:,} "
              f"({'상승' if after > before else '하락' if after < before else '동일'})")
    n = len(matched)
    print(f"\n  상승 {up}건 ({up / n:.1%}) / 하락 {down}건 ({down / n:.1%}) / 동일 {same}건 ({same / n:.1%}) "
          f"/ 원가 불명(LLM이 가격 미제시 등) {unknown}건")

    # 5) 판매처 분포 (응답에 남은 대표 price_table 기준 - 쿼리당 1개)
    print("\n" + "=" * 70)
    print("5) 판매처 분포 (쿼리당 대표 price_table 1개 기준, 전체 offer 합산)")
    print("=" * 70)
    seller_counter: Counter = Counter()
    total_offers = 0
    for i in ok:
        if i["price_table"] is None:
            continue
        for offer in i["price_table"]["offers"]:
            seller_counter[offer["seller"]] += 1
            total_offers += 1
    print(f"  총 offer 수: {total_offers}건 (price_table 있는 쿼리 {len(ok) - overall_missing}개)")
    for seller, count in seller_counter.most_common(20):
        print(f"  {seller:20s} {count:>4d}건 ({count / total_offers:.1%})")

    # 6) 미검증 cmpnyc 신규 관측 (뚫어보지 않음)
    print("\n" + "=" * 70)
    print("6) 신규 미검증 cmpnyc (뚫어보지 않음, 목록만)")
    print("=" * 70)
    print(f"  {side.get('unknown_cmpnyc_seen', [])}")


if __name__ == "__main__":
    main()
