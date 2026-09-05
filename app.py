"""
ReconAI — AI Finance Controller
Multi-Source Payment Reconciliation dashboard.

Run with:  streamlit run app.py
"""

import os
import sys
import time
import csv

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from data_generator import save_csvs, N_RECORDS, SEED  # noqa: E402
from normalizer import normalize_orders, normalize_payments, normalize_settlements  # noqa: E402
from matcher import run_matching  # noqa: E402
from exception_agent import resolve_all  # noqa: E402
from metrics import compute_metrics  # noqa: E402
from audit import build_audit_trail, to_dicts  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

st.set_page_config(page_title="ReconAI", page_icon="💠", layout="wide")

STATUS_COLORS = {
    "MATCHED": "#1a7f37",
    "LIKELY_MATCH": "#2f6feb",
    "AMOUNT_MISMATCH": "#b45309",
    "MISSING_SETTLEMENT": "#b91c1c",
    "DUPLICATE": "#7c3aed",
    "REFERENCE_MISMATCH": "#0e7490",
    "UNRESOLVED": "#6b7280",
}


def load_ground_truth():
    path = os.path.join(DATA_DIR, "ground_truth.csv")
    gt = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            gt[row["payment_id"]] = row["ground_truth_status"]
    return gt


def ensure_data(n_records, seed):
    save_csvs(DATA_DIR, n=n_records, seed=seed)


def run_pipeline(n_records, seed):
    start = time.time()
    ensure_data(n_records, seed)

    orders_df = pd.read_csv(os.path.join(DATA_DIR, "orders.csv"))
    payments_df = pd.read_csv(os.path.join(DATA_DIR, "payments.csv"))
    settlements_df = pd.read_csv(os.path.join(DATA_DIR, "settlements.csv"))

    orders_df = normalize_orders(orders_df)
    payments_df = normalize_payments(payments_df)
    settlements_df = normalize_settlements(settlements_df)

    match_results = run_matching(orders_df, payments_df, settlements_df)
    agent_decisions = resolve_all(match_results)
    audit_events = build_audit_trail(match_results, agent_decisions)

    ground_truth = load_ground_truth()
    elapsed = time.time() - start
    metrics = compute_metrics(match_results, agent_decisions, ground_truth, elapsed)

    return {
        "orders_df": orders_df,
        "payments_df": payments_df,
        "settlements_df": settlements_df,
        "match_results": match_results,
        "agent_decisions": agent_decisions,
        "audit_events": audit_events,
        "metrics": metrics,
        "elapsed": elapsed,
    }


