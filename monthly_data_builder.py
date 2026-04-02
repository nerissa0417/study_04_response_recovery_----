from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOCAL_TABLES_ROOT = Path(__file__).resolve().parent / "tables"
DEFAULT_SOURCE_RUN = "study00_manual_run"
DEFAULT_OUTPUT_RUN = "interruption_monthly_sample_12m"
TOTAL_MONTHS = 12
HISTORY_MONTHS = 6
INTERRUPTION_DURATION = 3
DEFAULT_MONTH_LABELS = [f"2025-{month:02d}" for month in range(1, TOTAL_MONTHS + 1)]
MONTHLY_BASELINE_DAYS = 30
REQUIRED_SOURCE_TABLES = (
    "Material_Summary_Table",
    "Supplier_Summary_Table",
    "Order_Table",
    "Material_BOM",
    "Supplier_Network",
    "Equivalent_Material_Table",
)
DIRECT_SUPPLY_EVENT_CAUSES = {
    "断供": "incident_supply_cutoff",
    "质量事故": "incident_quality_failure",
    "自然灾害": "incident_natural_disaster",
    "系统故障": "incident_system_failure",
}
EVENT_PRIORITY = {
    "自然灾害": 4,
    "断供": 3,
    "质量事故": 2,
    "系统故障": 1,
}


def load_json(path: Path) -> object:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    return json.loads(path.read_text(encoding="utf-8-sig"))


def dump_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def round_qty(value: float) -> int:
    return max(0, int(round(value)))


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator


def to_float(row: dict, key: str) -> float:
    return float(row[key])


def to_int(row: dict, key: str) -> int:
    return int(float(row[key]))


def usable_order_output_qty(row: dict) -> int:
    incoming_qty = to_int(row, "Incoming_Total_Qty")
    defective_qty = min(incoming_qty, to_int(row, "Defective_Quantity"))
    is_returned = int(float(row["Is_Returned"])) == 1
    if is_returned:
        return 0
    return max(0, incoming_qty - defective_qty)


def monthly_phase(month_index: int) -> str:
    return "history" if month_index <= HISTORY_MONTHS else "forecast"


def normalize_month_key(value: object) -> str:
    raw = str(value).strip()
    if not raw or raw.lower() == "none":
        return ""
    raw = raw.replace("/", "-")
    parts = raw.split("-")
    if len(parts) < 2:
        return ""
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return ""
    if month < 1 or month > 12:
        return ""
    return f"{year:04d}-{month:02d}"


def shift_month_key(month_key: str, offset: int) -> str:
    year, month = map(int, month_key.split("-"))
    absolute = year * 12 + (month - 1) + offset
    target_year = absolute // 12
    target_month = absolute % 12 + 1
    return f"{target_year:04d}-{target_month:02d}"


def build_month_labels(source_tables: dict[str, list[dict]]) -> list[str]:
    month_keys: list[str] = []
    for row in source_tables.get("Order_Table", []):
        for field in ("Order_Create_Date", "Promised_Delivery_Date", "Order_Delivery_Date"):
            month_key = normalize_month_key(row.get(field, ""))
            if month_key:
                month_keys.append(month_key)
    for row in source_tables.get("emergency_incident", []):
        for field in ("Time_of_the_Incident", "First_Response_Time"):
            month_key = normalize_month_key(row.get(field, ""))
            if month_key:
                month_keys.append(month_key)
    if not month_keys:
        return list(DEFAULT_MONTH_LABELS)
    start_month = min(month_keys)
    return [shift_month_key(start_month, offset) for offset in range(TOTAL_MONTHS)]


def build_month_index(month_labels: list[str]) -> dict[str, int]:
    return {month_label: month_index for month_index, month_label in enumerate(month_labels, start=1)}


def material_matches_scope(material: dict, node_scope: str) -> bool:
    is_critical = int(float(material.get("Is_Critical_Material", 0))) == 1
    if node_scope == "general":
        return not is_critical
    return is_critical


def supplier_matches_scope(
    supplier_id: str,
    critical_suppliers: set[str],
    node_scope: str,
) -> bool:
    is_critical = supplier_id in critical_suppliers
    if node_scope == "general":
        return not is_critical
    return is_critical


def average_nonzero(values: list[int]) -> int:
    nonzero_values = [value for value in values if value > 0]
    if not nonzero_values:
        return 0
    return round_qty(sum(nonzero_values) / len(nonzero_values))


def clamp_efficiency(value: float, default: float = 0.9) -> float:
    if value <= 0:
        return default
    return min(1.0, max(0.0, value))


def load_source_tables(source_run: str) -> dict[str, list[dict]]:
    if LOCAL_TABLES_ROOT.exists():
        local_table_names = {path.stem for path in LOCAL_TABLES_ROOT.glob("*.json")}
        if set(REQUIRED_SOURCE_TABLES).issubset(local_table_names):
            return {
                path.stem: load_json(path)
                for path in sorted(LOCAL_TABLES_ROOT.glob("*.json"))
            }

    tables_root = PROJECT_ROOT / "workspace" / "runs" / source_run / "study_00_data" / "tables"
    if not tables_root.exists():
        raise FileNotFoundError(
            f"Missing source tables under {tables_root}. "
            "Run study_00_data first or pass a different --source-run."
        )

    return {
        table_name: load_json(tables_root / f"{table_name}.json")
        for table_name in REQUIRED_SOURCE_TABLES
    }


