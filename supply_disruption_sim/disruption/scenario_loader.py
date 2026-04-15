from __future__ import annotations

from pathlib import Path
import copy
import random

import pandas as pd

from supply_disruption_sim.config import load_yaml_config
from supply_disruption_sim.labels import canonical_scenario_id, canonical_scenario_type
from supply_disruption_sim.types import ModelBundle, PolicySpec, ScenarioSpec, SimulationParams


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_TEMPLATE_PATH = PACKAGE_ROOT / "config" / "scenario_templates.yaml"


def load_scenario(template_name: str, model: ModelBundle) -> ScenarioSpec:
    scenarios = load_yaml_config("scenario_templates.yaml")["scenarios"]
    canonical_template_name = canonical_scenario_id(template_name)
    scenario_row = next(
        (
            row
            for row in scenarios
            if canonical_scenario_id(str(row["scenario_id"])) == canonical_template_name
        ),
        None,
    )
    if scenario_row is None:
        raise KeyError(f"Unknown scenario template: {template_name}")

    resolved_target = _resolve_auto_value(copy.deepcopy(scenario_row["target_id"]), model)
    resolved_extra = _resolve_auto_value(copy.deepcopy(scenario_row.get("extra", {})), model)
    scenario_type = canonical_scenario_type(str(scenario_row["scenario_type"]))

    target_id, scenario_extra = _normalize_scenario_target(
        scenario_type=scenario_type,
        resolved_target=resolved_target,
        resolved_extra=resolved_extra,
        model=model,
    )

    return ScenarioSpec(
        scenario_id=canonical_template_name,
        scenario_type=scenario_type,
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
        mode="bayesian",
        bayesian_enabled=bool(bayes_cfg.get("enabled", True)),
        bayesian_use_sampling=bool(bayes_cfg.get("use_sampling", False)),
        bayesian_random_seed=int(bayes_cfg.get("random_seed", 42)),
        bayesian_config=bayes_cfg,
    )


def _resolve_auto_value(value, model: ModelBundle):
    if isinstance(value, list):
        return [_resolve_auto_value(item, model) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_auto_value(item, model) for key, item in value.items()}
    if not isinstance(value, str):
        return value

    if value == "AUTO_KEY_SUPPLIERS":
        return _resolve_key_suppliers(model)
    return value


def _normalize_scenario_target(
    scenario_type: str,
    resolved_target,
    resolved_extra: dict,
    model: ModelBundle,
) -> tuple[str, dict]:
    scenario_extra = copy.deepcopy(resolved_extra)

    if scenario_type == "random_distributed_node_disruption":
        random_targets = _resolve_random_distributed_node_targets(model=model, config=scenario_extra)
        scenario_extra.update(random_targets)
        target_ids = random_targets["target_supplier_ids"] + random_targets["target_item_ids"]
        return ",".join(target_ids), scenario_extra

    if scenario_type in {"multi_supplier_disruption", "keynode_distributed_disruption"}:
        target_supplier_ids = resolved_target if isinstance(resolved_target, list) else str(resolved_target).split(",")
        target_supplier_ids = [str(supplier_id) for supplier_id in target_supplier_ids if str(supplier_id)]
        scenario_extra["target_supplier_ids"] = target_supplier_ids
        return ",".join(target_supplier_ids), scenario_extra

    return str(resolved_target), scenario_extra


def _resolve_key_suppliers(model: ModelBundle) -> list[str]:
    suppliers = model.standard_bundle.suppliers
    if "is_key_node" not in suppliers.columns:
        return []
    return sorted(
        suppliers.loc[suppliers["is_key_node"].astype(bool), "supplier_id"]
        .astype(str)
        .unique()
        .tolist()
    )


def _resolve_random_distributed_node_targets(model: ModelBundle, config: dict) -> dict:
    random_seed = int(config.get("random_seed", 42))
    desired_node_count = max(3, min(5, int(config.get("desired_node_count", 4))))
    supplier_node_count = max(1, int(config.get("supplier_node_count", 2)))
    item_node_count = max(1, int(config.get("item_node_count", 2)))
    rng = random.Random(random_seed)

    supplier_candidates = _build_random_supplier_candidates(model)
    item_candidates = _build_random_item_candidates(model)

    selected_suppliers = _select_diverse_supplier_candidates(
        supplier_candidates,
        count=min(supplier_node_count, len(supplier_candidates)),
        rng=rng,
    )
    selected_items = _select_diverse_item_candidates(
        item_candidates,
        count=min(item_node_count, len(item_candidates)),
        rng=rng,
    )

    selected_nodes = selected_suppliers + selected_items
    if len(selected_nodes) < desired_node_count:
        selected_nodes.extend(
            _fill_remaining_random_nodes(
                selected_nodes=selected_nodes,
                supplier_candidates=supplier_candidates,
                item_candidates=item_candidates,
                desired_node_count=desired_node_count,
                rng=rng,
            )
        )

    selected_nodes = selected_nodes[:desired_node_count]
    target_supplier_ids = [node["node_id"] for node in selected_nodes if node["node_type"] == "supplier"]
    target_item_ids = [node["node_id"] for node in selected_nodes if node["node_type"] == "item"]
    return {
        "random_seed": random_seed,
        "desired_node_count": desired_node_count,
        "target_supplier_ids": target_supplier_ids,
        "target_item_ids": target_item_ids,
        "selected_nodes": selected_nodes,
    }


