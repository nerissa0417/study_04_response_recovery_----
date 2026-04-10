from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.network_trend_plot import build_network_markers


def export_dashboard_data(
    result: SimulationResult,
    output_path: str | Path,
    *,
    artifact_paths: dict[str, str] | None = None,
    network_history: pd.DataFrame | None = None,
) -> Path:
    payload = build_dashboard_payload(
        result=result,
        artifact_paths=artifact_paths or {},
        network_history=network_history,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return destination


def build_dashboard_payload(
    *,
    result: SimulationResult,
    artifact_paths: dict[str, str],
    network_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    history = result.history.copy()
    history["date"] = pd.to_datetime(history["date"])
    network_frame = (
        network_history.copy()
        if network_history is not None
        else pd.DataFrame(columns=["date"])
    )
    if not network_frame.empty:
        network_frame["date"] = pd.to_datetime(network_frame["date"])
    kpis = {
        "scenario_id": result.scenario.scenario_id,
        "target_id": result.summary.get("target_id"),
        "ttr_days": result.summary.get("ttr_days"),
        "propagation_duration_months": result.summary.get("propagation_duration_months"),
        "propagation_stop_date": result.summary.get("propagation_stop_date"),
        "average_service_level": result.summary.get("average_service_level"),
        "avg_system_service_level": result.summary.get("avg_system_service_level"),
        "estimated_disruption_loss": result.summary.get("estimated_disruption_loss"),
        "policy_total_cost": result.summary.get("policy_total_cost"),
        "max_affected_key_items": result.summary.get("max_affected_key_items"),
        "max_failed_key_items": result.summary.get("max_failed_key_items"),
        "max_disrupted_key_suppliers": result.summary.get("max_disrupted_key_suppliers"),
    }
    peak_row = _select_peak_row(history)
    return {
        "scenario": {
            "scenario_id": result.scenario.scenario_id,
            "scenario_type": result.scenario.scenario_type,
            "target_type": result.scenario.target_type,
            "target_id": result.scenario.target_id,
            "start_date": str(result.scenario.start_date.date()),
            "duration_days": result.scenario.duration_days,
            "severity": result.scenario.severity,
        },
        "summary": result.summary,
        "kpis": kpis,
        "peak_snapshot": {
            "date": str(peak_row["date"].date()) if peak_row is not None else None,
            "service_level": float(peak_row["service_level"]) if peak_row is not None and "service_level" in peak_row else None,
            "fused_failed_items": int(peak_row["fused_failed_items"]) if peak_row is not None and "fused_failed_items" in peak_row else None,
            "total_backlog_demand": float(peak_row["total_backlog_demand"]) if peak_row is not None and "total_backlog_demand" in peak_row else None,
        },
        "time_series": _build_time_series(history),
        "network_time_series": _build_network_time_series(network_frame),
        "network_markers": build_network_markers(result, network_frame),
        "top_impacted_paths": result.impacted_paths[:12],
        "policy_events": result.policy_events,
        "artifact_paths": artifact_paths,
    }


def _build_time_series(history: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "date",
        "service_level",
        "demand_fulfillment_rate",
        "system_service_level",
        "supply_unavailable_items",
        "total_backlog_demand",
        "fused_failed_items",
        "affected_key_items",
        "failed_key_items",
        "disrupted_key_suppliers",
        "policy_cumulative_cost",
        "active_backup_switches",
        "active_priority_repairs",
    ]
    available = [column for column in columns if column in history.columns]
    records = history[available].copy().to_dict("records")
    for record in records:
        if "date" in record:
            record["date"] = str(pd.Timestamp(record["date"]).date())
    return records


def _select_peak_row(history: pd.DataFrame) -> pd.Series | None:
    if history.empty:
        return None
    sort_columns = [column for column in ["fused_failed_items", "total_backlog_demand", "service_level"] if column in history.columns]
    if not sort_columns:
        return history.iloc[0]
    ascending = [False, False, True][: len(sort_columns)]
    return history.sort_values(by=sort_columns, ascending=ascending).iloc[0]


def _build_network_time_series(network_history: pd.DataFrame) -> list[dict[str, Any]]:
    if network_history.empty:
        return []
    records = network_history.copy().to_dict("records")
    for record in records:
        if "date" in record:
            record["date"] = str(pd.Timestamp(record["date"]).date())
    return records