def kpi_card(col, label, value, sub=None):
    with col:
        st.markdown(
            f"""
            <div style="background:#12151c;border:1px solid #262b36;border-radius:12px;
                        padding:18px 20px;">
                <div style="color:#9aa4b2;font-size:12px;letter-spacing:.06em;
                            text-transform:uppercase;">{label}</div>
                <div style="color:#f5f6f7;font-size:30px;font-weight:700;
                            margin-top:4px;">{value}</div>
                {f'<div style="color:#6b7280;font-size:12px;margin-top:2px;">{sub}</div>' if sub else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )


def status_badge(status):
    color = STATUS_COLORS.get(status, "#6b7280")
    return f'<span style="background:{color}22;color:{color};padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;">{status}</span>'


def main():
    st.markdown(
        """
        <div style="margin-bottom:4px;">
            <span style="font-size:34px;font-weight:800;">💠 ReconAI</span>
        </div>
        <div style="color:#9aa4b2;font-size:16px;margin-bottom:20px;">
            AI Finance Controller — Multi-Source Reconciliation
        </div>
        """,
        unsafe_allow_html=True,
    )

    ai_mode_enabled = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    mode_label = "🟢 AI MODE: Enabled (LLM)" if ai_mode_enabled else "🟡 AI MODE: Fallback (deterministic templates)"

    with st.sidebar:
        st.subheader("Run Configuration")
        n_records = st.slider("Batch size (synthetic records)", 50, 300, N_RECORDS, step=10)
        seed = st.number_input("Random seed (deterministic demo)", value=SEED, step=1)
        st.caption(mode_label)
        run_clicked = st.button("▶ Run Reconciliation", type="primary", use_container_width=True)
        st.divider()
        st.caption(
            "Data → Normalization → Deterministic Matcher → Exception Agent "
            "→ Policy Gate → Auto-Resolve / Human Review → Audit Trail"
        )

    if "results" not in st.session_state or run_clicked:
        with st.spinner("Processing batch..."):
            st.session_state.results = run_pipeline(n_records, seed)

    results = st.session_state.results
    metrics = results["metrics"]

    st.success(f"Processed {metrics.total_records} records in {metrics.processing_time_sec}s "
               f"({metrics.throughput_per_sec} records/sec).")

    c1, c2, c3, c4, c5 = st.columns(5)
    kpi_card(c1, "Records", metrics.total_records)
    kpi_card(c2, "Match Rate", f"{metrics.match_rate*100:.1f}%")
    kpi_card(c3, "Resolution Rate", f"{metrics.resolution_rate*100:.1f}%")
    kpi_card(c4, "Accuracy", f"{metrics.accuracy*100:.1f}%", "vs. hidden ground truth")
    kpi_card(c5, "Exceptions", metrics.total_records - metrics.auto_matched)

    st.write("")
    c6, c7, c8 = st.columns(3)
    kpi_card(c6, "Auto-Resolved Exceptions", metrics.auto_resolved)
    kpi_card(c7, "Sent to Human Review", metrics.human_review)
    kpi_card(c8, "False Positive / Negative", f"{metrics.false_positive_count} / {metrics.false_negative_count}")

    st.write("")
    st.subheader("Reconciliation Status Breakdown")

    status_counts = {}
    for m in results["match_results"]:
        status_counts[m.status] = status_counts.get(m.status, 0) + 1
    decisions_by_txn = {d.transaction_id: d for d in results["agent_decisions"]}
    final_counts = {}
    for m in results["match_results"]:
        if m.status == "MATCHED":
            final_counts["Matched"] = final_counts.get("Matched", 0) + 1
        else:
            d = decisions_by_txn.get(m.payment_id)
            label = "Auto Resolved" if (d and d.action == "AUTO_RESOLVE") else "Human Review"
            final_counts[label] = final_counts.get(label, 0) + 1

    chart_df = pd.DataFrame({"Status": list(final_counts.keys()), "Count": list(final_counts.values())})
    st.bar_chart(chart_df.set_index("Status"))

    st.write("")
    st.subheader("Exception Table")

    rows = []
    for m in results["match_results"]:
        if m.status == "MATCHED":
            continue
        d = decisions_by_txn.get(m.payment_id)
        rows.append({
            "Transaction": m.payment_id,
            "Type": m.status,
            "Expected (₹)": m.expected_amount,
            "Actual (₹)": m.actual_amount,
            "Difference (₹)": m.difference,
            "AI Decision": d.action if d else "-",
            "Confidence": f"{d.confidence*100:.0f}%" if d else "-",
            "Status": "Resolved" if (d and d.action == "AUTO_RESOLVE") else "Open",
        })
    exception_df = pd.DataFrame(rows)
    st.dataframe(exception_df, use_container_width=True, height=320)

    st.write("")
    st.subheader("Transaction Detail")

    txn_ids = [m.payment_id for m in results["match_results"]]
    selected = st.selectbox("Select a transaction to inspect", txn_ids)

    match = next(m for m in results["match_results"] if m.payment_id == selected)
    order = results["orders_df"][results["orders_df"]["payment_id"] == selected]
    payment = results["payments_df"][results["payments_df"]["payment_id"] == selected]
    decision = decisions_by_txn.get(selected)
    audit_for_txn = [e for e in results["audit_events"] if e.transaction_id == selected]

    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        st.markdown("**Order**")
        if not order.empty:
            o = order.iloc[0]
            st.write(f"Order ID: `{o['order_id']}`")
            st.write(f"Customer: `{o['customer_id']}`")
            st.write(f"Amount: ₹{o['order_amount']}")
            st.write(f"Date: {o['order_date']}")
    with dc2:
        st.markdown("**Payment**")
        if not payment.empty:
            p = payment.iloc[0]
            st.write(f"Payment ID: `{p['payment_id']}`")
            st.write(f"Amount: ₹{p['payment_amount']}")
            st.write(f"Status: {p['payment_status']}")
            st.write(f"Method: {p['payment_method']}")
    with dc3:
        st.markdown("**Settlement**")
        st.write(f"Settlement amount: ₹{match.actual_amount}")
        st.write(f"Fee: ₹{match.fee_amount}")
        st.write(f"Difference: ₹{match.difference}")
        st.markdown(status_badge(match.status), unsafe_allow_html=True)

    st.markdown("**AI Analysis**")
    if decision:
        st.write(f"Decision: **{decision.action}** (classification: `{decision.classification}`)")
        st.write(f"Confidence: {decision.confidence*100:.0f}%")
        st.write(f"Explanation: {decision.explanation}")
        st.write("Evidence:")
        for ev in decision.evidence:
            st.write(f"- {ev}")
    else:
        st.write("No exception — this transaction matched automatically with no AI reasoning required.")

    with st.expander("Audit Trail"):
        for e in audit_for_txn:
            st.json(to_dicts([e])[0])

    st.write("")
    st.caption(
        "Metrics are computed against a hidden synthetic ground truth over the "
        "full batch — no cherry-picked examples. False positives/negatives shown "
        "above reflect the entire run."
    )


if __name__ == "__main__":
    main()
