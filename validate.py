"""재무제표 기초 정합성 검증 (대차평형 등).

확신 없으면 단정하지 않는다 — 필요 계정이 없거나 값이 None이면 검증을 건너뛰고
빈 경고 목록을 반환한다(계산 실패를 오탐으로 보고하지 않는다).
"""
from __future__ import annotations

_ASSETS_ID = "ifrs-full_Assets"
_LIABILITIES_ID = "ifrs-full_Liabilities"
_EQUITY_ID = "ifrs-full_Equity"

_RELATIVE_TOLERANCE = 0.001  # 자산총계 대비 0.1%까지는 반올림 오차로 허용


def check_balance_sheet(parsed_items: dict) -> list[str]:
    """자산총계 = 부채총계 + 자본총계 인지 확인한다.

    표준계정(ifrs-full_Assets/Liabilities/Equity) 중 하나라도 없거나 값이 None이면
    검증하지 않고 빈 리스트를 반환한다.
    """
    assets = _get_value(parsed_items, _ASSETS_ID)
    liabilities = _get_value(parsed_items, _LIABILITIES_ID)
    equity = _get_value(parsed_items, _EQUITY_ID)

    if assets is None or liabilities is None or equity is None:
        return []

    diff = assets - (liabilities + equity)
    tolerance = max(abs(assets) * _RELATIVE_TOLERANCE, 1.0)
    if abs(diff) > tolerance:
        return [
            f"⚠ 대차평형 불일치: 자산총계({assets:,.0f}) ≠ "
            f"부채총계+자본총계({liabilities + equity:,.0f}) (차이 {diff:,.0f})"
        ]
    return []


def _get_value(parsed_items: dict, account_id: str) -> float | None:
    entry = parsed_items.get(account_id)
    if not entry:
        return None
    return entry.get("value")
