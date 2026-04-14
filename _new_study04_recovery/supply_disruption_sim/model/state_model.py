from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from supply_disruption_sim.types import ModelBundle, ScenarioSpec, SimulationParams


@dataclass(slots=True)
class SimState:
    timeline: list[pd.Timestamp]
    scenario: ScenarioSpec
    params: SimulationParams
    supply_state: dict[str, dict]
    demand_state: dict[str, dict]
    fused_state: dict[str, dict]
    node_state: dict[str, dict]
    edge_state: dict[str, dict]
    supplier_status: dict[str, str]
    item_inventory: dict[str, float]
    item_supply_status: dict[str, str]
    item_effective_status: dict[str, str]
    assembly_status: dict[str, str]
    product_status: dict[str, str]
    backlog_age_days: dict[str, int] = field(default_factory=dict)
    backup_pending: dict[str, dict] = field(default_factory=dict)
    backup_active: dict[str, dict] = field(default_factory=dict)
    substitution_pending: dict[str, dict] = field(default_factory=dict)
    substitution_active: dict[str, str] = field(default_factory=dict)
    repair_pending_suppliers: dict[str, dict] = field(default_factory=dict)
    repair_active_suppliers: set[str] = field(default_factory=set)
    repair_pending_items: dict[str, dict] = field(default_factory=dict)
    repair_active_items: set[str] = field(default_factory=set)
    repair_log: list[dict] = field(default_factory=list)
    policy_event_log: list[dict] = field(default_factory=list)
    policy_cost_by_date: dict[pd.Timestamp, dict[str, float]] = field(default_factory=dict)
    policy_cost_totals: dict[str, float] = field(default_factory=dict)


def initialize_state(
    model: ModelBundle,
    scenario: ScenarioSpec,
    params: SimulationParams,
) -> SimState:
    items = model.standard_bundle.items
    suppliers = model.standard_bundle.suppliers
    start_date = scenario.start_date.normalize()
    timeline = [start_date + pd.Timedelta(days=offset) for offset in range(params.horizon_days)]
    item_inventory = items.set_index("item_id")["initial_inventory_qty"].astype(float).to_dict()
    supplier_status = {supplier_id: "available" for supplier_id in suppliers["supplier_id"]}
    item_supply_status = {item_id: "available" for item_id in items["item_id"]}
    item_effective_status = {item_id: "available" for item_id in items["item_id"]}
    assembly_status: dict[str, str] = {}
    product_status = {
        item_id: "active"
        for item_id in items.loc[items["is_final_product"], "item_id"]
    }
    demand_item_state = {
        row.item_id: {
            "requested_demand": float(row.default_requested_demand),
            "fulfilled_demand": float(row.default_requested_demand),
            "backlog_demand": 0.0,
            "lost_demand": 0.0,
            "demand_status": "stable",
            "demand_priority": int(row.demand_priority),
            "substitute_transfer_in": 0.0,
            "substitute_transfer_out": 0.0,
        }
        for row in items.itertuples(index=False)
    }
    demand_product_state = {
        product_id: {
            "requested_demand": float(
                items.loc[items["item_id"] == product_id, "default_requested_demand"].iloc[0]
            ),
            "fulfilled_demand": float(
                items.loc[items["item_id"] == product_id, "default_requested_demand"].iloc[0]
            ),
            "backlog_demand": 0.0,
            "lost_demand": 0.0,
            "demand_status": "stable",
        }
        for product_id in product_status
    }
    node_state = _initialize_node_state(items=items, suppliers=suppliers)
    edge_state = _initialize_edge_state(model=model)
    return SimState(
        timeline=timeline,
        scenario=scenario,
        params=params,
        supply_state={
            "suppliers": supplier_status,
            "items": item_supply_status,
            "assemblies": assembly_status,
            "products": product_status,
        },
        demand_state={
            "items": demand_item_state,
            "products": demand_product_state,
        },
        fused_state={
            "items": item_effective_status,
            "products": product_status,
            "root_cause": {},
        },
        node_state=node_state,
        edge_state=edge_state,
        supplier_status=supplier_status,
        item_inventory=item_inventory,
        item_supply_status=item_supply_status,
        item_effective_status=item_effective_status,
        assembly_status=assembly_status,
        product_status=product_status,
        backlog_age_days={str(item_id): 0 for item_id in items["item_id"].astype(str).tolist()},
    )