def build_material_context(
    material_rows: list[dict],
    order_rows: list[dict],
    bom_rows: list[dict],
    month_labels: list[str],
    month_index_by_key: dict[str, int],
    explicit_critical_material_ids: set[str] | None = None,
) -> tuple[
    list[str],
    dict[str, dict],
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, int],
    dict[str, dict[int, int]],
    dict[str, dict[int, float]],
    dict[str, dict[int, int]],
]:
    explicit_critical_material_ids = explicit_critical_material_ids or set()
    critical_flag_source = (
        "config.critical_material_ids"
        if explicit_critical_material_ids
        else "Material_Summary_Table.Is_Critical_Material"
    )
    materials_by_id = {
        row["Material_ID"]: {
            **row,
            "Is_Critical_Material": (
                1
                if explicit_critical_material_ids and row["Material_ID"] in explicit_critical_material_ids
                else int(float(row["Is_Critical_Material"]))
            ),
            "Critical_Flag_Source": critical_flag_source,
        }
        for row in material_rows
    }
    material_ids = sorted(materials_by_id)

    children_by_material: dict[str, list[str]] = defaultdict(list)
    parents_by_material: dict[str, list[str]] = defaultdict(list)
    for row in bom_rows:
        parent_id = row["Material_ID"]
        child_id = row["Downstream_Material_ID"]
        children_by_material[parent_id].append(child_id)
        parents_by_material[child_id].append(parent_id)

    monthly_order_demand: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    monthly_theoretical_capacity: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    monthly_usable_output: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for row in order_rows:
        material_id = row["Material_ID"]

        demand_month_index = month_index_by_key.get(
            normalize_month_key(row.get("Promised_Delivery_Date", ""))
        )
        if demand_month_index:
            monthly_order_demand[material_id][demand_month_index] += to_int(row, "Purchase_Quantity")

        production_month_index = month_index_by_key.get(
            normalize_month_key(row.get("Promised_Delivery_Date", ""))
        ) or month_index_by_key.get(normalize_month_key(row.get("Order_Create_Date", "")))
        if production_month_index:
            monthly_theoretical_capacity[material_id][production_month_index] += min(
                to_int(row, "Theoretical_Capacity"),
                to_int(row, "Purchase_Quantity"),
            )

        output_month_index = month_index_by_key.get(
            normalize_month_key(row.get("Order_Delivery_Date", ""))
        ) or month_index_by_key.get(normalize_month_key(row.get("Promised_Delivery_Date", "")))
        if output_month_index:
            monthly_usable_output[material_id][output_month_index] += usable_order_output_qty(row)

    initial_inventory_by_material: dict[str, int] = {}
    monthly_planned_production_by_material: dict[str, dict[int, int]] = {}
    monthly_output_efficiency_by_material: dict[str, dict[int, float]] = {}
    monthly_planned_demand_by_material: dict[str, dict[int, int]] = {}

    for material_id in material_ids:
        material = materials_by_id[material_id]
        demand_by_month = monthly_order_demand[material_id]
        capacity_by_month = monthly_theoretical_capacity[material_id]
        output_by_month = monthly_usable_output[material_id]

        consumption_baseline = round_qty(
            to_float(material, "Avg_Daily_Consumption") * MONTHLY_BASELINE_DAYS
        )
        fallback_demand_qty = max(
            consumption_baseline,
            average_nonzero(list(demand_by_month.values())),
            1,
        )
        fallback_production_qty = max(
            average_nonzero(list(capacity_by_month.values())),
            average_nonzero(list(output_by_month.values())),
            round_qty(fallback_demand_qty * 0.85),
            1,
        )
        overall_efficiency = clamp_efficiency(
            safe_ratio(
                sum(output_by_month.values()),
                max(sum(capacity_by_month.values()), 1),
                default=safe_ratio(
                    sum(output_by_month.values()),
                    max(sum(demand_by_month.values()), 1),
                    default=0.9,
                ),
            )
        )

        initial_inventory_by_material[material_id] = round_qty(
            to_float(material, "Available_Inventory_Qty")
        )
        monthly_planned_production_by_material[material_id] = {}
        monthly_output_efficiency_by_material[material_id] = {}
        monthly_planned_demand_by_material[material_id] = {}

        for month_index in range(1, TOTAL_MONTHS + 1):
            order_demand_qty = demand_by_month.get(month_index, 0)
            planned_demand_qty = order_demand_qty if order_demand_qty > 0 else fallback_demand_qty

            planned_production_qty = capacity_by_month.get(month_index, 0)
            if planned_production_qty <= 0:
                planned_production_qty = fallback_production_qty

            actual_output_qty = output_by_month.get(month_index, 0)
            if capacity_by_month.get(month_index, 0) > 0:
                month_efficiency = safe_ratio(
                    actual_output_qty,
                    capacity_by_month[month_index],
                    default=overall_efficiency,
                )
            elif planned_production_qty > 0 and actual_output_qty > 0:
                month_efficiency = safe_ratio(
                    actual_output_qty,
                    planned_production_qty,
                    default=overall_efficiency,
                )
            else:
                month_efficiency = overall_efficiency

            monthly_planned_demand_by_material[material_id][month_index] = round_qty(
                planned_demand_qty
            )
            monthly_planned_production_by_material[material_id][month_index] = round_qty(
                planned_production_qty
            )
            monthly_output_efficiency_by_material[material_id][month_index] = clamp_efficiency(
                month_efficiency,
                default=overall_efficiency,
            )

    return (
        material_ids,
        materials_by_id,
        {key: sorted(value) for key, value in children_by_material.items()},
        {key: sorted(value) for key, value in parents_by_material.items()},
        initial_inventory_by_material,
        monthly_planned_production_by_material,
        monthly_output_efficiency_by_material,
        monthly_planned_demand_by_material,
    )


def build_supplier_context(
    supplier_rows: list[dict],
    order_rows: list[dict],
    supplier_network_rows: list[dict],
    explicit_critical_supplier_ids: set[str] | None = None,
) -> tuple[
    list[str],
    dict[str, dict],
    dict[str, list[str]],
    dict[str, list[str]],
    set[str],
    str,
]:
    suppliers_by_id = {row["Supplier_ID"]: row for row in supplier_rows}
    supplier_ids = sorted(suppliers_by_id)

    supplier_materials: dict[str, set[str]] = defaultdict(set)
    for row in order_rows:
        supplier_id = row["Supplier_ID"]
        material_id = row["Material_ID"]
        supplier_materials[supplier_id].add(material_id)

    outgoing_edges: dict[str, list[str]] = defaultdict(list)
    for row in supplier_network_rows:
        upstream_supplier_id = row["Supplier_ID"]
        downstream_supplier_id = row["Supplier_down_ID"]
        outgoing_edges[upstream_supplier_id].append(downstream_supplier_id)
    if explicit_critical_supplier_ids:
        critical_suppliers = {
            supplier_id
            for supplier_id in supplier_ids
            if supplier_id in explicit_critical_supplier_ids
        }
        critical_flag_source = "config.critical_supplier_ids"
    else:
        direct_flag_suppliers = {
            supplier_id
            for supplier_id, row in suppliers_by_id.items()
            if "Is_Critical_Supplier" in row and int(float(row["Is_Critical_Supplier"])) == 1
        }
        if direct_flag_suppliers:
            critical_suppliers = direct_flag_suppliers
            critical_flag_source = "Supplier_Summary_Table.Is_Critical_Supplier"
        else:
            critical_suppliers = {
                supplier_id
                for supplier_id, row in suppliers_by_id.items()
                if int(float(row.get("Is_Chain_Owner_Supplier", 0))) == 1
            }
            critical_flag_source = "Supplier_Summary_Table.Is_Chain_Owner_Supplier"

    return (
        supplier_ids,
        suppliers_by_id,
        {key: sorted(value) for key, value in supplier_materials.items()},
        {key: sorted(value) for key, value in outgoing_edges.items()},
        critical_suppliers,
        critical_flag_source,
    )


def build_material_suppliers(
    supplier_materials: dict[str, list[str]],
) -> dict[str, list[str]]:
    material_suppliers: dict[str, set[str]] = defaultdict(set)
    for supplier_id, material_ids in supplier_materials.items():
        for material_id in material_ids:
            material_suppliers[material_id].add(supplier_id)
    return {
        material_id: sorted(supplier_ids)
        for material_id, supplier_ids in material_suppliers.items()
    }


