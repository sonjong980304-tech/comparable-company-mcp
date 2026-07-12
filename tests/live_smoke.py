#!/usr/bin/env python3
"""수동 라이브 스모크 (pytest 대상 아님 — 실제 DART API를 1회 호출한다).

DART 일일 한도를 소모하므로 자동 테스트에는 포함하지 않는다.
실행:  DART_API_KEY=... python tests/live_smoke.py [회사명] [연도] [기간] [재무제표종류]
예:    python tests/live_smoke.py 삼성전자 2023 사업보고서 재무상태표
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server  # noqa: E402


async def main() -> None:
    company = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
    period = sys.argv[3] if len(sys.argv) > 3 else "사업보고서"
    stmt = sys.argv[4] if len(sys.argv) > 4 else "재무상태표"

    if not os.environ.get("DART_API_KEY"):
        print("DART_API_KEY 환경변수가 필요합니다.")
        return

    found = await server.find_company(company)
    print("find_company:", found)

    out = await server.get_financial_statement(company, year, period, stmt)
    print("status:", out["status"], "| fs_div_used:", out["fs_div_used"], "| cached:", out["cached"])
    if out["warnings"]:
        print("warnings:", out["warnings"])
    print("-" * 60)
    print(out["table"])


if __name__ == "__main__":
    asyncio.run(main())
