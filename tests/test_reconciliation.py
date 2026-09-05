import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from normalizer import normalize_orders, normalize_payments, normalize_settlements
from matcher import run_matching
from exception_agent import resolve_all, apply_policy
from metrics import compute_metrics
from data_generator import generate_dataset, save_csvs


def _mk_dfs(orders, payments, settlements):
    o = normalize_orders(pd.DataFrame(orders))
    p = normalize_payments(pd.DataFrame(payments))
    s = normalize_settlements(pd.DataFrame(settlements))
    return o, p, s


def test_exact_match():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    settlements = [{"settlement_id": "SET1", "payment_id": "PAY1", "settlement_date": "2026-08-02",
                     "settlement_amount": 1000, "settlement_status": "SETTLED",
                     "fee_amount": 0, "bank_reference": "TXN1"}]
    o, p, s = _mk_dfs(orders, payments, settlements)
    results = run_matching(o, p, s)
    assert results[0].status == "MATCHED"
    assert results[0].rule_fired == "RULE_1_EXACT_PAYMENT_ID"


def test_fee_adjusted_match():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    settlements = [{"settlement_id": "SET1", "payment_id": "PAY1", "settlement_date": "2026-08-02",
                     "settlement_amount": 980, "settlement_status": "SETTLED",
                     "fee_amount": 20, "bank_reference": "TXN1"}]
    o, p, s = _mk_dfs(orders, payments, settlements)
    results = run_matching(o, p, s)
    assert results[0].status == "MATCHED"


def test_amount_mismatch():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    settlements = [{"settlement_id": "SET1", "payment_id": "PAY1", "settlement_date": "2026-08-02",
                     "settlement_amount": 800, "settlement_status": "SETTLED",
                     "fee_amount": 20, "bank_reference": "TXN1"}]
    o, p, s = _mk_dfs(orders, payments, settlements)
    results = run_matching(o, p, s)
    assert results[0].status == "AMOUNT_MISMATCH"
    assert abs(results[0].difference - 180) < 0.01


def test_missing_settlement():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    o = normalize_orders(pd.DataFrame(orders))
    p = normalize_payments(pd.DataFrame(payments))
    # Empty settlements dataframe needs correct columns for normalize
    s = normalize_settlements(pd.DataFrame(columns=[
        "settlement_id", "payment_id", "settlement_date",
        "settlement_amount", "settlement_status", "fee_amount", "bank_reference"]))
    results = run_matching(o, p, s)
    assert results[0].status == "MISSING_SETTLEMENT"


def test_duplicate_detection():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    settlements = [
        {"settlement_id": "SET1", "payment_id": "PAY1", "settlement_date": "2026-08-02",
         "settlement_amount": 1000, "settlement_status": "SETTLED", "fee_amount": 0,
         "bank_reference": "TXN1"},
        {"settlement_id": "SET1B", "payment_id": "PAY1", "settlement_date": "2026-08-03",
         "settlement_amount": 1000, "settlement_status": "SETTLED", "fee_amount": 0,
         "bank_reference": "TXN1"},
    ]
    o, p, s = _mk_dfs(orders, payments, settlements)
    results = run_matching(o, p, s)
    assert results[0].status == "DUPLICATE"


def test_unresolved_partial_status():
    orders = [{"order_id": "ORD1", "customer_id": "C1", "order_date": "2026-08-01",
               "order_amount": 1000, "currency": "INR", "payment_id": "PAY1"}]
    payments = [{"payment_id": "PAY1", "order_id": "ORD1", "transaction_reference": "TXN1",
                 "payment_date": "2026-08-01", "payment_amount": 1000,
                 "payment_status": "SUCCESS", "payment_method": "UPI"}]
    settlements = [{"settlement_id": "SET1", "payment_id": "PAY1", "settlement_date": "2026-08-02",
                     "settlement_amount": 500, "settlement_status": "PARTIAL",
                     "fee_amount": 0, "bank_reference": "UNKNOWN"}]
    o, p, s = _mk_dfs(orders, payments, settlements)
    results = run_matching(o, p, s)
    assert results[0].status == "UNRESOLVED"


def test_policy_gate_blocks_low_confidence():
    assert apply_policy("MISSING_SETTLEMENT", 0.60) == "HUMAN_REVIEW"
    assert apply_policy("AMOUNT_MISMATCH_EXPLAINED", 0.97) == "AUTO_RESOLVE"
    assert apply_policy("AMOUNT_MISMATCH_EXPLAINED", 0.50) == "HUMAN_REVIEW"
    assert apply_policy("DUPLICATE", 0.99) == "HUMAN_REVIEW"  # never in allowlist


def test_full_batch_generates_50plus_records_and_metrics():
    orders, payments, settlements = generate_dataset(n=60, seed=42)
    assert len(orders) >= 50
    o = normalize_orders(pd.DataFrame(orders))
    p = normalize_payments(pd.DataFrame(payments))
    real_settlements = [x for x in settlements if not x.get("_no_row")]
    s = normalize_settlements(pd.DataFrame(real_settlements))
    results = run_matching(o, p, s)
    decisions = resolve_all(results)

    gt = {}
    for row in settlements:
        gt.setdefault(row["payment_id"], row["ground_truth_status"])

    metrics = compute_metrics(results, decisions, gt, processing_time_sec=0.5)
    assert metrics.total_records == 60
    assert 0.0 <= metrics.match_rate <= 1.0
    assert 0.0 <= metrics.accuracy <= 1.0
    assert metrics.throughput_per_sec > 0


def test_save_csvs_creates_expected_files(tmp_path):
    out_dir = str(tmp_path)
    orders, payments, settlements = save_csvs(out_dir, n=55, seed=1)
    for fname in ["orders.csv", "payments.csv", "settlements.csv", "ground_truth.csv"]:
        assert os.path.exists(os.path.join(out_dir, fname))
    assert len(orders) == 55
