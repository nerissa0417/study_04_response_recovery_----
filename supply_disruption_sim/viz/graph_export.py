from __future__ import annotations

import textwrap

import networkx as nx

from supply_disruption_sim.types import ModelBundle


def build_export_graph(model: ModelBundle) -> tuple[nx.DiGraph, dict[str, tuple[float, float]]]:
    graph = nx.DiGraph()

    suppliers = model.standard_bundle.suppliers.sort_values("supplier_id")
    items = model.standard_bundle.items.sort_values(["item_level", "item_id"])

    for row in suppliers.itertuples(index=False):
        graph.add_node(
            f"supplier:{row.supplier_id}",
            entity_id=row.supplier_id,
            node_type=row.node_type,
            label=_compose_label(row.supplier_id, getattr(row, "supplier_name", row.supplier_id), bool(getattr(row, "is_key_node", False))),
            short_label=_compose_short_label(row.supplier_id, getattr(row, "supplier_name", row.supplier_id), bool(getattr(row, "is_key_node", False))),
            is_key_node=bool(getattr(row, "is_key_node", False)),
        )

    for _, level_frame in items.groupby("item_level", sort=False):
        for row in level_frame.itertuples(index=False):
            graph.add_node(
                f"item:{row.item_id}",
                entity_id=row.item_id,
                node_type=row.node_type,
                item_level=row.item_level,
                label=_compose_label(row.item_id, getattr(row, "item_name", row.item_id), bool(getattr(row, "is_key_node", False))),
                short_label=_compose_short_label(row.item_id, getattr(row, "item_name", row.item_id), bool(getattr(row, "is_key_node", False))),
                is_key_node=bool(getattr(row, "is_key_node", False)),
            )

    for row in model.standard_bundle.supplier_edges.itertuples(index=False):
        graph.add_edge(
            f"supplier:{row.source_supplier_id}",
            f"supplier:{row.target_supplier_id}",
            edge_key=f"supplier_edge:{row.edge_id}",
            edge_type=row.edge_type,
        )
    item_level_lookup = items.set_index("item_id")["item_level"].astype(str).to_dict()
    for row in model.standard_bundle.supplier_item_map.itertuples(index=False):
        graph.add_edge(
            f"supplier:{row.supplier_id}",
            f"item:{row.item_id}",
            edge_key=f"supply_edge:{row.supplier_id}:{row.item_id}",
            edge_type=row.edge_type,
            item_level=str(item_level_lookup.get(row.item_id, "")),
            is_backup=bool(getattr(row, "is_backup", False)),
            is_current_source=bool(getattr(row, "is_current_source", not bool(getattr(row, "is_backup", False)))),
            supply_role=str(getattr(row, "supply_role", "")),
            edge_status_default=str(getattr(row, "edge_status_default", "")),
        )
    for row in model.standard_bundle.bom_edges.itertuples(index=False):
        graph.add_edge(
            f"item:{row.child_item_id}",
            f"item:{row.parent_item_id}",
            edge_key=f"bom_edge:{row.bom_id}",
            edge_type=row.edge_type,
        )
    for row in model.standard_bundle.part_alternatives.itertuples(index=False):
        graph.add_edge(
            f"item:{row.item_id}",
            f"item:{row.alt_item_id}",
            edge_key=f"alt_edge:{row.alternative_id}",
            edge_type=row.edge_type,
        )
    positions = _build_separated_network_positions(model)
    return graph, positions


def _compose_label(entity_id: str, display_name: str, is_key_node: bool) -> str:
    prefix = "★ " if is_key_node else ""
    name = textwrap.shorten(str(display_name), width=16, placeholder="…")
    return f"{prefix}{entity_id}\n{name}"


def _compose_short_label(entity_id: str, display_name: str, is_key_node: bool) -> str:
    prefix = "★ " if is_key_node else ""
    name = textwrap.shorten(str(display_name), width=10, placeholder="…")
    return f"{prefix}{entity_id}\n{name}"