def _initialize_node_state(items: pd.DataFrame, suppliers: pd.DataFrame) -> dict[str, dict]:
    node_state: dict[str, dict] = {}
    for row in suppliers.itertuples(index=False):
        node_state[f"supplier:{row.supplier_id}"] = {
            "node_id": row.supplier_id,
            "node_type": row.node_type,
            "label": getattr(row, "supplier_name", row.supplier_id),
            "display_id": row.supplier_id,
            "is_key_node": bool(getattr(row, "is_key_node", False)),
            "critical_tier": getattr(row, "critical_tier", "general"),
            "critical_score": float(getattr(row, "critical_score", 0.0)),
            "critical_reason": getattr(row, "critical_reason", ""),
            "supply_status": row.supply_state_default,
            "demand_status": row.demand_state_default,
            "fused_status": row.fused_state_default,
            "visual_status": row.visual_status_default,
        }
    for row in items.itertuples(index=False):
        node_state[f"item:{row.item_id}"] = {
            "node_id": row.item_id,
            "node_type": row.node_type,
            "label": getattr(row, "item_name", row.item_id),
            "display_id": row.item_id,
            "is_key_node": bool(getattr(row, "is_key_node", False)),
            "critical_tier": getattr(row, "critical_tier", "general"),
            "critical_score": float(getattr(row, "critical_score", 0.0)),
            "critical_reason": getattr(row, "critical_reason", ""),
            "supply_status": row.supply_state_default,
            "demand_status": row.demand_state_default,
            "fused_status": row.fused_state_default,
            "visual_status": row.visual_status_default,
        }
    return node_state


def _initialize_edge_state(model: ModelBundle) -> dict[str, dict]:
    edge_state: dict[str, dict] = {}
    for row in model.standard_bundle.supplier_edges.itertuples(index=False):
        edge_state[f"supplier_edge:{row.edge_id}"] = {
            "edge_id": row.edge_id,
            "edge_type": row.edge_type,
            "source_id": row.source_supplier_id,
            "target_id": row.target_supplier_id,
            "status": row.edge_status_default,
        }
    for row in model.standard_bundle.bom_edges.itertuples(index=False):
        edge_state[f"bom_edge:{row.bom_id}"] = {
            "edge_id": row.bom_id,
            "edge_type": row.edge_type,
            "source_id": row.child_item_id,
            "target_id": row.parent_item_id,
            "status": row.edge_status_default,
        }
    for row in model.standard_bundle.supplier_item_map.itertuples(index=False):
        edge_key = f"supply_edge:{row.supplier_id}:{row.item_id}"
        edge_state[edge_key] = {
            "edge_id": edge_key,
            "edge_type": row.edge_type,
            "source_id": row.supplier_id,
            "target_id": row.item_id,
            "status": row.edge_status_default,
        }
    for row in model.standard_bundle.part_alternatives.itertuples(index=False):
        edge_state[f"alt_edge:{row.alternative_id}"] = {
            "edge_id": row.alternative_id,
            "edge_type": row.edge_type,
            "source_id": row.item_id,
            "target_id": row.alt_item_id,
            "status": row.edge_status_default,
        }
    return edge_state


def update_supplier_node_state(state: SimState, supplier_id: str, supply_status: str) -> None:
    node = state.node_state.get(f"supplier:{supplier_id}")
    if node is None:
        return
    node["supply_status"] = supply_status
    node["visual_status"] = supply_status


def update_item_node_state(
    state: SimState,
    item_id: str,
    *,
    supply_status: str | None = None,
    demand_status: str | None = None,
    fused_status: str | None = None,
) -> None:
    node = state.node_state.get(f"item:{item_id}")
    if node is None:
        return
    if supply_status is not None:
        node["supply_status"] = supply_status
    if demand_status is not None:
        node["demand_status"] = demand_status
    if fused_status is not None:
        node["fused_status"] = fused_status
        node["visual_status"] = _map_fused_to_visual_status(fused_status)


def update_item_demand_node_state(
    state: SimState,
    item_id: str,
    demand_status: str,
) -> None:
    item_node = state.node_state.get(f"item:{item_id}")
    if item_node is None:
        return
    item_node["demand_status"] = demand_status


def update_item_root_cause(state: SimState, item_id: str, root_cause: str) -> None:
    state.fused_state["root_cause"].setdefault("items", {})[item_id] = root_cause


def update_product_root_cause(state: SimState, product_id: str, root_cause: str) -> None:
    state.fused_state["root_cause"].setdefault("products", {})[product_id] = root_cause


def update_edge_status(state: SimState, edge_key: str, status: str) -> None:
    edge = state.edge_state.get(edge_key)
    if edge is None:
        return
    edge["status"] = status


def _map_fused_to_visual_status(fused_status: str) -> str:
    return {
        "active": "available",
        "affected": "affected",
        "failed": "blocked",
    }.get(fused_status, fused_status)
