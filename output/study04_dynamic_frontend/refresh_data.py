from __future__ import annotations

import csv
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from supply_disruption_sim.viz.dynamic_dashboard_export import (
    build_dashboard_payload,
    build_interactive_network_payload,
    build_scene_payload_from_frontend_dir,
    write_dashboard_contract_json,
    write_dashboard_data_js,
)
from supply_disruption_sim.disruption.recovery_engine import run_simulation
from supply_disruption_sim.disruption.scenario_loader import load_default_params
from supply_disruption_sim.experiment.interactive_runner import load_interactive_context
from supply_disruption_sim.experiment.runner import build_policy_set


SCENE_CONFIG = {
    "random": {
        "folder": "run_random_distributed",
        "label": "随机中断",
        "accent": "#0F766E",
        "accent_soft": "#DCFCE7",
    },
    "keynode": {
        "folder": "run_keynode_distributed",
        "label": "关键节点中断",
        "accent": "#B91C1C",
        "accent_soft": "#FEE2E2",
    },
}

OUTPUT_ROOT = REPO_ROOT / "output"
DASHBOARD_ROOT = Path(__file__).resolve().parent
DATA_FILE = DASHBOARD_ROOT / "data" / "dashboard-data.js"
CONTRACT_FILE = DASHBOARD_ROOT / "data" / "contract.json"
NAME_SOURCE_FILES = (
    REPO_ROOT / "Input_data" / "Supplier_Summary_Table.csv",
    REPO_ROOT / "Input_data" / "Material_Summary_Table.csv",
    REPO_ROOT / "Input_data" / "keynodes" / "monthly_v2_supplier_rankings_by_month.csv",
    REPO_ROOT / "Input_data" / "keynodes" / "monthly_v2_bom_rankings_by_month.csv",
)


def _load_entity_name_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for path in NAME_SOURCE_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                entity_id = str(
                    row.get("Supplier_ID")
                    or row.get("Material_ID")
                    or row.get("node_id")
                    or ""
                ).strip()
                entity_name = str(
                    row.get("Supplier_Name")
                    or row.get("Material_Name")
                    or row.get("node_name")
                    or ""
                ).strip()
                if not entity_id or not entity_name or entity_name in {"...", "…"}:
                    continue
                lookup.setdefault(entity_id, entity_name)
    return lookup


def _load_supplier_geo_nodes() -> list[dict]:
    path = REPO_ROOT / "Input_data" / "Supplier_Summary_Table.csv"
    nodes: list[dict] = []
    if not path.exists():
        return nodes
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            supplier_id = str(row.get("Supplier_ID") or "").strip()
            supplier_name = str(row.get("Supplier_Name") or "").strip()
            latitude = _to_float(row.get("Latitude"))
            longitude = _to_float(row.get("Longitude"))
            if not supplier_id or not supplier_name or latitude is None or longitude is None:
                continue
            nodes.append(
                {
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "is_key_node": _to_bool(row.get("Is_Chain_Owner_Supplier")),
                }
            )
    return nodes


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _apply_entity_names_to_payload(payload: dict, lookup: dict[str, str]) -> None:
    payload["entity_name_lookup"] = lookup
    scenes = payload.get("scenes") or {}
    for scene in scenes.values():
        network = scene.get("interactive_network") or {}
        for node in network.get("nodes") or []:
            entity_id = str(node.get("entity_id") or "").strip()
            entity_name = lookup.get(entity_id)
            if not entity_name:
                continue
            prefix = "关键 " if node.get("is_key_node") else ""
            node["label"] = f"{prefix}{entity_name}"
            node["short_label"] = entity_name


def _normalize_scene_payload(scene_key: str, scene_payload: dict) -> dict:
    scenario = scene_payload.get("scenario") or {}
    scenario_type = str(scenario.get("scenario_type") or "")
    if scene_key == "random" or scenario_type == "random_distributed_node_disruption":
        scenario["scenario_type_name"] = "随机中断"
    elif scene_key == "keynode" or scenario_type == "keynode_distributed_disruption":
        scenario["scenario_type_name"] = "关键节点中断"
    scene_payload["scenario"] = scenario
    return scene_payload


def main() -> None:
    context = load_interactive_context(REPO_ROOT / "Input_data")
    model = context["model"]
    reference_scenarios = context["reference_scenarios"]
    scenes = {
        scene_key: _normalize_scene_payload(
            scene_key,
            build_scene_payload_from_frontend_dir(
                scene_key=scene_key,
                label=config["label"],
                accent=config["accent"],
                accent_soft=config["accent_soft"],
                frontend_dir=OUTPUT_ROOT / config["folder"] / "tables" / "frontend",
                page_dir=DASHBOARD_ROOT,
                repo_root=REPO_ROOT,
                scene_family=scene_key,
            ),
        )
        for scene_key, config in SCENE_CONFIG.items()
    }
    params = load_default_params(model)
    policies = build_policy_set(policy_profile="time_priority_interrupt")
    for scene_key, scenario in reference_scenarios.items():
        result = run_simulation(model=model, scenario=scenario, policies=policies, params=params)
        scenes[scene_key]["interactive_network"] = build_interactive_network_payload(result)
    payload = build_dashboard_payload(
        scenes=scenes,
        meta={
            "page_mode": "main",
        },
    )
    _apply_entity_names_to_payload(payload, _load_entity_name_lookup())
    payload["supplier_geo_nodes"] = _load_supplier_geo_nodes()
    write_dashboard_data_js(payload, DATA_FILE)
    write_dashboard_contract_json(CONTRACT_FILE)
    print(f"wrote {DATA_FILE}")
    print(f"wrote {CONTRACT_FILE}")


if __name__ == "__main__":
    main()
