"""PART 4-2 영향 측정 - scripts/results_100.json(이미 캐시된 결과)만 읽는다.
LLM/네트워크 호출 없음.

주의(한계): 캐시에는 쿼리당 "대표(primary)" price_table 1개만 남아있다
(실제 파이프라인은 다나와 URL을 최대 3개까지 페치하지만, run_single_debate가
응답에 primary 하나만 담고 나머지는 버린다 - PART 2 보고 때도 밝힌 것과
같은 제약). 그래서 아래 수치는 "쿼리당 다나와 후보 최대 3개"의 하한(대표
1개 기준)이다 - 실제로는 이보다 약간 더 많을 수 있다.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = SCRIPT_DIR / "results_100.json"


def main() -> None:
    items = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    ok = [i for i in items if "error" not in i]

    no_table = 0
    table_no_a_grade = 0
    table_with_a_grade = 0
    pool_sizes_before = []
    pool_sizes_after = []
    by_cat_added = Counter()
    by_cat_total = Counter()

    for i in ok:
        # 실패한 프로포절이 있어도 judge.decide로 넘어가는 proposals 자체는
        # 항상 3개(top-1 per agent, error 필드로 표시)이므로 3으로 고정한다.
        before = 3
        pt = i["price_table"]
        cat = i["category"]
        by_cat_total[cat] += 1

        if pt is None:
            no_table += 1
            after = before
        else:
            has_a_grade = any(o["linkable"] for o in pt["offers"])
            if has_a_grade:
                table_with_a_grade += 1
                after = before + 1
                by_cat_added[cat] += 1
            else:
                table_no_a_grade += 1
                after = before

        pool_sizes_before.append(before)
        pool_sizes_after.append(after)

    n = len(ok)
    print(f"총 성공 쿼리: {n}건\n")

    print(f"후보 풀 크기(쿼리당 평균): {sum(pool_sizes_before) / n:.2f} -> {sum(pool_sizes_after) / n:.2f}")
    print(f"다나와 후보가 추가된 쿼리: {table_with_a_grade}/{n} ({table_with_a_grade / n:.1%})")
    print(f"price_table은 있지만 A등급이 없어 후보 승격 실패: {table_no_a_grade}/{n} ({table_no_a_grade / n:.1%})")
    print(f"price_table 자체가 없음: {no_table}/{n} ({no_table / n:.1%})")

    print("\n카테고리별 다나와 후보 추가율:")
    for cat in sorted(by_cat_total, key=lambda c: -by_cat_total[c]):
        added = by_cat_added.get(cat, 0)
        total = by_cat_total[cat]
        print(f"  {cat:12s} {added:>3d}/{total:<3d} ({added / total:.1%})")


if __name__ == "__main__":
    main()
