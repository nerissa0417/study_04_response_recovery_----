from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from supply_disruption_sim.viz.font_config import configure_matplotlib_chinese_font


configure_matplotlib_chinese_font()


DEFAULT_RUN_DIRS = [
    Path("output/run_random_distributed"),
    Path("output/run_keynode_distributed"),
]

SCENE_FAMILY_BY_RUN = {
    "run_random_distributed": "random",
    "run_keynode_distributed": "keynode",
}

SCENE_LABEL_BY_FAMILY = {
    "random": "随机中断",
    "keynode": "关键节点中断",
}

STAGE_LABELS = {
    "t0": "冲击前",
    "t_start": "冲击开始",
    "t_supply_peak": "冲击峰值",
    "t_policy_start": "策略启动",
    "t_recovery": "业务恢复",
}

POLICY_ORDER = [
    "time_priority_interrupt",
    "all_policies",
    "no_policy",
    "only_backup_switch",
    "only_substitution",
    "only_priority_repair",
]

POLICY_LABELS = {
    "time_priority_interrupt": "当前恢复策略",
    "all_policies": "全策略显示联动",
    "no_policy": "无恢复策略",
    "only_backup_switch": "仅备供切换",
    "only_substitution": "仅等效替代",
    "only_priority_repair": "仅优先抢修",
}

POLICY_COLORS = {
    "time_priority_interrupt": "#0F766E",
    "all_policies": "#1D4ED8",
    "no_policy": "#D62828",
    "only_backup_switch": "#F97316",
    "only_substitution": "#A855F7",
    "only_priority_repair": "#0891B2",
}

POLICY_LINESTYLES = {
    "time_priority_interrupt": "-",
    "all_policies": "--",
    "no_policy": "-",
    "only_backup_switch": "-.",
    "only_substitution": ":",
    "only_priority_repair": (0, (5, 1.4)),
}

COLORS = {
    "text": "#0F172A",
    "muted": "#64748B",
    "grid": "#E2E8F0",
    "spine": "#CBD5E1",
    "service": "#0F766E",
    "demand": "#F59E0B",
    "system": "#4F46E5",
    "supplier": "#0F766E",
    "material": "#D97706",
    "assembly": "#4F46E5",
    "product": "#C1121F",
    "unavailable": "#9A3412",
    "affected": "#D97706",
    "blocked": "#C1121F",
    "failed": "#7F1D1D",
    "backup": "#277DA1",
    "substitution": "#8E44AD",
    "repair": "#0284C7",
    "cost": "#334155",
    "key": "#FF2DAA",
    "available": "#22C55E",
    "bar": "#E11D48",
}


class RunBundle:
    def __init__(
        self,
        *,
        source_run_dir: Path,
        scene_output_dir: Path,
        scenario: pd.DataFrame,
        summary: pd.DataFrame,
        time_series: pd.DataFrame,
        network: pd.DataFrame,
        markers: pd.DataFrame,
        policy_events: pd.DataFrame,
        policy_comparison: pd.DataFrame,
        paths: pd.DataFrame,
        sensitivity: pd.DataFrame,
        snapshots: pd.DataFrame,
    ) -> None:
        self.source_run_dir = source_run_dir
        self.scene_output_dir = scene_output_dir
        self.figures_dir = scene_output_dir / "figures"
        self.snapshots_dir = scene_output_dir / "network_snapshots"
        self.scenario = scenario
        self.summary = summary
        self.time_series = time_series
        self.network = network
        self.markers = markers
        self.policy_events = policy_events
        self.policy_comparison = policy_comparison
        self.paths = paths
        self.sensitivity = sensitivity
        self.snapshots = snapshots
        self.family = SCENE_FAMILY_BY_RUN.get(source_run_dir.name, "unknown")
        self.scene_label = SCENE_LABEL_BY_FAMILY.get(self.family, source_run_dir.name)

    def prepare(self) -> None:
        for frame in [
            self.scenario,
            self.summary,
            self.time_series,
            self.network,
            self.markers,
            self.policy_events,
            self.policy_comparison,
            self.paths,
            self.sensitivity,
            self.snapshots,
        ]:
            if frame.empty:
                continue
            for column in ("date", "snapshot_date", "activate_date"):
                if column in frame.columns:
                    frame[column] = pd.to_datetime(frame[column], errors="coerce")
            numericize(frame)

    def marker_map(self) -> dict[str, pd.Timestamp]:
        if self.markers.empty or "marker_name" not in self.markers.columns:
            return {}
        result: dict[str, pd.Timestamp] = {}
        for row in self.markers.itertuples(index=False):
            marker_name = str(getattr(row, "marker_name", ""))
            date_value = getattr(row, "date", pd.NaT)
            if marker_name and pd.notna(date_value):
                result[marker_name] = pd.Timestamp(date_value)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="读取现有仿真 CSV，生成不覆盖原始结果的科研展示风优化图片。"
    )
    parser.add_argument(
        "--run-dir",
        action="append",
        type=Path,
        dest="run_dirs",
        help="单个情境输出目录，可重复传入；默认处理随机中断和关键节点中断两套正式结果。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/refined_visualizations"),
        help="优化版图片的独立输出根目录，默认不写入原 figures 目录。",
    )
    parser.add_argument(
        "--dashboard-data",
        type=Path,
        default=Path("output/study04_dynamic_frontend/data/dashboard-data.js"),
        help="用于重绘解释型网络快照的动态前端数据包。",
    )
    args = parser.parse_args()

    run_dirs = args.run_dirs or DEFAULT_RUN_DIRS
    dashboard_data = load_dashboard_data(args.dashboard_data)
    all_outputs: list[Path] = []

    for run_dir in run_dirs:
        if not run_dir.exists():
            print(f"跳过不存在的情境目录：{run_dir}")
            continue
        outputs = render_refined_run(run_dir, output_root=args.output_root, dashboard_data=dashboard_data)
        all_outputs.extend(outputs)

    print(f"refined-figures-ok count={len(all_outputs)}")
    for path in all_outputs:
        print(path)
    return 0


