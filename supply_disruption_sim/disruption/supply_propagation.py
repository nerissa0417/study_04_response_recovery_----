from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import (
    SimState,
    update_item_node_state,
    update_edge_status,
    update_supplier_node_state,
)
from supply_disruption_sim.types import ModelBundle


def _supply_available_threshold(model: ModelBundle) -> float:
    return float(
        model.standard_bundle.metadata.get("config", {})
        .get("supply_status", {})
        .get("available_threshold", 0.95)
    )


def update_supplier_supply_statuses(
    state: SimState,
    context: dict,
    model: ModelBundle,
) -> dict[str, float]:
    capacity_factors: dict[str, float] = {}
    disrupted = context["disrupted_suppliers"]
    degraded = context["degraded_suppliers"]
    for supplier_id in model.standard_bundle.suppliers["supplier_id"]:
        if supplier_id in disrupted:
            state.supplier_status[supplier_id] = "disrupted"
            state.supply_state["suppliers"][supplier_id] = "disrupted"
            update_supplier_node_state(state, supplier_id, "disrupted")
            capacity_factors[supplier_id] = 0.0
        elif supplier_id in degraded:
            state.supplier_status[supplier_id] = "degraded"
            state.supply_state["suppliers"][supplier_id] = "degraded"
            update_supplier_node_state(state, supplier_id, "degraded")
            capacity_factors[supplier_id] = float(degraded[supplier_id])
        else:
            state.supplier_status[supplier_id] = "available"
            state.supply_state["suppliers"][supplier_id] = "available"
            update_supplier_node_state(state, supplier_id, "available")
            capacity_factors[supplier_id] = 1.0
    _update_supplier_network_edges(state=state, model=model)
    return capacity_factors


