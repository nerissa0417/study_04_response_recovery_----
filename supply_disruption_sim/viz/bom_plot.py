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
DIMENSION_ORDER = ["fusion", "supply", "demand"]
PATH_PRIORITY = {
    ("fusion", "failed"): 0,
    ("fusion", "affected"): 1,
    ("supply", "unavailable"): 2,
    ("supply", "degraded"): 3,
    ("demand", "lost"): 4,
    ("demand", "backlog"): 5,
}

LEVEL_STYLES = {
    "material": {"shape": "s", "color": "#F6BD60", "label": "原材料"},
    "part": {"shape": "o", "color": "#84A59D", "label": "零件"},
    "assembly": {"shape": "D", "color": "#F28482", "label": "装配"},
    "product": {"shape": "^", "color": "#5C80BC", "label": "产品"},
}

LEVEL_ORDER = ["material", "part", "assembly", "product"]
LEVEL_STAGE_GAP = {
    "material": 1.2,
    "part": 1.25,
    "assembly": 1.95,
    "product": 1.0,
}
LEVEL_SECTION_GAP = {
    "material": 2.8,
    "part": 2.8,
    "assembly": 3.0,
    "product": 0.0,
}
LAYOUT_START_X = 1.6
SAME_LEVEL_EDGE_CURVE = 0.18


def export_bom_impact_plot(result: SimulationResult, figure_path: str | Path) -> Path | None:
    if not result.impacted_paths or result.model_bundle is None:
        return None

    prioritized = select_impacted_paths(result)
    if not prioritized:
        return None

    graph = nx.DiGraph()
    edge_dimensions: dict[tuple[str, str], str] = {}
    node_levels = result.model_bundle.standard_bundle.items.set_index("item_id")["item_level"].to_dict()

    for record in prioritized:
        nodes = [segment.strip() for segment in str(record["path"]).split("->") if segment.strip()]
        for index, node_id in enumerate(nodes):
            graph.add_node(node_id, item_level=node_levels.get(node_id, "part"))
            if index == 0:
                continue
            source = nodes[index - 1]
            target = node_id
            graph.add_edge(source, target)
            edge_key = (source, target)
            edge_dimensions[edge_key] = _preferred_dimension(
                current=edge_dimensions.get(edge_key),
                candidate=str(record.get("impact_dimension", "fusion")),
            )

    if graph.number_of_nodes() == 0:
        return None

    positions, level_layout = _build_layered_positions(graph, node_levels)
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
        "物料清单影响路径图",
        f"展示前 {len(prioritized)} 条关键传播路径，按物料清单层级从左到右规整排布",
    )
    fig.patch.set_facecolor("#FFFFFF")

    _draw_column_guides(ax=ax, level_layout=level_layout, positions=positions)

    _draw_bom_edges(ax=ax, graph=graph, positions=positions, edge_dimensions=edge_dimensions)

    for level in LEVEL_ORDER:
        style = LEVEL_STYLES[level]
        nodes = [node for node, data in graph.nodes(data=True) if data.get("item_level") == level]
        if not nodes:
            continue
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=nodes,
            node_shape=style["shape"],
            node_color=style["color"],
            edgecolors="#334E68",
            linewidths=1.6,
            node_size=1500 if level == "product" else (1360 if level == "assembly" else 1220),
            ax=ax,
            alpha=0.97,
        )

    _draw_labels(ax=ax, positions=positions)
    _configure_axes_bounds(ax=ax, positions=positions)
    _draw_sidebar(info_ax=info_ax, graph=graph, path_count=len(prioritized))
    return finish_figure(fig, figure_path, top=0.9, facecolor="#FFFFFF", tight=False)


