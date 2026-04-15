from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.tracking import record_policy_event
from supply_disruption_sim.types import ModelBundle, PolicySpec


def _key_node_bonus(model: ModelBundle) -> float:
    return float(model.standard_bundle.metadata.get("config", {}).get("priority_repair", {}).get("key_node_bonus_weight", 3.0))



def apply_priority_repair(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
    context: dict,
) -> None:
    if not policy.enabled:
        return

    _activate_due_repairs(current_date=current_date, state=state)
    _schedule_supplier_repairs(current_date=current_date, state=state, model=model, policy=policy, context=context)
    _schedule_material_repairs(current_date=current_date, state=state, model=model, policy=policy, context=context)


def override_context_with_repairs(context: dict, state: SimState) -> dict:
    patched = {
        "disrupted_suppliers": set(context["disrupted_suppliers"]),
        "degraded_suppliers": dict(context["degraded_suppliers"]),
        "disrupted_items": set(context.get("disrupted_items", set())),
        "disrupted_supply_edges": set(context.get("disrupted_supply_edges", set())),
        "degraded_supply_edges": dict(context.get("degraded_supply_edges", {})),
    }
    for supplier_id in state.repair_active_suppliers:
        patched["disrupted_suppliers"].discard(supplier_id)
        patched["degraded_suppliers"].pop(supplier_id, None)
    for item_id in state.repair_active_items:
        patched["disrupted_items"].discard(item_id)
    return patched


def _activate_due_repairs(current_date: pd.Timestamp, state: SimState) -> None:
    for supplier_id, payload in list(state.repair_pending_suppliers.items()):
        if payload["activate_date"] <= current_date:
            state.repair_active_suppliers.add(supplier_id)
            state.repair_log.append(
                {"date": current_date, "repair_type": "supplier", "target_id": supplier_id}
            )
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type="priority_repair",
                action="activate_supplier_repair",
                target_id=supplier_id,
                target_type="supplier",
                cost=float(payload.get("activation_cost", 0.0)),
            )
            del state.repair_pending_suppliers[supplier_id]
    for item_id, payload in list(state.repair_pending_items.items()):
        if payload["activate_date"] <= current_date:
            state.repair_active_items.add(item_id)
            state.repair_log.append(
                {"date": current_date, "repair_type": "material", "target_id": item_id}
            )
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type="priority_repair",
                action="activate_material_repair",
                target_id=item_id,
                target_type="item",
                cost=float(payload.get("activation_cost", 0.0)),
            )
            del state.repair_pending_items[item_id]


def _schedule_supplier_repairs(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
    context: dict,
) -> None:
    candidates = sorted(
        set(context["disrupted_suppliers"]) | set(context["degraded_suppliers"]),
        key=lambda supplier_id: _score_supplier(model, supplier_id, policy.priority_rule),
        reverse=True,
    )
    available_slots = max(
        0,
        int(policy.params.get("max_parallel_repairs", state.params.priority_repair_max_parallel))
        - len(state.repair_pending_suppliers),
    )
    for supplier_id in candidates:
        if available_slots <= 0:
            break
        if supplier_id in state.repair_active_suppliers or supplier_id in state.repair_pending_suppliers:
            continue
        schedule_cost = _estimate_supplier_repair_cost(model=model, supplier_id=supplier_id, policy=policy)
        state.repair_pending_suppliers[supplier_id] = {
            "activate_date": current_date + pd.Timedelta(days=state.params.priority_repair_lead_days),
            "activation_cost": float(policy.params.get("activation_cost", 0.0)),
        }
        record_policy_event(
            state=state,
            current_date=current_date,
            policy_type=policy.policy_type,
            action="schedule_supplier_repair",
            target_id=supplier_id,
            target_type="supplier",
            cost=schedule_cost,
            metadata={"activate_date": state.repair_pending_suppliers[supplier_id]["activate_date"]},
        )
        available_slots -= 1


def _schedule_material_repairs(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
    context: dict,
) -> None:
    candidates = sorted(
        set(context.get("disrupted_items", set())),
        key=lambda item_id: _score_item(model, item_id, policy.priority_rule),
        reverse=True,
    )
    available_slots = max(
        0,
        int(policy.params.get("max_parallel_repairs", state.params.priority_repair_max_parallel))
        - len(state.repair_pending_items),
    )
    for item_id in candidates:
        if available_slots <= 0:
            break
        if item_id in state.repair_active_items or item_id in state.repair_pending_items:
            continue
        schedule_cost = _estimate_material_repair_cost(model=model, item_id=item_id, policy=policy)
        state.repair_pending_items[item_id] = {
            "activate_date": current_date + pd.Timedelta(days=state.params.priority_repair_lead_days),
            "activation_cost": float(policy.params.get("activation_cost", 0.0)),
        }
        record_policy_event(
            state=state,
            current_date=current_date,
            policy_type=policy.policy_type,
            action="schedule_material_repair",
            target_id=item_id,
            target_type="item",
            cost=schedule_cost,
            metadata={"activate_date": state.repair_pending_items[item_id]["activate_date"]},
        )
        available_slots -= 1


def _score_supplier(model: ModelBundle, supplier_id: str, priority_rule: str) -> float:
    rows = model.standard_bundle.supplier_item_map.loc[
        model.standard_bundle.supplier_item_map["supplier_id"] == supplier_id
    ]
    if rows.empty:
        return 0.0
    items = model.standard_bundle.items.set_index("item_id")
    score = 0.0
    for row in rows.itertuples(index=False):
        if row.item_id not in items.index:
            continue
        score += float(items.at[row.item_id, "demand_priority"]) * max(float(row.share), 0.1)
        if bool(items.at[row.item_id, "is_critical_material"]):
            score += 2.0
        if "is_key_node" in items.columns and bool(items.at[row.item_id, "is_key_node"]):
            score += _key_node_bonus(model)
        if "critical_score" in items.columns:
            score += float(items.at[row.item_id, "critical_score"])
        score += len(model.bom_graph.paths_to_final_products(row.item_id))
    return score


def _score_item(model: ModelBundle, item_id: str, priority_rule: str) -> float:
    items = model.standard_bundle.items.set_index("item_id")
    if item_id not in items.index:
        return 0.0
    score = float(items.at[item_id, "demand_priority"])
    if bool(items.at[item_id, "is_critical_material"]):
        score += 2.0
    if "is_key_node" in items.columns and bool(items.at[item_id, "is_key_node"]):
        score += _key_node_bonus(model)
    if "critical_score" in items.columns:
        score += float(items.at[item_id, "critical_score"])
    score += len(model.bom_graph.paths_to_final_products(item_id))
    return score


def _estimate_supplier_repair_cost(model: ModelBundle, supplier_id: str, policy: PolicySpec) -> float:
    rows = model.standard_bundle.supplier_item_map.loc[
        model.standard_bundle.supplier_item_map["supplier_id"] == supplier_id
    ]
    impacted_items = max(len(rows), 1)
    return round(
        float(policy.params.get("supplier_repair_cost", 0.0)) + impacted_items * 75.0,
        4,
    )


def _estimate_material_repair_cost(model: ModelBundle, item_id: str, policy: PolicySpec) -> float:
    items = model.standard_bundle.items.set_index("item_id")
    if item_id in items.index:
        avg_daily_demand = float(items.at[item_id, "avg_daily_demand"])
        material_cost = float(items.at[item_id, "material_cost"])
    else:
        avg_daily_demand = 1.0
        material_cost = 1.0
    return round(
        float(policy.params.get("material_repair_cost", 0.0)) + avg_daily_demand * material_cost * 0.05,
        4,
    )
