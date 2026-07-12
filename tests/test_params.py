"""params.resolve_statement_type / resolve_period 단위테스트."""
import pytest

from params import resolve_period, resolve_statement_type


# ─── resolve_statement_type ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("재무상태표", "BS"),
        ("대차대조표", "BS"),
        ("손익계산서", "IS"),
        ("포괄손익계산서", "CIS"),
        ("현금흐름표", "CF"),
        ("자본변동표", "SCE"),
        ("전체", "ALL"),
        ("all", "ALL"),
        ("ALL", "ALL"),
    ],
)
def test_resolve_statement_type_keywords(keyword, expected):
    assert resolve_statement_type(keyword) == expected


def test_resolve_statement_type_code_passthrough():
    assert resolve_statement_type("BS") == "BS"
    assert resolve_statement_type("cis") == "CIS"  # 소문자 코드도 대문자로


def test_resolve_statement_type_whitespace():
    assert resolve_statement_type(" 재무상태표 ") == "BS"


def test_resolve_statement_type_no_substring_collision():
    # '손익계산서'가 '포괄손익계산서'의 부분문자열이지만 정확 매칭이어야 한다
    assert resolve_statement_type("포괄손익계산서") == "CIS"
    assert resolve_statement_type("손익계산서") == "IS"


def test_resolve_statement_type_unknown_raises():
    with pytest.raises(ValueError):
        resolve_statement_type("현금흐름")  # 오타/미지원
    with pytest.raises(ValueError):
        resolve_statement_type("")


# ─── resolve_period ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("1분기", "11013"),
        ("반기", "11012"),
        ("2분기", "11012"),
        ("상반기", "11012"),
        ("3분기", "11014"),
        ("사업보고서", "11011"),
        ("연간", "11011"),
        ("연도", "11011"),
        ("4분기", "11011"),
        ("전체", "11011"),
    ],
)
def test_resolve_period_keywords(keyword, expected):
    assert resolve_period(keyword) == expected


def test_resolve_period_code_passthrough():
    assert resolve_period("11011") == "11011"
    assert resolve_period("11013") == "11013"


def test_resolve_period_whitespace():
    assert resolve_period(" 1분기 ") == "11013"


def test_resolve_period_unknown_raises():
    with pytest.raises(ValueError):
        resolve_period("13분기")
    with pytest.raises(ValueError):
        resolve_period("")
