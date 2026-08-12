from app.danawa import _extract_pcode, _parse_lowest_price_link

# 실제 getAllPriceCompareMallList.ajax.php 응답에서 발췌한 구조 — 다나와가 마크업을
# 바꾸면 이 테스트가 먼저 깨져서 알려준다.
_SAMPLE_PRICE_LIST_HTML = """
<div class="price_list col_list" id="defaultMallList">
  <div class="columm left_col">
    <div class="diff_cont">
      <div class="diff_list" id="OpenMarketMallListDiv">
        <div class="diff_tit"><h4>오픈마켓</h4></div>
        <div class="diff_item " data-linkProduct="TH201_7555597224">
          <div class="diff_box">
            <div class="d_mall">
              <a href="https://prod.danawa.com/bridge/loadingBridge.html?pcode=59541506&cmpnyc=TH201" target="_blank" class="link priceCompareBuyLink">
                <img src="//img.danawa.com/cmpny_info/images/TH201_logo.gif" alt="11번가">
              </a>
            </div>
            <div class="d_dsc">
              <div class="prc_line">
                <a href="https://prod.danawa.com/bridge/loadingBridge.html?pcode=59541506&cmpnyc=TH201" target="_blank" class="priceCompareBuyLink">
                  <span class="price lowest"><em class="prc_c">159,000</em>원</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def test_extract_pcode_from_product_url():
    assert _extract_pcode("https://prod.danawa.com/info/?pcode=59541506") == "59541506"
    assert _extract_pcode("https://prod.danawa.com/info?pcode=59541506") == "59541506"


def test_extract_pcode_returns_none_for_non_product_page():
    """가격비교 상세 페이지가 아닌 다나와 URL(기획전·뉴스·목록)은 pcode가 없거나
    구조가 달라 해석 대상이 아니다 — 원래 URL을 그대로 쓰도록 None을 반환한다."""
    assert _extract_pcode("https://plan.danawa.com/info?nPlanSeq=10483") is None
    assert _extract_pcode("https://prod.danawa.com/list?cate=12352289") is None
    assert _extract_pcode("https://www.coupang.com/vp/products/123") is None


def test_parse_lowest_price_link_finds_bridge_url_and_retailer():
    result = _parse_lowest_price_link(_SAMPLE_PRICE_LIST_HTML)

    assert result is not None
    url, retailer = result
    assert url == "https://prod.danawa.com/bridge/loadingBridge.html?pcode=59541506&cmpnyc=TH201"
    assert retailer == "11번가"


def test_parse_lowest_price_link_returns_none_without_lowest_marker():
    """다나와가 "최저가" 표시(class="price lowest")를 아예 안 넣은 응답(예: 판매처
    없음)이면 파싱 대상이 없으므로 None — 호출부는 원래 URL을 그대로 쓴다."""
    assert _parse_lowest_price_link("<div>판매처가 없습니다</div>") is None
