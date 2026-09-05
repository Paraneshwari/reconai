"""
ReconAI - Normalization layer.
Cleans and standardizes IDs, dates, amounts and references across sources.
"""

import pandas as pd


def _norm_id(x):
    if pd.isna(x) or x is None:
        return None
    return str(x).strip().upper()


def _norm_amount(x):
    if x is None or x == "" or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return round(float(x), 2)
    except (ValueError, TypeError):
        return None


def _norm_date(x):
    if x is None or x == "" or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return pd.to_datetime(x)
    except Exception:
        return None


def normalize_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["order_id"] = df["order_id"].apply(_norm_id)
    df["payment_id"] = df["payment_id"].apply(_norm_id)
    df["customer_id"] = df["customer_id"].apply(_norm_id)
    df["order_amount"] = df["order_amount"].apply(_norm_amount)
    df["order_date"] = df["order_date"].apply(_norm_date)
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    return df


def normalize_payments(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["payment_id"] = df["payment_id"].apply(_norm_id)
    df["order_id"] = df["order_id"].apply(_norm_id)
    df["transaction_reference"] = df["transaction_reference"].apply(_norm_id)
    df["payment_amount"] = df["payment_amount"].apply(_norm_amount)
    df["payment_date"] = df["payment_date"].apply(_norm_date)
    df["payment_status"] = df["payment_status"].astype(str).str.strip().str.upper()
    df["payment_method"] = df["payment_method"].astype(str).str.strip().str.upper()
    return df


def normalize_settlements(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["settlement_id"] = df["settlement_id"].apply(_norm_id)
    df["payment_id"] = df["payment_id"].apply(_norm_id)
    df["settlement_amount"] = df["settlement_amount"].apply(_norm_amount)
    df["fee_amount"] = df["fee_amount"].apply(_norm_amount)
    df["settlement_date"] = df["settlement_date"].apply(_norm_date)
    df["bank_reference"] = df["bank_reference"].apply(_norm_id)
    if "settlement_status" in df.columns:
        df["settlement_status"] = df["settlement_status"].astype(str).str.strip().str.upper()
    return df
