"""B-4 집계 - scripts/results_100_search_only.json(이미 완료된 배치)만 읽는다.
네트워크 요청 없음. PART 2(scripts/aggregate_100_results.py)와 카테고리
분류 기준을 맞춰서 미보유율을 직접 비교할 수 있게 한다."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = SCRIPT_DIR / "results_100_search_only.json"

# PART 2(scripts/aggregate_100_results.py)와 동일한 분류 - 직접 비교를 위해 그대로 가져온다.
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

# PART 2 기준선 (scripts/aggregate_100_results.py 실행 결과에서 가져옴)
PART2_MISSING_RATE_OVERALL = 0.507


def _real_category(item: dict) -> str:
    if item["category"] == "기존20":
        return EXISTING_20_CATEGORY.get(item["query"], "기존20")
    return item["category"]


def main() -> None:
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    results = data["results"]
    blocked_at = data.get("blocked_at")

    print(f"처리된 쿼리: {len(results)}/100건")
    if blocked_at:
        print(f"!!! 차단으로 중단됨: index={blocked_at['index']}, query={blocked_at['query']!r}, status={blocked_at['status_code']} !!!")
    print()

    # 1) 진짜 미보유율 (직접 검색으로도 0건) - 전체
    zero = [r for r in results if r["pcode_count"] == 0]
    print("=" * 70)
    print(f"1) 진짜 미보유율 (직접 검색 0건): {len(zero)}/{len(results)} ({len(zero) / len(results):.1%})")
    print(f"   PART 2 미보유율(Tavily 경유, 참고용): {PART2_MISSING_RATE_OVERALL:.1%}")
    print("=" * 70)

    # 2) 카테고리별 미보유율
    print()
    print("=" * 70)
    print("2) 카테고리별 진짜 미보유율")
    print("=" * 70)
    by_cat_total: Counter = Counter()
    by_cat_missing: Counter = Counter()
    for r in results:
        cat = _real_category(r)
        by_cat_total[cat] += 1
        if r["pcode_count"] == 0:
            by_cat_missing[cat] += 1
    for cat in sorted(by_cat_total, key=lambda c: -by_cat_total[c]):
        n_total = by_cat_total[cat]
        n_missing = by_cat_missing.get(cat, 0)
        print(f"  {cat:12s} {n_missing:>3d}/{n_total:<3d} ({n_missing / n_total:.1%})")

    # 3) 쿼리당 확보 pcode 수 분포
    print()
    print("=" * 70)
    print("3) 쿼리당 확보 pcode 수 분포")
    print("=" * 70)
    count_dist: Counter = Counter(r["pcode_count"] for r in results)
    for n in sorted(count_dist):
        print(f"  {n}개: {count_dist[n]}건")
    avg = sum(r["pcode_count"] for r in results) / len(results) if results else 0
    print(f"  평균: {avg:.2f}개")

    # 4) total_mall_count 확보 현황 (검색결과 자체에서 "정품" 카테고리 행을 못 찾은 경우 None)
    print()
    print("=" * 70)
    print("4) total_mall_count 확보율 (검색결과에서 '정품' 카테고리 행 발견)")
    print("=" * 70)
    all_items = [it for r in results for it in r["items"]]
    with_count = [it for it in all_items if it["total_mall_count"] is not None]
    print(f"  전체 pcode {len(all_items)}건 중 {len(with_count)}건 ({len(with_count) / len(all_items):.1%} , all_items>0 가정)" if all_items else "  전체 pcode 0건")

    # 5) 0건 쿼리 목록 (카테고리별 육안 확인용)
    print()
    print("=" * 70)
    print("5) 0건 쿼리 목록")
    print("=" * 70)
    for r in zero:
        print(f"  [{_real_category(r)}] {r['query']}")


if __name__ == "__main__":
    main()
