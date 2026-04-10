from __future__ import annotations

from pathlib import Path

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
import networkx as nx
import pandas as pd

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.graph_export import build_export_graph
from supply_disruption_sim.viz.network_trend_plot import build_snapshot_summary
from supply_disruption_sim.viz.plot_theme import finish_figure, font_props
from supply_disruption_sim.viz.state_colormap import (
    edge_color_for_status,
    edge_style_for_status,
    edge_width_for_status,
    node_color_for_visual_status,
    node_shape_for_type,
)


NODE_EDGE_COLOR = "#22313F"
KEY_NODE_EDGE_COLOR = "#DB2777"
EDGE_ALPHA = {
    "active": 0.72,
    "backup_active": 0.96,
    "standby": 0.68,
    "substituted": 0.92,
    "disrupted": 0.95,
}


def _history_column(frame: pd.DataFrame, preferred: str, fallback: str) -> pd.Series:
    if preferred in frame:
        return pd.to_numeric(frame[preferred], errors="coerce").fillna(0)
    return pd.to_numeric(frame.get(fallback, 0), errors="coerce").fillna(0)


def export_network_snapshots(result: SimulationResult, output_dir: str | Path) -> list[Path]:
    if result.model_bundle is None or not result.network_snapshots:
        return []

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    graph, positions = build_export_graph(result.model_bundle)
    snapshot_specs = select_snapshot_points(result)
    rendered_paths: list[Path] = []
    for label, snapshot in snapshot_specs.items():
        figure_path = output_path / f"{label}_network.png"
        render_network_snapshot(
            graph=graph,
            positions=positions,
            snapshot=snapshot,
            figure_path=figure_path,
            title=f"{label.upper()} 网络快照",
        )
        rendered_paths.append(figure_path)
    return rendered_paths


def select_snapshot_points(result: SimulationResult) -> dict[str, dict]:
    snapshots_by_date = {
        str(snapshot["date"].date() if hasattr(snapshot["date"], "date") else snapshot["date"]): snapshot
        for snapshot in result.network_snapshots
    }
    history = result.history.copy()
    history["date_str"] = pd.to_datetime(history["date"]).dt.date.astype(str)
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
        _history_column(peak_history, "supply_effective_degraded_items", "supply_degraded_items")
        + _history_column(peak_history, "supply_effective_unavailable_items", "supply_unavailable_items")
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
            & (_history_column(history_after_peak, "supply_effective_degraded_items", "supply_degraded_items") <= 0.0)
            & (pd.to_numeric(history_after_peak.get("supply_affected_products", 0.0), errors="coerce").fillna(0.0) <= 0.0)
        ]
    t_recovery = (
        recovery_candidates.iloc[0]["date_str"]
        if not recovery_candidates.empty
        else history.iloc[-1]["date_str"]
    )
    ordered = {
        "t0": snapshots_by_date.get(t0),
        "t_start": snapshots_by_date.get(t_start, snapshots_by_date.get(t0)),
        "t_peak": snapshots_by_date.get(t_peak, snapshots_by_date.get(t0)),
        "t_recovery": snapshots_by_date.get(t_recovery, snapshots_by_date.get(t_peak, snapshots_by_date.get(t0))),
    }
    return {label: snapshot for label, snapshot in ordered.items() if snapshot is not None}


