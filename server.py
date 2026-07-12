#!/usr/bin/env python3
"""dart-financials MCP 서버 엔트리포인트.

회사명(또는 종목코드/corp_code) + 기간 + 재무제표 종류를 물어보면 DART Open API 를
직접 호출해 재무제표를 마크다운 표로 반환한다. 예: "삼성전자 1분기 재무상태표".

등록 툴 (2개):
  1. find_company            - 회사명/종목코드 6자리 → corp_code 식별
  2. get_financial_statement - 재무제표를 마크다운 표로 반환 (DART 원문 링크 동봉)
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

DART_API_KEY: str = os.environ.get("DART_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx 요청 URL 에 crtfc_key(DART 키)가 실리므로 INFO 요청 로그를 차단(키 노출 방지).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from mcp.server.fastmcp import FastMCP  # noqa: E402

import dart_financials  # noqa: E402
from cache_manager import (  # noqa: E402
    ensure_corp_codes,
    lookup_corp_code_by_name,
    lookup_corp_code_by_stock,
)
from models import CompanyLookupResult, FinancialStatementResult  # noqa: E402
from params import resolve_period, resolve_statement_type  # noqa: E402
from table_renderer import render_statement_table  # noqa: E402

# reprt_code → 사람이 읽는 기간 라벨 (표 제목용)
REPRT_LABELS = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}

mcp = FastMCP(
    "dart-financials",
    instructions=(
        "회사명(또는 종목코드 6자리)과 사업연도·기간·재무제표 종류를 입력하면 "
        "DART OpenAPI 를 호출해 재무제표를 마크다운 표로 반환하는 서버입니다. "
        "먼저 find_company 로 corp_code 를 확인할 수도 있고, get_financial_statement 에 "
        "회사명을 바로 넣어도 내부에서 자동 조회합니다. "
        "기간 키워드: 1분기 / 반기(2분기·상반기) / 3분기 / 사업보고서(연간·4분기·전체). "
        "재무제표 종류: 재무상태표 / 손익계산서 / 포괄손익계산서 / 현금흐름표 / 자본변동표 / 전체. "
        "표 하단에 DART 원문 링크가 붙어 사용자가 출처를 검증할 수 있습니다."
    ),
)


async def _resolve_corp(company: str) -> CompanyLookupResult:
    """회사명/종목코드(6자리)/corp_code(8자리) → CompanyLookupResult."""
    q = (company or "").strip()
    if not q:
        return CompanyLookupResult(
            corp_code="", corp_name="", status="error",
            error_message="company 가 비어 있습니다. 회사명 또는 종목코드 6자리를 입력하세요.",
        )

    try:
        df = await ensure_corp_codes(DART_API_KEY)
    except Exception as exc:
        return CompanyLookupResult(
            corp_code="", corp_name=q, status="error",
            error_message=f"corp_code 목록 확보 실패: {exc}",
        )

    if q.isdigit() and len(q) == 6:
        corp_code = lookup_corp_code_by_stock(q, df)
    elif q.isdigit() and len(q) == 8:
        corp_code = q if not df[df["corp_code"] == q].empty else None
    else:
        corp_code = lookup_corp_code_by_name(q, df)

    if not corp_code:
        return CompanyLookupResult(
            corp_code="", corp_name=q, status="not_found",
            error_message=f"'{q}' 에 해당하는 회사를 DART corp_code 목록에서 찾지 못했습니다.",
        )

    row = df[df["corp_code"] == corp_code].iloc[0]
    return CompanyLookupResult(
        corp_code=str(row["corp_code"]),
        corp_name=str(row["corp_name"]),
        stock_code=str(row["stock_code"]) or None,
        status="ok",
    )


@mcp.tool()
async def find_company(query: str) -> dict:
    """회사명 또는 종목코드(6자리)로 DART corp_code 를 식별합니다.

    Args:
        query: 회사명(예: "삼성전자") 또는 종목코드 6자리(예: "005930")

    Returns dict:
        corp_code, corp_name, stock_code, status("ok"|"not_found"|"error"), error_message
    """
    result = await _resolve_corp(query)
    return result.model_dump()


@mcp.tool()
async def get_financial_statement(
    company: str,
    year: int,
    period: str = "사업보고서",
    statement_type: str = "전체",
    fs_div_preference: str = "CFS",
) -> dict:
    """회사의 재무제표를 조회해 마크다운 표로 반환합니다.

    회사명·종목코드(6자리)·corp_code(8자리) 아무거나 넣어도 내부에서 자동 판별합니다.
    연결(CFS)을 우선 취득하고 없으면 개별(OFS)로 폴백하며, 표 하단에 DART 원문 링크를 붙입니다.

    Args:
        company: 회사명(예: "삼성전자") 또는 종목코드 6자리 또는 corp_code 8자리
        year: 사업연도 (예: 2023)
        period: 기간 키워드 — "1분기" | "반기"(=2분기·상반기) | "3분기" |
                "사업보고서"(=연간·4분기·전체). 기본 "사업보고서".
        statement_type: 재무제표 종류 — "재무상태표" | "손익계산서" | "포괄손익계산서" |
                "현금흐름표" | "자본변동표" | "전체". 기본 "전체".
        fs_div_preference: "CFS"(연결, 기본) | "OFS"(개별)

    Returns dict (FinancialStatementResult):
        corp_code, corp_name, bsns_year, reprt_code, fs_div_used, statement_types,
        table(마크다운), currency, rcept_no, source_url, cached, status, warnings, error_message
    """
    # 1) 파라미터 검증 (한국어 키워드 → DART 코드)
    try:
        reprt_code = resolve_period(period)
        sj_div = resolve_statement_type(statement_type)
    except ValueError as exc:
        return FinancialStatementResult(
            corp_code="", corp_name=company, bsns_year=int(year), reprt_code="",
            status="error", error_message=str(exc),
        ).model_dump()

    # 2) 회사 식별
    company_info = await _resolve_corp(company)
    if company_info.status != "ok":
        return FinancialStatementResult(
            corp_code=company_info.corp_code, corp_name=company_info.corp_name,
            bsns_year=int(year), reprt_code=reprt_code,
            status=company_info.status, error_message=company_info.error_message,
        ).model_dump()

    # 3) 재무제표 취득 (동기 — 캐시/API/파싱)
    fin = dart_financials.get_financial_statement(
        corp_code=company_info.corp_code,
        corp_name=company_info.corp_name,
        bsns_year=int(year),
        reprt_code=reprt_code,
        fs_div_preference=fs_div_preference,
    )

    period_label = REPRT_LABELS.get(reprt_code, period)
    parsed_items = fin.get("parsed_items") or {}

    # 4) 표 렌더링 + 출처 링크 동봉
    table_md = render_statement_table(
        parsed_items, sj_div, company_info.corp_name, int(year), period_label
    )
    if fin.get("source_url"):
        table_md += f"\n\n> 출처: [DART 원문 보기(rcept_no={fin.get('rcept_no')})]({fin['source_url']})"

    # 필터 후 표에 실제로 포함된 재무제표 종류 목록
    if sj_div == "ALL":
        statement_types = sorted({d.get("statement_type", "") for d in parsed_items.values() if d.get("statement_type")})
    else:
        from table_renderer import SJ_DIV_LABELS
        statement_types = [SJ_DIV_LABELS.get(sj_div, sj_div)]

    return FinancialStatementResult(
        corp_code=company_info.corp_code,
        corp_name=company_info.corp_name,
        bsns_year=int(year),
        reprt_code=reprt_code,
        fs_div_used=fin.get("fs_div_used"),
        statement_types=statement_types,
        table=table_md,
        currency=fin.get("currency"),
        rcept_no=fin.get("rcept_no"),
        source_url=fin.get("source_url"),
        cached=bool(fin.get("cached")),
        status=fin.get("status", "ok"),
        warnings=fin.get("warnings") or [],
        error_message=fin.get("error_message"),
    ).model_dump()


if __name__ == "__main__":
    mcp.run()
