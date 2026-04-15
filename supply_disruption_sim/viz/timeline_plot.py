from __future__ import annotations

from pathlib import Path

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from supply_disruption_sim.labels import scenario_label
from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.marker_selection import select_marker_dates
from supply_disruption_sim.viz.plot_theme import (
    add_figure_header,
    add_scenario_marker,
    finish_figure,
    font_props,
    format_date_axis,
    integer_ticks,
    legend_style,
    style_axes,
)


TIMELINE_ACTION_COLORS = {
    "backup_switch": "#0F766E",
    "substitution": "#C2410C",
    "priority_repair": "#7C3AED",
    "policy_cost": "#1D4ED8",
    "policy_event": "#111827",
}


def export_timeline_plot(result: SimulationResult, figure_path: str | Path) -> Path | None:
    if result.history.empty:
        return None

    history = result.history.copy()
    history["date"] = pd.to_datetime(history["date"])
    marker_dates = _build_timeline_markers(history, result)
    fig, axes = plt.subplots(3, 1, figsize=(14.4, 10.4), sharex=True)
    add_figure_header(
        fig,
        "恢复策略时间轴总览",
        f"{scenario_label(result.scenario.scenario_id)}：围绕冲击开始、策略启动与业务恢复三个阶段展开",
    )
    plot_top = max(0.68, min(0.84, float(getattr(fig, "_codex_header_layout_top", 0.87)) - 0.02))
    fig.subplots_adjust(left=0.09, right=0.66, bottom=0.09, top=plot_top, hspace=0.40)

    _plot_service_panel(axes[0], history, marker_dates)
    _plot_disruption_panel(axes[1], history, marker_dates)
    _plot_policy_panel(axes[2], history, result, marker_dates)

    for ax in axes:
        format_date_axis(ax)
    axes[-1].set_xlabel("日期", fontproperties=font_props(size=10.8))
    return finish_figure(fig, figure_path, top=0.93, tight=False)


def _plot_service_panel(
    ax,
    history: pd.DataFrame,
    marker_dates: dict[str, pd.Timestamp],
) -> None:
    if "service_level" in history.columns:
        ax.plot(history["date"], history["service_level"], color="#0F766E", linewidth=2.6, label="产品服务水平")
    if "demand_fulfillment_rate" in history.columns:
        ax.plot(history["date"], history["demand_fulfillment_rate"], color="#D97706", linewidth=2.3, label="需求满足率")
    if "system_service_level" in history.columns:
        ax.plot(history["date"], history["system_service_level"], color="#5B6CFA", linewidth=2.3, label="系统服务水平")
    style_axes(ax, title="服务水平变化", ylabel="服务水平", grid_axis="y")
    ax.set_ylim(-0.03, 1.05)
    _add_timeline_markers(ax, marker_dates)
    legend_style(ax, loc="upper left", bbox_to_anchor=(1.16, 1.0))


def _plot_disruption_panel(
    ax,
    history: pd.DataFrame,
    marker_dates: dict[str, pd.Timestamp],
) -> None:
    series = [
        ("supply_unavailable_items", "供应不可用物料", "#C44536"),
        ("supply_effective_unavailable_items", "有效不可用物料", "#7F1D1D"),
        ("total_backlog_demand", "积压需求总量", "#E9A03B"),
        ("fused_failed_items", "融合失败物料", "#6A040F"),
    ]
    plotted_columns: list[str] = []
    for column, label, color in series:
        if column not in history.columns:
            continue
        ax.plot(history["date"], history[column], color=color, linewidth=2.2, label=label)
        plotted_columns.append(column)
    style_axes(ax, title="冲击后果变化", ylabel="影响规模", grid_axis="y")
    if plotted_columns:
        integer_ticks(ax)
    _add_timeline_markers(ax, marker_dates)
    legend_style(ax, loc="upper left", bbox_to_anchor=(1.16, 1.0))


