from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from supply_disruption_sim.labels import policy_profile_label, scenario_label, scenario_policy_run_label
from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.plot_theme import (
    add_figure_header,
    annotate_series_endpoint,
    finish_figure,
    font_props,
    integer_ticks,
    legend_style,
    qualitative_color_map,
    style_axes,
)


MONTHLY_DISRUPTED_COLUMNS = [
    "month",
    "month_label",
    "supplier_disrupted_nodes",
    "material_disrupted_nodes",
    "assembly_disrupted_nodes",
    "product_disrupted_nodes",
    "total_disrupted_nodes",
]

PROPAGATION_LAYER_LABELS = {
    "overall": "整体传播",
    "supplier": "供应商层",
    "material": "物料层",
    "assembly": "装配层",
    "product": "产品层",
}

BATCH_PROPAGATION_METRICS = [
    ("propagation_duration_months", "整体传播"),
    ("supplier_propagation_duration_months", "供应商层"),
    ("material_propagation_duration_months", "物料层"),
    ("assembly_propagation_duration_months", "装配层"),
    ("product_propagation_duration_months", "产品层"),
]


def build_monthly_disrupted_nodes_frame(
    network_history: pd.DataFrame,
) -> pd.DataFrame:
    if network_history.empty:
        return pd.DataFrame(columns=MONTHLY_DISRUPTED_COLUMNS)

    history = network_history.copy()
    history["date"] = pd.to_datetime(history["date"])
    history["month"] = history["date"].dt.to_period("M").dt.to_timestamp()
    history["supplier_disrupted_nodes"] = _safe_numeric(history, "supplier_disrupted_nodes")
    history["material_disrupted_nodes"] = _safe_numeric(history, "material_blocked_nodes")
    history["assembly_disrupted_nodes"] = _safe_numeric(history, "assembly_blocked_nodes")
    history["product_disrupted_nodes"] = _safe_numeric(history, "product_blocked_nodes")
    history["total_disrupted_nodes"] = (
        history["supplier_disrupted_nodes"]
        + history["material_disrupted_nodes"]
        + history["assembly_disrupted_nodes"]
        + history["product_disrupted_nodes"]
    )

    monthly = (
        history.groupby("month", as_index=False)
        [
            [
                "month",
                "supplier_disrupted_nodes",
                "material_disrupted_nodes",
                "assembly_disrupted_nodes",
                "product_disrupted_nodes",
                "total_disrupted_nodes",
            ]
        ]
        .max()
        .sort_values("month")
        .reset_index(drop=True)
    )
    monthly["month_label"] = monthly["month"].dt.strftime("%Y-%m")
    return monthly[MONTHLY_DISRUPTED_COLUMNS].copy()


def summarize_propagation_durations(
    result: SimulationResult,
    network_history: pd.DataFrame,
) -> dict[str, Any]:
    if network_history.empty:
        return {
            "propagation_stop_date": None,
            "propagation_duration_months": 0,
            "supplier_propagation_duration_months": 0,
            "material_propagation_duration_months": 0,
            "assembly_propagation_duration_months": 0,
            "product_propagation_duration_months": 0,
        }

    history = network_history.copy()
    history["date"] = pd.to_datetime(history["date"])
    history = history.loc[history["date"] >= result.scenario.start_date.normalize()].reset_index(drop=True)
    if history.empty:
        return {
            "propagation_stop_date": None,
            "propagation_duration_months": 0,
            "supplier_propagation_duration_months": 0,
            "material_propagation_duration_months": 0,
            "assembly_propagation_duration_months": 0,
            "product_propagation_duration_months": 0,
        }

    activity = {
        "supplier": (_safe_numeric(history, "supplier_degraded_nodes") + _safe_numeric(history, "supplier_disrupted_nodes")) > 0,
        "material": (_safe_numeric(history, "material_affected_nodes") + _safe_numeric(history, "material_blocked_nodes")) > 0,
        "assembly": (_safe_numeric(history, "assembly_affected_nodes") + _safe_numeric(history, "assembly_blocked_nodes")) > 0,
        "product": (_safe_numeric(history, "product_affected_nodes") + _safe_numeric(history, "product_blocked_nodes")) > 0,
    }
    activity["overall"] = activity["supplier"] | activity["material"] | activity["assembly"] | activity["product"]

    summary: dict[str, Any] = {}
    overall_last_active = None
    for layer, mask in activity.items():
        active_dates = history.loc[mask, "date"]
        last_active = active_dates.max() if not active_dates.empty else pd.NaT
        duration_months = _count_active_months(
            start_date=result.scenario.start_date.normalize(),
            last_active_date=last_active,
        )
        if layer == "overall":
            overall_last_active = last_active
            summary["propagation_stop_date"] = (
                str(pd.Timestamp(last_active).date()) if pd.notna(last_active) else None
            )
            summary["propagation_duration_months"] = duration_months
        else:
            summary[f"{layer}_propagation_duration_months"] = duration_months

    if overall_last_active is None or pd.isna(overall_last_active):
        summary["propagation_stop_date"] = None
    return summary


