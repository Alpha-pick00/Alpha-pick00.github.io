"""app/agents/base.py의 is_generic_listing_url 테스트 - 카테고리/검색 목록
페이지 판별(2026-08-19 사용자 리포트: "10만원대 이어폰 추천해줘 했는데
아무것도 안뜨잖아" - 원인 중 하나가 이 판별에서 빠져있던 URL 패턴이었다)."""

from __future__ import annotations

from app.agents.base import is_generic_listing_url


def test_detects_danawa_category_list_page():
    assert is_generic_listing_url("https://prod.danawa.com/list?cate=12244076") is True


def test_detects_danawa_mobile_product_list_page():
    """2026-08-19 실측: m.danawa.com/product/productList.html?cateCode=...
    같은 모바일 카테고리 목록 페이지가 기존 정규식(/list?cate=)에 안 걸려
    "이어폰" 검색 결과에 섞여 들어왔다 - 단일 상품 페이지(product.html?code=)와
    이름이 비슷해 헷갈리기 쉽지만 "List"가 붙고 파라미터도 cateCode라 별개다."""
    url = "https://m.danawa.com/product/productList.html?cateCode=11252453"
    assert is_generic_listing_url(url) is True


def test_does_not_flag_single_product_page():
    assert is_generic_listing_url("https://m.danawa.com/product/product.html?code=28441325") is False
    assert is_generic_listing_url("https://prod.danawa.com/info?pcode=92763563") is False


def test_detects_search_result_page():
    assert is_generic_listing_url("https://search.danawa.com/dsearch.php?query=이어폰") is True
