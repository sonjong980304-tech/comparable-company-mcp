# Comparable Company MCP Server

> 비상장 평가대상 회사의 **대용기업(Comparable Company / Peer Group)** 후보를 자동 선정하고  
> 사업 내용 기반 유사성을 검증하는 **MCP(Model Context Protocol) 서버**

Claude Desktop / Claude Code에서 자연어로 호출하면 DART OpenAPI를 통해 업종 필터링 → 사업내용 추출 → 유사도 검증까지 전 과정을 자동으로 처리합니다.

---

## 주요 기능

| 툴 | 설명 |
|----|------|
| `find_comparable_companies` | **통합 파이프라인** (권장) — 회사명 하나로 전체 프로세스 실행 |
| `get_target_company_info` | DART에서 평가대상 기업 정보 + 사업내용 텍스트 조회 |
| `crawl_dart_candidates` | DART 기반 상장사 목록 조회 (일일 캐시, 업종 레벨별 필터) |
| `filter_candidates_tool` | 결산월·금융업·지주회사·관리종목 룰 필터 |
| `verify_business_similarity` | 사업내용 유사도 검증 (방식 A/B) |

### 비상장사 사업내용 자동 추출 전략

공시 유형을 순서대로 시도하여 사업내용 텍스트를 추출합니다:

```
사업보고서(A001) → 반기보고서(A002) → 분기보고서(A003)
→ 감사보고서(F001) → 연결감사보고서(F002)          ← 비상장사 fallback
→ 증권신고서(D001~D004) → 투자설명서(C001)
```

DART에 공시가 전혀 없거나 사업내용 추출이 실패하면  
`business_description` 파라미터로 사업 내용을 직접 입력하여 검증을 계속할 수 있습니다.

---

## 설치

### 사전 요건

- Python 3.11+
- DART OpenAPI 키 ([opendart.fss.or.kr](https://opendart.fss.or.kr) 가입 후 발급)
- (선택) Anthropic API 키 — 방식 B(내부 LLM 유사도 자동 판단) 사용 시

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
ANTHROPIC_API_KEY=선택사항_Anthropic_키
```

---

## Claude Desktop 등록 방법

### macOS

설정 파일 경로: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "comparable-company": {
      "command": "/Users/사용자명/comparable-company-mcp/.venv/bin/python3",
      "args": ["/Users/사용자명/comparable-company-mcp/server.py"],
      "env": {
        "DART_API_KEY": "발급받은_DART_키",
        "ANTHROPIC_API_KEY": "선택사항_Anthropic_키"
      }
    }
  }
}
```

> **경로 확인 방법**
> ```bash
> # venv python 절대경로
> source .venv/bin/activate
> which python3
>
> # 프로젝트 절대경로
> pwd
> ```

### Windows

설정 파일 경로: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "comparable-company": {
      "command": "C:\\Users\\사용자명\\comparable-company-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\사용자명\\comparable-company-mcp\\server.py"],
      "env": {
        "DART_API_KEY": "발급받은_DART_키"
      }
    }
  }
}
```

### Claude Code (CLI)

`~/.claude/settings.json` 또는 프로젝트의 `.claude/settings.json`에 추가:

```json
{
  "mcpServers": {
    "comparable-company": {
      "command": "/절대경로/.venv/bin/python3",
      "args": ["/절대경로/server.py"],
      "env": {
        "DART_API_KEY": "발급받은_DART_키"
      }
    }
  }
}
```

설정 후 Claude Desktop을 **완전 종료(Cmd+Q) 후 재시작**하면 적용됩니다.

---

## 사용 예시

### 기본 사용 (통합 파이프라인)

Claude에게 자연어로 입력합니다:

```
find_comparable_companies 툴을 사용해서 한미반도체의 대용기업을 찾아줘
```

```
구다이글로벌의 대용기업 찾아줘. find_comparable_companies 툴 써줘
```

### 비상장사라 DART 공시가 없는 경우

DART 자동 추출이 실패하면 사업 내용을 직접 제공합니다:

```
find_comparable_companies 툴로 구다이글로벌 대용기업을 찾아줘.
business_description에는 아래 내용을 넣어줘:

