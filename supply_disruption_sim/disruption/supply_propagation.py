from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import (
    SimState,
    update_item_node_state,
    update_edge_status,
    update_supplier_node_state,
)
from supply_disruption_sim.types import ModelBundle


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
    for item_id, item_row in items.iterrows():
        if item_id in assembly_items:
            state.item_inbound_factor[item_id] = 1.0
            state.item_supply_status[item_id] = "available"
            state.supply_state["items"][item_id] = "available"
            update_item_node_state(state, item_id, supply_status="available")
            continue

        demand = float(item_row["avg_daily_demand"])
        inventory = float(state.item_inventory[item_id])
        direct_shortage = item_id in context["material_shortages"]
        primary_rows = model.supply_map.primary_rows(item_id)
        backup_rows = model.supply_map.backup_rows(item_id)

        has_backup = not backup_rows.empty or item_id in state.backup_active
        primary_factor = 0.0
        primary_supplier_ids: list[str] = []
        if not direct_shortage and not primary_rows.empty:
            for row in primary_rows.itertuples(index=False):
                primary_supplier_ids.append(str(row.supplier_id))
                edge_ref = (str(row.supplier_id), str(item_id))
                if edge_ref in disrupted_supply_edges:
                    continue
                supplier_factor = supplier_capacity_factors.get(str(row.supplier_id), 0.0)
                if edge_ref in degraded_supply_edges:
                    supplier_factor *= float(degraded_supply_edges[edge_ref])
                supplier_status = state.supplier_status.get(str(row.supplier_id), "available")
                if (
                    bayes_engine is not None
                    and (supplier_status in {"disrupted", "degraded"} or edge_ref in degraded_supply_edges)
                ):
                    supplier_factor *= bayes_engine.edge_propagation_probability(
                        state=state,
                        item_row=item_row,
                        supplier_id=str(row.supplier_id),
                        item_id=str(item_id),
                        supplier_factor=float(supplier_factor),
                        has_backup=bool(has_backup),
                    )
                primary_factor = max(primary_factor, float(supplier_factor))

        backup_factor = 0.0
        active_backup = state.backup_active.get(item_id)
        active_backup_supplier_id = None
        if not direct_shortage and active_backup:
            active_backup_supplier_id = active_backup["supplier_id"]
            edge_ref = (str(active_backup_supplier_id), str(item_id))
            if edge_ref in disrupted_supply_edges:
                backup_factor = 0.0
            else:
                edge_capacity_factor = float(degraded_supply_edges.get(edge_ref, 1.0))
                backup_factor = (
                    supplier_capacity_factors.get(str(active_backup_supplier_id), 0.0)
                    * float(active_backup["capacity_factor"])
                    * edge_capacity_factor
                )
                supplier_status = state.supplier_status.get(str(active_backup_supplier_id), "available")
                if (
                    bayes_engine is not None
                    and (supplier_status in {"disrupted", "degraded"} or edge_ref in degraded_supply_edges)
                ):
                    backup_factor *= bayes_engine.edge_propagation_probability(
                        state=state,
                        item_row=item_row,
                        supplier_id=str(active_backup_supplier_id),
                        item_id=str(item_id),
                        supplier_factor=float(backup_factor),
                        has_backup=True,
                    )

        inbound_factor = max(primary_factor, backup_factor)
        state.item_inbound_factor[item_id] = inbound_factor
        inbound_qty = demand * inbound_factor
        next_inventory = max(0.0, inventory + inbound_qty - demand)
        if apply_inventory_update:
            state.item_inventory[item_id] = next_inventory
        else:
            next_inventory = inventory

        if inbound_factor >= 0.95:
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
            primary_supplier_ids=primary_supplier_ids,
            active_backup_supplier_id=active_backup_supplier_id,
            item_supply_status=supply_status,
            context=context,
        )


def propagate_supply_to_bom(state: SimState, model: ModelBundle) -> None:
    for item_id in model.bom_graph.child_first_order():
        base_status = state.item_supply_status.get(item_id, "unavailable")
        substitution_item = state.substitution_active.get(item_id)
        effective_status = base_status
        if substitution_item:
            alt_status = state.item_effective_status.get(
                substitution_item, state.item_supply_status.get(substitution_item, "unavailable")
            )
            if alt_status != "unavailable":
                effective_status = alt_status
                _update_alternative_edge_status(state=state, item_id=item_id, alt_item_id=substitution_item)

        children = model.bom_graph.children_of(item_id)
        if children:
            child_statuses = [state.item_effective_status.get(child, "unavailable") for child in children]
            if any(status == "unavailable" for status in child_statuses):
                effective_status = "unavailable"
            elif effective_status == "unavailable":
                effective_status = "unavailable"
            elif any(status == "degraded" for status in child_statuses) or effective_status == "degraded":
                effective_status = "degraded"
            else:
                effective_status = "available"
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


def _update_supply_edges(
    state: SimState,
    item_id: str,
    primary_supplier_ids: list[str],
    active_backup_supplier_id: str | None,
    item_supply_status: str,
    context: dict,
) -> None:
    disrupted_supply_edges = set(context.get("disrupted_supply_edges", set()))
    degraded_supply_edges = dict(context.get("degraded_supply_edges", {}))
    for supplier_id in primary_supplier_ids:
        edge_key = f"supply_edge:{supplier_id}:{item_id}"
        edge = state.edge_state.get(edge_key)
        if edge is None:
            continue
        edge_ref = (str(supplier_id), str(item_id))
        if edge_ref in disrupted_supply_edges:
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
        if edge_ref in disrupted_supply_edges:
            update_edge_status(state, edge_key, "disrupted")
        else:
            update_edge_status(state, edge_key, "backup_active")

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
