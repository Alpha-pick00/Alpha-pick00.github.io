from anthropic import AsyncAnthropic

from ..config import settings
from ..schemas import BulkDecision, BulkProposal, Decision, Proposal
from .base import parse_json_object

JUDGE_INSTRUCTIONS = (
    "당신은 여러 쇼핑 에이전트가 제안한 후보 중 하나를 최종 선택하는 Judge입니다. "
    "아래 제안들을 비교해 사용자에게 가장 적합한 상품 하나를 선택하고, "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", '
    '"reasoning": "...", "chosen_agent": "gpt|gemini|deepseek"}'
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


async def decide(query: str, proposals: list[Proposal]) -> Decision:
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
                    f"{JUDGE_INSTRUCTIONS}\n\n사용자 질의: {query}\n\n제안들:\n{proposals_block}"
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
