"""원(WON) 단위 금액을 사람이 읽기 쉬운 한국어 문자열로 변환한다.

경계값:
  - None            → "-"
  - abs >= 1조       → "{X}조 {Y}억원" (Y=0이면 "{X}조원")
  - 1억 <= abs < 1조 → "{X}억원" (소수 첫째자리, .0이면 정수로 축약)
  - abs < 1억        → "{value:,.0f}원" (3자리 콤마)
  음수는 부호를 유지한다.
"""
from __future__ import annotations

_EOK = 1_0000_0000  # 1억
_JO = 1_0000_0000_0000  # 1조


def format_won(value: float | int | None) -> str:
    if value is None:
        return "-"

    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if magnitude >= _JO:
        # 억 단위로 반올림한 뒤 조/억으로 분해 → 억 성분이 10000을 넘으면 조로 올림처리됨
        total_eok = round(magnitude / _EOK)
        jo = total_eok // 10000
        eok = total_eok % 10000
        if eok == 0:
            return f"{sign}{jo}조원"
        return f"{sign}{jo}조 {eok}억원"

    if magnitude >= _EOK:
        eok = round(magnitude / _EOK, 1)
        if eok == int(eok):
            return f"{sign}{int(eok)}억원"
        return f"{sign}{eok}억원"

    # 1억 미만: 원 단위 콤마 (부호 포함해 그대로 포맷)
    return f"{value:,.0f}원"
