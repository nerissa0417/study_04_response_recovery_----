from __future__ import annotations

import pandas as pd


def history_column(frame: pd.DataFrame, preferred: str, fallback: str) -> pd.Series:
    if preferred in frame:
        return pd.to_numeric(frame[preferred], errors="coerce").fillna(0)
    return pd.to_numeric(frame.get(fallback, 0), errors="coerce").fillna(0)


def select_policy_start_row(history: pd.DataFrame) -> pd.Series | None:
    if history.empty:
        return None

    peak_history = history.copy()
    peak_history["date"] = pd.to_datetime(peak_history["date"])
    strategy_candidates = peak_history.loc[_strategy_execution_mask(peak_history)]
    if not strategy_candidates.empty:
        return strategy_candidates.sort_values(by=["date"], ascending=[True]).iloc[0]
    return None


def select_supply_peak_row(history: pd.DataFrame) -> pd.Series | None:
    if history.empty:
        return None

    peak_history = history.copy()
    peak_history["date"] = pd.to_datetime(peak_history["date"])
    peak_history["_supplier_disrupted"] = pd.to_numeric(
        peak_history.get("disrupted_suppliers", 0), errors="coerce"
    ).fillna(0)
    peak_history["_supplier_degraded"] = pd.to_numeric(
        peak_history.get("degraded_suppliers", 0), errors="coerce"
    ).fillna(0)
    peak_history["_supply_unavailable"] = pd.to_numeric(
        peak_history.get("supply_unavailable_items", 0), errors="coerce"
    ).fillna(0)
    peak_history["_supply_degraded"] = pd.to_numeric(
        peak_history.get("supply_degraded_items", 0), errors="coerce"
    ).fillna(0)
    peak_history["_raw_supply_impact"] = (
        peak_history["_supplier_disrupted"]
        + peak_history["_supplier_degraded"]
        + peak_history["_supply_unavailable"]
        + peak_history["_supply_degraded"]
    )
    return peak_history.sort_values(
        by=[
            "_raw_supply_impact",
            "_supply_unavailable",
            "_supply_degraded",
            "_supplier_disrupted",
            "_supplier_degraded",
            "date",
        ],
        ascending=[False, False, False, False, False, True],
    ).iloc[0]


def select_marker_dates(
    history: pd.DataFrame,
    scenario_start_date: pd.Timestamp,
    *,
    initial_date: pd.Timestamp | None = None,
) -> dict[str, str]:
    if history.empty:
        return {}

    frame = history.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["date_str"] = frame["date"].dt.date.astype(str)
    start_date = pd.Timestamp(scenario_start_date).normalize()
    after_start = frame.loc[frame["date"] >= start_date].copy()

    t0 = str((pd.Timestamp(initial_date).normalize() if initial_date is not None else frame.iloc[0]["date"]).date())
    shock_candidates = after_start.loc[_visible_shock_mask(after_start)]
    if not shock_candidates.empty:
        t_start = shock_candidates.iloc[0]["date_str"]
    else:
        t_start = str(start_date.date())
    supply_peak_row = select_supply_peak_row(frame)
    policy_start_row = select_policy_start_row(after_start)
    if policy_start_row is None:
        return {
            "t0": t0,
            "t_start": t_start,
            "t_supply_peak": (supply_peak_row["date_str"] if supply_peak_row is not None else t0),
            "t_policy_start": (supply_peak_row["date_str"] if supply_peak_row is not None else t0),
            "t_recovery": t0,
        }

    t_supply_peak = (
        supply_peak_row["date_str"]
        if supply_peak_row is not None
        else t_start
    )
    t_policy_start = policy_start_row["date_str"]
    policy_start_date = pd.Timestamp(policy_start_row["date"]).normalize()
    history_after_peak = frame.loc[frame["date"] >= policy_start_date].copy()
    recovery_candidates = history_after_peak.loc[_business_recovery_mask(history_after_peak)]

    t_recovery = (
        recovery_candidates.iloc[0]["date_str"]
        if not recovery_candidates.empty
        else frame.iloc[-1]["date_str"]
    )
    return {
        "t0": t0,
        "t_start": t_start,
        "t_supply_peak": t_supply_peak,
        "t_policy_start": t_policy_start,
        "t_recovery": t_recovery,
    }


def _visible_shock_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    return (
        (pd.to_numeric(frame.get("disrupted_suppliers", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("degraded_suppliers", 0), errors="coerce").fillna(0) > 0)
        | (history_column(frame, "supply_degraded_items", "supply_degraded_items") > 0)
        | (history_column(frame, "supply_unavailable_items", "supply_unavailable_items") > 0)
        | (pd.to_numeric(frame.get("fused_affected_items", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("fused_failed_items", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("supply_affected_products", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("system_service_level", 1.0), errors="coerce").fillna(1.0) < 0.999)
        | (pd.to_numeric(frame.get("demand_fulfillment_rate", 1.0), errors="coerce").fillna(1.0) < 0.999)
    )


def _strategy_execution_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    return (
        (pd.to_numeric(frame.get("active_backup_switches", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("active_substitutions", 0), errors="coerce").fillna(0) > 0)
        | (pd.to_numeric(frame.get("active_priority_repairs", 0), errors="coerce").fillna(0) > 0)
    )


def _business_recovery_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    final_product_active = (
        frame.get("final_product_status", pd.Series(["active"] * len(frame), index=frame.index))
        .astype(str)
        .eq("active")
    )
    return (
        final_product_active
        & (pd.to_numeric(frame.get("system_service_level", 0.0), errors="coerce").fillna(0.0) >= 0.999)
        & (pd.to_numeric(frame.get("demand_fulfillment_rate", 0.0), errors="coerce").fillna(0.0) >= 0.999)
        & (pd.to_numeric(frame.get("total_backlog_demand", 0.0), errors="coerce").fillna(0.0) <= 0.0)
        & (pd.to_numeric(frame.get("total_lost_demand", 0.0), errors="coerce").fillna(0.0) <= 0.0)
    )
