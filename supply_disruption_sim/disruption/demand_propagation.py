from __future__ import annotations

from supply_disruption_sim.model.state_model import SimState, update_item_demand_node_state
from supply_disruption_sim.types import ModelBundle


PRODUCT_FULFILLMENT_RATIO = {
    "active": 1.0,
    "affected": 0.75,
    "failed": 0.0,
}


def propagate_demand(current_date, state: SimState, model: ModelBundle, bayes_engine=None) -> None:
    items = model.standard_bundle.items.set_index("item_id")
    _reset_item_demand_state(state=state, items=items.index.tolist())
    _propagate_product_demand(current_date=current_date, state=state, model=model, items=items, bayes_engine=bayes_engine)
    _propagate_parent_to_child_demand(state=state, model=model)
    _apply_substitution_transfer(state=state)
    _finalize_item_demand_status(state=state)


def _reset_item_demand_state(state: SimState, items: list[str]) -> None:
    for item_id in items:
        demand_entry = state.demand_state["items"].setdefault(
            item_id,
            {
                "requested_demand": 0.0,
                "fulfilled_demand": 0.0,
                "backlog_demand": 0.0,
                "lost_demand": 0.0,
                "demand_status": "stable",
                "demand_priority": 0,
                "substitute_transfer_in": 0.0,
                "substitute_transfer_out": 0.0,
            },
        )
        demand_priority = demand_entry.get("demand_priority", 0)
        demand_entry.update(
            {
                "requested_demand": 0.0,
                "fulfilled_demand": 0.0,
                "backlog_demand": 0.0,
                "lost_demand": 0.0,
                "demand_status": "stable",
                "demand_priority": demand_priority,
                "substitute_transfer_in": 0.0,
                "substitute_transfer_out": 0.0,
            }
        )


def _propagate_product_demand(current_date, state: SimState, model: ModelBundle, items, bayes_engine=None) -> None:
    final_products = model.bom_graph.final_products()
    for product_id in final_products:
        base_requested = float(items.at[product_id, "default_requested_demand"])
        previous_backlog = float(
            state.demand_state["products"].get(product_id, {}).get("backlog_demand", 0.0)
        )
        requested = base_requested + previous_backlog * state.params.backlog_retention_ratio
        product_status = state.product_status.get(product_id, "failed")
        fulfilled_ratio = PRODUCT_FULFILLMENT_RATIO.get(product_status, 0.0)
        fulfilled = requested * fulfilled_ratio
        gap = max(0.0, requested - fulfilled)
        backlog_ratio = state.params.backlog_retention_ratio
        backlog = gap * backlog_ratio
        lost = max(0.0, gap - backlog)
        demand_status = _evaluate_demand_status(
            requested=requested,
            backlog=backlog,
            lost=lost,
            state=state,
        )
        state.backlog_age_days[str(product_id)] = state.backlog_age_days.get(str(product_id), 0) + 1 if backlog > 0 else 0
        state.demand_state["products"][product_id] = {
            "requested_demand": requested,
            "fulfilled_demand": fulfilled,
            "backlog_demand": backlog,
            "lost_demand": lost,
            "demand_status": demand_status,
        }
        state.demand_state["items"][product_id].update(
            {
                "requested_demand": requested,
                "fulfilled_demand": fulfilled,
                "backlog_demand": backlog,
                "lost_demand": lost,
                "demand_status": demand_status,
            }
        )
        update_item_demand_node_state(state, product_id, demand_status)


def _propagate_parent_to_child_demand(state: SimState, model: ModelBundle) -> None:
    quantity_by_edge = {
        (row.parent_item_id, row.child_item_id): float(row.quantity)
        for row in model.standard_bundle.bom_edges.itertuples(index=False)
    }
    for parent_item_id in reversed(model.bom_graph.child_first_order()):
        parent_demand = state.demand_state["items"].get(parent_item_id)
        if not parent_demand:
            continue
        children = model.bom_graph.children_of(parent_item_id)
        for child_item_id in children:
            qty = quantity_by_edge.get((parent_item_id, child_item_id), 1.0)
            child_demand = state.demand_state["items"].setdefault(
                child_item_id,
                {
                    "requested_demand": 0.0,
                    "fulfilled_demand": 0.0,
                    "backlog_demand": 0.0,
                    "lost_demand": 0.0,
                    "demand_status": "stable",
                    "demand_priority": 0,
                    "substitute_transfer_in": 0.0,
                    "substitute_transfer_out": 0.0,
                },
            )
            child_demand["requested_demand"] += parent_demand["requested_demand"] * qty
            child_demand["fulfilled_demand"] += parent_demand["fulfilled_demand"] * qty
            child_demand["backlog_demand"] += parent_demand["backlog_demand"] * qty
            child_demand["lost_demand"] += parent_demand["lost_demand"] * qty


def _apply_substitution_transfer(state: SimState) -> None:
    for original_item_id, alt_item_id in state.substitution_active.items():
        if original_item_id not in state.demand_state["items"]:
            continue
        original = state.demand_state["items"][original_item_id]
        transfer_qty = float(original["backlog_demand"] + original["lost_demand"])
        if transfer_qty <= 0:
            continue
        original["substitute_transfer_out"] += transfer_qty
        alt = state.demand_state["items"].setdefault(
            alt_item_id,
            {
                "requested_demand": 0.0,
                "fulfilled_demand": 0.0,
                "backlog_demand": 0.0,
                "lost_demand": 0.0,
                "demand_status": "stable",
                "demand_priority": 0,
                "substitute_transfer_in": 0.0,
                "substitute_transfer_out": 0.0,
            },
        )
        alt["substitute_transfer_in"] += transfer_qty


def _finalize_item_demand_status(state: SimState) -> None:
    for item_id, demand in state.demand_state["items"].items():
        requested = float(demand["requested_demand"])
        backlog = float(demand["backlog_demand"])
        lost = float(demand["lost_demand"])
        demand_status = _evaluate_demand_status(
            requested=requested,
            backlog=backlog,
            lost=lost,
            state=state,
        )
        demand["demand_status"] = demand_status
        state.backlog_age_days[str(item_id)] = state.backlog_age_days.get(str(item_id), 0) + 1 if backlog > 0 else 0
        update_item_demand_node_state(state, item_id, demand_status)


def _evaluate_demand_status(
    *,
    requested: float,
    backlog: float,
    lost: float,
    state: SimState,
) -> str:
    if requested <= 0:
        return "stable"
    loss_ratio = lost / requested
    backlog_ratio = backlog / requested
    if loss_ratio >= (1 - state.params.demand_lost_threshold):
        return "lost"
    if backlog_ratio >= (1 - state.params.demand_backlog_threshold):
        return "backlog"
    return "stable"
