"""
DART API 기반 상장사 목록 수집.
corpCode.xml(stock_code 있는 기업) → company.json 배치 호출 → parquet 캐시

list.json(수백 페이지) 대신 corpCode 캐시를 활용하여 3,000~4,000건만 조회.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from cache_manager import CACHE_DIR, CORP_CODE_CACHE, ensure_cache_dir

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
DART_CACHE_PREFIX = "dart_companies_"
CONCURRENCY = 5           # 동시 company.json 호출 수
REQUEST_DELAY = 0.2       # 요청 간 딜레이 (초)
MAX_RETRIES = 3           # 실패 시 재시도 횟수


# ─── 캐시 관리 ──────────────────────────────────────────────────────────────

def _dart_cache_path() -> Path:
    return CACHE_DIR / f"{DART_CACHE_PREFIX}{date.today().strftime('%Y%m%d')}.parquet"


def _latest_dart_cache() -> Optional[Path]:
    """날짜 무관하게 가장 최근 DART 캐시 파일 반환. 없으면 None."""
    files = sorted(CACHE_DIR.glob(f"{DART_CACHE_PREFIX}*.parquet"), reverse=True)
    return files[0] if files else None


def dart_cache_exists() -> bool:
    return _latest_dart_cache() is not None


def load_dart_cache() -> pd.DataFrame:
    path = _latest_dart_cache()
    if path is None:
        raise FileNotFoundError("DART 상장사 캐시 파일이 없습니다")
    logger.info("DART 캐시 로드: %s", path.name)
    return pd.read_parquet(path)


def save_dart_cache(df: pd.DataFrame) -> None:
    ensure_cache_dir()
    path = _dart_cache_path()
    df.to_parquet(path, index=False)
    logger.info("DART 상장사 캐시 저장: %d건 → %s", len(df), path)


# ─── corpCode 캐시에서 상장사 corp_code 추출 ─────────────────────────────────

def _get_listed_corp_codes() -> list[str]:
    """corpCode 캐시에서 stock_code가 있는 기업의 corp_code 목록 반환."""
    if not CORP_CODE_CACHE.exists():
        raise FileNotFoundError(
            "corpCode 캐시가 없습니다. ensure_corp_codes(api_key)를 먼저 호출하세요."
        )
    df = pd.read_parquet(CORP_CODE_CACHE)
    listed = df[df["stock_code"].str.strip().str.len() > 0]
    logger.info("corpCode 캐시에서 stock_code 있는 기업: %d건", len(listed))
    return listed["corp_code"].tolist()


# ─── company.json 배치 호출 ────────────────────────────────────────────────

async def _fetch_company_info(
    client: httpx.AsyncClient,
    api_key: str,
    corp_code: str,
    sem: asyncio.Semaphore,
) -> Optional[dict]:
    """company.json 호출. KOSPI(Y)/KOSDAQ(K)만 반환, 나머지는 None."""
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                await asyncio.sleep(REQUEST_DELAY)
                r = await client.get(
                    f"{BASE_URL}/company.json",
                    params={"crtfc_key": api_key, "corp_code": corp_code},
                    timeout=15.0,
                )
                d = r.json()
                if d.get("status") != "000":
                    return None
                corp_cls = d.get("corp_cls", "")
                if corp_cls not in ("Y", "K"):
                    return None
                return {
                    "corp_code": corp_code,
                    "corp_name": d.get("corp_name", ""),
                    "stock_code": d.get("stock_code", ""),
                    "induty_code": d.get("induty_code", ""),
                    "induty_name": d.get("induty_nm", ""),
                    "acc_mt": d.get("acc_mt", ""),
                    "ceo_nm": d.get("ceo_nm", ""),
                    "adres": d.get("adres", ""),
                    "market_type": "KOSPI" if corp_cls == "Y" else "KOSDAQ",
                }
            except Exception as exc:
                wait = 2 ** attempt
                logger.debug(
                    "company.json 실패(%s) 시도%d/%d: %s — %ds 후 재시도",
                    corp_code, attempt + 1, MAX_RETRIES, exc, wait,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
        return None


async def _batch_fetch_company_info(corp_codes: list[str], api_key: str) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            _fetch_company_info(client, api_key, corp_code, sem)
            for corp_code in corp_codes
        ]
        results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


# ─── 공개 API ─────────────────────────────────────────────────────────────

async def get_dart_listed_companies(
    api_key: str,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    DART 기반 KOSPI/KOSDAQ 상장사 목록 반환 (캐시 우선).

    캐시가 있으면 날짜 무관하게 재사용.
    없으면 corpCode.xml(stock_code 있는 기업, ~3,970건) → company.json 배치 호출.
    최초 수집 시 약 3~5분 소요.
    """
    if not force_refresh and dart_cache_exists():
        return load_dart_cache()

    logger.info("DART 상장사 목록 신규 수집 시작 (corpCode 기반)...")

    # corpCode 캐시가 없으면 먼저 다운로드
    if not CORP_CODE_CACHE.exists():
        from cache_manager import download_corp_codes
        await download_corp_codes(api_key)

    corp_codes = _get_listed_corp_codes()
    logger.info("company.json 배치 호출 시작: %d건", len(corp_codes))
    rows = await _batch_fetch_company_info(corp_codes, api_key)

    df = pd.DataFrame(rows)
    if "acc_mt" in df.columns:
        df["fiscal_month"] = df["acc_mt"].astype(str).str.zfill(2) + "월"
    else:
        df["fiscal_month"] = ""

    save_dart_cache(df)
    logger.info("DART 상장사 수집 완료: %d건 (KOSPI+KOSDAQ)", len(df))
    return df


def filter_dart_by_industry(
    df: pd.DataFrame,
    induty_code: str,
    induty_name: str,
    industry_level: str = "세분류",
) -> pd.DataFrame:
    """
    DART 상장사 DataFrame에서 업종 레벨별 필터링.
    induty_code 앞자리 매칭 우선, 없으면 induty_name 텍스트 매칭.
    """
    if df.empty:
        return df

    code_col = df["induty_code"].fillna("")
    name_col = df["induty_name"].fillna("")
    target_code = induty_code.strip()

    if industry_level == "세분류":
        prefix = target_code[:4] if len(target_code) >= 4 else target_code
        mask = code_col.str.startswith(prefix) if prefix else (name_col == induty_name)

    elif industry_level == "중분류":
        prefix = target_code[:3] if len(target_code) >= 3 else target_code[:2]
        mask = code_col.str.startswith(prefix) if prefix else name_col.str.contains(
            induty_name.split()[0] if induty_name else "", na=False
        )

    elif industry_level == "대분류":
        prefix = target_code[:2] if len(target_code) >= 2 else target_code
        mask = code_col.str.startswith(prefix) if prefix else pd.Series([False] * len(df))

    else:
        raise ValueError(f"지원하지 않는 industry_level: {industry_level}")

    filtered = df[mask].copy()
    logger.info(
        "DART 업종 필터(%s, code=%s): 전체 %d → %d건",
        industry_level, target_code, len(df), len(filtered),
    )
    return filtered
