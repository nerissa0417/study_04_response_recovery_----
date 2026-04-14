from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.backup_supplier_switch import apply_backup_supplier_switch
from supply_disruption_sim.policy.equivalent_material_substitution import (
    apply_equivalent_material_substitution,
)
from supply_disruption_sim.policy.priority_repair import apply_priority_repair
from supply_disruption_sim.types import ModelBundle, PolicySpec


class PolicyManager:
    def __init__(self, policies: list[PolicySpec]) -> None:
        self.policies = [policy for policy in policies if policy.enabled]

    def enabled_policy_types(self) -> list[str]:
        return [policy.policy_type for policy in self.policies]

    def apply_pre(self, current_date: pd.Timestamp, state: SimState, model: ModelBundle, context: dict) -> None:
        for policy in self.policies:
            if policy.policy_type == "priority_repair":
                apply_priority_repair(current_date, state, model, policy, context)

    def apply_post(self, current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> None:
        for policy in self.policies:
            if policy.policy_type == "backup_supplier_switch":
                apply_backup_supplier_switch(current_date, state, model, policy)
            elif policy.policy_type == "equivalent_material_substitution":
                apply_equivalent_material_substitution(current_date, state, model, policy)
