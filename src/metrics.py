"""
ReconAI - Metrics engine.
Computes throughput, match rate, resolution rate and accuracy against the
hidden synthetic ground truth (never shown directly in the UI).
"""

from dataclasses import dataclass
from typing import List, Dict


# Ground truth labels are fine-grained (MATCHED, AMOUNT_MISMATCH, ...).
# Agent classifications are finer still (e.g. AMOUNT_MISMATCH_EXPLAINED).
# This map decides what counts as a "correct decision" for accuracy scoring.
CORRECTNESS_MAP = {
    "MATCHED": {"MATCHED"},
    "AMOUNT_MISMATCH": {"AMOUNT_MISMATCH_EXPLAINED", "AMOUNT_MISMATCH_UNEXPLAINED"},
    "MISSING_SETTLEMENT": {"MISSING_SETTLEMENT"},
    "DUPLICATE": {"DUPLICATE"},
    "REFERENCE_MISMATCH": {"REFERENCE_MISMATCH", "LIKELY_MATCH"},
    "UNRESOLVED": {"UNRESOLVED"},
}


@dataclass
class Metrics:
    total_records: int
    auto_matched: int
    auto_resolved: int
    human_review: int
    unresolved: int
    match_rate: float
    resolution_rate: float
    accuracy: float
    false_positive_count: int
    false_negative_count: int
    processing_time_sec: float
    throughput_per_sec: float


def compute_metrics(match_results, agent_decisions, ground_truth: Dict[str, str],
                     processing_time_sec: float) -> Metrics:
    total = len(match_results)
    decisions_by_txn = {d.transaction_id: d for d in agent_decisions}

    auto_matched = sum(1 for m in match_results if m.status == "MATCHED")
    auto_resolved = sum(1 for d in agent_decisions if d.action == "AUTO_RESOLVE")
    human_review = sum(1 for d in agent_decisions if d.action == "HUMAN_REVIEW")
    unresolved_final = sum(
        1 for d in agent_decisions
        if d.action == "HUMAN_REVIEW" and d.classification == "UNRESOLVED"
    )

    correct = 0
    false_positive = 0  # auto-resolved but ground truth says it was a real problem
    false_negative = 0  # flagged for human review but ground truth was actually a clean match

    for m in match_results:
        truth = ground_truth.get(m.payment_id, "UNRESOLVED")
        if m.status == "MATCHED":
            predicted_ok = truth == "MATCHED"
            if predicted_ok:
                correct += 1
            else:
                false_negative += 1  # we said fine, but it wasn't -> under-caught
            continue

        decision = decisions_by_txn.get(m.payment_id)
        if decision is None:
            continue

        allowed_labels = CORRECTNESS_MAP.get(truth, set())
        is_correct = decision.classification in allowed_labels
        if is_correct:
            correct += 1
        else:
            if decision.action == "AUTO_RESOLVE":
                false_positive += 1
            else:
                false_negative += 1

    match_rate = round(auto_matched / total, 4) if total else 0.0
    resolved_total = auto_matched + auto_resolved
    resolution_rate = round(resolved_total / total, 4) if total else 0.0
    accuracy = round(correct / total, 4) if total else 0.0
    throughput = round(total / processing_time_sec, 2) if processing_time_sec > 0 else 0.0

    return Metrics(
        total_records=total,
        auto_matched=auto_matched,
        auto_resolved=auto_resolved,
        human_review=human_review,
        unresolved=unresolved_final,
        match_rate=match_rate,
        resolution_rate=resolution_rate,
        accuracy=accuracy,
        false_positive_count=false_positive,
        false_negative_count=false_negative,
        processing_time_sec=round(processing_time_sec, 4),
        throughput_per_sec=throughput,
    )
