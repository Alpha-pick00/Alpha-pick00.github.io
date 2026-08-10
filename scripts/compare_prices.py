"""collected_raw.json(LLM이 추측한 price_krw)과 probe_result.csv(JSON-LD로 실측한
가격)을 URL 기준으로 조인해서, 같은 URL에 대해 LLM 추측가와 실측가가 얼마나
다른지 오차율 분포를 낸다. JSONLD/OG로 실제 가격을 확보한 URL만 대상으로 한다
(CSS_NEEDED/HEADLESS_NEEDED/FAIL은 비교 기준값 자체가 없다).
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RAW_CACHE_PATH = SCRIPT_DIR / "collected_raw.json"
PROBE_CSV_PATH = SCRIPT_DIR / "probe_result.csv"


def load_probed_prices() -> dict[str, float]:
    """JSONLD/OG로 실측된 가격만 URL -> 가격(여러 개면 첫 값)으로 모은다."""
    probed = {}
    with PROBE_CSV_PATH.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["status"] not in ("JSONLD", "OG"):
                continue
            prices_raw = row["prices"]
            if not prices_raw:
                continue
            first_price = float(prices_raw.split(";")[0])
            probed[row["url"]] = first_price
    return probed


def main() -> None:
    cache = json.loads(RAW_CACHE_PATH.read_text(encoding="utf-8"))
    probed = load_probed_prices()

    rows = []
    for query, entry in cache.items():
        for agent, data in entry.get("agents", {}).items():
            url = data.get("url")
            llm_price = data.get("price_krw_llm")
            if not url or llm_price is None:
                continue
            actual_price = probed.get(url)
            if actual_price is None:
                continue
            error_ratio = abs(llm_price - actual_price) / actual_price
            rows.append(
                {
                    "query": query,
                    "agent": agent,
                    "url": url,
                    "llm_price_krw": llm_price,
                    "actual_price_krw": actual_price,
                    "error_ratio": round(error_ratio, 4),
                }
            )

    print(f"실측 가격을 확보한 URL과 대조 가능한 LLM 추측 건수: {len(rows)}")
    for r in rows:
        print(
            f"  [{r['agent']}] {r['query']!r}: LLM={r['llm_price_krw']:,} "
            f"실측={r['actual_price_krw']:,.0f} 오차율={r['error_ratio']:.1%}  {r['url']}"
        )

    if rows:
        ratios = [r["error_ratio"] for r in rows]
        print("\n오차율 분포:")
        print(f"  건수: {len(ratios)}")
        print(f"  평균: {statistics.mean(ratios):.1%}")
        print(f"  중앙값: {statistics.median(ratios):.1%}")
        print(f"  최소/최대: {min(ratios):.1%} / {max(ratios):.1%}")
        exact = sum(1 for r in ratios if r == 0)
        within_5pct = sum(1 for r in ratios if r <= 0.05)
        print(f"  정확히 일치(오차 0%): {exact}/{len(ratios)}")
        print(f"  5% 이내: {within_5pct}/{len(ratios)}")
    else:
        print(
            "\n[주의] LLM 추측가와 실측가를 동시에 가진 URL이 하나도 없습니다 — "
            "숫자를 만들어내지 말고 이 사실 그대로 보고할 것."
        )


if __name__ == "__main__":
    main()
