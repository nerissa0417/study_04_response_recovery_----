from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from xd_supply_chain.core.utils import load_json, resolve_path


REQUIRED_TABLE_NAMES = (
    "Material_Summary_Table",
    "Supplier_Summary_Table",
    "Order_Table",
    "Material_BOM",
    "Supplier_Network",
    "Equivalent_Material_Table",
)
LOCAL_TUNING_PATH = Path(__file__).resolve().parent / "scenario_tuning.json"


def _parse_month_date(raw_value: str) -> date | None:
    if not raw_value:
        return None
    cleaned = str(raw_value).strip().replace("-", "/")
    parts = cleaned.split("/")
    if len(parts) < 2:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def _collect_order_months(order_rows: list[dict]) -> list[date]:
    months: set[date] = set()
    for row in order_rows:
        for field in ("Order_Create_Date", "Promised_Delivery_Date", "Order_Delivery_Date"):
            parsed = _parse_month_date(str(row.get(field, "")))
            if parsed:
                months.add(parsed)
    return sorted(months)


def _next_sequence(rows: list[dict], field_name: str, prefix: str) -> int:
    max_value = 0
    for row in rows:
        raw_value = str(row.get(field_name, ""))
        if raw_value.startswith(prefix):
            suffix = raw_value[len(prefix) :]
            if suffix.isdigit():
                max_value = max(max_value, int(suffix))
    return max_value + 1


