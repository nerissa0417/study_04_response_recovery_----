from __future__ import annotations

import networkx as nx

from supply_disruption_sim.types import StandardBundle, ValidationReport


def validate_standard_bundle(bundle: StandardBundle) -> ValidationReport:
    report = ValidationReport()
    _validate_non_empty(bundle, report)
    _validate_foreign_keys(bundle, report)
    _validate_auxiliary_foreign_keys(bundle, report)
    _validate_bom(bundle, report)
    _validate_final_product(bundle, report)
    _validate_supply_map(bundle, report)
    return report


def _validate_non_empty(bundle: StandardBundle, report: ValidationReport) -> None:
    for name, frame in bundle.as_dict().items():
        if frame.empty:
            report.add("error", "non_empty", f"Table '{name}' is empty.")


def _validate_foreign_keys(bundle: StandardBundle, report: ValidationReport) -> None:
    supplier_ids = set(bundle.suppliers["supplier_id"])
    item_ids = set(bundle.items["item_id"])
    region_missing = bundle.suppliers["region_id"].isna().sum()
    if region_missing:
        report.add("warning", "supplier_region", "Some suppliers are missing a region mapping.", missing_count=int(region_missing))

    missing_supply_suppliers = sorted(set(bundle.supplier_item_map["supplier_id"]) - supplier_ids)
    if missing_supply_suppliers:
        report.add("error", "supply_supplier_fk", "Supply map contains unknown suppliers.", supplier_ids=missing_supply_suppliers)
    missing_supply_items = sorted(set(bundle.supplier_item_map["item_id"]) - item_ids)
    if missing_supply_items:
        report.add("error", "supply_item_fk", "Supply map contains unknown items.", item_ids=missing_supply_items)

    missing_bom_items = sorted(
        (set(bundle.bom_edges["parent_item_id"]) | set(bundle.bom_edges["child_item_id"])) - item_ids
    )
    if missing_bom_items:
        report.add("error", "bom_item_fk", "BOM contains unknown items.", item_ids=missing_bom_items)


def _validate_auxiliary_foreign_keys(bundle: StandardBundle, report: ValidationReport) -> None:
    supplier_ids = set(bundle.suppliers["supplier_id"].astype(str))
    item_ids = set(bundle.items["item_id"].astype(str))

    checks = [
        ("supplier_materials", bundle.supplier_materials, ["supplier_id"], ["item_id"]),
        ("supplier_production_plan", bundle.supplier_production_plan, ["purchasing_supplier_id", "supplying_supplier_id"], ["item_id"]),
        ("supplier_licensed_supply", bundle.supplier_licensed_supply, ["purchasing_supplier_id", "supplying_supplier_id"], ["item_id"]),
        ("supplier_potential_supply", bundle.supplier_potential_supply, ["purchasing_supplier_id", "supplying_supplier_id"], ["item_id"]),
        ("supplier_daily_inventory", bundle.supplier_daily_inventory, ["supplier_id"], ["item_id"]),
        ("supplier_material_flow_events", bundle.supplier_material_flow_events, ["supplier_id"], ["item_id"]),
        ("supplier_material_inventory_policy", bundle.supplier_material_inventory_policy, ["supplier_id"], ["item_id"]),
    ]
    for table_name, frame, supplier_columns, item_columns in checks:
        if frame.empty:
            continue
        for column in supplier_columns:
            if column not in frame.columns:
                continue
            missing = sorted(set(frame[column].dropna().astype(str)) - supplier_ids)
            if missing:
                report.add(
                    "error",
                    f"{table_name}_{column}_fk",
                    f"Table '{table_name}' contains unknown suppliers.",
                    supplier_ids=missing,
                )
        for column in item_columns:
            if column not in frame.columns:
                continue
            missing = sorted(set(frame[column].dropna().astype(str)) - item_ids)
            if missing:
                report.add(
                    "error",
                    f"{table_name}_{column}_fk",
                    f"Table '{table_name}' contains unknown items.",
                    item_ids=missing,
                )


def _validate_bom(bundle: StandardBundle, report: ValidationReport) -> None:
    graph = nx.DiGraph()
    for row in bundle.bom_edges.itertuples(index=False):
        graph.add_edge(row.child_item_id, row.parent_item_id)
    if not nx.is_directed_acyclic_graph(graph):
        report.add("error", "bom_dag", "BOM graph contains cycles.")
    else:
        report.add("info", "bom_dag", "BOM graph is a valid DAG.", node_count=graph.number_of_nodes(), edge_count=graph.number_of_edges())


def _validate_final_product(bundle: StandardBundle, report: ValidationReport) -> None:
    final_products = bundle.items.loc[bundle.items["is_final_product"], "item_id"].tolist()
    if not final_products:
        report.add("error", "final_product", "No final product found in standardized items.")
    elif len(final_products) > 1:
        report.add("warning", "final_product", "More than one final product found; simulation will use the first by default.", final_products=final_products)
    else:
        report.add("info", "final_product", "Single final product detected.", final_product_id=final_products[0])


def _validate_supply_map(bundle: StandardBundle, report: ValidationReport) -> None:
    supply_map = bundle.supplier_item_map
    if "is_current_source" in supply_map.columns:
        current_source_mask = supply_map["is_current_source"].fillna(~supply_map["is_backup"]).astype(bool)
    else:
        current_source_mask = ~supply_map["is_backup"].astype(bool)
    current_rows = supply_map.loc[current_source_mask]
    primary_count = current_rows.groupby("item_id")["is_primary"].sum()
    bad_items = primary_count.loc[primary_count == 0].index.tolist()
    if bad_items:
        report.add("error", "primary_source", "Some current-supply items do not have a primary supplier.", item_ids=bad_items)

    alt_self_cycle = bundle.part_alternatives.loc[
        bundle.part_alternatives["item_id"] == bundle.part_alternatives["alt_item_id"]
    ]
    if not alt_self_cycle.empty:
        report.add("error", "alt_self_cycle", "Equivalent material table contains self cycles.", rows=alt_self_cycle.to_dict("records"))

    share_sum = bundle.supplier_item_map.groupby("item_id")["share"].sum().round(4)
    inconsistent = share_sum.loc[share_sum > 1.001].index.tolist()
    if inconsistent:
        report.add("warning", "share_sum", "Some item share sums exceed 1.0; synthetic backups are expected to use share 0.", item_ids=inconsistent)