def select_impacted_paths(result: SimulationResult, limit: int = 10) -> list[dict]:
    unique: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for record in sorted(
        result.impacted_paths,
        key=lambda item: (
            PATH_PRIORITY.get((str(item.get("impact_dimension")), str(item.get("impact_status"))), 9),
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

    selected: list[dict] = []
    selected_keys: set[tuple[str, str, str]] = set()
    for dimension in DIMENSION_ORDER:
        for record in unique:
            if str(record.get("impact_dimension")) != dimension:
                continue
            key = (
                str(record.get("impact_dimension")),
                str(record.get("impact_status", "")),
                str(record.get("path")),
            )
            if key in selected_keys:
                continue
            selected.append(record)
            selected_keys.add(key)
            break

    for record in unique:
        if len(selected) >= limit:
            break
        key = (
            str(record.get("impact_dimension")),
            str(record.get("impact_status", "")),
            str(record.get("path")),
        )
        if key in selected_keys:
            continue
        selected.append(record)
        selected_keys.add(key)
    return selected[:limit]


def _select_paths(result: SimulationResult, limit: int = 10) -> list[dict]:
    return select_impacted_paths(result, limit=limit)


def _build_layered_positions(
    graph: nx.DiGraph,
    node_levels: dict[str, str],
) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, object]]]:
    positions: dict[str, tuple[float, float]] = {}
    same_level_edge_counts = {level: 0 for level in LEVEL_ORDER}
    stage_lookup, stage_count_by_level = _same_level_stage_lookup(graph, node_levels)
    upstream_anchor, downstream_anchor = _build_graph_anchor_lookup(graph)
    level_layout = _build_level_layout(graph, node_levels, stage_count_by_level)

    for source, target in graph.edges:
        source_level = node_levels.get(source, graph.nodes[source].get("item_level", "part"))
        target_level = node_levels.get(target, graph.nodes[target].get("item_level", "part"))
        if source_level == target_level and source_level in same_level_edge_counts:
            same_level_edge_counts[source_level] += 1

    for level in LEVEL_ORDER:
        if level not in level_layout:
            continue
        nodes = [
            node
            for node in graph.nodes
            if node_levels.get(node, graph.nodes[node].get("item_level", "part")) == level
        ]
        if not nodes:
            continue
        ordered_nodes = sorted(
            nodes,
            key=lambda node: (
                downstream_anchor.get(node, 0.0),
                upstream_anchor.get(node, 0.0),
                stage_lookup.get(node, 0),
                node,
            ),
        )
        y_positions = _balanced_y_positions(
            len(ordered_nodes),
            level=level,
            same_level_edge_count=same_level_edge_counts.get(level, 0),
            stage_count=stage_count_by_level.get(level, 1),
        )
        for node, y_coord in zip(ordered_nodes, y_positions):
            stage = int(stage_lookup.get(node, 0))
            x_coord = float(level_layout[level]["stage_positions"][stage])
            positions[node] = (x_coord, y_coord)

    other_nodes = [node for node in graph.nodes if node not in positions]
    if other_nodes:
        fallback_x = float(max((coord[0] for coord in positions.values()), default=LAYOUT_START_X) + 2.4)
        for node, y_coord in zip(
            sorted(other_nodes),
            _balanced_y_positions(len(other_nodes), level="part", same_level_edge_count=0, stage_count=1),
        ):
            positions[node] = (fallback_x, y_coord)
    return positions, level_layout


def _same_level_stage_lookup(
    graph: nx.DiGraph,
    node_levels: dict[str, str],
) -> tuple[dict[str, int], dict[str, int]]:
    # The BOM path figure uses a single-column layout per level:
    # material -> part -> assembly -> product. Same-level relations are
    # expressed by curved edges rather than additional horizontal columns.
    stage_lookup: dict[str, int] = {node: 0 for node in graph.nodes}
    stage_count_by_level: dict[str, int] = {}
    for level in LEVEL_ORDER:
        level_nodes = [
            node
            for node in graph.nodes
            if node_levels.get(node, graph.nodes[node].get("item_level", "part")) == level
        ]
        if level_nodes:
            stage_count_by_level[level] = 1
    return stage_lookup, stage_count_by_level


def _build_graph_anchor_lookup(graph: nx.DiGraph) -> tuple[dict[str, float], dict[str, float]]:
    try:
        traversal = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        traversal = sorted(graph.nodes)

    upstream_anchor: dict[str, float] = {}
    source_nodes = [node for node in traversal if graph.in_degree(node) == 0]
    for index, node in enumerate(source_nodes):
        upstream_anchor[node] = float(index)
    for node in traversal:
        predecessor_values = [upstream_anchor[pred] for pred in graph.predecessors(node) if pred in upstream_anchor]
        if predecessor_values:
            upstream_anchor[node] = sum(predecessor_values) / len(predecessor_values)
        else:
            upstream_anchor.setdefault(node, float(len(upstream_anchor)))

    downstream_anchor: dict[str, float] = {}
    sink_nodes = [node for node in traversal if graph.out_degree(node) == 0]
    for index, node in enumerate(sink_nodes):
        downstream_anchor[node] = float(index)
    for node in reversed(traversal):
        successor_values = [downstream_anchor[succ] for succ in graph.successors(node) if succ in downstream_anchor]
        if successor_values:
            downstream_anchor[node] = sum(successor_values) / len(successor_values)
        else:
            downstream_anchor.setdefault(node, float(len(downstream_anchor)))
    return upstream_anchor, downstream_anchor