def build_supplier_monthly_planned_demand(
    order_rows: list[dict],
    month_index_by_key: dict[str, int],
) -> dict[str, dict[int, int]]:
    monthly_demand_by_supplier: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for row in order_rows:
        active_months: set[int] = set()
        for field in ("Order_Create_Date", "Promised_Delivery_Date", "Order_Delivery_Date"):
            month_index = month_index_by_key.get(normalize_month_key(row.get(field, "")))
            if month_index:
                active_months.add(month_index)
        for month_index in active_months:
            monthly_demand_by_supplier[row["Supplier_ID"]][month_index] += 1
    return {
        supplier_id: dict(month_map)
        for supplier_id, month_map in monthly_demand_by_supplier.items()
    }


def build_supplier_demand_edge_context(
    supplier_ids: list[str],
    outgoing_edges: dict[str, list[str]],
    supplier_materials: dict[str, list[str]],
    children_by_material: dict[str, list[str]],
    monthly_planned_demand_by_material: dict[str, dict[int, int]],
    monthly_planned_production_by_material: dict[str, dict[int, int]],
) -> tuple[
    dict[tuple[str, str], list[tuple[str, str]]],
    dict[tuple[str, str], dict[int, int]],
    dict[tuple[str, str], str],
]:
    supplier_monthly_material_activity: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for supplier_id, material_ids in supplier_materials.items():
        for month_index in range(1, TOTAL_MONTHS + 1):
            active_material_count = sum(
                1
                for material_id in material_ids
                if monthly_planned_demand_by_material.get(material_id, {}).get(month_index, 0) > 0
                or monthly_planned_production_by_material.get(material_id, {}).get(month_index, 0)
                > 0
            )
            if active_material_count > 0:
                supplier_monthly_material_activity[supplier_id][month_index] = active_material_count

    edge_material_pairs: dict[tuple[str, str], list[tuple[str, str]]] = {}
    edge_monthly_active_counts: dict[tuple[str, str], dict[int, int]] = {}
    edge_activity_sources: dict[tuple[str, str], str] = {}

    for supplier_id in supplier_ids:
        upstream_material_ids = supplier_materials.get(supplier_id, [])
        for downstream_supplier_id in outgoing_edges.get(supplier_id, []):
            downstream_material_ids = set(supplier_materials.get(downstream_supplier_id, []))
            edge_key = (supplier_id, downstream_supplier_id)
            linked_pairs = sorted(
                {
                    (upstream_material_id, downstream_material_id)
                    for upstream_material_id in upstream_material_ids
                    for downstream_material_id in children_by_material.get(upstream_material_id, [])
                    if downstream_material_id in downstream_material_ids
                }
            )
            edge_material_pairs[edge_key] = linked_pairs
            edge_monthly_active_counts[edge_key] = {}
            edge_activity_sources[edge_key] = (
                "Material_BOM_linked_downstream_material_plan"
                if linked_pairs
                else "downstream_supplier_material_activity_fallback"
            )

            for month_index in range(1, TOTAL_MONTHS + 1):
                if linked_pairs:
                    active_count = sum(
                        1
                        for _, downstream_material_id in linked_pairs
                        if monthly_planned_demand_by_material.get(
                            downstream_material_id,
                            {},
                        ).get(month_index, 0)
                        > 0
                        or monthly_planned_production_by_material.get(
                            downstream_material_id,
                            {},
                        ).get(month_index, 0)
                        > 0
                    )
                else:
                    active_count = supplier_monthly_material_activity.get(
                        downstream_supplier_id,
                        {},
                    ).get(month_index, 0)
                edge_monthly_active_counts[edge_key][month_index] = active_count

    return edge_material_pairs, edge_monthly_active_counts, edge_activity_sources


def build_event_driven_material_shocks(
    source_tables: dict[str, list[dict]],
    supplier_materials: dict[str, list[str]],
    materials_by_id: dict[str, dict],
    children_by_material: dict[str, list[str]],
    month_index_by_key: dict[str, int],
) -> list[dict]:
    incidents_by_id = {
        row["Emergency_Incident_ID"]: row
        for row in source_tables.get("emergency_incident", [])
    }
    selected_shocks: dict[tuple[str, int], dict] = {}

    for row in source_tables.get("Supplier_Emergency_Incident_Table", []):
        supplier_id = row["Supplier_ID"]
        incident = incidents_by_id.get(row["Emergency_Incident_ID"])
        if not incident:
            continue
        event_type = incident.get("Event_Type", "")
        if event_type not in DIRECT_SUPPLY_EVENT_CAUSES:
            continue
        month_index = month_index_by_key.get(
            normalize_month_key(incident.get("Time_of_the_Incident", ""))
        )
        if not month_index:
            continue

        ranked_materials = sorted(
            supplier_materials.get(supplier_id, []),
            key=lambda material_id: (
                1 if materials_by_id[material_id]["Is_Critical_Material"] == 1 else 0,
                len(children_by_material.get(material_id, [])),
                to_float(materials_by_id[material_id], "Avg_Daily_Consumption"),
                material_id,
            ),
            reverse=True,
        )
        target_material_id = next(
            (
                material_id
                for material_id in ranked_materials
                if materials_by_id[material_id]["Is_Critical_Material"] == 1
            ),
            "",
        )
        if not target_material_id:
            continue

        shock_key = (target_material_id, month_index)
        candidate = {
            "month_index": month_index,
            "material_id": target_material_id,
            "cause": DIRECT_SUPPLY_EVENT_CAUSES[event_type],
            "source_supplier_id": supplier_id,
            "incident_id": incident["Emergency_Incident_ID"],
            "event_type": event_type,
            "direct_source": "Supplier_Emergency_Incident_Table+emergency_incident",
            "_priority": EVENT_PRIORITY.get(event_type, 0),
        }
        existing = selected_shocks.get(shock_key)
        if existing is None or candidate["_priority"] > existing["_priority"]:
            selected_shocks[shock_key] = candidate

    return [
        {
            key: value
            for key, value in shock.items()
            if key != "_priority"
        }
        for shock in sorted(
            selected_shocks.values(),
            key=lambda row: (row["month_index"], row["material_id"]),
        )
    ]


def build_forced_zero_demand_lookup(
    scenario_tuning: dict | None,
) -> dict[tuple[str, int], str]:
    lookup: dict[tuple[str, int], str] = {}
    for row in (scenario_tuning or {}).get("demo_force_zero_demand", []):
        supplier_id = row.get("supplier_id", "")
        for month_index in row.get("month_indices", []):
            lookup[(supplier_id, int(month_index))] = "connection_level_no_demand"
    return lookup


