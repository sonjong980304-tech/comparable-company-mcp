"""일일 캐싱 관리: corpCode.xml + KIND 상장사 목록"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"
CORP_CODE_CACHE = CACHE_DIR / "corp_codes.parquet"
CORP_CODE_XML = CACHE_DIR / "CORPCODE.xml"
KIND_CACHE_PREFIX = "kind_listed_"


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _kind_cache_path() -> Path:
    return CACHE_DIR / f"{KIND_CACHE_PREFIX}{_today_str()}.parquet"


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─── corpCode ───────────────────────────────────────────────────────────────

async def download_corp_codes(api_key: str) -> pd.DataFrame:
    """DART에서 corpCode.xml ZIP을 받아 파싱, 캐시 저장 후 DataFrame 반환."""
    ensure_cache_dir()
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    xml_files = [n for n in zf.namelist() if n.lower().endswith(".xml")]
    if not xml_files:
        xml_files = zf.namelist()
    if not xml_files:
        raise ValueError("DART corpCode ZIP이 비어 있습니다")
    xml_name = xml_files[0]
    xml_bytes = zf.read(xml_name)

    root = ET.fromstring(xml_bytes.decode("utf-8"))
    rows = []
    for item in root.iter("list"):
        rows.append(
            {
                "corp_code": item.findtext("corp_code", "").strip(),
                "corp_name": item.findtext("corp_name", "").strip(),
                "stock_code": item.findtext("stock_code", "").strip(),
                "modify_date": item.findtext("modify_date", "").strip(),
            }
        )

    df = pd.DataFrame(rows)
    df.to_parquet(CORP_CODE_CACHE, index=False)
    logger.info("corpCode 캐시 저장 완료: %d건", len(df))
    return df


def load_corp_codes(api_key: Optional[str] = None) -> pd.DataFrame:
    """캐시된 corp_code DataFrame 로드. 없으면 동기적으로 다운로드."""
    if CORP_CODE_CACHE.exists():
        return pd.read_parquet(CORP_CODE_CACHE)
    if api_key is None:
        raise FileNotFoundError("corpCode 캐시가 없고 api_key도 없음")
    return asyncio.get_event_loop().run_until_complete(download_corp_codes(api_key))


async def ensure_corp_codes(api_key: str) -> pd.DataFrame:
    """비동기 환경에서 corp_code DataFrame 보장."""
    if CORP_CODE_CACHE.exists():
        return pd.read_parquet(CORP_CODE_CACHE)
    return await download_corp_codes(api_key)


def lookup_corp_code_by_name(corp_name: str, df: pd.DataFrame) -> Optional[str]:
    """회사명으로 corp_code 검색 (정확 → 부분 순)."""
    exact = df[df["corp_name"] == corp_name]
    if not exact.empty:
        return exact.iloc[0]["corp_code"]
    partial = df[df["corp_name"].str.contains(corp_name, na=False)]
    if not partial.empty:
        return partial.iloc[0]["corp_code"]
    return None


def lookup_corp_code_by_stock(stock_code: str, df: pd.DataFrame) -> Optional[str]:
    """종목코드로 corp_code 검색."""
    if not stock_code:
        return None
    row = df[df["stock_code"] == stock_code]
    if not row.empty:
        return row.iloc[0]["corp_code"]
    return None


# ─── KIND 상장사 목록 ─────────────────────────────────────────────────────────

def kind_cache_exists() -> bool:
    return _kind_cache_path().exists()


def load_kind_cache() -> pd.DataFrame:
    return pd.read_parquet(_kind_cache_path())


def save_kind_cache(df: pd.DataFrame) -> None:
    ensure_cache_dir()
    df.to_parquet(_kind_cache_path(), index=False)
    logger.info("KIND 상장사 캐시 저장: %d건 → %s", len(df), _kind_cache_path())


def purge_old_kind_caches(keep_days: int = 3) -> None:
    """오래된 KIND 캐시 파일 정리."""
    for path in CACHE_DIR.glob(f"{KIND_CACHE_PREFIX}*.parquet"):
        date_str = path.stem.replace(KIND_CACHE_PREFIX, "")
        if date_str < _today_str():
            try:
                path.unlink()
            except OSError:
                pass
