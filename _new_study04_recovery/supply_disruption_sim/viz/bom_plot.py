from __future__ import annotations

from pathlib import Path

import matplotlib


matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
import networkx as nx

from supply_disruption_sim.types import SimulationResult
from supply_disruption_sim.viz.plot_theme import THEME, add_figure_header, finish_figure, font_props


DIMENSION_STYLES = {
    "fusion": {"color": "#C8553D", "label": "融合影响"},
    "supply": {"color": "#2A6F97", "label": "供应影响"},
    "demand": {"color": "#E09F3E", "label": "需求影响"},
}

LEVEL_STYLES = {
    "material": {"shape": "s", "color": "#F6BD60", "label": "原材料"},
    "part": {"shape": "o", "color": "#84A59D", "label": "零件"},
    "assembly": {"shape": "D", "color": "#F28482", "label": "装配"},
    "product": {"shape": "^", "color": "#5C80BC", "label": "产品"},
}

LEVEL_ORDER = ["material", "part", "assembly", "product"]
LEVEL_X = {
    "material": 1.4,
    "part": 5.8,
    "assembly": 10.2,
    "product": 14.6,
}
SAME_LEVEL_X_OFFSET = 1.15

NODE_SIZE_BY_LEVEL = {
    "material": 980,
    "part": 900,
    "assembly": 860,
    "product": 1120,
}

LABEL_SIZE_BY_LEVEL = {
    "material": 8.8,
    "part": 8.6,
    "assembly": 8.4,
    "product": 9.2,
}

KEY_NODE_BORDER_COLOR = "#B7791F"
KEY_NODE_STAR_COLOR = "#D69E2E"
KEY_NODE_LINEWIDTH = 3.2
GENERAL_NODE_LINEWIDTH = 1.6


def export_bom_impact_plot(result: SimulationResult, figure_path: str | Path) -> Path | None:
    if not result.impacted_paths or result.model_bundle is None:
        return None

    prioritized = _select_paths(result)
    if not prioritized:
        return None

    graph = nx.DiGraph()
    edge_dimensions: dict[tuple[str, str], str] = {}
    item_frame = result.model_bundle.standard_bundle.items.set_index("item_id")
    node_levels = item_frame["item_level"].to_dict()
    key_node_lookup = (
        item_frame["is_key_node"].astype(bool).to_dict() if "is_key_node" in item_frame.columns else {}
    )

    for record in prioritized:
        nodes = [segment.strip() for segment in str(record["path"]).split("->") if segment.strip()]
        for index, node_id in enumerate(nodes):
            graph.add_node(
                node_id,
                item_level=node_levels.get(node_id, "part"),
                is_key_node=bool(key_node_lookup.get(node_id, False)),
            )
            if index == 0:
                continue
            source = nodes[index - 1]
            target = node_id
            graph.add_edge(source, target)
            edge_dimensions[(source, target)] = str(record.get("impact_dimension", "fusion"))

    if graph.number_of_nodes() == 0:
        return None

    positions = _build_layered_positions(graph, node_levels)
    fig = plt.figure(figsize=(19.6, 10.6))
    grid = fig.add_gridspec(1, 2, width_ratios=[5.8, 1.35], left=0.05, right=0.97, bottom=0.09, top=0.88, wspace=0.05)
    ax = fig.add_subplot(grid[0, 0])
    info_ax = fig.add_subplot(grid[0, 1])
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    info_ax.set_facecolor("#FFFFFF")
    ax.axis("off")
    info_ax.axis("off")

    add_figure_header(
        fig,
        f"BOM 影响路径图：{result.scenario.scenario_id}",
        f"展示前 {len(prioritized)} 条关键传播路径，按 BOM 层级从左到右规整排布",
    )
    fig.patch.set_facecolor("#FFFFFF")

    _draw_column_guides(ax=ax, positions=positions)

    _draw_bom_edges(ax=ax, graph=graph, positions=positions, edge_dimensions=edge_dimensions)

    _draw_nodes(ax=ax, graph=graph, positions=positions)

    _draw_labels(ax=ax, graph=graph, positions=positions)
    _configure_axes_bounds(ax=ax, positions=positions)
    _draw_sidebar(info_ax=info_ax, graph=graph, path_count=len(prioritized))
    return finish_figure(fig, figure_path, top=0.9, facecolor="#FFFFFF", tight=False)


