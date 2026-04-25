from __future__ import annotations

import csv
import json
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from supply_disruption_sim.experiment.interactive_runner import (
    build_custom_node_scenario,
    load_interactive_context,
    run_custom_node_experiment,
)
from supply_disruption_sim.viz.dynamic_dashboard_export import (
    build_dashboard_contract,
    build_dashboard_payload,
    build_interactive_network_payload,
    build_scene_payload_from_frontend_dir,
    build_selector_graph,
)


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

WHATIF_SCENE_STYLE = {
    "accent": "#7C3AED",
    "accent_soft": "#F3E8FF",
}

HOST = "127.0.0.1"
PORT = 8765
DASHBOARD_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = REPO_ROOT / "output"
GENERATED_ROOT = DASHBOARD_ROOT / "generated"
NAME_SOURCE_FILES = (
    REPO_ROOT / "Input_data" / "Supplier_Summary_Table.csv",
    REPO_ROOT / "Input_data" / "Material_Summary_Table.csv",
    REPO_ROOT / "Input_data" / "keynodes" / "monthly_v2_supplier_rankings_by_month.csv",
    REPO_ROOT / "Input_data" / "keynodes" / "monthly_v2_bom_rankings_by_month.csv",
)


def _normalize_scene_payload(scene_family: str, scene_payload: dict) -> dict:
    scenario = scene_payload.get("scenario") or {}
    scenario_type = str(scenario.get("scenario_type") or "")
    if scene_family == "random" or scenario_type == "random_distributed_node_disruption":
        scenario["scenario_type_name"] = "随机中断"
    elif scene_family == "keynode" or scenario_type == "keynode_distributed_disruption":
        scenario["scenario_type_name"] = "关键节点中断"
    scene_payload["scenario"] = scenario
    return scene_payload


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


def _apply_entity_names_to_network(network: dict, lookup: dict[str, str]) -> None:
    for node in network.get("nodes") or []:
        entity_id = str(node.get("entity_id") or "").strip()
        entity_name = lookup.get(entity_id)
        if not entity_name:
            continue
        prefix = "关键 " if node.get("is_key_node") else ""
        node["label"] = f"{prefix}{entity_name}"
        node["short_label"] = entity_name


def _apply_entity_names_to_payload(payload: dict, lookup: dict[str, str]) -> None:
    payload["entity_name_lookup"] = lookup
    for scene in (payload.get("scenes") or {}).values():
        _apply_entity_names_to_network(scene.get("interactive_network") or {}, lookup)