def propagate_supply_to_items(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    supplier_capacity_factors: dict[str, float],
    context: dict,
    apply_inventory_update: bool = True,
    bayes_engine=None,
) -> None:
    items = model.standard_bundle.items.set_index("item_id")
    assembly_items = set(model.bom_graph.parent_to_children)
    disrupted_supply_edges = set(context.get("disrupted_supply_edges", set()))
    degraded_supply_edges = dict(context.get("degraded_supply_edges", {}))
    available_threshold = _supply_available_threshold(model)
    for item_id, item_row in items.iterrows():
        demand = float(item_row["avg_daily_demand"])
        inventory = float(state.item_inventory[item_id])
        direct_shortage = item_id in context["material_shortages"]

        active_rows = model.supply_map.active_rows(item_id)
        backup_rows = model.supply_map.backup_rows(item_id)
        has_direct_route = not active_rows.empty or item_id in state.backup_active or direct_shortage
        if item_id in assembly_items and not has_direct_route:
            state.item_supply_status[item_id] = "available"
            state.supply_state["items"][item_id] = "available"
            update_item_node_state(state, item_id, supply_status="available")
            continue

        has_backup = not backup_rows.empty or item_id in state.backup_active
        active_factor = 0.0
        active_supplier_ids: list[str] = []
        edge_factors: dict[tuple[str, str], float] = {}
        active_shares = pd.Series(dtype=float)
        if not active_rows.empty:
            active_supplier_ids = [str(supplier_id) for supplier_id in active_rows["supplier_id"].tolist()]
            active_shares = pd.to_numeric(active_rows.get("share", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            active_share_total = float(active_shares.sum())
            if active_share_total <= 0:
                active_shares = pd.Series([1.0 / len(active_rows.index)] * len(active_rows.index), index=active_rows.index)
            elif abs(active_share_total - 1.0) > 0.0001:
                active_shares = active_shares / active_share_total

        if not direct_shortage and not active_rows.empty:
            for row_index, row in active_rows.iterrows():
                edge_ref = (str(row["supplier_id"]), str(item_id))
                row_share = float(active_shares.at[row_index]) if row_index in active_shares.index else 0.0
                if edge_ref in disrupted_supply_edges:
                    edge_factors[edge_ref] = 0.0
                    continue
                supplier_factor = supplier_capacity_factors.get(str(row["supplier_id"]), 0.0)
                explicit_edge_degraded = edge_ref in degraded_supply_edges
                if explicit_edge_degraded:
                    supplier_factor *= float(degraded_supply_edges[edge_ref])
                if bayes_engine is not None and not explicit_edge_degraded:
                    supplier_factor = bayes_engine.edge_interruption_factor(
                        state=state,
                        item_row=item_row,
                        supplier_id=str(row["supplier_id"]),
                        item_id=str(item_id),
                        supplier_factor=float(supplier_factor),
                        has_backup=bool(has_backup),
                    )
                supplier_factor = max(0.0, min(float(supplier_factor), 1.0))
                edge_factors[edge_ref] = supplier_factor
                active_factor += max(row_share, 0.0) * supplier_factor

        backup_factor = 0.0
        active_backup = state.backup_active.get(item_id)
        active_backup_supplier_id = None
        if not direct_shortage and active_backup:
            active_backup_supplier_id = active_backup["supplier_id"]
            edge_ref = (str(active_backup_supplier_id), str(item_id))
            if edge_ref in disrupted_supply_edges:
                backup_factor = 0.0
            else:
                explicit_edge_degraded = edge_ref in degraded_supply_edges
                edge_capacity_factor = float(degraded_supply_edges.get(edge_ref, 1.0))
                supplier_factor = supplier_capacity_factors.get(active_backup_supplier_id, 0.0)
                if bayes_engine is not None and not explicit_edge_degraded:
                    supplier_factor = bayes_engine.edge_interruption_factor(
                        state=state,
                        item_row=item_row,
                        supplier_id=str(active_backup_supplier_id),
                        item_id=str(item_id),
                        supplier_factor=float(supplier_factor),
                        has_backup=True,
                    )
                backup_factor = supplier_factor * float(active_backup["capacity_factor"]) * edge_capacity_factor
                edge_factors[edge_ref] = max(0.0, min(float(supplier_factor * edge_capacity_factor), 1.0))

        inbound_factor = min(1.0, active_factor + backup_factor)
        inbound_qty = demand * inbound_factor
        next_inventory = max(0.0, inventory + inbound_qty - demand)
        if apply_inventory_update:
            state.item_inventory[item_id] = next_inventory
        else:
            next_inventory = inventory

        if inbound_factor >= available_threshold:
            supply_status = "available"
        elif inbound_factor > 0.0 or next_inventory > 0.0:
            supply_status = "degraded"
        else:
            supply_status = "unavailable"

        state.item_supply_status[item_id] = supply_status
        state.supply_state["items"][item_id] = supply_status
        update_item_node_state(state, item_id, supply_status=supply_status)
        _update_supply_edges(
            state=state,
            item_id=item_id,
            active_supplier_ids=active_supplier_ids,
            active_backup_supplier_id=active_backup_supplier_id,
            edge_factors=edge_factors,
            item_supply_status=supply_status,
            context=context,
        )


def propagate_supply_to_bom(state: SimState, model: ModelBundle) -> None:
    external_route_items = set(
        model.standard_bundle.supplier_item_map.loc[
            ~model.standard_bundle.supplier_item_map["is_backup"].astype(bool),
            "item_id",
        ].astype(str)
    ) | set(state.backup_active)
    for item_id in model.bom_graph.child_first_order():
        base_status = state.item_supply_status.get(item_id, "unavailable")
        substitution_item = state.substitution_active.get(item_id)
        external_status = base_status if item_id in external_route_items else None
        effective_status = base_status
        if substitution_item:
            alt_status = state.item_effective_status.get(
                substitution_item, state.item_supply_status.get(substitution_item, "unavailable")
            )
            if alt_status != "unavailable":
                external_status = _best_route_status([external_status, alt_status])
                _update_alternative_edge_status(state=state, item_id=item_id, alt_item_id=substitution_item)

        children = model.bom_graph.children_of(item_id)
        if children:
            child_statuses = [state.item_effective_status.get(child, "unavailable") for child in children]
            bom_status = _bom_route_status(child_statuses)
            effective_status = _best_route_status([external_status, bom_status])
            state.assembly_status[item_id] = "assemblable" if effective_status != "unavailable" else "blocked"
            state.supply_state["assemblies"][item_id] = (
                "blocked" if effective_status == "unavailable" else effective_status
            )
        else:
            state.supply_state["assemblies"].setdefault(item_id, "n/a")

        state.item_effective_status[item_id] = effective_status
        state.fused_state["items"][item_id] = effective_status
        update_item_node_state(state, item_id, fused_status=effective_status)
        _update_bom_edge_states(state=state, model=model, parent_item_id=item_id, effective_status=effective_status)

    for final_product in model.bom_graph.final_products():
        status = state.item_effective_status.get(final_product, "unavailable")
        if status == "available":
            product_status = "active"
        elif status == "degraded":
            product_status = "affected"
        else:
            product_status = "failed"
        state.product_status[final_product] = product_status
        state.supply_state["products"][final_product] = product_status
        state.fused_state["products"][final_product] = product_status
        update_item_node_state(state, final_product, fused_status=product_status)


def _bom_route_status(child_statuses: list[str]) -> str:
    if any(status == "unavailable" for status in child_statuses):
        return "unavailable"
    if any(status == "degraded" for status in child_statuses):
        return "degraded"
    return "available"


def _best_route_status(statuses: list[str | None]) -> str:
    rank = {"unavailable": 0, "degraded": 1, "available": 2}
    valid_statuses = [status for status in statuses if status is not None]
    if not valid_statuses:
        return "unavailable"
    return max(valid_statuses, key=lambda status: rank.get(status, 0))


def _update_supply_edges(
    state: SimState,
    item_id: str,
    active_supplier_ids: list[str],
    active_backup_supplier_id: str | None,
    edge_factors: dict[tuple[str, str], float],
    item_supply_status: str,
    context: dict,
) -> None:
    disrupted_supply_edges = set(context.get("disrupted_supply_edges", set()))
    degraded_supply_edges = dict(context.get("degraded_supply_edges", {}))
    for supplier_id in active_supplier_ids:
        edge_key = f"supply_edge:{supplier_id}:{item_id}"
        edge = state.edge_state.get(edge_key)
        if edge is None:
            continue
        edge_ref = (str(supplier_id), str(item_id))
        edge_factor = float(edge_factors.get(edge_ref, 0.0 if item_supply_status == "unavailable" else 1.0))
        if edge_ref in disrupted_supply_edges or edge_factor <= 0.0:
            update_edge_status(state, edge_key, "disrupted")
        elif edge_ref in degraded_supply_edges:
            update_edge_status(state, edge_key, "active")
        elif item_supply_status == "unavailable":
            update_edge_status(state, edge_key, "disrupted")
        elif item_supply_status == "degraded":
            update_edge_status(state, edge_key, "active")
        else:
            update_edge_status(state, edge_key, "active")

    if active_backup_supplier_id is not None:
        edge_key = f"supply_edge:{active_backup_supplier_id}:{item_id}"
        edge_ref = (str(active_backup_supplier_id), str(item_id))
        edge_factor = float(edge_factors.get(edge_ref, 0.0))
        if edge_ref in disrupted_supply_edges or edge_factor <= 0.0:
            update_edge_status(state, edge_key, "disrupted")
        else:
            update_edge_status(state, edge_key, "backup_active")


def derive_supplier_status_from_item_supply(state: SimState, model: ModelBundle) -> None:
    """Reflect material-level outcomes back onto supplier nodes for reporting."""
    items = model.standard_bundle.items.set_index("item_id")
    supply_map = model.standard_bundle.supplier_item_map.copy()
    active_rows = supply_map.loc[~supply_map["is_backup"].astype(bool)]
    severity = {"available": 0, "degraded": 1, "disrupted": 2}

    for supplier_id in model.standard_bundle.suppliers["supplier_id"].astype(str):
        rows = active_rows.loc[active_rows["supplier_id"].astype(str) == supplier_id]
        statuses: list[str] = []
        for row in rows.itertuples(index=False):
            item_id = str(row.item_id)
            if item_id not in items.index:
                continue
            item_level = str(items.at[item_id, "item_level"])
            if item_level == "product":
                continue
            statuses.append(state.item_supply_status.get(item_id, "available"))

        derived_status = "available"
        if statuses and all(status == "unavailable" for status in statuses):
            derived_status = "disrupted"
        elif any(status in {"degraded", "unavailable"} for status in statuses):
            derived_status = "degraded"

        causal_status = state.supplier_status.get(supplier_id, "available")
        final_status = causal_status if severity.get(causal_status, 0) >= severity[derived_status] else derived_status
        state.supplier_status[supplier_id] = final_status
        state.supply_state["suppliers"][supplier_id] = final_status
        update_supplier_node_state(state, supplier_id, final_status)

    _update_supplier_network_edges(state=state, model=model)


def _update_bom_edge_states(state: SimState, model: ModelBundle, parent_item_id: str, effective_status: str) -> None:
    rows = model.standard_bundle.bom_edges.loc[
        model.standard_bundle.bom_edges["parent_item_id"] == parent_item_id
    ]
    for row in rows.itertuples(index=False):
        edge_key = f"bom_edge:{row.bom_id}"
        edge = state.edge_state.get(edge_key)
        if edge is None:
            continue
        if effective_status == "unavailable":
            update_edge_status(state, edge_key, "disrupted")
        else:
            update_edge_status(state, edge_key, "active")


def _update_supplier_network_edges(state: SimState, model: ModelBundle) -> None:
    for row in model.standard_bundle.supplier_edges.itertuples(index=False):
        source_status = state.supplier_status.get(row.source_supplier_id, "available")
        target_status = state.supplier_status.get(row.target_supplier_id, "available")
        edge_key = f"supplier_edge:{row.edge_id}"
        if "disrupted" in {source_status, target_status}:
            update_edge_status(state, edge_key, "disrupted")
        elif "degraded" in {source_status, target_status}:
            update_edge_status(state, edge_key, "active")
        else:
            update_edge_status(state, edge_key, "active")


def _update_alternative_edge_status(state: SimState, item_id: str, alt_item_id: str) -> None:
    for edge_key, edge in state.edge_state.items():
        if edge["edge_type"] == "alternative" and edge["source_id"] == item_id and edge["target_id"] == alt_item_id:
            update_edge_status(state, edge_key, "substituted")