def render_refined_run(
    run_dir: Path,
    *,
    output_root: Path = Path("output/refined_visualizations"),
    dashboard_data: dict[str, Any] | None = None,
) -> list[Path]:
    run_dir = Path(run_dir)
    front = run_dir / "tables" / "frontend"
    scene_output_dir = Path(output_root) / run_dir.name
    bundle = RunBundle(
        source_run_dir=run_dir,
        scene_output_dir=scene_output_dir,
        scenario=read_csv(front / "scenario.csv"),
        summary=read_csv(front / "summary.csv"),
        time_series=read_csv(front / "time_series.csv"),
        network=read_csv(front / "network_time_series.csv"),
        markers=read_csv(front / "network_markers.csv"),
        policy_events=read_csv(front / "policy_events.csv"),
        policy_comparison=read_csv(front / "policy_comparison_time_series.csv"),
        paths=read_csv(front / "top_impacted_paths.csv"),
        sensitivity=read_csv(front / "parameter_sensitivity_ranking.csv"),
        snapshots=read_csv(front / "network_snapshots.csv"),
    )
    bundle.prepare()
    bundle.figures_dir.mkdir(parents=True, exist_ok=True)
    bundle.snapshots_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[Path] = [
        render_core_metric_trends(bundle),
        render_demand_propagation_trends(bundle),
        render_timeline_overview(bundle),
        render_policy_comparison(bundle),
        render_supplier_network_trends(bundle),
        render_material_network_trends(bundle),
        render_bom_impact_paths(bundle),
        render_monthly_disrupted_nodes(bundle),
        render_propagation_duration_comparison(bundle),
        render_parameter_sensitivity_ranking(bundle),
    ]
    outputs.extend(render_network_snapshots(bundle, dashboard_data=dashboard_data))
    write_manifest(bundle, outputs)
    return outputs


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def numericize(frame: pd.DataFrame) -> None:
    non_numeric = {
        "date",
        "snapshot_date",
        "activate_date",
        "policy_profile",
        "policy_label",
        "scenario_id",
        "target_id",
        "final_product_id",
        "first_failure_date",
        "propagation_stop_date",
        "marker_name",
        "snapshot_name",
        "snapshot_title",
        "figure_file_name",
        "figure_path",
        "policy_type",
        "policy_type_name",
        "action",
        "target_type",
        "supplier_id",
        "strategy_role",
        "impact_dimension",
        "impact_level",
        "impact_status",
        "root_cause",
        "item_id",
        "path",
        "parameter_name",
    }
    for column in frame.columns:
        if column in non_numeric:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        original_notna = frame[column].notna()
        if original_notna.any() and converted[original_notna].isna().all():
            continue
        frame[column] = converted


def load_dashboard_data(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    prefix = "window.study04DynamicData = "
    if text.startswith(prefix):
        return json.loads(text[len(prefix) :].strip().rstrip(";"))
    return None


def apply_refined_theme() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#FFFFFF",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": COLORS["spine"],
            "axes.labelcolor": COLORS["muted"],
            "axes.titlecolor": COLORS["text"],
            "xtick.color": COLORS["muted"],
            "ytick.color": COLORS["muted"],
            "grid.color": COLORS["grid"],
            "grid.linestyle": "--",
            "grid.linewidth": 0.75,
            "axes.unicode_minus": False,
            "legend.frameon": True,
            "legend.facecolor": "#FFFFFF",
            "legend.edgecolor": COLORS["spine"],
            "savefig.facecolor": "#FFFFFF",
        }
    )


apply_refined_theme()


def style_axis(
    ax,
    title: str,
    ylabel: str | None = None,
    xlabel: str | None = None,
    *,
    grid_axis: str = "y",
    numeric_y: bool = True,
) -> None:
    ax.set_title(title, loc="left", pad=10, fontsize=13.5, fontweight="semibold", color=COLORS["text"])
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10.5, color=COLORS["muted"])
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10.5, color=COLORS["muted"])
    ax.grid(True, axis=grid_axis, alpha=0.82)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLORS["spine"])
    ax.spines["bottom"].set_color(COLORS["spine"])
    ax.tick_params(labelsize=9.5)
    if numeric_y:
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=False))


def add_header(fig, title: str, subtitle: str) -> None:
    fig.text(0.045, 0.982, title, ha="left", va="top", fontsize=20, fontweight="bold", color=COLORS["text"])
    fig.text(0.045, 0.932, subtitle, ha="left", va="top", fontsize=11.5, color=COLORS["muted"])


def finish(fig, path: Path, *, top: float = 0.89) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0.02, 0.02, 0.985, top))
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return path


def format_dates(ax) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.tick_params(axis="x", rotation=0)


