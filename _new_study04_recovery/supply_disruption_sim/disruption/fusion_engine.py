from __future__ import annotations

from collections import Counter

from supply_disruption_sim.model.state_model import (
    SimState,
    update_item_node_state,
    update_item_root_cause,
    update_product_root_cause,
)
from supply_disruption_sim.types import ModelBundle


FUSED_STATUS_TO_SERVICE_LEVEL = {
    "active": 1.0,
    "affected": 0.5,
    "failed": 0.0,
}


def fuse_supply_and_demand(state: SimState, model: ModelBundle) -> None:
    _fuse_item_states(state=state, model=model)
    _fuse_product_states(state=state, model=model)
    _update_system_root_cause(state=state)


def _fuse_item_states(state: SimState, model: ModelBundle) -> None:
    items = model.standard_bundle.items["item_id"].tolist()
    for item_id in items:
        supply_status = _resolve_item_supply_status(state=state, item_id=item_id)
        demand_status = state.demand_state["items"].get(item_id, {}).get("demand_status", "stable")
        fused_status, root_cause = _combine_statuses(
            supply_status=supply_status,
            demand_status=demand_status,
            state=state,
        )
        state.fused_state["items"][item_id] = fused_status
        update_item_root_cause(state, item_id, root_cause)
        update_item_node_state(
            state=state,
            item_id=item_id,
            demand_status=demand_status,
            fused_status=fused_status,
        )


def _fuse_product_states(state: SimState, model: ModelBundle) -> None:
    for product_id in model.bom_graph.final_products():
        supply_status = state.supply_state["products"].get(product_id, state.product_status.get(product_id, "failed"))
        demand_status = state.demand_state["products"].get(product_id, {}).get("demand_status", "stable")
        fused_status, root_cause = _combine_statuses(
            supply_status=supply_status,
            demand_status=demand_status,
            state=state,
            is_product=True,
        )
        state.fused_state["products"][product_id] = fused_status
        update_product_root_cause(state, product_id, root_cause)
        update_item_node_state(
            state=state,
            item_id=product_id,
            demand_status=demand_status,
            fused_status=fused_status,
        )


def _combine_statuses(
    *,
    supply_status: str,
    demand_status: str,
    state: SimState,
    is_product: bool = False,
) -> tuple[str, str]:
    supply_failure_states = set(state.params.fusion_failure_supply_states)
    demand_failure_states = set(state.params.fusion_failure_demand_states)
    supply_affected_states = set(state.params.fusion_affected_supply_states)
    demand_affected_states = set(state.params.fusion_affected_demand_states)

    supply_failed = supply_status in supply_failure_states or (is_product and supply_status == "failed")
    demand_failed = demand_status in demand_failure_states
    supply_affected = supply_status in supply_affected_states or (is_product and supply_status == "affected")
    demand_affected = demand_status in demand_affected_states

    if supply_failed and demand_failed:
        return "failed", "mixed_failure"
    if supply_failed:
        return "failed", "supply_constraint"
    if demand_failed:
        return "failed", "demand_loss"
    if supply_affected and demand_affected:
        return "affected", "mixed_pressure"
    if supply_affected:
        return "affected", "supply_constraint"
    if demand_affected:
        return "affected", "demand_backlog"
    return "active", "stable"


def _resolve_item_supply_status(state: SimState, item_id: str) -> str:
    if item_id in state.supply_state["assemblies"] and state.supply_state["assemblies"][item_id] == "blocked":
        return "blocked"
    return state.supply_state["items"].get(item_id, state.item_effective_status.get(item_id, "available"))


def _update_system_root_cause(state: SimState) -> None:
    product_root_causes = list(state.fused_state["root_cause"].get("products", {}).values())
    if not product_root_causes:
        state.fused_state["root_cause"]["system"] = "stable"
        return
    dominant = Counter(product_root_causes).most_common(1)[0][0]
    state.fused_state["root_cause"]["system"] = dominant
