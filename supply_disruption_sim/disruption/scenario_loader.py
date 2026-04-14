from __future__ import annotations

from pathlib import Path

import copy
import pandas as pd

from supply_disruption_sim.config import load_yaml_config
from supply_disruption_sim.types import ModelBundle, PolicySpec, ScenarioSpec, SimulationParams


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_TEMPLATE_PATH = PACKAGE_ROOT / "config" / "scenario_templates.yaml"


def load_scenario(template_name: str, model: ModelBundle) -> ScenarioSpec:
    if template_name.startswith("historical:"):
        incident_key = template_name.split(":", 1)[1]
        return _load_historical_scenario(incident_key, model)

    scenarios = load_yaml_config("scenario_templates.yaml")["scenarios"]
    scenario_row = next((row for row in scenarios if row["scenario_id"] == template_name), None)
    if scenario_row is None:
        raise KeyError(f"Unknown scenario template: {template_name}")

    resolved_target = _resolve_auto_value(copy.deepcopy(scenario_row["target_id"]), model)
    resolved_extra = _resolve_auto_value(copy.deepcopy(scenario_row.get("extra", {})), model)

    target_id, scenario_extra = _normalize_scenario_target(
        scenario_type=str(scenario_row["scenario_type"]),
        resolved_target=resolved_target,
        resolved_extra=resolved_extra,
    )

    return ScenarioSpec(
        scenario_id=scenario_row["scenario_id"],
        scenario_type=scenario_row["scenario_type"],
        target_type=scenario_row["target_type"],
        target_id=str(target_id),
        start_date=pd.Timestamp(scenario_row["start_date"]),
        duration_days=int(scenario_row["duration_days"]),
        severity=float(scenario_row.get("severity", 1.0)),
        description=str(scenario_row.get("description", "")),
        extra=scenario_extra,
    )


def load_default_policies() -> list[PolicySpec]:
    config = load_yaml_config("default_params.yaml")
    return [
        PolicySpec(
            policy_type="backup_supplier_switch",
            enabled=bool(config["backup_supplier_switch"]["enabled"]),
            switch_time_days=int(config["backup_supplier_switch"]["switch_time_days"]),
            params={
                "backup_capacity_factor": float(config["backup_supplier_switch"]["backup_capacity_factor"]),
                "setup_cost": float(config["backup_supplier_switch"].get("setup_cost", 0.0)),
                "qualification_cost_per_day": float(
                    config["backup_supplier_switch"].get("qualification_cost_per_day", 0.0)
                ),
                "activation_cost": float(config["backup_supplier_switch"].get("activation_cost", 0.0)),
            },
        ),
        PolicySpec(
            policy_type="equivalent_material_substitution",
            enabled=bool(config["equivalent_material_substitution"]["enabled"]),
            switch_time_days=int(config["equivalent_material_substitution"]["switch_time_days"]),
            params={
                "alt_capacity_factor": float(config["equivalent_material_substitution"]["alt_capacity_factor"]),
                "setup_cost": float(config["equivalent_material_substitution"].get("setup_cost", 0.0)),
                "activation_cost": float(config["equivalent_material_substitution"].get("activation_cost", 0.0)),
                "material_premium_factor": float(
                    config["equivalent_material_substitution"].get("material_premium_factor", 0.0)
                ),
            },
        ),
        PolicySpec(
            policy_type="priority_repair",
            enabled=bool(config["priority_repair"]["enabled"]),
            switch_time_days=int(config["priority_repair"]["repair_lead_days"]),
            priority_rule=str(config["priority_repair"]["priority_rule"]),
            params={
                "max_parallel_repairs": int(config["priority_repair"]["max_parallel_repairs"]),
                "supplier_repair_cost": float(config["priority_repair"].get("supplier_repair_cost", 0.0)),
                "material_repair_cost": float(config["priority_repair"].get("material_repair_cost", 0.0)),
                "activation_cost": float(config["priority_repair"].get("activation_cost", 0.0)),
                "key_node_bonus_weight": float(config["priority_repair"].get("key_node_bonus_weight", 3.0)),
            },
        ),
    ]