def add_stage_bands(ax, markers: dict[str, pd.Timestamp]) -> None:
    impact_start = markers.get("t_start")
    policy_start = markers.get("t_policy_start")
    recovery = markers.get("t_recovery")
    if impact_start is not None and policy_start is not None:
        ax.axvspan(impact_start, policy_start, color="#FEF3C7", alpha=0.28, lw=0, zorder=0)
    if policy_start is not None and recovery is not None:
        ax.axvspan(policy_start, recovery, color="#DBEAFE", alpha=0.26, lw=0, zorder=0)
    ymin, ymax = ax.get_ylim()
    for idx, key in enumerate(("t_start", "t_supply_peak", "t_policy_start", "t_recovery")):
        date_value = markers.get(key)
        if date_value is None or pd.isna(date_value):
            continue
        ax.axvline(date_value, color="#94A3B8", linestyle=(0, (3, 2)), linewidth=1.0, alpha=0.78, zorder=1)
        ax.annotate(
            STAGE_LABELS[key],
            xy=(date_value, 0.94 - 0.11 * (idx % 2)),
            xycoords=("data", "axes fraction"),
            ha="center",
            va="top",
            fontsize=8.2,
            color=COLORS["muted"],
            bbox={"boxstyle": "round,pad=0.18", "fc": "#FFFFFF", "ec": "#CBD5E1", "alpha": 0.92},
            clip_on=True,
        )
    ax.set_ylim(ymin, ymax)


def legend_right(ax, *, fontsize: float = 9.0) -> None:
    ax.legend(loc="center left", bbox_to_anchor=(1.015, 0.5), fontsize=fontsize, frameon=True)


def legend_bottom(ax, *, ncol: int = 3, fontsize: float = 9.0) -> None:
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=ncol, fontsize=fontsize, frameon=False)


def plot_line(
    ax,
    data: pd.DataFrame,
    column: str,
    *,
    label: str,
    color: str,
    step: bool = False,
    linestyle: Any = "-",
    marker: str = "o",
    linewidth: float = 2.2,
    alpha: float = 1.0,
) -> None:
    if column not in data.columns or data.empty:
        return
    drawstyle = "steps-post" if step else "default"
    ax.plot(
        data["date"],
        data[column],
        label=label,
        color=color,
        linestyle=linestyle,
        linewidth=linewidth,
        marker=marker,
        markersize=3.2,
        markevery=max(1, len(data) // 8),
        drawstyle=drawstyle,
        alpha=alpha,
    )


def add_end_labels(ax, data: pd.DataFrame, specs: Iterable[tuple[str, str, str]], *, max_labels: int = 4) -> None:
    if data.empty or "date" not in data.columns:
        return
    last_x = data["date"].iloc[-1]
    y_min, y_max = ax.get_ylim()
    span = max(y_max - y_min, 1.0)
    used: list[float] = []
    shown = 0
    for column, label, color in specs:
        if column not in data.columns or shown >= max_labels:
            continue
        value = float(data[column].iloc[-1])
        y = value
        for used_y in used:
            if abs(y - used_y) < 0.055 * span:
                y += 0.07 * span
        y = min(max(y, y_min + 0.04 * span), y_max - 0.04 * span)
        used.append(y)
        value_text = f"{value:.0f}" if abs(value - round(value)) < 1e-6 else f"{value:.2f}"
        ax.annotate(
            f"{label} {value_text}",
            xy=(last_x, value),
            xytext=(-10, y - value),
            textcoords="offset points",
            ha="right",
            va="center",
            fontsize=8.5,
            color=color,
            bbox={"boxstyle": "round,pad=0.18", "fc": "#FFFFFF", "ec": color, "alpha": 0.88},
        )
        shown += 1


def render_core_metric_trends(bundle: RunBundle) -> Path:
    data = bundle.time_series.copy()
    markers = bundle.marker_map()
    fig, axes = plt.subplots(4, 1, figsize=(12.8, 9.6), sharex=True)
    add_header(
        fig,
        "核心指标趋势",
        f"{bundle.scene_label}：紧凑多子图展示服务水平、中断强度、关键节点与策略成本",
    )

    service_specs = [
        ("service_level", "产品服务水平", COLORS["service"]),
        ("demand_fulfillment_rate", "需求满足率", COLORS["demand"]),
        ("system_service_level", "系统服务水平", COLORS["system"]),
    ]
    for col, label, color in service_specs:
        plot_line(axes[0], data, col, label=label, color=color)
    style_axis(axes[0], "服务水平恢复轨迹", "服务水平")
    axes[0].set_ylim(-0.04, 1.08)
    add_stage_bands(axes[0], markers)
    add_end_labels(axes[0], data, service_specs, max_labels=3)
    legend_right(axes[0])

    impact_specs = [
        ("supply_unavailable_items", "供应不可用物料", COLORS["unavailable"]),
        ("supply_effective_unavailable_items", "有效不可用物料", COLORS["failed"]),
        ("fused_failed_items", "融合失败物料", COLORS["blocked"]),
    ]
    for col, label, color in impact_specs:
        plot_line(axes[1], data, col, label=label, color=color, step=True)
    style_axis(axes[1], "中断影响强度", "数量")
    add_stage_bands(axes[1], markers)
    add_end_labels(axes[1], data, impact_specs, max_labels=3)
    legend_right(axes[1])

    key_specs = [
        ("affected_key_items", "受影响关键物料", "#D97706"),
        ("failed_key_items", "失败关键物料", "#B91C1C"),
        ("disrupted_key_suppliers", "中断关键供应商", "#0F766E"),
        ("active_backup_switches", "激活备供切换", COLORS["backup"]),
        ("active_priority_repairs", "激活优先抢修", COLORS["repair"]),
    ]
    for col, label, color in key_specs:
        plot_line(axes[2], data, col, label=label, color=color, step=True, marker=".")
    style_axis(axes[2], "关键节点与策略动作", "数量")
    add_stage_bands(axes[2], markers)
    legend_right(axes[2], fontsize=8.5)

    plot_line(axes[3], data, "policy_cumulative_cost", label="累计策略成本", color=COLORS["cost"], step=True, marker=".")
    style_axis(axes[3], "策略累计成本", "成本", "日期")
    add_stage_bands(axes[3], markers)
    legend_right(axes[3])

    for ax in axes:
        format_dates(ax)
    return finish(fig, bundle.figures_dir / "core_metric_trends.png", top=0.88)


def render_demand_propagation_trends(bundle: RunBundle) -> Path:
    data = bundle.time_series.merge(bundle.network, on="date", how="left", suffixes=("", "_network"))
    markers = bundle.marker_map()
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 7.0), sharex=True)
    add_header(
        fig,
        "需求传播与下游阻断",
        f"{bundle.scene_label}：分层展示需求满足、积压损失与 BOM 下游阻断",
    )

    ax = axes[0]
    plot_line(ax, data, "demand_fulfillment_rate", label="需求满足率", color=COLORS["service"])
    plot_line(ax, data, "service_level", label="产品服务水平", color=COLORS["system"])
    ax2 = ax.twinx()
    plot_line(ax2, data, "total_backlog_demand", label="积压需求", color="#F59E0B", step=True, marker="s", linewidth=1.8)
    plot_line(ax2, data, "total_lost_demand", label="损失需求", color="#D62828", step=True, marker="^", linewidth=1.8)
    style_axis(ax, "需求满足与缺口", "比例")
    ax2.set_ylabel("需求量", fontsize=10.5, color=COLORS["muted"])
    ax2.tick_params(axis="y", labelsize=9.5, colors=COLORS["muted"])
    ax.set_ylim(-0.04, 1.08)
    add_stage_bands(ax, markers)
    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, labels + labels2, loc="center left", bbox_to_anchor=(1.08, 0.5), fontsize=9, frameon=True)

    block_specs = [
        ("material_blocked_nodes", "物料阻断", COLORS["material"]),
        ("assembly_blocked_nodes", "装配阻断", COLORS["blocked"]),
        ("product_blocked_nodes", "产品阻断", COLORS["system"]),
    ]
    for col, label, color in block_specs:
        plot_line(axes[1], data, col, label=label, color=color, step=True)
    style_axis(axes[1], "下游阻断节点", "节点数", "日期")
    add_stage_bands(axes[1], markers)
    legend_right(axes[1])

    for ax in axes:
        format_dates(ax)
    return finish(fig, bundle.figures_dir / "demand_propagation_trends.png", top=0.86)


