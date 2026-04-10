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

    for item_id in model.standard_bundle.items["item_id"]:
        active_rows = model.supply_map.active_rows(item_id)
        if active_rows.empty:
            continue
        trigger_supply_factor = float(policy.params.get("trigger_supply_factor", 0.95))
        current_supply_factor = _estimate_current_supply_factor(active_rows=active_rows, state=state)
        if current_supply_factor >= trigger_supply_factor:
            state.backup_pending.pop(item_id, None)
            continue

        if item_id in state.backup_active and state.backup_active[item_id]["activate_date"] <= current_date:
            continue

        if item_id not in state.backup_pending:
            backup_rows = model.supply_map.backup_rows(item_id)
            if backup_rows.empty:
                continue
            selected = backup_rows.sort_values(
                by=["backup_priority", "qualified_rate", "avg_capacity", "switch_time_days", "supplier_id"],
                ascending=[True, False, False, True, True],
            ).iloc[0]
            delay = int(selected["switch_time_days"]) + int(selected["qualification_time_days"])
            delay = max(delay, policy.switch_time_days)
            switch_cost = _estimate_backup_switch_cost(
                item_id=item_id,
                selected=selected,
                model=model,
                policy=policy,
            )
            state.backup_pending[item_id] = {
                "supplier_id": selected["supplier_id"],
                "activate_date": current_date + pd.Timedelta(days=delay),
                "capacity_factor": float(selected["backup_capacity_factor"]),
                "backup_priority": int(selected.get("backup_priority", 99)),
                "supply_role": str(selected.get("supply_role", selected.get("mapping_origin", "backup"))),
            }
            record_policy_event(
                state=state,
                current_date=current_date,
                policy_type=policy.policy_type,
                action="schedule_backup_switch",
                target_id=item_id,
                target_type="item",
                cost=switch_cost,
                metadata={
                    "supplier_id": str(selected["supplier_id"]),
                    "activate_date": state.backup_pending[item_id]["activate_date"],
                    "supply_role": state.backup_pending[item_id]["supply_role"],
                },
            )

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
                metadata={"supplier_id": str(pending["supplier_id"])},
            )


def _estimate_current_supply_factor(active_rows: pd.DataFrame, state: SimState) -> float:
    if active_rows.empty:
        return 0.0
    shares = pd.to_numeric(active_rows["share"], errors="coerce").fillna(0.0)
    total_share = float(shares.sum())
    if total_share <= 0:
        shares = pd.Series([1.0 / len(active_rows.index)] * len(active_rows.index), index=active_rows.index)
    elif abs(total_share - 1.0) > 0.0001:
        shares = shares / total_share

    factor = 0.0
    for row_index, row in active_rows.iterrows():
        supplier_status = state.supplier_status.get(str(row["supplier_id"]), "available")
        if supplier_status == "disrupted":
            supplier_factor = 0.0
        elif supplier_status == "degraded":
            supplier_factor = 0.5
        else:
            supplier_factor = 1.0
        factor += float(shares.at[row_index]) * supplier_factor
    return max(0.0, min(factor, 1.0))


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
