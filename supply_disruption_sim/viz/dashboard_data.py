from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.bom_plot import select_impacted_paths
from supply_disruption_sim.viz.network_trend_plot import build_network_markers


def export_dashboard_tables(
    result: SimulationResult,
    output_dir: str | Path,
    *,
    artifact_paths: dict[str, str] | None = None,
    network_history: pd.DataFrame | None = None,
) -> dict[str, Path]:
    payload = build_dashboard_payload(
        result=result,
        artifact_paths=artifact_paths or {},
        network_history=network_history,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    frames = {
        "scenario": pd.DataFrame([payload["scenario"]]),
        "summary": pd.DataFrame([payload["summary"]]),
        "kpis": pd.DataFrame([payload["kpis"]]),
        "policy_start_snapshot": pd.DataFrame([payload["policy_start_snapshot"]]),
        "time_series": pd.DataFrame(payload["time_series"]),
        "network_time_series": pd.DataFrame(payload["network_time_series"]),
        "network_markers": _build_network_markers_frame(payload["network_markers"]),
        "top_impacted_paths": pd.DataFrame(payload["top_impacted_paths"]),
        "policy_events": pd.DataFrame(payload["policy_events"]),
        "artifact_paths": _build_artifact_paths_frame(payload["artifact_paths"]),
    }

    paths: dict[str, Path] = {}
    manifest_rows: list[dict[str, Any]] = []
    for dataset_name, frame in frames.items():
        csv_path = destination / f"{dataset_name}.csv"
        frame.to_csv(csv_path, index=False)
        paths[dataset_name] = csv_path
        manifest_rows.append(
            {
                "dataset_name": dataset_name,
                "file_name": csv_path.name,
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "description": _dataset_description(dataset_name),
            }
        )

    manifest_path = destination / "manifest.csv"
    pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False)
    paths["manifest"] = manifest_path
    return paths


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
    network_markers = build_network_markers(result, network_frame)
    policy_start_row = None
    policy_start_date = network_markers.get("t_policy_start", {}).get("date")
    if policy_start_date is not None:
        policy_start_candidates = history.loc[history["date"].dt.date.astype(str) == str(policy_start_date)]
        if not policy_start_candidates.empty:
            policy_start_row = policy_start_candidates.iloc[0]
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
        "policy_start_snapshot": {
            "date": str(policy_start_row["date"].date()) if policy_start_row is not None else None,
            "service_level": float(policy_start_row["service_level"]) if policy_start_row is not None and "service_level" in policy_start_row else None,
            "supply_unavailable_items": (
                int(policy_start_row["supply_unavailable_items"])
                if policy_start_row is not None and "supply_unavailable_items" in policy_start_row
                else None
            ),
            "supply_degraded_items": (
                int(policy_start_row["supply_degraded_items"])
                if policy_start_row is not None and "supply_degraded_items" in policy_start_row
                else None
            ),
            "supply_effective_degraded_items": (
                int(policy_start_row["supply_effective_degraded_items"])
                if policy_start_row is not None and "supply_effective_degraded_items" in policy_start_row
                else None
            ),
            "supply_effective_unavailable_items": (
                int(policy_start_row["supply_effective_unavailable_items"])
                if policy_start_row is not None and "supply_effective_unavailable_items" in policy_start_row
                else None
            ),
            "fused_failed_items": int(policy_start_row["fused_failed_items"]) if policy_start_row is not None and "fused_failed_items" in policy_start_row else None,
            "total_backlog_demand": float(policy_start_row["total_backlog_demand"]) if policy_start_row is not None and "total_backlog_demand" in policy_start_row else None,
        },
        "time_series": _build_time_series(history),
        "network_time_series": _build_network_time_series(network_frame),
        "network_markers": network_markers,
        "top_impacted_paths": select_impacted_paths(result, limit=12),
        "policy_events": result.policy_events,
        "artifact_paths": artifact_paths,
    }


def _build_time_series(history: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "date",
        "service_level",
        "demand_fulfillment_rate",
        "system_service_level",
        "supply_degraded_items",
        "supply_unavailable_items",
        "supply_effective_degraded_items",
        "supply_effective_unavailable_items",
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


def _build_network_time_series(network_history: pd.DataFrame) -> list[dict[str, Any]]:
    if network_history.empty:
        return []
    records = network_history.copy().to_dict("records")
    for record in records:
        if "date" in record:
            record["date"] = str(pd.Timestamp(record["date"]).date())
    return records


def _build_network_markers_frame(network_markers: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for marker_name, payload in network_markers.items():
        if isinstance(payload, dict):
            row = {"marker_name": marker_name}
            row.update(payload)
            rows.append(row)
        else:
            rows.append({"marker_name": marker_name, "value": payload})
    return pd.DataFrame(rows)


def _build_artifact_paths_frame(artifact_paths: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {"artifact_name": str(name), "artifact_path": str(path)}
        for name, path in artifact_paths.items()
    ]
    return pd.DataFrame(rows)


def _dataset_description(dataset_name: str) -> str:
    descriptions = {
        "scenario": "Scenario metadata for the current run.",
        "summary": "Full one-row simulation summary for business review.",
        "kpis": "Headline KPI cards for the web overview section.",
        "policy_start_snapshot": "Strategy-start-day metrics shown in the disruption overview panel.",
        "time_series": "Daily business and supply KPI time series.",
        "network_time_series": "Daily network node and edge counts for charts.",
        "network_markers": "Shared marker dates for baseline, first visible shock, raw supply peak, policy start and business recovery.",
        "top_impacted_paths": "Top impacted BOM paths for path and table views.",
        "policy_events": "Recovery policy events for timeline and audit views.",
        "artifact_paths": "Resolved paths to figures and related generated assets.",
    }
    return descriptions.get(dataset_name, "")