def render_timeline_overview(bundle: RunBundle) -> Path:
    data = bundle.time_series.merge(bundle.network, on="date", how="left", suffixes=("", "_network"))
    markers = bundle.marker_map()
    fig, axes = plt.subplots(3, 1, figsize=(13.2, 9.0), sharex=True)
    add_header(
        fig,
        "恢复策略时间轴总览",
        f"{bundle.scene_label}：用阶段背景带串联冲击开始、峰值、策略启动与业务恢复",
    )

    for col, label, color in [
        ("service_level", "产品服务水平", COLORS["service"]),
        ("demand_fulfillment_rate", "需求满足率", COLORS["demand"]),
        ("system_service_level", "系统服务水平", COLORS["system"]),
    ]:
        plot_line(axes[0], data, col, label=label, color=color)
    axes[0].set_ylim(-0.04, 1.08)
    style_axis(axes[0], "服务水平变化", "服务水平")
    add_stage_bands(axes[0], markers)
    legend_right(axes[0])

    for col, label, color in [
        ("supplier_disrupted_nodes", "中断供应商", COLORS["unavailable"]),
        ("material_blocked_nodes", "阻断物料", COLORS["blocked"]),
        ("bom_edge_disrupted", "中断 BOM 边", "#D1495B"),
    ]:
        plot_line(axes[1], data, col, label=label, color=color, step=True)
    style_axis(axes[1], "冲击后变化", "数量")
    add_stage_bands(axes[1], markers)
    legend_right(axes[1])

    for col, label, color in [
        ("active_backup_switches", "激活备供切换", COLORS["backup"]),
        ("active_substitutions", "激活等效替代", COLORS["substitution"]),
        ("active_priority_repairs", "激活优先抢修", COLORS["repair"]),
    ]:
        plot_line(axes[2], data, col, label=label, color=color, step=True)
    ax_cost = axes[2].twinx()
    plot_line(ax_cost, data, "policy_cumulative_cost", label="累计策略成本", color=COLORS["cost"], step=True, marker=".", linewidth=2.5)
    style_axis(axes[2], "恢复动作时间线", "动作数量", "日期")
    ax_cost.set_ylabel("累计策略成本", fontsize=10.5, color=COLORS["muted"])
    ax_cost.tick_params(axis="y", labelsize=9.5, colors=COLORS["muted"])
    add_stage_bands(axes[2], markers)
    lines, labels = axes[2].get_legend_handles_labels()
    lines2, labels2 = ax_cost.get_legend_handles_labels()
    axes[2].legend(lines + lines2, labels + labels2, loc="center left", bbox_to_anchor=(1.12, 0.5), fontsize=9, frameon=True)

    for ax in axes:
        format_dates(ax)
    return finish(fig, bundle.figures_dir / "timeline_overview.png", top=0.88)


