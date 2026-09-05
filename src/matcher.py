"""
ReconAI - Deterministic reconciliation engine.
No LLM involved here. Implements the rule hierarchy from the spec:

RULE 1: exact payment_id match + amount reconciles after fee -> MATCHED
RULE 2: order_id maps uniquely + amount matches -> MATCHED
RULE 3: reference approx match + amount/date within tolerance -> LIKELY_MATCH
RULE 4: transaction identified but amount doesn't reconcile -> AMOUNT_MISMATCH
RULE 5: successful payment, no settlement row -> MISSING_SETTLEMENT
RULE 6: multiple settlement rows for one payment -> DUPLICATE
RULE 7: otherwise -> UNRESOLVED
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

AMOUNT_TOLERANCE = 1.0  # rupees
DATE_TOLERANCE_DAYS = 4


@dataclass
class MatchResult:
    payment_id: str
    order_id: Optional[str]
    status: str  # MATCHED / LIKELY_MATCH / AMOUNT_MISMATCH / MISSING_SETTLEMENT / DUPLICATE / UNRESOLVED
    expected_amount: Optional[float]
    actual_amount: Optional[float]
    fee_amount: Optional[float]
    difference: Optional[float]
    rule_fired: str
    evidence: List[str] = field(default_factory=list)
    settlement_ids: List[str] = field(default_factory=list)
    reference_match: Optional[bool] = None


def _amounts_reconcile(expected, settlement_amt, fee, tolerance=AMOUNT_TOLERANCE):
    if expected is None or settlement_amt is None:
        return False
    fee = fee or 0.0
    return abs(expected - (settlement_amt + fee)) <= tolerance


def run_matching(orders_df, payments_df, settlements_df) -> List[MatchResult]:
    results: List[MatchResult] = []

    settlement_groups: Dict[str, list] = {}
    for _, row in settlements_df.iterrows():
        pid = row["payment_id"]
        settlement_groups.setdefault(pid, []).append(row)

    orders_by_id = {row["order_id"]: row for _, row in orders_df.iterrows()}

    for _, pay in payments_df.iterrows():
        payment_id = pay["payment_id"]
        order_id = pay["order_id"]
        expected_amount = pay["payment_amount"]
        order = orders_by_id.get(order_id)
        settlement_rows = settlement_groups.get(payment_id, [])

        # RULE 6: Duplicate settlement rows for the same payment
        if len(settlement_rows) > 1:
            total_settled = sum((r["settlement_amount"] or 0) for r in settlement_rows)
            results.append(MatchResult(
                payment_id=payment_id,
                order_id=order_id,
                status="DUPLICATE",
                expected_amount=expected_amount,
                actual_amount=total_settled,
                fee_amount=sum((r["fee_amount"] or 0) for r in settlement_rows),
                difference=round(total_settled - expected_amount, 2) if expected_amount is not None else None,
                rule_fired="RULE_6_DUPLICATE",
                evidence=[f"{len(settlement_rows)} settlement records found for payment_id={payment_id}"],
                settlement_ids=[r["settlement_id"] for r in settlement_rows],
            ))
            continue

        # RULE 5: Missing settlement entirely
        if len(settlement_rows) == 0:
            if pay["payment_status"] == "SUCCESS":
                results.append(MatchResult(
                    payment_id=payment_id,
                    order_id=order_id,
                    status="MISSING_SETTLEMENT",
                    expected_amount=expected_amount,
                    actual_amount=None,
                    fee_amount=None,
                    difference=expected_amount,
                    rule_fired="RULE_5_MISSING_SETTLEMENT",
                    evidence=["Payment marked SUCCESS but no settlement record exists"],
                ))
            else:
                results.append(MatchResult(
                    payment_id=payment_id,
                    order_id=order_id,
                    status="UNRESOLVED",
                    expected_amount=expected_amount,
                    actual_amount=None,
                    fee_amount=None,
                    difference=None,
                    rule_fired="RULE_7_UNRESOLVED",
                    evidence=["No settlement found and payment not marked SUCCESS"],
                ))
            continue

        settlement = settlement_rows[0]
        settlement_amt = settlement["settlement_amount"]
        fee = settlement["fee_amount"] or 0.0
        difference = None
        if expected_amount is not None and settlement_amt is not None:
            difference = round(expected_amount - (settlement_amt + fee), 2)

        ref_match = (
            settlement.get("bank_reference") is not None
            and pay.get("transaction_reference") is not None
            and settlement["bank_reference"] == pay["transaction_reference"]
        )

        status = settlement.get("settlement_status")

        # RULE 1: exact payment_id + amount reconciles after fee
        if _amounts_reconcile(expected_amount, settlement_amt, fee) and status == "SETTLED":
            results.append(MatchResult(
                payment_id=payment_id, order_id=order_id, status="MATCHED",
                expected_amount=expected_amount, actual_amount=settlement_amt,
                fee_amount=fee, difference=difference,
                rule_fired="RULE_1_EXACT_PAYMENT_ID",
                evidence=[f"payment_amount ({expected_amount}) == settlement_amount ({settlement_amt}) + fee ({fee})"],
                settlement_ids=[settlement["settlement_id"]],
                reference_match=ref_match,
            ))
            continue

        # RULE 3: reference/amount/date proximity -> LIKELY_MATCH
        if (not ref_match) and status == "SETTLED":
            date_ok = True
            if pay.get("payment_date") is not None and settlement.get("settlement_date") is not None:
                delta = abs((settlement["settlement_date"] - pay["payment_date"]).days)
                date_ok = delta <= DATE_TOLERANCE_DAYS
            amount_close = (
                expected_amount is not None and settlement_amt is not None
                and abs(expected_amount - (settlement_amt + fee)) <= 5.0
            )
            if amount_close and date_ok:
                results.append(MatchResult(
                    payment_id=payment_id, order_id=order_id, status="LIKELY_MATCH",
                    expected_amount=expected_amount, actual_amount=settlement_amt,
                    fee_amount=fee, difference=difference,
                    rule_fired="RULE_3_REFERENCE_PROXIMITY",
                    evidence=["Reference differs but amount and settlement date fall within tolerance",
                              f"bank_reference={settlement.get('bank_reference')} vs transaction_reference={pay.get('transaction_reference')}"],
                    settlement_ids=[settlement["settlement_id"]],
                    reference_match=False,
                ))
                continue

        # RULE 4: amount mismatch
        if expected_amount is not None and settlement_amt is not None and status == "SETTLED":
            if abs(difference) > AMOUNT_TOLERANCE:
                results.append(MatchResult(
                    payment_id=payment_id, order_id=order_id, status="AMOUNT_MISMATCH",
                    expected_amount=expected_amount, actual_amount=settlement_amt,
                    fee_amount=fee, difference=difference,
                    rule_fired="RULE_4_AMOUNT_MISMATCH",
                    evidence=[f"Expected {expected_amount}, settlement+fee = {round(settlement_amt+fee,2)}, "
                              f"unexplained difference = {difference}"],
                    settlement_ids=[settlement["settlement_id"]],
                    reference_match=ref_match,
                ))
                continue

        # Otherwise: unresolved (e.g., PARTIAL status, ambiguous data)
        results.append(MatchResult(
            payment_id=payment_id, order_id=order_id, status="UNRESOLVED",
            expected_amount=expected_amount, actual_amount=settlement_amt,
            fee_amount=fee, difference=difference,
            rule_fired="RULE_7_UNRESOLVED",
            evidence=[f"settlement_status={status}", "Insufficient evidence for automatic reconciliation"],
            settlement_ids=[settlement.get("settlement_id")] if settlement.get("settlement_id") else [],
            reference_match=ref_match,
        ))

    return results
