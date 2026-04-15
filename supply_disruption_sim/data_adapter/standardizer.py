from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pandas as pd
import yaml

from supply_disruption_sim.config import load_yaml_config
from supply_disruption_sim.types import RawBundle, StandardBundle


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "default_params.yaml"


def standardize(raw_bundle: RawBundle, rules: dict | None = None) -> StandardBundle:
    config = load_yaml_config("default_params.yaml")
    if rules:
        config.update(rules)
    visualization_config = load_yaml_config("visualization.yaml")

    tables = raw_bundle.tables
    suppliers = _standardize_suppliers(tables)
    supplier_edges = _standardize_supplier_edges(tables)
    items = _standardize_items(tables, config)
    bom_edges = _standardize_bom_edges(tables)
    supply_map = _standardize_supply_map(tables, config)
    part_alternatives = _standardize_part_alternatives(tables)
    supplier_materials = _standardize_supplier_materials(tables)
    supplier_production_plan = _standardize_supplier_production_plan(tables)
    supplier_licensed_supply = _standardize_supplier_licensed_supply(tables)
    supplier_potential_supply = _standardize_supplier_potential_supply(tables)
    supplier_daily_inventory = _standardize_supplier_daily_inventory(tables)
    supplier_material_flow_events = _standardize_supplier_material_flow_events(tables)
    supplier_material_inventory_policy = _standardize_supplier_material_inventory_policy(tables)
    critical_nodes = _load_optional_critical_nodes(raw_bundle.source_dir)
    incident_events = _standardize_incident_events(tables, config)
    items = _enrich_items(items=items, bom_edges=bom_edges, config=config)
    suppliers = _enrich_suppliers(suppliers)
    items, suppliers = _apply_critical_node_labels(
        items=items,
        suppliers=suppliers,
        critical_nodes=critical_nodes,
        config=config,
    )
    supplier_edges = _enrich_supplier_edges(supplier_edges)
    bom_edges = _enrich_bom_edges(bom_edges)
    supply_map = _enrich_supply_map(supply_map)
    external_supply_meta = _summarize_supply_map_item_levels(
        items=items,
        bom_edges=bom_edges,
        supply_map=supply_map,
    )
    part_alternatives = _enrich_part_alternatives(part_alternatives)

    supply_map, augmentation_meta = _augment_backup_cases(
        items=items,
        bom_edges=bom_edges,
        suppliers=suppliers,
        supply_map=supply_map,
        config=config,
    )

    final_products = items.loc[items["is_final_product"], "item_id"].tolist()
    metadata = {
        "source_dir": str(raw_bundle.source_dir),
        "final_product_ids": final_products,
        "augmented_backup_items": augmentation_meta["augmented_backup_items"],
        "external_supply_item_levels": external_supply_meta["external_supply_item_levels"],
        "external_supply_items_with_bom": external_supply_meta["external_supply_items_with_bom"],
        "critical_node_file": critical_nodes.attrs.get("source_filename") if critical_nodes is not None else None,
        "critical_item_ids": items.loc[items["is_key_node"], "item_id"].astype(str).tolist(),
        "critical_supplier_ids": suppliers.loc[suppliers["is_key_node"], "supplier_id"].astype(str).tolist(),
        "new_input_tables_loaded": sorted(tables.keys()),
        "standardized_optional_tables": {
            "supplier_materials": len(supplier_materials),
            "supplier_production_plan": len(supplier_production_plan),
            "supplier_licensed_supply": len(supplier_licensed_supply),
            "supplier_potential_supply": len(supplier_potential_supply),
            "supplier_daily_inventory": len(supplier_daily_inventory),
            "supplier_material_flow_events": len(supplier_material_flow_events),
            "supplier_material_inventory_policy": len(supplier_material_inventory_policy),
        },
        "config": config,
        "visualization": visualization_config,
        "status_schema": {
            "supply": ["available", "degraded", "disrupted", "unavailable", "blocked"],
            "demand": ["stable", "backlog", "lost"],
            "fused": ["active", "affected", "failed"],
        },
    }

    return StandardBundle(
        suppliers=suppliers,
        supplier_edges=supplier_edges,
        items=items,
        bom_edges=bom_edges,
        supplier_item_map=supply_map,
        part_alternatives=part_alternatives,
        incident_events=incident_events,
        supplier_materials=supplier_materials,
        supplier_production_plan=supplier_production_plan,
        supplier_licensed_supply=supplier_licensed_supply,
        supplier_potential_supply=supplier_potential_supply,
        supplier_daily_inventory=supplier_daily_inventory,
        supplier_material_flow_events=supplier_material_flow_events,
        supplier_material_inventory_policy=supplier_material_inventory_policy,
        metadata=metadata,
    )


def export_standard_bundle(bundle: StandardBundle, output_dir: str | Path) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    table_paths: dict[str, Path] = {}
    for table_name, frame in bundle.as_dict().items():
        path = output_path / f"{table_name}.csv"
        frame.to_csv(path, index=False)
        table_paths[table_name] = path

    metadata_path = output_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(bundle.metadata, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    table_paths["metadata"] = metadata_path
    return table_paths


def _estimate_observation_window_days(tables: dict[str, pd.DataFrame]) -> int:
    date_values: list[pd.Series] = []
    order_table = tables.get("order_table")
    if order_table is not None and "Order_Create_Date" in order_table.columns:
        date_values.append(pd.to_datetime(order_table["Order_Create_Date"], errors="coerce"))
    flow_events = tables.get("supplier_material_flow_event")
    if flow_events is not None and "Event_Date" in flow_events.columns:
        date_values.append(pd.to_datetime(flow_events["Event_Date"], errors="coerce"))
    daily_inventory = tables.get("supplier_daily_inventory")
    if daily_inventory is not None and "Inventory_Date" in daily_inventory.columns:
        date_values.append(pd.to_datetime(daily_inventory["Inventory_Date"], errors="coerce"))
    if not date_values:
        return 365
    combined = pd.concat(date_values, ignore_index=True).dropna()
    if combined.empty:
        return 365
    return max(int((combined.max() - combined.min()).days) + 1, 1)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series | float | int) -> pd.Series:
    denominator_series = denominator if isinstance(denominator, pd.Series) else pd.Series(denominator, index=numerator.index)
    denominator_series = pd.to_numeric(denominator_series, errors="coerce").replace(0, pd.NA)
    return (
        pd.to_numeric(numerator, errors="coerce")
        .div(denominator_series)
        .replace([float("inf"), -float("inf")], pd.NA)
    )