def _build_separated_network_positions(model: ModelBundle) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    items = model.standard_bundle.items.sort_values(["item_level", "item_id"])
    level_order = ["material", "part", "assembly", "product"]
    bom_edges = model.standard_bundle.bom_edges
    parent_lookup = (
        bom_edges.groupby("child_item_id")["parent_item_id"].apply(lambda series: sorted(series.astype(str).tolist())).to_dict()
    )
    item_anchor_lookup = _build_item_anchor_lookup(items, parent_lookup)
    bom_x_positions = {
        "material": 2.4,
        "part": 7.4,
        "assembly": 12.4,
        "product": 17.4,
    }

    item_y_lookup: dict[str, float] = {}
    for item_level in level_order:
        level_frame = items.loc[items["item_level"] == item_level].copy()
        if level_frame.empty:
            continue
        node_keys = [f"item:{item_id}" for item_id in level_frame["item_id"].astype(str).tolist()]
        anchors = {
            f"item:{row.item_id}": float(item_anchor_lookup.get(str(row.item_id), 0.0))
            for row in level_frame.itertuples(index=False)
        }
        level_positions = _column_positions(
            node_keys=node_keys,
            x=bom_x_positions[item_level],
            y_min=10.0,
            y_max=19.2,
            anchors=anchors,
        )
        positions.update(level_positions)
        for node_key, (_, y_coord) in level_positions.items():
            item_y_lookup[node_key.removeprefix("item:")] = y_coord

    other_frame = items.loc[~items["item_level"].isin(level_order)].copy()
    if not other_frame.empty:
        other_keys = [f"item:{item_id}" for item_id in other_frame["item_id"].astype(str).tolist()]
        positions.update(
            _column_positions(
                node_keys=other_keys,
                x=8.5,
                y_min=10.4,
                y_max=18.4,
            )
        )

    supplier_rows = model.standard_bundle.suppliers.sort_values("supplier_id")
    mapping = model.standard_bundle.supplier_item_map.copy()
    supplier_anchor_lookup: dict[str, float] = {}
    for row in supplier_rows.itertuples(index=False):
        supplied_items = mapping.loc[mapping["supplier_id"] == row.supplier_id, "item_id"].astype(str).tolist()
        supplied_y = [item_y_lookup[item_id] for item_id in supplied_items if item_id in item_y_lookup]
        supplier_anchor_lookup[str(row.supplier_id)] = sum(supplied_y) / len(supplied_y) if supplied_y else 0.0

    supplier_levels = _build_supplier_level_lookup(model)
    ordered_supplier_ids = sorted(
        [str(supplier_id) for supplier_id in supplier_rows["supplier_id"].astype(str).tolist()],
        key=lambda supplier_id: (
            int(supplier_levels.get(supplier_id, 0)),
            float(supplier_anchor_lookup.get(supplier_id, 0.0)),
            supplier_id,
        ),
    )
    supplier_columns = _split_into_columns(ordered_supplier_ids, columns=5)
    max_rows = max((len(column) for column in supplier_columns), default=0)
    for column_index, supplier_ids in enumerate(supplier_columns):
        if not supplier_ids:
            continue
        x_coord = 2.4 + column_index * 3.55
        anchors = {f"supplier:{supplier_id}": supplier_anchor_lookup.get(supplier_id, 0.0) for supplier_id in supplier_ids}
        column_positions = _column_positions(
            node_keys=[f"supplier:{supplier_id}" for supplier_id in supplier_ids],
            x=x_coord,
            y_min=1.0,
            y_max=6.6,
            anchors=anchors,
            row_slots=max_rows or None,
        )
        positions.update(column_positions)
    return positions


