"""DART fnlttSinglAcntAll 재무제표 취득 + TTL 캐시 + 일일한도(020) 처리.

핵심 함수:
  - is_quota_exceeded(resp)      : status == "020" 판별 (순수)
  - _is_cache_fresh(path, ttl)   : mtime 기준 캐시 신선도 (순수)
  - _parse_fnltt_items(...)      : account_id(표준계정) 기반 파싱 (순수)
  - get_financial_statement(...) : 캐시 → API(CFS→OFS 폴백) → 파싱 조립

네트워크 호출(_fetch_fnltt)만 격리해 테스트에서 mock 하고, 나머지는 순수 로직이다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import httpx

from validate import check_balance_sheet

# httpx 요청 URL 에 crtfc_key(DART 키)가 실리므로 INFO 요청 로그를 차단(키 노출 방지).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"
CACHE_DIR = Path(__file__).parent / "cache" / "financials"

# DART sj_div → 재무제표 종류 라벨
SJ_DIV_LABELS = {
    "BS": "재무상태표",
    "IS": "손익계산서",
    "CIS": "포괄손익계산서",
    "CF": "현금흐름표",
    "SCE": "자본변동표",
}


# ─── 순수 판별/파싱 로직 ──────────────────────────────────────────────────────

def is_quota_exceeded(dart_response: dict) -> bool:
    """DART 응답이 일일 API 한도 초과(status=020)인지 판별한다."""
    return str(dart_response.get("status", "")) == "020"


def _is_cache_fresh(path: Path, ttl_hours: int = 24) -> bool:
    """캐시 파일이 존재하고 mtime 기준 ttl_hours 이내면 True."""
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds < ttl_hours * 3600


def _cache_path(corp_code: str, bsns_year: int, reprt_code: str, fs_div: str) -> Path:
    return CACHE_DIR / f"{corp_code}_{bsns_year}_{reprt_code}_{fs_div}.json"


def _parse_amount(raw: object) -> float | None:
    """thstrm_amount(당기금액) → float. 빈문자/'-'/파싱 실패는 None."""
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if text in ("", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_fnltt_items(
    items: list[dict],
    year: int,
    fs_div: str,
    warnings: list[str],
) -> tuple[dict, str | None]:
    """fnlttSinglAcntAll list → ({account_id: {label, value, statement_type}}, currency).

    - account_id(표준계정) 키 사용. '표준계정코드 미사용' 항목은 제외(건수만 경고).
    - 동일 account_id 가 IS/CIS 등에 중복되면 먼저 나온 항목 유지.
    - value 파싱 불가(빈문자/'-'/형식 오류)는 None + 경고 (예외로 죽지 않음).
    """
    parsed: dict[str, dict] = {}
    currency: str | None = None
    skipped_nonstandard = 0

    for item in items:
        if currency is None:
            cur = str(item.get("currency") or "").strip()
            if cur:
                currency = cur

        account_id = str(item.get("account_id") or "").strip()
        account_nm = str(item.get("account_nm") or "").strip()
        if not account_id or "표준계정코드 미사용" in account_id:
            skipped_nonstandard += 1
            continue
        if account_id in parsed:
            continue  # IS/CIS 중복 등 — 먼저 나온 항목 유지

        raw = item.get("thstrm_amount")
        value = _parse_amount(raw)
        if value is None:
            warnings.append(
                f"{year}/{fs_div} {account_id}({account_nm}): 당기금액 '{raw}' 파싱 불가 → None"
            )

        sj_div = str(item.get("sj_div") or "").strip()
        parsed[account_id] = {
            "label": account_nm,
            "value": value,
            "statement_type": SJ_DIV_LABELS.get(sj_div, sj_div or "기타"),
        }

    if skipped_nonstandard:
        warnings.append(
            f"{year}/{fs_div}: 표준계정코드 미사용 항목 {skipped_nonstandard}건 제외"
        )
    return parsed, currency


# ─── 네트워크 (테스트에서 mock 대상) ─────────────────────────────────────────

def _fetch_fnltt(
    corp_code: str,
    bsns_year: int,
    reprt_code: str,
    fs_div: str,
    api_key: str,
) -> dict:
    """OpenDART fnlttSinglAcntAll.json 단일 호출 → JSON dict."""
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{BASE_URL}/fnlttSinglAcntAll.json", params=params)
        resp.raise_for_status()
    return resp.json()


# ─── 조립 ────────────────────────────────────────────────────────────────────

def _build_result(
    corp_code: str,
    data: dict,
    fs_div: str,
    bsns_year: int,
    cached: bool,
    warnings: list[str],
    status: str = "ok",
) -> dict:
    items = data.get("list") or []
    parsed, currency = _parse_fnltt_items(items, bsns_year, fs_div, warnings)
    warnings.extend(check_balance_sheet(parsed))

    rcept_no: str | None = None
    for item in items:
        rn = str(item.get("rcept_no") or "").strip()
        if rn:
            rcept_no = rn
            break
    source_url = (
        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else None
    )

    return {
        "corp_code": corp_code,
        "fs_div_used": fs_div,
        "currency": currency,
        "parsed_items": parsed,
        "rcept_no": rcept_no,
        "source_url": source_url,
        "cached": cached,
        "status": status,
        "warnings": warnings,
        "error_message": None,
    }


def _empty_result(corp_code: str, status: str, warnings: list[str], error_message: str) -> dict:
    return {
        "corp_code": corp_code,
        "fs_div_used": None,
        "currency": None,
        "parsed_items": {},
        "rcept_no": None,
        "source_url": None,
        "cached": False,
        "status": status,
        "warnings": warnings,
        "error_message": error_message,
    }


def get_financial_statement(
    corp_code: str,
    corp_name: str,
    bsns_year: int,
    reprt_code: str,
    fs_div_preference: str = "CFS",
) -> dict:
    """재무제표를 취득한다: 신선한 캐시 → API(CFS→OFS 폴백) → 파싱.

    - 020(일일한도) 이면 캐시(만료 포함)가 있으면 그것을 사용(경고), 없으면
      status="quota_exceeded" 로 명확히 반환한다(크래시 금지).
    - 성공 응답은 캐시에 저장한다.
    """
    warnings: list[str] = []

    pref = (fs_div_preference or "CFS").strip().upper()
    if pref not in ("CFS", "OFS"):
        warnings.append(f"알 수 없는 fs_div_preference '{fs_div_preference}' → 'CFS' 로 대체")
        pref = "CFS"
    try_order = [pref, "OFS" if pref == "CFS" else "CFS"]

    # 1) 신선한 캐시 우선
    for fs_div in try_order:
        cpath = _cache_path(corp_code, bsns_year, reprt_code, fs_div)
        if _is_cache_fresh(cpath):
            try:
                data = json.loads(cpath.read_text(encoding="utf-8"))
            except Exception as exc:  # 손상 캐시 — 무시하고 진행
                warnings.append(f"캐시 로드 실패({fs_div}): {exc}")
                continue
            return _build_result(corp_code, data, fs_div, bsns_year, cached=True, warnings=warnings)

    # 2) API 호출 전 키 확인 (신선 캐시가 없을 때만 키가 필요)
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        return _empty_result(
            corp_code,
            "error",
            warnings,
            "DART_API_KEY 환경변수가 없어 재무제표 API를 호출할 수 없습니다. .env 를 확인하세요.",
        )

    # 3) API 호출 (CFS → OFS 폴백)
    quota_hit = False
    fail_reasons: list[str] = []
    for fs_div in try_order:
        try:
            data = _fetch_fnltt(corp_code, bsns_year, reprt_code, fs_div, api_key)
        except Exception as exc:  # HTTP/네트워크/JSON 오류 — 예외로 죽지 않는다
            fail_reasons.append(f"{fs_div}: 요청 실패({exc})")
            continue

        if is_quota_exceeded(data):
            quota_hit = True
            fail_reasons.append(f"{fs_div}: 일일 한도 초과(020)")
            continue

        status = str(data.get("status", ""))
        items = data.get("list") or []
        if status != "000" or not items:
            reason = "빈 응답(list 없음)" if status == "000" else f"status={status} {data.get('message', '')}".strip()
            fail_reasons.append(f"{fs_div}: {reason}")
            continue

        # 성공 → 캐시 저장
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(corp_code, bsns_year, reprt_code, fs_div).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            warnings.append(f"캐시 저장 실패({fs_div}): {exc}")

        if fs_div != try_order[0]:
            warnings.append(
                f"{try_order[0]} 취득 불가({'; '.join(fail_reasons)}) → {fs_div} 로 폴백"
            )
        return _build_result(corp_code, data, fs_div, bsns_year, cached=False, warnings=warnings)

    # 4) 모두 실패 — 020 이면 만료 캐시라도 사용
    if quota_hit:
        for fs_div in try_order:
            cpath = _cache_path(corp_code, bsns_year, reprt_code, fs_div)
            if cpath.exists():
                try:
                    data = json.loads(cpath.read_text(encoding="utf-8"))
                except Exception:
                    continue
                warnings.append("DART 일일 한도 초과(020) — 만료된 캐시로 응답합니다.")
                return _build_result(corp_code, data, fs_div, bsns_year, cached=True, warnings=warnings)
        return _empty_result(
            corp_code,
            "quota_exceeded",
            warnings,
            "DART 일일 API 한도 초과(020)이며 사용할 캐시가 없습니다. 잠시 후 다시 시도하세요. "
            + "; ".join(fail_reasons),
        )

    # 5) 020 이 아닌 실패 (데이터 없음/네트워크)
    return _empty_result(
        corp_code,
        "no_data",
        warnings,
        "재무제표를 가져오지 못했습니다: " + "; ".join(fail_reasons),
    )
