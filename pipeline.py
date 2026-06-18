"""find_comparable_companies 통합 파이프라인 + 업종 재시도 분기."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from dart_client import get_target_company_info
from dart_company_crawler import filter_dart_by_industry, get_dart_listed_companies
from filters import filter_candidates_df
from models import ComparableCompanyResult, FilteredCandidate, VerificationResult
from verifier import verify_candidate

logger = logging.getLogger(__name__)

INDUSTRY_LEVELS = ["세분류", "중분류", "대분류"]
MIN_CANDIDATES_THRESHOLD = 5
DEFAULT_MAX_VERIFY = 30
VERIFY_CONCURRENCY = 5  # 동시 DART 호출 수 제한


async def _verify_all(
    targets_biz: str,
    candidates: list[FilteredCandidate],
    dart_key: str,
    anthropic_key: Optional[str],
    max_verify: int,
    corp_code_map: dict[str, str],  # stock_code → corp_code (사전 조회)
) -> tuple[list[VerificationResult], list[VerificationResult]]:
    """후보 목록 병렬 검증. ok 목록과 확인불가 목록 분리 반환."""
    to_verify = candidates[:max_verify]
    sem = asyncio.Semaphore(VERIFY_CONCURRENCY)

    async def _one(c: FilteredCandidate) -> VerificationResult:
        async with sem:
            corp_code = corp_code_map.get(c.stock_code, "")
            return await verify_candidate(
                target_business_text=targets_biz,
                candidate_name=c.name,
                candidate_corp_code=corp_code,
                candidate_stock_code=c.stock_code,
                dart_api_key=dart_key,
                anthropic_api_key=anthropic_key,
            )

    results = await asyncio.gather(*[_one(c) for c in to_verify])

    ok: list[VerificationResult] = []
    unverifiable: list[VerificationResult] = []
    for r in results:
        if r.status == "ok":
            ok.append(r)
        else:
            unverifiable.append(r)
    return ok, unverifiable


def _sort_results(results: list[VerificationResult]) -> list[VerificationResult]:
    """유사도 점수 내림차순 정렬. 점수 없으면 뒤로."""
    return sorted(results, key=lambda r: r.similarity_score or 0, reverse=True)


async def find_comparable_companies(
    company_name: str,
    dart_api_key: str,
    anthropic_api_key: Optional[str] = None,
    market_type: str = "ALL",
    max_verify: int = DEFAULT_MAX_VERIFY,
    exclude_konex: bool = True,
    business_description: Optional[str] = None,
) -> ComparableCompanyResult:
    """
    비상장 평가대상 회사명 → 대용기업 후보 선정 전체 파이프라인.

    1. 평가대상 정보 조회 (DART)
    2. DART 기반 상장사 목록 조회 (캐시 우선)
    3. 룰 기반 필터 적용
    4. 후보 < 5건이면 업종 레벨 상향(세분류→중분류→대분류) 재시도
    5. 사업 내용 유사성 검증
    6. 유사도 점수 내림차순 정렬
    """
    # ── 1. 평가대상 정보 ───────────────────────────────────────────────────
    logger.info("[파이프라인] 평가대상 정보 조회: %s", company_name)
    target = await get_target_company_info(company_name, dart_api_key)
    if target.status not in ("ok", "사업내용 확인불가") or not target.induty_code:
        return ComparableCompanyResult(
            target_company=company_name,
            target_info=target,
            error_message=target.error_message or "평가대상 정보 조회 실패",
        )

    # DART 자동 추출 실패 시 business_description 수동 입력으로 fallback
    if not target.business_text and business_description:
        logger.info("사업내용 수동 입력 사용: %s", company_name)
        target = target.model_copy(update={
            "business_text": business_description,
            "status": "ok",
            "source_report": "수동 입력",
        })

    if not target.business_text:
        logger.warning("평가대상 사업내용 추출 실패: %s", company_name)

    # ── 2. DART 기반 상장사 목록 로드 (캐시 우선) ────────────────────────
    logger.info("[파이프라인] DART 상장사 목록 로드")
    listed_df = await get_dart_listed_companies(dart_api_key, force_refresh=False)
    # corp_name → company_name 만 미리 정규화 (induty_name은 filter_dart_by_industry가 사용 후 처리)
    listed_df = listed_df.rename(columns={"corp_name": "company_name"})

    # ── 3~4. 업종 레벨별 필터링 + 재시도 ──────────────────────────────────
    passed_df = None
    excluded_df = None
    level_used = "세분류"
    total_found = 0

    for level in INDUSTRY_LEVELS:
        logger.info("[파이프라인] 업종 필터: %s / induty_code=%s", level, target.induty_code)
        filtered_by_industry = filter_dart_by_industry(
            listed_df,
            induty_code=target.induty_code,
            induty_name=target.induty_name,
            industry_level=level,
        )
        # 평가대상 자신 제외 (상장사인 경우 stock_code로 제거)
        if target.stock_code and "stock_code" in filtered_by_industry.columns:
            filtered_by_industry = filtered_by_industry[
                filtered_by_industry["stock_code"] != target.stock_code
            ]
        total_found = len(filtered_by_industry)

        # filter_candidates_df가 기대하는 컬럼명으로 정규화
        to_filter = filtered_by_industry.rename(columns={"induty_name": "industry"})

        p_df, e_df = filter_candidates_df(
            to_filter,
            exclude_konex=exclude_konex,
            require_december_fiscal=True,
        )
        passed_df = p_df
        excluded_df = e_df
        level_used = level

        logger.info(
            "업종(%s) 필터 후: 전체=%d / 통과=%d / 제외=%d",
            level, total_found, len(p_df), len(e_df),
        )

        if len(p_df) >= MIN_CANDIDATES_THRESHOLD:
            break
        if level == INDUSTRY_LEVELS[-1]:
            logger.warning("대분류까지 재시도했으나 후보 %d건으로 부족", len(p_df))
            break

    if passed_df is None or passed_df.empty:
        return ComparableCompanyResult(
            target_company=company_name,
            target_info=target,
            industry_level_used=level_used,
            total_candidates_found=total_found,
            error_message="룰 필터 후 검증 가능한 후보가 없습니다.",
        )

    # FilteredCandidate 리스트로 변환
    passed_candidates = [
        FilteredCandidate(**row)
        for _, row in passed_df.iterrows()
        if not row.get("excluded", False)
    ]
    _excl_iter = excluded_df if (excluded_df is not None and not excluded_df.empty) else passed_df.head(0)
    excluded_candidates = [
        FilteredCandidate(**row)
        for _, row in _excl_iter.iterrows()
    ]

    # ── 5. 사업내용 유사성 검증 ────────────────────────────────────────────
    if not target.business_text:
        # 사업내용 없어도 구조상 후보 목록은 반환 (수동 확인 가능하도록)
        return ComparableCompanyResult(
            target_company=company_name,
            target_info=target,
            comparable_companies=[],
            unverifiable_candidates=[
                VerificationResult(
                    candidate_name=c.name,
                    stock_code=c.stock_code,
                    status="평가대상 사업내용 없음",
                )
                for c in passed_candidates
            ],
            excluded_candidates=excluded_candidates,
            industry_level_used=level_used,
            total_candidates_found=total_found,
            total_after_filter=len(passed_candidates),
            error_message="평가대상 사업내용을 추출하지 못했습니다. 유사도 검증 생략.",
        )

    logger.info("[파이프라인] 유사도 검증 시작: %d건 (최대 %d)", len(passed_candidates), max_verify)

    # 사전 corp_code 조회 (캐시에서 일괄)
    from cache_manager import ensure_corp_codes
    from cache_manager import lookup_corp_code_by_stock

    corp_df = await ensure_corp_codes(dart_api_key)
    corp_code_map = {
        c.stock_code: (lookup_corp_code_by_stock(c.stock_code, corp_df) or "")
        for c in passed_candidates[:max_verify]
    }

    ok_results, unverifiable = await _verify_all(
        targets_biz=target.business_text,
        candidates=passed_candidates,
        dart_key=dart_api_key,
        anthropic_key=anthropic_api_key,
        max_verify=max_verify,
        corp_code_map=corp_code_map,
    )

    sorted_results = _sort_results(ok_results)

    return ComparableCompanyResult(
        target_company=company_name,
        target_info=target,
        comparable_companies=sorted_results,
        unverifiable_candidates=unverifiable,
        excluded_candidates=excluded_candidates,
        industry_level_used=level_used,
        total_candidates_found=total_found,
        total_after_filter=len(passed_candidates),
    )