def _select_paths(result: SimulationResult, limit: int = 10) -> list[dict]:
    priority = {
        ("fusion", "failed"): 0,
        ("fusion", "affected"): 1,
        ("supply", "unavailable"): 2,
        ("supply", "degraded"): 3,
        ("demand", "lost"): 4,
        ("demand", "backlog"): 5,
    }
    unique: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for record in sorted(
        result.impacted_paths,
        key=lambda item: (
            priority.get((str(item.get("impact_dimension")), str(item.get("impact_status"))), 9),
            str(item.get("path")),
        ),
    ):
        key = (
            str(record.get("impact_dimension")),
            str(record.get("impact_status", "")),
            str(record.get("path")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
        if len(unique) >= limit:
            break
    return unique


def _build_layered_positions(graph: nx.DiGraph, node_levels: dict[str, str]) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    anchor_lookup: dict[str, float] = {}
    same_level_edge_counts = {level: 0 for level in LEVEL_ORDER}
    same_level_offsets = _same_level_x_offsets(graph, node_levels)

    for source, target in graph.edges:
        source_level = node_levels.get(source, graph.nodes[source].get("item_level", "part"))
        target_level = node_levels.get(target, graph.nodes[target].get("item_level", "part"))
        if source_level == target_level and source_level in same_level_edge_counts:
            same_level_edge_counts[source_level] += 1

    for level in reversed(LEVEL_ORDER):
        nodes = [node for node in graph.nodes if node_levels.get(node, graph.nodes[node].get("item_level", "part")) == level]
        if not nodes:
            continue
        anchors: dict[str, float] = {}
        for node in nodes:
            parent_anchors = [anchor_lookup[parent] for parent in graph.successors(node) if parent in anchor_lookup]
            anchors[node] = sum(parent_anchors) / len(parent_anchors) if parent_anchors else float(len(anchors))
        ordered_nodes = sorted(nodes, key=lambda node: (anchors.get(node, 0.0), node))
        y_positions = _balanced_y_positions(
            len(ordered_nodes),
            level=level,
            same_level_edge_count=same_level_edge_counts.get(level, 0),
        )
        for node, y_coord in zip(ordered_nodes, y_positions):
            positions[node] = (LEVEL_X[level] + same_level_offsets.get(node, 0) * SAME_LEVEL_X_OFFSET, y_coord)
            anchor_lookup[node] = y_coord

    other_nodes = [node for node in graph.nodes if node not in positions]
    if other_nodes:
        for node, y_coord in zip(
            sorted(other_nodes),
            _balanced_y_positions(len(other_nodes), level="part", same_level_edge_count=0),
        ):
            positions[node] = (LEVEL_X["part"], y_coord)
    return positions


def _same_level_x_offsets(graph: nx.DiGraph, node_levels: dict[str, str]) -> dict[str, int]:
    offsets: dict[str, int] = {node: 0 for node in graph.nodes}
    for level in LEVEL_ORDER:
        level_nodes = [
            node
            for node in graph.nodes
            if node_levels.get(node, graph.nodes[node].get("item_level", "part")) == level
        ]
        if not level_nodes:
            continue
        same_level_graph = nx.DiGraph()
        same_level_graph.add_nodes_from(level_nodes)
        same_level_graph.add_edges_from(
            (source, target)
            for source, target in graph.edges
            if source in same_level_graph and target in same_level_graph
        )
        if not nx.is_directed_acyclic_graph(same_level_graph):
            continue
        for node in nx.topological_sort(same_level_graph):
            upstream_offsets = [offsets[upstream] + 1 for upstream in same_level_graph.predecessors(node)]
            if upstream_offsets:
                offsets[node] = max(offsets[node], max(upstream_offsets))
    return offsets


def _balanced_y_positions(
    count: int,
    *,
    level: str,
    same_level_edge_count: int = 0,
) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [0.0]
    span = 12.6 if count >= 8 else (10.4 if count >= 5 else 7.4)
    if level == "assembly":
        # Keep assembly nodes much farther apart because many arrows terminate there.
        span += 8.4 if count >= 8 else (5.6 if count >= 5 else 3.0)
    if same_level_edge_count > 0:
        span += min(5.2, same_level_edge_count * 0.8)
    step = span / max(count - 1, 1)
    if level == "assembly":
        step = max(step, 2.75)
        span = step * max(count - 1, 1)
    start = span / 2.0
    return [start - index * step for index in range(count)]


def _draw_bom_edges(
    *,
    ax,
    graph: nx.DiGraph,
    positions: dict[str, tuple[float, float]],
    edge_dimensions: dict[tuple[str, str], str],
) -> None:
    for edge, dimension in edge_dimensions.items():
        style = DIMENSION_STYLES.get(dimension, DIMENSION_STYLES["fusion"])
        _draw_straight_edge(
            ax=ax,
            source=positions[edge[0]],
            target=positions[edge[1]],
            color=style["color"],
        )


def _draw_nodes(*, ax, graph: nx.DiGraph, positions: dict[str, tuple[float, float]]) -> None:
    for level in LEVEL_ORDER:
        style = LEVEL_STYLES[level]
        level_nodes = [node for node, data in graph.nodes(data=True) if data.get("item_level") == level]
        if not level_nodes:
            continue
        general_nodes = [node for node in level_nodes if not bool(graph.nodes[node].get("is_key_node", False))]
        key_nodes = [node for node in level_nodes if bool(graph.nodes[node].get("is_key_node", False))]

        if general_nodes:
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=general_nodes,
                node_shape=style["shape"],
                node_color=style["color"],
                edgecolors="#334E68",
                linewidths=GENERAL_NODE_LINEWIDTH,
                node_size=NODE_SIZE_BY_LEVEL[level],
                ax=ax,
                alpha=0.97,
            )

        if key_nodes:
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=key_nodes,
                node_shape=style["shape"],
                node_color=style["color"],
                edgecolors=KEY_NODE_BORDER_COLOR,
                linewidths=KEY_NODE_LINEWIDTH,
                node_size=NODE_SIZE_BY_LEVEL[level],
                ax=ax,
                alpha=0.99,
            )


