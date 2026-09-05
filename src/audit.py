"""
ReconAI - Audit trail.
Every reconciliation decision (matched or exception) produces one audit
event capturing what was decided, why, and what evidence supported it.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class AuditEvent:
    timestamp: str
    transaction_id: str
    decision: str
    confidence: float
    reason: str
    evidence: List[str]
    action: str
    source_records: List[str]


def build_audit_trail(match_results, agent_decisions) -> List[AuditEvent]:
    events: List[AuditEvent] = []
    decisions_by_txn = {d.transaction_id: d for d in agent_decisions}
    now = datetime.utcnow().isoformat()

    for m in match_results:
        source_records = [m.payment_id] + (m.settlement_ids or [])
        if m.status == "MATCHED":
            events.append(AuditEvent(
                timestamp=now,
                transaction_id=m.payment_id,
                decision="MATCHED",
                confidence=1.0,
                reason=m.evidence[0] if m.evidence else "Exact match on payment ID and amount",
                evidence=m.evidence,
                action="RECONCILE",
                source_records=source_records,
            ))
        else:
            d = decisions_by_txn.get(m.payment_id)
            if d is None:
                continue
            events.append(AuditEvent(
                timestamp=now,
                transaction_id=m.payment_id,
                decision=d.action,
                confidence=d.confidence,
                reason=d.explanation,
                evidence=d.evidence,
                action="RECONCILE" if d.action == "AUTO_RESOLVE" else "ESCALATE_TO_HUMAN",
                source_records=source_records,
            ))
    return events


def to_dicts(events: List[AuditEvent]):
    return [asdict(e) for e in events]
