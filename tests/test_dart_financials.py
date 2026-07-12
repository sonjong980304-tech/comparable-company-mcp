"""dart_financials 단위테스트 — 네트워크는 mock, 캐시/020/파싱은 순수 로직."""
import json
import os
import time

import pytest

import dart_financials as df


# ─── is_quota_exceeded ───────────────────────────────────────────────────────

def test_is_quota_exceeded():
    assert df.is_quota_exceeded({"status": "020"}) is True
    assert df.is_quota_exceeded({"status": "000"}) is False  # 정상
    assert df.is_quota_exceeded({"status": "013"}) is False  # 데이터 없음
    assert df.is_quota_exceeded({}) is False


# ─── _is_cache_fresh ─────────────────────────────────────────────────────────

def test_is_cache_fresh_missing(tmp_path):
    assert df._is_cache_fresh(tmp_path / "nope.json", ttl_hours=24) is False


def test_is_cache_fresh_recent(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{}", encoding="utf-8")
    assert df._is_cache_fresh(p, ttl_hours=24) is True


def test_is_cache_fresh_expired(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{}", encoding="utf-8")
    old = time.time() - 48 * 3600  # 48시간 전
    os.utime(p, (old, old))
    assert df._is_cache_fresh(p, ttl_hours=24) is False


# ─── _parse_fnltt_items ──────────────────────────────────────────────────────

def test_parse_fnltt_items():
    items = [
        {"account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": "1,500,000,000,000", "sj_div": "BS", "currency": "KRW"},
        {"account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "3000000000000", "sj_div": "IS", "currency": "KRW"},
        {"account_id": "-표준계정코드 미사용-", "account_nm": "기타", "thstrm_amount": "100", "sj_div": "BS", "currency": "KRW"},
        {"account_id": "ifrs-full_BadAmt", "account_nm": "이상치", "thstrm_amount": "-", "sj_div": "BS", "currency": "KRW"},
    ]
    warnings: list[str] = []
    parsed, currency = df._parse_fnltt_items(items, 2023, "CFS", warnings)

    assert currency == "KRW"
    assert parsed["ifrs-full_Assets"]["value"] == 1_5000_0000_0000
    assert parsed["ifrs-full_Assets"]["statement_type"] == "재무상태표"
    assert parsed["ifrs-full_Revenue"]["statement_type"] == "손익계산서"
    # 표준계정코드 미사용 항목은 제외
    assert "-표준계정코드 미사용-" not in parsed
    # 파싱 불가 금액은 None + 항목은 유지
    assert parsed["ifrs-full_BadAmt"]["value"] is None
    assert any("파싱 불가" in w for w in warnings)


# ─── get_financial_statement (mock _fetch_fnltt) ─────────────────────────────

def _resp(status="000", sj_div="BS", account_id="ifrs-full_Assets", nm="자산총계", amount="1500000000000", rcept="20230315000001"):
    return {
        "status": status,
        "message": "정상" if status == "000" else "",
        "list": [
            {
                "rcept_no": rcept,
                "sj_div": sj_div,
                "account_id": account_id,
                "account_nm": nm,
                "thstrm_amount": amount,
                "currency": "KRW",
            }
        ] if status == "000" else [],
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # 캐시 디렉터리를 테스트 임시경로로 격리
    monkeypatch.setattr(df, "CACHE_DIR", tmp_path / "financials")
    monkeypatch.setenv("DART_API_KEY", "test-key")


def test_get_cfs_success_and_cache(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div, api_key):
        calls.append(fs_div)
        return _resp()

    monkeypatch.setattr(df, "_fetch_fnltt", fake_fetch)
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    assert out["status"] == "ok"
    assert out["fs_div_used"] == "CFS"
    assert out["cached"] is False
    assert out["parsed_items"]["ifrs-full_Assets"]["value"] == 1_5000_0000_0000
    assert out["rcept_no"] == "20230315000001"
    assert out["source_url"].endswith("rcpNo=20230315000001")
    assert calls == ["CFS"]

    # 두 번째 호출은 신선한 캐시 → fetch 호출 없음
    calls.clear()
    out2 = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")
    assert out2["cached"] is True
    assert calls == []


def test_get_cfs_empty_then_ofs_fallback(monkeypatch):
    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div, api_key):
        if fs_div == "CFS":
            return _resp(status="013")  # 연결 데이터 없음
        return _resp(status="000")

    monkeypatch.setattr(df, "_fetch_fnltt", fake_fetch)
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    assert out["status"] == "ok"
    assert out["fs_div_used"] == "OFS"
    assert any("폴백" in w for w in out["warnings"])


def test_get_quota_exceeded_no_cache(monkeypatch):
    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div, api_key):
        return {"status": "020", "message": "usage limit", "list": []}

    monkeypatch.setattr(df, "_fetch_fnltt", fake_fetch)
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    assert out["status"] == "quota_exceeded"
    assert out["parsed_items"] == {}
    assert out["error_message"]


def test_get_quota_exceeded_uses_stale_cache(monkeypatch):
    # 1) 먼저 성공 응답으로 캐시를 채운다
    monkeypatch.setattr(df, "_fetch_fnltt", lambda *a, **k: _resp())
    df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    # 2) 캐시를 만료시킨다
    cpath = df._cache_path("00126380", 2023, "11011", "CFS")
    old = time.time() - 48 * 3600
    os.utime(cpath, (old, old))

    # 3) 이제 API 는 020 → 만료 캐시라도 사용
    monkeypatch.setattr(df, "_fetch_fnltt", lambda *a, **k: {"status": "020", "list": []})
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    assert out["cached"] is True
    assert out["parsed_items"]["ifrs-full_Assets"]["value"] == 1_5000_0000_0000
    assert any("한도" in w for w in out["warnings"])


def test_get_no_api_key(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(df, "_fetch_fnltt", lambda *a, **k: _resp())
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")
    assert out["status"] == "error"
    assert "DART_API_KEY" in out["error_message"]


def test_get_unbalanced_bs_surfaces_warning(monkeypatch):
    def fake_fetch(corp_code, bsns_year, reprt_code, fs_div, api_key):
        return {
            "status": "000",
            "message": "정상",
            "list": [
                {"rcept_no": "1", "sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": "1000", "currency": "KRW"},
                {"rcept_no": "1", "sj_div": "BS", "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계", "thstrm_amount": "400", "currency": "KRW"},
                {"rcept_no": "1", "sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "thstrm_amount": "500", "currency": "KRW"},
            ],
        }

    monkeypatch.setattr(df, "_fetch_fnltt", fake_fetch)
    out = df.get_financial_statement("00126380", "삼성전자", 2023, "11011", "CFS")

    assert any("대차평형" in w for w in out["warnings"])
