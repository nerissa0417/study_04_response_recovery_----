from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.plot_theme import (
    add_figure_header,
    add_scenario_marker,
    annotate_series_endpoint,
    annotate_series_endpoints,
    compute_time_focus_window,
    finish_figure,
    font_props,
    format_date_axis,
    integer_ticks,
    legend_style,
    qualitative_color_map,
    style_axes,
)


NETWORK_HISTORY_COLUMNS = [
    "date",
    "supplier_available_nodes",
    "supplier_degraded_nodes",
    "supplier_disrupted_nodes",
    "material_available_nodes",
    "material_affected_nodes",
    "material_blocked_nodes",
    "assembly_available_nodes",
    "assembly_affected_nodes",
    "assembly_blocked_nodes",
    "product_available_nodes",
    "product_affected_nodes",
    "product_blocked_nodes",
    "supplier_network_active_edges",
    "supplier_network_disrupted_edges",
    "supply_edge_active",
    "supply_edge_backup_active",
    "supply_edge_disrupted",
    "supply_edge_standby",
    "bom_edge_active",
    "bom_edge_disrupted",
    "alternative_edge_standby",
    "alternative_edge_substituted",
    "unknown_edge_count",
]

NETWORK_COMPARISON_COLUMNS = [
    "scenario_id",
    "policy_profile",
    "run_label",
    "day_offset",
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
    "supplier_degraded_nodes",
    "supplier_disrupted_nodes",
    "supply_edge_backup_active",
    "material_affected_nodes",
    "material_blocked_nodes",
    "assembly_affected_nodes",
    "assembly_blocked_nodes",
    "product_affected_nodes",
    "product_blocked_nodes",
    "bom_edge_disrupted",
    "alternative_edge_substituted",
]