def _draw_straight_edge(
    *,
    ax,
    source: tuple[float, float],
    target: tuple[float, float],
    color: str,
) -> None:
    patch = FancyArrowPatch(
        source,
        target,
        arrowstyle="-|>",
        mutation_scale=22,
        linewidth=2.55,
        color=color,
        alpha=0.88,
        shrinkA=18,
        shrinkB=20,
        connectionstyle="arc3,rad=0.0",
        zorder=2,
    )
    ax.add_patch(patch)


def _draw_column_guides(*, ax, positions: dict[str, tuple[float, float]]) -> None:
    if not positions:
        return
    y_values = [coord[1] for coord in positions.values()]
    y_min = min(y_values) - 0.55
    y_max = max(y_values) + 0.3
    for level in LEVEL_ORDER:
        x_coord = LEVEL_X[level]
        ax.vlines(x_coord, y_min, y_max, colors="#E2E8F0", linewidth=0.95, linestyles=(0, (3, 5)), zorder=0)
        ax.text(
            x_coord,
            y_max + 0.5,
            LEVEL_STYLES[level]["label"],
            ha="center",
            va="bottom",
            color="#334E68",
            **(font_props(size=12.5, weight="semibold") or {}),
        )


def _draw_labels(*, ax, graph: nx.DiGraph, positions: dict[str, tuple[float, float]]) -> None:
    for node_id, (x_coord, y_coord) in positions.items():
        level = _node_level(graph, node_id)
        ax.text(
            x_coord,
            y_coord,
            node_id,
            ha="center",
            va="center",
            color="#0F172A",
            zorder=6,
            **(font_props(size=LABEL_SIZE_BY_LEVEL[level], weight="semibold") or {}),
        )
        node_level = level
        star_offset = {
            "material": 0.5,
            "part": 0.46,
            "assembly": 0.48,
            "product": 0.58,
        }.get(node_level, 0.48)
        graph_node = graph.nodes.get(node_id, {})
        if bool(graph_node.get("is_key_node", False)):
            ax.text(
                x_coord,
                y_coord + star_offset,
                "★",
                ha="center",
                va="center",
                color=KEY_NODE_STAR_COLOR,
                zorder=7,
                **(font_props(size=11.4, weight="bold") or {}),
        )


