#!/usr/bin/env python3
"""
comparable-company MCP 서버 엔트리포인트.
5개 툴 등록:
  1. get_target_company_info      - 평가대상 DART 정보 + 사업내용 조회
  2. crawl_dart_candidates        - DART 기반 상장사 후보 목록 (일일 캐시)
  3. filter_candidates_tool       - 룰 기반 필터 적용
  4. verify_business_similarity   - 사업내용 유사성 검증
  5. find_comparable_companies    - 전체 파이프라인 통합 실행
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DART_API_KEY: str = os.environ.get("DART_API_KEY", "")
ANTHROPIC_API_KEY: Optional[str] = os.environ.get("ANTHROPIC_API_KEY") or None

mcp = FastMCP(
    "comparable-company",
    instructions=(
        "DCF/시장접근법 밸류에이션에서 비상장 평가대상 회사의 "
        "대용기업(Comparable Company / Peer Group)을 자동 선정하는 MCP 서버입니다. "
        "일반적으로 find_comparable_companies 하나로 전체 파이프라인을 실행하거나, "
        "get_target_company_info → crawl_kind_candidates → filter_candidates_tool → "
        "verify_business_similarity 순으로 단계별 제어할 수 있습니다."
    ),
)


def _require_dart_key() -> str:
    if not DART_API_KEY:
        raise RuntimeError(
            "DART_API_KEY 환경변수가 없습니다. "
            ".env 파일 또는 MCP 설정의 env 항목을 확인하세요."
        )
    return DART_API_KEY


# ─── 툴 1 ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_target_company_info(company_name: str) -> dict:
    """
    평가대상 비상장 회사의 DART 기업 정보와 사업 내용 텍스트를 조회합니다.

    DART OpenAPI에서 corp_code, 업종코드(induty_code), 업종명(induty_name)을 가져오고,
    최신 사업보고서 → 반기/분기보고서 → 증권신고서 순 fallback으로 사업 내용 섹션을 추출합니다.
    사업 섹션 제목이 보고서마다 다를 수 있어 '사업의 내용', '사업개요', '영업개황' 등
    넓은 범위로 탐색하며, 어느 부분이 핵심 사업 설명인지는 LLM이 판단합니다.

    Args:
        company_name: 평가대상 회사명 (예: "ABC테크놀로지")

    Returns dict with keys:
        corp_code, corp_name, stock_code, induty_code, induty_name,
        business_text, source_report, status, error_message
    """
    api_key = _require_dart_key()
    from dart_client import get_target_company_info as _impl
    result = await _impl(company_name, api_key)
    return result.model_dump()


# ─── 툴 2 ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def crawl_dart_candidates(
    induty_code: str,
    induty_name: str,
    market_type: str = "ALL",
    industry_level: str = "세분류",
    force_refresh: bool = False,
) -> dict:
    """
    DART API 기반으로 동일 업종 KOSPI/KOSDAQ 상장사 후보 목록을 가져옵니다.

    오늘 날짜 캐시가 있으면 DART 재수집 없이 캐시에서 업종 필터링만 수행합니다.
    같은 날 업종 레벨을 바꿔 재호출해도 추가 API 요청이 발생하지 않습니다.

    industry_level 별 KSIC 코드 매칭 방식:
      - "세분류": induty_code 앞 4자리 매칭
      - "중분류": induty_code 앞 3자리 매칭
      - "대분류": induty_code 앞 2자리 매칭

    Args:
        induty_code:    get_target_company_info 반환의 induty_code (KSIC 코드)
        induty_name:    get_target_company_info 반환의 induty_name (업종명)
        market_type:    "ALL" | "KOSPI" | "KOSDAQ"  (기본: "ALL")
        industry_level: "세분류" | "중분류" | "대분류"  (기본: "세분류")
        force_refresh:  True이면 오늘 캐시를 무시하고 DART 재수집

    Returns dict with keys:
        candidates (list), count (int), industry_level (str), cached (bool)
    """
    from dart_company_crawler import dart_cache_exists, filter_dart_by_industry, get_dart_listed_companies
    from models import CandidateCompany

    api_key = _require_dart_key()
    cached = dart_cache_exists() and not force_refresh
    dart_df = await get_dart_listed_companies(api_key, force_refresh=force_refresh)

    filtered = filter_dart_by_industry(dart_df, induty_code=induty_code, induty_name=induty_name, industry_level=industry_level)

    if market_type and market_type.upper() != "ALL":
        if "market_type" in filtered.columns:
            filtered = filtered[filtered["market_type"].str.upper() == market_type.upper()]

    candidates = [
        CandidateCompany(
            name=row.get("corp_name", ""),
            stock_code=row.get("stock_code", ""),
            industry=row.get("induty_name", ""),
            fiscal_month=str(row.get("fiscal_month", "")),
            region=row.get("adres", ""),
            market_type=row.get("market_type", ""),
        )
        for _, row in filtered.iterrows()
        if row.get("stock_code")
    ]
    return {
        "candidates": [c.model_dump() for c in candidates],
        "count": len(candidates),
        "industry_level": industry_level,
        "cached": cached,
    }


# ─── 툴 3 ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def filter_candidates_tool(
    candidates_json: str,
    exclude_konex: bool = True,
    require_december_fiscal: bool = True,
) -> dict:
    """
    후보 기업 목록에 룰 기반 필터를 적용합니다.

    제외 기준:
      - 결산월이 12월이 아닌 법인 (require_december_fiscal=True 시)
      - 금융·보험·은행·증권·캐피탈 등 금융 관련 업종
      - 지주회사 (회사명에 '지주', '홀딩스', '홀딩' 포함)
      - KONEX 시장 종목 (exclude_konex=True 시)
      - 관리종목

    Args:
        candidates_json:         crawl_kind_candidates 반환의 candidates 리스트를 JSON 문자열로 전달
        exclude_konex:           True이면 KONEX 제외  (기본: True)
        require_december_fiscal: True이면 12월 결산만 허용  (기본: True)

    Returns dict with keys:
        passed (list), excluded (list with exclusion_reason), passed_count, excluded_count
    """
    from filters import filter_candidates
    from models import CandidateCompany

    try:
        raw_list = json.loads(candidates_json)
    except json.JSONDecodeError as exc:
        return {"error": f"candidates_json JSON 파싱 실패: {exc}"}

    try:
        candidates = [CandidateCompany(**item) for item in raw_list]
    except Exception as exc:
        return {"error": f"후보 목록 형식 오류: {exc}"}

    passed, excluded = filter_candidates(candidates, exclude_konex, require_december_fiscal)
    return {
        "passed": [c.model_dump() for c in passed],
        "excluded": [c.model_dump() for c in excluded],
        "passed_count": len(passed),
        "excluded_count": len(excluded),
    }


# ─── 툴 4 ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def verify_business_similarity(
    target_business_text: str,
    candidate_name: str,
    candidate_corp_code: str = "",
    candidate_stock_code: str = "",
) -> dict:
    """
    평가대상 사업 내용과 후보 기업의 사업 내용을 비교합니다.

    방식 A (ANTHROPIC_API_KEY 없음 — 기본):
      후보 기업 DART 사업내용 텍스트를 추출하여 반환합니다.
      MCP 호스트(Claude)가 두 텍스트를 직접 비교하여 유사도를 판단합니다.
      is_comparable / similarity_score는 null로 반환됩니다.

    방식 B (ANTHROPIC_API_KEY 있음):
      Claude API를 내부 호출하여 is_comparable, similarity_score(1~5),
      rationale, key_overlaps, key_differences까지 자동 산출합니다.

    Args:
        target_business_text: get_target_company_info의 business_text
        candidate_name:       후보 회사명
        candidate_corp_code:  후보 DART corp_code (있으면 우선 사용)
        candidate_stock_code: 후보 종목코드 6자리 (corp_code 없을 때 자동 조회)

    Returns dict with keys:
        candidate_name, is_comparable, similarity_score, rationale,
        key_overlaps, key_differences, target_business_text,
        candidate_business_text, source_report, status, error_message
    """
    api_key = _require_dart_key()
    from verifier import verify_candidate
    result = await verify_candidate(
        target_business_text=target_business_text,
        candidate_name=candidate_name,
        candidate_corp_code=candidate_corp_code,
        candidate_stock_code=candidate_stock_code,
        dart_api_key=api_key,
        anthropic_api_key=ANTHROPIC_API_KEY,
    )
    return result.model_dump()


# ─── 툴 5 ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def find_comparable_companies(
    company_name: str,
    market_type: str = "ALL",
    max_verify: int = 30,
    business_description: Optional[str] = None,
) -> dict:
    """
    비상장 평가대상 회사의 대용기업(Comparable Company / Peer Group)을 자동 선정합니다.

    내부 실행 순서:
      1. DART: 평가대상 기업 정보 + 사업내용 텍스트 조회
         → DART에서 사업내용 추출 실패 시 business_description(수동 입력)으로 대체
      2. DART 기반 동일 업종 KOSPI/KOSDAQ 상장사 목록 (일일 캐시 우선)
      3. 룰 기반 필터 (결산월 12월, 금융·지주·관리종목 제외)
      4. 후보 5개 미만 → 업종 레벨 상향(세분류→중분류→대분류) 재시도
      5. 각 후보 DART 사업내용 추출 → 유사성 검증 (동시 처리)
      6. 유사도 점수 내림차순 정렬 반환

    비상장사라 DART 사업내용 자동 추출이 실패하는 경우,
    business_description에 해당 회사의 사업 내용을 직접 입력하면
    그 텍스트를 기준으로 유사도 검증을 수행합니다.

    Args:
        company_name:          비상장 평가대상 회사명
        market_type:           "ALL" | "KOSPI" | "KOSDAQ"  (기본: "ALL")
        max_verify:            유사도 검증 최대 후보 수  (기본: 30)
        business_description:  DART 추출 실패 시 사용할 사업 내용 텍스트 (선택)

    Returns dict with keys:
        target_company, target_info, comparable_companies (유사도 내림차순),
        unverifiable_candidates, excluded_candidates,
        industry_level_used, total_candidates_found, total_after_filter, error_message
    """
    api_key = _require_dart_key()
    from pipeline import find_comparable_companies as _impl
    result = await _impl(
        company_name=company_name,
        dart_api_key=api_key,
        anthropic_api_key=ANTHROPIC_API_KEY,
        market_type=market_type,
        max_verify=max_verify,
        business_description=business_description,
    )
    return result.model_dump()


# ─── 실행 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
