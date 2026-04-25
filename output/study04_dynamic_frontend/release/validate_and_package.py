from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from output.study04_dynamic_frontend.refresh_data import main as refresh_dashboard_data
from supply_disruption_sim.viz.dynamic_dashboard_export import build_dashboard_contract


DASHBOARD_ROOT = Path(__file__).resolve().parent
DATA_ROOT = DASHBOARD_ROOT / "data"
RELEASE_ROOT = DASHBOARD_ROOT / "release"
REQUIRED_FILES = [
    DASHBOARD_ROOT / "index.html",
    DASHBOARD_ROOT / "styles.css",
    DASHBOARD_ROOT / "app.js",
    DASHBOARD_ROOT / "serve.py",
    DATA_ROOT / "dashboard-data.js",
    DATA_ROOT / "contract.json",
]


def main() -> None:
    refresh_dashboard_data()
    validate_contract()
    package_release()
    print("study04-dynamic-frontend-package-ok")


def validate_contract() -> None:
    missing = [path for path in REQUIRED_FILES if not path.exists()]
    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(f"缺少以下前端交付文件：\n{missing_text}")

    contract = json.loads((DATA_ROOT / "contract.json").read_text(encoding="utf-8"))
    expected = build_dashboard_contract()
    if contract.get("contract_version") != expected.get("contract_version"):
        raise ValueError("contract.json 的契约版本与导出层不一致。")

    dashboard_text = (DATA_ROOT / "dashboard-data.js").read_text(encoding="utf-8")
    if "window.study04DynamicData" not in dashboard_text:
        raise ValueError("dashboard-data.js 不包含预期的全局数据对象。")


def package_release() -> None:
    if RELEASE_ROOT.exists():
        shutil.rmtree(RELEASE_ROOT)
    shutil.copytree(
        DASHBOARD_ROOT,
        RELEASE_ROOT,
        ignore=shutil.ignore_patterns("__pycache__", "generated", "release"),
    )
    archive_base = DASHBOARD_ROOT / "study04_dynamic_frontend_release"
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=RELEASE_ROOT)
    print(f"wrote {archive_path}")


if __name__ == "__main__":
    main()