def render_network_snapshot(
    *,
    graph: nx.DiGraph,
    positions: dict[str, tuple[float, float]],
    snapshot: dict,
    figure_path: Path,
    title: str,
) -> None:
    fig = plt.figure(figsize=(25.0, 15.8))
    ax = fig.add_axes([0.10, 0.11, 0.73, 0.73])
    node_legend_ax = fig.add_axes([0.83, 0.56, 0.14, 0.22])
    status_legend_ax = fig.add_axes([0.83, 0.28, 0.14, 0.26])
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    node_legend_ax.set_facecolor("#FFFFFF")
    status_legend_ax.set_facecolor("#FFFFFF")
    ax.axis("off")
    node_legend_ax.axis("off")
    status_legend_ax.axis("off")

    summary = build_snapshot_summary(snapshot)
    _draw_header(fig=fig, title=title, snapshot=snapshot, summary=summary)
    _draw_structure_notes(fig=fig)

    edge_state = snapshot.get("edge_state", {})
    grouped_edges: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for source, target, data in graph.edges(data=True):
        edge_key = data["edge_key"]
        state = str(edge_state.get(edge_key, {}).get("status", "active"))
        style = edge_style_for_status(state)
        color = edge_color_for_status(state)
        grouped_edges.setdefault((state, style, color), []).append((source, target))

    for (state_name, style, color), edge_list in grouped_edges.items():
        nx.draw_networkx_edges(
            graph,
            positions,
            edgelist=edge_list,
            edge_color=color,
            style=style,
            width=edge_width_for_status(state_name) * 1.22,
            alpha=EDGE_ALPHA.get(state_name, 0.65),
            ax=ax,
            arrows=False,
        )

    node_state = snapshot.get("node_state", {})
    for node_type in ["supplier", "material", "part", "assembly", "product"]:
        node_keys = [node_key for node_key, data in graph.nodes(data=True) if data["node_type"] == node_type]
        if not node_keys:
            continue
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=node_keys,
            node_color=[
                node_color_for_visual_status(node_state.get(node_key, {}).get("visual_status", "stable"))
                for node_key in node_keys
            ],
            node_shape=node_shape_for_type(node_type),
            node_size=[_node_size(node_key=node_key, node_type=node_type, snapshot=snapshot) for node_key in node_keys],
            edgecolors=NODE_EDGE_COLOR,
            linewidths=[_node_line_width(node_key=node_key, snapshot=snapshot) for node_key in node_keys],
            alpha=0.98,
            ax=ax,
        )
        key_node_keys = [node_key for node_key in node_keys if bool(node_state.get(node_key, {}).get("is_key_node", False))]
        if key_node_keys:
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=key_node_keys,
                node_color="none",
                node_shape=node_shape_for_type(node_type),
                node_size=[
                    _node_size(node_key=node_key, node_type=node_type, snapshot=snapshot) * 1.24
                    for node_key in key_node_keys
                ],
                edgecolors=KEY_NODE_EDGE_COLOR,
                linewidths=3.8,
                alpha=1.0,
                ax=ax,
            )

    _draw_all_labels(ax=ax, graph=graph, positions=positions, snapshot=snapshot)
    _draw_legends(node_legend_ax=node_legend_ax, status_legend_ax=status_legend_ax)
    _configure_axes_bounds(ax=ax, positions=positions)
    finish_figure(fig, figure_path, top=0.91, facecolor="#FFFFFF", tight=False)


def _draw_header(*, fig, title: str, snapshot: dict, summary: dict[str, int]) -> None:
    date_text = str(pd.Timestamp(snapshot["date"]).date())
    fig.text(
        0.045,
        0.982,
        f"{title}（{date_text}）",
        ha="left",
        va="top",
        color="#111827",
        fontproperties=font_props(size=22, weight="bold"),
    )
    fig.text(
        0.045,
        0.948,
        (
            f"供应商中断 {summary['supplier_disrupted_nodes']}，降级 {summary['supplier_degraded_nodes']} ｜ "
            f"物料受影响 {summary['material_affected_nodes']}，阻断 {summary['material_blocked_nodes']} ｜ "
            f"装配受影响 {summary['assembly_affected_nodes']} ｜ "
            f"产品受影响 {summary['product_affected_nodes']} ｜ "
            f"中断边：{summary['supply_edge_disrupted'] + summary['bom_edge_disrupted']}"
        ),
        ha="left",
        va="top",
        color="#111827",
        fontproperties=font_props(size=16),
    )


def _draw_structure_notes(*, fig) -> None:
    note_style = {
        "facecolor": "#FFFFFF",
        "edgecolor": "#CBD5E1",
        "boxstyle": "round,pad=0.28",
        "alpha": 0.98,
    }
    text_style = font_props(size=13) or {}
    fig.text(0.205, 0.865, "上游：BOM 网络（从左到右）", ha="left", va="center", color="#475569", bbox=note_style, **text_style)
    fig.text(0.02, 0.54, "中部：物料-供应商映射关系", ha="left", va="center", color="#475569", bbox=note_style, **text_style)
    fig.text(0.02, 0.17, "下部：供应商网络", ha="left", va="center", color="#475569", bbox=note_style, **text_style)
    fig.text(0.84, 0.23, "供应关系映射按表显示当前/备用来源", ha="left", va="center", color="#475569", bbox=note_style, **text_style)


