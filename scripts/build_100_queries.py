"""PART 2 쿼리 100개 구성. 기존 20개(scripts/collect_urls.py)는 그대로 두고,
공공데이터(한국소비자원 온라인 수집 가격정보, 2026-01-05자)의 good_name
컬럼에서 카테고리별로 실제 값을 뽑아 80개를 추가한다. 가전·디지털/PC는
이 데이터셋이 생필품 편중이라 커버가 약해 별도로 구성한다(대형가전 위주는
직접 골랐고, 데이터셋에 실제로 있는 소형가전/PC주변기기 항목 5개는 그대로
가져다 썼다).

네트워크 요청 없음 - 로컬 CSV 파일만 읽는다.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

CSV_PATH = Path(r"C:\Users\82106\Downloads\202601\2026-01-05.csv")
OUTPUT_PATH = Path(__file__).resolve().parent / "queries_100.json"

EXISTING_20 = [
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

# (pum_name, 카테고리) - 카테고리당 목표 개수를 채우는 데 쓸 후보들.
DATASET_PUM_NAMES: list[tuple[str, str]] = [
    # 식품·생필품 (22)
    ("간장", "식품·생필품"), ("고등어", "식품·생필품"), ("고추장", "식품·생필품"),
    ("국수", "식품·생필품"), ("김치", "식품·생필품"), ("낙지", "식품·생필품"),
    ("냉동식품", "식품·생필품"), ("된장", "식품·생필품"), ("라면", "식품·생필품"),
    ("마른멸치", "식품·생필품"), ("미역", "식품·생필품"), ("밀가루", "식품·생필품"),
    ("빵", "식품·생필품"), ("사과", "식품·생필품"), ("생수", "식품·생필품"),
    ("설탕", "식품·생필품"), ("소금", "식품·생필품"), ("쌀", "식품·생필품"),
    ("아이스크림", "식품·생필품"), ("참기름", "식품·생필품"), ("카레", "식품·생필품"),
    ("커피", "식품·생필품"),
    # 생활/주방 (11)
    ("가정용비닐용품", "생활/주방"), ("방향제", "생활/주방"), ("부엌용세제", "생활/주방"),
    ("섬유유연제", "생활/주방"), ("세탁세제", "생활/주방"), ("습기제거제", "생활/주방"),
    ("이유식", "생활/주방"), ("치약", "생활/주방"), ("칫솔", "생활/주방"),
    ("화장지", "생활/주방"), ("키친타월", "생활/주방"),
    # 뷰티 (9)
    ("기능성화장품", "뷰티"), ("기초화장품", "뷰티"), ("마스크", "뷰티"),
    ("면도기", "뷰티"), ("바디워시", "뷰티"), ("비누", "뷰티"),
    ("색조화장품", "뷰티"), ("샴푸", "뷰티"), ("구강세정제", "뷰티"),
    # 패션/기타 (8)
    ("남자상의", "패션/기타"), ("여자상의", "패션/기타"), ("청바지", "패션/기타"),
    ("티셔츠", "패션/기타"), ("원피스", "패션/기타"), ("운동화", "패션/기타"),
    ("등산복", "패션/기타"), ("지갑", "패션/기타"),
    # 가전 (데이터셋에 실제로 있는 소형가전 3개)
    ("선풍기", "가전"), ("헤어드라이어", "가전"), ("전기레인지", "가전"),
    # 디지털/PC (데이터셋에 실제로 있는 PC주변기기 2개)
    ("컴퓨터소모품", "디지털/PC"), ("저장장치", "디지털/PC"),
]

HAND_PICKED_APPLIANCE_13 = [
    "삼성 비스포크 냉장고", "LG 트롬 세탁기", "발뮤다 토스터기", "필립스 에어프라이어",
    "쿠쿠 전기밥솥", "삼성 무풍에어컨", "위닉스 제습기", "브라운 전기면도기",
    "필립스 전동칫솔", "테팔 에어프라이어", "삼성 비스포크 김치냉장고",
    "LG 퓨리케어 정수기", "발뮤다 가습기",
]

HAND_PICKED_DIGITAL_12 = [
    "아이폰 16 프로", "갤럭시 S25 울트라", "맥북 에어 M3", "아이패드 프로 13인치",
    "삼성 오디세이 게이밍모니터", "로지텍 G502 마우스", "커세어 기계식 키보드",
    "삼성 포터블 SSD T7", "애플워치 시리즈 10", "소니 WH-1000XM5",
    "닌텐도 스위치 2", "갤럭시탭 S10",
]


def _first_good_name_per_pum(csv_path: Path, wanted_pum_names: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    remaining = set(wanted_pum_names)
    with open(csv_path, encoding="cp949", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pum = row.get("pum_name", "")
            if pum in remaining:
                good_name = (row.get("good_name") or "").strip()
                if good_name:
                    found[pum] = good_name
                    remaining.discard(pum)
            if not remaining:
                break
    return found


def main() -> None:
    wanted = {pum for pum, _cat in DATASET_PUM_NAMES}
    resolved = _first_good_name_per_pum(CSV_PATH, wanted)

    missing = wanted - resolved.keys()
    if missing:
        print(f"경고: CSV에서 못 찾은 pum_name: {missing}")

    queries: list[dict[str, str]] = []
    for q in EXISTING_20:
        queries.append({"query": q, "category": "기존20", "source": "existing"})

    for pum, category in DATASET_PUM_NAMES:
        if pum in resolved:
            queries.append({"query": resolved[pum], "category": category, "source": f"dataset:{pum}"})

    for q in HAND_PICKED_APPLIANCE_13:
        queries.append({"query": q, "category": "가전", "source": "hand_picked"})
    for q in HAND_PICKED_DIGITAL_12:
        queries.append({"query": q, "category": "디지털/PC", "source": "hand_picked"})

    print(f"총 쿼리 수: {len(queries)}")
    from collections import Counter

    cat_counts = Counter(q["category"] for q in queries)
    for cat, n in cat_counts.most_common():
        print(f"  {cat}: {n}")

    OUTPUT_PATH.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