def _material_order_baselines(order_rows: list[dict]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for row in order_rows:
        material_id = row["Material_ID"]
        bucket = totals.setdefault(
            material_id,
            {
                "purchase_qty": 0.0,
                "capacity_qty": 0.0,
                "incoming_qty": 0.0,
                "unit_price": 0.0,
            },
        )
        bucket["purchase_qty"] += float(row.get("Purchase_Quantity", 0) or 0)
        bucket["capacity_qty"] += float(row.get("Theoretical_Capacity", 0) or 0)
        bucket["incoming_qty"] += float(row.get("Incoming_Total_Qty", 0) or 0)
        bucket["unit_price"] += float(row.get("Material_Unit_Price", 0) or 0)
        counts[material_id] = counts.get(material_id, 0) + 1

    baselines: dict[str, dict[str, float]] = {}
    for material_id, bucket in totals.items():
        count = max(counts.get(material_id, 1), 1)
        baselines[material_id] = {
            "purchase_qty": bucket["purchase_qty"] / count or 900.0,
            "capacity_qty": bucket["capacity_qty"] / count or 1100.0,
            "incoming_qty": bucket["incoming_qty"] / count or 820.0,
            "unit_price": bucket["unit_price"] / count or 220.0,
        }
    return baselines


def _format_month_date(month_date: date, day: int) -> str:
    return f"{month_date.year:04d}/{month_date.month:02d}/{day:02d}"


def _build_demo_orders(source_tables: dict[str, list[dict]], tuning: dict) -> list[dict]:
    clusters = tuning.get("demo_multi_material_suppliers", [])
    if not clusters:
        return []

    order_rows = source_tables.get("Order_Table", [])
    months = _collect_order_months(order_rows)
    if not months:
        return []

    material_baselines = _material_order_baselines(order_rows)
    existing_pairs = {(row["Supplier_ID"], row["Material_ID"]) for row in order_rows}
    next_order_id = _next_sequence(order_rows, "Order_ID", "OID")
    generated_rows: list[dict] = []

    for cluster_index, cluster in enumerate(clusters, start=1):
        supplier_id = cluster["supplier_id"]
        quantity_scale = float(cluster.get("quantity_scale", 1.0))
        reinforce_existing_pairs = bool(cluster.get("reinforce_existing_pairs", False))
        for material_offset, material_id in enumerate(cluster.get("material_ids", []), start=1):
            if (supplier_id, material_id) in existing_pairs and not reinforce_existing_pairs:
                continue
            baseline = material_baselines.get(
                material_id,
                {
                    "purchase_qty": 900.0,
                    "capacity_qty": 1100.0,
                    "incoming_qty": 820.0,
                    "unit_price": 220.0,
                },
            )
            for month_offset, month_date in enumerate(months, start=1):
                seasonal_factor = 0.92 + 0.04 * ((cluster_index + material_offset + month_offset) % 4)
                purchase_qty = int(round(baseline["purchase_qty"] * quantity_scale * seasonal_factor))
                capacity_qty = int(round(max(purchase_qty, baseline["capacity_qty"] * quantity_scale * 1.05)))
                incoming_qty = int(round(purchase_qty * 0.93))
                defective_qty = int(round(incoming_qty * 0.03))
                generated_rows.append(
                    {
                        "Supplier_ID": supplier_id,
                        "Material_ID": material_id,
                        "Order_ID": f"OID{next_order_id:04d}",
                        "Theoretical_Capacity": capacity_qty,
                        "Purchase_Quantity": purchase_qty,
                        "Material_Unit_Price": round(
                            baseline["unit_price"] * (0.96 + 0.01 * ((month_offset + material_offset) % 5)),
                            2,
                        ),
                        "Order_Create_Date": _format_month_date(month_date, 3),
                        "Promised_Delivery_Date": _format_month_date(month_date, 14),
                        "Order_Delivery_Date": _format_month_date(month_date, 21),
                        "Defective_Quantity": defective_qty,
                        "Incoming_Total_Qty": incoming_qty,
                        "Is_Qualified_Supplier": 1,
                        "Is_Returned": 0,
                        "Is_Delayed": 0,
                        "Delayed_Delivery_Cost": 0,
                    }
                )
                next_order_id += 1
    return generated_rows


def _build_demo_supplier_links(source_tables: dict[str, list[dict]], tuning: dict) -> list[dict]:
    link_rows = tuning.get("demo_supplier_network_links", [])
    if not link_rows:
        return []

    supplier_network_rows = source_tables.get("Supplier_Network", [])
    existing_links = {
        (row["Supplier_ID"], row["Supplier_down_ID"])
        for row in supplier_network_rows
    }
    next_link_id = _next_sequence(supplier_network_rows, "Supplier_Network_ID", "SNID")
    generated_rows: list[dict] = []
    for row in link_rows:
        source_supplier_id = row["source_supplier_id"]
        downstream_supplier_id = row["downstream_supplier_id"]
        if (source_supplier_id, downstream_supplier_id) in existing_links:
            continue
        generated_rows.append(
            {
                "Supplier_ID": source_supplier_id,
                "Supplier_down_ID": downstream_supplier_id,
                "Supplier_Network_ID": f"SNID{next_link_id:04d}",
            }
        )
        next_link_id += 1
    return generated_rows


def _build_demo_supplier_incidents(
    source_tables: dict[str, list[dict]],
    tuning: dict,
) -> tuple[list[dict], list[dict]]:
    incident_plans = tuning.get("demo_supplier_incidents", [])
    if not incident_plans:
        return [], []

    incident_rows = source_tables.get("emergency_incident", [])
    supplier_incident_rows = source_tables.get("Supplier_Emergency_Incident_Table", [])
    incidents_by_id = {
        row["Emergency_Incident_ID"]: row
        for row in incident_rows
    }
    existing_signatures = {
        (
            row["Supplier_ID"],
            incidents_by_id.get(row["Emergency_Incident_ID"], {}).get("Event_Type", ""),
            _parse_month_date(
                str(
                    incidents_by_id.get(row["Emergency_Incident_ID"], {}).get(
                        "Time_of_the_Incident",
                        "",
                    )
                )
            ),
        )
        for row in supplier_incident_rows
    }
    next_incident_id = _next_sequence(incident_rows, "Emergency_Incident_ID", "EIID")
    next_link_id = _next_sequence(
        supplier_incident_rows,
        "Supplier_Emergency_Incident_ID",
        "SEIID",
    )
    generated_incidents: list[dict] = []
    generated_links: list[dict] = []

    for plan in incident_plans:
        supplier_id = plan["supplier_id"]
        month_date = _parse_month_date(str(plan["month"]))
        event_type = plan["event_type"]
        if month_date is None:
            continue
        signature = (supplier_id, event_type, month_date)
        if signature in existing_signatures:
            continue

        incident_id = f"EIID{next_incident_id:04d}"
        generated_incidents.append(
            {
                "Emergency_Incident_ID": incident_id,
                "Event_Type": event_type,
                "Time_of_the_Incident": _format_month_date(month_date, 5),
                "First_Response_Time": _format_month_date(month_date, 7),
            }
        )
        generated_links.append(
            {
                "Supplier_Emergency_Incident_ID": f"SEIID{next_link_id:04d}",
                "Supplier_ID": supplier_id,
                "Emergency_Incident_ID": incident_id,
            }
        )
        existing_signatures.add(signature)
        next_incident_id += 1
        next_link_id += 1

    return generated_incidents, generated_links


def _apply_demo_augmentations(
    source_tables: dict[str, list[dict]],
    tuning: dict,
) -> dict[str, list[dict]]:
    demo_orders = _build_demo_orders(source_tables, tuning)
    demo_supplier_links = _build_demo_supplier_links(source_tables, tuning)
    demo_incidents, demo_supplier_incidents = _build_demo_supplier_incidents(source_tables, tuning)
    if not demo_orders and not demo_supplier_links and not demo_incidents and not demo_supplier_incidents:
        return source_tables

    augmented_tables = {table_name: deepcopy(rows) for table_name, rows in source_tables.items()}
    if demo_orders:
        augmented_tables.setdefault("Order_Table", []).extend(demo_orders)
    if demo_supplier_links:
        augmented_tables.setdefault("Supplier_Network", []).extend(demo_supplier_links)
    if demo_incidents:
        augmented_tables.setdefault("emergency_incident", []).extend(demo_incidents)
    if demo_supplier_incidents:
        augmented_tables.setdefault("Supplier_Emergency_Incident_Table", []).extend(
            demo_supplier_incidents
        )
    return augmented_tables


def _load_json_robust(path: Path) -> list[dict]:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ResponseRecoveryInputAdapter:
    def load(self, request) -> dict:
        config = request.config
        tuning = self._load_local_tuning()
        scenarios = []
        scenarios_path = config.get("scenarios_path")
        if scenarios_path:
            scenarios = load_json(resolve_path(request.project_root, scenarios_path))

        source_tables = self._apply_source_table_tuning(self._load_source_tables(request), tuning)
        node_scopes = tuning.get("node_scopes", config.get("node_scopes", ["general", "critical"]))
        supplier_modes = tuning.get("supplier_modes", config.get("supplier_modes", ["supply", "demand"]))
        critical_material_ids = list(
            tuning.get("critical_material_ids", config.get("critical_material_ids", []))
        )
        critical_supplier_ids = list(
            tuning.get("critical_supplier_ids", config.get("critical_supplier_ids", []))
        )
        return {
            "scenarios": scenarios,
            "response_target_hours": config.get("response_target_hours", 12),
            "source_tables": source_tables,
            "node_scopes": node_scopes,
            "supplier_modes": supplier_modes,
            "critical_material_ids": critical_material_ids,
            "critical_supplier_ids": critical_supplier_ids,
            "default_scenario_key": tuning.get(
                "default_scenario_key",
                config.get("default_scenario_key", "critical_supply"),
            ),
            "scenario_tuning": tuning,
            "run_id": request.run_id,
            "project_root": str(request.project_root),
            "workspace_root": str(request.workspace_root),
            "study_root": str(request.workspace_root / "runs" / request.run_id / request.metadata.key),
            "monthly_output_dirname": config.get("monthly_output_dirname", "monthly_tables"),
        }

    def _load_local_tuning(self) -> dict:
        if not LOCAL_TUNING_PATH.exists():
            return {}
        return _load_json_robust(LOCAL_TUNING_PATH)

    def _load_source_tables(self, request) -> dict[str, list[dict]]:
        local_tables = self._load_local_study_tables()
        if local_tables:
            return local_tables

        study00_payload = request.dependency_payloads.get("study_00_data")
        if study00_payload and "table_exports" in study00_payload:
            return {
                table_name: load_json(
                    resolve_path(
                        request.project_root,
                        export_info["json_path"],
                    )
                )
                for table_name, export_info in study00_payload["table_exports"].items()
            }

        source_run = request.config.get("source_run_id", "study00_manual_run")
        tables_root = (
            Path(request.project_root)
            / "workspace"
            / "runs"
            / source_run
            / "study_00_data"
            / "tables"
        )
        return {
            table_name: load_json(tables_root / f"{table_name}.json")
            for table_name in REQUIRED_TABLE_NAMES
        }

    def _load_local_study_tables(self) -> dict[str, list[dict]]:
        tables_root = Path(__file__).resolve().parent / "tables"
        if not tables_root.exists():
            return {}

        available_table_names = {path.stem for path in tables_root.glob("*.json")}
        if not set(REQUIRED_TABLE_NAMES).issubset(available_table_names):
            return {}

        return {
            path.stem: _load_json_robust(path)
            for path in sorted(tables_root.glob("*.json"))
        }

    def _apply_source_table_tuning(
        self,
        source_tables: dict[str, list[dict]],
        tuning: dict,
    ) -> dict[str, list[dict]]:
        return _apply_demo_augmentations(source_tables, tuning)
