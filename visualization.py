from __future__ import annotations

import json
from collections import defaultdict


TOTAL_MONTHS = 12
STATUS_PRIORITY = {"normal": 0, "affected": 1, "interrupted": 2}
STATUS_COLORS = {
    "normal": {"fill": "#78a9d1", "stroke": "#295f87"},
    "affected": {"fill": "#f2b366", "stroke": "#a96512"},
    "interrupted": {"fill": "#df5a49", "stroke": "#7e2015"},
}


def _entity_lookup(rows: list[dict], id_field: str) -> dict[int, dict[str, dict]]:
    lookup: dict[int, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        lookup[int(row["Month_Index"])][row[id_field]] = row
    return lookup


def _status_rank(status: str) -> int:
    return STATUS_PRIORITY.get(status, 0)


def _merge_status(*statuses: str) -> str:
    final_status = "normal"
    for status in statuses:
        if _status_rank(status) > _status_rank(final_status):
            final_status = status
    return final_status


def _display_status(status: str) -> str:
    if status == "interrupted":
        return "interrupted"
    if status == "affected":
        return "affected"
    return "normal"


def _build_supplier_metadata(source_tables: dict[str, list[dict]]) -> dict[str, dict]:
    supplier_region = {
        row["Supplier_ID"]: row["Region_ID"]
        for row in source_tables.get("Supplier_Region_Table", [])
    }
    regions_by_id = {
        row["Region_ID"]: row
        for row in source_tables.get("Region_Table", [])
    }
    incidents_by_id = {
        row["Emergency_Incident_ID"]: row
        for row in source_tables.get("emergency_incident", [])
    }
    supplier_incidents: dict[str, list[dict]] = defaultdict(list)
    for row in source_tables.get("Supplier_Emergency_Incident_Table", []):
        incident = incidents_by_id.get(row["Emergency_Incident_ID"])
        if incident:
            supplier_incidents[row["Supplier_ID"]].append(incident)

    final_products_by_supplier: dict[str, list[str]] = defaultdict(list)
    for row in source_tables.get("Supplier_Final_Product_Table", []):
        final_products_by_supplier[row["Supplier_ID"]].append(row["Final_Product_ID"])

    metadata: dict[str, dict] = {}
    for row in source_tables.get("Supplier_Summary_Table", []):
        supplier_id = row["Supplier_ID"]
        region_id = supplier_region.get(supplier_id, "")
        metadata[supplier_id] = {
            "Supplier_Name": row.get("Supplier_Name", supplier_id),
            "Region_ID": region_id,
            "Region_Summary": regions_by_id.get(region_id, {}),
            "Incident_Count": len(supplier_incidents.get(supplier_id, [])),
            "Incident_Types": sorted(
                {incident.get("Event_Type", "") for incident in supplier_incidents.get(supplier_id, [])}
            ),
            "Linked_Final_Product_IDs": sorted(final_products_by_supplier.get(supplier_id, [])),
        }
    return metadata


def _compute_tier_positions(
    entity_ids: list[str],
    edges: list[tuple[str, str]],
    x_start: float,
    x_end: float,
    y_start: float = 120,
    y_step: float = 80,
) -> dict[str, tuple[float, float]]:
    outgoing: dict[str, list[str]] = {entity_id: [] for entity_id in entity_ids}
    indegree: dict[str, int] = {entity_id: 0 for entity_id in entity_ids}

    for source_id, target_id in edges:
        if source_id not in outgoing or target_id not in indegree:
            continue
        outgoing[source_id].append(target_id)
        indegree[target_id] += 1

    queue = sorted([entity_id for entity_id, degree in indegree.items() if degree == 0])
    if not queue:
        queue = sorted(entity_ids)

    tiers: dict[str, int] = {entity_id: 0 for entity_id in queue}
    cursor = 0
    while cursor < len(queue):
        entity_id = queue[cursor]
        for target_id in outgoing.get(entity_id, []):
            tiers[target_id] = max(tiers.get(target_id, 0), tiers.get(entity_id, 0) + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                queue.append(target_id)
        cursor += 1

    for entity_id in entity_ids:
        tiers.setdefault(entity_id, 0)

    tier_groups: dict[int, list[str]] = defaultdict(list)
    for entity_id in sorted(entity_ids):
        tier_groups[tiers[entity_id]].append(entity_id)

    max_tier = max(tier_groups.keys(), default=0)
    tier_count = max_tier + 1
    if tier_count <= 1:
        x_positions = [round((x_start + x_end) / 2, 2)]
    else:
        step = (x_end - x_start) / max(tier_count - 1, 1)
        x_positions = [round(x_start + step * index, 2) for index in range(tier_count)]

    positions: dict[str, tuple[float, float]] = {}
    for tier_index in range(tier_count):
        group = tier_groups.get(tier_index, [])
        x_value = x_positions[tier_index]
        for row_index, entity_id in enumerate(group):
            positions[entity_id] = (x_value, y_start + row_index * y_step)
    return positions


def build_network_visualization_payload(
    source_tables: dict[str, list[dict]],
    baseline_payload: dict,
    strategy_payload: dict,
    monthly_recovery_comparison: list[dict],
) -> dict:
    month_labels = strategy_payload.get("metadata", {}).get(
        "month_labels",
        [f"2025-{month:02d}" for month in range(1, TOTAL_MONTHS + 1)],
    )
    supplier_rows = source_tables.get("Supplier_Summary_Table", [])
    material_rows = source_tables.get("Material_Summary_Table", [])
    order_rows = source_tables.get("Order_Table", [])
    supplier_network_rows = source_tables.get("Supplier_Network", [])
    bom_rows = source_tables.get("Material_BOM", [])

    supplier_ids = sorted({row["Supplier_ID"] for row in supplier_rows})
    material_ids = sorted({row["Material_ID"] for row in material_rows})
    material_by_id = {row["Material_ID"]: row for row in material_rows}
    supplier_by_id = {row["Supplier_ID"]: row for row in supplier_rows}
    supplier_meta = _build_supplier_metadata(source_tables)

    supplier_positions = _compute_tier_positions(
        entity_ids=supplier_ids,
        edges=[
            (row["Supplier_ID"], row["Supplier_down_ID"])
            for row in supplier_network_rows
            if row["Supplier_ID"] in supplier_by_id and row["Supplier_down_ID"] in supplier_by_id
        ],
        x_start=140,
        x_end=1020,
        y_start=120,
        y_step=80,
    )
    material_positions = _compute_tier_positions(
        entity_ids=material_ids,
        edges=[
            (row["Material_ID"], row["Downstream_Material_ID"])
            for row in bom_rows
            if row["Material_ID"] in material_by_id and row["Downstream_Material_ID"] in material_by_id
        ],
        x_start=1300,
        x_end=2020,
        y_start=120,
        y_step=80,
    )

    nodes = []
    for material_id in material_ids:
        row = material_by_id[material_id]
        x_value, y_value = material_positions.get(material_id, (1300, 120))
        nodes.append(
            {
                "id": f"material:{material_id}",
                "entity_id": material_id,
                "node_type": "material",
                "layer": "material",
                "label": row.get("Material_Name", material_id),
                "x": x_value,
                "y": y_value,
                "critical_flag": int(float(row.get("Is_Critical_Material", 0))),
                "meta": {
                    "Material_Name": row.get("Material_Name", material_id),
                    "Is_Critical_Material": int(float(row.get("Is_Critical_Material", 0))),
                    "Is_Final_Product": int(float(row.get("Is_Final_Product", 0))),
                    "Is_Equivalent_Material": int(float(row.get("Is_Equivalent_Material", 0))),
                    "Available_Inventory_Qty": row.get("Available_Inventory_Qty", 0),
                },
            }
        )
    for supplier_id in supplier_ids:
        meta = supplier_meta.get(supplier_id, {})
        x_value, y_value = supplier_positions.get(supplier_id, (140, 120))
        nodes.append(
            {
                "id": f"supplier:{supplier_id}",
                "entity_id": supplier_id,
                "node_type": "supplier",
                "layer": "supplier",
                "label": meta.get("Supplier_Name", supplier_id),
                "x": x_value,
                "y": y_value,
                "critical_flag": int(float(supplier_by_id[supplier_id].get("Is_Chain_Owner_Supplier", 0))),
                "meta": meta,
            }
        )

    edge_set: set[tuple[str, str, str]] = set()
    for row in supplier_network_rows:
        edge_set.add(
            (f"supplier:{row['Supplier_ID']}", f"supplier:{row['Supplier_down_ID']}", "supplier_network")
        )
    for row in order_rows:
        if row["Supplier_ID"] in supplier_by_id and row["Material_ID"] in material_by_id:
            edge_set.add(
                (f"supplier:{row['Supplier_ID']}", f"material:{row['Material_ID']}", "supply")
            )
    for row in bom_rows:
        if row["Material_ID"] in material_by_id and row["Downstream_Material_ID"] in material_by_id:
            edge_set.add(
                (f"material:{row['Material_ID']}", f"material:{row['Downstream_Material_ID']}", "bom")
            )

    edges = [
        {"source": source_id, "target": target_id, "edge_type": edge_type}
        for source_id, target_id, edge_type in sorted(edge_set)
    ]

    def build_month_states(payload: dict) -> dict[str, dict[str, dict]]:
        material_lookup = _entity_lookup(payload["material_monthly_state"], "Material_ID")
        supplier_supply_lookup = _entity_lookup(payload["supplier_monthly_supply_state"], "Supplier_ID")
        supplier_demand_lookup = _entity_lookup(payload["supplier_monthly_demand_state"], "Supplier_ID")

        month_states: dict[str, dict[str, dict]] = {}
        for month_index in range(1, TOTAL_MONTHS + 1):
            node_states: dict[str, dict] = {}
            for material_id in material_ids:
                row = material_lookup.get(month_index, {}).get(material_id, {})
                raw_status = row.get("Final_Status", "normal")
                node_states[f"material:{material_id}"] = {
                    "status": _display_status(raw_status),
                    "raw_status": _display_status(raw_status),
                    "trigger_reason": row.get("Trigger_Reason", "none"),
                    "inventory_end_qty": row.get("Inventory_End_Qty", 0),
                    "planned_demand_qty": row.get("Planned_Demand_Qty", 0),
                    "unmet_demand_qty": row.get("Unmet_Demand_Qty", 0),
                }
            for supplier_id in supplier_ids:
                supply_row = supplier_supply_lookup.get(month_index, {}).get(supplier_id, {})
                demand_row = supplier_demand_lookup.get(month_index, {}).get(supplier_id, {})
                merged_raw_status = _merge_status(
                    supply_row.get("Final_Status", "normal"),
                    demand_row.get("Final_Status", "normal"),
                )
                node_states[f"supplier:{supplier_id}"] = {
                    "status": _display_status(merged_raw_status),
                    "raw_status": _display_status(merged_raw_status),
                    "supply_status": _display_status(supply_row.get("Final_Status", "normal")),
                    "supply_reason": supply_row.get("Trigger_Reason", "none"),
                    "demand_status": _display_status(demand_row.get("Final_Status", "normal")),
                    "demand_reason": demand_row.get("Trigger_Reason", "none"),
                    "interrupted_material_count": supply_row.get("Interrupted_Material_Count", 0),
                    "zero_demand_edge_count": demand_row.get("Zero_Demand_Edge_Count", 0),
                }
            month_states[str(month_index)] = node_states
        return month_states

    return {
        "canvas": {"width": 2340, "height": 920},
        "months": [
            {"month_index": month_index, "month_label": month_labels[month_index - 1]}
            for month_index in range(1, TOTAL_MONTHS + 1)
        ],
        "nodes": nodes,
        "edges": edges,
        "status_palette": STATUS_COLORS,
        "comparison_rows": monthly_recovery_comparison,
        "scenarios": {
            "baseline": {"month_states": build_month_states(baseline_payload)},
            "strategy": {"month_states": build_month_states(strategy_payload)},
        },
    }


def build_network_visualization_html(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Study 04 Monthly Interruption Network</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --card: #ffffff;
      --text: #173042;
      --muted: #607486;
      --line: #d7dee6;
      --normal: #78a9d1;
      --affected: #f2b366;
      --interrupted: #df5a49;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #eef3f7 0%, #f8fafc 100%);
      color: var(--text);
    }
    .page {
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 16px;
      padding: 16px;
    }
    .panel {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(26, 54, 93, 0.08);
    }
    .title {
      margin: 0 0 8px;
      font-size: 20px;
      font-weight: 700;
    }
    .subtle {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      margin: 0 0 12px;
    }
    .controls {
      display: grid;
      gap: 12px;
      margin-bottom: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    select, input[type="range"] {
      width: 100%;
    }
    .legend {
      display: grid;
      gap: 8px;
      margin: 16px 0;
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }
    .swatch {
      width: 14px;
      height: 14px;
      border-radius: 999px;
      border: 1px solid rgba(0,0,0,0.2);
    }
    .metrics {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      background: #fbfdff;
    }
    .metric strong {
      display: block;
      font-size: 18px;
      margin-top: 2px;
      color: var(--text);
    }
    .detail {
      margin-top: 16px;
      border-top: 1px solid var(--line);
      padding-top: 16px;
      font-size: 13px;
      line-height: 1.55;
    }
    .detail-title {
      font-weight: 700;
      margin-bottom: 8px;
      font-size: 15px;
    }
    .detail pre {
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    }
    .canvas-wrap {
      overflow: auto;
      background: radial-gradient(circle at top left, rgba(120, 169, 209, 0.14), transparent 28%),
                  radial-gradient(circle at bottom right, rgba(242, 179, 102, 0.16), transparent 22%),
                  #f9fbfd;
    }
    svg {
      width: 100%;
      min-width: 2340px;
      min-height: 920px;
    }
    .edge {
      stroke: #b9c5d1;
      stroke-width: 1.6;
      opacity: 0.18;
    }
    .edge.edge-bom {
      stroke-dasharray: 6 4;
    }
    .edge.edge-supplier_network {
      stroke: #8aa3b7;
    }
    .node text {
      font-size: 12px;
      fill: #244861;
      pointer-events: none;
    }
    .node circle {
      stroke-width: 2;
      cursor: pointer;
      transition: transform 120ms ease;
    }
    .node.selected circle {
      stroke-width: 4;
      transform: scale(1.05);
    }
    .node.supplier circle {
      r: 20;
    }
    .node.material circle {
      r: 18;
    }
  </style>
</head>
<body>
  <div class="page">
    <aside class="panel">
      <h1 class="title">月度中断网络图</h1>
      <p class="subtle">红色表示中断，橙色表示受影响，蓝色表示正常。左侧为供应商网络，右侧为物料 BOM 网络。</p>
      <div class="controls">
        <label>场景
          <select id="scenario-select">
            <option value="strategy">恢复策略</option>
            <option value="baseline">基线对照</option>
          </select>
        </label>
        <label>月份
          <input id="month-range" type="range" min="1" max="12" step="1" value="7" />
        </label>
        <div id="month-label" class="subtle"></div>
      </div>
      <div class="legend">
        <div class="legend-item"><span class="swatch" style="background: var(--interrupted)"></span>中断</div>
        <div class="legend-item"><span class="swatch" style="background: var(--affected)"></span>受影响</div>
        <div class="legend-item"><span class="swatch" style="background: var(--normal)"></span>正常</div>
      </div>
      <div class="metrics">
        <div class="metric">中断节点数<strong id="metric-interrupted">0</strong></div>
        <div class="metric">受影响节点数<strong id="metric-affected">0</strong></div>
        <div class="metric">正常节点数<strong id="metric-normal">0</strong></div>
        <div class="metric">恢复未满足需求量<strong id="metric-recovered-demand">0</strong></div>
        <div class="metric">恢复期末库存<strong id="metric-recovered-inventory">0</strong></div>
      </div>
      <div class="detail">
        <div class="detail-title">节点详情</div>
        <pre id="detail-box">点击节点后，这里会展示该节点在当前月份的状态和辅助信息。</pre>
      </div>
    </aside>
    <section class="panel canvas-wrap">
      <svg id="network-svg" viewBox="0 0 2340 920" preserveAspectRatio="xMinYMin meet"></svg>
    </section>
  </div>
  <script>
    const payload = __PAYLOAD_JSON__;
    const svg = document.getElementById("network-svg");
    const scenarioSelect = document.getElementById("scenario-select");
    const monthRange = document.getElementById("month-range");
    const monthLabel = document.getElementById("month-label");
    const detailBox = document.getElementById("detail-box");
    const metricInterrupted = document.getElementById("metric-interrupted");
    const metricAffected = document.getElementById("metric-affected");
    const metricNormal = document.getElementById("metric-normal");
    const metricRecoveredDemand = document.getElementById("metric-recovered-demand");
    const metricRecoveredInventory = document.getElementById("metric-recovered-inventory");

    const nodeById = Object.fromEntries(payload.nodes.map((node) => [node.id, node]));
    const nodeElements = new Map();
    const edgeElements = [];
    const comparisonByMonth = Object.fromEntries(payload.comparison_rows.map((row) => [String(row.Month_Index), row]));
    let selectedNodeId = null;

    function createSvgElement(tagName, attrs) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
      Object.entries(attrs || {}).forEach(([key, value]) => element.setAttribute(key, value));
      return element;
    }

    function renderGraph() {
      payload.edges.forEach((edge) => {
        const source = nodeById[edge.source];
        const target = nodeById[edge.target];
        if (!source || !target) return;
        const line = createSvgElement("line", {
          x1: source.x,
          y1: source.y,
          x2: target.x,
          y2: target.y,
          class: `edge edge-${edge.edge_type}`,
        });
        svg.appendChild(line);
        edgeElements.push({ edge, line });
      });

      payload.nodes.forEach((node) => {
        const group = createSvgElement("g", {
          class: `node ${node.node_type}`,
          transform: `translate(${node.x}, ${node.y})`,
        });
        const circle = createSvgElement("circle", {
          cx: 0,
          cy: 0,
          r: node.node_type === "supplier" ? 20 : 18,
        });
        const title = createSvgElement("title");
        title.textContent = `${node.label} (${node.entity_id})`;
        const text = createSvgElement("text", {
          x: node.node_type === "supplier" ? -28 : -24,
          y: node.node_type === "supplier" ? 36 : 32,
        });
        text.textContent = node.label;

        circle.addEventListener("click", () => {
          selectedNodeId = node.id;
          updateGraph();
        });

        group.appendChild(circle);
        group.appendChild(title);
        group.appendChild(text);
        svg.appendChild(group);
        nodeElements.set(node.id, { node, group, circle, text });
      });
    }

    function currentMonthStates() {
      return payload.scenarios[scenarioSelect.value].month_states[String(monthRange.value)] || {};
    }

    function formatNumber(value) {
      return Number(value || 0).toLocaleString("zh-CN");
    }

    function updateDetail(nodeState, node) {
      if (!node) {
        detailBox.textContent = "点击节点后，这里会展示该节点在当前月份的状态和辅助信息。";
        return;
      }
      const lines = [
        `节点: ${node.label}`,
        `类型: ${node.node_type}`,
        `ID: ${node.entity_id}`,
        `状态: ${nodeState.status || "normal"}`,
      ];
      if (node.node_type === "material") {
        lines.push(`触发原因: ${nodeState.trigger_reason || "none"}`);
        lines.push(`未满足需求量: ${formatNumber(nodeState.unmet_demand_qty)}`);
        lines.push(`计划需求量: ${formatNumber(nodeState.planned_demand_qty)}`);
        lines.push(`月末库存量: ${formatNumber(nodeState.inventory_end_qty)}`);
      } else {
        lines.push(`供给状态: ${nodeState.supply_status || "normal"}`);
        lines.push(`供给原因: ${nodeState.supply_reason || "none"}`);
        lines.push(`需求状态: ${nodeState.demand_status || "normal"}`);
        lines.push(`需求原因: ${nodeState.demand_reason || "none"}`);
        lines.push(`中断物料数: ${formatNumber(nodeState.interrupted_material_count)}`);
        lines.push(`零需求边数: ${formatNumber(nodeState.zero_demand_edge_count)}`);
      }
      Object.entries(node.meta || {}).forEach(([key, value]) => {
        if (value === "" || value === null) return;
        lines.push(`${key}: ${typeof value === "object" ? JSON.stringify(value, null, 2) : value}`);
      });
      detailBox.textContent = lines.join("\\n");
    }

    function updateGraph() {
      const monthIndex = String(monthRange.value);
      const monthInfo = payload.months[Number(monthRange.value) - 1];
      const states = currentMonthStates();
      let interrupted = 0;
      let affected = 0;
      let normal = 0;

      monthLabel.textContent = `当前月份: 第${monthInfo.month_index}月（${monthInfo.month_label}）`;

      nodeElements.forEach((entry, nodeId) => {
        const nodeState = states[nodeId] || { status: "normal" };
        const palette = payload.status_palette[nodeState.status] || payload.status_palette.normal;
        entry.circle.setAttribute("fill", palette.fill);
        entry.circle.setAttribute("stroke", palette.stroke);
        entry.group.classList.toggle("selected", selectedNodeId === nodeId);

        if (nodeState.status === "interrupted") interrupted += 1;
        else if (nodeState.status === "affected") affected += 1;
        else normal += 1;
      });

      edgeElements.forEach(({ edge, line }) => {
        const sourceStatus = (states[edge.source] || { status: "normal" }).status;
        const targetStatus = (states[edge.target] || { status: "normal" }).status;
        const isActive = selectedNodeId
          ? edge.source === selectedNodeId || edge.target === selectedNodeId
          : sourceStatus !== "normal" || targetStatus !== "normal";
        line.setAttribute("opacity", isActive ? "0.62" : "0.18");
      });

      metricInterrupted.textContent = formatNumber(interrupted);
      metricAffected.textContent = formatNumber(affected);
      metricNormal.textContent = formatNumber(normal);

      const comparison = comparisonByMonth[monthIndex];
      if (comparison) {
        metricRecoveredDemand.textContent = formatNumber(comparison.Recovered_Unmet_Demand_Qty);
        metricRecoveredInventory.textContent = formatNumber(comparison.Recovered_End_Inventory_Qty);
      } else {
        metricRecoveredDemand.textContent = "0";
        metricRecoveredInventory.textContent = "0";
      }

      const selectedNode = nodeById[selectedNodeId];
      updateDetail(states[selectedNodeId] || { status: "normal" }, selectedNode || null);
    }

    scenarioSelect.addEventListener("change", updateGraph);
    monthRange.addEventListener("input", updateGraph);
    renderGraph();
    updateGraph();
  </script>
</body>
</html>"""
    return html.replace("__PAYLOAD_JSON__", payload_json)

def build_dashboard_visualization_payload(
    scenario_summaries: dict[str, dict],
    scenario_monthly_comparison_rows: dict[str, list[dict]],
    scenario_continuous_rows: dict[str, list[dict]],
    scenario_strategy_matrix: list[dict],
    default_scenario_key: str,
) -> dict:
    return {
        "default_scenario_key": default_scenario_key,
        "scenario_keys": list(scenario_summaries.keys()),
        "scenario_summaries": scenario_summaries,
        "scenario_monthly_comparison_rows": scenario_monthly_comparison_rows,
        "scenario_continuous_rows": scenario_continuous_rows,
        "scenario_strategy_matrix": scenario_strategy_matrix,
    }


def build_dashboard_visualization_html(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Study 04 Scenario Dashboard</title>
  <style>
    body{margin:0;font-family:"Microsoft YaHei","Segoe UI",sans-serif;background:linear-gradient(180deg,#eef3f7 0%,#f8fafc 100%);color:#173042}
    .page{max-width:1680px;margin:0 auto;padding:18px;display:grid;gap:16px}
    .panel{background:#fff;border:1px solid #d7dee6;border-radius:16px;padding:16px;box-shadow:0 10px 30px rgba(26,54,93,.08)}
    .head{display:flex;justify-content:space-between;gap:16px;align-items:end;flex-wrap:wrap}
    .title{margin:0;font-size:24px}
    .subtle{margin:6px 0 0;color:#607486;font-size:13px}
    .cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
    .card{border:1px solid #d7dee6;border-radius:12px;padding:12px;background:#fbfdff}
    .card strong{display:block;margin-top:4px;font-size:18px}
    .grid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{border-bottom:1px solid #e3ebf1;padding:8px 10px;text-align:left}
    th{background:#f7fafc}
    select{min-width:260px;padding:8px 10px;border:1px solid #cdd9e3;border-radius:10px;background:#fff}
    @media (max-width:1200px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="page">
    <section class="panel">
      <div class="head">
        <div>
          <h1 class="title">中断恢复总览看板</h1>
          <p class="subtle">对比不同场景下的中断数量、恢复效果、连续中断月数和月度差异。</p>
        </div>
        <label>场景
          <select id="scenario-select"></select>
        </label>
      </div>
    </section>
    <section class="panel">
      <div class="cards">
        <div class="card">预测期物料中断<strong id="metric-material"></strong></div>
        <div class="card">预测期供应商中断<strong id="metric-supplier"></strong></div>
        <div class="card">恢复波及节点数<strong id="metric-scope"></strong></div>
        <div class="card">恢复未满足需求量<strong id="metric-demand"></strong></div>
        <div class="card">恢复期末库存<strong id="metric-inventory"></strong></div>
        <div class="card">最长连续中断月数<strong id="metric-continuous"></strong></div>
      </div>
    </section>
    <section class="grid">
      <section class="panel">
        <h2>月度恢复对比</h2>
        <table>
          <thead>
            <tr>
              <th>月份</th>
              <th>基线中断</th>
              <th>策略中断</th>
              <th>恢复未满足需求</th>
              <th>恢复期末库存</th>
            </tr>
          </thead>
          <tbody id="monthly-body"></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>连续中断对比</h2>
        <table>
          <thead>
            <tr>
              <th>节点</th>
              <th>基线最长连续中断</th>
              <th>策略最长连续中断</th>
            </tr>
          </thead>
          <tbody id="continuous-body"></tbody>
        </table>
      </section>
    </section>
    <section class="panel">
      <h2>情景矩阵</h2>
      <table>
        <thead>
          <tr>
            <th>场景</th>
            <th>节点范围</th>
            <th>供应商模式</th>
            <th>恢复波及节点</th>
            <th>恢复未满足需求</th>
            <th>恢复期末库存</th>
            <th>策略最长连续中断</th>
          </tr>
        </thead>
        <tbody id="matrix-body"></tbody>
      </table>
    </section>
  </div>
  <script>
    const payload = __PAYLOAD_JSON__;
    const scenarioSelect = document.getElementById("scenario-select");
    const monthlyBody = document.getElementById("monthly-body");
    const continuousBody = document.getElementById("continuous-body");
    const matrixBody = document.getElementById("matrix-body");
    const metricMaterial = document.getElementById("metric-material");
    const metricSupplier = document.getElementById("metric-supplier");
    const metricScope = document.getElementById("metric-scope");
    const metricDemand = document.getElementById("metric-demand");
    const metricInventory = document.getElementById("metric-inventory");
    const metricContinuous = document.getElementById("metric-continuous");

    function formatNumber(value) {
      const numeric = Number(value || 0);
      return Number.isInteger(numeric) ? numeric.toLocaleString("zh-CN") : numeric.toFixed(2);
    }

    function renderMatrix() {
      matrixBody.innerHTML = "";
      payload.scenario_strategy_matrix.forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.Scenario_Key}</td>
          <td>${row.Node_Scope}</td>
          <td>${row.Supplier_Mode}</td>
          <td>${formatNumber((row.Forecast_Scope_Node_Count_Baseline || 0) - (row.Forecast_Scope_Node_Count_Strategy || 0))}</td>
          <td>${formatNumber((row.Forecast_Unmet_Demand_Qty_Baseline || 0) - (row.Forecast_Unmet_Demand_Qty_Strategy || 0))}</td>
          <td>${formatNumber((row.Forecast_End_Inventory_Qty_Strategy || 0) - (row.Forecast_End_Inventory_Qty_Baseline || 0))}</td>
          <td>${formatNumber(row.Max_Continuous_Interrupted_Months_Strategy || 0)}</td>`;
        matrixBody.appendChild(tr);
      });
    }

    function renderScenario() {
      const scenarioKey = scenarioSelect.value;
      const summary = payload.scenario_summaries[scenarioKey] || {};
      const monthlyRows = payload.scenario_monthly_comparison_rows[scenarioKey] || [];
      const continuousRows = payload.scenario_continuous_rows[scenarioKey] || [];

      metricMaterial.textContent = `${formatNumber(summary.forecast_material_interruption_rows_baseline)} -> ${formatNumber(summary.forecast_material_interruption_rows_strategy)}`;
      metricSupplier.textContent = `${formatNumber(summary.forecast_supplier_interruption_rows_baseline)} -> ${formatNumber(summary.forecast_supplier_interruption_rows_strategy)}`;
      metricScope.textContent = formatNumber(summary.forecast_recovered_scope_node_count);
      metricDemand.textContent = formatNumber(summary.forecast_recovered_unmet_demand_qty);
      metricInventory.textContent = formatNumber(summary.forecast_recovered_end_inventory_qty);
      metricContinuous.textContent = `${formatNumber(summary.max_continuous_interrupted_months_baseline)} -> ${formatNumber(summary.max_continuous_interrupted_months_strategy)}`;

      monthlyBody.innerHTML = "";
      monthlyRows.forEach((row) => {
        const interruptedBaseline = (row.Baseline_Material_Interrupted_Count || 0) + (row.Baseline_Supplier_Interrupted_Count || 0);
        const interruptedStrategy = (row.Strategy_Material_Interrupted_Count || 0) + (row.Strategy_Supplier_Interrupted_Count || 0);
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.Month_Label || row.Month_Index}</td>
          <td>${formatNumber(interruptedBaseline)}</td>
          <td>${formatNumber(interruptedStrategy)}</td>
          <td>${formatNumber(row.Recovered_Unmet_Demand_Qty || 0)}</td>
          <td>${formatNumber(row.Recovered_End_Inventory_Qty || 0)}</td>`;
        monthlyBody.appendChild(tr);
      });

      continuousBody.innerHTML = "";
      continuousRows.slice(0, 16).forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.Node_Label || row.Node_ID}</td>
          <td>${formatNumber(row.Baseline_Max_Continuous_Interrupted_Months || 0)}</td>
          <td>${formatNumber(row.Strategy_Max_Continuous_Interrupted_Months || 0)}</td>`;
        continuousBody.appendChild(tr);
      });
    }

    payload.scenario_keys.forEach((scenarioKey) => {
      const option = document.createElement("option");
      option.value = scenarioKey;
      option.textContent = scenarioKey;
      scenarioSelect.appendChild(option);
    });
    scenarioSelect.value = payload.default_scenario_key;
    scenarioSelect.addEventListener("change", renderScenario);
    renderMatrix();
    renderScenario();
  </script>
</body>
</html>
"""
    return html.replace("__PAYLOAD_JSON__", payload_json)


