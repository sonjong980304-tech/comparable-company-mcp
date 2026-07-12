"""파싱된 재무제표 항목을 마크다운 표로 렌더링한다."""
from __future__ import annotations

from unit_format import format_won

# sj_div 코드 → 재무제표 라벨 (dart_financials._parse_fnltt_items 와 동일 매핑)
SJ_DIV_LABELS = {
    "BS": "재무상태표",
    "IS": "손익계산서",
    "CIS": "포괄손익계산서",
    "CF": "현금흐름표",
    "SCE": "자본변동표",
}

_EMPTY_MESSAGE = "해당 재무제표 종류의 데이터가 없습니다."


def render_statement_table(
    parsed_items: dict,
    sj_div_filter: str,
    company_name: str,
    bsns_year: int,
    period_label: str,
) -> str:
    """{account_id: {label, value, statement_type}} 를 마크다운 표로 변환한다.

    - sj_div_filter 가 "ALL" 이 아니면 해당 재무제표(statement_type)만 필터링한다.
    - 필터링 후 항목이 없으면 안내 문구를 반환한다.
    - value 가 None 인 항목도 행은 유지하고 금액칸은 "-" 로 표시한다.
    """
    parsed_items = parsed_items or {}

    if sj_div_filter and sj_div_filter != "ALL":
        target_label = SJ_DIV_LABELS.get(sj_div_filter, sj_div_filter)
        items = [
            (aid, d)
            for aid, d in parsed_items.items()
            if d.get("statement_type") == target_label
        ]
        statement_name = target_label
    else:
        items = list(parsed_items.items())
        statement_name = "전체 재무제표"

    if not items:
        return _EMPTY_MESSAGE

    lines = [
        f"## {company_name} {bsns_year}년 {period_label} {statement_name}",
        "",
        "| 계정과목 | 금액 |",
        "|---|---:|",
    ]
    for aid, d in items:
        label = (d.get("label") or aid) if isinstance(d, dict) else aid
        value = d.get("value") if isinstance(d, dict) else None
        lines.append(f"| {label} | {format_won(value)} |")

    return "\n".join(lines)
