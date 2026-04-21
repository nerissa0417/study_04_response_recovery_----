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

    candidates = collect_substitution_candidates(
        current_date=current_date,
        state=state,
        model=model,
        policy=policy,
    )
    for item_id, payload in candidates.items():
        schedule_substitution(
            current_date=current_date,
            state=state,
            model=model,
            policy=policy,
            item_id=item_id,
            payload=payload,
        )
    activate_due_substitutions(current_date=current_date, state=state, policy=policy)


def collect_substitution_candidates(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
) -> dict[str, dict]:
    candidates: dict[str, dict] = {}
    critical_items = model.standard_bundle.items.loc[
        model.standard_bundle.items["is_critical_material"], "item_id"
    ]
    for item_id in critical_items.astype(str):
        if state.item_supply_status.get(item_id) != "unavailable":
            state.substitution_pending.pop(item_id, None)
            continue
        if item_id in state.substitution_active or item_id in state.substitution_pending:
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
        activate_date = current_date + pd.Timedelta(days=max(policy.switch_time_days, 0))
        candidates[item_id] = {
            "policy_type": policy.policy_type,
            "alt_item_id": str(alt_item_id),
            "activate_date": activate_date,
            "delay_days": max(policy.switch_time_days, 0),
            "expected_effective_date": activate_date,
            "substitution_cost": _estimate_substitution_cost(
                item_id=item_id,
                alt_item_id=str(alt_item_id),
                model=model,
                policy=policy,
            ),
        }
    return candidates


def schedule_substitution(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
    item_id: str,
    payload: dict,
    strategy_role: str = "primary",
) -> None:
    if item_id in state.substitution_active or item_id in state.substitution_pending:
        return

    state.substitution_pending[item_id] = {
        "alt_item_id": str(payload["alt_item_id"]),
        "activate_date": pd.Timestamp(payload["activate_date"]).normalize(),
        "strategy_role": strategy_role,
    }
    record_policy_event(
        state=state,
        current_date=current_date,
        policy_type=policy.policy_type,
        action="schedule_substitution",
        target_id=item_id,
        target_type="item",
        cost=float(payload.get("substitution_cost", 0.0)),
        metadata={
            "alt_item_id": str(payload["alt_item_id"]),
            "activate_date": state.substitution_pending[item_id]["activate_date"],
            "strategy_role": strategy_role,
        },
    )


def activate_due_substitutions(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    policy: PolicySpec,
) -> None:
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
                metadata={
                    "alt_item_id": pending["alt_item_id"],
                    "strategy_role": str(pending.get("strategy_role", "primary")),
                },
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
