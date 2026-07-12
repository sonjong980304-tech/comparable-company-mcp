# DART Financials MCP Server

> 회사명(또는 종목코드)과 기간·재무제표 종류를 물어보면 **DART OpenAPI를 직접 호출해
> 재무제표를 마크다운 표로 바로 반환**하는 **MCP(Model Context Protocol) 서버**

Claude Desktop / Claude Code에서 자연어로 "삼성전자 2023년 1분기 재무상태표 보여줘"처럼 물어보면,
DART 전자공시 원본 수치를 표로 정리해 원문 링크와 함께 돌려줍니다.

---

## 주요 기능

| 툴 | 설명 |
|----|------|
| `find_company` | 회사명 또는 종목코드 6자리 → DART `corp_code` 식별 |
| `get_financial_statement` | 재무제표를 조회해 **마크다운 표**로 반환 (DART 원문 링크 동봉) |

- **연결(CFS) 우선, 없으면 개별(OFS) 자동 폴백** — 어느 쪽을 썼는지 `fs_div_used`로 명시
- **표준계정(account_id) 기반 파싱** — 계정과목명이 회사·연도별로 달라도 방어
- **TTL 캐시(24시간)** — 같은 요청 반복 시 DART 재호출 없이 캐시 사용
- **일일 한도 초과(status 020) 처리** — 캐시가 있으면 캐시로 응답, 없으면 명확히 안내(크래시 없음)
- **출처 동봉** — 표 하단에 `rcept_no` 기반 DART 원문 링크를 붙여 사용자가 직접 검증 가능
- **대차평형 정합성 검증** — 자산총계 = 부채총계 + 자본총계 여부를 자동 확인, 불일치 시 `warnings`에 경고

---

## 설치

### 사전 요건
- Python 3.11+
- DART OpenAPI 키 ([opendart.fss.or.kr](https://opendart.fss.or.kr) 가입 후 발급)

### 패키지 설치
```bash
git clone https://github.com/sonjong980304/comparable-company-mcp.git
cd comparable-company-mcp

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 환경변수 설정
```bash
cp .env.example .env
# .env 열어서 DART_API_KEY 입력
```
`.env` 예시:
```
DART_API_KEY=발급받은_DART_키
```

---

## Claude Desktop / Claude Code 등록

`~/Library/Application Support/Claude/claude_desktop_config.json`(macOS) 또는
`~/.claude/settings.json`(Claude Code)에 추가:

```json
{
  "mcpServers": {
    "dart-financials": {
      "command": "/절대경로/.venv/bin/python3",
      "args": ["/절대경로/server.py"],
      "env": {
        "DART_API_KEY": "발급받은_DART_키"
      }
    }
  }
}
```
> venv python 절대경로는 `source .venv/bin/activate && which python3`, 프로젝트 경로는 `pwd`로 확인하세요.
> 설정 후 Claude Desktop을 **완전 종료(Cmd+Q) 후 재시작**하면 적용됩니다.

---

## 사용 예시

Claude에게 자연어로 입력합니다:
```
삼성전자 2023년 1분기 재무상태표 보여줘
```
```
get_financial_statement 툴로 005930의 2022년 손익계산서를 알려줘
```

### 파라미터

`get_financial_statement(company, year, period, statement_type, fs_div_preference)`

| 파라미터 | 값 | 기본값 |
|----------|-----|--------|
| `company` | 회사명 / 종목코드 6자리 / corp_code 8자리 | (필수) |
| `year` | 사업연도 (예: 2023) | (필수) |
| `period` | `1분기` · `반기`(=2분기·상반기) · `3분기` · `사업보고서`(=연간·4분기·전체) | `사업보고서` |
| `statement_type` | `재무상태표` · `손익계산서` · `포괄손익계산서` · `현금흐름표` · `자본변동표` · `전체` | `전체` |
| `fs_div_preference` | `CFS`(연결) · `OFS`(개별) | `CFS` |

### 예시 응답 (`table` 필드)

```markdown
## 삼성전자 2022년 사업보고서 재무상태표

| 계정과목 | 금액 |
|---|---:|
| 자산총계 | 455조 9060억원 |
| 부채총계 | 93조 6749억원 |
| 자본총계 | 362조 2311억원 |

> 출처: [DART 원문 보기(rcept_no=20230315000123)](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230315000123)
```

`get_financial_statement`는 위 `table` 외에도 `corp_code`, `corp_name`, `fs_div_used`,
`currency`, `rcept_no`, `source_url`, `cached`, `status`, `warnings`, `error_message`를 함께 반환합니다.

---

## 아키텍처

```
comparable-company-mcp/
├── server.py            # MCP 서버 엔트리포인트 (FastMCP, 2개 툴 배선)
├── dart_financials.py   # fnlttSinglAcntAll 호출 + TTL 캐시 + 020 처리 + 파싱
├── cache_manager.py     # corpCode.xml 다운로드 + parquet 캐시, corp_code 조회
├── params.py            # 한국어 키워드 → DART 파라미터(sj_div, reprt_code) 매핑
├── table_renderer.py    # 파싱 결과 → 마크다운 표 렌더링
├── unit_format.py       # 원 단위 금액 → "조/억원" 사람이 읽는 문자열
├── validate.py          # 대차평형(자산=부채+자본) 등 기초 정합성 검증
├── models.py            # Pydantic 스키마 (CompanyLookupResult, FinancialStatementResult)
├── cache/               # corp_codes.parquet + financials/*.json (재무제표 응답 캐시)
├── tests/               # pytest 단위테스트 (네트워크는 mock)
├── .env.example
├── requirements.txt
└── README.md
```

### 캐싱 전략

| 데이터 | 파일 | 갱신 주기 |
|--------|------|-----------|
| DART corpCode.xml | `cache/corp_codes.parquet` | 최초 1회 (없을 때만 다운로드) |
| 재무제표 응답(JSON) | `cache/financials/{corp}_{year}_{reprt}_{fs}.json` | TTL 24시간 (초과 시 재호출) |

---

## 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `DART_API_KEY` | O | DART OpenAPI 인증키 ([발급](https://opendart.fss.or.kr)) |

> DART 키는 요청 URL에 실리므로 httpx 요청 로그를 WARNING으로 억제해 키 노출을 막습니다.
> 키는 절대 코드/로그/커밋에 하드코딩하지 말고 `.env`로만 로드하세요.

---

## 테스트

```bash
pytest            # 순수 로직(포맷·파라미터·표·캐시/020/파싱) 단위테스트, 네트워크는 mock
```

- 라이브 DART API 호출 테스트는 두지 않습니다(일일 한도 소모 방지). 네트워크 계층(`_fetch_fnltt`)은
  테스트에서 mock 처리합니다.

---

## 주의사항

- **최초 실행 시** DART `corpCode.xml` 다운로드가 1회 발생합니다. 이후에는 parquet 캐시를 재사용합니다.
- **연결/개별**: 기본은 연결(CFS)이며, 연결이 없으면 개별(OFS)로 자동 폴백하고 `fs_div_used`에 명시합니다.
- **DART 전체 재무제표(fnlttSinglAcntAll)는 2015 사업연도부터** 제공됩니다.
- **일일 한도 초과(020)** 시 유효한 캐시가 있으면 캐시로 응답하고, 없으면 `status="quota_exceeded"`로 안내합니다.
- **대차평형 자동 검증**: 재무상태표에 자산총계·부채총계·자본총계가 모두 있으면 `자산총계 = 부채총계 + 자본총계`를 확인하고, 불일치 시 `warnings`에 표시합니다(계정이 일부 없으면 단정하지 않고 검증을 건너뜁니다).