def _node_level(graph: nx.DiGraph, node_id: str) -> str:
    level = str(graph.nodes[node_id].get("item_level", "part"))
    return level if level in LEVEL_STYLES else "part"


def _configure_axes_bounds(*, ax, positions: dict[str, tuple[float, float]]) -> None:
    x_values = [coord[0] for coord in positions.values()]
    y_values = [coord[1] for coord in positions.values()]
    ax.set_xlim(min(x_values) - 1.8, max(x_values) + 1.8)
    ax.set_ylim(min(y_values) - 1.3, max(y_values) + 1.8)


def _draw_sidebar(*, info_ax, graph: nx.DiGraph, path_count: int) -> None:
    info_ax.text(
        0.0,
        0.98,
        "路径摘要\n"
        f"展示路径数: {path_count}\n"
        f"节点数: {graph.number_of_nodes()}\n"
        f"边数: {graph.number_of_edges()}",
        transform=info_ax.transAxes,
        va="top",
        ha="left",
        color="#12263A",
        linespacing=1.65,
        **(font_props(size=11.2) or {}),
    )
    info_ax.plot([0.0, 1.0], [0.76, 0.76], transform=info_ax.transAxes, color="#E2E8F0", linewidth=1.0)

    dimension_handles = [
        Line2D([0], [0], color=style["color"], lw=3, label=style["label"])
        for style in DIMENSION_STYLES.values()
    ]
    level_handles = [
        Line2D(
            [0],
            [0],
            marker=style["shape"],
            color="w",
            label=style["label"],
            markerfacecolor=style["color"],
            markeredgecolor="#334E68",
            markersize=9,
        )
        for style in LEVEL_STYLES.values()
    ]
    key_handle = Line2D(
        [0],
        [0],
        marker="o",
        color="w",
        label="关键节点 ★",
        markerfacecolor="#FFFFFF",
        markeredgecolor=KEY_NODE_BORDER_COLOR,
        markeredgewidth=2.2,
        markersize=9,
    )
    legend_kwargs = {
        "frameon": False,
        "borderaxespad": 0.0,
        "handletextpad": 0.65,
        "labelspacing": 0.75,
        "prop": font_props(size=10.2),
    }

    info_ax.text(
        0.0,
        0.72,
        "影响维度",
        transform=info_ax.transAxes,
        va="top",
        ha="left",
        color="#475569",
        **(font_props(size=11.2, weight="semibold") or {}),
    )
    first = info_ax.legend(handles=dimension_handles, loc="upper left", bbox_to_anchor=(0.0, 0.66), **legend_kwargs)
    info_ax.add_artist(first)

    info_ax.text(
        0.0,
        0.43,
        "节点层级",
        transform=info_ax.transAxes,
        va="top",
        ha="left",
        color="#475569",
        **(font_props(size=11.2, weight="semibold") or {}),
    )
    info_ax.legend(handles=level_handles, loc="upper left", bbox_to_anchor=(0.0, 0.37), **legend_kwargs)

    info_ax.text(
        0.0,
        0.24,
        "关键节点",
        transform=info_ax.transAxes,
        va="top",
        ha="left",
        color="#475569",
        **(font_props(size=11.2, weight="semibold") or {}),
    )
    third = info_ax.legend(handles=[key_handle], loc="upper left", bbox_to_anchor=(0.0, 0.195), **legend_kwargs)
    info_ax.add_artist(third)

    info_ax.text(
        0.0,
        0.105,
        "说明\n"
        "列位置代表 BOM 层级\n"
        "节点按上游依赖关系排序\n"
        "关键节点加描边和星标",
        transform=info_ax.transAxes,
        va="top",
        ha="left",
        color="#5B6B7A",
        linespacing=1.32,
        **(font_props(size=9.4) or {}),
    )
