from __future__ import annotations

import pandas as pd

from supply_disruption_sim.types import ModelBundle, ScenarioSpec


def inject_scenario_for_day(
    current_date: pd.Timestamp,
    scenario: ScenarioSpec,
    model: ModelBundle,
) -> dict:
    active_window_end = scenario.start_date.normalize() + pd.Timedelta(days=scenario.duration_days - 1)
    if current_date < scenario.start_date.normalize() or current_date > active_window_end:
        return _empty_context()

    severity = float(scenario.severity)
    if scenario.scenario_type in {"single_supplier_disruption", "historical_supplier_incident"}:
        if severity >= 0.95:
            context = _empty_context()
            context["disrupted_suppliers"] = {scenario.target_id}
            return context
        context = _empty_context()
        context["degraded_suppliers"] = {scenario.target_id: max(0.0, 1.0 - severity)}
        return context

    if scenario.scenario_type == "multi_supplier_disruption":
        target_supplier_ids = scenario.extra.get("target_supplier_ids", [])
        context = _empty_context()
        if severity >= 0.95:
            context["disrupted_suppliers"] = {str(supplier_id) for supplier_id in target_supplier_ids}
        else:
            context["degraded_suppliers"] = {
                str(supplier_id): max(0.0, 1.0 - severity) for supplier_id in target_supplier_ids
            }
        return context

    if scenario.scenario_type == "region_disruption":
        region_suppliers = set(model.supplier_graph.suppliers_in_region(scenario.target_id))
        if severity >= 0.95:
            context = _empty_context()
            context["disrupted_suppliers"] = region_suppliers
            return context
        context = _empty_context()
        context["degraded_suppliers"] = {
            supplier_id: max(0.0, 1.0 - severity) for supplier_id in region_suppliers
        }
        return context

    if scenario.scenario_type == "material_shortage":
        context = _empty_context()
        context["material_shortages"] = {scenario.target_id}
        return context

    if scenario.scenario_type == "supply_edge_disruption":
        context = _empty_context()
        target = scenario.extra.get("supply_edge_target", {})
        supplier_id = str(target.get("supplier_id"))
        item_id = str(target.get("item_id"))
        if severity >= 0.95:
            context["disrupted_supply_edges"] = {(supplier_id, item_id)}
        else:
            context["degraded_supply_edges"] = {(supplier_id, item_id): max(0.0, 1.0 - severity)}
        return context

    if scenario.scenario_type == "progressive_supplier_disruption":
        return _build_progressive_supplier_context(current_date=current_date, scenario=scenario)

    raise NotImplementedError(f"Unsupported scenario type: {scenario.scenario_type}")


def _build_progressive_supplier_context(current_date: pd.Timestamp, scenario: ScenarioSpec) -> dict:
    context = _empty_context()
    day_offset = int((current_date.normalize() - scenario.start_date.normalize()).days)
    phases = scenario.extra.get("phases", [])
    elapsed = 0
    for phase in phases:
        duration_days = int(phase.get("duration_days", 0))
        if duration_days <= 0:
            continue
        phase_end = elapsed + duration_days
        if day_offset >= phase_end:
            elapsed = phase_end
            continue

        phase_type = str(phase.get("phase_type", "degraded"))
        if phase_type == "disrupted":
            context["disrupted_suppliers"] = {scenario.target_id}
            return context
        if phase_type == "degraded":
            context["degraded_suppliers"] = {
                scenario.target_id: float(phase.get("capacity_factor", max(0.0, 1.0 - scenario.severity)))
            }
            return context
        if phase_type == "recovering":
            local_offset = day_offset - elapsed
            start_capacity = float(phase.get("start_capacity_factor", 0.3))
            end_capacity = float(phase.get("end_capacity_factor", 0.9))
            if duration_days == 1:
                capacity_factor = end_capacity
            else:
                progress = local_offset / (duration_days - 1)
                capacity_factor = start_capacity + (end_capacity - start_capacity) * progress
            context["degraded_suppliers"] = {scenario.target_id: round(min(max(capacity_factor, 0.0), 1.0), 4)}
            return context
        elapsed = phase_end
    return context


def _empty_context() -> dict:
    return {
        "disrupted_suppliers": set(),
        "degraded_suppliers": {},
        "material_shortages": set(),
        "disrupted_supply_edges": set(),
        "degraded_supply_edges": {},
    }
