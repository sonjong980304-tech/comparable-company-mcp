"""table_renderer.render_statement_table 단위테스트."""
from table_renderer import render_statement_table


def _sample():
    return {
        "ifrs-full_Assets": {"label": "자산총계", "value": 1_5000_0000_0000, "statement_type": "재무상태표"},
        "ifrs-full_Liabilities": {"label": "부채총계", "value": 5_0000_0000_0000, "statement_type": "재무상태표"},
        "ifrs-full_Equity": {"label": "자본총계", "value": None, "statement_type": "재무상태표"},
        "ifrs-full_Revenue": {"label": "매출액", "value": 3_0000_0000_0000, "statement_type": "손익계산서"},
    }


def test_title_and_header():
    md = render_statement_table(_sample(), "BS", "삼성전자", 2023, "1분기보고서")
    assert md.startswith("## 삼성전자 2023년 1분기보고서 재무상태표")
    assert "| 계정과목 | 금액 |" in md
    assert "|---|---:|" in md


def test_filter_by_statement_type():
    md = render_statement_table(_sample(), "BS", "삼성전자", 2023, "사업보고서")
    # BS 항목만 포함, IS 항목(매출액)은 제외
    assert "자산총계" in md
    assert "매출액" not in md


def test_amount_formatting_and_none_row_kept():
    md = render_statement_table(_sample(), "BS", "삼성전자", 2023, "사업보고서")
    assert "1조 5000억원" in md  # 자산총계
    # value=None 인 자본총계도 행은 유지되고 금액칸은 "-"
    assert "| 자본총계 | - |" in md


def test_all_filter_includes_every_statement():
    md = render_statement_table(_sample(), "ALL", "삼성전자", 2023, "사업보고서")
    assert "자산총계" in md
    assert "매출액" in md


def test_empty_after_filter_message():
    # CF(현금흐름표) 항목이 하나도 없으면 안내 문구 반환
    md = render_statement_table(_sample(), "CF", "삼성전자", 2023, "사업보고서")
    assert md == "해당 재무제표 종류의 데이터가 없습니다."


def test_empty_parsed_items():
    md = render_statement_table({}, "ALL", "삼성전자", 2023, "사업보고서")
    assert md == "해당 재무제표 종류의 데이터가 없습니다."
