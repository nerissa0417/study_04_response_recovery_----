from __future__ import annotations

from supply_disruption_sim.config import load_yaml_config


VIS_CONFIG = load_yaml_config("visualization.yaml")


def node_color_for_visual_status(status: str) -> str:
    return VIS_CONFIG["node_palette"].get(status, "#7F8C8D")


def node_shape_for_type(node_type: str) -> str:
    return VIS_CONFIG["node_shape"].get(node_type, "o")


def edge_color_for_status(status: str) -> str:
    return VIS_CONFIG["edge_palette"].get(status, "#BFC9CA")


def edge_style_for_status(status: str) -> str:
    return {
        "active": "solid",
        "backup_active": "solid",
        "standby": "dashed",
        "substituted": "dashdot",
        "disrupted": "dotted",
    }.get(status, "solid")


def edge_width_for_status(status: str) -> float:
    return {
        "active": 1.1,
        "backup_active": 2.3,
        "substituted": 2.0,
        "standby": 1.7,
        "disrupted": 2.0,
    }.get(status, 1.0)
