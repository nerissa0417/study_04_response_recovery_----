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

    def apply_disruption_occurrence(
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
        for supplier_id in list(patched["disrupted_suppliers"]):
            if supplier_id not in suppliers.index:
                continue
            p = self.disruption_probability(suppliers.loc[supplier_id], scenario, current_date)
            if self.use_sampling:
                if not self.rng.binomial(1, p):
                    patched["disrupted_suppliers"].discard(supplier_id)
                    patched["degraded_suppliers"][supplier_id] = max(0.25, 1.0 - p)
            else:
                if p < 0.5:
                    patched["disrupted_suppliers"].discard(supplier_id)
                    patched["degraded_suppliers"][supplier_id] = max(0.25, 1.0 - p)
        return patched

    def apply_supplier_network_propagation(
        self,
        *,
        context: dict,
        state: SimState,
        model: ModelBundle,
    ) -> dict:
        patched = {
            "disrupted_suppliers": set(context.get("disrupted_suppliers", set())),
            "degraded_suppliers": dict(context.get("degraded_suppliers", {})),
            "material_shortages": set(context.get("material_shortages", set())),
            "disrupted_supply_edges": set(context.get("disrupted_supply_edges", set())),
            "degraded_supply_edges": dict(context.get("degraded_supply_edges", {})),
        }
        supplier_edges = model.standard_bundle.supplier_edges
        if supplier_edges.empty:
            return patched

        suppliers = model.standard_bundle.suppliers.set_index("supplier_id")
        cfg = self.config.get("supplier_network_propagation", {})
        degrade_threshold = float(cfg.get("degrade_threshold", 0.35))
        disrupt_threshold = float(cfg.get("disrupt_threshold", 0.8))
        min_capacity = float(cfg.get("min_capacity_factor", 0.25))

        max_depth = max(len(supplier_edges), 1)
        for _ in range(max_depth):
            changed = False
            current_disrupted = set(patched["disrupted_suppliers"])
            current_degraded = dict(patched["degraded_suppliers"])
            for row in supplier_edges.itertuples(index=False):
                source_supplier_id = str(row.source_supplier_id)
                target_supplier_id = str(row.target_supplier_id)
                if source_supplier_id == target_supplier_id:
                    continue
                if source_supplier_id in current_disrupted:
                    source_status = "disrupted"
                elif source_supplier_id in current_degraded:
                    source_status = "degraded"
                else:
                    continue
                if target_supplier_id in patched["disrupted_suppliers"]:
                    continue

                target_row = suppliers.loc[target_supplier_id] if target_supplier_id in suppliers.index else None
                p = self.supplier_network_propagation_probability(
                    source_status=source_status,
                    target_supplier_row=target_row,
                )
                if not self._propagation_occurs(p, threshold=degrade_threshold):
                    continue

                if source_status == "disrupted" and p >= disrupt_threshold:
                    patched["degraded_suppliers"].pop(target_supplier_id, None)
                    patched["disrupted_suppliers"].add(target_supplier_id)
                    changed = True
                else:
                    capacity_factor = max(min_capacity, 1.0 - p)
                    previous = float(patched["degraded_suppliers"].get(target_supplier_id, 1.0))
                    next_factor = min(previous, capacity_factor)
                    if target_supplier_id not in patched["degraded_suppliers"] or next_factor < previous:
                        patched["degraded_suppliers"][target_supplier_id] = next_factor
                        changed = True
            if not changed:
                break
        return patched

    def disruption_probability(self, supplier_row, scenario: ScenarioSpec, current_date: pd.Timestamp) -> float:
        cfg = self.config.get("disruption", {})
        p = float(cfg.get("prior", 0.15))
        risk_level_factor = cfg.get("risk_level_factor", {})
        p *= float(risk_level_factor.get(str(supplier_row.get("risk_level", "medium")), 1.0))
        p *= 1 + float(cfg.get("incident_weight", 0.15)) * float(supplier_row.get("historical_incident_count", 0.0))
        p *= 1 + float(cfg.get("severity_weight", 1.2)) * float(getattr(scenario, "severity", 1.0))
        p *= 1 + float(cfg.get("compliance_penalty", 0.4)) * (1 - float(supplier_row.get("compliance_rate", 1.0)))
        p *= 1 + float(cfg.get("qms_penalty", 0.25)) * (1 - float(supplier_row.get("qms_rate", 1.0)))
        return self._clip_probability(p)

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
        source_status: str,
        target_supplier_row,
    ) -> float:
        cfg = self.config.get("supplier_network_propagation", {})
        base = (
            float(cfg.get("disrupted_base", 0.45))
            if source_status == "disrupted"
            else float(cfg.get("degraded_base", 0.22))
        )
        if target_supplier_row is not None:
            resilience = (
                float(target_supplier_row.get("compliance_rate", 1.0))
                + float(target_supplier_row.get("qms_rate", 1.0))
                + max(0.0, 1.0 - float(target_supplier_row.get("default_rate", 0.0)))
            ) / 3.0
            if resilience < 0.75:
                base += float(cfg.get("low_resilience_bonus", 0.15))
            if float(target_supplier_row.get("historical_incident_count", 0.0)) >= 2:
                base += float(cfg.get("high_incident_bonus", 0.08))
            if bool(target_supplier_row.get("is_key_node", False)):
                base += float(cfg.get("key_supplier_bonus", 0.12))
        return self._clip_probability(base)

    def _propagation_occurs(self, probability: float, *, threshold: float) -> bool:
        p = self._clip_probability(probability)
        if self.use_sampling:
            return bool(self.rng.binomial(1, p))
        return p >= threshold

    @staticmethod
    def _clip_probability(value: float) -> float:
        if math.isnan(value):
            return 0.0
        return max(0.0, min(float(value), 1.0))