def build_network_history(result: SimulationResult) -> pd.DataFrame:
    base_dates = pd.to_datetime(result.history.get("date", pd.Series(dtype="datetime64[ns]")))
    snapshot_map = {
        str(pd.Timestamp(snapshot["date"]).date()): snapshot
        for snapshot in result.network_snapshots
    }

    records: list[dict[str, Any]] = []
    for raw_date in base_dates:
        date_str = str(pd.Timestamp(raw_date).date())
        record = _empty_network_record(date_str)
        snapshot = snapshot_map.get(date_str)
        if snapshot is not None:
            record.update(_summarize_snapshot(snapshot))
        records.append(record)

    if not records and result.network_snapshots:
        for snapshot in result.network_snapshots:
            date_str = str(pd.Timestamp(snapshot["date"]).date())
            record = _empty_network_record(date_str)
            record.update(_summarize_snapshot(snapshot))
            records.append(record)

    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=NETWORK_HISTORY_COLUMNS)

    for column in NETWORK_HISTORY_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0
    frame = frame[NETWORK_HISTORY_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    numeric_columns = [column for column in frame.columns if column != "date"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    return frame


def build_network_markers(result: SimulationResult, network_history: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if network_history.empty:
        return {}
    history = result.history.copy()
    history["date"] = pd.to_datetime(history["date"])
    history["date_str"] = history["date"].dt.date.astype(str)
    network_indexed = network_history.copy()
    network_indexed["date"] = pd.to_datetime(network_indexed["date"])
    network_indexed["date_str"] = network_indexed["date"].dt.date.astype(str)
    network_by_date = network_indexed.set_index("date_str")

    t0 = history.iloc[0]["date_str"]
    t_start = str(result.scenario.start_date.normalize().date())
    peak_history = history.copy()
    peak_history["_system_loss"] = 1.0 - pd.to_numeric(
        peak_history.get("system_service_level", 1.0), errors="coerce"
    ).fillna(1.0)
    peak_history["_demand_loss"] = 1.0 - pd.to_numeric(
        peak_history.get("demand_fulfillment_rate", 1.0), errors="coerce"
    ).fillna(1.0)
    peak_history["_product_impact"] = (
        pd.to_numeric(peak_history.get("supply_affected_products", 0), errors="coerce").fillna(0)
        + pd.to_numeric(peak_history.get("supply_failed_products", 0), errors="coerce").fillna(0)
    )
    peak_history["_supply_impact"] = (
        pd.to_numeric(peak_history.get("supply_degraded_items", 0), errors="coerce").fillna(0)
        + pd.to_numeric(peak_history.get("supply_unavailable_items", 0), errors="coerce").fillna(0)
    )
    peak_row = peak_history.sort_values(
        by=[
            "_system_loss",
            "_demand_loss",
            "_product_impact",
            "_supply_impact",
            "fused_failed_items",
            "fused_affected_items",
            "date",
        ],
        ascending=[False, False, False, False, False, False, True],
    ).iloc[0]
    t_peak = peak_row["date_str"]
    peak_date = pd.Timestamp(peak_row["date"]).normalize()
    history_after_peak = history.loc[history["date"] >= peak_date].copy()
    if float(peak_row["_system_loss"]) > 0 or float(peak_row["_demand_loss"]) > 0 or float(peak_row["_product_impact"]) > 0:
        recovery_candidates = history_after_peak.loc[
            (pd.to_numeric(history_after_peak.get("system_service_level", 0.0), errors="coerce").fillna(0.0) >= 0.999)
            & (pd.to_numeric(history_after_peak.get("demand_fulfillment_rate", 0.0), errors="coerce").fillna(0.0) >= 0.999)
            & (pd.to_numeric(history_after_peak.get("supply_affected_products", 0.0), errors="coerce").fillna(0.0) <= 0.0)
        ]
    else:
        recovery_candidates = history_after_peak.loc[
            (pd.to_numeric(history_after_peak.get("disrupted_suppliers", 0.0), errors="coerce").fillna(0.0) <= 0.0)
            & (pd.to_numeric(history_after_peak.get("degraded_suppliers", 0.0), errors="coerce").fillna(0.0) <= 0.0)
            & (pd.to_numeric(history_after_peak.get("supply_degraded_items", 0.0), errors="coerce").fillna(0.0) <= 0.0)
            & (pd.to_numeric(history_after_peak.get("supply_affected_products", 0.0), errors="coerce").fillna(0.0) <= 0.0)
        ]
    t_recovery = (
        recovery_candidates.iloc[0]["date_str"]
        if not recovery_candidates.empty
        else history.iloc[-1]["date_str"]
    )

    markers: dict[str, dict[str, Any]] = {}
    fallback_key = t0
    for label, date_key in {
        "t0": t0,
        "t_start": t_start,
        "t_peak": t_peak,
        "t_recovery": t_recovery,
    }.items():
        selected_key = date_key if date_key in network_by_date.index else fallback_key
        if selected_key not in network_by_date.index:
            continue
        row = network_by_date.loc[selected_key]
        markers[label] = {
            "date": str(pd.Timestamp(row["date"]).date()),
            "supplier_disrupted_nodes": int(row["supplier_disrupted_nodes"]),
            "supplier_degraded_nodes": int(row["supplier_degraded_nodes"]),
            "material_affected_nodes": int(row["material_affected_nodes"]),
            "material_blocked_nodes": int(row["material_blocked_nodes"]),
            "bom_edge_disrupted": int(row["bom_edge_disrupted"]),
        }
    return markers


def build_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, int]:
    summary = _summarize_snapshot(snapshot)
    return {
        "supplier_disrupted_nodes": int(summary["supplier_disrupted_nodes"]),
        "supplier_degraded_nodes": int(summary["supplier_degraded_nodes"]),
        "material_affected_nodes": int(summary["material_affected_nodes"]),
        "material_blocked_nodes": int(summary["material_blocked_nodes"]),
        "assembly_affected_nodes": int(summary["assembly_affected_nodes"]),
        "assembly_blocked_nodes": int(summary["assembly_blocked_nodes"]),
        "product_affected_nodes": int(summary["product_affected_nodes"]),
        "product_blocked_nodes": int(summary["product_blocked_nodes"]),
        "supply_edge_disrupted": int(summary["supply_edge_disrupted"]),
        "bom_edge_disrupted": int(summary["bom_edge_disrupted"]),
        "supply_edge_backup_active": int(summary["supply_edge_backup_active"]),
    }


def export_core_metric_trends(result: SimulationResult, figure_path: str | Path) -> Path | None:
    history = result.history.copy()
    if history.empty:
        return None
    history["date"] = pd.to_datetime(history["date"])
    return export_panel_trend_figure(
        history=history,
        figure_path=figure_path,
        title=f"核心指标趋势：{result.scenario.scenario_id}",
        scenario_start=result.scenario.start_date.normalize(),
        panels=[
            {
                "title": "服务水平恢复轨迹",
                "ylabel": "服务水平",
                "series": [
                    ("service_level", "产品服务水平", "#0F766E"),
                    ("demand_fulfillment_rate", "需求满足率", "#D97706"),
                    ("system_service_level", "系统服务水平", "#5B6CFA"),
                ],
            },
            {
                "title": "中断影响强度",
                "ylabel": "影响规模",
                "series": [
                    ("supply_unavailable_items", "供应不可用物料", "#C44536"),
                    ("total_backlog_demand", "累计积压需求", "#E9A03B"),
                    ("fused_failed_items", "融合失败物料", "#7F1D1D"),
                ],
            },
            {
                "title": "关键节点与策略动作",
                "ylabel": "节点 / 动作数",
                "series": [
                    ("disrupted_suppliers", "中断供应商", "#D1495B"),
                    ("degraded_suppliers", "降级供应商", "#F6BD60"),
                    ("disrupted_key_suppliers", "中断关键供应商", "#8C1C13"),
                    ("affected_key_items", "受影响关键物料", "#C9A227"),
                    ("failed_key_items", "失败关键物料", "#5F0F40"),
                    ("active_backup_switches", "激活备用切换", "#277DA1"),
                    ("active_priority_repairs", "激活优先修复", "#577590"),
                ],
            },
            {
                "title": "策略累计成本",
                "ylabel": "累计成本",
                "series": [
                    ("policy_cumulative_cost", "累计策略成本", "#3D5A80"),
                    ("backup_supplier_switch_cumulative_cost", "备用切换累计成本", "#2A9D8F"),
                    ("equivalent_material_substitution_cumulative_cost", "替代料累计成本", "#E76F51"),
                    ("priority_repair_cumulative_cost", "优先修复累计成本", "#264653"),
                ],
            },
        ],
    )


def export_supplier_network_trends(
    result: SimulationResult,
    network_history: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    if network_history.empty:
        return None
    history = network_history.copy()
    history["date"] = pd.to_datetime(history["date"])
    return export_panel_trend_figure(
        history=history,
        figure_path=figure_path,
        title=f"供应商网络趋势：{result.scenario.scenario_id}",
        scenario_start=result.scenario.start_date.normalize(),
        panels=[
            {
                "title": "供应商节点状态",
                "ylabel": "节点数",
                "series": [
                    ("supplier_available_nodes", "可用供应商", "#2A9D8F"),
                    ("supplier_degraded_nodes", "降级供应商", "#E9C46A"),
                    ("supplier_disrupted_nodes", "中断供应商", "#D62828"),
                ],
            },
            {
                "title": "供应商网络边状态",
                "ylabel": "边数",
                "series": [
                    ("supplier_network_active_edges", "供应商网络活跃边", "#577590"),
                    ("supplier_network_disrupted_edges", "供应商网络中断边", "#A4133C"),
                ],
            },
            {
                "title": "供应映射与备用路径",
                "ylabel": "边数",
                "series": [
                    ("supply_edge_active", "供应映射活跃边", "#43AA8B"),
                    ("supply_edge_backup_active", "备用映射激活边", "#277DA1"),
                    ("supply_edge_disrupted", "供应映射中断边", "#BC4749"),
                ],
            },
        ],
    )


def export_material_network_trends(
    result: SimulationResult,
    network_history: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    if network_history.empty:
        return None
    history = network_history.copy()
    history["date"] = pd.to_datetime(history["date"])
    return export_panel_trend_figure(
        history=history,
        figure_path=figure_path,
        title=f"物料网络趋势：{result.scenario.scenario_id}",
        scenario_start=result.scenario.start_date.normalize(),
        panels=[
            {
                "title": "物料层中断情况",
                "ylabel": "节点数",
                "series": [
                    ("material_affected_nodes", "受影响物料", "#F4A261"),
                    ("material_blocked_nodes", "阻断物料", "#BC4749"),
                ],
            },
            {
                "title": "装配层中断情况",
                "ylabel": "节点数",
                "series": [
                    ("assembly_affected_nodes", "受影响装配件", "#F6BD60"),
                    ("assembly_blocked_nodes", "阻断装配件", "#D00000"),
                ],
            },
            {
                "title": "产品层中断情况",
                "ylabel": "节点数",
                "series": [
                    ("product_affected_nodes", "受影响产品", "#4D908E"),
                    ("product_blocked_nodes", "阻断产品", "#7F1D1D"),
                ],
            },
            {
                "title": "BOM 与替代边变化",
                "ylabel": "边数",
                "series": [
                    ("bom_edge_disrupted", "BOM 中断边", "#6A040F"),
                    ("alternative_edge_substituted", "替代边已启用", "#6D597A"),
                ],
            },
        ],
    )


def export_panel_trend_figure(
    *,
    history: pd.DataFrame,
    figure_path: str | Path,
    title: str,
    scenario_start: pd.Timestamp,
    panels: list[dict[str, Any]],
) -> Path | None:
    if history.empty:
        return None

    working = history.copy()
    working["date"] = pd.to_datetime(working["date"])
    fig, axes = plt.subplots(len(panels), 1, figsize=(14.4, max(3.15 * len(panels), 7.8)), sharex=True)
    if len(panels) == 1:
        axes = [axes]

    value_columns = [
        column
        for panel in panels
        for column, _, _ in panel["series"]
        if column in working.columns
    ]
    focus_window = compute_time_focus_window(
        working,
        value_columns=value_columns,
        scenario_start=scenario_start,
    )
    subtitle = f"自动聚焦扰动影响窗口 | 场景开始：{pd.Timestamp(scenario_start).date()}"
    add_figure_header(fig, title, subtitle)
    plot_top = max(0.67, min(0.82, float(getattr(fig, "_codex_header_layout_top", 0.85)) - 0.02))
    fig.subplots_adjust(left=0.09, right=0.82, bottom=0.085, top=plot_top, hspace=0.36)

    for ax, panel in zip(axes, panels):
        _plot_lines(
            ax,
            working,
            panel["series"],
            ylabel=panel["ylabel"],
            title=panel.get("title"),
            scenario_start=scenario_start,
            focus_window=focus_window,
        )
        if focus_window is not None:
            ax.set_xlim(focus_window)
        format_date_axis(ax)

    axes[-1].set_xlabel("日期", fontproperties=font_props())
    return finish_figure(fig, figure_path, top=0.93, tight=False)


def build_network_comparison_frame(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return pd.DataFrame(columns=NETWORK_COMPARISON_COLUMNS)

    records: list[dict[str, Any]] = []
    for row in summary_df.itertuples(index=False):
        history_csv = getattr(row, "history_csv", None)
        network_history_csv = getattr(row, "network_history_csv", None)
        if not history_csv or not network_history_csv:
            continue
        history_path = Path(history_csv)
        network_path = Path(network_history_csv)
        if not history_path.exists() or not network_path.exists():
            continue

        history = pd.read_csv(history_path)
        network_history = pd.read_csv(network_path)
        if history.empty or network_history.empty:
            continue

        comparison = history.merge(network_history, on="date", how="left", suffixes=("", "_network"))
        comparison = comparison.reset_index(drop=True)
        comparison["scenario_id"] = str(getattr(row, "scenario_id"))
        comparison["policy_profile"] = str(getattr(row, "policy_profile"))
        comparison["run_label"] = f"{getattr(row, 'scenario_id')} | {getattr(row, 'policy_profile')}"
        comparison["day_offset"] = comparison.index.astype(int)
        records.extend(
            comparison[[column for column in NETWORK_COMPARISON_COLUMNS if column in comparison.columns]]
            .to_dict("records")
        )

    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=NETWORK_COMPARISON_COLUMNS)
    for column in NETWORK_COMPARISON_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[NETWORK_COMPARISON_COLUMNS].copy()


def export_timeline_comparison_figure(network_comparison: pd.DataFrame, figure_path: str | Path) -> Path | None:
    return _export_batch_comparison_figure(
        network_comparison,
        figure_path,
        metrics=[
            ("service_level", "产品服务水平"),
            ("system_service_level", "系统服务水平"),
            ("total_backlog_demand", "总积压需求"),
        ],
        title="批量时间轴对比",
    )


def export_supplier_network_comparison_figure(
    network_comparison: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    return _export_batch_comparison_figure(
        network_comparison,
        figure_path,
        metrics=[
            ("supplier_disrupted_nodes", "中断供应商"),
            ("supplier_degraded_nodes", "降级供应商"),
            ("supply_edge_backup_active", "备用激活边"),
        ],
        title="批量供应商网络对比",
    )


def export_material_network_comparison_figure(
    network_comparison: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    return _export_batch_comparison_figure(
        network_comparison,
        figure_path,
        metrics=[
            ("material_affected_nodes", "受影响物料"),
            ("material_blocked_nodes", "阻断物料"),
            ("bom_edge_disrupted", "BOM 中断边"),
        ],
        title="批量物料网络对比",
    )


def _export_batch_comparison_figure(
    network_comparison: pd.DataFrame,
    figure_path: str | Path,
    *,
    metrics: list[tuple[str, str]],
    title: str,
) -> Path | None:
    if network_comparison.empty or "scenario_id" not in network_comparison.columns:
        return None
    scenarios = sorted(network_comparison["scenario_id"].dropna().astype(str).unique().tolist())
    if not scenarios:
        return None

    fig, axes = plt.subplots(
        len(scenarios),
        len(metrics),
        figsize=(5.4 * len(metrics), 3.8 * len(scenarios)),
        squeeze=False,
        sharex=False,
    )
    color_map = _build_profile_colors(network_comparison)
    add_figure_header(fig, title, "按场景拆分对比不同策略在关键指标上的演化")
    plot_top = max(0.68, min(0.86, float(getattr(fig, "_codex_header_layout_top", 0.88)) - 0.02))
    fig.subplots_adjust(left=0.07, right=0.91, bottom=0.085, top=plot_top, hspace=0.34, wspace=0.2)
    for row_index, scenario_id in enumerate(scenarios):
        scenario_df = network_comparison.loc[network_comparison["scenario_id"].astype(str) == scenario_id].copy()
        profile_count = scenario_df["policy_profile"].astype(str).nunique()
        for col_index, (metric, metric_title) in enumerate(metrics):
            ax = axes[row_index][col_index]
            if metric not in scenario_df.columns:
                ax.set_axis_off()
                continue
            for policy_profile, group in scenario_df.groupby("policy_profile", dropna=False):
                working = group.sort_values("day_offset")
                values = pd.to_numeric(working[metric], errors="coerce")
                ax.plot(
                    working["day_offset"],
                    values,
                    linewidth=2.4,
                    label=str(policy_profile),
                    color=color_map.get(str(policy_profile)),
                    alpha=0.95,
                )
                if profile_count <= 4 and not working.empty and values.notna().any():
                    last_index = values.last_valid_index()
                    if last_index is not None:
                        annotate_series_endpoint(
                            ax,
                            int(working.loc[last_index, "day_offset"]),
                            float(values.loc[last_index]),
                            str(policy_profile),
                            color=color_map.get(str(policy_profile), "#334155"),
                        )
            style_axes(
                ax,
                title=f"{scenario_id} | {metric_title}",
                xlabel="相对天数",
                ylabel=metric_title,
                grid_axis="y",
            )
            if _is_integer_metric(metric):
                integer_ticks(ax)
            if row_index == 0 and col_index == len(metrics) - 1:
                legend_style(ax, loc="upper left", bbox_to_anchor=(1.01, 1.0))

    return finish_figure(fig, figure_path, top=0.92, tight=False)


def _plot_lines(
    ax,
    frame: pd.DataFrame,
    series: list[tuple[str, str, str]],
    *,
    ylabel: str,
    scenario_start: pd.Timestamp,
    title: str | None = None,
    focus_window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> None:
    drawn = False
    rate_like = True
    visible_columns: list[str] = []
    endpoints: list[tuple[pd.Timestamp, float, str, str]] = []

    for column, label, color in series:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        ax.plot(
            frame["date"],
            values,
            color=color,
            linewidth=2.6,
            label=label,
            alpha=0.96,
            solid_capstyle="round",
        )
        if not frame.empty and values.notna().any():
            endpoint_values = values
            if focus_window is not None:
                visible_mask = frame["date"].between(pd.Timestamp(focus_window[0]), pd.Timestamp(focus_window[1]))
                if bool(visible_mask.any()):
                    endpoint_values = values.loc[visible_mask]
            last_index = endpoint_values.last_valid_index()
            if last_index is not None:
                last_date = pd.Timestamp(frame.loc[last_index, "date"])
                last_value = float(values.loc[last_index])
                ax.scatter(
                    last_date,
                    last_value,
                    color=color,
                    s=34,
                    zorder=4,
                    edgecolor="#FFFFFF",
                    linewidth=0.9,
                )
                endpoints.append((last_date, last_value, label, color))
        visible_columns.append(column)
        if not _looks_like_rate_column(column, values):
            rate_like = False
        drawn = True
    style_axes(ax, title=title, ylabel=ylabel, grid_axis="y")
    ax.margins(x=0.02, y=0.14)
    if drawn and rate_like and visible_columns:
        ax.set_ylim(-0.03, 1.05)
    if drawn and _is_integer_panel(frame, visible_columns):
        integer_ticks(ax)
    add_scenario_marker(ax, scenario_start)
    if len(endpoints) <= 3:
        annotate_series_endpoints(
            ax,
            [
                (
                    last_date,
                    last_value,
                    f"{label} {last_value:.0f}" if abs(last_value - round(last_value)) < 1e-9 else f"{label} {last_value:.2f}",
                    color,
                )
                for last_date, last_value, label, color in endpoints
            ],
        )
    if drawn:
        legend_style(
            ax,
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            fontsize=9.6 if len(visible_columns) >= 5 else 10.2,
        )


def _summarize_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    summary = _empty_network_record(snapshot["date"])
    summary["date"] = str(pd.Timestamp(snapshot["date"]).date())

    for node in snapshot.get("node_state", {}).values():
        node_type = str(node.get("node_type") or "").strip().lower()
        visual_status = str(node.get("visual_status") or "").strip().lower()
        key = _node_metric_key(node_type=node_type, visual_status=visual_status)
        if key:
            summary[key] += 1

    for edge in snapshot.get("edge_state", {}).values():
        edge_type = _normalize_edge_token(edge.get("edge_type"))
        status = _normalize_edge_token(edge.get("status"))
        key = _edge_metric_key(edge_type=edge_type, status=status)
        if key == "unknown_edge_count":
            summary["unknown_edge_count"] += 1
        elif key:
            summary[key] += 1

    return summary


def _empty_network_record(date_value: Any) -> dict[str, Any]:
    record = {column: 0 for column in NETWORK_HISTORY_COLUMNS}
    record["date"] = str(pd.Timestamp(date_value).date())
    return record


def _node_metric_key(*, node_type: str, visual_status: str) -> str | None:
    if node_type == "supplier":
        return {
            "available": "supplier_available_nodes",
            "degraded": "supplier_degraded_nodes",
            "disrupted": "supplier_disrupted_nodes",
        }.get(visual_status)
    if node_type == "part":
        node_type = "material"
    if node_type in {"material", "assembly", "product"}:
        return {
            "available": f"{node_type}_available_nodes",
            "affected": f"{node_type}_affected_nodes",
            "blocked": f"{node_type}_blocked_nodes",
        }.get(visual_status)
    return None


def _edge_metric_key(*, edge_type: str, status: str) -> str | None:
    if edge_type == "unknown" or status == "unknown":
        return "unknown_edge_count"
    return {
        ("supplier_network", "active"): "supplier_network_active_edges",
        ("supplier_network", "disrupted"): "supplier_network_disrupted_edges",
        ("supplier_item_map", "active"): "supply_edge_active",
        ("supplier_item_map", "backup_active"): "supply_edge_backup_active",
        ("supplier_item_map", "disrupted"): "supply_edge_disrupted",
        ("supplier_item_map", "standby"): "supply_edge_standby",
        ("bom", "active"): "bom_edge_active",
        ("bom", "disrupted"): "bom_edge_disrupted",
        ("alternative", "standby"): "alternative_edge_standby",
        ("alternative", "substituted"): "alternative_edge_substituted",
    }.get((edge_type, status))


def _normalize_edge_token(value: Any) -> str:
    if pd.isna(value):
        return "unknown"
    normalized = str(value).strip().lower()
    return normalized if normalized else "unknown"


def _build_profile_colors(frame: pd.DataFrame) -> dict[str, Any]:
    profiles = frame["policy_profile"].dropna().astype(str).unique().tolist()
    return qualitative_color_map(profiles)


def _looks_like_rate_column(column: str, values: pd.Series) -> bool:
    normalized_name = str(column).lower()
    if any(token in normalized_name for token in ["service_level", "rate", "fulfillment"]):
        return True
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return False
    return bool(numeric.between(0.0, 1.0).all())


def _is_integer_panel(frame: pd.DataFrame, columns: list[str]) -> bool:
    if not columns:
        return False
    numeric_columns = [
        pd.to_numeric(frame[column], errors="coerce").dropna()
        for column in columns
        if column in frame.columns
    ]
    if not numeric_columns:
        return False
    return all((series % 1).abs().lt(1e-9).all() for series in numeric_columns if not series.empty)


def _is_integer_metric(metric: str) -> bool:
    normalized = str(metric).lower()
    return not any(token in normalized for token in ["service_level", "rate", "ratio", "fulfillment", "cost"])