def render_policy_comparison(bundle: RunBundle) -> Path:
    data = bundle.policy_comparison.copy()
    output_path = bundle.figures_dir / "policy_comparison.png"
    if data.empty:
        return output_path
    markers = bundle.marker_map()
    panels = [
        ("total_interrupted_nodes", "全链中断节点总数"),
        ("supplier_disrupted_nodes", "供应商中断节点数"),
        ("downstream_interrupted_nodes", "下游阻断节点数"),
    ]
    existing_cols = [col for col, _ in panels if col in data.columns]
    ymax = max([float(pd.to_numeric(data[col], errors="coerce").max()) for col in existing_cols] + [1.0])
    fig, axes = plt.subplots(3, 1, figsize=(13.4, 9.2), sharex=True)
    add_header(
        fig,
        "不同恢复策略下中断节点数对比",
        f"{bundle.scene_label}：用阶梯折线比较不同策略组合压制中断节点的速度",
    )

    for ax, (col, title) in zip(axes, panels):
        for profile in POLICY_ORDER:
            part = data.loc[data["policy_profile"].astype(str).eq(profile)].sort_values("date")
            if part.empty:
                continue
            plot_line(
                ax,
                part,
                col,
                label=POLICY_LABELS.get(profile, str(part["policy_label"].iloc[0])),
                color=POLICY_COLORS.get(profile, "#64748B"),
                linestyle=POLICY_LINESTYLES.get(profile, "-"),
                step=True,
                marker=".",
                linewidth=2.2 if profile in {"time_priority_interrupt", "all_policies"} else 1.85,
            )
        style_axis(ax, title, "节点数")
        ax.set_ylim(-0.5, ymax * 1.12 + 0.5)
        add_stage_bands(ax, markers)
        format_dates(ax)
    axes[-1].set_xlabel("日期")
    legend_right(axes[1], fontsize=8.8)
    return finish(fig, output_path, top=0.88)


def render_supplier_network_trends(bundle: RunBundle) -> Path:
    data = bundle.network.copy()
    markers = bundle.marker_map()
    fig, axes = plt.subplots(2, 1, figsize=(12.8, 7.2), sharex=True)
    add_header(
        fig,
        "供应层状态演化",
        f"{bundle.scene_label}：突出供应商不可用、降级与供应网络边恢复过程",
    )

    ax = axes[0]
    if "supplier_disrupted_nodes" in data.columns:
        ax.fill_between(data["date"], data["supplier_disrupted_nodes"], color=COLORS["unavailable"], alpha=0.13, step="post")
    for col, label, color in [
        ("supplier_disrupted_nodes", "中断供应商", COLORS["unavailable"]),
        ("supplier_degraded_nodes", "降级供应商", COLORS["demand"]),
        ("supplier_available_nodes", "可用供应商", COLORS["available"]),
    ]:
        plot_line(ax, data, col, label=label, color=color, step=True)
    style_axis(ax, "供应商节点状态", "节点数")
    add_stage_bands(ax, markers)
    legend_right(ax)

    for col, label, color in [
        ("supplier_network_disrupted_edges", "中断供应关系边", COLORS["blocked"]),
        ("supplier_network_active_edges", "可用供应关系边", COLORS["backup"]),
    ]:
        plot_line(axes[1], data, col, label=label, color=color, step=True)
    style_axis(axes[1], "供应网络边状态", "边数", "日期")
    add_stage_bands(axes[1], markers)
    legend_right(axes[1])

    for ax in axes:
        format_dates(ax)
    return finish(fig, bundle.figures_dir / "supplier_network_trends.png", top=0.86)


def render_material_network_trends(bundle: RunBundle) -> Path:
    data = bundle.network.copy()
    markers = bundle.marker_map()
    fig, axes = plt.subplots(3, 1, figsize=(12.8, 8.4), sharex=True)
    add_header(
        fig,
        "物料网络状态演化",
        f"{bundle.scene_label}：按物料、装配、产品层级分面板展示受影响与阻断",
    )

    level_specs = [
        ("material", "物料层", COLORS["material"]),
        ("assembly", "装配层", COLORS["assembly"]),
        ("product", "产品层", COLORS["product"]),
    ]
    for ax, (prefix, title, color) in zip(axes, level_specs):
        blocked_col = f"{prefix}_blocked_nodes"
        affected_col = f"{prefix}_affected_nodes"
        available_col = f"{prefix}_available_nodes"
        if blocked_col in data.columns:
            ax.fill_between(data["date"], data[blocked_col], color=COLORS["blocked"], alpha=0.10, step="post")
        plot_line(ax, data, affected_col, label="受影响", color=color, step=True)
        plot_line(ax, data, blocked_col, label="阻断", color=COLORS["blocked"], step=True)
        plot_line(ax, data, available_col, label="可用", color="#94A3B8", step=True, linestyle="--", linewidth=1.6)
        style_axis(ax, title, "节点数")
        add_stage_bands(ax, markers)
        legend_right(ax, fontsize=8.6)
        format_dates(ax)
    axes[-1].set_xlabel("日期")
    return finish(fig, bundle.figures_dir / "material_network_trends.png", top=0.87)


