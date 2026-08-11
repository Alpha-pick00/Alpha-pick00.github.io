from anthropic import AsyncAnthropic

from ..config import settings
from ..schemas import BulkDecision, BulkProposal, JudgeVerdict, Proposal
from .base import parse_json_object

# 병합된 후보들이 이미 어느 모델(들)이 제안했는지(proposed_by)와 DeepSeek의
# 검증 결과(verified/challenge_note)를 달고 들어오므로, judge는 그 두 신호를 보고
# 고른다. chosen_agent는 여기서 LLM에게 직접 고르게 하지 않는다 — 후보 하나를
# 3개 모델이 공동 제안했을 수도 있어 단일 리터럴 선택을 요구하면 정보 손실 +
# 불필요한 실패 지점만 생긴다(adk_pipeline이 선택된 후보의 url로 역매칭해 채운다).
JUDGE_INSTRUCTIONS = (
    "당신은 여러 쇼핑 에이전트가 제안하고 별도 에이전트가 근거를 검증한 후보 중 "
    "하나를 최종 선택하는 Judge입니다. 각 후보에는 어느 모델(들)이 제안했는지와 "
    "DeepSeek의 검증 결과(통과/우려 + 메모)가 함께 제공됩니다 — 검증에서 우려가 "
    "표시된 후보보다는 통과한 후보를 우선하되, 우려가 사소하고 다른 후보보다 "
    "확실히 더 적합하다면 그 후보를 선택해도 됩니다. "
    "아래 제안들을 비교해 사용자에게 가장 적합한 상품 하나를 선택하세요. "
    "근거(reasoning)에는 아래 목록에 실제로 있는 후보끼리만 비교하고, "
    "목록에 없는 상품이나 가상의 대안을 지어내 언급하지 마세요. "
    "반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트를 덧붙이지 마세요.\n\n"
    '{"product_name": "...", "price": "...", "retailer": "...", "url": "...", "reasoning": "..."}'
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
