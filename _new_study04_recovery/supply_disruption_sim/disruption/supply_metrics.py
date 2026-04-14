from __future__ import annotations

import pandas as pd

from supply_disruption_sim.model.state_model import SimState
from supply_disruption_sim.types import ModelBundle


def build_supply_daily_record(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> dict:
    supply_items = state.supply_state["items"]
    supply_assemblies = state.supply_state["assemblies"]
    supply_products = state.supply_state["products"]
    affected_products = [product_id for product_id, status in supply_products.items() if status != "active"]
    return {
        "date": current_date,
        "supply_available_items": sum(status == "available" for status in supply_items.values()),
        "supply_degraded_items": sum(status == "degraded" for status in supply_items.values()),
        "supply_unavailable_items": sum(status == "unavailable" for status in supply_items.values()),
        "supply_blocked_assemblies": sum(status == "blocked" for status in supply_assemblies.values()),
        "supply_affected_products": len(affected_products),
        "supply_failed_products": sum(status == "failed" for status in supply_products.values()),
    }


def build_supply_item_records(current_date: pd.Timestamp, state: SimState, model: ModelBundle) -> list[dict]:
    records: list[dict] = []
    item_info = model.standard_bundle.items.set_index("item_id")
    for item_id, row in item_info.iterrows():
        records.append(
            {
                "date": current_date,
                "item_id": item_id,
                "item_level": row["item_level"],
                "supply_status": state.item_supply_status.get(item_id, "unavailable"),
                "supply_effective_status": state.supply_state["items"].get(
                    item_id,
                    state.item_effective_status.get(item_id, "unavailable"),
                ),
                "assembly_status": state.assembly_status.get(item_id),
            }
        )
    return records


def summarize_supply_history(history: pd.DataFrame) -> dict:
    if history.empty:
        return {}
    return {
        "max_supply_degraded_items": int(history["supply_degraded_items"].max()),
        "max_supply_unavailable_items": int(history["supply_unavailable_items"].max()),
        "max_supply_blocked_assemblies": int(history["supply_blocked_assemblies"].max()),
        "max_supply_affected_products": int(history["supply_affected_products"].max()),
    }


def build_supply_impacted_paths(item_history: pd.DataFrame, model: ModelBundle) -> list[dict]:
    if item_history.empty:
        return []
    impacted_items = (
        item_history.loc[
            item_history["supply_effective_status"].isin(["degraded", "unavailable"]),
            ["item_id", "item_level"],
        ]
        .drop_duplicates()
        .to_dict("records")
    )
    records: list[dict] = []
    for impacted in impacted_items:
        item_id = impacted["item_id"]
        item_level = impacted["item_level"]
        paths = model.bom_graph.paths_to_final_products(item_id)
        if not paths and item_level == "product":
            records.append(
                {
                    "impact_dimension": "supply",
                    "impact_level": item_level,
                    "item_id": item_id,
                    "path": item_id,
                }
            )
            continue
        for path in paths[:5]:
            records.append(
                {
                    "impact_dimension": "supply",
                    "impact_level": item_level,
                    "item_id": item_id,
                    "path": " -> ".join(path),
                }
            )
    return records