def simulate_material_monthly_state(
    material_ids: list[str],
    materials_by_id: dict[str, dict],
    children_by_material: dict[str, list[str]],
    parents_by_material: dict[str, list[str]],
    initial_inventory_by_material: dict[str, int],
    monthly_planned_production_by_material: dict[str, dict[int, int]],
    monthly_output_efficiency_by_material: dict[str, dict[int, float]],
    monthly_planned_demand_by_material: dict[str, dict[int, int]],
    month_labels: list[str],
    material_shocks: list[dict],
    supplier_mode: str = "supply",
    node_scope: str = "critical",
    allow_recovery_actions: bool = True,
    supplier_ids: list[str] | None = None,
    suppliers_by_id: dict[str, dict] | None = None,
    supplier_materials: dict[str, list[str]] | None = None,
    critical_suppliers: set[str] | None = None,
    supplier_critical_flag_source: str = "",
    material_suppliers_by_material: dict[str, list[str]] | None = None,
) -> tuple[list[dict], list[dict], dict[int, dict[str, dict]], list[dict]]:
    shock_lookup = {
        (shock["material_id"], shock["month_index"]): shock
        for shock in material_shocks
    }
    opening_inventory = dict(initial_inventory_by_material)
    material_active_until: dict[str, int] = {material_id: 0 for material_id in material_ids}
    scheduled_recovery_qty: dict[tuple[int, str], int] = defaultdict(int)
    interrupted_by_month: dict[int, set[str]] = defaultdict(set)
    previous_supply_interrupted_suppliers: set[str] = set()
    supplier_active_until: dict[str, int] = {
        supplier_id: 0
        for supplier_id in (supplier_ids or [])
    }

    monthly_rows: list[dict] = []
    recovery_rows: list[dict] = []
    supplier_supply_rows: list[dict] = []
    row_lookup_by_month: dict[int, dict[str, dict]] = defaultdict(dict)

    for month_index in range(1, TOTAL_MONTHS + 1):
        previous_interrupted = interrupted_by_month.get(month_index - 1, set())
        current_month_rows: dict[str, dict] = {}
        for material_id in material_ids:
            material = materials_by_id[material_id]
            is_critical = material["Is_Critical_Material"] == 1
            is_scope_target = material_matches_scope(material, node_scope)
            planned_demand_qty = monthly_planned_demand_by_material[material_id][month_index]
            baseline_planned_production_qty = monthly_planned_production_by_material[material_id][
                month_index
            ]
            baseline_output_efficiency = monthly_output_efficiency_by_material[material_id][
                month_index
            ]

            inventory_begin_qty = opening_inventory[material_id]
            recovery_effective_qty = scheduled_recovery_qty[(month_index, material_id)]
            upstream_material_ids = parents_by_material.get(material_id, [])
            upstream_interrupted_count = sum(
                1
                for upstream_material_id in upstream_material_ids
                if upstream_material_id in previous_interrupted
            )
            upstream_interrupted_ratio = (
                upstream_interrupted_count / len(upstream_material_ids)
                if upstream_material_ids
                else 0.0
            )
            producing_supplier_ids = (material_suppliers_by_material or {}).get(material_id, [])
            interrupted_producing_supplier_count = sum(
                1
                for supplier_id in producing_supplier_ids
                if supplier_id in previous_supply_interrupted_suppliers
            )
            supplier_interrupted_ratio = (
                interrupted_producing_supplier_count / len(producing_supplier_ids)
                if producing_supplier_ids
                else 0.0
            )
            shock = shock_lookup.get((material_id, month_index))
            is_window_active = material_active_until[material_id] >= month_index

            if is_window_active:
                planned_production_qty = 0
                actual_output_qty = 0
                trigger_reason = "continuing_interruption_window"
                is_new_interruption = 0
                final_status = "interrupted"
            else:
                if shock:
                    planned_production_qty = 0
                else:
                    production_multiplier = max(0.0, 1.0 - (0.55 * upstream_interrupted_ratio))
                    if supplier_mode == "supply":
                        production_multiplier *= max(0.0, 1.0 - supplier_interrupted_ratio)
                    planned_production_qty = round_qty(
                        baseline_planned_production_qty * production_multiplier
                    )

                effective_available_qty = (
                    inventory_begin_qty + planned_production_qty + recovery_effective_qty
                )
                severe_shortage = shock is not None or upstream_interrupted_ratio >= 0.75
                if (
                    supplier_mode == "supply"
                    and producing_supplier_ids
                    and interrupted_producing_supplier_count == len(producing_supplier_ids)
                ):
                    severe_shortage = True
                actual_output_qty = 0
                if not severe_shortage and effective_available_qty > 0:
                    actual_output_qty = min(
                        planned_demand_qty,
                        effective_available_qty,
                        round_qty(
                            planned_production_qty * baseline_output_efficiency
                            + recovery_effective_qty
                        ),
                    )
                balance_qty = effective_available_qty - planned_demand_qty

                if is_scope_target and balance_qty < 0 and actual_output_qty == 0:
                    material_active_until[material_id] = month_index + INTERRUPTION_DURATION - 1
                    final_status = "interrupted"
                    if shock:
                        trigger_reason = shock["cause"]
                    elif (
                        supplier_mode == "supply"
                        and producing_supplier_ids
                        and interrupted_producing_supplier_count == len(producing_supplier_ids)
                    ):
                        trigger_reason = "all_producing_suppliers_interrupted_previous_month"
                    elif upstream_interrupted_count > 0:
                        trigger_reason = "upstream_material_pressure_and_zero_output"
                    else:
                        trigger_reason = "balance_negative_and_zero_output"
                    is_new_interruption = 1
                elif (
                    balance_qty < 0
                    or upstream_interrupted_count > 0
                    or interrupted_producing_supplier_count > 0
                ):
                    final_status = "affected"
                    if interrupted_producing_supplier_count > 0 and supplier_mode == "supply":
                        trigger_reason = "supplier_supply_pressure_from_previous_month"
                    elif upstream_interrupted_count > 0:
                        trigger_reason = "negative_balance_or_upstream_pressure"
                    else:
                        trigger_reason = "negative_balance"
                    is_new_interruption = 0
                else:
                    final_status = "normal"
                    trigger_reason = "none"
                    is_new_interruption = 0

            effective_available_qty = (
                inventory_begin_qty + planned_production_qty + recovery_effective_qty
            )
            balance_qty = effective_available_qty - planned_demand_qty
            unmet_demand_qty = max(0, planned_demand_qty - actual_output_qty)
            inventory_end_qty = max(0, effective_available_qty - actual_output_qty)

            if final_status == "interrupted":
                interrupted_by_month[month_index].add(material_id)

            row = {
                "Month_Index": month_index,
                "Month_Label": month_labels[month_index - 1],
                "Data_Phase": monthly_phase(month_index),
                "Material_ID": material_id,
                "Material_Name": material["Material_Name"],
                "Is_Critical_Material": int(is_critical),
                "Critical_Flag_Source": material.get("Critical_Flag_Source", ""),
                "Inventory_Begin_Qty": inventory_begin_qty,
                "Planned_Production_Qty": planned_production_qty,
                "Recovery_Effective_Qty": recovery_effective_qty,
                "Planned_Demand_Qty": planned_demand_qty,
                "Actual_Output_Qty": actual_output_qty,
                "Inventory_Source": "Material_Summary_Table.Available_Inventory_Qty_then_roll_forward",
                "Production_Source": (
                    "Order_Table.Theoretical_Capacity_allocated_by_Promised_Delivery_Date"
                ),
                "Demand_Source": (
                    "Order_Table.Purchase_Quantity_allocated_by_Promised_Delivery_Date"
                    "_with_Avg_Daily_Consumption_fallback"
                ),
                "Output_Source": (
                    "Order_Table.Incoming_Total_Qty_minus_Defective_Quantity"
                    "_with_return_filter_allocated_by_Order_Delivery_Date"
                ),
                "Balance_Qty": balance_qty,
                "Unmet_Demand_Qty": unmet_demand_qty,
                "Upstream_Interrupted_Count": upstream_interrupted_count,
                "Interrupted_Producing_Supplier_Count": interrupted_producing_supplier_count,
                "Producing_Supplier_Count": len(producing_supplier_ids),
                "Supplier_Mode": supplier_mode,
                "Node_Scope": node_scope,
                "Is_Scope_Target": int(is_scope_target),
                "Interruption_Trigger_Reason": trigger_reason,
                "Trigger_Reason": trigger_reason,
                "Is_New_Interruption": is_new_interruption,
                "Disruption_Window_End_Month": material_active_until[material_id]
                if final_status == "interrupted"
                else "",
                "Window_Remaining_Months": max(
                    0,
                    material_active_until[material_id] - month_index + 1,
                )
                if final_status == "interrupted"
                else 0,
                "Final_Status": final_status,
                "Inventory_End_Qty": inventory_end_qty,
            }
            monthly_rows.append(row)
            row_lookup_by_month[month_index][material_id] = row
            current_month_rows[material_id] = row
            opening_inventory[material_id] = inventory_end_qty

            if (
                allow_recovery_actions
                and final_status == "interrupted"
                and is_new_interruption == 1
                and HISTORY_MONTHS < month_index < TOTAL_MONTHS
            ):
                if node_scope == "general":
                    targets = [material_id]
                    strategy_type = "strategy_a_local_replenishment"
                else:
                    downstream_targets = [
                        child_material_id
                        for child_material_id in children_by_material.get(material_id, [])
                        if materials_by_id[child_material_id]["Is_Critical_Material"] == 1
                    ]
                    targets = [material_id] + downstream_targets[:2]
                    strategy_type = "strategy_b_priority_linked_replenishment"
                next_month_index = min(month_index + 1, TOTAL_MONTHS)
                for index, target_material_id in enumerate(targets, start=1):
                    target_month_demand_qty = monthly_planned_demand_by_material[target_material_id].get(
                        next_month_index,
                        monthly_planned_demand_by_material[target_material_id][month_index],
                    )
                    planned_qty = round_qty(
                        target_month_demand_qty
                        * (
                            0.28
                            if node_scope == "general"
                            else 0.35
                            if index == 1
                            else 0.2
                        )
                    )
                    scheduled_recovery_qty[(month_index + 1, target_material_id)] += planned_qty
                    recovery_rows.append(
                        {
                            "Decision_Month": month_index,
                            "Effective_Month": month_index + 1,
                            "Decision_Month_Label": month_labels[month_index - 1],
                            "Effective_Month_Label": month_labels[month_index],
                            "Strategy_Type": strategy_type,
                            "Interruption_Scope": node_scope,
                            "Supplier_Mode": supplier_mode,
                            "Source_Material_ID": material_id,
                            "Target_Material_ID": target_material_id,
                            "Planned_Replenishment_Qty": planned_qty,
                            "Linked_Supplier_IDs": ",".join(
                                (material_suppliers_by_material or {}).get(material_id, [])
                            ),
                            "Timing_Rule": "decide_in_month_m_effective_in_month_m_plus_1",
                        }
                    )

        if supplier_mode != "supply":
            continue

        previous_material_rows = row_lookup_by_month.get(month_index - 1, {})
        current_supply_interrupted_suppliers: set[str] = set()
        for supplier_id in supplier_ids or []:
            supplied_material_ids = (supplier_materials or {}).get(supplier_id, [])
            supplied_material_count = len(supplied_material_ids)
            previous_interrupted_material_count = sum(
                1
                for material_id in supplied_material_ids
                if previous_material_rows.get(material_id, {}).get("Final_Status") == "interrupted"
            )
            current_interrupted_material_count = sum(
                1
                for material_id in supplied_material_ids
                if current_month_rows.get(material_id, {}).get("Final_Status") == "interrupted"
            )
            current_affected_material_count = sum(
                1
                for material_id in supplied_material_ids
                if current_month_rows.get(material_id, {}).get("Final_Status") == "affected"
            )
            all_previous_materials_interrupted = (
                supplied_material_count > 0
                and previous_interrupted_material_count == supplied_material_count
            )
            is_scope_target = supplier_matches_scope(
                supplier_id,
                critical_suppliers or set(),
                node_scope,
            )

            if supplier_active_until[supplier_id] >= month_index:
                final_status = "interrupted"
                is_new_interruption = 0
                trigger_reason = "continuing_interruption_window"
            elif all_previous_materials_interrupted and is_scope_target:
                supplier_active_until[supplier_id] = month_index + INTERRUPTION_DURATION - 1
                final_status = "interrupted"
                is_new_interruption = 1
                trigger_reason = "all_produced_materials_interrupted_previous_month"
            elif (
                all_previous_materials_interrupted
                or current_interrupted_material_count > 0
                or current_affected_material_count > 0
            ):
                final_status = "affected"
                is_new_interruption = 0
                trigger_reason = "current_month_material_pressure_pending_next_month"
            else:
                final_status = "normal"
                is_new_interruption = 0
                trigger_reason = "none"

            if final_status == "interrupted":
                current_supply_interrupted_suppliers.add(supplier_id)

            supplier_supply_rows.append(
                {
                    "Month_Index": month_index,
                    "Month_Label": month_labels[month_index - 1],
                    "Data_Phase": monthly_phase(month_index),
                    "Supplier_ID": supplier_id,
                    "Supplier_Name": (suppliers_by_id or {})[supplier_id]["Supplier_Name"],
                    "Is_Critical_Supplier": int(supplier_id in (critical_suppliers or set())),
                    "Is_Scope_Target": int(is_scope_target),
                    "Supplier_Mode": supplier_mode,
                    "Node_Scope": node_scope,
                    "Critical_Flag_Source": supplier_critical_flag_source,
                    "Supplied_Material_Count": supplied_material_count,
                    "Previous_Interrupted_Material_Count": previous_interrupted_material_count,
                    "Interrupted_Material_Count": current_interrupted_material_count,
                    "Affected_Material_Count": current_affected_material_count,
                    "All_Produced_Materials_Interrupted_Previous_Month": int(
                        all_previous_materials_interrupted
                    ),
                    "Is_New_Interruption": is_new_interruption,
                    "Disruption_Window_End_Month": supplier_active_until[supplier_id]
                    if final_status == "interrupted"
                    else "",
                    "Window_Remaining_Months": max(
                        0,
                        supplier_active_until[supplier_id] - month_index + 1,
                    )
                    if final_status == "interrupted"
                    else 0,
                    "Trigger_Reason": trigger_reason,
                    "Final_Status": final_status,
                }
            )

        previous_supply_interrupted_suppliers = current_supply_interrupted_suppliers

    return monthly_rows, recovery_rows, row_lookup_by_month, supplier_supply_rows


