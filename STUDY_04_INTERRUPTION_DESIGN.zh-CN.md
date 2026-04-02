# Study 04 中断与恢复开发说明

## 1. 需求文档已经明确的规则

根据 `0401中断需求文档.docx`，当前版本已经明确了以下实现边界：

- 时间粒度按月，固定 12 个月。
- 第 1-6 个月是历史承接期，第 7-12 个月是预测与恢复仿真期。
- 中断持续期固定为参数 `L`，当前默认 `L=3`。
- 物料中断判定公式固定为：`库存 + 生产 - 计划需求量 < 0` 且 `产出 = 0`。
- 供应商判定分为两类单独情景：`supply` 和 `demand`，同一轮仿真不能混用。
- 传播时序固定为“本月判定、本月传播、下月计算”。
- 恢复动作固定为“当月决策、次月生效”。
- 恢复仅作用于第 7-12 个月。
- 一般节点使用策略 A，关键节点使用策略 B。

## 2. 当前代码已经具备的能力

`study_04_response_recovery` 现在已经能输出一套开发样例级的月度数据与仿真结果，包括：

- `material_monthly_state`
- `supplier_monthly_supply_state`
- `supplier_demand_edge_monthly_state`
- `supplier_monthly_demand_state`
- `recovery_actions`
- `scenario_seed_summary`
- 情景对比表、网络可视化、场景仪表盘

当前模块的定位不是“真实业务预测”，而是“先把字段、时序、状态机和可视化跑通”。

## 3. 文档里已有、代码可直接复用的数据

从现有静态表里，可以直接复用的基础数据有：

- `Material_Summary_Table`
  作用：物料主数据、关键物料标识、起始库存、平均消耗。
- `Supplier_Summary_Table`
  作用：供应商主数据、基础经营属性。
- `Order_Table`
  作用：供应商-物料供货关系、月度需求/产能/产出近似来源。
- `Material_BOM`
  作用：物料上下游传播关系。
- `Equivalent_Material_Table`
  作用：替代料候选关系。
- `Supplier_Network`
  作用：供应商需求传播或供应链传播底座。
- `Supplier_Emergency_Incident_Table` + `emergency_incident`
  作用：供应冲击种子事件来源。

## 4. 文档里没给清楚、正式开发前必须补齐的数据

下面这些在需求文档里只有规则，没有完整数据口径，正式版必须补：

- `Is_Critical_Supplier`
  说明：文档要求关键供应商由外部给定，但底表没有正式字段。
  建议：在 `Supplier_Summary_Table` 中新增正式字段，或由上游研究模块输出一张关键供应商清单表。

- 第 7-12 个月的真实预测输入
  说明：文档规定后 6 个月要做恢复仿真，但没有给出真实预测值来源。
  需要补齐：
  - 月度库存预测
  - 月度生产计划预测
  - 月度需求预测
  - 月度产出预测

- 月度需求边事实表
  说明：需求情景要求按月判断边状态 `0/1`，但当前底库没有真实月度需求边表。
  建议新增：`supplier_demand_edge_monthly_fact`
  最低字段建议：
  - `Month_Index`
  - `Supplier_ID`
  - `Supplier_down_ID`
  - `Demand_Edge_Status`
  - `Order_Count`
  - `Demand_Qty`
  - `Demand_Source`

- 恢复动作执行参数
  说明：文档说明了“补料”，但没有完整执行约束。
  建议正式补齐：
  - `Decision_Month`
  - `Effective_Month`
  - `Target_Node_ID`
  - `Target_Node_Type`
  - `Action_Type`
  - `Planned_Replenishment_Qty`
  - `Recovery_Cost`
  - `Available_Recovery_Capacity`
  - `Lead_Time`
  - `Execution_Success_Rate`

## 5. 当前开发建议

推荐按下面顺序推进：

1. 先把月度事实层稳定下来。
   目标是让 `material_monthly_state`、`supplier_monthly_supply_state`、`supplier_demand_edge_monthly_state`、`supplier_monthly_demand_state` 成为稳定输出。

2. 再把传播状态机固化。
   重点是确保 `L=3`、本月判定/本月传播/下月计算、以及供应商两种单情景逻辑严格符合文档。

3. 之后再细化恢复策略。
   当前版本先保留策略 A/B 的结构差异；正式版再接入补料容量、成本、替代料、联动供应商等更真实的决策参数。

4. 最后再做验收型可视化。
   包括月度中断数量、中断波及范围、连续中断月数、情景-策略矩阵，以及可选的物料热力图和需求边状态图。

## 6. 本次样例数据的定位

本目录里的 12 个月数据属于“开发样例数据”，作用是：

- 明确字段定义
- 验证状态时序
- 让可视化上能明显看出波动
- 支撑后续把真实预测数据接进来

它不是最终业务校准数据，也不能替代真实预测或真实月报。
