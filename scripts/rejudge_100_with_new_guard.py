"""PART 4-1 영향 측정 - scripts/results_100.json(이미 캐시된 결과)에서
price_source="danawa_offer"였던 15건에 새 family 가드(app.price_table의
현재 코드)를 다시 적용해 몇 건이 살아남는지 확인한다. LLM/네트워크 호출 없음 -
캐시된 llm_original.product_name / price_table.product_name 문자열만
다시 판정한다.

가드는 강화만 됐지 완화된 적이 없으므로(디스조인트 -> family 단위로 더 엄격해짐),
기존에 실패했던 58건이 새로 통과할 일은 없다 - 15건만 재검사하면 충분하다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.price_table import _product_name_matches  # noqa: E402

RESULTS_PATH = SCRIPT_DIR / "results_100.json"


def main() -> None:
    items = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    ok = [i for i in items if "error" not in i]
    matched = [i for i in ok if i["decision"]["price_source"] == "danawa_offer"]

    print(f"기존 매칭 성공: {len(matched)}건 / 전체 성공 쿼리 {len(ok)}건\n")

    still_ok = 0
    now_blocked = 0
    for i in matched:
        llm_name = (i.get("llm_original") or {}).get("product_name") or i["decision"]["product_name"]
        danawa_name = i["price_table"]["product_name"] if i["price_table"] else None
        if not danawa_name:
            continue
        matches_now = _product_name_matches(llm_name, danawa_name)
        status = "유지" if matches_now else "차단됨(신규 가드)"
        if matches_now:
            still_ok += 1
        else:
            now_blocked += 1
        print(f"  [{status}] {i['category']}")
        print(f"    LLM: {llm_name}")
        print(f"    다나와: {danawa_name}")

    print(f"\n재판정 후 매칭 성공: {still_ok}/{len(matched)} "
          f"(신규 가드로 차단된 건: {now_blocked}건)")
    print(f"전체 기준 매칭율: {still_ok}/{len(ok)} ({still_ok / len(ok):.1%})  "
          f"(기존 {len(matched)}/{len(ok)} = {len(matched) / len(ok):.1%})")


if __name__ == "__main__":
    main()