def build_supplier_demand_monthly_state(
    supplier_ids: list[str],
    suppliers_by_id: dict[str, dict],
    outgoing_edges: dict[str, list[str]],
    critical_suppliers: set[str],
    edge_material_pairs: dict[tuple[str, str], list[tuple[str, str]]],
    edge_monthly_active_counts: dict[tuple[str, str], dict[int, int]],
    edge_activity_sources: dict[tuple[str, str], str],
    month_labels: list[str],
    node_scope: str,
    supplier_critical_flag_source: str,
    forced_zero_demand_lookup: dict[tuple[str, int], str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    edge_rows: list[dict] = []
    supplier_rows: list[dict] = []
    demand_seed_rows: list[dict] = []
    active_until: dict[str, int] = {supplier_id: 0 for supplier_id in supplier_ids}
    previous_interrupted_suppliers: set[str] = set()

    for month_index in range(1, TOTAL_MONTHS + 1):
        current_interrupted_suppliers: set[str] = set()
        outgoing_edge_status: dict[str, list[int]] = defaultdict(list)
        outgoing_edge_reasons: dict[str, list[str]] = defaultdict(list)

        for supplier_id in supplier_ids:
            for downstream_supplier_id in outgoing_edges.get(supplier_id, []):
                edge_key = (supplier_id, downstream_supplier_id)
                linked_pairs = edge_material_pairs.get(edge_key, [])
                active_connection_count = edge_monthly_active_counts.get(edge_key, {}).get(
                    month_index,
                    0,
                )
                forced_zero_reason = (forced_zero_demand_lookup or {}).get((supplier_id, month_index))
                downstream_has_planned_demand = active_connection_count > 0
                propagated_zero = downstream_supplier_id in previous_interrupted_suppliers
                if forced_zero_reason:
                    edge_status = 0
                    edge_reason = forced_zero_reason
                    downstream_has_planned_demand = False
                    propagated_zero = False
                else:
                    edge_status = 1 if downstream_has_planned_demand and not propagated_zero else 0
                    edge_reason = (
                        "downstream_supplier_demand_interrupted_previous_month"
                        if propagated_zero
                        else "connection_level_demand_active"
                        if downstream_has_planned_demand
                        else "connection_level_no_demand"
                    )
                outgoing_edge_status[supplier_id].append(edge_status)
                outgoing_edge_reasons[supplier_id].append(edge_reason)
                edge_rows.append(
                    {
                        "Month_Index": month_index,
                        "Month_Label": month_labels[month_index - 1],
                        "Data_Phase": monthly_phase(month_index),
                        "Supplier_ID": supplier_id,
                        "Supplier_down_ID": downstream_supplier_id,
                        "Demand_Edge_Status": edge_status,
                        "Status_Definition": "1_active_demand_0_no_demand",
                        "Linked_Material_Pair_Count": len(linked_pairs),
                        "Active_Linked_Material_Pair_Count": active_connection_count,
                        "Demand_Source": edge_activity_sources.get(
                            edge_key,
                            "downstream_supplier_material_activity_fallback",
                        ),
                        "Supplier_Mode": "demand",
                        "Node_Scope": node_scope,
                        "Demand_Override_Flag": int(bool(forced_zero_reason)),
                        "Trigger_Reason": edge_reason,
                    }
                )

        for supplier_id in supplier_ids:
            edge_statuses = outgoing_edge_status.get(supplier_id, [])
            edge_reasons = outgoing_edge_reasons.get(supplier_id, [])
            total_edge_count = len(edge_statuses)
            zero_demand_edge_count = edge_statuses.count(0)
            active_edge_count = edge_statuses.count(1)
            trigger_condition = total_edge_count > 0 and zero_demand_edge_count == total_edge_count
            direct_zero_demand = trigger_condition and all(
                reason == "connection_level_no_demand" for reason in edge_reasons
            )
            is_scope_target = supplier_matches_scope(
                supplier_id,
                critical_suppliers,
                node_scope,
            )

            if active_until[supplier_id] >= month_index:
                final_status = "interrupted"
                trigger_reason = "continuing_interruption_window"
                is_new_interruption = 0
            elif trigger_condition and is_scope_target:
                active_until[supplier_id] = month_index + INTERRUPTION_DURATION - 1
                final_status = "interrupted"
                trigger_reason = (
                    "all_demand_edges_zero_from_connection_level_plan_gap"
                    if direct_zero_demand
                    else "all_demand_edges_zero_after_previous_month_propagation"
                )
                is_new_interruption = 1
                if direct_zero_demand:
                    demand_seed_rows.append(
                        {
                            "Scenario_Type": "supplier_demand_seed",
                            "Month_Index": month_index,
                            "Month_Label": month_labels[month_index - 1],
                            "Target_ID": supplier_id,
                            "Cause": "all_connection_level_demand_edges_zero",
                            "Rule_Note": (
                                "supplier_demand_interruption_uses_single_scenario"
                                "_and_all_edges_zero_trigger"
                            ),
                        }
                    )
            elif trigger_condition or zero_demand_edge_count > 0:
                final_status = "affected"
                trigger_reason = (
                    "all_demand_edges_zero_but_out_of_scope"
                    if trigger_condition
                    else "partial_zero_demand_edges"
                )
                is_new_interruption = 0
            else:
                final_status = "normal"
                trigger_reason = "none"
                is_new_interruption = 0

            if final_status == "interrupted":
                current_interrupted_suppliers.add(supplier_id)

            supplier_rows.append(
                {
                    "Month_Index": month_index,
                    "Month_Label": month_labels[month_index - 1],
                    "Data_Phase": monthly_phase(month_index),
                    "Supplier_ID": supplier_id,
                    "Supplier_Name": suppliers_by_id[supplier_id]["Supplier_Name"],
                    "Is_Critical_Supplier": int(supplier_id in critical_suppliers),
                    "Is_Scope_Target": int(is_scope_target),
                    "Supplier_Mode": "demand",
                    "Node_Scope": node_scope,
                    "Critical_Flag_Source": supplier_critical_flag_source,
                    "Demand_Edge_Count": total_edge_count,
                    "Active_Demand_Edge_Count": active_edge_count,
                    "Zero_Demand_Edge_Count": zero_demand_edge_count,
                    "Trigger_Condition_All_Edges_Zero": int(trigger_condition),
                    "Is_New_Interruption": is_new_interruption,
                    "Disruption_Window_End_Month": active_until[supplier_id]
                    if final_status == "interrupted"
                    else "",
                    "Window_Remaining_Months": max(0, active_until[supplier_id] - month_index + 1)
                    if final_status == "interrupted"
                    else 0,
                    "Trigger_Reason": trigger_reason,
                    "Final_Status": final_status,
                }
            )

        previous_interrupted_suppliers = current_interrupted_suppliers

    return edge_rows, supplier_rows, demand_seed_rows


def build_seed_summary(
    material_shocks: list[dict],
    demand_seed_rows: list[dict],
    month_labels: list[str],
) -> list[dict]:
    seed_rows = []
    for shock in material_shocks:
        seed_rows.append(
            {
                "Scenario_Type": "material_supply_seed",
                "Month_Index": shock["month_index"],
                "Month_Label": month_labels[shock["month_index"] - 1],
                "Target_ID": shock["material_id"],
                "Cause": shock["cause"],
                "Source_Supplier_ID": shock.get("source_supplier_id", ""),
                "Source_Incident_ID": shock.get("incident_id", ""),
                "Source_Event_Type": shock.get("event_type", ""),
                "Rule_Note": (
                    "critical_material_can_trigger_interruption_when_balance_lt_zero"
                    "_and_output_zero"
                ),
            }
        )
    seed_rows.extend(demand_seed_rows)
    return sorted(seed_rows, key=lambda row: (row["Month_Index"], row["Scenario_Type"], row["Target_ID"]))


def build_summary_markdown(
    output_run: str,
    material_rows: list[dict],
    supplier_supply_rows: list[dict],
    demand_edge_rows: list[dict],
    supplier_demand_rows: list[dict],
    recovery_rows: list[dict],
    seed_rows: list[dict],
    month_labels: list[str],
    supplier_mode: str,
    node_scope: str,
) -> str:
    interrupted_material_rows = [
        row for row in material_rows if row["Final_Status"] == "interrupted"
    ]
    interrupted_supplier_supply_rows = [
        row for row in supplier_supply_rows if row["Final_Status"] == "interrupted"
    ]
    interrupted_supplier_demand_rows = [
        row for row in supplier_demand_rows if row["Final_Status"] == "interrupted"
    ]
    return "\n".join(
        [
            "# 12-month interruption sample dataset",
            "",
            f"- Output run id: `{output_run}`",
            f"- Month window: `{month_labels[0]}` to `{month_labels[-1]}`",
            f"- History months: `{month_labels[0]}` to `{month_labels[HISTORY_MONTHS - 1]}`",
            f"- Forecast months: `{month_labels[HISTORY_MONTHS]}` to `{month_labels[-1]}`",
            f"- Interruption duration L: `{INTERRUPTION_DURATION}`",
            f"- Supplier scenario mode: `{supplier_mode}`",
            f"- Node scope: `{node_scope}`",
            "",
            "## Generated tables",
            "",
            f"- `material_monthly_state`: `{len(material_rows)}` rows",
            f"- `supplier_monthly_supply_state`: `{len(supplier_supply_rows)}` rows",
            f"- `supplier_demand_edge_monthly_state`: `{len(demand_edge_rows)}` rows",
            f"- `supplier_monthly_demand_state`: `{len(supplier_demand_rows)}` rows",
            f"- `recovery_actions`: `{len(recovery_rows)}` rows",
            f"- `scenario_seed_summary`: `{len(seed_rows)}` rows",
            "",
            "## Rule alignment",
            "",
            "- Material interruption uses monthly balance and zero-output trigger.",
            "- Inventory starts from Material_Summary_Table and rolls month by month.",
            "- Demand baseline comes from Order_Table purchase quantity allocated by promised delivery month, with Avg_Daily_Consumption fallback only when a month has no order plan.",
            "- Production baseline comes from Order_Table theoretical capacity allocated by promised delivery month.",
            "- Output baseline comes from usable incoming quantity after defect and return filtering, allocated by actual delivery month.",
            "- Supply-side seeds come from Supplier_Emergency_Incident_Table linked to emergency_incident.",
            "- Supplier supply interruption uses previous-month material results; same month can only become affected from fresh pressure.",
            "- Supplier demand interruption uses connection-level demand edges plus previous-month propagation.",
            "- Recovery actions are only decided in forecast months and become effective next month.",
            "- This is a development sample for rule walkthrough, not a calibrated forecast model.",
            "",
            "## Interruption counts",
            "",
            f"- Interrupted material rows: `{len(interrupted_material_rows)}`",
            f"- Interrupted supplier supply rows: `{len(interrupted_supplier_supply_rows)}`",
            f"- Interrupted supplier demand rows: `{len(interrupted_supplier_demand_rows)}`",
        ]
    )


def build_monthly_dataset_payload(
    source_tables: dict[str, list[dict]],
    allow_recovery_actions: bool = True,
    supplier_mode: str = "supply",
    node_scope: str = "critical",
    critical_supplier_ids: set[str] | None = None,
    critical_material_ids: set[str] | None = None,
    scenario_tuning: dict | None = None,
) -> dict:
    month_labels = build_month_labels(source_tables)
    month_index_by_key = build_month_index(month_labels)

    material_rows = source_tables["Material_Summary_Table"]
    supplier_rows = source_tables["Supplier_Summary_Table"]
    order_rows = source_tables["Order_Table"]
    bom_rows = source_tables["Material_BOM"]
    supplier_network_rows = source_tables["Supplier_Network"]

    (
        material_ids,
        materials_by_id,
        children_by_material,
        parents_by_material,
        initial_inventory_by_material,
        monthly_planned_production_by_material,
        monthly_output_efficiency_by_material,
        monthly_planned_demand_by_material,
    ) = build_material_context(
        material_rows,
        order_rows,
        bom_rows,
        month_labels,
        month_index_by_key,
        explicit_critical_material_ids=critical_material_ids,
    )
    (
        supplier_ids,
        suppliers_by_id,
        supplier_materials,
        outgoing_edges,
        critical_suppliers,
        supplier_critical_flag_source,
    ) = build_supplier_context(
        supplier_rows,
        order_rows,
        supplier_network_rows,
        explicit_critical_supplier_ids=critical_supplier_ids,
    )
    material_suppliers_by_material = build_material_suppliers(supplier_materials)
    edge_material_pairs, edge_monthly_active_counts, edge_activity_sources = (
        build_supplier_demand_edge_context(
            supplier_ids,
            outgoing_edges,
            supplier_materials,
            children_by_material,
            monthly_planned_demand_by_material,
            monthly_planned_production_by_material,
        )
    )
    material_shocks = build_event_driven_material_shocks(
        source_tables,
        supplier_materials,
        materials_by_id,
        children_by_material,
        month_index_by_key,
    )
    forced_zero_demand_lookup = build_forced_zero_demand_lookup(scenario_tuning)
    material_monthly_rows, recovery_rows, material_lookup, supplier_supply_rows = (
        simulate_material_monthly_state(
        material_ids,
        materials_by_id,
        children_by_material,
        parents_by_material,
        initial_inventory_by_material,
        monthly_planned_production_by_material,
        monthly_output_efficiency_by_material,
        monthly_planned_demand_by_material,
        month_labels,
        material_shocks,
        supplier_mode=supplier_mode,
        node_scope=node_scope,
        allow_recovery_actions=allow_recovery_actions,
        supplier_ids=supplier_ids,
        suppliers_by_id=suppliers_by_id,
        supplier_materials=supplier_materials,
        critical_suppliers=critical_suppliers,
        supplier_critical_flag_source=supplier_critical_flag_source,
        material_suppliers_by_material=material_suppliers_by_material,
    )
    )
    if supplier_mode == "demand":
        supplier_supply_rows = []
        demand_edge_rows, supplier_demand_rows, demand_seed_rows = build_supplier_demand_monthly_state(
            supplier_ids,
            suppliers_by_id,
            outgoing_edges,
            critical_suppliers,
            edge_material_pairs,
            edge_monthly_active_counts,
            edge_activity_sources,
            month_labels,
            node_scope=node_scope,
            supplier_critical_flag_source=supplier_critical_flag_source,
            forced_zero_demand_lookup=forced_zero_demand_lookup,
        )
    else:
        demand_edge_rows = []
        supplier_demand_rows = []
        demand_seed_rows = []
    seed_rows = build_seed_summary(material_shocks, demand_seed_rows, month_labels)

    return {
        "material_monthly_state": material_monthly_rows,
        "supplier_monthly_supply_state": supplier_supply_rows,
        "supplier_demand_edge_monthly_state": demand_edge_rows,
        "supplier_monthly_demand_state": supplier_demand_rows,
        "recovery_actions": recovery_rows,
        "scenario_seed_summary": seed_rows,
        "metadata": {
            "total_months": TOTAL_MONTHS,
            "history_months": HISTORY_MONTHS,
            "forecast_months": TOTAL_MONTHS - HISTORY_MONTHS,
            "interruption_duration": INTERRUPTION_DURATION,
            "allow_recovery_actions": allow_recovery_actions,
            "supplier_mode": supplier_mode,
            "node_scope": node_scope,
            "critical_supplier_flag_source": supplier_critical_flag_source,
            "month_labels": month_labels,
            "history_month_labels": month_labels[:HISTORY_MONTHS],
            "forecast_month_labels": month_labels[HISTORY_MONTHS:],
        },
    }


def export_monthly_dataset(payload: dict, output_root: Path, output_run: str) -> dict:
    material_monthly_rows = payload["material_monthly_state"]
    supplier_supply_rows = payload["supplier_monthly_supply_state"]
    demand_edge_rows = payload["supplier_demand_edge_monthly_state"]
    supplier_demand_rows = payload["supplier_monthly_demand_state"]
    recovery_rows = payload["recovery_actions"]
    seed_rows = payload["scenario_seed_summary"]
    month_labels = payload["metadata"]["month_labels"]

    dump_json(output_root / "material_monthly_state.json", material_monthly_rows)
    dump_csv(output_root / "material_monthly_state.csv", material_monthly_rows)
    dump_json(output_root / "supplier_monthly_supply_state.json", supplier_supply_rows)
    dump_csv(output_root / "supplier_monthly_supply_state.csv", supplier_supply_rows)
    dump_json(output_root / "supplier_demand_edge_monthly_state.json", demand_edge_rows)
    dump_csv(output_root / "supplier_demand_edge_monthly_state.csv", demand_edge_rows)
    dump_json(output_root / "supplier_monthly_demand_state.json", supplier_demand_rows)
    dump_csv(output_root / "supplier_monthly_demand_state.csv", supplier_demand_rows)
    dump_json(output_root / "recovery_actions.json", recovery_rows)
    dump_csv(output_root / "recovery_actions.csv", recovery_rows)
    dump_json(output_root / "scenario_seed_summary.json", seed_rows)
    dump_csv(output_root / "scenario_seed_summary.csv", seed_rows)
    (output_root / "README.md").write_text(
        build_summary_markdown(
            output_run,
            material_monthly_rows,
            supplier_supply_rows,
            demand_edge_rows,
            supplier_demand_rows,
            recovery_rows,
            seed_rows,
            month_labels,
            payload["metadata"]["supplier_mode"],
            payload["metadata"]["node_scope"],
        ),
        encoding="utf-8",
    )

    return {
        "output_root": str(output_root),
        "tables": {
            "material_monthly_state": len(material_monthly_rows),
            "supplier_monthly_supply_state": len(supplier_supply_rows),
            "supplier_demand_edge_monthly_state": len(demand_edge_rows),
            "supplier_monthly_demand_state": len(supplier_demand_rows),
            "recovery_actions": len(recovery_rows),
            "scenario_seed_summary": len(seed_rows),
        },
    }


def generate_monthly_sample(source_run: str, output_run: str) -> dict:
    source_tables = load_source_tables(source_run)
    tuning_path = Path(__file__).resolve().parent / "scenario_tuning.json"
    scenario_tuning = load_json(tuning_path) if tuning_path.exists() else {}
    if scenario_tuning:
        from xd_supply_chain.studies.study_04_response_recovery.io import _apply_demo_augmentations

        source_tables = _apply_demo_augmentations(source_tables, scenario_tuning)
    default_scenario_key = scenario_tuning.get("default_scenario_key", "critical_supply")
    default_parts = default_scenario_key.split("_", maxsplit=1)
    default_node_scope = default_parts[0] if default_parts else "critical"
    default_supplier_mode = default_parts[1] if len(default_parts) > 1 else "supply"
    payload = build_monthly_dataset_payload(
        source_tables=source_tables,
        allow_recovery_actions=True,
        supplier_mode=default_supplier_mode,
        node_scope=default_node_scope,
        critical_supplier_ids=set(scenario_tuning.get("critical_supplier_ids", [])),
        critical_material_ids=set(scenario_tuning.get("critical_material_ids", [])),
        scenario_tuning=scenario_tuning,
    )
    output_root = PROJECT_ROOT / "workspace" / "runs" / output_run
    return export_monthly_dataset(payload, output_root, output_run)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a 12-month interruption development sample dataset.",
    )
    parser.add_argument(
        "--source-run",
        default=DEFAULT_SOURCE_RUN,
        help="study_00_data run id used as the source static dataset.",
    )
    parser.add_argument(
        "--output-run",
        default=DEFAULT_OUTPUT_RUN,
        help="workspace run id for the generated monthly sample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate_monthly_sample(args.source_run, args.output_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

