"""사업 내용 유사성 검증: 방식 A(텍스트 반환) + 방식 B(Claude API 내부 호출)."""
from __future__ import annotations

import json
import logging
from typing import Optional

from dart_client import find_corp_code_by_stock, get_business_text
from models import VerificationResult

logger = logging.getLogger(__name__)

# ─── 방식 B 시스템 프롬프트 ─────────────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 기업가치평가(Valuation) 전문가다. 비상장 평가대상 회사의 대용기업
(Comparable Company)을 선정하기 위해, 두 회사의 공시 사업 내용을 비교하여
대용기업으로서 적합한지 판단한다.

아래 제공되는 텍스트는 정기보고서/증권신고서에서 추출한 사업 관련 섹션으로,
개요·제품·매출 등 여러 내용이 섞여 있을 수 있다. 그중 핵심 사업이 무엇인지 스스로
식별한 뒤 비교하라. 특정 소제목에 얽매이지 말고 사업의 실질을 파악할 것.

[판단 기준]
1. 주력 제품/서비스의 유사성
2. 속한 산업 및 가치사슬상 위치
3. 주요 고객군 및 전방시장
4. 사업 모델(B2B/B2C, 제조/서비스 등) 일치도
5. 매출 구성의 유사성

[출력 형식 - JSON만, 다른 텍스트 없이]
{{
  "is_comparable": true/false,
  "similarity_score": 1~5,
  "rationale": "선정/제외 근거를 구체적·상세하게. 어떤 사업 영역이 겹치고 \
어떤 부분이 다른지 명시. '같은 업종'이 아니라 사업 실질로 판단",
  "key_overlaps": ["겹치는 사업 영역 1", "영역 2"],
  "key_differences": ["차이점 1", "차이점 2"]
}}

반드시 사업의 실질(substance over form)을 기준으로 판단하라.\
"""


# ─── 내부 헬퍼 ──────────────────────────────────────────────────────────────

async def _get_candidate_biz_info(
    candidate_name: str,
    candidate_corp_code: str,
    candidate_stock_code: str,
    api_key: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """후보 기업의 (corp_code, business_text, source) 반환."""
    corp_code = candidate_corp_code or None
    if not corp_code and candidate_stock_code:
        corp_code = await find_corp_code_by_stock(candidate_stock_code, api_key)
    if not corp_code:
        logger.warning("corp_code 없음: %s / stock=%s", candidate_name, candidate_stock_code)
        return None, None, None

    biz_text, source = await get_business_text(corp_code, api_key)
    return corp_code, biz_text, source


# ─── 방식 A: 텍스트 반환 (호스트 Claude 판단) ─────────────────────────────

async def prepare_verification_data(
    target_business_text: str,
    candidate_name: str,
    candidate_corp_code: str,
    candidate_stock_code: str,
    api_key: str,
) -> VerificationResult:
    """
    후보 기업의 사업 내용 텍스트를 추출하여 반환.
    유사도 판단은 MCP 호스트(Claude)에 위임하므로 is_comparable/score는 None.
    """
    corp_code, biz_text, source = await _get_candidate_biz_info(
        candidate_name, candidate_corp_code, candidate_stock_code, api_key
    )
    if not biz_text:
        return VerificationResult(
            candidate_name=candidate_name,
            stock_code=candidate_stock_code or None,
            corp_code=corp_code,
            status="사업내용 확인불가",
            error_message="DART에서 사업 내용을 추출할 수 없습니다.",
        )
    return VerificationResult(
        candidate_name=candidate_name,
        stock_code=candidate_stock_code or None,
        corp_code=corp_code,
        target_business_text=target_business_text,
        candidate_business_text=biz_text,
        source_report=source,
        status="ok",
    )


# ─── 방식 B: Claude API 내부 호출 ─────────────────────────────────────────

async def verify_with_claude_api(
    target_business_text: str,
    candidate_name: str,
    candidate_corp_code: str,
    candidate_stock_code: str,
    api_key: str,
    anthropic_api_key: str,
) -> VerificationResult:
    """
    후보 사업 내용 추출 후 Claude API를 내부 호출하여 유사도 점수까지 산출.
    ANTHROPIC_API_KEY가 없으면 prepare_verification_data로 fallback.
    """
    import anthropic  # 지연 임포트 — 설치 여부 확인

    corp_code, biz_text, source = await _get_candidate_biz_info(
        candidate_name, candidate_corp_code, candidate_stock_code, api_key
    )
    if not biz_text:
        return VerificationResult(
            candidate_name=candidate_name,
            corp_code=corp_code,
            status="사업내용 확인불가",
            error_message="DART에서 사업 내용을 추출할 수 없습니다.",
        )

    user_content = (
        f"[평가대상 회사 사업 내용]\n{target_business_text[:6000]}\n\n"
        f"[후보 회사: {candidate_name} 사업 내용]\n{biz_text[:6000]}"
    )

    client = anthropic.Anthropic(api_key=anthropic_api_key)
    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        # 코드블록 제거 후 JSON 파싱
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        return VerificationResult(
            candidate_name=candidate_name,
            stock_code=candidate_stock_code or None,
            corp_code=corp_code,
            is_comparable=parsed.get("is_comparable"),
            similarity_score=parsed.get("similarity_score"),
            rationale=parsed.get("rationale"),
            key_overlaps=parsed.get("key_overlaps", []),
            key_differences=parsed.get("key_differences", []),
            target_business_text=target_business_text,
            candidate_business_text=biz_text,
            source_report=source,
            status="ok",
        )
    except Exception as exc:
        logger.error("Claude API 호출 실패(%s): %s", candidate_name, exc)
        return VerificationResult(
            candidate_name=candidate_name,
            stock_code=candidate_stock_code or None,
            corp_code=corp_code,
            target_business_text=target_business_text,
            candidate_business_text=biz_text,
            source_report=source,
            status="API 오류",
            error_message=str(exc),
        )


# ─── 통합 진입점 ─────────────────────────────────────────────────────────────

async def verify_candidate(
    target_business_text: str,
    candidate_name: str,
    candidate_corp_code: str,
    candidate_stock_code: str,
    dart_api_key: str,
    anthropic_api_key: Optional[str] = None,
) -> VerificationResult:
    """
    ANTHROPIC_API_KEY 존재 여부에 따라 방식 A/B 자동 선택.
    """
    if anthropic_api_key:
        return await verify_with_claude_api(
            target_business_text,
            candidate_name,
            candidate_corp_code,
            candidate_stock_code,
            dart_api_key,
            anthropic_api_key,
        )
    return await prepare_verification_data(
        target_business_text,
        candidate_name,
        candidate_corp_code,
        candidate_stock_code,
        dart_api_key,
    )