def render_bom_impact_paths(bundle: RunBundle) -> Path:
    paths = bundle.paths.copy()
    fig, ax = plt.subplots(figsize=(13.6, 7.8))
    add_header(
        fig,
        "关键路径与物料清单影响链",
        f"{bundle.scene_label}：横向流程展示 Top 影响路径，弱化非关键路径噪声",
    )
    ax.set_axis_off()
    if paths.empty or "path" not in paths.columns:
        ax.text(0.5, 0.5, "暂无关键路径数据", ha="center", va="center", fontsize=14, color=COLORS["muted"])
        return finish(fig, bundle.figures_dir / "bom_impact_paths.png", top=0.86)

    top = paths.head(8).reset_index(drop=True)
    x_min, x_max = 0.12, 0.88
    row_gap = 0.09
    y_start = 0.82
    status_color = {
        "failed": COLORS["blocked"],
        "blocked": COLORS["blocked"],
        "unavailable": COLORS["unavailable"],
        "affected": COLORS["affected"],
        "degraded": COLORS["demand"],
        "backlog": COLORS["demand"],
    }
    for i, row in top.iterrows():
        y = y_start - i * row_gap
        nodes = [item.strip() for item in str(row.get("path", "")).split("->") if item.strip()]
        if not nodes:
            continue
        draw_nodes = nodes[:4] + [nodes[-1]] if len(nodes) > 5 else nodes
        xs = np.linspace(x_min, x_max, len(draw_nodes))
        color = status_color.get(str(row.get("impact_status", "")).lower(), COLORS["affected"])
        ax.text(0.025, y, f"{i + 1}", ha="center", va="center", fontsize=10, color="#FFFFFF", bbox={"boxstyle": "circle", "fc": color, "ec": color})
        ax.text(0.050, y, translate_impact_level(str(row.get("impact_level", "路径"))), ha="left", va="center", fontsize=9.5, color=COLORS["muted"])
        for j, (x, node) in enumerate(zip(xs, draw_nodes)):
            ax.scatter([x], [y], s=520 if j in {0, len(draw_nodes) - 1} else 430, color="#FFFFFF", edgecolor=color, linewidth=2.0, zorder=3)
            ax.text(x, y, node, ha="center", va="center", fontsize=8.6, fontweight="semibold", color=COLORS["text"], zorder=4)
            if j < len(xs) - 1:
                ax.annotate("", xy=(xs[j + 1] - 0.035, y), xytext=(x + 0.035, y), arrowprops={"arrowstyle": "->", "color": "#94A3B8", "lw": 1.35})
        ax.text(0.925, y, translate_status(str(row.get("impact_status", "-"))), ha="left", va="center", fontsize=9.2, color=color, fontweight="semibold")
    ax.text(x_min, 0.93, "源节点", ha="center", fontsize=10, color=COLORS["muted"])
    ax.text(0.50, 0.93, "中间 BOM 传导", ha="center", fontsize=10, color=COLORS["muted"])
    ax.text(x_max, 0.93, "最终影响", ha="center", fontsize=10, color=COLORS["muted"])
    return finish(fig, bundle.figures_dir / "bom_impact_paths.png", top=0.87)


def render_monthly_disrupted_nodes(bundle: RunBundle) -> Path:
    data = bundle.network.copy()
    data["month"] = data["date"].dt.strftime("%Y-%m")
    total_cols = ["supplier_disrupted_nodes", "material_blocked_nodes", "assembly_blocked_nodes", "product_blocked_nodes"]
    data["total_interrupted"] = data[[col for col in total_cols if col in data.columns]].sum(axis=1)
    monthly = data.groupby("month", as_index=False).agg(
        peak_interrupted=("total_interrupted", "max"),
        mean_interrupted=("total_interrupted", "mean"),
    )
    fig, ax = plt.subplots(figsize=(10.6, 5.8))
    add_header(fig, "月度中断节点分布", f"{bundle.scene_label}：柱线组合展示月度峰值与平均中断水平")
    x = np.arange(len(monthly))
    bars = ax.bar(x, monthly["peak_interrupted"], width=0.46, color=COLORS["bar"], alpha=0.88, label="月度峰值")
    ax.plot(x, monthly["mean_interrupted"], color=COLORS["text"], marker="o", linewidth=2.0, label="月度平均")
    for bar, value in zip(bars, monthly["peak_interrupted"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.35, f"峰值 {value:.0f}", ha="center", va="bottom", fontsize=9.2, color=COLORS["text"])
    ax.set_xticks(x)
    ax.set_xticklabels(monthly["month"].tolist())
    style_axis(ax, "月度节点中断峰值", "节点数", "月份")
    legend_bottom(ax, ncol=2)
    return finish(fig, bundle.figures_dir / "monthly_disrupted_nodes.png", top=0.82)


def render_propagation_duration_comparison(bundle: RunBundle) -> Path:
    output_path = bundle.figures_dir / "propagation_duration_comparison.png"
    if bundle.summary.empty:
        return output_path
    row = bundle.summary.iloc[0]
    labels = ["供应商层", "物料层", "装配层", "产品层"]
    cols = [
        "supplier_propagation_duration_months",
        "material_propagation_duration_months",
        "assembly_propagation_duration_months",
        "product_propagation_duration_months",
    ]
    values = [float(row.get(col, 0) or 0) for col in cols]
    fig, ax = plt.subplots(figsize=(10.6, 5.8))
    add_header(fig, "传播持续时间对比", f"{bundle.scene_label}：水平条形图展示各网络层传播持续月数")
    y = np.arange(len(labels))
    colors = [COLORS["supplier"], COLORS["material"], COLORS["assembly"], COLORS["product"]]
    ax.barh(y, values, color=colors, alpha=0.88, height=0.48)
    for yi, value in zip(y, values):
        ax.text(value + 0.05, yi, f"{value:.0f} 个月", va="center", ha="left", fontsize=10, color=COLORS["text"])
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(values + [1]) + 0.8)
    style_axis(ax, "分层传播持续时间", "网络层级", "持续月数", grid_axis="x", numeric_y=False)
    return finish(fig, output_path, top=0.82)


def render_parameter_sensitivity_ranking(bundle: RunBundle) -> Path:
    output_path = bundle.figures_dir / "parameter_sensitivity_ranking.png"
    data = bundle.sensitivity.copy()
    if data.empty:
        return output_path
    data = data.sort_values("sensitivity_score", ascending=False).head(8).iloc[::-1]
    labels = [translate_parameter_name(str(value)) for value in data["parameter_name"]]
    scores = data["sensitivity_score"].astype(float)
    fig, ax = plt.subplots(figsize=(11.0, 6.2))
    add_header(fig, "参数敏感度排序", f"{bundle.scene_label}：按综合敏感度保留 Top 8 参数")
    median = scores.median()
    colors = ["#0F766E" if value >= median else "#94A3B8" for value in scores]
    ax.barh(labels, scores, color=colors, alpha=0.92, height=0.52)
    for y, value in enumerate(scores):
        ax.text(value + scores.max() * 0.02, y, f"{value:.2f}", va="center", fontsize=9.6, color=COLORS["text"])
    ax.set_xlim(0, scores.max() * 1.18 if scores.max() > 0 else 1.0)
    style_axis(ax, "综合敏感度", "参数", "敏感度得分", grid_axis="x", numeric_y=False)
    return finish(fig, output_path, top=0.82)