class InteractiveRuntime:
    def __init__(self) -> None:
        self.context = load_interactive_context(REPO_ROOT / "Input_data")
        self.model = self.context["model"]
        self.reference_scenarios = self.context["reference_scenarios"]
        self.entity_name_lookup = _load_entity_name_lookup()
        self.selector_graph = build_selector_graph(self.model)
        _apply_entity_names_to_network(self.selector_graph, self.entity_name_lookup)
        self.node_map = {node["node_key"]: node for node in self.selector_graph["nodes"]}
        self.lock = threading.Lock()

    def health_payload(self) -> dict:
        return {
            "ok": True,
            "ready": True,
            "generated_root": str(GENERATED_ROOT),
            "node_count": len(self.selector_graph.get("nodes", [])),
            "contract_version": build_dashboard_contract()["contract_version"],
        }

    def contract_payload(self) -> dict:
        return {
            "ok": True,
            "contract": build_dashboard_contract(),
        }

    def run_whatif(self, *, scene_family: str, node_keys: list[str], policy_profile: str = "time_priority_interrupt") -> dict:
        family = scene_family.strip().lower()
        if family not in SCENE_CONFIG:
            known = ", ".join(sorted(SCENE_CONFIG))
            raise KeyError(f"Unknown scene family '{scene_family}'. Known families: {known}")
        clean_node_keys = [key for key in node_keys if key]
        if not clean_node_keys:
            raise KeyError("No node keys selected.")
        for node_key in clean_node_keys:
            if node_key not in self.node_map:
                raise KeyError(f"Unknown node key '{node_key}'.")

        node_metas = [self.node_map[node_key] for node_key in clean_node_keys]
        invalid_nodes = [meta for meta in node_metas if not _node_allowed_for_family(family, meta)]
        if invalid_nodes:
            raise ValueError(_selection_rule_text(family))
        node_label = "、".join(str(meta.get("short_label") or meta.get("entity_id")) for meta in node_metas)
        run_id = self._build_run_id(family, node_metas)
        page_dir = GENERATED_ROOT / run_id
        run_output_dir = page_dir / "run"

        with self.lock:
            scenario = build_custom_node_scenario(
                model=self.model,
                node_key=clean_node_keys,
                scene_family=family,
                reference_scenarios=self.reference_scenarios,
            )
            execution = run_custom_node_experiment(
                model=self.model,
                scenario=scenario,
                output_dir=run_output_dir,
                policy_profile=policy_profile,
                report_profile="minimal",
                params_overrides={"bayesian_use_sampling": False},
            )

            reference_scene = build_scene_payload_from_frontend_dir(
                scene_key="reference",
                label=f"{SCENE_CONFIG[family]['label']}（基准）",
                accent=SCENE_CONFIG[family]["accent"],
                accent_soft=SCENE_CONFIG[family]["accent_soft"],
                frontend_dir=OUTPUT_ROOT / SCENE_CONFIG[family]["folder"] / "tables" / "frontend",
                page_dir=DASHBOARD_ROOT,
                repo_root=REPO_ROOT,
                scene_family=family,
            )
            reference_scene = _normalize_scene_payload(family, reference_scene)
            whatif_scene = build_scene_payload_from_frontend_dir(
                scene_key="whatif",
                label=f"{node_label} 节点中断推演",
                accent=WHATIF_SCENE_STYLE["accent"],
                accent_soft=WHATIF_SCENE_STYLE["accent_soft"],
                frontend_dir=run_output_dir / "tables" / "frontend",
                page_dir=DASHBOARD_ROOT,
                repo_root=REPO_ROOT,
                scene_family=family,
            )
            whatif_scene = _normalize_scene_payload(family, whatif_scene)
            whatif_scene["interactive_network"] = build_interactive_network_payload(execution["result"])

            payload = build_dashboard_payload(
                scenes={
                    "reference": reference_scene,
                    "whatif": whatif_scene,
                },
                meta={
                    "page_mode": "generated",
                    "scene_family": family,
                    "policy_profile": policy_profile,
                    "run_id": run_id,
                    "trigger_node_keys": clean_node_keys,
                    "trigger_node_label": node_label,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            _apply_entity_names_to_payload(payload, self.entity_name_lookup)
        return {
            "ok": True,
            "run_id": run_id,
            "node_keys": clean_node_keys,
            "node_label": node_label,
            "output_dir": str(run_output_dir),
            "dashboard_payload": payload,
            "summary": execution["result"].summary,
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "scenario_type": scenario.scenario_type,
                "target_type": scenario.target_type,
                "target_id": scenario.target_id,
                "start_date": str(scenario.start_date.date()),
                "duration_days": scenario.duration_days,
                "severity": scenario.severity,
            },
        }

    def _build_run_id(self, family: str, node_metas: list[dict]) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        first = node_metas[0]
        node_type = str(first.get("node_type") or "node")
        entity_id = str(first.get("entity_id") or "node").replace("/", "_")
        suffix = entity_id if len(node_metas) == 1 else f"{entity_id}_{len(node_metas)}nodes"
        return f"{timestamp}_{family}_{node_type}_{suffix}"


def _node_allowed_for_family(family: str, node_meta: dict) -> bool:
    is_key_node = bool(node_meta.get("is_key_node"))
    if family == "random":
        return not is_key_node
    if family == "keynode":
        return is_key_node
    return True


def _selection_rule_text(family: str) -> str:
    if family == "random":
        return "随机中断情境只能选择非关键节点。"
    if family == "keynode":
        return "关键节点中断情境只能选择关键节点。"
    return "当前情境不支持所选节点。"


class DashboardHandler(SimpleHTTPRequestHandler):
    runtime: InteractiveRuntime | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_ROOT), **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers(content_type="application/json")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(self.runtime.health_payload())
            return
        if parsed.path == "/api/contract":
            self._send_json(self.runtime.contract_payload())
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/whatif-run":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            payload = json.loads(body or "{}")
            raw_node_keys = payload.get("node_keys")
            if isinstance(raw_node_keys, str):
                node_keys = [raw_node_keys]
            elif isinstance(raw_node_keys, list):
                node_keys = [str(item) for item in raw_node_keys if item]
            else:
                fallback_node_key = str(payload.get("node_key") or "")
                node_keys = [fallback_node_key] if fallback_node_key else []
            response = self.runtime.run_whatif(
                scene_family=str(payload.get("scene_family") or "random"),
                node_keys=node_keys,
                policy_profile=str(payload.get("policy_profile") or "time_priority_interrupt"),
            )
            self._send_json(response)
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                {
                    "ok": False,
                    "error": str(exc),
                },
                status=HTTPStatus.BAD_REQUEST,
            )

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers(content_type="application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self, *, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")


def main() -> None:
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    runtime = InteractiveRuntime()
    DashboardHandler.runtime = runtime
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Study04 dynamic frontend server ready at http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
