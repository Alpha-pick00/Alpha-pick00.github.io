import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000") + "/decide"

st.set_page_config(page_title="Étiquette 구매 의사결정 데모", page_icon="🛍️")
st.title("Étiquette 구매 의사결정 데모")
st.caption("GPT + Gemini가 후보를 제안하고, Claude가 최종 추천을 결정합니다.")

if "data" not in st.session_state:
    st.session_state.data = None


def call_api(q: str, spinner_text: str, brand: str | None = None) -> None:
    payload = {"query": q}
    if brand:
        payload["brand"] = brand
    with st.spinner(spinner_text):
        try:
            response = httpx.post(API_URL, json=payload, timeout=120)
            response.raise_for_status()
            st.session_state.data = response.json()
        except httpx.HTTPStatusError as exc:
            st.session_state.data = None
            st.error(f"에러: {exc.response.json().get('detail', str(exc))}")
        except Exception as exc:
            st.session_state.data = None
            st.error(f"요청 실패: {exc}")


query = st.text_input(
    "무엇을 사고 싶으신가요?",
    placeholder="무선 이어폰 10만원대  /  옥수수수염차 24개 사고 싶어  /  생수 사고싶어",
)

if st.button("추천받기", type="primary") and query:
    call_api(query, "에이전트들이 작업 중입니다... (최대 1분 소요)")

data = st.session_state.data

if data and data.get("mode") == "clarify":
    options = data["options"]
    st.info("브랜드를 선택하면 그 브랜드의 최저가를 찾아드려요.")
    brand = st.selectbox("브랜드", options.get("brands", []))
    volume = st.selectbox("용량 (선택)", ["상관없음"] + options.get("volumes", []))
    quantity = st.selectbox("수량 (선택)", ["상관없음"] + options.get("quantities", []))

    if st.button("이 브랜드 최저가 찾기") and brand:
        parts = [data["query"]]
        parts += [v for v in (volume, quantity) if v != "상관없음"]
        call_api(" ".join(parts), f"'{brand}' 최저가를 찾는 중입니다...", brand=brand)
        st.rerun()

elif data and data.get("mode") == "brand_price":
    if data.get("error"):
        st.error(data["error"])
    else:
        option = data["option"]
        st.success(f"{data['brand']} 최저가")
        st.markdown(f"**{option['product_name']}** — {option['price']} ({option['retailer']})")
        st.markdown(f"[구매하러 가기]({option['url']})")

elif data and data.get("mode") == "bulk":
    decision = data["decision"]
    st.success(f"브랜드별 최저가 옵션 {len(decision['options'])}개")
    price_range = data.get("price_range")
    if price_range:
        st.caption(f"가격대: {price_range['min']} ~ {price_range['max']}")
    st.caption(decision["reasoning"])
    for option in decision["options"]:
        st.markdown(
            f"**{option['brand']}** — {option['product_name']} · "
            f"{option['price']} ({option['retailer']}) · "
            f"[이 브랜드로 보기]({option['url']})"
        )
        if option.get("delivery_note"):
            st.caption(f"🚚 {option['delivery_note']}")

    st.divider()
    st.subheader("토론 내역 (에이전트별 원본 제안 + 추론)")
    cols = st.columns(len(data["proposals"]))
    for col, proposal in zip(cols, data["proposals"]):
        with col:
            st.markdown(f"**{proposal['agent'].upper()}**")
            if proposal.get("error"):
                st.error(proposal["error"])
            elif not proposal.get("options"):
                st.caption("제안 없음")
            else:
                for option in proposal["options"]:
                    st.write(f"{option['brand']} — {option['price']}")
                    if option.get("reasoning"):
                        st.caption(option["reasoning"])
                    if option.get("delivery_note"):
                        st.caption(f"🚚 {option['delivery_note']}")

elif data:
    decision = data["decision"]
    st.success("최종 추천")
    st.markdown(f"**{decision['product_name']}** — {decision['price']} ({decision['retailer']})")
    st.write(decision["reasoning"])
    st.markdown(f"[상품 보러가기]({decision['url']})")
    st.caption(f"채택된 제안: {decision['chosen_agent']}")

    st.divider()
    st.subheader("토론 내역")
    cols = st.columns(len(data["proposals"]))
    for col, proposal in zip(cols, data["proposals"]):
        with col:
            st.markdown(f"**{proposal['agent'].upper()}**")
            if proposal.get("error"):
                st.error(proposal["error"])
            else:
                st.write(f"{proposal['product_name']} — {proposal['price']}")
                st.write(proposal["retailer"])
                st.write(proposal["reasoning"])
                st.markdown(f"[링크]({proposal['url']})")