def load_default_params(model: ModelBundle) -> SimulationParams:
    config = load_yaml_config("default_params.yaml")
    final_products = model.standard_bundle.metadata.get("final_product_ids", [])
    bayes_cfg = copy.deepcopy(config.get("bayesian_model", {}))
    return SimulationParams(
        time_step=str(config["time_step"]),
        horizon_days=int(config["horizon_days"]),
        inventory_buffer_rule=str(config["inventory_buffer_rule"]),
        record_item_history=bool(config["record_item_history"]),
        target_final_product_id=final_products[0] if final_products else None,
        enable_supply_tracking=bool(config["enable_supply_tracking"]),
        enable_demand_tracking=bool(config["enable_demand_tracking"]),
        enable_fusion_tracking=bool(config["enable_fusion_tracking"]),
        track_network_state=bool(config["track_network_state"]),
        demand_backlog_threshold=float(config["demand_model"]["backlog_threshold"]),
        demand_lost_threshold=float(config["demand_model"]["lost_threshold"]),
        backlog_retention_ratio=float(config["demand_model"]["backlog_retention_ratio"]),
        fusion_failure_supply_states=tuple(config["fusion_model"]["failure_supply_states"]),
        fusion_failure_demand_states=tuple(config["fusion_model"]["failure_demand_states"]),
        fusion_affected_supply_states=tuple(config["fusion_model"]["affected_supply_states"]),
        fusion_affected_demand_states=tuple(config["fusion_model"]["affected_demand_states"]),
        priority_repair_enabled=bool(config["priority_repair"]["enabled"]),
        priority_repair_lead_days=int(config["priority_repair"]["repair_lead_days"]),
        priority_repair_max_parallel=int(config["priority_repair"]["max_parallel_repairs"]),
        priority_repair_rule=str(config["priority_repair"]["priority_rule"]),
        priority_repair_key_node_bonus_weight=float(config["priority_repair"].get("key_node_bonus_weight", 3.0)),
        mode=str(bayes_cfg.get("mode", "deterministic")),
        bayesian_enabled=bool(bayes_cfg.get("enabled", False) or str(bayes_cfg.get("mode", "deterministic")) == "bayesian"),
        bayesian_use_sampling=bool(bayes_cfg.get("use_sampling", False)),
        bayesian_random_seed=int(bayes_cfg.get("random_seed", 42)),
        bayesian_config=bayes_cfg,
    )


def _load_historical_scenario(incident_key: str, model: ModelBundle) -> ScenarioSpec:
    incidents = model.standard_bundle.incident_events
    row = incidents.loc[
        (incidents["incident_id"] == incident_key)
        | (incidents["supplier_incident_id"] == incident_key)
    ]
    if row.empty:
        raise KeyError(f"Historical incident not found: {incident_key}")
    record = row.iloc[0]
    return ScenarioSpec(
        scenario_id=f"historical_{record['supplier_incident_id']}",
        scenario_type="historical_supplier_incident",
        target_type="supplier",
        target_id=str(record["supplier_id"]),
        start_date=pd.Timestamp(record["start_date"]),
        duration_days=int(record["resolved_duration_days"]),
        severity=float(record["severity"]),
        description=str(record["event_type"]),
        extra={"incident_id": str(record["incident_id"])} ,
    )


def _resolve_default_material_target(model: ModelBundle) -> str:
    final_products = model.standard_bundle.metadata.get("final_product_ids", [])
    final_product_id = final_products[0] if final_products else None
    candidates = model.standard_bundle.items.copy()
    if final_product_id is not None:
        ancestors = set(model.bom_graph.ancestors_of(final_product_id))
        candidates = candidates.loc[candidates["item_id"].isin(ancestors)]
    candidates = candidates.sort_values(
        by=["is_key_node", "is_critical_material", "demand_priority", "avg_daily_demand", "initial_inventory_qty"],
        ascending=[False, False, False, False, True],
    )
    if candidates.empty:
        raise ValueError("Cannot resolve AUTO_CRITICAL_PATH_ITEM from standardized items.")
    return str(candidates.iloc[0]["item_id"])