def render_network_snapshots(bundle: RunBundle, *, dashboard_data: dict[str, Any] | None) -> list[Path]:
    if dashboard_data is None:
        return []
    scene = dashboard_data.get("scenes", {}).get(bundle.family)
    if not scene:
        return []
    network = scene.get("interactive_network") or {}
    nodes = network.get("nodes") or []
    edges = network.get("edges") or []
    states = network.get("daily_states") or []
    if not nodes or not edges or not states or bundle.snapshots.empty:
        return []

    state_by_date = {str(state.get("date")): state for state in states}
    positions = refined_network_positions(nodes)
    outputs: list[Path] = []
    for row in bundle.snapshots.itertuples(index=False):
        snapshot_name = str(getattr(row, "snapshot_name", "snapshot"))
        snapshot_date = pd.Timestamp(getattr(row, "snapshot_date")).date().isoformat()
        state = state_by_date.get(snapshot_date) or nearest_state(states, snapshot_date)
        title = str(getattr(row, "snapshot_title", STAGE_LABELS.get(snapshot_name, snapshot_name)))
        file_name = str(getattr(row, "figure_file_name", f"{snapshot_name}_network.png"))
        outputs.append(
            render_single_network_snapshot(
                bundle,
                nodes=nodes,
                edges=edges,
                positions=positions,
                state=state,
                snapshot_name=snapshot_name,
                title=title,
                output_path=bundle.snapshots_dir / file_name,
            )
        )
    return outputs


def refined_network_positions(nodes: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {"supplier": [], "material": [], "assembly": [], "part": [], "product": []}
    for node in nodes:
        node_type = str(node.get("node_type") or "material")
        grouped.setdefault(node_type, []).append(node)
    for values in grouped.values():
        values.sort(key=lambda item: str(item.get("entity_id") or item.get("node_key")))

    positions: dict[str, tuple[float, float]] = {}
    supplier_cols = [0.17, 0.34, 0.51]
    suppliers = grouped.get("supplier", [])
    rows = math.ceil(max(len(suppliers), 1) / len(supplier_cols))
    for idx, node in enumerate(suppliers):
        col = idx % len(supplier_cols)
        row = idx // len(supplier_cols)
        y = 0.11 + (rows - 1 - row) * (0.31 / max(rows - 1, 1))
        positions[str(node["node_key"])] = (supplier_cols[col], y)

    layer_specs = [
        ("material", 0.18, 0.58),
        ("assembly", 0.54, 0.62),
        ("part", 0.72, 0.58),
        ("product", 0.88, 0.62),
    ]
    for node_type, x, center_y in layer_specs:
        values = grouped.get(node_type, [])
        count = len(values)
        if not count:
            continue
        span = min(0.55, 0.045 * max(count - 1, 1))
        for idx, node in enumerate(values):
            y = center_y + span / 2 - idx * (span / max(count - 1, 1) if count > 1 else 0)
            positions[str(node["node_key"])] = (x, y)
    return positions


def nearest_state(states: list[dict[str, Any]], date_value: str) -> dict[str, Any]:
    target = pd.Timestamp(date_value)
    return min(states, key=lambda payload: abs(pd.Timestamp(payload.get("date")) - target))


def render_single_network_snapshot(
    bundle: RunBundle,
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    positions: dict[str, tuple[float, float]],
    state: dict[str, Any],
    snapshot_name: str,
    title: str,
    output_path: Path,
) -> Path:
    fig, ax = plt.subplots(figsize=(14.2, 8.2))
    ax.set_axis_off()
    node_status = state.get("node_status", {})
    edge_status = state.get("edge_status", {})
    date_text = state.get("date", "")
    add_header(
        fig,
        f"{clean_snapshot_title(title)}（{date_text}）",
        f"{bundle.scene_label}：解释型网络快照，弱化全局结构，突出当前阶段传播路径与恢复动作",
    )

    for edge in edges:
        source = str(edge.get("source_key"))
        target = str(edge.get("target_key"))
        if source not in positions or target not in positions:
            continue
        status = str(edge_status.get(str(edge.get("edge_key")), "active"))
        edge_type = str(edge.get("edge_type"))
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        color, alpha, linewidth, linestyle, directed = edge_style(edge_type, status, snapshot_name)
        if directed:
            arrow = mpatches.FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=7.5,
                linewidth=linewidth,
                linestyle=linestyle,
                color=color,
                alpha=alpha,
                shrinkA=7,
                shrinkB=7,
                zorder=1,
            )
            ax.add_patch(arrow)
        else:
            ax.plot([x1, x2], [y1, y2], color=color, alpha=alpha, linewidth=linewidth, linestyle=linestyle, zorder=1)

    for node in nodes:
        key = str(node.get("node_key"))
        if key not in positions:
            continue
        x, y = positions[key]
        status = str(node_status.get(key, "available"))
        draw_refined_node(ax, node, x, y, status)

    for x, y, text in [
        (0.34, 0.035, "供应商网络"),
        (0.18, 0.910, "原材料"),
        (0.54, 0.910, "装配/零件"),
        (0.88, 0.910, "产品"),
    ]:
        ax.text(x, y, text, ha="center", va="center", fontsize=10.5, color=COLORS["muted"], bbox={"boxstyle": "round,pad=0.25", "fc": "#F8FAFC", "ec": "#E2E8F0"})
    ax.text(0.02, 0.955, stage_caption(snapshot_name), ha="left", va="top", fontsize=11, color=COLORS["text"], bbox={"boxstyle": "round,pad=0.35", "fc": "#FFFFFF", "ec": "#CBD5E1"})
    add_network_legend(ax)
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    return finish(fig, output_path, top=0.88)


