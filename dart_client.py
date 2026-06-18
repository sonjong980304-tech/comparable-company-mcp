"""DART OpenAPI 래퍼: corp_code 캐싱, 기업 정보, 사업 내용 추출."""
from __future__ import annotations

import io
import logging
import re
import warnings
import zipfile
from typing import Optional

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from cache_manager import (
    ensure_corp_codes,
    lookup_corp_code_by_name,
    lookup_corp_code_by_stock,
)
from models import TargetCompanyInfo

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"

# 사업 내용 섹션 시작 키워드 (순서 중요 — 더 구체적인 것 먼저)
BUSI_START_KWS = [
    "II. 사업의 내용",
    "Ⅱ. 사업의 내용",
    "2. 사업의 내용",
    "사업의 내용",
    "사업의 개요",
    "사업 개요",
    "사업개요",
    "영업의 개황",
    "영업개황",
    "회사의 개요",
    "사업의 주요내용",
    "주요사업",
    "사업내용",
    "회사의 사업",
    "사업 현황",
    "주요 사업",
]

# 다음 주요 섹션 시작 → 추출 종료
BUSI_END_KWS = [
    "III.", "Ⅲ.", "3. 재무", "재무에 관한", "재무상태",
    "주주에 관한", "임원에 관한", "IV.", "Ⅳ.",
]

# 공시 유형 → (pblntf_detail_ty, 표시 레이블)
# 비상장사는 A001~A003 공시 없음 → F001/F002(감사보고서) fallback
REPORT_FALLBACK = [
    ("A001", "사업보고서"),
    ("A002", "반기보고서"),
    ("A003", "분기보고서"),
    ("F001", "감사보고서"),
    ("F002", "연결감사보고서"),
    ("D001", "증권신고서(지분증권)"),
    ("D002", "증권신고서(채무증권)"),
    ("D003", "증권신고서(파생결합증권)"),
    ("D004", "증권신고서(증권예탁증권)"),
    ("C001", "투자설명서"),
]


# ─── HTTP 헬퍼 ─────────────────────────────────────────────────────────────

async def _get_json(path: str, params: dict, timeout: float = 30.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{BASE_URL}/{path}", params=params)
        resp.raise_for_status()
    return resp.json()


# ─── corp_code 조회 ────────────────────────────────────────────────────────

async def find_corp_code(company_name: str, api_key: str) -> Optional[str]:
    """회사명으로 DART corp_code 반환 (캐시 우선)."""
    df = await ensure_corp_codes(api_key)
    return lookup_corp_code_by_name(company_name, df)


async def find_corp_code_by_stock(stock_code: str, api_key: str) -> Optional[str]:
    """종목코드로 DART corp_code 반환."""
    df = await ensure_corp_codes(api_key)
    return lookup_corp_code_by_stock(stock_code, df)


# ─── 기업 개황 ──────────────────────────────────────────────────────────────

async def get_company_info(corp_code: str, api_key: str) -> dict:
    """DART company.json 호출 → 기업 개황 반환."""
    data = await _get_json("company.json", {"crtfc_key": api_key, "corp_code": corp_code})
    if data.get("status") != "000":
        raise ValueError(f"DART 기업개황 오류: {data.get('message')} (corp_code={corp_code})")
    return data


# ─── 공시 목록 ──────────────────────────────────────────────────────────────

async def _get_report_list(
    corp_code: str,
    detail_ty: str,
    api_key: str,
    page_count: int = 5,
) -> list[dict]:
    """특정 유형의 최신 공시 목록 반환.
    bgn_de/end_de 없으면 DART가 corp_code+pblntf_detail_ty 조합을 빈 결과로 반환하므로 필수.
    """
    from datetime import date
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "pblntf_detail_ty": detail_ty,
        "bgn_de": "20150101",
        "end_de": date.today().strftime("%Y%m%d"),
        "sort": "date",
        "sort_mth": "desc",
        "page_count": page_count,
    }
    data = await _get_json("list.json", params, timeout=20.0)
    if data.get("status") not in ("000", "013"):  # 013 = 조회 데이터 없음
        logger.warning("list.json 오류: %s / %s", data.get("status"), data.get("message"))
    return data.get("list") or []


# ─── 사업 내용 텍스트 추출 ─────────────────────────────────────────────────

