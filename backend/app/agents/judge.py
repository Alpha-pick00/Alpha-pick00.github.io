from anthropic import AsyncAnthropic

from ..config import settings
from ..schemas import BulkDecision, BulkProposal, Decision, JudgeVerdict, Proposal
from .base import parse_json_object

# 병합된 후보들이 이미 어느 모델(들)이 제안했는지(proposed_by)와 DeepSeek의
# 검증 결과(verified/challenge_note)를 달고 들어오므로, judge는 그 두 신호를 보고
# 고른다. chosen_agent는 여기서 LLM에게 직접 고르게 하지 않는다 — 후보 하나를
# 3개 모델이 공동 제안했을 수도 있어 단일 리터럴 선택을 요구하면 정보 손실 +
# 불필요한 실패 지점만 생긴다(adk_pipeline이 선택된 후보의 url로 역매칭해 채운다).
JUDGE_INSTRUCTIONS = (
    "당신은 여러 쇼핑 에이전트가 제안하고 별도 에이전트가 근거를 검증한 후보 중 "
    "하나를 최종 선택하는 Judge입니다. DeepSeek 검증에서 명확히 우려로 표시된 "
    "후보는 이미 걸러지고 통과했거나 미검증인 후보만 전달됩니다(모든 후보가 "
    "우려로 걸러진 경우에만 예외적으로 우려 후보도 포함되니, 그런 경우 그중 "
    "가장 적합한 것을 고르세요). 각 후보에는 어느 모델(들)이 제안했는지와 "
    "검증 메모가 함께 제공됩니다. "
    "제안 중 agent가 'danawa'로 표시된 것은 여러 판매처의 실제 가격을 비교한 "
    "가격비교 데이터에서 나온 후보입니다 - retailer와 price가 실측 확인된 값이라 "
    "다른 제안보다 가격 신뢰도가 높으니 우선 고려하세요. 다나와·에누리 같은 "
    "가격비교 사이트 자체는 실제 판매처가 아니므로 그 사이트 이름을 retailer로 "
    "쓰지 마세요 - 후보에 이미 채워진 실제 판매처(쿠팡, 11번가 등)를 그대로 쓰세요. "
    "아래 제안들을 비교해 사용자에게 가장 적합한 상품 하나를 선택하세요. "
    "근거(reasoning)에는 아래 목록에 실제로 있는 후보끼리만 비교하고, "
    "목록에 없는 상품이나 가상의 대안을 지어내 언급하지 마세요. "
    "product_name/price/retailer/url은 선택한 후보에 있는 값을 그대로 옮기세요 — "
    "직접 다른 값으로 바꾸거나 새로 지어내지 마세요. 선택한 후보에 price가 "
    "비어 있으면 그 사실을 reasoning에 설명하고, price 필드는 '<UNKNOWN>' 같은 "
    "placeholder 문자열을 쓰지 말고 빈 문자열로 두세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", "reasoning": "..."}'
)

# PRESERVED FROM seungmin/lsm - decide()/LEGACY_JUDGE_INSTRUCTIONS는
# run_single_debate_price_table_variant(app.debate)에서만 쓰인다. 이 경로는
# chosen_agent를 LLM에게 직접 고르게 한다(위 JUDGE_INSTRUCTIONS/adk_pipeline
# 경로와 다른 설계 - url 역매칭이 아니라 여기서는 애초에 danawa 후보까지
# 한 번에 넘기므로 LLM이 그 자리에서 고르는 편이 더 단순하다). 두 경로를
# 섞지 않도록 상수 이름을 분리했다.
LEGACY_JUDGE_INSTRUCTIONS = (
    "당신은 여러 쇼핑 에이전트가 제안한 후보 중 하나를 최종 선택하는 Judge입니다. "
    "아래 제안들을 비교해 사용자에게 가장 적합한 상품 하나를 선택하고, "
    "다나와·에누리 같은 가격비교 사이트는 실제 판매처가 아니므로 "
    "retailer나 url로 최종 선택하지 마세요 - 그 사이트가 비교해서 보여주는 "
    "실제 판매처(쿠팡, 11번가 등)를 골라야 합니다. "
    "제안 중 agent가 'danawa'로 표시된 것은 여러 판매처의 실제 가격을 비교한 "
    "가격비교 데이터에서 나온 후보입니다 - retailer와 price가 실측 확인된 값이라 "
    "다른 제안보다 가격 신뢰도가 높으니 우선 고려하세요(단, 이 경우에도 retailer와 "
    "url 자체는 이미 실제 판매처를 가리키므로 그대로 최종 선택해도 됩니다). "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", '
    '"reasoning": "...", "chosen_agent": "gpt|gemini|deepseek|danawa"}'
)