def _resolve_auto_value(value, model: ModelBundle):
    if isinstance(value, list):
        return [_resolve_auto_value(item, model) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_auto_value(item, model) for key, item in value.items()}
    if not isinstance(value, str):
        return value

    if value == "AUTO_PRIMARY_SUPPLIER_ON_FINAL_PATH":
        target_id = model.standard_bundle.metadata.get("default_disruption_supplier_id")
        if target_id is None:
            raise ValueError("Cannot resolve AUTO_PRIMARY_SUPPLIER_ON_FINAL_PATH without standardized metadata.")
        return str(target_id)
    if value == "AUTO_REGION_OF_DEFAULT_SUPPLIER":
        default_supplier_id = model.standard_bundle.metadata.get("default_disruption_supplier_id")
        if default_supplier_id is None:
            raise ValueError("Cannot resolve AUTO_REGION_OF_DEFAULT_SUPPLIER without standardized metadata.")
        supplier_row = model.standard_bundle.suppliers.loc[
            model.standard_bundle.suppliers["supplier_id"] == default_supplier_id
        ]
        if supplier_row.empty:
            raise ValueError(f"Default supplier '{default_supplier_id}' not found in standardized suppliers.")
        return str(supplier_row.iloc[0]["region_id"])
    if value == "AUTO_CRITICAL_PATH_ITEM":
        return _resolve_default_material_target(model)
    if value == "AUTO_FINAL_PATH_SUPPLIERS":
        return _resolve_final_path_suppliers(model)
    if value == "AUTO_DEFAULT_SUPPLY_EDGE":
        return _resolve_default_supply_edge(model)
    return value


def _normalize_scenario_target(
    scenario_type: str,
    resolved_target,
    resolved_extra: dict,
) -> tuple[str, dict]:
    scenario_extra = copy.deepcopy(resolved_extra)

    if scenario_type == "multi_supplier_disruption":
        target_supplier_ids = resolved_target if isinstance(resolved_target, list) else str(resolved_target).split(",")
        target_supplier_ids = [str(supplier_id) for supplier_id in target_supplier_ids if str(supplier_id)]
        scenario_extra["target_supplier_ids"] = target_supplier_ids
        return ",".join(target_supplier_ids), scenario_extra

    if scenario_type == "supply_edge_disruption":
        if isinstance(resolved_target, dict):
            supplier_id = str(resolved_target["supplier_id"])
            item_id = str(resolved_target["item_id"])
        else:
            supplier_id, item_id = [segment.strip() for segment in str(resolved_target).split(":", 1)]
        scenario_extra["supply_edge"] = {"supplier_id": supplier_id, "item_id": item_id}
        return f"{supplier_id}:{item_id}", scenario_extra

    if scenario_type == "region_disruption":
        scenario_extra["region_id"] = str(resolved_target)
        return str(resolved_target), scenario_extra

    return str(resolved_target), scenario_extra


def _resolve_final_path_suppliers(model: ModelBundle) -> list[str]:
    final_products = model.standard_bundle.metadata.get("final_product_ids", [])
    final_product_id = final_products[0] if final_products else None
    if final_product_id is None:
        return []
    ancestors = set(model.bom_graph.ancestors_of(final_product_id))
    rows = model.standard_bundle.supplier_item_map.loc[
        model.standard_bundle.supplier_item_map["item_id"].isin(ancestors)
        & model.standard_bundle.supplier_item_map["is_primary"]
    ]
    return sorted(rows["supplier_id"].astype(str).unique().tolist())


def _resolve_default_supply_edge(model: ModelBundle) -> dict[str, str]:
    supplier_id = model.standard_bundle.metadata.get("default_disruption_supplier_id")
    if supplier_id is None:
        raise ValueError("Cannot resolve AUTO_DEFAULT_SUPPLY_EDGE without standardized metadata.")
    primary_rows = model.standard_bundle.supplier_item_map.loc[
        (model.standard_bundle.supplier_item_map["supplier_id"] == supplier_id)
        & model.standard_bundle.supplier_item_map["is_primary"].astype(bool)
    ]
    rows = (primary_rows if not primary_rows.empty else model.standard_bundle.supplier_item_map.loc[
        model.standard_bundle.supplier_item_map["supplier_id"] == supplier_id
    ]).sort_values(
        by=["share", "is_primary"],
        ascending=[False, False],
    )
    if rows.empty:
        raise ValueError(f"Supplier '{supplier_id}' has no standardized supply edges.")
    row = rows.iloc[0]
    return {"supplier_id": str(row["supplier_id"]), "item_id": str(row["item_id"])}