def _derive_avg_daily_demand(
    material_summary: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    observation_days: int,
) -> pd.Series:
    item_ids = material_summary["Material_ID"].astype(str)
    fallback = _safe_ratio(material_summary["Total_Purchase_Amount"], material_summary["Material_Cost"]).fillna(0.0)
    fallback = fallback.div(max(observation_days, 1))

    order_based = pd.Series(dtype=float)
    orders = tables.get("order_table")
    if orders is not None and {"Material_ID", "Purchase_Quantity"}.issubset(orders.columns):
        order_based = (
            orders.assign(Purchase_Quantity=pd.to_numeric(orders["Purchase_Quantity"], errors="coerce").fillna(0.0))
            .groupby("Material_ID")["Purchase_Quantity"]
            .sum()
            .div(max(observation_days, 1))
        )

    flow_based = pd.Series(dtype=float)
    flow_events = tables.get("supplier_material_flow_event")
    if flow_events is not None and {"Material_ID", "Quantity_Change"}.issubset(flow_events.columns):
        flow = flow_events.copy()
        flow["Quantity_Change"] = pd.to_numeric(flow["Quantity_Change"], errors="coerce").fillna(0.0)
        if "Event_Type" in flow.columns:
            flow = flow.loc[flow["Event_Type"].astype(str).eq("production_consumption")]
        flow = flow.loc[flow["Quantity_Change"] < 0]
        if not flow.empty:
            flow_based = flow.groupby("Material_ID")["Quantity_Change"].sum().abs().div(max(observation_days, 1))

    avg_daily_demand = item_ids.map(flow_based).astype(float)
    avg_daily_demand = avg_daily_demand.fillna(item_ids.map(order_based).astype(float))
    avg_daily_demand = avg_daily_demand.fillna(fallback.astype(float))
    avg_daily_demand = avg_daily_demand.fillna(0.0).clip(lower=0.0)
    avg_daily_demand = avg_daily_demand.where(avg_daily_demand > 0, fallback.fillna(1.0))
    avg_daily_demand = avg_daily_demand.where(avg_daily_demand > 0, 1.0)
    return pd.Series(avg_daily_demand.to_numpy(), index=item_ids, dtype=float)


def _derive_initial_inventory(
    material_summary: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    avg_daily_demand: pd.Series,
    config: dict,
) -> pd.Series:
    default_inventory_days = float(config.get("standardization", {}).get("default_inventory_days", 12.0))
    item_ids = material_summary["Material_ID"].astype(str)
    inventory_by_item = pd.Series(dtype=float)

    inventory_policy = tables.get("supplier_material_inventory_policy")
    if inventory_policy is not None and {"Material_ID", "Opening_Inventory_Qty"}.issubset(inventory_policy.columns):
        inventory_by_item = (
            inventory_policy.assign(
                Opening_Inventory_Qty=pd.to_numeric(
                    inventory_policy["Opening_Inventory_Qty"], errors="coerce"
                ).fillna(0.0)
            )
            .groupby("Material_ID")["Opening_Inventory_Qty"]
            .sum()
        )

    if inventory_by_item.empty:
        daily_inventory = tables.get("supplier_daily_inventory")
        if daily_inventory is not None and {"Supplier_ID", "Purchased_Material_ID", "Inventory_Qty"}.issubset(daily_inventory.columns):
            inventory = daily_inventory.copy()
            inventory["Inventory_Qty"] = pd.to_numeric(inventory["Inventory_Qty"], errors="coerce").fillna(0.0)
            if "Inventory_Date" in inventory.columns:
                inventory["Inventory_Date"] = pd.to_datetime(inventory["Inventory_Date"], errors="coerce")
                inventory = inventory.sort_values("Inventory_Date")
            inventory = inventory.groupby(["Supplier_ID", "Purchased_Material_ID"], as_index=False).head(1)
            inventory_by_item = inventory.groupby("Purchased_Material_ID")["Inventory_Qty"].sum()

    fallback_inventory = avg_daily_demand.mul(default_inventory_days).where(avg_daily_demand > 0, 1.0)
    initial_inventory = item_ids.map(inventory_by_item).astype(float).fillna(fallback_inventory.astype(float))
    initial_inventory = initial_inventory.fillna(0.0).clip(lower=0.0)
    return pd.Series(initial_inventory.to_numpy(), index=item_ids, dtype=float)


