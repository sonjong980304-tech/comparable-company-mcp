"""룰 기반 후보 필터링."""
from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd

from models import CandidateCompany, FilteredCandidate

logger = logging.getLogger(__name__)

# 결산월 기준 (12월 결산)
FISCAL_MONTH_OK = {"12월", "12", "12 월"}

# 금융업 관련 업종 키워드
FINANCE_KEYWORDS = [
    "금융", "보험", "은행", "증권", "자산운용", "투자", "신탁", "카드",
    "캐피탈", "저축", "대부", "여신", "수신",
]

# 지주회사 키워드
HOLDING_KEYWORDS = ["지주", "홀딩스", "홀딩"]

# 관리종목 / 투자주의 구분 키워드 (KIND 업종 칼럼에 포함될 때)
MANAGED_KEYWORDS = ["관리", "투자주의"]

# KONEX 기본 제외
KONEX_MARKET = "konex"


def _is_finance(industry: str) -> bool:
    return any(kw in industry for kw in FINANCE_KEYWORDS)


def _is_holding(company_name: str) -> bool:
    return any(kw in company_name for kw in HOLDING_KEYWORDS)


def _is_managed(industry: str) -> bool:
    return any(kw in industry for kw in MANAGED_KEYWORDS)


def _normalize_fiscal_month(raw: str) -> str:
    return re.sub(r"\s+", "", raw).replace("월", "").strip()


def filter_candidates(
    candidates: list[CandidateCompany],
    exclude_konex: bool = True,
    require_december_fiscal: bool = True,
) -> tuple[list[FilteredCandidate], list[FilteredCandidate]]:
    """
    룰 기반 필터 적용.

    Returns:
        (통과 목록, 제외 목록) — 각 항목에 excluded / exclusion_reason 포함
    """
    passed: list[FilteredCandidate] = []
    excluded: list[FilteredCandidate] = []

    for c in candidates:
        reason = _check_exclusion(c, exclude_konex, require_december_fiscal)
        item = FilteredCandidate(
            name=c.name,
            stock_code=c.stock_code,
            industry=c.industry,
            fiscal_month=c.fiscal_month,
            region=c.region,
            market_type=c.market_type,
            excluded=reason is not None,
            exclusion_reason=reason,
        )
        if reason:
            excluded.append(item)
        else:
            passed.append(item)

    logger.info("필터 결과: 통과 %d건 / 제외 %d건", len(passed), len(excluded))
    return passed, excluded


def _check_exclusion(
    c: CandidateCompany,
    exclude_konex: bool,
    require_december_fiscal: bool,
) -> Optional[str]:
    # KONEX 제외
    if exclude_konex and c.market_type and KONEX_MARKET in c.market_type.lower():
        return "KONEX 시장"

    # 결산월 필터
    if require_december_fiscal:
        month = _normalize_fiscal_month(c.fiscal_month)
        if month != "12":
            return f"결산월 불일치({c.fiscal_month})"

    # 금융업 제외
    if _is_finance(c.industry):
        return f"금융업 제외({c.industry})"

    # 지주회사 제외
    if _is_holding(c.name):
        return f"지주회사 제외({c.name})"

    # 관리종목 제외
    if _is_managed(c.industry):
        return f"관리종목({c.industry})"

    return None


def filter_candidates_df(
    df: pd.DataFrame,
    exclude_konex: bool = True,
    require_december_fiscal: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DataFrame 버전 필터 (pipeline.py 내부 사용)."""
    candidates = [
        CandidateCompany(
            name=row["company_name"],
            stock_code=row["stock_code"],
            industry=row.get("industry", ""),
            fiscal_month=str(row.get("fiscal_month", "")),
            region=row.get("region"),
            market_type=row.get("market_type"),
            main_products=row.get("main_products"),
        )
        for _, row in df.iterrows()
    ]
    passed, excluded = filter_candidates(candidates, exclude_konex, require_december_fiscal)

    def to_df(lst: list[FilteredCandidate]) -> pd.DataFrame:
        if not lst:
            return pd.DataFrame()
        return pd.DataFrame([c.model_dump() for c in lst])

    return to_df(passed), to_df(excluded)