def _build_level_layout(
    graph: nx.DiGraph,
    node_levels: dict[str, str],
    stage_count_by_level: dict[str, int],
) -> dict[str, dict[str, object]]:
    level_layout: dict[str, dict[str, object]] = {}
    current_x = LAYOUT_START_X
    present_levels = [
        level
        for level in LEVEL_ORDER
        if any(node_levels.get(node, graph.nodes[node].get("item_level", "part")) == level for node in graph.nodes)
    ]
    for level in present_levels:
        stage_count = max(1, int(stage_count_by_level.get(level, 1)))
        gap = float(LEVEL_STAGE_GAP.get(level, 1.4))
        stage_positions = [current_x + index * gap for index in range(stage_count)]
        level_layout[level] = {
            "stage_positions": stage_positions,
            "x_min": stage_positions[0],
            "x_max": stage_positions[-1],
            "x_center": sum(stage_positions) / len(stage_positions),
        }
        current_x = stage_positions[-1] + float(LEVEL_SECTION_GAP.get(level, 2.8))
    return level_layout


def _balanced_y_positions(
    count: int,
    *,
    level: str,
    same_level_edge_count: int = 0,
    stage_count: int = 1,
) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [0.0]
    span = 12.6 if count >= 8 else (10.4 if count >= 5 else 7.4)
    if level == "assembly":
        span += 10.6 if count >= 8 else (7.4 if count >= 5 else 4.2)
    if stage_count > 1:
        span += min(6.0, (stage_count - 1) * (1.65 if level == "assembly" else 0.95))
    if same_level_edge_count > 0:
        span += min(6.4, same_level_edge_count * 1.05)
    step = span / max(count - 1, 1)
    if level == "assembly":
        step = max(step, 3.35)
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
        source_level = graph.nodes[edge[0]].get("item_level", "part")
        target_level = graph.nodes[edge[1]].get("item_level", "part")
        _draw_edge(
            ax=ax,
            source=positions[edge[0]],
            target=positions[edge[1]],
            color=style["color"],
            connectionstyle=_edge_connectionstyle(
                source=positions[edge[0]],
                target=positions[edge[1]],
                same_level=source_level == target_level,
            ),
        )


def _draw_edge(
    *,
    ax,
    source: tuple[float, float],
    target: tuple[float, float],
    color: str,
    connectionstyle: str,
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
        connectionstyle=connectionstyle,
        zorder=2,
    )
    ax.add_patch(patch)


def _edge_connectionstyle(
    *,
    source: tuple[float, float],
    target: tuple[float, float],
    same_level: bool,
) -> str:
    if not same_level:
        return "arc3,rad=0.0"
    vertical_delta = target[1] - source[1]
    direction = 1.0 if vertical_delta <= 0 else -1.0
    return f"arc3,rad={direction * SAME_LEVEL_EDGE_CURVE:.3f}"


def _preferred_dimension(*, current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    current_rank = DIMENSION_ORDER.index(current) if current in DIMENSION_ORDER else len(DIMENSION_ORDER)
    candidate_rank = DIMENSION_ORDER.index(candidate) if candidate in DIMENSION_ORDER else len(DIMENSION_ORDER)
    return candidate if candidate_rank < current_rank else current


def _draw_column_guides(*, ax, level_layout: dict[str, dict[str, object]], positions: dict[str, tuple[float, float]]) -> None:
    if not positions or not level_layout:
        return
    y_values = [coord[1] for coord in positions.values()]
    y_min = min(y_values) - 0.75
    y_max = max(y_values) + 0.55
    for level in LEVEL_ORDER:
        if level not in level_layout:
            continue
        meta = level_layout[level]
        x_min = float(meta["x_min"])
        x_max = float(meta["x_max"])
        x_center = float(meta["x_center"])
        ax.vlines(
            [x_min, x_max],
            y_min,
            y_max,
            colors="#E2E8F0",
            linewidth=0.9,
            linestyles=(0, (3, 5)),
            zorder=0,
        )
        ax.text(
            x_center,
            y_max + 0.5,
            LEVEL_STYLES[level]["label"],
            ha="center",
            va="bottom",
            color="#334E68",
            **(font_props(size=12.5, weight="semibold") or {}),
        )


def _draw_labels(*, ax, positions: dict[str, tuple[float, float]]) -> None:
    for node_id, (x_coord, y_coord) in positions.items():
        ax.text(
            x_coord,
            y_coord,
            node_id,
            ha="center",
            va="center",
            color="#0F172A",
            zorder=6,
            **(font_props(size=10.2, weight="semibold") or {}),
        )


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
        0.08,
        "说明\n"
        "列位置代表物料清单层级\n"
        "节点按上游依赖关系排序\n"
        "尽量减少跨层交叉",
        transform=info_ax.transAxes,
        va="bottom",
        ha="left",
        color="#5B6B7A",
        linespacing=1.6,
        **(font_props(size=10) or {}),
    )