def export_monthly_disrupted_nodes_figure(
    result: SimulationResult,
    network_history: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    monthly = build_monthly_disrupted_nodes_frame(network_history)
    if monthly.empty:
        return None

    fig, ax = plt.subplots(figsize=(14.2, 6.9))
    x_values = list(range(len(monthly)))
    bottom = [0] * len(monthly)
    series = [
        ("supplier_disrupted_nodes", "供应商中断", "#D1495B"),
        ("material_disrupted_nodes", "物料阻断", "#BC4749"),
        ("assembly_disrupted_nodes", "装配阻断", "#7F1D1D"),
        ("product_disrupted_nodes", "产品阻断", "#3D405B"),
    ]
    for column, label, color in series:
        values = monthly[column].astype(int).tolist()
        ax.bar(
            x_values,
            values,
            bottom=bottom,
            label=label,
            color=color,
            alpha=0.92,
            width=0.68,
            edgecolor="#FFFFFF",
            linewidth=0.9,
        )
        bottom = [current + value for current, value in zip(bottom, values)]

    total_values = monthly["total_disrupted_nodes"].astype(int).tolist()
    ax.plot(
        x_values,
        total_values,
        color="#1D3557",
        linewidth=2.6,
        marker="o",
        markersize=6.4,
        label="总中断节点",
    )
    if total_values:
        peak_index = max(range(len(total_values)), key=lambda index: total_values[index])
        annotate_series_endpoint(
            ax,
            x_values[peak_index],
            total_values[peak_index],
            f"峰值 {total_values[peak_index]}",
            color="#1D3557",
            x_offset=8,
            y_offset=-18,
        )

    style_axes(ax, title="月度中断节点分布", ylabel="节点数", xlabel="月份", grid_axis="y")
    ax.set_xticks(x_values)
    ax.set_xticklabels(monthly["month_label"], fontproperties=font_props(size=10.2))
    if max(total_values, default=0) <= 0:
        ax.set_ylim(-0.05, 1.0)
        ax.text(
            0.5,
            0.5,
            "本场景没有观测到 blocked / disrupted 节点高峰",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=11,
            color="#5B6B7A",
            fontproperties=font_props(size=11),
        )
    else:
        integer_ticks(ax)
    legend_style(ax, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    add_figure_header(
        fig,
        "中断节点月度变化",
        "按月分别提取供应商与物料/装配/产品阻断节点的最大值，并叠加展示总中断峰值",
    )

    plot_top = max(0.69, min(0.82, float(getattr(fig, "_codex_header_layout_top", 0.85)) - 0.02))
    fig.subplots_adjust(left=0.09, right=0.82, bottom=0.19, top=plot_top)
    start_month = result.scenario.start_date.normalize().to_period("M").to_timestamp()
    start_matches = monthly.index[monthly["month"] == start_month].tolist()
    if start_matches:
        ax.axvline(start_matches[0], color="#D1495B", linestyle=(0, (3, 2)), linewidth=1.4, alpha=0.9)

    ax.text(
        0.01,
        -0.16,
        "统计口径：供应商 disrupted 与物料/装配/产品 blocked 按月分别取最大值；总中断节点为日度总和在该月内的最大值。",
        transform=ax.transAxes,
        fontsize=10,
        color="#5B6B7A",
        fontproperties=font_props(size=10),
    )
    return finish_figure(fig, figure_path, top=0.9, tight=False)


def export_propagation_duration_figure(
    result: SimulationResult,
    network_history: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    summary = summarize_propagation_durations(result, network_history)
    frame = pd.DataFrame(
        [
            {
                "layer": layer,
                "label": PROPAGATION_LAYER_LABELS[layer],
                "duration_months": int(summary.get(_duration_key(layer), 0) or 0),
            }
            for layer in ["overall", "supplier", "material", "assembly", "product"]
        ]
    )
    if frame["duration_months"].sum() <= 0:
        return None

    fig, ax = plt.subplots(figsize=(12.6, 6.3))
    colors = ["#264653", "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51"]
    bars = ax.barh(frame["label"], frame["duration_months"], color=colors, alpha=0.92, height=0.62)
    ax.invert_yaxis()
    max_duration = max(float(frame["duration_months"].max()), 1.0)
    x_padding = max_duration * 0.16
    x_limit = max_duration + x_padding
    style_axes(ax, title="各层传播持续时间", xlabel="月数", ylabel="传播层级", grid_axis="x")
    ax.set_xlim(0, x_limit)

    for bar, months in zip(bars, frame["duration_months"]):
        ax.text(
            min(bar.get_width() + x_padding * 0.35, x_limit - x_padding * 0.2),
            bar.get_y() + bar.get_height() / 2,
            f"{int(months)} 个月",
            va="center",
            fontsize=10,
            color="#12263A",
            fontproperties=font_props(size=10),
        )

    stop_date = summary.get("propagation_stop_date")
    subtitle = f"传播停止日期：{stop_date}" if stop_date else "传播停止日期：未观测到显著传播"
    add_figure_header(fig, "中断传播时长对比", subtitle)
    plot_top = max(0.71, min(0.83, float(getattr(fig, "_codex_header_layout_top", 0.85)) - 0.02))
    fig.subplots_adjust(left=0.15, right=0.94, bottom=0.13, top=plot_top)
    return finish_figure(fig, figure_path, top=0.9, tight=False)


def build_monthly_disrupted_nodes_comparison_frame(network_comparison: pd.DataFrame) -> pd.DataFrame:
    if network_comparison.empty:
        return pd.DataFrame(
            columns=[
                "scenario_id",
                "policy_profile",
                "month",
                "month_label",
                "supplier_disrupted_nodes",
                "material_disrupted_nodes",
                "assembly_disrupted_nodes",
                "product_disrupted_nodes",
                "total_disrupted_nodes",
            ]
        )

    frame = network_comparison.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["month"] = frame["date"].dt.to_period("M").dt.to_timestamp()
    frame["supplier_disrupted_nodes"] = _safe_numeric(frame, "supplier_disrupted_nodes")
    frame["material_disrupted_nodes"] = _safe_numeric(frame, "material_blocked_nodes")
    frame["assembly_disrupted_nodes"] = _safe_numeric(frame, "assembly_blocked_nodes")
    frame["product_disrupted_nodes"] = _safe_numeric(frame, "product_blocked_nodes")
    frame["total_disrupted_nodes"] = (
        frame["supplier_disrupted_nodes"]
        + frame["material_disrupted_nodes"]
        + frame["assembly_disrupted_nodes"]
        + frame["product_disrupted_nodes"]
    )
    monthly = (
        frame.groupby(["scenario_id", "policy_profile", "month"], as_index=False)[
            [
                "supplier_disrupted_nodes",
                "material_disrupted_nodes",
                "assembly_disrupted_nodes",
                "product_disrupted_nodes",
                "total_disrupted_nodes",
            ]
        ]
        .max()
        .sort_values(["scenario_id", "policy_profile", "month"])
        .reset_index(drop=True)
    )
    monthly["month_label"] = monthly["month"].dt.strftime("%Y-%m")
    return monthly


def export_monthly_disrupted_nodes_comparison_figure(
    network_comparison: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    monthly = build_monthly_disrupted_nodes_comparison_frame(network_comparison)
    if monthly.empty:
        return None

    scenarios = sorted(monthly["scenario_id"].dropna().astype(str).unique().tolist())
    if not scenarios:
        return None

    fig, axes = plt.subplots(len(scenarios), 1, figsize=(13.4, max(4.4 * len(scenarios), 5.8)), squeeze=False)
    color_map = _build_profile_color_map(monthly["policy_profile"].astype(str).tolist())
    add_figure_header(fig, "不同策略下的月度中断节点对比", "按场景拆分，观察策略是否缩短中断高峰持续时间")
    plot_top = max(0.69, min(0.84, float(getattr(fig, "_codex_header_layout_top", 0.87)) - 0.02))
    fig.subplots_adjust(left=0.09, right=0.82, bottom=0.11, top=plot_top, hspace=0.38)

    for row_index, scenario_id in enumerate(scenarios):
        ax = axes[row_index][0]
        scenario_df = monthly.loc[monthly["scenario_id"].astype(str) == scenario_id].copy()
        month_labels = scenario_df["month_label"].drop_duplicates().tolist()
        x_lookup = {month_label: index for index, month_label in enumerate(month_labels)}
        for policy_profile, group in scenario_df.groupby("policy_profile", dropna=False):
            ordered = group.sort_values("month")
            x_values = [x_lookup[label] for label in ordered["month_label"]]
            y_values = ordered["total_disrupted_nodes"].astype(int).tolist()
            ax.plot(
                x_values,
                y_values,
                linewidth=2.4,
                marker="o",
                markersize=4.8,
                label=policy_profile_label(str(policy_profile)),
                color=color_map.get(str(policy_profile)),
            )
        style_axes(ax, title=f"{scenario_label(scenario_id)} | 月度中断节点", ylabel="节点数", grid_axis="y")
        ax.set_xticks(list(x_lookup.values()))
        ax.set_xticklabels(month_labels, fontproperties=font_props(size=10))
        integer_ticks(ax)
        legend_style(ax, loc="upper left", bbox_to_anchor=(1.01, 1.0))

    axes[-1][0].set_xlabel("月份", fontproperties=font_props())
    return finish_figure(fig, figure_path, top=0.92, tight=False)


def export_batch_propagation_duration_comparison_figure(
    summary_df: pd.DataFrame,
    figure_path: str | Path,
) -> Path | None:
    required_columns = {"scenario_id", "policy_profile"}
    if summary_df.empty or not required_columns.issubset(summary_df.columns):
        return None
    available_metrics = [metric for metric, _ in BATCH_PROPAGATION_METRICS if metric in summary_df.columns]
    if not available_metrics:
        return None

    frame = summary_df.copy()
    frame["run_label"] = frame.apply(
        lambda row: scenario_policy_run_label(str(row["scenario_id"]), str(row["policy_profile"])),
        axis=1,
    )
    fig, axes = plt.subplots(len(available_metrics), 1, figsize=(14.0, max(3.45 * len(available_metrics), 6.7)), squeeze=False)
    color_map = _build_profile_color_map(frame["policy_profile"].astype(str).tolist())
    ordered = frame.sort_values(["scenario_id", "policy_profile"]).reset_index(drop=True)
    add_figure_header(fig, "不同策略下的传播时长对比", "将总体传播与各层传播拆开，便于观察策略主要作用在哪一层")
    plot_top = max(0.69, min(0.84, float(getattr(fig, "_codex_header_layout_top", 0.87)) - 0.02))
    fig.subplots_adjust(left=0.09, right=0.95, bottom=0.17, top=plot_top, hspace=0.44)

    for row_index, metric in enumerate(available_metrics):
        ax = axes[row_index][0]
        metric_title = next(label for key, label in BATCH_PROPAGATION_METRICS if key == metric)
        values = pd.to_numeric(ordered[metric], errors="coerce").fillna(0)
        colors = [color_map.get(str(policy_profile)) for policy_profile in ordered["policy_profile"].astype(str)]
        ax.bar(ordered["run_label"], values, color=colors, alpha=0.92, edgecolor="#FFFFFF", linewidth=0.9)
        style_axes(ax, title=f"{metric_title}传播时长", ylabel="月数", grid_axis="y")
        ax.tick_params(axis="x", labelsize=10)
        plt.setp(ax.get_xticklabels(), rotation=16, ha="right")
        integer_ticks(ax)

    axes[-1][0].set_xlabel("情境与策略组合", fontproperties=font_props())
    return finish_figure(fig, figure_path, top=0.92, tight=False)


def _count_active_months(start_date: pd.Timestamp, last_active_date: Any) -> int:
    if pd.isna(last_active_date):
        return 0
    start_period = pd.Timestamp(start_date).to_period("M")
    last_period = pd.Timestamp(last_active_date).to_period("M")
    return int(last_period.ordinal - start_period.ordinal + 1)


def _safe_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([0] * len(frame), index=frame.index, dtype="int64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)


def _duration_key(layer: str) -> str:
    if layer == "overall":
        return "propagation_duration_months"
    return f"{layer}_propagation_duration_months"


def _build_profile_color_map(profiles: list[str]) -> dict[str, str]:
    return qualitative_color_map(profiles)

