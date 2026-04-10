from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.types import ModelBundle


def build_demand_daily_record(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> dict:
    product_demands = list(state.demand_state["products"].values())
    item_demands = list(state.demand_state["items"].values())
    total_requested = sum(float(entry["requested_demand"]) for entry in product_demands)
    total_fulfilled = sum(float(entry["fulfilled_demand"]) for entry in product_demands)
    total_backlog = sum(float(entry["backlog_demand"]) for entry in product_demands)
    total_lost = sum(float(entry["lost_demand"]) for entry in product_demands)
    demand_fulfillment_rate = total_fulfilled / total_requested if total_requested else 1.0
    return {
        "date": current_date,
        "total_requested_demand": total_requested,
        "total_fulfilled_demand": total_fulfilled,
        "total_backlog_demand": total_backlog,
        "total_lost_demand": total_lost,
        "demand_fulfillment_rate": round(demand_fulfillment_rate, 4),
        "demand_backlog_items": sum(entry["demand_status"] == "backlog" for entry in item_demands),
        "demand_lost_items": sum(entry["demand_status"] == "lost" for entry in item_demands),
        "demand_backlog_products": sum(entry["demand_status"] == "backlog" for entry in product_demands),
        "demand_lost_products": sum(entry["demand_status"] == "lost" for entry in product_demands),
    }


def build_demand_item_records(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> list[dict]:
    records: list[dict] = []
    for item_id, demand in state.demand_state["items"].items():
        records.append(
            {
                "date": current_date,
                "item_id": item_id,
                "requested_demand": float(demand["requested_demand"]),
                "fulfilled_demand": float(demand["fulfilled_demand"]),
                "backlog_demand": float(demand["backlog_demand"]),
                "lost_demand": float(demand["lost_demand"]),
                "demand_status": demand["demand_status"],
                "substitute_transfer_in": float(demand.get("substitute_transfer_in", 0.0)),
                "substitute_transfer_out": float(demand.get("substitute_transfer_out", 0.0)),
            }
        )
    return records


def summarize_demand_history(history: pd.DataFrame) -> dict:
    if history.empty:
        return {}
    return {
        "max_total_backlog_demand": round(float(history["total_backlog_demand"].max()), 4),
        "max_total_lost_demand": round(float(history["total_lost_demand"].max()), 4),
        "min_demand_fulfillment_rate": round(float(history["demand_fulfillment_rate"].min()), 4),
        "avg_demand_fulfillment_rate": round(float(history["demand_fulfillment_rate"].mean()), 4),
    }


def build_demand_impacted_paths(item_history: pd.DataFrame, model: ModelBundle) -> list[dict]:
    if item_history.empty:
        return []
    impacted_items = (
        item_history.loc[
            item_history["demand_status"].isin(["backlog", "lost"]),
            ["item_id", "item_level", "demand_status"],
        ]
        .drop_duplicates()
        .to_dict("records")
    )
    records: list[dict] = []
    for impacted in impacted_items:
        item_id = impacted["item_id"]
        item_level = impacted["item_level"]
        demand_status = impacted["demand_status"]
        paths = model.bom_graph.paths_to_final_products(item_id)
        if not paths and item_level == "product":
            records.append(
                {
                    "impact_dimension": "demand",
                    "impact_level": item_level,
                    "impact_status": demand_status,
                    "item_id": item_id,
                    "path": item_id,
                }
            )
            continue
        for path in paths[:5]:
            records.append(
                {
                    "impact_dimension": "demand",
                    "impact_level": item_level,
                    "impact_status": demand_status,
                    "item_id": item_id,
                    "path": " -> ".join(reversed(path)),
                }
            )
    return records
