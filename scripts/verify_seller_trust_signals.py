"""검증 B — 판매처 신뢰도 신호(평점/배지/부가 배송정보/표면가 외 가격)가
다나와 판매처별 가격표(ul.list__mall-price) 안에 실제로 존재하는지 확인한다.

네트워크 요청 없음 — backend/tests/fixtures/danawa_offers_*.html만 읽는다.
파싱 코드에 반영하지 않는다 — 존재 여부와 실제 예시만 보고한다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from bs4 import BeautifulSoup  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_FILES = [
    "danawa_offers_1151074.html",
    "danawa_offers_1152054.html",
    "danawa_offers_16559657.html",
    "danawa_offers_17171645.html",
    "danawa_offers_59537216.html",
]

SIGNAL_GROUPS = {
    "판매처 평점/리뷰": ["평점", "리뷰", "구매평", "별점", "만족도"],
    "판매처 배지": ["인증판매자", "우수판매자", "우수몰", "베스트", "공식판매자", "파트너", "굿서비스"],
    "부가 배송정보(무료배송/배송비 외)": ["무료배송", "배송비", "당일배송", "빠른배송", "택배비", "산간", "도서지역"],
    "표면가 외 가격(카드/쿠폰/적립)": ["카드가", "카드할인", "쿠폰가", "쿠폰할인", "즉시할인", "적립금", "무이자", "청구할인"],
}


def _class_before(html: str, pos: int) -> str | None:
    window = html[max(0, pos - 400) : pos]
    matches = re.findall(r'class="([^"]*)"', window)
    return matches[-1] if matches else None


def main() -> None:
    for filename in FIXTURE_FILES:
        html = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "lxml")
        mall_list = soup.select_one("ul.list__mall-price")
        if mall_list is None:
            print(f"[{filename}] ul.list__mall-price 없음 — 스킵")
            continue
        scoped_html = str(mall_list)

        print("=" * 70)
        print(filename)
        print("=" * 70)

        for group_name, keywords in SIGNAL_GROUPS.items():
            hits = []
            for kw in keywords:
                for m in re.finditer(re.escape(kw), scoped_html):
                    start = m.start()
                    snippet = scoped_html[max(0, start - 40) : start + 60].replace("\n", " ")
                    snippet = re.sub(r"\s+", " ", snippet).strip()
                    cls = _class_before(scoped_html, start)
                    hits.append((kw, cls, snippet))
            if hits:
                print(f"  [{group_name}] 있음 ({len(hits)}건)")
                for kw, cls, snippet in hits[:3]:
                    print(f"    - 키워드 '{kw}' / 가장 가까운 class=\"{cls}\"")
                    print(f"      스니펫: ...{snippet}...")
            else:
                print(f"  [{group_name}] 없음")
        print()


if __name__ == "__main__":
    main()
