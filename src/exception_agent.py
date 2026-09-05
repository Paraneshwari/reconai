"""
ReconAI - Exception Resolution Agent.

Pipeline:
    Deterministic exception -> AI reasoning (LLM or fallback template)
    -> structured recommendation -> POLICY GATE -> AUTO_RESOLVE or HUMAN_REVIEW

IMPORTANT SAFETY DESIGN:
The LLM (or fallback engine) never directly changes a financial record.
It only produces a structured recommendation. A separate deterministic
policy layer (`apply_policy`) decides whether that recommendation is
allowed to auto-resolve. This keeps the AI advisory-only.
"""

import os
import json
from dataclasses import dataclass, asdict
from typing import List, Optional

# Exception types that are ever eligible for AUTO_RESOLVE, regardless of
# how confident the agent is. Everything else always goes to human review.
AUTO_RESOLVE_ALLOWLIST = {"AMOUNT_MISMATCH_EXPLAINED", "LIKELY_MATCH", "REFERENCE_MISMATCH"}
CONFIDENCE_THRESHOLD = 0.90


@dataclass
class AgentDecision:
    transaction_id: str
    classification: str
    explanation: str
    confidence: float
    action: str  # AUTO_RESOLVE or HUMAN_REVIEW (post-policy)
    recommended_action: str  # what the AI itself suggested, pre-policy
    evidence: List[str]
    ai_mode: str  # "LLM" or "FALLBACK"


def _fallback_reason(match_result) -> (str, float, str):
    """Deterministic template engine used when no LLM API key is configured."""
    status = match_result.status
    diff = match_result.difference
    fee = match_result.fee_amount or 0.0

    if status == "LIKELY_MATCH":
        return (
            "Reference numbers differ across systems, but the settlement amount "
            "and date fall within normal tolerance of the expected payment, "
            "consistent with a same transaction recorded with a different reference format.",
            0.93,
            "LIKELY_MATCH",
        )

    if status == "AMOUNT_MISMATCH":
        explained = fee
        unexplained = abs(diff) if diff is not None else None
        if unexplained is not None and unexplained <= 5:
            return (
                f"Settlement differs from expected amount by a negligible ₹{unexplained}, "
                f"fully within the recorded fee (₹{explained}). No further action needed.",
                0.97,
                "AMOUNT_MISMATCH_EXPLAINED",
            )
        return (
            f"Settlement differs from expected amount. The recorded fee (₹{explained}) "
            f"explains part of the gap, but ₹{unexplained} remains unexplained. "
            "No supporting adjustment record was found.",
            0.94,
            "AMOUNT_MISMATCH_UNEXPLAINED",
        )

    if status == "MISSING_SETTLEMENT":
        return (
            "No settlement record was found for this successful payment. "
            "This could indicate a delayed settlement or a data sync gap; "
            "it cannot be confirmed without an external bank statement.",
            0.60,
            "MISSING_SETTLEMENT",
        )

    if status == "DUPLICATE":
        return (
            "Multiple settlement records reference the same payment. This may be a "
            "genuine double-settlement or a duplicate data entry. Requires reversal "
            "verification before any adjustment is made.",
            0.55,
            "DUPLICATE",
        )

    if status == "REFERENCE_MISMATCH":
        return (
            "Payment and settlement bank references do not match, but the amount, "
            "fee and settlement date are otherwise consistent, offering partial "
            "supporting evidence for the same transaction.",
            0.80,
            "REFERENCE_MISMATCH",
        )

    return (
        "Available records do not provide sufficient evidence for automatic "
        "reconciliation of this transaction.",
        0.40,
        "UNRESOLVED",
    )


def _llm_reason(match_result, api_key) -> Optional[tuple]:
    """Attempt to use an OpenAI-compatible LLM for richer reasoning.
    Returns None on any failure so the caller can fall back gracefully.
    """
    try:
        import urllib.request

        prompt = f"""You are a finance reconciliation exception analyst. Analyze this
transaction discrepancy and respond ONLY with JSON, no prose, no markdown fences:
{{"explanation": "...", "confidence": 0.0-1.0, "classification": "one of MATCHED, AMOUNT_MISMATCH_EXPLAINED, AMOUNT_MISMATCH_UNEXPLAINED, LIKELY_MATCH, MISSING_SETTLEMENT, DUPLICATE, REFERENCE_MISMATCH, UNRESOLVED"}}

Transaction: {match_result.payment_id}
Status: {match_result.status}
Expected amount: {match_result.expected_amount}
Actual settlement amount: {match_result.actual_amount}
Fee amount: {match_result.fee_amount}
Unexplained difference: {match_result.difference}
Evidence: {match_result.evidence}
"""
        body = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        return (parsed["explanation"], float(parsed["confidence"]), parsed["classification"])
    except Exception:
        return None


def apply_policy(classification: str, confidence: float) -> str:
    """Deterministic policy gate. The AI can only recommend; this decides."""
    if classification in AUTO_RESOLVE_ALLOWLIST and confidence >= CONFIDENCE_THRESHOLD:
        return "AUTO_RESOLVE"
    return "HUMAN_REVIEW"


def resolve_exception(match_result) -> AgentDecision:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    ai_mode = "FALLBACK"
    reasoning = None

    if api_key:
        reasoning = _llm_reason(match_result, api_key)
        if reasoning is not None:
            ai_mode = "LLM"

    if reasoning is None:
        reasoning = _fallback_reason(match_result)

    explanation, confidence, classification = reasoning
    action = apply_policy(classification, confidence)

    return AgentDecision(
        transaction_id=match_result.payment_id,
        classification=classification,
        explanation=explanation,
        confidence=round(confidence, 2),
        action=action,
        recommended_action=action,
        evidence=match_result.evidence,
        ai_mode=ai_mode,
    )


def resolve_all(match_results) -> List[AgentDecision]:
    """Run the agent over every non-MATCHED result (MATCHED needs no reasoning)."""
    decisions = []
    for m in match_results:
        if m.status == "MATCHED":
            continue
        decisions.append(resolve_exception(m))
    return decisions
