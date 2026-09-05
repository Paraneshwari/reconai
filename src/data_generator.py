"""
ReconAI - Synthetic Data Generator
Generates orders, payments and settlements with realistic reconciliation
problems baked in, plus a HIDDEN ground_truth_status used only for scoring.
Deterministic (seeded) so demo runs are repeatable.
"""

import random
from datetime import datetime, timedelta

SEED = 42
N_RECORDS = 100

CUSTOMERS = [f"CUST{100+i}" for i in range(40)]
METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]

# Target distribution of ground-truth exception types (approx, from spec)
# 75% clean matches, 10% amount mismatch, 5% missing settlement,
# 5% duplicate, 5% reference mismatch / unresolved mix


def _base_date(i):
    return datetime(2026, 8, 1) + timedelta(hours=i * 3, minutes=random.randint(0, 59))


def generate_dataset(n=N_RECORDS, seed=SEED):
    random.seed(seed)

    orders, payments, settlements = [], [], []

    # Decide category for each record up-front so distribution is controlled
    categories = (
        ["MATCHED"] * int(n * 0.55)
        + ["MATCHED_AFTER_FEE"] * int(n * 0.20)
        + ["AMOUNT_MISMATCH"] * int(n * 0.10)
        + ["MISSING_SETTLEMENT"] * int(n * 0.05)
        + ["DUPLICATE"] * int(n * 0.05)
        + ["REFERENCE_MISMATCH"] * int(n * 0.03)
    )
    while len(categories) < n:
        categories.append("UNRESOLVED")
    random.shuffle(categories)
    categories = categories[:n]

    dup_extra_rows = []

    for i, category in enumerate(categories):
        idx = 1000 + i
        order_id = f"ORD{idx}"
        payment_id = f"PAY{idx}"
        settlement_id = f"SET{idx}"
        customer_id = random.choice(CUSTOMERS)
        order_amount = round(random.uniform(199, 9999), 2)
        order_date = _base_date(i)
        payment_date = order_date + timedelta(minutes=random.randint(1, 15))
        fee = round(order_amount * random.uniform(0.015, 0.025), 2)

        orders.append({
            "order_id": order_id,
            "customer_id": customer_id,
            "order_date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            "order_amount": order_amount,
            "currency": "INR",
            "payment_id": payment_id,
        })

        payments.append({
            "payment_id": payment_id,
            "order_id": order_id,
            "transaction_reference": f"TXN{idx}",
            "payment_date": payment_date.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_amount": order_amount,
            "payment_status": "SUCCESS",
            "payment_method": random.choice(METHODS),
        })

        settlement_date = payment_date + timedelta(days=random.choice([1, 1, 2, 3]))

        if category == "MATCHED":
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": order_amount,
                "settlement_status": "SETTLED",
                "fee_amount": 0.0,
                "bank_reference": f"TXN{idx}",
                "ground_truth_status": "MATCHED",
            })

        elif category == "MATCHED_AFTER_FEE":
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount - fee, 2),
                "settlement_status": "SETTLED",
                "fee_amount": fee,
                "bank_reference": f"TXN{idx}",
                "ground_truth_status": "MATCHED",
            })

        elif category == "AMOUNT_MISMATCH":
            # Fee explains part of the gap, but a real discrepancy remains
            unexplained = round(random.uniform(50, 400), 2)
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount - fee - unexplained, 2),
                "settlement_status": "SETTLED",
                "fee_amount": fee,
                "bank_reference": f"TXN{idx}",
                "ground_truth_status": "AMOUNT_MISMATCH",
            })

        elif category == "MISSING_SETTLEMENT":
            # No settlement row at all for a successful payment
            pass  # ground truth implied by absence; tracked below

        elif category == "DUPLICATE":
            # Two settlement rows referencing the same payment
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount - fee, 2),
                "settlement_status": "SETTLED",
                "fee_amount": fee,
                "bank_reference": f"TXN{idx}",
                "ground_truth_status": "DUPLICATE",
            })
            dup_extra_rows.append({
                "settlement_id": f"SET{idx}B",
                "payment_id": payment_id,
                "settlement_date": (settlement_date + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount - fee, 2),
                "settlement_status": "SETTLED",
                "fee_amount": fee,
                "bank_reference": f"TXN{idx}",
                "ground_truth_status": "DUPLICATE",
            })

        elif category == "REFERENCE_MISMATCH":
            # Small amount wobble (still within LIKELY_MATCH tolerance) so this
            # doesn't get silently absorbed by the exact RULE_1 amount check -
            # it needs the AI/agent layer to reason about the reference gap.
            wobble = round(random.uniform(1.5, 4.5), 2)
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount - fee - wobble, 2),
                "settlement_status": "SETTLED",
                "fee_amount": fee,
                "bank_reference": f"BANKREF{idx}9",  # doesn't match TXN reference
                "ground_truth_status": "REFERENCE_MISMATCH",
            })

        elif category == "UNRESOLVED":
            # Ambiguous: partial data, no clean explanation available
            settlements.append({
                "settlement_id": settlement_id,
                "payment_id": payment_id,
                "settlement_date": settlement_date.strftime("%Y-%m-%d %H:%M:%S"),
                "settlement_amount": round(order_amount * random.uniform(0.4, 0.6), 2),
                "settlement_status": "PARTIAL",
                "fee_amount": 0.0,
                "bank_reference": f"UNK{idx}",
                "ground_truth_status": "UNRESOLVED",
            })

        # Track missing-settlement ground truth separately since no row exists
        if category == "MISSING_SETTLEMENT":
            settlements.append({
                "settlement_id": None,
                "payment_id": payment_id,
                "settlement_date": None,
                "settlement_amount": None,
                "settlement_status": None,
                "fee_amount": None,
                "bank_reference": None,
                "ground_truth_status": "MISSING_SETTLEMENT",
                "_no_row": True,
            })

    settlements.extend(dup_extra_rows)

    return orders, payments, settlements


def save_csvs(out_dir="data", n=N_RECORDS, seed=SEED):
    import csv
    import os

    orders, payments, settlements = generate_dataset(n, seed)
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "orders.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(orders[0].keys()))
        w.writeheader()
        w.writerows(orders)

    with open(os.path.join(out_dir, "payments.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(payments[0].keys()))
        w.writeheader()
        w.writerows(payments)

    # settlements: only real rows (with settlement_id) go to CSV;
    # the "no row" missing-settlement ground truth is kept in-memory
    # by the app (it derives MISSING_SETTLEMENT from absence + ground_truth map)
    real_settlements = [s for s in settlements if not s.get("_no_row")]
    fieldnames = ["settlement_id", "payment_id", "settlement_date",
                  "settlement_amount", "settlement_status", "fee_amount",
                  "bank_reference", "ground_truth_status"]
    with open(os.path.join(out_dir, "settlements.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in real_settlements:
            w.writerow({k: row.get(k) for k in fieldnames})

    # Ground truth map (payment_id -> true status), including missing-settlement
    # rows that never made it into settlements.csv. This file is for internal
    # scoring only - never shown in the UI.
    gt_map = {}
    for s in settlements:
        gt_map.setdefault(s["payment_id"], s["ground_truth_status"])
    with open(os.path.join(out_dir, "ground_truth.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "ground_truth_status"])
        for pid, status in gt_map.items():
            w.writerow([pid, status])

    return orders, payments, settlements


if __name__ == "__main__":
    orders, payments, settlements = save_csvs()
    print(f"Generated {len(orders)} orders, {len(payments)} payments, "
          f"{len([s for s in settlements if not s.get('_no_row')])} settlement rows.")
