from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.backup_supplier_switch import (
    activate_due_backup_switches,
    collect_backup_switch_candidates,
    schedule_backup_switch,
)
from supply_disruption_sim.policy.equivalent_material_substitution import (
    activate_due_substitutions,
    collect_substitution_candidates,
    schedule_substitution,
)
from supply_disruption_sim.policy.priority_repair import (
    activate_due_repairs,
    apply_priority_repair,
    schedule_priority_repairs_from_state,
)
from supply_disruption_sim.types import ModelBundle, PolicySpec


TIME_PRIORITY_RECOVERY_MODE = "time_priority_interrupt"


class PolicyManager:
    def __init__(self, policies: list[PolicySpec]) -> None:
        self.policies = [policy for policy in policies if policy.enabled]
        self.policy_map = {policy.policy_type: policy for policy in self.policies}
        self.recovery_mode = next(
            (
                str(policy.params.get("recovery_mode"))
                for policy in self.policies
                if policy.params.get("recovery_mode")
            ),
            "default",
        )

    def enabled_policy_types(self) -> list[str]:
        return [policy.policy_type for policy in self.policies]

    def apply_pre(self, current_date: pd.Timestamp, state: SimState, model: ModelBundle, context: dict) -> None:
        if self.recovery_mode == TIME_PRIORITY_RECOVERY_MODE:
            if "priority_repair" in self.policy_map:
                activate_due_repairs(current_date=current_date, state=state)
            return

        for policy in self.policies:
            if policy.policy_type == "priority_repair":
                apply_priority_repair(current_date, state, model, policy, context)

    def apply_post(self, current_date: pd.Timestamp, state: SimState, model: ModelBundle, context: dict | None = None) -> None:
        if self.recovery_mode == TIME_PRIORITY_RECOVERY_MODE:
            self._apply_time_priority_recovery(current_date=current_date, state=state, model=model)
            return

        for policy in self.policies:
            if policy.policy_type == "backup_supplier_switch":
                from supply_disruption_sim.policy.backup_supplier_switch import apply_backup_supplier_switch

                apply_backup_supplier_switch(current_date, state, model, policy)
            elif policy.policy_type == "equivalent_material_substitution":
                from supply_disruption_sim.policy.equivalent_material_substitution import apply_equivalent_material_substitution

                apply_equivalent_material_substitution(current_date, state, model, policy)

    def _apply_time_priority_recovery(
        self,
        *,
        current_date: pd.Timestamp,
        state: SimState,
        model: ModelBundle,
    ) -> None:
        backup_policy = self.policy_map.get("backup_supplier_switch")
        substitution_policy = self.policy_map.get("equivalent_material_substitution")
        repair_policy = self.policy_map.get("priority_repair")

        if backup_policy is not None:
            activate_due_backup_switches(current_date=current_date, state=state, policy=backup_policy)
        if substitution_policy is not None:
            activate_due_substitutions(current_date=current_date, state=state, policy=substitution_policy)

        backup_candidates = (
            collect_backup_switch_candidates(
                current_date=current_date,
                state=state,
                model=model,
                policy=backup_policy,
            )
            if backup_policy is not None
            else {}
        )
        substitution_candidates = (
            collect_substitution_candidates(
                current_date=current_date,
                state=state,
                model=model,
                policy=substitution_policy,
            )
            if substitution_policy is not None
            else {}
        )

        item_ids = sorted(set(backup_candidates) | set(substitution_candidates))
        for item_id in item_ids:
            existing_types = set()
            if item_id in state.backup_active or item_id in state.backup_pending:
                existing_types.add("backup_supplier_switch")
            if item_id in state.substitution_active or item_id in state.substitution_pending:
                existing_types.add("equivalent_material_substitution")

            candidates: list[dict] = []
            if item_id in substitution_candidates and "equivalent_material_substitution" not in existing_types:
                candidates.append(substitution_candidates[item_id])
            if item_id in backup_candidates and "backup_supplier_switch" not in existing_types:
                candidates.append(backup_candidates[item_id])
            if not candidates:
                continue

            selected = min(candidates, key=_mitigation_sort_key)
            strategy_role = "primary" if not existing_types else "secondary"
            if selected["policy_type"] == "equivalent_material_substitution" and substitution_policy is not None:
                schedule_substitution(
                    current_date=current_date,
                    state=state,
                    model=model,
                    policy=substitution_policy,
                    item_id=item_id,
                    payload=selected,
                    strategy_role=strategy_role,
                )
            elif selected["policy_type"] == "backup_supplier_switch" and backup_policy is not None:
                schedule_backup_switch(
                    current_date=current_date,
                    state=state,
                    model=model,
                    policy=backup_policy,
                    item_id=item_id,
                    payload=selected,
                    strategy_role=strategy_role,
                )

        if repair_policy is not None:
            schedule_priority_repairs_from_state(
                current_date=current_date,
                state=state,
                model=model,
                policy=repair_policy,
            )


def _mitigation_sort_key(payload: dict) -> tuple[pd.Timestamp, int]:
    policy_type = str(payload.get("policy_type") or "")
    order = {
        "equivalent_material_substitution": 0,
        "backup_supplier_switch": 1,
    }
    return (
        pd.Timestamp(payload.get("expected_effective_date") or payload.get("activate_date")),
        order.get(policy_type, 99),
    )
