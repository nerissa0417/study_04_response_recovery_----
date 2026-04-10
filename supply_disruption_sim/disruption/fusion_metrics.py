from __future__ import annotations

import pandas as pd

from supply_disruption_sim.disruption.fusion_engine import FUSED_STATUS_TO_SERVICE_LEVEL
from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.types import ModelBundle


def build_fusion_daily_record(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> dict:
    fused_items = state.fused_state["items"]
    fused_products = state.fused_state["products"]
    fused_product_levels = [
        FUSED_STATUS_TO_SERVICE_LEVEL.get(status, 0.0) for status in fused_products.values()
    ]
    system_service_level = (
        round(sum(fused_product_levels) / len(fused_product_levels), 4) if fused_product_levels else 1.0
    )
    item_root_causes = state.fused_state["root_cause"].get("items", {})
    product_root_causes = state.fused_state["root_cause"].get("products", {})
    return {
        "date": current_date,
        "fused_active_items": sum(status == "active" for status in fused_items.values()),
        "fused_affected_items": sum(status == "affected" for status in fused_items.values()),
        "fused_failed_items": sum(status == "failed" for status in fused_items.values()),
        "fused_active_products": sum(status == "active" for status in fused_products.values()),
        "fused_affected_products": sum(status == "affected" for status in fused_products.values()),
        "fused_failed_products": sum(status == "failed" for status in fused_products.values()),
        "system_service_level": system_service_level,
        "system_root_cause": state.fused_state["root_cause"].get("system", "stable"),
        "root_cause_supply_constraint_items": sum(
            root_cause == "supply_constraint" for root_cause in item_root_causes.values()
        ),
        "root_cause_demand_items": sum(
            root_cause in {"demand_loss", "demand_backlog"} for root_cause in item_root_causes.values()
        ),
        "root_cause_mixed_items": sum(
            root_cause in {"mixed_failure", "mixed_pressure"} for root_cause in item_root_causes.values()
        ),
        "root_cause_supply_constraint_products": sum(
            root_cause == "supply_constraint" for root_cause in product_root_causes.values()
        ),
        "root_cause_demand_products": sum(
            root_cause in {"demand_loss", "demand_backlog"} for root_cause in product_root_causes.values()
        ),
        "root_cause_mixed_products": sum(
            root_cause in {"mixed_failure", "mixed_pressure"} for root_cause in product_root_causes.values()
        ),
    }


def build_fusion_item_records(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> list[dict]:
    records: list[dict] = []
    root_causes = state.fused_state["root_cause"].get("items", {})
    for item_id, fused_status in state.fused_state["items"].items():
        records.append(
            {
                "date": current_date,
                "item_id": item_id,
                "fused_status": fused_status,
                "fused_root_cause": root_causes.get(item_id, "stable"),
            }
        )
    return records


def summarize_fusion_history(history: pd.DataFrame) -> dict:
    if history.empty:
        return {}
    return {
        "max_fused_affected_items": int(history["fused_affected_items"].max()),
        "max_fused_failed_items": int(history["fused_failed_items"].max()),
        "avg_system_service_level": round(float(history["system_service_level"].mean()), 4),
        "min_system_service_level": round(float(history["system_service_level"].min()), 4),
        "dominant_root_cause_at_peak": str(
            history.loc[history["fused_failed_items"].idxmax(), "system_root_cause"]
        ),
    }


def build_fusion_impacted_paths(item_history: pd.DataFrame, model: ModelBundle) -> list[dict]:
    if item_history.empty:
        return []
    impacted_items = (
        item_history.loc[
            item_history["fused_status"].isin(["affected", "failed"]),
            ["item_id", "item_level", "fused_status", "fused_root_cause"],
        ]
        .drop_duplicates()
        .to_dict("records")
    )
    records: list[dict] = []
    for impacted in impacted_items:
        item_id = impacted["item_id"]
        item_level = impacted["item_level"]
        fused_status = impacted["fused_status"]
        fused_root_cause = impacted["fused_root_cause"]
        paths = model.bom_graph.paths_to_final_products(item_id)
        if not paths and item_level == "product":
            records.append(
                {
                    "impact_dimension": "fusion",
                    "impact_level": item_level,
                    "impact_status": fused_status,
                    "root_cause": fused_root_cause,
                    "item_id": item_id,
                    "path": item_id,
                }
            )
            continue
        for path in paths[:5]:
            records.append(
                {
                    "impact_dimension": "fusion",
                    "impact_level": item_level,
                    "impact_status": fused_status,
                    "root_cause": fused_root_cause,
                    "item_id": item_id,
                    "path": " -> ".join(path),
                }
            )
    return records
