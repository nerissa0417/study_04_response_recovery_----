from __future__ import annotations

from typing import Any

import pandas as pd

from supply_disruption_sim.model.state_model import SimState


POLICY_TYPES = (
    "backup_supplier_switch",
    "equivalent_material_substitution",
    "priority_repair",
)


def record_policy_event(
    *,
    state: SimState,
    current_date: pd.Timestamp,
    policy_type: str,
    action: str,
    target_id: str,
    target_type: str,
    cost: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_date = pd.Timestamp(current_date).normalize()
    rounded_cost = round(float(cost), 4)
    event = {
        "date": normalized_date,
        "policy_type": policy_type,
        "action": action,
        "target_id": target_id,
        "target_type": target_type,
        "cost": rounded_cost,
    }
    if metadata:
        event.update(metadata)
    state.policy_event_log.append(event)

    daily_bucket = state.policy_cost_by_date.setdefault(normalized_date, {"policy_daily_cost": 0.0})
    daily_bucket["policy_daily_cost"] = round(float(daily_bucket.get("policy_daily_cost", 0.0)) + rounded_cost, 4)
    daily_key = f"{policy_type}_daily_cost"
    daily_bucket[daily_key] = round(float(daily_bucket.get(daily_key, 0.0)) + rounded_cost, 4)

    state.policy_cost_totals["policy_total_cost"] = round(
        float(state.policy_cost_totals.get("policy_total_cost", 0.0)) + rounded_cost,
        4,
    )
    total_key = f"{policy_type}_total_cost"
    state.policy_cost_totals[total_key] = round(
        float(state.policy_cost_totals.get(total_key, 0.0)) + rounded_cost,
        4,
    )


def build_policy_daily_metrics(current_date: pd.Timestamp, state: SimState) -> dict[str, float | int]:
    normalized_date = pd.Timestamp(current_date).normalize()
    daily_bucket = state.policy_cost_by_date.get(normalized_date, {})
    metrics: dict[str, float | int] = {
        "policy_daily_cost": round(float(daily_bucket.get("policy_daily_cost", 0.0)), 4),
        "policy_cumulative_cost": round(float(state.policy_cost_totals.get("policy_total_cost", 0.0)), 4),
        "policy_event_count": len(state.policy_event_log),
        "pending_backup_switches": len(state.backup_pending),
        "pending_substitutions": len(state.substitution_pending),
        "pending_priority_repairs": len(state.repair_pending_suppliers) + len(state.repair_pending_items),
        "active_priority_repairs": len(state.repair_active_suppliers) + len(state.repair_active_items),
    }
    for policy_type in POLICY_TYPES:
        metrics[f"{policy_type}_daily_cost"] = round(float(daily_bucket.get(f"{policy_type}_daily_cost", 0.0)), 4)
        metrics[f"{policy_type}_cumulative_cost"] = round(
            float(state.policy_cost_totals.get(f"{policy_type}_total_cost", 0.0)),
            4,
        )
    return metrics


def summarize_policy_events(policy_events: list[dict[str, Any]]) -> dict[str, float | int]:
    summary: dict[str, float | int] = {
        "policy_event_count": len(policy_events),
        "policy_total_cost": 0.0,
    }
    for policy_type in POLICY_TYPES:
        summary[f"{policy_type}_total_cost"] = 0.0
        summary[f"{policy_type}_scheduled_count"] = 0
        summary[f"{policy_type}_activated_count"] = 0

    for event in policy_events:
        policy_type = str(event.get("policy_type", ""))
        cost = round(float(event.get("cost", 0.0) or 0.0), 4)
        action = str(event.get("action", ""))
        summary["policy_total_cost"] = round(float(summary["policy_total_cost"]) + cost, 4)
        if policy_type in POLICY_TYPES:
            total_key = f"{policy_type}_total_cost"
            summary[total_key] = round(float(summary[total_key]) + cost, 4)
            if "schedule" in action or "pending" in action:
                summary[f"{policy_type}_scheduled_count"] = int(summary[f"{policy_type}_scheduled_count"]) + 1
            if "activate" in action:
                summary[f"{policy_type}_activated_count"] = int(summary[f"{policy_type}_activated_count"]) + 1

    summary["policy_total_cost"] = round(float(summary["policy_total_cost"]), 4)
    return summary
