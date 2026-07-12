from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class CompanyLookupResult(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: Optional[str] = None
    status: str = "ok"
    error_message: Optional[str] = None


class FinancialStatementResult(BaseModel):
    corp_code: str
    corp_name: str
    bsns_year: int
    reprt_code: str
    fs_div_used: Optional[str] = None
    statement_types: list[str] = Field(default_factory=list)
    table: str = ""
    currency: Optional[str] = None
    rcept_no: Optional[str] = None
    source_url: Optional[str] = None
    cached: bool = False
    status: str = "ok"
    warnings: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
