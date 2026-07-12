from validate import check_balance_sheet


def test_balanced_bs_has_no_warning():
    items = {
        "ifrs-full_Assets": {"label": "자산총계", "value": 1000.0, "statement_type": "재무상태표"},
        "ifrs-full_Liabilities": {"label": "부채총계", "value": 400.0, "statement_type": "재무상태표"},
        "ifrs-full_Equity": {"label": "자본총계", "value": 600.0, "statement_type": "재무상태표"},
    }
    assert check_balance_sheet(items) == []


def test_unbalanced_bs_returns_warning():
    items = {
        "ifrs-full_Assets": {"label": "자산총계", "value": 1000.0, "statement_type": "재무상태표"},
        "ifrs-full_Liabilities": {"label": "부채총계", "value": 400.0, "statement_type": "재무상태표"},
        "ifrs-full_Equity": {"label": "자본총계", "value": 500.0, "statement_type": "재무상태표"},
    }
    warnings = check_balance_sheet(items)
    assert len(warnings) == 1
    assert "대차평형" in warnings[0]


def test_missing_accounts_skips_silently():
    assert check_balance_sheet({}) == []
    partial = {
        "ifrs-full_Assets": {"label": "자산총계", "value": 1000.0, "statement_type": "재무상태표"},
    }
    assert check_balance_sheet(partial) == []


def test_none_value_skips_silently():
    items = {
        "ifrs-full_Assets": {"label": "자산총계", "value": None, "statement_type": "재무상태표"},
        "ifrs-full_Liabilities": {"label": "부채총계", "value": 400.0, "statement_type": "재무상태표"},
        "ifrs-full_Equity": {"label": "자본총계", "value": 600.0, "statement_type": "재무상태표"},
    }
    assert check_balance_sheet(items) == []


def test_small_rounding_diff_within_tolerance():
    items = {
        "ifrs-full_Assets": {"label": "자산총계", "value": 1000000.0, "statement_type": "재무상태표"},
        "ifrs-full_Liabilities": {"label": "부채총계", "value": 400000.0, "statement_type": "재무상태표"},
        "ifrs-full_Equity": {"label": "자본총계", "value": 599999.6, "statement_type": "재무상태표"},
    }
    assert check_balance_sheet(items) == []
