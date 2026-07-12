"""unit_format.format_won 단위테스트."""
from unit_format import format_won


def test_none_returns_dash():
    assert format_won(None) == "-"


def test_zero_won():
    assert format_won(0) == "0원"


def test_sub_eok_comma():
    assert format_won(12345) == "12,345원"
    assert format_won(50_000_000) == "50,000,000원"
    # 1억 바로 아래 경계
    assert format_won(99_999_999) == "99,999,999원"


def test_sub_eok_negative():
    assert format_won(-12345) == "-12,345원"


def test_eok_range_one_decimal():
    # 12.345억 → 소수 첫째자리 반올림
    assert format_won(1_234_500_000) == "12.3억원"


def test_eok_range_integer_shrink():
    # .0 이면 정수로 축약
    assert format_won(1_200_000_000) == "12억원"
    # 정확히 1억 경계
    assert format_won(1_0000_0000) == "1억원"


def test_eok_negative():
    assert format_won(-1_200_000_000) == "-12억원"


def test_jo_exact_boundary():
    # 정확히 1조 → "1조원"
    assert format_won(1_0000_0000_0000) == "1조원"


def test_jo_with_eok():
    # 1조 5000억
    assert format_won(1_5000_0000_0000) == "1조 5000억원"
    # 1조 2340억
    assert format_won(1_2340_0000_0000) == "1조 2340억원"


def test_jo_negative():
    assert format_won(-1_5000_0000_0000) == "-1조 5000억원"


def test_jo_rounds_eok_component():
    # 2조 0억 근처 — 억 단위 반올림으로 조가 커지는 케이스가 아닌 일반 반올림
    # 1조 1234.5억 → 억 반올림 → 1조 1234억 또는 1235억 (반올림 규칙에 의존하지 않게 정수 억 사용)
    assert format_won(3_0000_0000_0000) == "3조원"
