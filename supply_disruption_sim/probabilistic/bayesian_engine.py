from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.types import ModelBundle, ScenarioSpec


class BayesianEngine:
    def __init__(self, config: dict[str, Any] | None = None, *, use_sampling: bool = False, random_seed: int = 42):
        self.config = config or {}
        self.use_sampling = bool(use_sampling)
        self.rng = np.random.default_rng(int(random_seed))

    def apply_supplier_network_propagation(
        self,
        *,
        current_date: pd.Timestamp,
        state: SimState,
        model: ModelBundle,
        context: dict,
        scenario: ScenarioSpec,
    ) -> dict:
        patched = {
            "disrupted_suppliers": set(context.get("disrupted_suppliers", set())),
            "degraded_suppliers": dict(context.get("degraded_suppliers", {})),
            "material_shortages": set(context.get("material_shortages", set())),
            "disrupted_supply_edges": set(context.get("disrupted_supply_edges", set())),
            "degraded_supply_edges": dict(context.get("degraded_supply_edges", {})),
        }
        suppliers = model.standard_bundle.suppliers.set_index("supplier_id")
        source_statuses = {
            **{str(supplier_id): "disrupted" for supplier_id in patched["disrupted_suppliers"]},
            **{str(supplier_id): "degraded" for supplier_id in patched["degraded_suppliers"]},
        }
        for supplier_id, status in state.supplier_status.items():
            supplier_id = str(supplier_id)
            if supplier_id in state.repair_active_suppliers:
                continue
            if supplier_id in source_statuses:
                continue
            if status in {"disrupted", "degraded"}:
                source_statuses[supplier_id] = status

        for source_id, source_status in list(source_statuses.items()):
            if source_id in state.repair_active_suppliers:
                continue
            for target_id in sorted(model.supplier_graph.neighbors(source_id)):
                if target_id == source_id or target_id in state.repair_active_suppliers:
                    continue
                if target_id in patched["disrupted_suppliers"] or target_id in patched["degraded_suppliers"]:
                    continue
                if target_id not in suppliers.index:
                    continue

                p = self.supplier_network_propagation_probability(
                    supplier_row=suppliers.loc[target_id],
                    source_status=source_status,
                    scenario=scenario,
                    current_date=current_date,
                )
                propagated = bool(self.rng.binomial(1, p)) if self.use_sampling else p >= self._degrade_threshold()
                if not propagated:
                    continue

                if source_status == "disrupted" and p >= self._disrupt_threshold():
                    patched["disrupted_suppliers"].add(target_id)
                    patched["degraded_suppliers"].pop(target_id, None)
                else:
                    patched["degraded_suppliers"][target_id] = max(
                        self._propagated_degrade_floor(),
                        1.0 - p,
                    )
        return patched

    def edge_propagation_probability(
        self,
        *,
        state: SimState,
        item_row,
        supplier_id: str,
        item_id: str,
        supplier_factor: float,
        has_backup: bool,
    ) -> float:
        cfg = self.config.get("edge_propagation", {})
        supplier_status = state.supplier_status.get(supplier_id, "available")
        base = float(cfg.get("disrupted_base", 0.9)) if supplier_status == "disrupted" else float(cfg.get("degraded_base", 0.55))
        inventory = float(state.item_inventory.get(item_id, 0.0))
        avg_daily_demand = max(float(getattr(item_row, "avg_daily_demand", 1.0)), 1.0)
        inventory_days = inventory / avg_daily_demand if avg_daily_demand > 0 else 0.0
        low_inventory_days = float(cfg.get("low_inventory_days_threshold", 3.0))
        if inventory_days < low_inventory_days:
            base += float(cfg.get("low_inventory_bonus", 0.15))
        if not has_backup:
            base += float(cfg.get("no_backup_bonus", 0.10))
        if bool(getattr(item_row, "is_key_node", False)):
            base += float(cfg.get("key_node_bonus", 0.20))
        if supplier_factor >= 0.95:
            base *= 0.25
        return self._clip_probability(base)

    def edge_interruption_factor(
        self,
        *,
        state: SimState,
        item_row,
        supplier_id: str,
        item_id: str,
        supplier_factor: float,
        has_backup: bool,
    ) -> float:
        supplier_factor = float(supplier_factor)
        if supplier_factor >= 0.95:
            return supplier_factor
        p = self.edge_propagation_probability(
            state=state,
            item_row=item_row,
            supplier_id=supplier_id,
            item_id=item_id,
            supplier_factor=supplier_factor,
            has_backup=has_backup,
        )
        threshold = float(self.config.get("edge_propagation", {}).get("propagation_threshold", 0.5))
        if not self._propagation_occurs(p, threshold=threshold):
            return 1.0
        if supplier_factor <= 0.0:
            return 0.0
        return max(0.0, min(supplier_factor, 1.0 - p))

    def supplier_network_propagation_probability(
        self,
        *,
        supplier_row,
        source_status: str,
        scenario: ScenarioSpec,
        current_date: pd.Timestamp,
    ) -> float:
        cfg = self.config.get("supplier_network_propagation", {})
        base = (
            float(cfg.get("disrupted_base", 0.45))
            if source_status == "disrupted"
            else float(cfg.get("degraded_base", 0.22))
        )

        severity = float(getattr(scenario, "severity", 1.0))
        severity_multiplier = 0.75 + 0.5 * max(0.0, min(severity, 1.0))
        base *= severity_multiplier

        compliance_rate = float(supplier_row.get("compliance_rate", 1.0))
        qms_rate = float(supplier_row.get("qms_rate", 1.0))
        default_rate = float(supplier_row.get("default_rate", 0.0))
        resilience = (compliance_rate + qms_rate + max(0.0, 1.0 - default_rate)) / 3.0
        vulnerability = max(0.0, 1.0 - resilience)
        base += vulnerability * float(cfg.get("resilience_penalty", 0.25))

        if str(supplier_row.get("risk_level", "medium")) == "high":
            base += float(cfg.get("high_risk_bonus", 0.10))
        if bool(supplier_row.get("is_key_node", False)):
            base += float(cfg.get("key_node_bonus", 0.10))
        return self._clip_probability(base)

    def _propagation_occurs(self, probability: float, *, threshold: float) -> bool:
        p = self._clip_probability(probability)
        if self.use_sampling:
            return bool(self.rng.binomial(1, p))
        return p >= threshold

    def _disrupt_threshold(self) -> float:
        return float(self.config.get("supplier_network_propagation", {}).get("disrupt_threshold", 0.7))

    def _degrade_threshold(self) -> float:
        return float(self.config.get("supplier_network_propagation", {}).get("degrade_threshold", 0.35))

    def _propagated_degrade_floor(self) -> float:
        return float(self.config.get("supplier_network_propagation", {}).get("propagated_degrade_floor", 0.25))

    @staticmethod
    def _clip_probability(value: float) -> float:
        if math.isnan(value):
            return 0.0
        return max(0.0, min(float(value), 1.0))