ORGANIZE_INSTRUCTIONS = (
    "당신은 여러 쇼핑 에이전트가 제안한 브랜드별 후보를 정리하는 Judge입니다. "
    "아래 제안들을 모두 모아 같은 브랜드(표기가 달라도 같은 브랜드면 하나로 합침)는 "
    "가장 낮은 가격 하나만 남기고, 가격이 낮은 순서로 정렬하세요. "
    "브랜드를 하나만 고르지 말고 서로 다른 브랜드는 전부 남기세요. "
    "각 옵션의 reasoning과 delivery_note는 그 옵션을 제안한 에이전트가 적은 내용을 "
    "그대로 옮기고, 새로 지어내지 마세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"options": [{"brand": "...", "product_name": "...", "price": "...", "retailer": "...", '
    '"url": "...", "reasoning": "...", "delivery_note": "..."}], '
    '"reasoning": "..."}'
)


def build_judge_prompt(query: str, proposals: list[Proposal]) -> str:
    """adk_pipeline의 judge LlmAgent가 쓰는 프롬프트 — 각 후보의 제안자
    (proposed_by)와 DeepSeek 검증 결과(verified/challenge_note)를 함께 보여준다."""
    proposals_block = "\n\n".join(
        f"[후보 {i}] 제안자: {', '.join(p.proposed_by) if p.proposed_by else p.agent}\n"
        f"상품: {p.product_name}\n가격: {p.price}\n판매처: {p.retailer}\nURL: {p.url}\n"
        f"제안 근거: {p.reasoning}\n"
        f"DeepSeek 검증: {'통과' if p.verified else '우려' if p.verified is False else '미검증'}"
        + (f" — {p.challenge_note}" if p.challenge_note else "")
        for i, p in enumerate(proposals, start=1)
    )
    return f"{JUDGE_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n후보들:\n{proposals_block}"


async def decide(query: str, proposals: list[Proposal]) -> Decision:
    """PRESERVED FROM seungmin/lsm - run_single_debate_price_table_variant 전용.
    LEGACY_JUDGE_INSTRUCTIONS 참고."""
    valid = [p for p in proposals if p.error is None]
    if not valid:
        raise RuntimeError("No successful proposals to judge")

    proposals_block = "\n\n".join(
        f"[{p.agent}]\n상품: {p.product_name}\n가격: {p.price}\n판매처: {p.retailer}\n"
        f"URL: {p.url}\n근거: {p.reasoning}"
        for p in valid
    )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.judge_model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{LEGACY_JUDGE_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n제안들:\n{proposals_block}"
                ),
            }
        ],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    data = parse_json_object(text)
    return Decision(**data)


async def organize_options(query: str, proposals: list[BulkProposal]) -> BulkDecision:
    valid = [p for p in proposals if p.error is None]
    if not any(p.options for p in valid):
        raise RuntimeError("No successful proposals to organize")

    proposals_block = "\n\n".join(
        f"[{p.agent}]\n"
        + "\n".join(
            f"- {o.brand} / {o.product_name} / {o.price} / {o.retailer} / {o.url} / "
            f"이유: {o.reasoning or '-'} / 배송: {o.delivery_note or '-'}"
            for o in p.options
        )
        for p in valid
    )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.judge_model,
        max_tokens=1536,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{ORGANIZE_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n제안들:\n{proposals_block}"
                ),
            }
        ],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    data = parse_json_object(text)
    return BulkDecision(**data)