def _build_random_supplier_candidates(model: ModelBundle) -> list[dict]:
    final_products = model.standard_bundle.metadata.get("final_product_ids", [])
    final_product_id = final_products[0] if final_products else None
    if final_product_id is None:
        return []

    ancestors = set(model.bom_graph.ancestors_of(final_product_id))
    suppliers = model.standard_bundle.suppliers.set_index("supplier_id")
    supply_rows = model.standard_bundle.supplier_item_map.loc[
        model.standard_bundle.supplier_item_map["item_id"].isin(ancestors)
        & (~model.standard_bundle.supplier_item_map["is_backup"].astype(bool))
    ].copy()
    if supply_rows.empty:
        return []

    scores = _supplier_impact_scores(model)
    sorted_scores = sorted(scores.values())
    cutoff_index = min(max(len(sorted_scores) // 3, 2), max(len(sorted_scores) - 1, 0))
    critical_cutoff = sorted_scores[-cutoff_index] if sorted_scores else float("inf")

    candidates: list[dict] = []
    for supplier_id, group in supply_rows.groupby("supplier_id", sort=False):
        supplier_id = str(supplier_id)
        if supplier_id not in suppliers.index:
            continue
        if bool(suppliers.at[supplier_id, "is_key_node"]):
            continue
        if scores.get(supplier_id, 0.0) >= critical_cutoff:
            continue
        branch_labels: set[str] = set()
        for item_id in group["item_id"].astype(str).tolist():
            branch_labels.update(_item_branch_labels(model, item_id))
        if not branch_labels:
            continue
        candidates.append(
            {
                "node_id": supplier_id,
                "node_type": "supplier",
                "item_level": "supplier",
                "branch_labels": sorted(branch_labels),
                "impact_score": round(float(scores.get(supplier_id, 0.0)), 4),
                "selection_basis": "noncritical_current_supplier",
            }
        )
    return candidates


def _build_random_item_candidates(model: ModelBundle) -> list[dict]:
    final_products = model.standard_bundle.metadata.get("final_product_ids", [])
    final_product_id = final_products[0] if final_products else None
    if final_product_id is None:
        return []

    ancestors = set(model.bom_graph.ancestors_of(final_product_id))
    items = model.standard_bundle.items.copy()
    candidates = items.loc[
        items["item_id"].isin(ancestors)
        & (~items["is_final_product"].astype(bool))
        & (~items["is_key_node"].astype(bool))
    ].copy()
    records: list[dict] = []
    for row in candidates.itertuples(index=False):
        branch_labels = sorted(_item_branch_labels(model, str(row.item_id)))
        if not branch_labels:
            continue
        records.append(
            {
                "node_id": str(row.item_id),
                "node_type": "item",
                "item_level": str(row.item_level),
                "branch_labels": branch_labels,
                "impact_score": round(float(getattr(row, "demand_priority", 0.0)), 4),
                "selection_basis": "noncritical_relevant_item",
            }
        )
    return records


def _select_diverse_supplier_candidates(candidates: list[dict], count: int, rng: random.Random) -> list[dict]:
    return _select_diverse_nodes(candidates, count=count, rng=rng, prefer_distinct_levels=False)


def _select_diverse_item_candidates(candidates: list[dict], count: int, rng: random.Random) -> list[dict]:
    return _select_diverse_nodes(candidates, count=count, rng=rng, prefer_distinct_levels=True)


def _select_diverse_nodes(
    candidates: list[dict],
    *,
    count: int,
    rng: random.Random,
    prefer_distinct_levels: bool,
) -> list[dict]:
    pool = [copy.deepcopy(candidate) for candidate in candidates]
    rng.shuffle(pool)
    selected: list[dict] = []
    used_levels: set[str] = set()
    used_branches: set[str] = set()

    while pool and len(selected) < count:
        best_index = 0
        best_score: tuple[int, int, float] | None = None
        for index, candidate in enumerate(pool):
            branch_gain = len(set(candidate["branch_labels"]) - used_branches)
            level_gain = 1 if prefer_distinct_levels and candidate["item_level"] not in used_levels else 0
            score = (level_gain, branch_gain, -float(candidate["impact_score"]))
            if best_score is None or score > best_score:
                best_index = index
                best_score = score
        chosen = pool.pop(best_index)
        selected.append(chosen)
        used_levels.add(str(chosen["item_level"]))
        used_branches.update(str(branch) for branch in chosen["branch_labels"])
    return selected


def _fill_remaining_random_nodes(
    *,
    selected_nodes: list[dict],
    supplier_candidates: list[dict],
    item_candidates: list[dict],
    desired_node_count: int,
    rng: random.Random,
) -> list[dict]:
    chosen_ids = {node["node_id"] for node in selected_nodes}
    pool = [copy.deepcopy(node) for node in (supplier_candidates + item_candidates) if node["node_id"] not in chosen_ids]
    rng.shuffle(pool)
    return pool[: max(0, desired_node_count - len(selected_nodes))]


def _supplier_impact_scores(model: ModelBundle) -> dict[str, float]:
    items = model.standard_bundle.items.set_index("item_id")
    scores: dict[str, float] = {}
    rows = model.standard_bundle.supplier_item_map.loc[
        ~model.standard_bundle.supplier_item_map["is_backup"].astype(bool)
    ]
    for supplier_id, group in rows.groupby("supplier_id", sort=False):
        score = 0.0
        for row in group.itertuples(index=False):
            item_id = str(row.item_id)
            if item_id not in items.index:
                continue
            score += float(items.at[item_id, "demand_priority"]) * max(float(row.share), 0.1)
            score += len(model.bom_graph.paths_to_final_products(item_id))
            if bool(items.at[item_id, "is_critical_material"]):
                score += 2.0
        scores[str(supplier_id)] = score
    return scores


def _item_branch_labels(model: ModelBundle, item_id: str) -> set[str]:
    labels: set[str] = set()
    for path in model.bom_graph.paths_to_final_products(item_id):
        if len(path) >= 2:
            labels.add(str(path[1]))
        elif path:
            labels.add(str(path[-1]))
    return labels