def _draw_all_labels(*, ax, graph: nx.DiGraph, positions: dict[str, tuple[float, float]], snapshot: dict) -> None:
    node_state = snapshot.get("node_state", {})
    for node_key, (x_coord, y_coord) in sorted(positions.items(), key=lambda item: (item[1][1], item[1][0])):
        visual_status = str(node_state.get(node_key, {}).get("visual_status", "stable"))
        text_color = "#FFFFFF" if visual_status in {"disrupted", "blocked"} else "#111827"
        node_type = str(graph.nodes[node_key].get("node_type", "item"))
        font_size = 11.6 if node_type in {"material", "part", "assembly", "product"} else 10.8
        path_effects = [pe.withStroke(linewidth=2.4, foreground="#FFFFFF", alpha=0.95)]
        if text_color == "#FFFFFF":
            path_effects = [pe.withStroke(linewidth=2.8, foreground="#22313F", alpha=0.95)]
        ax.text(
            x_coord,
            y_coord,
            str(graph.nodes[node_key].get("entity_id", node_key.split(":", 1)[-1])),
            ha="center",
            va="center",
            color=text_color,
            zorder=6,
            clip_on=False,
            fontproperties=font_props(size=font_size, weight="semibold"),
            path_effects=path_effects,
        )


def _draw_legends(*, node_legend_ax, status_legend_ax) -> None:
    node_type_handles = [
        Line2D([0], [0], marker="o", color="w", label="供应商", markerfacecolor="#7F8C8D", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.5, markersize=16),
        Line2D([0], [0], marker="s", color="w", label="物料", markerfacecolor="#7F8C8D", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.5, markersize=16),
        Line2D([0], [0], marker="D", color="w", label="装配件", markerfacecolor="#7F8C8D", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.5, markersize=16),
        Line2D([0], [0], marker="^", color="w", label="产品", markerfacecolor="#7F8C8D", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.5, markersize=16),
        Line2D([0], [0], marker="o", color="w", label="关键节点", markerfacecolor="none", markeredgecolor=KEY_NODE_EDGE_COLOR, markeredgewidth=3.8, markersize=18),
    ]
    state_handles = [
        Line2D([0], [0], marker="o", color="w", label="可用", markerfacecolor="#2E8B57", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.4, markersize=16),
        Line2D([0], [0], marker="o", color="w", label="降级/受影响", markerfacecolor="#F0AD4E", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.4, markersize=16),
        Line2D([0], [0], marker="o", color="w", label="中断/阻断", markerfacecolor="#D9534F", markeredgecolor=NODE_EDGE_COLOR, markeredgewidth=1.4, markersize=16),
        Line2D([0], [0], color="#9AA9BA", lw=3.0, linestyle="dashed", label="备用/待命边"),
        Line2D([0], [0], color="#4A90E2", lw=3.2, label="备用已激活"),
        Line2D([0], [0], color="#8E44AD", lw=3.0, linestyle="dashdot", label="已替代"),
        Line2D([0], [0], color="#D9534F", lw=3.0, linestyle="dotted", label="中断边"),
    ]
    legend_style = {
        "frameon": True,
        "facecolor": "#FFFFFF",
        "edgecolor": "#CBD5E1",
        "framealpha": 0.96,
        "borderpad": 0.55,
        "labelspacing": 0.62,
        "handlelength": 2.3,
        "prop": font_props(size=14),
    }
    first_legend = node_legend_ax.legend(
        handles=node_type_handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        title="节点类型",
        title_fontproperties=font_props(size=15, weight="bold"),
        **legend_style,
    )
    node_legend_ax.add_artist(first_legend)
    status_legend_ax.legend(
        handles=state_handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        title="状态",
        title_fontproperties=font_props(size=15, weight="bold"),
        **legend_style,
    )


def _node_size(*, node_key: str, node_type: str, snapshot: dict) -> float:
    node_state = snapshot.get("node_state", {}).get(node_key, {})
    if node_type == "supplier":
        return 940.0 if bool(node_state.get("is_key_node", False)) else 840.0
    if node_type == "product":
        return 1020.0
    if node_type == "assembly":
        return 950.0
    return 900.0


def _node_line_width(*, node_key: str, snapshot: dict) -> float:
    node_state = snapshot.get("node_state", {}).get(node_key, {})
    return 2.4 if bool(node_state.get("is_key_node", False)) else 1.6


def _configure_axes_bounds(*, ax, positions: dict[str, tuple[float, float]]) -> None:
    x_values = [coords[0] for coords in positions.values()]
    y_values = [coords[1] for coords in positions.values()]
    x_span = max(x_values) - min(x_values)
    y_span = max(y_values) - min(y_values)
    x_padding = max(0.95, x_span * 0.045)
    y_padding = max(0.95, y_span * 0.055)
    ax.set_xlim(min(x_values) - x_padding, max(x_values) + x_padding)
    ax.set_ylim(min(y_values) - y_padding, max(y_values) + y_padding)
