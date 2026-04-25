from __future__ import annotations

import re


SCENARIO_ID_ALIASES = {
    "default_multi_supplier_disruption": "default_keynode_distributed_disruption",
}

SCENARIO_TYPE_ALIASES = {
    "multi_supplier_disruption": "keynode_distributed_disruption",
}

SCENARIO_ID_LABELS = {
    "default_random_distributed_node_disruption": "随机中断情境",
    "default_keynode_distributed_disruption": "关键节点中断情境",
}

SCENARIO_TYPE_LABELS = {
    "random_distributed_node_disruption": "随机节点中断",
    "keynode_distributed_disruption": "关键节点中断",
}

POLICY_PROFILE_LABELS = {
    "time_priority_interrupt": "当前恢复策略",
    "baseline": "默认联动恢复",
    "all_policies": "全策略显示联动",
    "no_policy": "无恢复策略",
    "only_backup_switch": "仅备供切换",
    "only_substitution": "仅等效替代",
    "only_priority_repair": "仅优先抢修",
    "no_priority_repair": "去除优先抢修",
    "no_backup_switch": "去除备供切换",
    "no_substitution": "去除等效替代",
}

POLICY_TYPE_LABELS = {
    "backup_supplier_switch": "备供切换",
    "equivalent_material_substitution": "等效替代",
    "priority_repair": "优先抢修",
}

PARAMETER_LABELS = {
    "single_source_ratio": "单一来源占比",
    "backup_coverage": "备份覆盖率",
    "substitution_availability": "替代可得性",
    "backup_switch_time_days": "备供切换时滞",
    "priority_repair_lead_days": "优先抢修提前天数",
    "incident_duration_factor": "中断持续时间系数",
}

PARAMETER_DIMENSION_LABELS = {
    "single_source_ratio": "节点能力",
    "backup_coverage": "节点能力",
    "substitution_availability": "节点能力",
    "backup_switch_time_days": "协同平台支撑能力",
    "priority_repair_lead_days": "协同平台支撑能力",
    "incident_duration_factor": "场景扰动强度",
}

TOKEN_LABELS = {
    "time": "时间",
    "default": "默认",
    "random": "随机",
    "distributed": "分散",
    "node": "节点",
    "nodes": "节点",
    "disruption": "中断",
    "keynode": "关键节点",
    "key": "关键",
    "critical": "关键",
    "supplier": "供应商",
    "suppliers": "供应商",
    "multi": "多",
    "policy": "策略",
    "policies": "策略",
    "baseline": "当前",
    "all": "全",
    "only": "仅",
    "no": "无",
    "backup": "备用",
    "switch": "切换",
    "substitution": "等效替代",
    "priority": "优先",
    "repair": "抢修",
    "scenario": "情境",
    "profile": "方案",
}


def canonical_scenario_id(value: str) -> str:
    normalized = str(value or "").strip()
    return SCENARIO_ID_ALIASES.get(normalized, normalized)


def canonical_scenario_type(value: str) -> str:
    normalized = str(value or "").strip()
    return SCENARIO_TYPE_ALIASES.get(normalized, normalized)


def scenario_label(value: str) -> str:
    canonical = canonical_scenario_id(value)
    return SCENARIO_ID_LABELS.get(canonical, _humanize_identifier(canonical, fallback="未命名场景"))


def scenario_type_label(value: str) -> str:
    canonical = canonical_scenario_type(value)
    return SCENARIO_TYPE_LABELS.get(canonical, _humanize_identifier(canonical, fallback="未命名情境类型"))


def policy_profile_label(value: str) -> str:
    normalized = str(value or "").strip()
    return POLICY_PROFILE_LABELS.get(normalized, _humanize_identifier(normalized, fallback="未命名策略"))


def policy_type_label(value: str) -> str:
    normalized = str(value or "").strip()
    return POLICY_TYPE_LABELS.get(normalized, _humanize_identifier(normalized, fallback="未命名策略类型"))


def parameter_label(value: str) -> str:
    normalized = str(value or "").strip()
    return PARAMETER_LABELS.get(normalized, _humanize_identifier(normalized, fallback="未命名参数"))


def parameter_dimension_label(value: str) -> str:
    normalized = str(value or "").strip()
    return PARAMETER_DIMENSION_LABELS.get(normalized, _humanize_identifier(normalized, fallback="未命名能力维度"))


def scenario_policy_run_label(scenario_id: str, policy_profile: str) -> str:
    return f"{scenario_label(scenario_id)} | {policy_profile_label(policy_profile)}"


def _humanize_identifier(value: str, *, fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return fallback
    tokens = [token for token in re.split(r"[_\\-]+", normalized) if token]
    if not tokens:
        return fallback
    translated: list[str] = []
    for token in tokens:
        if token in TOKEN_LABELS:
            translated.append(TOKEN_LABELS[token])
            continue
        if token.isdigit():
            translated.append(token)
            continue
        translated.append(token.upper())
    rendered = "".join(translated).strip()
    return rendered or fallback
