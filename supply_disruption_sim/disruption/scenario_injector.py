from __future__ import annotations

import pandas as pd

from supply_disruption_sim.types import ModelBundle, ScenarioSpec


def inject_scenario_for_day(
    current_date: pd.Timestamp,
    scenario: ScenarioSpec,
    model: ModelBundle,
) -> dict:
    del model
    active_window_end = scenario.start_date.normalize() + pd.Timedelta(days=scenario.duration_days - 1)
    if current_date < scenario.start_date.normalize() or current_date > active_window_end:
        return _empty_context()

    severity = float(scenario.severity)
    if scenario.scenario_type == "random_distributed_node_disruption":
        context = _empty_context()
        if severity >= 0.95:
            context["disrupted_suppliers"] = {str(supplier_id) for supplier_id in scenario.extra.get("target_supplier_ids", [])}
            context["disrupted_items"] = {str(item_id) for item_id in scenario.extra.get("target_item_ids", [])}
        else:
            context["degraded_suppliers"] = {
                str(supplier_id): max(0.0, 1.0 - severity)
                for supplier_id in scenario.extra.get("target_supplier_ids", [])
            }
            context["disrupted_items"] = {str(item_id) for item_id in scenario.extra.get("target_item_ids", [])}
        return context

    if scenario.scenario_type in {"multi_supplier_disruption", "keynode_distributed_disruption"}:
        target_supplier_ids = scenario.extra.get("target_supplier_ids", [])
        context = _empty_context()
        if severity >= 0.95:
            context["disrupted_suppliers"] = {str(supplier_id) for supplier_id in target_supplier_ids}
        else:
            context["degraded_suppliers"] = {
                str(supplier_id): max(0.0, 1.0 - severity) for supplier_id in target_supplier_ids
            }
        return context

    raise NotImplementedError(f"Unsupported scenario type: {scenario.scenario_type}")


def _empty_context() -> dict:
    return {
        "disrupted_suppliers": set(),
        "degraded_suppliers": {},
        "disrupted_items": set(),
        "disrupted_supply_edges": set(),
        "degraded_supply_edges": {},
    }
