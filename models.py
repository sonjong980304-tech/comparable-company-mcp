from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class TargetCompanyInfo(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str] = None
    induty_code: str
    induty_name: str
    business_text: Optional[str] = None
    source_report: Optional[str] = None
    status: str = "ok"
    error_message: Optional[str] = None


class CandidateCompany(BaseModel):
    name: str
    stock_code: str
    industry: str
    fiscal_month: str
    region: Optional[str] = None
    market_type: Optional[str] = None
    main_products: Optional[str] = None


class FilteredCandidate(BaseModel):
    name: str
    stock_code: str
    industry: str
    fiscal_month: str
    region: Optional[str] = None
    market_type: Optional[str] = None
    excluded: bool = False
    exclusion_reason: Optional[str] = None


class VerificationResult(BaseModel):
    candidate_name: str
    stock_code: Optional[str] = None
    corp_code: Optional[str] = None
    is_comparable: Optional[bool] = None
    similarity_score: Optional[int] = None
    rationale: Optional[str] = None
    key_overlaps: list[str] = Field(default_factory=list)
    key_differences: list[str] = Field(default_factory=list)
    target_business_text: Optional[str] = None
    candidate_business_text: Optional[str] = None
    source_report: Optional[str] = None
    status: str = "ok"
    error_message: Optional[str] = None


class ComparableCompanyResult(BaseModel):
    target_company: str
    target_info: Optional[TargetCompanyInfo] = None
    comparable_companies: list[VerificationResult] = Field(default_factory=list)
    unverifiable_candidates: list[VerificationResult] = Field(default_factory=list)
    excluded_candidates: list[FilteredCandidate] = Field(default_factory=list)
    industry_level_used: str = "세분류"
    total_candidates_found: int = 0
    total_after_filter: int = 0
    error_message: Optional[str] = None
