from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.tracking import record_policy_event
from supply_disruption_sim.types import ModelBundle, PolicySpec


def apply_backup_supplier_switch(
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
) -> None:
    if not policy.enabled:
        return

    candidates = collect_backup_switch_candidates(
        current_date=current_date,
        state=state,
        model=model,
        policy=policy,
    )
    for item_id, payload in candidates.items():
        schedule_backup_switch(
            current_date=current_date,
            state=state,
            model=model,
            policy=policy,
            item_id=item_id,
            payload=payload,
        )
    activate_due_backup_switches(current_date=current_date, state=state, policy=policy)


def collect_backup_switch_candidates(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
) -> dict[str, dict]:
    candidates: dict[str, dict] = {}
    for item_id in model.standard_bundle.items["item_id"].astype(str):
        primary_rows = model.supply_map.primary_rows(item_id)
        if primary_rows.empty:
            continue
        primary_disrupted = primary_rows["supplier_id"].map(state.supplier_status.get).eq("disrupted").all()
        if not primary_disrupted:
            state.backup_pending.pop(item_id, None)
            continue
        if item_id in state.backup_active or item_id in state.backup_pending:
            continue

        backup_rows = model.supply_map.backup_rows(item_id)
        if backup_rows.empty:
            continue

        selected = backup_rows.sort_values(
            by=["mapping_origin", "qualified_rate", "avg_capacity"],
            ascending=[True, False, False],
        ).iloc[0]
        delay = int(selected["switch_time_days"]) + int(selected["qualification_time_days"])
        delay = max(delay, policy.switch_time_days)
        activate_date = current_date + pd.Timedelta(days=delay)
        candidates[item_id] = {
            "policy_type": policy.policy_type,
            "supplier_id": str(selected["supplier_id"]),
            "activate_date": activate_date,
            "capacity_factor": float(selected["backup_capacity_factor"]),
            "delay_days": delay,
            "expected_effective_date": activate_date,
            "switch_cost": _estimate_backup_switch_cost(
                item_id=item_id,
                selected=selected,
                model=model,
                policy=policy,
            ),
        }
    return candidates


def schedule_backup_switch(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    model: ModelBundle,
    policy: PolicySpec,
    item_id: str,
    payload: dict,
    strategy_role: str = "primary",
) -> None:
    if item_id in state.backup_active or item_id in state.backup_pending:
        return

    state.backup_pending[item_id] = {
        "supplier_id": str(payload["supplier_id"]),
        "activate_date": pd.Timestamp(payload["activate_date"]).normalize(),
        "capacity_factor": float(payload["capacity_factor"]),
        "strategy_role": strategy_role,
    }
    record_policy_event(
        state=state,
        current_date=current_date,
        policy_type=policy.policy_type,
        action="schedule_backup_switch",
        target_id=item_id,
        target_type="item",
        cost=float(payload.get("switch_cost", 0.0)),
        metadata={
            "supplier_id": str(payload["supplier_id"]),
            "activate_date": state.backup_pending[item_id]["activate_date"],
            "strategy_role": strategy_role,
        },
    )


def activate_due_backup_switches(
    *,
    current_date: pd.Timestamp,
    state: SimState,
    policy: PolicySpec,
) -> None:
    for item_id, pending in list(state.backup_pending.items()):
        if pending["activate_date"] <= current_date:
            state.backup_active[item_id] = pending
            del state.backup_pending[item_id]
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type=policy.policy_type,
                action="activate_backup_switch",
                target_id=item_id,
                target_type="item",
                cost=float(policy.params.get("activation_cost", 0.0)),
                metadata={
                    "supplier_id": str(pending["supplier_id"]),
                    "strategy_role": str(pending.get("strategy_role", "primary")),
                },
            )


def _estimate_backup_switch_cost(item_id: str, selected: pd.Series, model: ModelBundle, policy: PolicySpec) -> float:
    items = model.standard_bundle.items.set_index("item_id")
    if item_id in items.index:
        unit_cost = float(items.at[item_id, "material_cost"])
        avg_daily_demand = float(items.at[item_id, "avg_daily_demand"])
    else:
        unit_cost = 1.0
        avg_daily_demand = 1.0
    capacity_gap = max(0.0, 1.0 - float(selected["backup_capacity_factor"]))
    setup_cost = float(policy.params.get("setup_cost", 0.0))
    qualification_cost = (
        float(selected["qualification_time_days"]) * float(policy.params.get("qualification_cost_per_day", 0.0))
    )
    capacity_penalty = avg_daily_demand * unit_cost * capacity_gap * 0.1
    return round(setup_cost + qualification_cost + capacity_penalty, 4)
