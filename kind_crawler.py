"""KIND(kind.krx.co.kr) 크롤링 + 일일 캐싱 + 업종 레벨별 필터링."""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from cache_manager import (
    kind_cache_exists,
    load_kind_cache,
    purge_old_kind_caches,
    save_kind_cache,
)
from models import CandidateCompany

logger = logging.getLogger(__name__)

KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"

MARKET_MAP = {
    "KOSPI": "stockMkt",
    "KOSDAQ": "kosdaqMkt",
    "ALL": "",
}

# 大분류 섹터 키워드 매핑 (대분류 수준 매칭에 사용)
MAJOR_SECTOR_MAP: dict[str, list[str]] = {
    "제조업": ["제조", "생산"],
    "정보통신업": ["정보통신", "소프트웨어", "통신", "인터넷", "게임"],
    "금융보험업": ["금융", "보험", "은행", "증권"],
    "도매소매업": ["도매", "소매", "유통"],
    "건설업": ["건설", "토목", "건축"],
    "부동산업": ["부동산", "임대"],
    "운수창고업": ["운수", "창고", "물류"],
    "전문과학기술": ["전문", "과학", "기술서비스"],
    "의료보건": ["의료", "보건", "병원"],
    "교육서비스": ["교육"],
    "예술스포츠": ["예술", "스포츠", "여가"],
    "서비스업": ["서비스", "컨설팅"],
}


# ─── 크롤링 ─────────────────────────────────────────────────────────────────

async def _crawl_single_market(market_type_param: str) -> pd.DataFrame:
    """KIND에서 특정 시장 상장사 목록 크롤링."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://kind.krx.co.kr/corpgeneral/corpList.do",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "method": "getItems",
        "searchType": "13",
        "marketType": market_type_param,
        "industry": "",
        "fiscalYearEnd": "all",
        "pageSize": "5000",
        "currentPage": "1",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(KIND_URL, data=payload, headers=headers)
        resp.raise_for_status()

    html = resp.content.decode("euc-kr", errors="replace")
    return _parse_kind_table(html, market_type_param)


def _parse_kind_table(html: str, market_type_param: str) -> pd.DataFrame:
    """HTML 테이블 파싱 → DataFrame."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        logger.warning("KIND 응답에서 테이블을 찾지 못함 (market=%s)", market_type_param)
        return pd.DataFrame()

    headers: list[str] = []
    rows: list[dict] = []

    thead = table.find("thead")
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all("th")]

    tbody = table.find("tbody")
    if not tbody:
        tbody = table

    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        row_data: dict = {}
        for i, td in enumerate(cells):
            key = headers[i] if i < len(headers) else f"col{i}"
            # 회사명 링크에서 텍스트만 추출
            a_tag = td.find("a")
            row_data[key] = (a_tag or td).get_text(strip=True)
        rows.append(row_data)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = _normalize_columns(df, market_type_param)
    return df


def _normalize_columns(df: pd.DataFrame, market_type_param: str) -> pd.DataFrame:
    """컬럼명 표준화."""
    rename = {}
    for col in df.columns:
        col_lower = col.replace(" ", "").lower()
        if "회사명" in col or col_lower == "회사명":
            rename[col] = "company_name"
        elif "종목코드" in col or "코드" in col:
            rename[col] = "stock_code"
        elif "업종" in col:
            rename[col] = "industry"
        elif "주요제품" in col or "제품" in col:
            rename[col] = "main_products"
        elif "상장일" in col:
            rename[col] = "listing_date"
        elif "결산월" in col:
            rename[col] = "fiscal_month"
        elif "대표자" in col:
            rename[col] = "ceo_name"
        elif "홈페이지" in col:
            rename[col] = "homepage"
        elif "지역" in col:
            rename[col] = "region"

    df = df.rename(columns=rename)

    # market_type 컬럼 추가
    market_label = {
        "stockMkt": "KOSPI",
        "kosdaqMkt": "KOSDAQ",
        "": "ALL",
    }.get(market_type_param, market_type_param)
    df["market_type"] = market_label

    # 필수 컬럼 없으면 빈 값으로
    for col in ["company_name", "stock_code", "industry", "fiscal_month", "region", "main_products"]:
        if col not in df.columns:
            df[col] = ""

    # 종목코드 6자리 정규화
    if "stock_code" in df.columns:
        df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)

    return df


# ─── 공개 함수 ───────────────────────────────────────────────────────────────