async def _download_document_zip(rcept_no: str, api_key: str) -> Optional[bytes]:
    """document.xml 엔드포인트에서 ZIP 바이너리 다운로드."""
    url = f"{BASE_URL}/document.xml"
    params = {"rcept_no": rcept_no, "crtfc_key": api_key}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, params=params)
        # ZIP 매직 넘버 확인
        if resp.content[:2] == b"PK":
            return resp.content
        # 에러 JSON일 가능성
        logger.debug("document.xml 응답이 ZIP이 아님: rcept_no=%s", rcept_no)
        return None
    except Exception as exc:
        logger.warning("document.xml 다운로드 실패(%s): %s", rcept_no, exc)
        return None


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "euc-kr", "cp949", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _extract_business_section(full_text: str, max_chars: int = 15000) -> str:
    """전체 텍스트에서 사업 내용 구간 추출."""
    # 시작 위치 탐색
    start = -1
    for kw in BUSI_START_KWS:
        idx = full_text.find(kw)
        if idx != -1:
            start = idx
            break

    if start == -1:
        # 키워드를 못 찾으면 앞 15,000자 반환 (LLM이 판단)
        return full_text[:max_chars]

    # 종료 위치 탐색 (목차 건너뛰기 위해 시작에서 최소 5,000자 이후부터 탐색)
    end = len(full_text)
    for kw in BUSI_END_KWS:
        idx = full_text.find(kw, start + 5000)
        if idx != -1 and idx < end:
            end = idx

    return full_text[start:end][:max_chars]


async def _extract_text_from_zip(zip_bytes: bytes) -> Optional[str]:
    """ZIP 파일에서 사업 내용 텍스트 추출."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return None

    names = zf.namelist()
    # 서브 파일(파일명에 _숫자 패턴) 먼저, 그 다음 메인 파일. 각 그룹 내 크기 내림차순.
    # DART ZIP: {rcept_no}.xml = 목차, {rcept_no}_{num}.xml = 실제 내용
    import re as _re
    def _zip_sort_key(name: str) -> tuple:
        basename = name.split("/")[-1]
        is_sub = bool(_re.search(r"_\d+\.", basename))
        return (0 if is_sub else 1, -zf.getinfo(name).file_size)

    html_files = sorted(
        [n for n in names if n.lower().endswith((".html", ".htm", ".xml"))],
        key=_zip_sort_key,
    )

    best_text: Optional[str] = None

    for fname in html_files:
        raw = zf.read(fname)
        text = _html_to_text(_decode_bytes(raw))

        # 사업 키워드 포함 여부 확인
        if any(kw in text for kw in BUSI_START_KWS):
            best_text = _extract_business_section(text)
            break

    # 키워드 미발견 → 가장 큰 파일로 fallback
    if best_text is None and html_files:
        raw = zf.read(html_files[0])
        text = _html_to_text(_decode_bytes(raw))
        best_text = _extract_business_section(text)

    return best_text if best_text else None


async def _get_business_text_from_report(
    corp_code: str,
    detail_ty: str,
    api_key: str,
) -> tuple[Optional[str], Optional[str]]:
    """특정 유형 공시에서 사업 내용 추출. (text, source_label) 반환."""
    label_map = dict(REPORT_FALLBACK)
    reports = await _get_report_list(corp_code, detail_ty, api_key)
    if not reports:
        return None, None

    rcept_no = reports[0]["rcept_no"]
    zip_bytes = await _download_document_zip(rcept_no, api_key)
    if not zip_bytes:
        return None, None

    text = await _extract_text_from_zip(zip_bytes)
    if text:
        return text, f"{label_map.get(detail_ty, detail_ty)}({rcept_no})"
    return None, None


async def get_business_text(
    corp_code: str,
    api_key: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    fallback 순서에 따라 사업 내용 텍스트 추출.
    Returns: (business_text, source_report_label)
    """
    for detail_ty, _label in REPORT_FALLBACK:
        text, source = await _get_business_text_from_report(corp_code, detail_ty, api_key)
        if text:
            return text, source
        logger.debug("사업 내용 추출 실패: corp_code=%s, type=%s", corp_code, detail_ty)

    return None, None


# ─── 통합 진입점 ─────────────────────────────────────────────────────────────

async def get_target_company_info(company_name: str, api_key: str) -> TargetCompanyInfo:
    """
    평가대상 회사의 corp_code, 업종 코드/명, 사업 내용 텍스트를 조합하여 반환.
    """
    corp_code = await find_corp_code(company_name, api_key)
    if not corp_code:
        return TargetCompanyInfo(
            corp_code="",
            corp_name=company_name,
            induty_code="",
            induty_name="",
            status="회사명 미발견",
            error_message=f"'{company_name}'을 DART에서 찾을 수 없습니다.",
        )

    try:
        info = await get_company_info(corp_code, api_key)
    except Exception as exc:
        return TargetCompanyInfo(
            corp_code=corp_code,
            corp_name=company_name,
            induty_code="",
            induty_name="",
            status="기업개황 조회 실패",
            error_message=str(exc),
        )

    induty_code = info.get("induty_code", "")
    induty_name = info.get("induty_nm", "")
    stock_code = info.get("stock_code", "")

    biz_text, source = await get_business_text(corp_code, api_key)

    return TargetCompanyInfo(
        corp_code=corp_code,
        corp_name=info.get("corp_name", company_name),
        stock_code=stock_code,
        induty_code=re.sub(r"\s+", "", induty_code),
        induty_name=induty_name,
        business_text=biz_text,
        source_report=source,
        status="ok" if biz_text else "사업내용 확인불가",
    )