def _plot_policy_panel(
    ax,
    history: pd.DataFrame,
    result: SimulationResult,
    marker_dates: dict[str, pd.Timestamp],
) -> None:
    action_columns = []
    if "active_backup_switches" in history.columns:
        ax.plot(
            history["date"],
            history["active_backup_switches"],
            color=TIMELINE_ACTION_COLORS["backup_switch"],
            linewidth=2.2,
            label="激活备用切换",
        )
        action_columns.append("active_backup_switches")
    if "active_substitutions" in history.columns:
        ax.plot(
            history["date"],
            history["active_substitutions"],
            color=TIMELINE_ACTION_COLORS["substitution"],
            linewidth=2.2,
            label="激活等效替代",
        )
        action_columns.append("active_substitutions")
    if "active_priority_repairs" in history.columns:
        ax.plot(
            history["date"],
            history["active_priority_repairs"],
            color=TIMELINE_ACTION_COLORS["priority_repair"],
            linewidth=2.2,
            label="激活优先修复",
        )
        action_columns.append("active_priority_repairs")

    if action_columns:
        integer_ticks(ax)
        action_max = max(
            float(
                pd.concat(
                    [pd.to_numeric(history[column], errors="coerce").fillna(0) for column in action_columns],
                    axis=0,
                ).max()
            ),
            1.0,
        )
        ax.set_ylim(0, action_max * 1.16)

    ax_cost = ax.twinx()
    if "policy_cumulative_cost" in history.columns:
        ax_cost.plot(
            history["date"],
            history["policy_cumulative_cost"],
            color=TIMELINE_ACTION_COLORS["policy_cost"],
            linewidth=2.5,
            linestyle="--",
            label="累计策略成本",
        )
        ax_cost.fill_between(
            history["date"],
            pd.to_numeric(history["policy_cumulative_cost"], errors="coerce").fillna(0),
            color=TIMELINE_ACTION_COLORS["policy_cost"],
            alpha=0.06,
        )

    if result.policy_events:
        event_frame = pd.DataFrame(result.policy_events)
        if not event_frame.empty and "date" in event_frame.columns:
            event_dates = pd.to_datetime(event_frame["date"])
            action_ceiling = float(ax.get_ylim()[1])
            ax.scatter(
                event_dates,
                [action_ceiling * 0.82] * len(event_dates),
                color=TIMELINE_ACTION_COLORS["policy_event"],
                s=26,
                label="策略事件",
                zorder=4,
            )
    style_axes(ax, title="恢复动作时间线", ylabel="动作数量", grid_axis="y")
    _add_timeline_markers(ax, marker_dates)
    ax_cost.set_ylabel("累计成本", color=TIMELINE_ACTION_COLORS["policy_cost"], fontproperties=font_props(size=10.8))
    ax_cost.yaxis.set_label_coords(1.1, 0.5)
    ax_cost.tick_params(axis="y", colors=TIMELINE_ACTION_COLORS["policy_cost"], labelsize=10.5, pad=3)
    ax_cost.spines["top"].set_visible(False)
    ax_cost.spines["left"].set_visible(False)
    ax_cost.spines["right"].set_color("#CBD5E1")
    handles, labels = ax.get_legend_handles_labels()
    cost_handles, cost_labels = ax_cost.get_legend_handles_labels()
    combined_handles = handles + cost_handles
    combined_labels = labels + cost_labels
    if combined_handles:
        legend = ax.legend(
            combined_handles,
            combined_labels,
            loc="upper left",
            bbox_to_anchor=(1.16, 1.0),
            frameon=True,
            fancybox=True,
            framealpha=0.95,
            borderpad=0.45,
            borderaxespad=0.0,
            handlelength=2.1,
            handletextpad=0.6,
            labelspacing=0.45,
            fontsize=10,
            prop=font_props(size=10),
        )
        if legend is not None:
            legend.get_frame().set_linewidth(0.9)
            legend.get_frame().set_facecolor("#FFFFFF")
            legend.get_frame().set_edgecolor("#CBD5E1")


def _build_timeline_markers(history: pd.DataFrame, result: SimulationResult) -> dict[str, pd.Timestamp]:
    marker_candidates = select_marker_dates(history, result.scenario.start_date.normalize())
    markers: dict[str, pd.Timestamp] = {}
    for key in ["t_start", "t_policy_start", "t_recovery"]:
        marker_value = marker_candidates.get(key)
        if marker_value is None:
            continue
        markers[key] = pd.Timestamp(marker_value)
    return markers


def _add_timeline_markers(ax, marker_dates: dict[str, pd.Timestamp]) -> None:
    if "t_start" in marker_dates:
        add_scenario_marker(ax, marker_dates["t_start"], label="冲击开始")

    marker_specs = [
        ("t_policy_start", "策略启动", "#277DA1", "#EFF6FF", "#93C5FD"),
        ("t_recovery", "业务恢复", "#0F766E", "#ECFDF5", "#6EE7B7"),
    ]
    ymin, ymax = ax.get_ylim()
    for key, label, color, facecolor, edgecolor in marker_specs:
        if key not in marker_dates:
            continue
        marker_date = marker_dates[key]
        ax.axvline(marker_date, color=color, linestyle=(0, (3, 2)), linewidth=1.4, alpha=0.9)
        ax.text(
            marker_date,
            ymax - (ymax - ymin) * (0.20 if key == "t_policy_start" else 0.30),
            label,
            color=color,
            fontsize=9.2,
            ha="left",
            va="top",
            bbox={
                "facecolor": facecolor,
                "edgecolor": edgecolor,
                "boxstyle": "round,pad=0.22",
                "alpha": 0.9,
            },
            fontproperties=font_props(size=9.2),
        )
