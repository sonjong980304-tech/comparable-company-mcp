"""한국어 키워드 → DART OpenAPI 파라미터 매핑 (순수 함수, 부작용 없음).

- resolve_statement_type: 재무제표 종류 키워드 → sj_div 코드(BS/IS/CIS/CF/SCE) 또는 ALL
- resolve_period:         기간 키워드 → reprt_code(11011~11014)

이미 코드 형태가 들어오면 그대로 통과시킨다. 모르는 키워드는 ValueError.
"""
from __future__ import annotations

# 재무제표 종류 키워드 → sj_div 코드
_STATEMENT_MAP = {
    "재무상태표": "BS",
    "대차대조표": "BS",
    "손익계산서": "IS",
    "포괄손익계산서": "CIS",
    "현금흐름표": "CF",
    "자본변동표": "SCE",
    "전체": "ALL",
}
_VALID_SJ_CODES = {"BS", "IS", "CIS", "CF", "SCE", "ALL"}

# 기간 키워드 → reprt_code
_PERIOD_MAP = {
    "1분기": "11013",
    "반기": "11012",
    "2분기": "11012",
    "상반기": "11012",
    "3분기": "11014",
    "사업보고서": "11011",
    "연간": "11011",
    "연도": "11011",
    "4분기": "11011",
    "전체": "11011",
}
_VALID_REPRT_CODES = {"11011", "11012", "11013", "11014"}


def resolve_statement_type(keyword: str) -> str:
    """재무제표 종류 키워드를 sj_div 코드(또는 ALL)로 변환한다."""
    k = (keyword or "").strip()
    if not k:
        raise ValueError(_statement_help(""))

    upper = k.upper()
    if upper in _VALID_SJ_CODES:  # 이미 코드(대/소문자 무관)
        return upper
    if k in _STATEMENT_MAP:  # 정확 일치 (부분문자열 오탐 방지)
        return _STATEMENT_MAP[k]
    if k.lower() == "all":
        return "ALL"
    raise ValueError(_statement_help(keyword))


def resolve_period(keyword: str) -> str:
    """기간 키워드를 reprt_code(11011~11014)로 변환한다."""
    k = (keyword or "").strip()
    if not k:
        raise ValueError(_period_help(""))

    if k.isdigit() and len(k) == 5:  # 이미 reprt_code
        return k
    if k in _PERIOD_MAP:
        return _PERIOD_MAP[k]
    raise ValueError(_period_help(keyword))


def _statement_help(bad: str) -> str:
    return (
        f"알 수 없는 재무제표 종류 '{bad}'. 유효 값: "
        "재무상태표, 대차대조표, 손익계산서, 포괄손익계산서, 현금흐름표, 자본변동표, 전체 "
        "(또는 코드 BS/IS/CIS/CF/SCE/ALL)."
    )


def _period_help(bad: str) -> str:
    return (
        f"알 수 없는 기간 '{bad}'. 유효 값: "
        "1분기, 반기(=2분기/상반기), 3분기, 사업보고서(=연간/연도/4분기/전체) "
        "(또는 reprt_code 11011~11014)."
    )
