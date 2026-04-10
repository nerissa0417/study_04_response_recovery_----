from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.tracking import record_policy_event
from supply_disruption_sim.types import ModelBundle, PolicySpec


def apply_equivalent_material_substitution(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
) -> None:
    if not policy.enabled:
        return

    critical_items = model.standard_bundle.items.loc[
        model.standard_bundle.items["is_critical_material"], "item_id"
    ]
    for item_id in critical_items:
        if state.item_supply_status.get(item_id) != "unavailable":
            state.substitution_pending.pop(item_id, None)
            state.substitution_active.pop(item_id, None)
            continue
        if item_id in state.substitution_active:
            continue
        alternatives = model.supply_map.alternative_items(item_id)
        if not alternatives:
            continue
        alt_item_id = next(
            (
                alt_id
                for alt_id in alternatives
                if state.item_effective_status.get(alt_id, state.item_supply_status.get(alt_id)) != "unavailable"
            ),
            None,
        )
        if alt_item_id is None:
            continue
        if item_id not in state.substitution_pending:
            substitution_cost = _estimate_substitution_cost(
                item_id=item_id,
                alt_item_id=alt_item_id,
                model=model,
                policy=policy,
            )
            state.substitution_pending[item_id] = {
                "alt_item_id": alt_item_id,
                "activate_date": current_date + pd.Timedelta(days=max(policy.switch_time_days, 0)),
            }
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type=policy.policy_type,
                action="schedule_substitution",
                target_id=item_id,
                target_type="item",
                cost=substitution_cost,
                metadata={
                    "alt_item_id": alt_item_id,
                    "activate_date": state.substitution_pending[item_id]["activate_date"],
                },
            )

    for item_id, pending in list(state.substitution_pending.items()):
        if pending["activate_date"] <= current_date:
            state.substitution_active[item_id] = pending["alt_item_id"]
            del state.substitution_pending[item_id]
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type=policy.policy_type,
                action="activate_substitution",
                target_id=item_id,
                target_type="item",
                cost=float(policy.params.get("activation_cost", 0.0)),
                metadata={"alt_item_id": pending["alt_item_id"]},
            )


def _estimate_substitution_cost(
    item_id: str,
    alt_item_id: str,
    model: ModelBundle,
    policy: PolicySpec,
) -> float:
    items = model.standard_bundle.items.set_index("item_id")
    if item_id in items.index:
        base_demand = float(items.at[item_id, "avg_daily_demand"])
        base_cost = float(items.at[item_id, "material_cost"])
    else:
        base_demand = 1.0
        base_cost = 1.0
    alt_cost = float(items.at[alt_item_id, "material_cost"]) if alt_item_id in items.index else base_cost
    setup_cost = float(policy.params.get("setup_cost", 0.0))
    premium_factor = float(policy.params.get("material_premium_factor", 0.0))
    material_premium = max(alt_cost - base_cost, 0.0) * base_demand + alt_cost * base_demand * premium_factor
    return round(setup_cost + material_premium, 4)
