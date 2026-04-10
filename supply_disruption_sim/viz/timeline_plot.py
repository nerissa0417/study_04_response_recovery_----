from __future__ import annotations

from pathlib import Path

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.font_config import configure_matplotlib_chinese_font


CHINESE_FONT_NAME = configure_matplotlib_chinese_font()


def export_timeline_plot(result: SimulationResult, figure_path: str | Path) -> Path | None:
    if result.history.empty:
        return None

    output_path = Path(figure_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    history = result.history.copy()
    history["date"] = pd.to_datetime(history["date"])

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

    _plot_service_panel(axes[0], history, result)
    _plot_disruption_panel(axes[1], history, result)
    _plot_policy_panel(axes[2], history, result)

    axes[2].set_xlabel("日期")
    fig.suptitle(f"统一时间轴图：{result.scenario.scenario_id}", fontsize=14)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _plot_service_panel(ax, history: pd.DataFrame, result: SimulationResult) -> None:
    ax.plot(history["date"], history["service_level"], color="#0F6F5C", linewidth=2, label="产品服务水平")
    if "demand_fulfillment_rate" in history:
        ax.plot(history["date"], history["demand_fulfillment_rate"], color="#E09F3E", linewidth=1.8, label="需求满足率")
    if "system_service_level" in history:
        ax.plot(history["date"], history["system_service_level"], color="#5C80BC", linewidth=1.8, label="系统服务水平")
    ax.axvline(result.scenario.start_date.normalize(), color="#D9534F", linestyle="--", linewidth=1.2, label="场景开始")
    ax.set_ylabel("服务水平")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", prop=_font_props())


def _plot_disruption_panel(ax, history: pd.DataFrame, result: SimulationResult) -> None:
    if "supply_effective_unavailable_items" in history:
        ax.plot(history["date"], history["supply_effective_unavailable_items"], color="#C8553D", linewidth=2, label="供应不可用物料")
    if "total_backlog_demand" in history:
        ax.plot(history["date"], history["total_backlog_demand"], color="#F6BD60", linewidth=2, label="积压需求")
    if "fused_failed_items" in history:
        ax.plot(history["date"], history["fused_failed_items"], color="#6A040F", linewidth=2, label="融合失败物料")
    ax.axvline(result.scenario.start_date.normalize(), color="#D9534F", linestyle="--", linewidth=1.2)
    ax.set_ylabel("影响强度")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", prop=_font_props())


def _plot_policy_panel(ax, history: pd.DataFrame, result: SimulationResult) -> None:
    if "policy_cumulative_cost" in history:
        ax.plot(history["date"], history["policy_cumulative_cost"], color="#7A4EAB", linewidth=2, label="累计策略成本")
    if "active_priority_repairs" in history:
        ax.plot(history["date"], history["active_priority_repairs"], color="#2A6F97", linewidth=1.8, label="激活修复数")
    if "active_backup_switches" in history:
        ax.plot(history["date"], history["active_backup_switches"], color="#5FA8D3", linewidth=1.8, label="激活备用切换数")
    if result.policy_events:
        event_dates = pd.to_datetime(pd.DataFrame(result.policy_events)["date"])
        event_levels = [history["policy_cumulative_cost"].max() * 0.05 if "policy_cumulative_cost" in history else 1] * len(event_dates)
        ax.scatter(event_dates, event_levels, color="#111827", s=22, label="策略事件")
    ax.axvline(result.scenario.start_date.normalize(), color="#D9534F", linestyle="--", linewidth=1.2)
    ax.set_ylabel("策略活动")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", prop=_font_props())


def _font_props() -> dict | None:
    if CHINESE_FONT_NAME is None:
        return None
    return {"family": CHINESE_FONT_NAME}