def _build_order_supplier_item_stats(
    tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    orders = tables.get("order_table")
    if orders is None or orders.empty:
        return pd.DataFrame(
            columns=[
                "item_id",
                "supplier_id",
                "order_count",
                "total_purchase_qty",
                "avg_capacity",
                "qualified_rate",
                "delay_rate",
                "avg_unit_price",
                "estimated_lead_time_days",
            ]
        )

    orders = orders.copy()
    orders["order_create_date"] = pd.to_datetime(orders["Order_Create_Date"], errors="coerce")
    orders["order_delivery_date"] = pd.to_datetime(orders["Order_Delivery_Date"], errors="coerce")
    orders["lead_time_days"] = (
        orders["order_delivery_date"] - orders["order_create_date"]
    ).dt.days.clip(lower=1)

    return (
        orders.groupby(["Material_ID", "Supplier_ID"], as_index=False)
        .agg(
            order_count=("Order_ID", "count"),
            total_purchase_qty=("Purchase_Quantity", "sum"),
            avg_capacity=("Theoretical_Capacity", "mean"),
            qualified_rate=("Is_Qualified_Supplier", "mean"),
            delay_rate=("Is_Delayed", "mean"),
            avg_unit_price=("Material_Unit_Price", "mean"),
            estimated_lead_time_days=("lead_time_days", "median"),
        )
        .rename(columns={"Material_ID": "item_id", "Supplier_ID": "supplier_id"})
    )


def _build_supplier_item_lead_time_lookup(tables: dict[str, pd.DataFrame]) -> pd.Series:
    inventory_policy = tables.get("supplier_material_inventory_policy")
    if inventory_policy is None or inventory_policy.empty:
        return pd.Series(dtype=float)
    policy = inventory_policy.copy()
    policy["Lead_Time_Days"] = pd.to_numeric(policy["Lead_Time_Days"], errors="coerce")
    grouped = policy.groupby(["Supplier_ID", "Material_ID"])["Lead_Time_Days"].median()
    grouped.index = pd.MultiIndex.from_tuples(
        [(str(supplier_id), str(item_id)) for supplier_id, item_id in grouped.index],
        names=["supplier_id", "item_id"],
    )
    return grouped


def _unique_supplier_item_pairs(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["item_id", "supplier_id"])
    return (
        frame.rename(
            columns={
                "Purchased_Material_ID": "item_id",
                "Material_ID": "item_id",
                "Supplying_Supplier_ID": "supplier_id",
                "Supplier_ID": "supplier_id",
            }
        )[["item_id", "supplier_id"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )


def _build_optional_supply_rows(
    *,
    pair_frame: pd.DataFrame,
    origin: str,
    supply_role: str,
    existing_keys: set[tuple[str, str]],
    order_stats: pd.DataFrame,
    lead_time_lookup: pd.Series,
    default_qualified_rate: float,
    qualification_required: bool,
    qualification_time_days: int,
    backup_capacity_factor: float,
    backup_priority: int,
    observation_days: int,
) -> list[dict]:
    if pair_frame.empty:
        return []

    stats_lookup = order_stats.set_index(["item_id", "supplier_id"]).to_dict("index") if not order_stats.empty else {}
    default_lead_time = 7.0
    if not lead_time_lookup.empty:
        default_lead_time = float(lead_time_lookup.dropna().median())
    elif not order_stats.empty:
        default_lead_time = float(pd.to_numeric(order_stats["estimated_lead_time_days"], errors="coerce").dropna().median())
    if pd.isna(default_lead_time) or default_lead_time <= 0:
        default_lead_time = 7.0

    rows: list[dict] = []
    for record in pair_frame.itertuples(index=False):
        key = (str(record.item_id), str(record.supplier_id))
        if key in existing_keys:
            continue
        stats = stats_lookup.get(key, {})
        lead_time = lead_time_lookup.get((str(record.supplier_id), str(record.item_id)), stats.get("estimated_lead_time_days", default_lead_time))
        avg_capacity = stats.get("avg_capacity", stats.get("total_purchase_qty", 0.0) / max(observation_days, 1))
        rows.append(
            {
                "supplier_id": str(record.supplier_id),
                "item_id": str(record.item_id),
                "share": 0.0,
                "is_primary": False,
                "is_backup": True,
                "is_current_source": False,
                "avg_capacity": max(float(avg_capacity) if pd.notna(avg_capacity) else 0.0, 1.0),
                "qualified_rate": float(stats.get("qualified_rate", default_qualified_rate)),
                "delay_rate": float(stats.get("delay_rate", 0.0)),
                "estimated_lead_time_days": max(float(lead_time) if pd.notna(lead_time) else default_lead_time, 1.0),
                "switch_time_days": max(int(round(float(lead_time) if pd.notna(lead_time) else default_lead_time)), 1),
                "qualification_required": qualification_required,
                "qualification_time_days": qualification_time_days if qualification_required else 0,
                "backup_capacity_factor": backup_capacity_factor,
                "backup_priority": backup_priority,
                "mapping_origin": origin,
                "supply_role": supply_role,
            }
        )
    return rows


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _standardize_supplier_materials(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_material")
    columns = ["relation_id", "supplier_id", "item_id", "relation_type"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Material_ID": "relation_id",
            "Supplier_ID": "supplier_id",
            "Material_ID": "item_id",
        }
    )[["relation_id", "supplier_id", "item_id"]].copy()
    frame["relation_type"] = "supplier_material_capability"
    return frame[columns]


def _standardize_supplier_production_plan(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_production_plan")
    columns = ["plan_id", "purchasing_supplier_id", "item_id", "supplying_supplier_id", "purchase_quantity"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Production_Plan_ID": "plan_id",
            "Purchasing_Supplier_ID": "purchasing_supplier_id",
            "Purchased_Material_ID": "item_id",
            "Supplying_Supplier_ID": "supplying_supplier_id",
            "Purchase_Quantity": "purchase_quantity",
        }
    )[columns].copy()
    frame["purchase_quantity"] = pd.to_numeric(frame["purchase_quantity"], errors="coerce").fillna(0.0)
    return frame


def _standardize_supplier_licensed_supply(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_licensed_supply")
    columns = ["license_id", "purchasing_supplier_id", "item_id", "supplying_supplier_id", "relation_type"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Licensed_Supply_ID": "license_id",
            "Purchasing_Supplier_ID": "purchasing_supplier_id",
            "Purchased_Material_ID": "item_id",
            "Supplying_Supplier_ID": "supplying_supplier_id",
        }
    )[["license_id", "purchasing_supplier_id", "item_id", "supplying_supplier_id"]].copy()
    frame["relation_type"] = "licensed_supply"
    return frame[columns]


def _standardize_supplier_potential_supply(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_potential_supply")
    columns = ["potential_supply_id", "purchasing_supplier_id", "item_id", "supplying_supplier_id", "relation_type"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Potential_Supply_ID": "potential_supply_id",
            "Purchasing_Supplier_ID": "purchasing_supplier_id",
            "Purchased_Material_ID": "item_id",
            "Supplying_Supplier_ID": "supplying_supplier_id",
        }
    )[["potential_supply_id", "purchasing_supplier_id", "item_id", "supplying_supplier_id"]].copy()
    frame["relation_type"] = "potential_supply"
    return frame[columns]


def _standardize_supplier_daily_inventory(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_daily_inventory")
    columns = ["inventory_id", "supplier_id", "item_id", "inventory_qty", "inventory_date"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Daily_Inventory_ID": "inventory_id",
            "Supplier_ID": "supplier_id",
            "Purchased_Material_ID": "item_id",
            "Inventory_Qty": "inventory_qty",
            "Inventory_Date": "inventory_date",
        }
    )[columns].copy()
    frame["inventory_qty"] = pd.to_numeric(frame["inventory_qty"], errors="coerce").fillna(0.0)
    frame["inventory_date"] = pd.to_datetime(frame["inventory_date"], errors="coerce")
    return frame


def _standardize_supplier_material_flow_events(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_material_flow_event")
    columns = ["flow_event_id", "supplier_id", "item_id", "event_date", "event_type", "quantity_change", "source_type", "source_id"]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Material_Flow_Event_ID": "flow_event_id",
            "Supplier_ID": "supplier_id",
            "Material_ID": "item_id",
            "Event_Date": "event_date",
            "Event_Type": "event_type",
            "Quantity_Change": "quantity_change",
            "Source_Type": "source_type",
            "Source_ID": "source_id",
        }
    ).copy()
    for column in ["source_type", "source_id"]:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[columns].copy()
    frame["event_date"] = pd.to_datetime(frame["event_date"], errors="coerce")
    frame["quantity_change"] = pd.to_numeric(frame["quantity_change"], errors="coerce").fillna(0.0)
    return frame


def _standardize_supplier_material_inventory_policy(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = tables.get("supplier_material_inventory_policy")
    columns = [
        "policy_id",
        "supplier_id",
        "item_id",
        "opening_inventory_qty",
        "safety_stock_days",
        "reorder_point_days",
        "target_cover_days",
        "lot_size_qty",
        "lead_time_days",
    ]
    if source is None or source.empty:
        return _empty_frame(columns)
    frame = source.rename(
        columns={
            "Supplier_Material_Inventory_Policy_ID": "policy_id",
            "Supplier_ID": "supplier_id",
            "Material_ID": "item_id",
            "Opening_Inventory_Qty": "opening_inventory_qty",
            "Safety_Stock_Days": "safety_stock_days",
            "Reorder_Point_Days": "reorder_point_days",
            "Target_Cover_Days": "target_cover_days",
            "Lot_Size_Qty": "lot_size_qty",
            "Lead_Time_Days": "lead_time_days",
        }
    ).copy()
    for column in [
        "opening_inventory_qty",
        "safety_stock_days",
        "reorder_point_days",
        "target_cover_days",
        "lot_size_qty",
        "lead_time_days",
    ]:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame[columns].copy()


def _standardize_suppliers(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    supplier_summary = tables["supplier_summary"].copy()
    supplier_region = tables["supplier_region"].copy()
    region_table = tables["region"].copy()
    supplier_incident = tables["supplier_incident"].copy()

    incident_count = (
        supplier_incident.groupby("Supplier_ID")["Emergency_Incident_ID"]
        .nunique()
        .rename("historical_incident_count")
        .reset_index()
    )
    suppliers = supplier_summary.merge(supplier_region[["Supplier_ID", "Region_ID"]], on="Supplier_ID", how="left")
    suppliers = suppliers.merge(region_table, on="Region_ID", how="left")
    suppliers = suppliers.merge(incident_count, on="Supplier_ID", how="left")
    suppliers["historical_incident_count"] = suppliers["historical_incident_count"].fillna(0).astype(int)
    suppliers["risk_level"] = pd.cut(
        suppliers["historical_incident_count"],
        bins=[-1, 0, 2, 1000],
        labels=["low", "medium", "high"],
    ).astype(str)
    suppliers["available_storage_gap"] = suppliers["Available_Storage"] - suppliers["Required_Storage"]
    suppliers["default_rate"] = (
        suppliers["Default_Contracts"] / suppliers["Total_Contracts"].replace(0, 1)
    )
    suppliers["compliance_rate"] = (
        suppliers["Compliant_Items"] / suppliers["Total_Compliance_Items"].replace(0, 1)
    )
    suppliers["qms_rate"] = (
        suppliers["Certified_QMS_Items"] / suppliers["Total_QMS_Items"].replace(0, 1)
    )
    suppliers = suppliers.rename(
        columns={
            "Supplier_ID": "supplier_id",
            "Supplier_Name": "supplier_name",
            "Region_ID": "region_id",
            "WGI_Index": "wgi_index",
            "Sovereign_Rating": "sovereign_rating",
            "National_Credit_Rating": "national_credit_rating",
        }
    )
    return suppliers[
        [
            "supplier_id",
            "supplier_name",
            "region_id",
            "historical_incident_count",
            "risk_level",
            "default_rate",
            "compliance_rate",
            "qms_rate",
            "available_storage_gap",
            "wgi_index",
            "sovereign_rating",
            "national_credit_rating",
        ]
    ].copy()


def _enrich_suppliers(suppliers: pd.DataFrame) -> pd.DataFrame:
    suppliers = suppliers.copy()
    suppliers["node_type"] = "supplier"
    suppliers["supply_state_default"] = "available"
    suppliers["demand_state_default"] = "stable"
    suppliers["fused_state_default"] = "active"
    suppliers["visual_status_default"] = "available"
    suppliers["is_key_node"] = False
    suppliers["critical_tier"] = "general"
    suppliers["critical_score"] = 0.0
    suppliers["critical_reason"] = ""
    suppliers["critical_source"] = "default"
    return suppliers


def _standardize_supplier_edges(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    edges = tables["supplier_network"].copy().rename(
        columns={
            "Supplier_Network_ID": "edge_id",
            "Supplier_ID": "source_supplier_id",
            "Supplier_down_ID": "target_supplier_id",
        }
    )
    edges["relation_type"] = "upstream_dependency"
    return edges[["edge_id", "source_supplier_id", "target_supplier_id", "relation_type"]].copy()


def _enrich_supplier_edges(edges: pd.DataFrame) -> pd.DataFrame:
    edges = edges.copy()
    edges["edge_type"] = "supplier_network"
    edges["edge_status_default"] = "active"
    return edges


def _standardize_items(tables: dict[str, pd.DataFrame], config: dict) -> pd.DataFrame:
    material_summary = tables["material_summary"].copy()
    observation_days = _estimate_observation_window_days(tables)
    derived_avg_daily_demand = _derive_avg_daily_demand(material_summary, tables, observation_days)
    derived_initial_inventory = _derive_initial_inventory(material_summary, tables, derived_avg_daily_demand, config)
    default_inventory_days = float(config.get("standardization", {}).get("default_inventory_days", 12.0))

    items = material_summary.rename(
        columns={
            "Material_ID": "item_id",
            "Material_Name": "item_name",
            "Is_Critical_Material": "is_critical_material",
            "Is_Standard_Part": "is_standard_part",
            "Is_Equivalent_Material": "is_equivalent_material",
            "Is_Final_Product": "is_final_product",
            "Material_Cost": "material_cost",
        }
    )
    item_ids = items["item_id"].astype(str)
    items["avg_daily_demand"] = item_ids.map(derived_avg_daily_demand).fillna(0.0).clip(lower=0.0)
    inventory_fallback = item_ids.map(derived_initial_inventory).fillna(items["avg_daily_demand"] * default_inventory_days)
    items["initial_inventory_qty"] = inventory_fallback.fillna(0.0).clip(lower=0.0)
    items["avg_daily_demand"] = items["avg_daily_demand"].where(items["avg_daily_demand"] > 0, 1.0)
    items["initial_inventory_qty"] = items["initial_inventory_qty"].where(
        items["initial_inventory_qty"] > 0,
        items["avg_daily_demand"] * default_inventory_days,
    )
    items["material_cost"] = pd.to_numeric(items["material_cost"], errors="coerce").fillna(0.0)
    for column in [
        "is_critical_material",
        "is_standard_part",
        "is_equivalent_material",
        "is_final_product",
    ]:
        items[column] = pd.to_numeric(items[column], errors="coerce").fillna(0).astype(int).astype(bool)
    return items[
        [
            "item_id",
            "item_name",
            "initial_inventory_qty",
            "avg_daily_demand",
            "is_critical_material",
            "is_standard_part",
            "is_equivalent_material",
            "is_final_product",
            "material_cost",
        ]
    ].copy()


def _enrich_items(items: pd.DataFrame, bom_edges: pd.DataFrame, config: dict) -> pd.DataFrame:
    items = items.copy()
    child_nodes = set(bom_edges["child_item_id"])
    parent_nodes = set(bom_edges["parent_item_id"])
    item_level: list[str] = []
    for row in items.itertuples(index=False):
        item_id = row.item_id
        if row.is_final_product:
            level = "product"
        elif item_id in parent_nodes and item_id in child_nodes:
            level = "assembly"
        elif item_id in child_nodes:
            level = "material"
        else:
            level = "part"
        item_level.append(level)
    items["item_level"] = item_level
    items["node_type"] = items["item_level"]
    items["demand_priority"] = (
        items["is_final_product"].astype(int) * 3
        + items["is_critical_material"].astype(int) * 2
        + items["is_standard_part"].astype(int)
    )
    items["target_service_level"] = config["demand_model"]["target_service_level"]
    items["default_requested_demand"] = items["avg_daily_demand"].astype(float)
    items["backlog_retention_ratio"] = config["demand_model"]["backlog_retention_ratio"]
    items["supply_state_default"] = "available"
    items["demand_state_default"] = "stable"
    items["fused_state_default"] = "active"
    items["visual_status_default"] = "available"
    items["is_key_node"] = False
    items["critical_tier"] = "general"
    items["critical_score"] = 0.0
    items["critical_reason"] = ""
    items["critical_source"] = "default"
    return items


def _standardize_bom_edges(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    bom = tables["material_bom"].copy().rename(
        columns={
            "BOM_ID": "bom_id",
            "Material_ID": "child_item_id",
            "Downstream_Material_ID": "parent_item_id",
            "Required_Qty": "quantity",
        }
    )
    bom["is_mandatory"] = True
    bom["dependency_type"] = "AND"
    return bom[
        ["bom_id", "parent_item_id", "child_item_id", "quantity", "is_mandatory", "dependency_type"]
    ].copy()


def _enrich_bom_edges(bom_edges: pd.DataFrame) -> pd.DataFrame:
    bom_edges = bom_edges.copy()
    bom_edges["edge_type"] = "bom"
    bom_edges["edge_status_default"] = "active"
    return bom_edges


def _standardize_supply_map(tables: dict[str, pd.DataFrame], config: dict) -> pd.DataFrame:
    role_cfg = config.get("supply_source_roles", {})
    output_columns = [
        "supplier_id",
        "item_id",
        "share",
        "is_primary",
        "is_backup",
        "is_current_source",
        "avg_capacity",
        "qualified_rate",
        "delay_rate",
        "estimated_lead_time_days",
        "switch_time_days",
        "qualification_required",
        "qualification_time_days",
        "backup_capacity_factor",
        "backup_priority",
        "mapping_origin",
        "supply_role",
    ]
    observation_days = _estimate_observation_window_days(tables)
    order_stats = _build_order_supplier_item_stats(tables)
    lead_time_lookup = _build_supplier_item_lead_time_lookup(tables)

    production_plan = tables.get("supplier_production_plan")
    if production_plan is not None and not production_plan.empty:
        base = (
            production_plan.groupby(["Purchased_Material_ID", "Supplying_Supplier_ID"], as_index=False)
            .agg(total_purchase_qty=("Purchase_Quantity", "sum"))
            .rename(columns={"Purchased_Material_ID": "item_id", "Supplying_Supplier_ID": "supplier_id"})
        )
        base["mapping_origin"] = "production_plan"
    elif not order_stats.empty:
        base = order_stats[["item_id", "supplier_id", "total_purchase_qty"]].copy()
        base["mapping_origin"] = "observed"
    else:
        base = pd.DataFrame(columns=["item_id", "supplier_id", "total_purchase_qty", "mapping_origin"])

    if base.empty:
        merged = pd.DataFrame(columns=output_columns)
    else:
        base["supplier_id"] = base["supplier_id"].astype(str)
        base["item_id"] = base["item_id"].astype(str)
        base["total_purchase_qty"] = pd.to_numeric(base["total_purchase_qty"], errors="coerce").fillna(0.0)
        base["has_positive_qty"] = base["total_purchase_qty"] > 0
        positive_total = (
            base.loc[base["has_positive_qty"]]
            .groupby("item_id")["total_purchase_qty"]
            .transform("sum")
        )
        base["share"] = 0.0
        if not positive_total.empty:
            positive_mask = base["has_positive_qty"]
            base.loc[positive_mask, "share"] = (
                base.loc[positive_mask, "total_purchase_qty"] / positive_total.replace(0, 1)
            )
        for item_id, group in base.groupby("item_id", sort=False):
            if group["share"].sum() <= 0 and not group.empty:
                base.loc[group.index, "share"] = 1.0 / len(group.index)

        base = base.sort_values(
            by=["item_id", "has_positive_qty", "share", "supplier_id"],
            ascending=[True, False, False, True],
        )
        base["supplier_rank"] = base.groupby("item_id", sort=False).cumcount()
        base["is_primary"] = base["supplier_rank"] == 0
        base["is_backup"] = ~base["is_primary"]
        base["is_current_source"] = base["is_primary"]
        base["backup_priority"] = base["supplier_rank"].where(base["is_backup"], 0).astype(int)
        base["backup_capacity_factor"] = 1.0
        base["supply_role"] = [
            f"{origin}_primary" if is_primary else f"{origin}_backup"
            for origin, is_primary in zip(base["mapping_origin"], base["is_primary"])
        ]

        merged = base.merge(order_stats, on=["item_id", "supplier_id"], how="left", suffixes=("", "_order"))
        merged["qualified_rate"] = pd.to_numeric(merged["qualified_rate"], errors="coerce")
        merged["delay_rate"] = pd.to_numeric(merged["delay_rate"], errors="coerce")
        merged["avg_capacity"] = pd.to_numeric(merged["avg_capacity"], errors="coerce")
        merged["estimated_lead_time_days"] = pd.to_numeric(merged["estimated_lead_time_days"], errors="coerce")

        if not lead_time_lookup.empty:
            merged["policy_lead_time_days"] = [
                lead_time_lookup.get((str(row.supplier_id), str(row.item_id)), pd.NA)
                for row in merged.itertuples(index=False)
            ]
            merged["estimated_lead_time_days"] = merged["estimated_lead_time_days"].fillna(
                pd.to_numeric(merged["policy_lead_time_days"], errors="coerce")
            )

        merged["avg_capacity"] = merged["avg_capacity"].fillna(
            merged["total_purchase_qty"].div(max(observation_days, 1)).replace(0, pd.NA)
        )
        merged["avg_capacity"] = merged["avg_capacity"].fillna(1.0)
        merged["qualified_rate"] = merged["qualified_rate"].fillna(1.0)
        merged["delay_rate"] = merged["delay_rate"].fillna(0.0)
        merged["estimated_lead_time_days"] = merged["estimated_lead_time_days"].fillna(7.0)

        merged["switch_time_days"] = 0
        merged["qualification_required"] = False
        merged["qualification_time_days"] = 0

    existing_keys = {
        (str(item_id), str(supplier_id))
        for item_id, supplier_id in merged[["item_id", "supplier_id"]].itertuples(index=False, name=None)
    }
    licensed_rows = _build_optional_supply_rows(
        pair_frame=_unique_supplier_item_pairs(tables.get("supplier_licensed_supply")),
        origin="licensed",
        supply_role="licensed_backup",
        existing_keys=existing_keys,
        order_stats=order_stats,
        lead_time_lookup=lead_time_lookup,
        default_qualified_rate=1.0,
        qualification_required=False,
        qualification_time_days=int(role_cfg.get("licensed_qualification_time_days", 0)),
        backup_capacity_factor=float(role_cfg.get("licensed_backup_capacity_factor", 0.85)),
        backup_priority=int(role_cfg.get("licensed_backup_priority", 10)),
        observation_days=observation_days,
    )
    existing_keys.update((row["item_id"], row["supplier_id"]) for row in licensed_rows)
    potential_rows = _build_optional_supply_rows(
        pair_frame=_unique_supplier_item_pairs(tables.get("supplier_potential_supply")),
        origin="potential",
        supply_role="potential_backup",
        existing_keys=existing_keys,
        order_stats=order_stats,
        lead_time_lookup=lead_time_lookup,
        default_qualified_rate=0.9,
        qualification_required=True,
        qualification_time_days=int(role_cfg.get("potential_qualification_time_days", 5)),
        backup_capacity_factor=float(role_cfg.get("potential_backup_capacity_factor", 0.65)),
        backup_priority=int(role_cfg.get("potential_backup_priority", 20)),
        observation_days=observation_days,
    )
    existing_keys.update((row["item_id"], row["supplier_id"]) for row in potential_rows)
    supplier_material_rows = _build_optional_supply_rows(
        pair_frame=_unique_supplier_item_pairs(tables.get("supplier_material")),
        origin="supplier_material",
        supply_role="supplier_material_backup",
        existing_keys=existing_keys,
        order_stats=order_stats,
        lead_time_lookup=lead_time_lookup,
        default_qualified_rate=1.0,
        qualification_required=True,
        qualification_time_days=int(role_cfg.get("capability_fallback_qualification_time_days", 5)),
        backup_capacity_factor=float(role_cfg.get("capability_fallback_capacity_factor", 0.60)),
        backup_priority=int(role_cfg.get("capability_fallback_priority", 30)),
        observation_days=observation_days,
    )

    optional_rows = licensed_rows + potential_rows + supplier_material_rows
    if optional_rows:
        merged = pd.concat([merged, pd.DataFrame(optional_rows)], ignore_index=True, sort=False)

    if merged.empty:
        return pd.DataFrame(columns=output_columns)

    merged["supplier_id"] = merged["supplier_id"].astype(str)
    merged["item_id"] = merged["item_id"].astype(str)
    merged["is_primary"] = merged["is_primary"].astype(bool)
    merged["is_backup"] = merged["is_backup"].astype(bool)
    merged["is_current_source"] = merged.get("is_current_source", ~merged["is_backup"]).fillna(~merged["is_backup"]).astype(bool)

    merged["share"] = pd.to_numeric(merged["share"], errors="coerce").fillna(0.0)
    merged["avg_capacity"] = pd.to_numeric(merged["avg_capacity"], errors="coerce").fillna(1.0).clip(lower=1.0)
    merged["qualified_rate"] = pd.to_numeric(merged["qualified_rate"], errors="coerce").fillna(1.0).clip(lower=0.0, upper=1.0)
    merged["delay_rate"] = pd.to_numeric(merged["delay_rate"], errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)
    merged["estimated_lead_time_days"] = pd.to_numeric(merged["estimated_lead_time_days"], errors="coerce").fillna(7.0).clip(lower=1.0)
    merged["switch_time_days"] = merged["switch_time_days"].astype(int)
    merged["qualification_required"] = merged["qualification_required"].astype(bool)
    merged["qualification_time_days"] = merged["qualification_time_days"].astype(int)
    merged["backup_capacity_factor"] = pd.to_numeric(merged["backup_capacity_factor"], errors="coerce").fillna(1.0)
    merged["backup_priority"] = pd.to_numeric(merged["backup_priority"], errors="coerce").fillna(99).astype(int)
    merged["mapping_origin"] = merged["mapping_origin"].fillna("unknown").astype(str)
    merged["supply_role"] = merged["supply_role"].fillna(merged["mapping_origin"]).astype(str)

    return merged[output_columns].copy()


def _enrich_supply_map(supply_map: pd.DataFrame) -> pd.DataFrame:
    supply_map = supply_map.copy()
    supply_map["edge_type"] = "supplier_item_map"
    supply_map["edge_status_default"] = supply_map["is_backup"].map({True: "standby", False: "active"})
    return supply_map


def _summarize_supply_map_item_levels(
    *,
    items: pd.DataFrame,
    bom_edges: pd.DataFrame,
    supply_map: pd.DataFrame,
) -> dict[str, object]:
    if supply_map.empty:
        return {"external_supply_item_levels": {}, "external_supply_items_with_bom": []}

    bom_parent_ids = set(bom_edges["parent_item_id"].astype(str).tolist())
    item_levels = items.set_index("item_id")["item_level"].astype(str).to_dict()
    supply_map = supply_map.copy()
    supply_map["item_level"] = supply_map["item_id"].map(item_levels).fillna("unknown")
    level_counts = supply_map.groupby("item_level").size().astype(int).to_dict()
    bom_supplied_items = sorted(
        supply_map.loc[supply_map["item_id"].astype(str).isin(bom_parent_ids), "item_id"]
        .astype(str)
        .unique()
        .tolist()
    )
    return {
        "external_supply_item_levels": level_counts,
        "external_supply_items_with_bom": bom_supplied_items,
    }


def _standardize_part_alternatives(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    alternatives = tables["equivalent_material"].copy().rename(
        columns={
            "Equivalent_Material_Info_ID": "alternative_id",
            "Material_ID": "item_id",
            "Equivalent_Material_ID": "alt_item_id",
        }
    )
    alternatives["switch_time_days"] = 3
    alternatives["priority"] = alternatives.groupby("item_id").cumcount() + 1
    return alternatives[["alternative_id", "item_id", "alt_item_id", "priority", "switch_time_days"]].copy()


def _enrich_part_alternatives(part_alternatives: pd.DataFrame) -> pd.DataFrame:
    part_alternatives = part_alternatives.copy()
    part_alternatives["edge_type"] = "alternative"
    part_alternatives["edge_status_default"] = "standby"
    return part_alternatives


def _standardize_incident_events(tables: dict[str, pd.DataFrame], config: dict) -> pd.DataFrame:
    supplier_incident = tables["supplier_incident"].copy()
    incident = tables["incident"].copy()
    merged = supplier_incident.merge(incident, on="Emergency_Incident_ID", how="left")
    merged["start_date"] = pd.to_datetime(merged["Time_of_the_Incident"])
    merged["first_response_date"] = pd.to_datetime(merged["First_Response_Time"])
    merged["duration_days"] = (
        merged["first_response_date"] - merged["start_date"]
    ).dt.days.clip(lower=1)
    merged["default_duration_days"] = merged["Event_Type"].map(config["incident_duration_days"]).fillna(7)
    merged["resolved_duration_days"] = merged[["duration_days", "default_duration_days"]].max(axis=1)
    merged["severity"] = merged["Event_Type"].map(config["incident_severity"]).fillna(0.7)
    merged = merged.rename(
        columns={
            "Supplier_Emergency_Incident_ID": "supplier_incident_id",
            "Supplier_ID": "supplier_id",
            "Emergency_Incident_ID": "incident_id",
            "Event_Type": "event_type",
        }
    )
    return merged[
        [
            "supplier_incident_id",
            "supplier_id",
            "incident_id",
            "event_type",
            "start_date",
            "first_response_date",
            "resolved_duration_days",
            "severity",
        ]
    ].copy()




def _load_optional_critical_nodes(source_dir: Path) -> pd.DataFrame | None:
    keynodes_dir = Path(source_dir) / "keynodes"
    if keynodes_dir.exists() and keynodes_dir.is_dir():
        ranking_frames: list[pd.DataFrame] = []
        for candidate in sorted(keynodes_dir.glob("*.csv")):
            if not candidate.is_file():
                continue
            frame = pd.read_csv(candidate)
            if frame.empty:
                continue
            frame = frame.copy()
            frame["source_filename"] = f"keynodes/{candidate.name}"
            if "node_type" not in frame.columns:
                frame["node_type"] = _infer_keynode_file_node_type(frame=frame, filename=candidate.name)
            ranking_frames.append(frame)
        if ranking_frames:
            combined = pd.concat(ranking_frames, ignore_index=True)
            combined.attrs["source_filename"] = ";".join(
                f"keynodes/{path.name}" for path in sorted(keynodes_dir.glob("*.csv")) if path.is_file()
            )
            return combined

    candidate_names = [
        "Critical_Node_Table.csv",
        "critical_nodes.csv",
        "critical_node_table.csv",
        "关键节点清单.csv",
    ]
    for filename in candidate_names:
        candidate = Path(source_dir) / filename
        if candidate.exists() and candidate.is_file():
            frame = pd.read_csv(candidate)
            frame.attrs["source_filename"] = candidate.name
            return frame
    return None


def _infer_keynode_file_node_type(*, frame: pd.DataFrame, filename: str) -> str | pd.Series:
    lower_name = filename.lower()
    if "supplier" in lower_name:
        return "supplier"
    if "bom" in lower_name or "material" in lower_name or "item" in lower_name:
        return "item"
    node_ids = frame.get("node_id", pd.Series("", index=frame.index)).astype(str).str.upper()
    return node_ids.str.startswith("SID").map({True: "supplier", False: "item"})


def _truthy_series(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.fillna(0).ne(0) | normalized.isin({"true", "yes", "y", "key", "critical", "是", "关键"})


def _apply_critical_node_labels(
    *,
    items: pd.DataFrame,
    suppliers: pd.DataFrame,
    critical_nodes: pd.DataFrame | None,
    config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = items.copy()
    suppliers = suppliers.copy()

    required_defaults = {
        "is_key_node": False,
        "critical_tier": "general",
        "critical_score": 0.0,
        "critical_reason": "",
        "critical_source": "default",
    }
    for frame in (items, suppliers):
        for column, value in required_defaults.items():
            if column not in frame.columns:
                frame[column] = value

    _reset_critical_node_labels(items)
    _reset_critical_node_labels(suppliers)

    if critical_nodes is None or critical_nodes.empty:
        return items, suppliers

    normalized = critical_nodes.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    rename_map = {
        "node_id": "node_id",
        "Node_ID": "node_id",
        "节点ID": "node_id",
        "node_type": "node_type",
        "Node_Type": "node_type",
        "节点类型": "node_type",
        "critical_tier": "critical_tier",
        "Critical_Tier": "critical_tier",
        "关键等级": "critical_tier",
        "critical_score": "critical_score",
        "Critical_Score": "critical_score",
        "关键分数": "critical_score",
        "critical_reason": "critical_reason",
        "Critical_Reason": "critical_reason",
        "关键原因": "critical_reason",
    }
    normalized = normalized.rename(columns={src: dst for src, dst in rename_map.items() if src in normalized.columns})
    if "node_id" not in normalized.columns:
        return items, suppliers

    if "is_critical" in normalized.columns:
        normalized = normalized.loc[_truthy_series(normalized["is_critical"])].copy()
    if normalized.empty:
        return items, suppliers

    if "node_type" not in normalized.columns:
        normalized["node_type"] = "item"
    if "critical_tier" not in normalized.columns:
        normalized["critical_tier"] = "key"
    if "critical_score" not in normalized.columns:
        normalized["critical_score"] = pd.NA
    for score_column in ("bom_score", "supplier_score", "fusion_score", "weighted_degree"):
        if score_column in normalized.columns:
            normalized["critical_score"] = normalized["critical_score"].fillna(
                pd.to_numeric(normalized[score_column], errors="coerce")
            )
    normalized["critical_score"] = normalized["critical_score"].fillna(1.0)
    if "critical_reason" not in normalized.columns:
        normalized["critical_reason"] = "关键节点清单"

    normalized["node_id"] = normalized["node_id"].astype(str).str.strip()
    normalized = normalized.loc[normalized["node_id"].ne("")]
    normalized["node_type"] = (
        normalized["node_type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"material": "item", "part": "item", "assembly": "item", "product": "item", "bom": "item"})
    )
    inferred_supplier = normalized["node_id"].str.upper().str.startswith("SID")
    inferred_item = normalized["node_id"].str.upper().str.startswith("MID")
    normalized.loc[inferred_supplier, "node_type"] = "supplier"
    normalized.loc[inferred_item, "node_type"] = "item"
    normalized["critical_tier"] = (
        normalized["critical_tier"]
        .astype(str)
        .str.lower()
        .replace({"critical": "key", "核心": "key", "关键": "key", "true": "key", "1": "key"})
    )
    normalized.loc[~normalized["critical_tier"].eq("key"), "critical_tier"] = "key"
    normalized["critical_score"] = pd.to_numeric(normalized["critical_score"], errors="coerce").fillna(1.0)
    if "source_filename" not in normalized.columns:
        normalized["source_filename"] = critical_nodes.attrs.get("source_filename", "critical_nodes")

    normalized = (
        normalized.sort_values(["node_type", "node_id", "critical_score"], ascending=[True, True, False])
        .drop_duplicates(["node_type", "node_id"], keep="first")
    )

    item_meta = normalized.loc[normalized["node_type"].eq("item")].set_index("node_id").to_dict("index")
    supplier_meta = normalized.loc[normalized["node_type"].eq("supplier")].set_index("node_id").to_dict("index")

    for idx, row in items.iterrows():
        item_id = str(row["item_id"])
        if item_id not in item_meta:
            continue
        meta = item_meta[item_id]
        items.at[idx, "is_key_node"] = str(meta.get("critical_tier", "general")) == "key"
        items.at[idx, "critical_tier"] = str(meta.get("critical_tier", "general"))
        items.at[idx, "critical_score"] = float(meta.get("critical_score", 1.0))
        items.at[idx, "critical_reason"] = str(meta.get("critical_reason", "关键节点清单"))
        items.at[idx, "critical_source"] = str(meta.get("source_filename", "keynodes"))

    for idx, row in suppliers.iterrows():
        supplier_id = str(row["supplier_id"])
        if supplier_id not in supplier_meta:
            continue
        meta = supplier_meta[supplier_id]
        suppliers.at[idx, "is_key_node"] = str(meta.get("critical_tier", "general")) == "key"
        suppliers.at[idx, "critical_tier"] = str(meta.get("critical_tier", "general"))
        suppliers.at[idx, "critical_score"] = float(meta.get("critical_score", 1.0))
        suppliers.at[idx, "critical_reason"] = str(meta.get("critical_reason", "关键节点清单"))
        suppliers.at[idx, "critical_source"] = str(meta.get("source_filename", "keynodes"))

    return items, suppliers


def _reset_critical_node_labels(frame: pd.DataFrame) -> None:
    frame["is_key_node"] = False
    frame["critical_tier"] = "general"
    frame["critical_score"] = 0.0
    frame["critical_reason"] = ""
    frame["critical_source"] = "default"


def _augment_backup_cases(
    items: pd.DataFrame,
    bom_edges: pd.DataFrame,
    suppliers: pd.DataFrame,
    supply_map: pd.DataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    min_cases = config["standardization"]["min_augmented_backup_cases"]
    supply_map = supply_map.copy()
    if int(min_cases) <= 0:
        return supply_map, {"augmented_backup_items": []}

    graph = nx.DiGraph()
    for row in bom_edges.itertuples(index=False):
        graph.add_edge(row.child_item_id, row.parent_item_id)
    final_products = items.loc[items["is_final_product"], "item_id"].tolist()
    final_ancestors: set[str] = set()
    for final_product in final_products:
        final_ancestors |= nx.ancestors(graph, final_product)
    candidate_items = items.loc[items["item_id"].isin(final_ancestors)].copy()
    candidate_items = candidate_items.sort_values(
        by=["is_critical_material", "avg_daily_demand", "initial_inventory_qty"],
        ascending=[False, False, True],
    )

    supplier_quality = suppliers.copy()
    supplier_quality["candidate_score"] = (
        supplier_quality["compliance_rate"].fillna(0)
        + supplier_quality["qms_rate"].fillna(0)
        + (1 - supplier_quality["default_rate"].fillna(0))
        + supplier_quality["wgi_index"].fillna(0) / 10
    )
    supplier_quality = supplier_quality.sort_values("candidate_score", ascending=False)

    existing_backup_counts = (
        supply_map.groupby("item_id")["is_backup"].sum().astype(int).to_dict()
    )
    augmented_rows: list[dict] = []
    assigned_items: list[str] = []

    for item_row in candidate_items.itertuples(index=False):
        item_id = item_row.item_id
        current_rows = supply_map.loc[supply_map["item_id"] == item_id]
        if current_rows.empty or existing_backup_counts.get(item_id, 0) > 0:
            continue

        primary_supplier = current_rows.sort_values("share", ascending=False).iloc[0]["supplier_id"]
        region_id = suppliers.loc[suppliers["supplier_id"] == primary_supplier, "region_id"]
        preferred_region = region_id.iloc[0] if not region_id.empty else None

        candidate_pool = supplier_quality.loc[
            ~supplier_quality["supplier_id"].isin(current_rows["supplier_id"])
        ]
        if preferred_region is not None:
            same_region = candidate_pool.loc[candidate_pool["region_id"] == preferred_region]
            if not same_region.empty:
                candidate_pool = pd.concat([same_region, candidate_pool.loc[candidate_pool["region_id"] != preferred_region]])
        if candidate_pool.empty:
            continue

        backup_supplier = candidate_pool.iloc[0]
        augmented_rows.append(
            {
                "supplier_id": backup_supplier["supplier_id"],
                "item_id": item_id,
                "share": 0.0,
                "is_primary": False,
                "is_backup": True,
                "avg_capacity": max(float(item_row.avg_daily_demand) * 1.2, 1.0),
                "qualified_rate": float(backup_supplier["compliance_rate"]),
                "delay_rate": max(0.05, float(backup_supplier["default_rate"]) / 2),
                "estimated_lead_time_days": config["standardization"]["synthetic_switch_time_days"],
                "switch_time_days": config["standardization"]["synthetic_switch_time_days"],
                "qualification_required": True,
                "qualification_time_days": config["standardization"]["synthetic_qualification_time_days"],
                "backup_capacity_factor": config["standardization"]["synthetic_backup_capacity_factor"],
                "backup_priority": 90,
                "mapping_origin": "augmented",
                "supply_role": "synthetic_backup",
                "is_current_source": False,
                "edge_type": "supplier_item_map",
                "edge_status_default": "standby",
            }
        )
        assigned_items.append(item_id)
        if len(assigned_items) >= min_cases:
            break

    if augmented_rows:
        supply_map = pd.concat([supply_map, pd.DataFrame(augmented_rows)], ignore_index=True)

    return supply_map, {"augmented_backup_items": assigned_items}