"구다이글로벌은 골프 의류 및 용품 전문 브랜드를 기획·개발하고 유통하는 기업입니다.
주요 브랜드로는 XXXX가 있으며, 국내 백화점·아울렛·온라인 채널을 통해 판매합니다.
B2C 위주의 패션 유통 사업 모델을 영위합니다."
```

### 단계별 수동 호출

세밀한 제어가 필요할 때:

```
# 1단계: 평가대상 정보 조회
get_target_company_info("ABC테크놀로지")
→ induty_code: "29271", induty_name: "반도체 조립 장비 제조업"

# 2단계: 동일 업종 상장사 목록
crawl_dart_candidates("29271", "반도체 조립 장비 제조업", industry_level="세분류")
→ KOSPI/KOSDAQ 후보 목록

# 3단계: 룰 기반 필터
filter_candidates_tool(candidates_json=..., require_december_fiscal=True)
→ 금융업·지주회사·관리종목 제거

# 4단계: 유사도 검증
verify_business_similarity(
    target_business_text="...",
    candidate_name="AA전자",
    candidate_stock_code="012345"
)
```

---

## 유사도 검증 방식

### 방식 A — 기본 (ANTHROPIC_API_KEY 없음)

후보 기업의 사업내용 텍스트를 추출하여 Claude(호스트)에 제공합니다.  
Claude가 두 텍스트를 직접 비교하여 유사도를 판단합니다.  
`is_comparable` / `similarity_score`는 null로 반환됩니다.

### 방식 B — 자동 판단 (ANTHROPIC_API_KEY 있음)

Claude API를 내부 호출하여 다음 항목을 자동 산출합니다:
- `is_comparable`: 대용기업 적합 여부 (true/false)
- `similarity_score`: 유사도 점수 (1~5)
- `rationale`: 판단 근거
- `key_overlaps`: 겹치는 사업 영역
- `key_differences`: 차이점

---

## 아키텍처

```
comparable-company-mcp/
├── server.py              # MCP 서버 엔트리포인트 (FastMCP, 5개 툴)
├── dart_client.py         # DART OpenAPI 래퍼 (corp_code 캐싱, 사업내용 추출)
├── dart_company_crawler.py # DART 기반 KOSPI/KOSDAQ 상장사 목록 수집
├── cache_manager.py       # corpCode.xml 다운로드 + parquet 캐시 관리
├── filters.py             # 룰 기반 필터 (결산월·금융·지주·관리종목)
├── verifier.py            # 사업내용 유사도 검증 (방식 A/B)
├── pipeline.py            # 통합 파이프라인 + 업종 레벨 재시도
├── models.py              # Pydantic 스키마
├── cache/                 # corp_codes.parquet + dart_companies_YYYYMMDD.parquet
├── .env.example
├── requirements.txt
└── README.md
```

### 캐싱 전략

| 데이터 | 파일 | 갱신 주기 |
|--------|------|-----------|
| DART corpCode.xml | `cache/corp_codes.parquet` | 최초 1회 (수동 갱신 가능) |
| DART 상장사 목록 | `cache/dart_companies_YYYYMMDD.parquet` | 날짜 무관 최신 캐시 재사용 |

---

## 환경변수

| 변수 | 필수 | 설명 |
|------|------|------|
| `DART_API_KEY` | ✅ | DART OpenAPI 인증키 ([발급](https://opendart.fss.or.kr)) |
| `ANTHROPIC_API_KEY` | 선택 | Claude API 키 — 방식 B 자동 유사도 판단 시 필요 |

---

## 주의사항

- **최초 실행 시** DART corpCode.xml 다운로드 및 KOSPI/KOSDAQ 상장사 정보 수집(약 3~5분) 이 1회 발생합니다. 이후에는 캐시를 재사용합니다.
- **비상장사**는 DART 사업보고서가 없을 수 있습니다. 이 경우 감사보고서(F001/F002)로 자동 fallback하며, 그래도 실패하면 `business_description`으로 수동 입력하세요.
- **후보 수가 적을 때** 업종 레벨을 자동으로 상향(세분류→중분류→대분류)하여 재시도합니다.
- **방식 A**는 추가 API 비용 없이 호스트 Claude가 직접 판단합니다.