async def get_all_listed_companies(force_refresh: bool = False) -> pd.DataFrame:
    """
    오늘 날짜 캐시 우선 로드. 없거나 force_refresh면 KIND에서 전체 목록 1회 크롤링 후 저장.
    KOSPI + KOSDAQ 합쳐서 반환.
    """
    if not force_refresh and kind_cache_exists():
        logger.info("KIND 캐시 로드")
        return load_kind_cache()

    logger.info("KIND 크롤링 시작 (KOSPI + KOSDAQ)")
    dfs = []
    for market_param in ["stockMkt", "kosdaqMkt"]:
        try:
            df = await _crawl_single_market(market_param)
            if not df.empty:
                dfs.append(df)
                logger.info("KIND %s: %d건", market_param, len(df))
        except Exception as exc:
            logger.error("KIND %s 크롤링 실패: %s", market_param, exc)

    if not dfs:
        raise RuntimeError("KIND 크롤링 완전 실패: KOSPI/KOSDAQ 모두 데이터 없음")

    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["stock_code"])
    save_kind_cache(combined)
    purge_old_kind_caches()
    return combined


def _major_sector_of(industry_name: str) -> str:
    """업종명에서 대분류 섹터 키 추출."""
    for sector, keywords in MAJOR_SECTOR_MAP.items():
        if any(kw in industry_name for kw in keywords):
            return sector
    return "기타"


def filter_by_industry(
    df: pd.DataFrame,
    induty_name: str,
    industry_level: str = "세분류",
    induty_code: Optional[str] = None,
) -> pd.DataFrame:
    """
    KIND 전체 목록에서 업종 레벨별로 필터링.

    Args:
        df: KIND 전체 상장사 DataFrame
        induty_name: DART에서 가져온 평가대상 업종명
        industry_level: "세분류" | "중분류" | "대분류"
        induty_code: (선택) DART 업종코드, 향후 정밀 매칭에 사용
    """
    if "industry" not in df.columns or df.empty:
        return pd.DataFrame()

    industry_col = df["industry"].fillna("")

    if industry_level == "세분류":
        mask = industry_col == induty_name
        if not mask.any():
            # 대소문자/공백 무관 부분 매칭 fallback
            mask = industry_col.str.contains(
                re.escape(induty_name[:10]), na=False
            )

    elif industry_level == "중분류":
        # 업종명 앞 2~4 어절 공통 부분으로 매칭
        words = induty_name.split()
        prefix = " ".join(words[:min(3, len(words))])
        if len(prefix) < 4:
            prefix = induty_name[:6]
        mask = industry_col.str.contains(re.escape(prefix), na=False)
        if not mask.any():
            mask = _partial_match_mask(industry_col, induty_name, ratio=0.5)

    elif industry_level == "대분류":
        target_sector = _major_sector_of(induty_name)
        if target_sector == "기타":
            # 대분류 판단 불가 → 중분류 방식으로 fallback
            words = induty_name.split()
            prefix = " ".join(words[:2]) if len(words) >= 2 else induty_name[:4]
            mask = industry_col.str.contains(re.escape(prefix), na=False)
        else:
            kws = MAJOR_SECTOR_MAP[target_sector]
            mask = industry_col.apply(lambda x: any(kw in x for kw in kws))

    else:
        raise ValueError(f"지원하지 않는 industry_level: {industry_level}")

    filtered = df[mask].copy()
    logger.info(
        "업종 필터(%s, '%s'): 전체 %d → %d건",
        industry_level, induty_name, len(df), len(filtered),
    )
    return filtered


def _partial_match_mask(series: "pd.Series[str]", target: str, ratio: float) -> "pd.Series[bool]":
    """target 어절의 일정 비율 이상 포함 시 매칭."""
    words = target.split()
    if not words:
        return pd.Series([False] * len(series))

    def score(s: str) -> float:
        return sum(1 for w in words if w in s) / len(words)

    return series.apply(score) >= ratio


def df_to_candidates(df: pd.DataFrame) -> list[CandidateCompany]:
    """KIND DataFrame → CandidateCompany 리스트 변환."""
    result = []
    for _, row in df.iterrows():
        try:
            result.append(
                CandidateCompany(
                    name=str(row.get("company_name", "")),
                    stock_code=str(row.get("stock_code", "")),
                    industry=str(row.get("industry", "")),
                    fiscal_month=str(row.get("fiscal_month", "")),
                    region=str(row.get("region", "")) or None,
                    market_type=str(row.get("market_type", "")) or None,
                    main_products=str(row.get("main_products", "")) or None,
                )
            )
        except Exception:
            pass
    return result


