from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from supply_disruption_sim.labels import policy_type_label, scenario_label, scenario_type_label
from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.bom_plot import select_impacted_paths
from supply_disruption_sim.viz.network_trend_plot import build_network_markers


def export_dashboard_tables(
    result: SimulationResult,
    output_dir: str | Path,
    *,
    artifact_paths: dict[str, str] | None = None,
    network_history: pd.DataFrame | None = None,
    extra_frames: dict[str, pd.DataFrame] | None = None,
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
    if extra_frames:
        frames.update(extra_frames)

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
        "scenario_name": scenario_label(result.scenario.scenario_id),
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
            "scenario_name": scenario_label(result.scenario.scenario_id),
            "scenario_type": result.scenario.scenario_type,
            "scenario_type_name": scenario_type_label(result.scenario.scenario_type),
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
        "policy_events": _build_policy_events(result.policy_events),
        "artifact_paths": artifact_paths,
    }


def _build_time_series(history: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "date",
        "service_level",
        "total_requested_demand",
        "total_fulfilled_demand",
        "demand_fulfillment_rate",
        "system_service_level",
        "supply_degraded_items",
        "supply_unavailable_items",
        "supply_effective_degraded_items",
        "supply_effective_unavailable_items",
        "total_backlog_demand",
        "total_lost_demand",
        "fused_failed_items",
        "affected_key_items",
        "failed_key_items",
        "disrupted_key_suppliers",
        "policy_cumulative_cost",
        "active_backup_switches",
        "active_substitutions",
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
    rows: list[dict[str, str]] = []
    for name, path in artifact_paths.items():
        if isinstance(path, (list, tuple, set)):
            for index, item in enumerate(path):
                rows.append(
                    {
                        "artifact_name": f"{str(name)}_{index}",
                        "artifact_path": str(item),
                    }
                )
            continue
        rows.append({"artifact_name": str(name), "artifact_path": str(path)})
    return pd.DataFrame(rows)


def _build_policy_events(policy_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in policy_events:
        record = dict(event)
        if "policy_type" in record:
            record["policy_type_name"] = policy_type_label(str(record["policy_type"]))
        records.append(record)
    return records


def _dataset_description(dataset_name: str) -> str:
    descriptions = {
        "scenario": "当前运行情境的基础信息与中文情境名称。",
        "summary": "当前运行的完整单行汇总结果，用于页面概览与分析复核。",
        "kpis": "首页概览所需的核心指标卡片数据。",
        "policy_start_snapshot": "恢复策略启动当天的关键指标快照。",
        "time_series": "业务层、供给层、需求层与恢复动作的日度时间序列。",
        "network_time_series": "网络节点与边状态的日度统计序列。",
        "network_markers": "统一时间标记点，包括基线、首次冲击、供应峰值、策略启动和业务恢复。",
        "top_impacted_paths": "用于路径图和表格展示的关键受影响物料清单路径。",
        "policy_events": "恢复策略事件时间线及中文策略名称。",
        "artifact_paths": "前端展示所需图像与衍生文件的实际输出路径。",
        "network_snapshots": "网络快照清单，逐张列出快照标识、标题、日期与图片路径。",
        "policy_comparison_summary": "不同恢复策略组合的汇总对比表。",
        "policy_comparison_time_series": "不同恢复策略组合下中断节点数的日级对比时间序列。",
        "parameter_experiment_summary": "参数扰动分析结果表，按能力维度和参数取值汇总恢复表现。",
        "parameter_sensitivity_ranking": "不同能力参数对恢复效果的综合敏感度排序结果。",
    }
    return descriptions.get(dataset_name, "")
