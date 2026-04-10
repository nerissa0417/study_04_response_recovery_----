from __future__ import annotations

import pandas as pd

from supply_disruption_sim.disruption.demand_metrics import (
    build_demand_daily_record,
    build_demand_impacted_paths,
    build_demand_item_records,
    summarize_demand_history,
)
from supply_disruption_sim.disruption.fusion_metrics import (
    build_fusion_daily_record,
    build_fusion_impacted_paths,
    build_fusion_item_records,
    summarize_fusion_history,
)
from supply_disruption_sim.disruption.supply_metrics import (
    build_supply_daily_record,
    build_supply_impacted_paths,
    build_supply_item_records,
    summarize_supply_history,
)
from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.policy.tracking import build_policy_daily_metrics, summarize_policy_events
from supply_disruption_sim.types import ModelBundle, ScenarioSpec, SimulationResult


SERVICE_LEVEL_MAP = {"active": 1.0, "affected": 0.5, "failed": 0.0}
BACKLOG_VALUE_DISCOUNT = 0.35


def build_daily_record(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> dict:
    final_product_id = next(iter(state.product_status), None)
    product_status = state.product_status.get(final_product_id, "failed") if final_product_id else "failed"
    items = model.standard_bundle.items.set_index("item_id")
    suppliers = model.standard_bundle.suppliers.set_index("supplier_id")
    key_item_ids = set(items.index[items["is_key_node"] == True].tolist()) if "is_key_node" in items else set()
    key_supplier_ids = set(suppliers.index[suppliers["is_key_node"] == True].tolist()) if "is_key_node" in suppliers else set()

    record = {
        "date": current_date,
        "active_suppliers": sum(status == "available" for status in state.supplier_status.values()),
        "disrupted_suppliers": sum(status == "disrupted" for status in state.supplier_status.values()),
        "degraded_suppliers": sum(status == "degraded" for status in state.supplier_status.values()),
        "final_product_id": final_product_id,
        "final_product_status": product_status,
        "service_level": SERVICE_LEVEL_MAP.get(product_status, 0.0),
        "active_backup_switches": len(state.backup_active),
        "active_substitutions": len(state.substitution_active),
        "affected_key_items": sum(
            item_id in key_item_ids and status in {"degraded", "unavailable"}
            for item_id, status in state.item_effective_status.items()
        ),
        "failed_key_items": sum(
            item_id in key_item_ids and status == "unavailable"
            for item_id, status in state.item_effective_status.items()
        ),
        "disrupted_key_suppliers": sum(
            supplier_id in key_supplier_ids and status == "disrupted"
            for supplier_id, status in state.supplier_status.items()
        ),
        "degraded_key_suppliers": sum(
            supplier_id in key_supplier_ids and status == "degraded"
            for supplier_id, status in state.supplier_status.items()
        ),
    }
    record.update(build_supply_daily_record(current_date=current_date, state=state, model=model))
    record.update(build_demand_daily_record(current_date=current_date, state=state, model=model))
    record.update(build_fusion_daily_record(current_date=current_date, state=state, model=model))
    record.update(build_policy_daily_metrics(current_date=current_date, state=state))
    return record


def build_item_records(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> list[dict]:
    records: list[dict] = []
    item_info = model.standard_bundle.items.set_index("item_id")
    supply_records = {
        record["item_id"]: record
        for record in build_supply_item_records(current_date=current_date, state=state, model=model)
    }
    demand_records = {
        record["item_id"]: record
        for record in build_demand_item_records(current_date=current_date, state=state, model=model)
    }
    fusion_records = {
        record["item_id"]: record
        for record in build_fusion_item_records(current_date=current_date, state=state, model=model)
    }
    for item_id in item_info.index:
        supply_record = supply_records[item_id]
        demand_record = demand_records[item_id]
        fusion_record = fusion_records[item_id]
        records.append(
            {
                "date": current_date,
                "item_id": item_id,
                "item_name": item_info.at[item_id, "item_name"],
                "item_level": supply_record["item_level"],
                "is_key_node": bool(item_info.at[item_id, "is_key_node"]) if "is_key_node" in item_info.columns else False,
                "critical_tier": item_info.at[item_id, "critical_tier"] if "critical_tier" in item_info.columns else "general",
                "critical_score": float(item_info.at[item_id, "critical_score"]) if "critical_score" in item_info.columns else 0.0,
                "critical_reason": item_info.at[item_id, "critical_reason"] if "critical_reason" in item_info.columns else "",
                "inventory_qty": state.item_inventory[item_id],
                "supply_status": state.item_supply_status.get(item_id, "unavailable"),
                "supply_effective_status": supply_record["supply_effective_status"],
                "assembly_status": supply_record["assembly_status"],
                "requested_demand": demand_record["requested_demand"],
                "fulfilled_demand": demand_record["fulfilled_demand"],
                "backlog_demand": demand_record["backlog_demand"],
                "lost_demand": demand_record["lost_demand"],
                "demand_status": demand_record["demand_status"],
                "substitute_transfer_in": demand_record["substitute_transfer_in"],
                "substitute_transfer_out": demand_record["substitute_transfer_out"],
                "fused_status": fusion_record["fused_status"],
                "fused_root_cause": fusion_record["fused_root_cause"],
                "effective_status": state.item_effective_status.get(item_id, "unavailable"),
                "backup_supplier_id": state.backup_active.get(item_id, {}).get("supplier_id"),
                "substitute_item_id": state.substitution_active.get(item_id),
            }
        )
    return records


def summarize_result(
    scenario: ScenarioSpec,
    history: pd.DataFrame,
    item_history: pd.DataFrame,
    model: ModelBundle,
    policy_events: list[dict] | None = None,
) -> tuple[dict, list[dict]]:
    final_product_id = history["final_product_id"].dropna().iloc[0]
    failed_history = history.loc[history["final_product_status"] == "failed", "date"]
    ttr = None
    for _, row in history.iterrows():
        if row["date"] >= scenario.start_date.normalize() and row["final_product_status"] == "active":
            ttr = int((row["date"] - scenario.start_date.normalize()).days)
            break

    summary = {
        "scenario_id": scenario.scenario_id,
        "target_id": scenario.target_id,
        "final_product_id": final_product_id,
        "ttr_days": ttr,
        "failed_days": int((history["final_product_status"] == "failed").sum()),
        "affected_days": int((history["final_product_status"] == "affected").sum()),
        "average_service_level": round(float(history["service_level"].mean()), 4),
        "max_supply_effective_affected_items": int(history["supply_effective_affected_items"].max()),
        "max_supply_effective_unavailable_items": int(history["supply_effective_unavailable_items"].max()),
        "max_affected_key_items": int(history["affected_key_items"].max()) if "affected_key_items" in history else 0,
        "max_failed_key_items": int(history["failed_key_items"].max()) if "failed_key_items" in history else 0,
        "max_disrupted_key_suppliers": int(history["disrupted_key_suppliers"].max()) if "disrupted_key_suppliers" in history else 0,
        "first_failure_date": str(failed_history.iloc[0].date()) if not failed_history.empty else None,
    }
    summary.update(summarize_supply_history(history))
    summary.update(summarize_demand_history(history))
    summary.update(summarize_fusion_history(history))
    summary.update(summarize_policy_events(policy_events or []))
    summary.update(_estimate_policy_economics(history=history, model=model))
    impacted_paths = _build_impacted_paths(item_history, model)
    return summary, impacted_paths


def build_simulation_result(
    scenario: ScenarioSpec,
    history_records: list[dict],
    item_records: list[dict],
    model: ModelBundle,
    policy_events: list[dict] | None = None,
) -> SimulationResult:
    history = pd.DataFrame(history_records)
    item_history = pd.DataFrame(item_records)
    summary, impacted_paths = summarize_result(
        scenario,
        history,
        item_history,
        model,
        policy_events=policy_events or [],
    )
    return SimulationResult(
        scenario=scenario,
        history=history,
        item_history=item_history,
        summary=summary,
        impacted_paths=impacted_paths,
        model_bundle=model,
        policy_events=list(policy_events or []),
    )


def _build_impacted_paths(item_history: pd.DataFrame, model: ModelBundle) -> list[dict]:
    return (
        build_supply_impacted_paths(item_history=item_history, model=model)
        + build_demand_impacted_paths(item_history=item_history, model=model)
        + build_fusion_impacted_paths(item_history=item_history, model=model)
    )


def _estimate_policy_economics(history: pd.DataFrame, model: ModelBundle) -> dict:
    if history.empty or "total_fulfilled_demand" not in history.columns:
        return {}

    items = model.standard_bundle.items.set_index("item_id")
    final_product_ids = history["final_product_id"].dropna().tolist() if "final_product_id" in history else []
    final_product_id = final_product_ids[0] if final_product_ids else None
    if final_product_id and final_product_id in items.index:
        unit_value = float(items.at[final_product_id, "material_cost"])
    else:
        unit_value = float(items["material_cost"].replace(0, pd.NA).dropna().mean()) if "material_cost" in items else 1.0
    if pd.isna(unit_value) or unit_value <= 0:
        unit_value = 1.0

    fulfilled_value = float(history["total_fulfilled_demand"].sum()) * unit_value
    lost_value = float(history["total_lost_demand"].sum()) if "total_lost_demand" in history else 0.0
    lost_value *= unit_value
    backlog_penalty = (
        float(history["total_backlog_demand"].sum()) * unit_value * BACKLOG_VALUE_DISCOUNT
        if "total_backlog_demand" in history
        else 0.0
    )
    disruption_loss = lost_value + backlog_penalty
    benefit_estimate = max(fulfilled_value - disruption_loss, 0.0)
    policy_total_cost = float(history["policy_cumulative_cost"].max()) if "policy_cumulative_cost" in history else 0.0

    return {
        "economic_unit_value": round(unit_value, 4),
        "estimated_fulfilled_value": round(fulfilled_value, 4),
        "estimated_lost_value": round(lost_value, 4),
        "estimated_backlog_penalty": round(backlog_penalty, 4),
        "estimated_disruption_loss": round(disruption_loss, 4),
        "estimated_policy_benefit": round(benefit_estimate, 4),
        "policy_cost_benefit_ratio": (
            round(benefit_estimate / policy_total_cost, 4) if policy_total_cost > 0 else None
        ),
    }
