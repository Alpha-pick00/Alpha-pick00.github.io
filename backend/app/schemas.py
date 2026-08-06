from typing import Literal

from pydantic import BaseModel

AgentName = Literal["gpt", "gemini"]


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class Proposal(BaseModel):
    agent: AgentName
    product_name: str | None = None
    price: str | None = None
    retailer: str | None = None
    url: str | None = None
    reasoning: str | None = None
    error: str | None = None


class Decision(BaseModel):
    product_name: str
    price: str
    retailer: str
    url: str
    reasoning: str
    chosen_agent: AgentName


class DecideRequest(BaseModel):
    query: str
    brand: str | None = None


class DecideResponse(BaseModel):
    mode: Literal["single"] = "single"
    query: str
    proposals: list[Proposal]
    decision: Decision


class BrandOption(BaseModel):
    brand: str
    product_name: str
    price: str
    retailer: str
    url: str


class BulkProposal(BaseModel):
    agent: AgentName
    options: list[BrandOption] = []
    error: str | None = None


class BulkDecision(BaseModel):
    options: list[BrandOption]
    reasoning: str


class BulkDecideResponse(BaseModel):
    mode: Literal["bulk"] = "bulk"
    query: str
    proposals: list[BulkProposal]
    decision: BulkDecision


class ClarifyOptions(BaseModel):
    brands: list[str] = []
    volumes: list[str] = []
    quantities: list[str] = []


class ClarifyResponse(BaseModel):
    mode: Literal["clarify"] = "clarify"
    query: str
    options: ClarifyOptions


class BrandPriceResponse(BaseModel):
    mode: Literal["brand_price"] = "brand_price"
    query: str
    brand: str
    option: BrandOption | None = None
    error: str | None = None