def _build_item_anchor_lookup(items, parent_lookup: dict[str, list[str]]) -> dict[str, float]:
    item_ids = items["item_id"].astype(str).tolist()
    level_lookup = items.set_index("item_id")["item_level"].astype(str).to_dict()
    anchor_lookup: dict[str, float] = {}
    product_ids = sorted([item_id for item_id in item_ids if level_lookup.get(item_id) == "product"])
    for index, item_id in enumerate(product_ids):
        anchor_lookup[item_id] = float(index)

    for item_level in ["assembly", "part", "material"]:
        level_ids = sorted([item_id for item_id in item_ids if level_lookup.get(item_id) == item_level])
        fallback_start = max(anchor_lookup.values(), default=-1.0) + 1.0
        for offset, item_id in enumerate(level_ids):
            parent_ids = [parent_id for parent_id in parent_lookup.get(item_id, []) if parent_id in anchor_lookup]
            if parent_ids:
                anchor_lookup[item_id] = sum(anchor_lookup[parent_id] for parent_id in parent_ids) / len(parent_ids)
            else:
                anchor_lookup[item_id] = fallback_start + float(offset)

    for item_id in item_ids:
        anchor_lookup.setdefault(item_id, max(anchor_lookup.values(), default=-1.0) + 1.0)
    return anchor_lookup


def _column_positions(
    node_keys: list[str],
    *,
    x: float,
    y_min: float,
    y_max: float,
    anchors: dict[str, float] | None = None,
    row_slots: int | None = None,
) -> dict[str, tuple[float, float]]:
    if not node_keys:
        return {}
    if anchors:
        ordered_keys = sorted(node_keys, key=lambda node_key: (anchors.get(node_key, 0.0), node_key))
    else:
        ordered_keys = sorted(node_keys)
    if row_slots is not None and row_slots > len(ordered_keys):
        slot_positions = [
            y_max - idx * ((y_max - y_min) / max(row_slots - 1, 1))
            for idx in range(row_slots)
        ]
        slot_indices = _evenly_spaced_indices(len(ordered_keys), row_slots)
        return {
            node_key: (x, slot_positions[slot_index])
            for node_key, slot_index in zip(ordered_keys, slot_indices)
        }
    if len(ordered_keys) == 1:
        return {ordered_keys[0]: (x, (y_min + y_max) / 2.0)}
    step = (y_max - y_min) / max(len(ordered_keys) - 1, 1)
    return {node_key: (x, y_max - idx * step) for idx, node_key in enumerate(ordered_keys)}


def _build_supplier_level_lookup(model: ModelBundle) -> dict[str, int]:
    graph = nx.DiGraph()
    for row in model.standard_bundle.suppliers.itertuples(index=False):
        graph.add_node(str(row.supplier_id))
    for row in model.standard_bundle.supplier_edges.itertuples(index=False):
        graph.add_edge(str(row.source_supplier_id), str(row.target_supplier_id))

    indegree_zero = sorted([node for node, indegree in graph.in_degree() if indegree == 0])
    level_lookup = {node: 0 for node in indegree_zero}
    try:
        traversal = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible:
        traversal = sorted(graph.nodes)
    for node in traversal:
        parent_levels = [level_lookup[parent] for parent in graph.predecessors(node) if parent in level_lookup]
        if parent_levels:
            level_lookup[node] = max(parent_levels) + 1
        else:
            level_lookup.setdefault(node, 0)
    for node in graph.nodes:
        level_lookup.setdefault(node, 0)
    return level_lookup


def _split_into_columns(node_ids: list[str], columns: int = 5) -> list[list[str]]:
    if not node_ids:
        return []
    bucket_count = min(columns, len(node_ids))
    bucket_size = (len(node_ids) + bucket_count - 1) // bucket_count
    return [
        node_ids[index * bucket_size : (index + 1) * bucket_size]
        for index in range(bucket_count)
        if node_ids[index * bucket_size : (index + 1) * bucket_size]
    ]


def _evenly_spaced_indices(count: int, total_slots: int) -> list[int]:
    if count <= 0 or total_slots <= 0:
        return []
    if count == 1:
        return [total_slots // 2]
    return [
        int(round(index * (total_slots - 1) / max(count - 1, 1)))
        for index in range(count)
    ]