def edge_style(edge_type: str, status: str, snapshot_name: str) -> tuple[str, float, float, Any, bool]:
    if status == "backup_active":
        return COLORS["backup"], 0.86, 1.8, "-", True
    if status == "substituted":
        return COLORS["substitution"], 0.86, 1.8, (0, (4, 2)), True
    if status == "disrupted":
        if edge_type == "supplier_network":
            alpha = 0.20 if snapshot_name in {"t_start", "t_supply_peak"} else 0.10
            return COLORS["blocked"], alpha, 0.65, (0, (1.2, 2.4)), False
        alpha = 0.62 if snapshot_name in {"t_start", "t_supply_peak"} else 0.34
        return COLORS["blocked"], alpha, 1.15, (0, (1.5, 2.2)), True
    if edge_type == "supplier_network":
        return "#64748B", 0.13, 0.78, "--", False
    if edge_type == "supplier_item_map":
        return "#94A3B8", 0.16, 0.82, "-", False
    return "#94A3B8", 0.18, 0.86, "-", False


def draw_refined_node(ax, node: dict[str, Any], x: float, y: float, status: str) -> None:
    node_type = str(node.get("node_type"))
    is_key = bool(node.get("is_key_node"))
    entity = str(node.get("entity_id") or "")
    fill = {
        "available": "#FFFFFF",
        "affected": "#FEF3C7",
        "degraded": "#FEF3C7",
        "blocked": "#FEE2E2",
        "disrupted": "#FEE2E2",
    }.get(status, "#FFFFFF")
    edge = {
        "available": COLORS["available"],
        "affected": COLORS["affected"],
        "degraded": COLORS["demand"],
        "blocked": COLORS["unavailable"],
        "disrupted": COLORS["unavailable"],
    }.get(status, "#64748B")
    if is_key:
        edge = COLORS["key"]
    marker = {"supplier": "o", "material": "s", "assembly": "D", "part": "D", "product": "^"}.get(node_type, "o")
    size = 230 if node_type == "supplier" else 265
    ax.scatter([x], [y], s=size, marker=marker, facecolor=fill, edgecolor=edge, linewidth=2.5 if is_key else 1.35, zorder=4)
    ax.text(x, y - 0.022, entity, ha="center", va="top", fontsize=7.6, color=COLORS["text"], fontweight="semibold", zorder=5)


def add_network_legend(ax) -> None:
    handles = [
        mlines.Line2D([], [], color=COLORS["blocked"], linestyle=(0, (1.5, 2.2)), label="中断传播边"),
        mlines.Line2D([], [], color=COLORS["backup"], label="备供切换边"),
        mlines.Line2D([], [], color=COLORS["substitution"], linestyle=(0, (4, 2)), label="等效替代边"),
        mlines.Line2D([], [], color="#94A3B8", label="普通关系边"),
        mlines.Line2D([], [], marker="o", linestyle="", markerfacecolor="#FEE2E2", markeredgecolor=COLORS["unavailable"], label="中断/阻断节点"),
        mlines.Line2D([], [], marker="o", linestyle="", markerfacecolor="#FFFFFF", markeredgecolor=COLORS["key"], label="关键节点边框"),
    ]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.52), fontsize=9, frameon=True)


def clean_snapshot_title(value: str) -> str:
    return value.replace("网络快照", "").strip()


def stage_caption(snapshot_name: str) -> str:
    return {
        "t0": "全局结构版：保留完整网络，普通关系弱化。",
        "t_start": "初始冲击版：突出冲击源与刚被波及的传播边。",
        "t_supply_peak": "传播峰值版：突出当前最强冲击路径。",
        "t_policy_start": "恢复动作版：突出备供切换、等效替代和抢修动作。",
        "t_recovery": "恢复结果版：突出仍未恢复与已缓解区域。",
    }.get(snapshot_name, "阶段快照：突出当前阶段主导变化。")


def translate_parameter_name(value: str) -> str:
    return {
        "backup_coverage": "备供覆盖率",
        "priority_repair_days": "优先抢修天数",
        "priority_repair_lead_days": "优先抢修提前量",
        "backup_switch_time_days": "备供切换耗时",
        "substitution_availability": "等效替代可用率",
    }.get(value, value)


def translate_impact_level(value: str) -> str:
    return {
        "supplier": "供应商",
        "material": "物料",
        "assembly": "装配",
        "part": "零件",
        "product": "产品",
    }.get(value, value)


def translate_status(value: str) -> str:
    return {
        "failed": "失败",
        "blocked": "阻断",
        "unavailable": "不可用",
        "affected": "受影响",
        "degraded": "降级",
        "backlog": "积压",
    }.get(value, value)


def write_manifest(bundle: RunBundle, outputs: list[Path]) -> None:
    rows = []
    for path in outputs:
        rows.append(
            {
                "figure_name": path.name,
                "figure_path": str(path),
                "category": "network_snapshot" if path.parent.name == "network_snapshots" else "figure",
                "source_run_dir": str(bundle.source_run_dir),
                "source": "refined_output_renderer",
            }
        )
    manifest = bundle.scene_output_dir / "refined_manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["figure_name", "figure_path", "category", "source_run_dir", "source"],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
