(function () {
  const dashboardData = window.study04DynamicData;
  const CHINA_MAP_ASSET = "assets/china-100000-full.json";
  const baseScenes = (dashboardData && dashboardData.scenes) || {};
  const families = Object.keys(baseScenes);
  const contract = dashboardData?.contract || {
    contract_version: "0.0.0",
    policy_profiles: [
      { value: "time_priority_interrupt", label: "当前恢复策略" },
      { value: "all_policies", label: "全策略显示联动" },
      { value: "no_policy", label: "无恢复策略" },
      { value: "only_backup_switch", label: "仅备供切换" },
      { value: "only_substitution", label: "仅等效替代" },
      { value: "only_priority_repair", label: "仅优先抢修" },
    ],
    network_filters: [
      { value: "all", label: "全链路" },
      { value: "key", label: "仅关键节点" },
      { value: "disrupted", label: "仅中断/阻断" },
      { value: "supplier", label: "仅供应商" },
      { value: "item", label: "仅物料/BOM" },
      { value: "policy", label: "仅策略作用边" },
    ],
  };

  if (!dashboardData || !families.length) {
    document.body.innerHTML = '<div class="page-shell"><div class="panel">未找到动态展示数据，请先刷新前端数据。</div></div>';
    return;
  }

  const state = {
    page: "overview",
    subViewByPage: {
      overview: "scene_summary",
      random: "process_overview",
      keynode: "process_overview",
      recovery: "recovery_overview",
    },
    recoveryFamily: "random",
    selectedIndexByFamily: {},
    viewportByFamily: {},
    selectedNodeByFamily: {
      random: [],
      keynode: [],
    },
    policyProfileByFamily: {
      random: "time_priority_interrupt",
      keynode: "time_priority_interrupt",
    },
    networkFilterByFamily: {
      random: "process",
      keynode: "process",
    },
    recoveryFilterByFamily: {
      random: "recovery",
      keynode: "recovery",
    },
    networkViewByFamily: {
      random: { scale: 1, panX: 0, panY: 0 },
      keynode: { scale: 1, panX: 0, panY: 0 },
    },
    focusNodeByFamily: {
      random: null,
      keynode: null,
    },
    layoutOverridesByScene: {},
    whatIfPayloads: {
      random: null,
      keynode: null,
    },
    resultModeByFamily: {
      random: "baseline",
      keynode: "baseline",
    },
    playingFamily: null,
    timer: null,
    policyMetric: "total_interrupted_nodes",
    apiBase: resolveApiBase(),
    apiAvailable: false,
    apiMessage: "正在检测本地推演服务…",
    apiContractVersion: contract.contract_version || "0.0.0",
    isSubmittingWhatIf: false,
    lastWhatIf: null,
    chinaGeoJson: null,
    chinaMapLoading: false,
    chinaMapError: "",
  };

  const dom = {
    pageNavGroup: document.getElementById("page-nav-group"),
    familyNavRow: document.getElementById("family-nav-row"),
    resultModeRow: document.getElementById("result-mode-row"),
    resultBanner: document.getElementById("result-banner"),
    viewRoot: document.getElementById("view-root"),
  };

  const pageDefs = [
    { key: "overview", label: "总览" },
    { key: "random", label: "随机中断" },
    { key: "keynode", label: "关键节点中断" },
    { key: "recovery", label: "恢复策略" },
    { key: "map", label: "地图展示" },
  ];

  const pageModuleDefs = {
    overview: [
      { key: "scene_summary", label: "情境总览" },
      { key: "propagation_statistics", label: "传播统计" },
    ],
    random: [
      { key: "process_overview", label: "传播总览" },
      { key: "dynamic_network", label: "动态网络" },
      { key: "supply_propagation", label: "供给传播" },
      { key: "demand_propagation", label: "需求传播" },
      { key: "node_simulation", label: "节点推演" },
    ],
    keynode: [
      { key: "process_overview", label: "传播总览" },
      { key: "dynamic_network", label: "动态网络" },
      { key: "supply_propagation", label: "供给传播" },
      { key: "demand_propagation", label: "需求传播" },
      { key: "node_simulation", label: "节点推演" },
    ],
    recovery: [
      { key: "recovery_overview", label: "恢复总览" },
      { key: "recovery_network", label: "恢复网络" },
      { key: "policy_compare", label: "策略对比" },
      { key: "impact_paths", label: "影响路径" },
    ],
  };

  const sceneTrendDefs = [
    {
      title: "服务水平与需求履约",
      mode: "ratio",
      note: "",
      series: [
        { key: "service_level", label: "产品服务水平", color: "#0F766E" },
        { key: "demand_fulfillment_rate", label: "需求满足率", color: "#2563EB" },
        { key: "system_service_level", label: "系统服务水平", color: "#7C3AED" },
      ],
    },
    {
      title: "供给与需求冲击",
      mode: "count",
      note: "",
      series: [
        { key: "supply_unavailable_items", label: "供应不可用物料", color: "#C2410C" },
        { key: "total_backlog_demand", label: "积压需求总量", color: "#D97706" },
        { key: "total_lost_demand", label: "损失需求总量", color: "#DC2626" },
        { key: "fused_failed_items", label: "融合失败物料", color: "#6D28D9" },
      ],
    },
    {
      title: "供给传播",
      mode: "count",
      note: "",
      series: [
        { key: "supplier_disrupted_nodes", label: "中断供应商", color: "#E11D48" },
        { key: "supplier_network_disrupted_edges", label: "供应商网络中断边", color: "#B91C1C" },
        { key: "supply_edge_backup_active", label: "备用映射激活边", color: "#277DA1" },
      ],
    },
    {
      title: "需求传播与下游阻断",
      mode: "count",
      note: "",
      series: [
        { key: "material_blocked_nodes", label: "阻断物料", color: "#B23A48" },
        { key: "assembly_blocked_nodes", label: "阻断装配件", color: "#EF4444" },
        { key: "product_blocked_nodes", label: "阻断产品", color: "#374151" },
        { key: "bom_edge_disrupted", label: "物料清单中断边", color: "#4A044E" },
      ],
    },
  ];

  const recoveryTrendDefs = [
    {
      title: "恢复动作激活轨迹",
      mode: "count",
      note: "",
      series: [
        { key: "active_backup_switches", label: "激活备供切换", color: "#0B8F72" },
        { key: "active_substitutions", label: "激活等效替代", color: "#EA580C" },
        { key: "active_priority_repairs", label: "激活优先抢修", color: "#0284C7" },
      ],
    },
    {
      title: "策略累计成本",
      mode: "count",
      note: "",
      series: [
        { key: "policy_cumulative_cost", label: "累计策略成本", color: "#334155" },
      ],
    },
  ];

  init();

  async function init() {
    families.forEach((family) => {
      const scene = baseScenes[family];
      const startIndex = Math.max(0, scene.daily.findIndex((row) => row.date === scene.scenario.start_date));
      state.selectedIndexByFamily[family] = startIndex >= 0 ? startIndex : 0;
      state.viewportByFamily[family] = createViewport(scene.daily.length, state.selectedIndexByFamily[family]);
    });
    window.addEventListener("resize", debounce(renderApp, 120));
    renderApp();
    await bootstrapApi();
  }

  async function bootstrapApi() {
    renderApp();
    try {
      const health = await fetchJson(buildApiUrl("/api/health"));
      if (health && health.ok) {
        state.apiAvailable = true;
        state.apiContractVersion = health.contract_version || state.apiContractVersion;
        state.apiMessage = `本地推演服务已连接（${health.node_count || 0} 个节点可点选）`;
        const contractPayload = await fetchJson(buildApiUrl("/api/contract"));
        if (contractPayload?.ok && contractPayload.contract?.contract_version) {
          state.apiContractVersion = contractPayload.contract.contract_version;
          if (state.apiContractVersion !== (contract.contract_version || "0.0.0")) {
            state.apiMessage = `本地服务已连接，但接口契约版本为 ${state.apiContractVersion}，与页面内置版本 ${contract.contract_version} 不一致。`;
          }
        }
      } else {
        state.apiMessage = "本地推演服务未就绪";
      }
    } catch (error) {
      state.apiAvailable = false;
      state.apiMessage = "未连接到本地推演服务。若需点击节点实时重算，请先启动本地服务脚本。";
    }
    renderApp();
  }

  function renderApp() {
    const family = currentFamily();
    document.body.dataset.page = state.page;
    document.body.dataset.resultMode = family ? (state.resultModeByFamily[family] || "baseline") : "baseline";
    renderPageNav();
    renderFamilyNav();
    renderResultModes();
    renderResultBanner();
    dom.viewRoot.innerHTML = "";

    if (state.page === "overview") {
      renderOverviewView();
      return;
    }
    if (state.page === "random" || state.page === "keynode") {
      renderSceneView(state.page);
      return;
    }
    if (state.page === "map") {
      renderMapView();
      return;
    }
    renderRecoveryView();
  }

  function renderPageNav() {
    dom.pageNavGroup.innerHTML = "";
    pageDefs.forEach((page) => {
      const button = createElement("button", "scene-pill", page.label);
      if (state.page === page.key) {
        button.classList.add("active");
        button.style.background = pageAccent(page.key);
      }
      button.addEventListener("click", () => {
        const nextRecoveryFamily =
          (page.key === "recovery" || page.key === "map") && (state.page === "random" || state.page === "keynode")
            ? state.page
            : state.recoveryFamily;
        syncPlaybackForFamily(resolvePageFamily(page.key, nextRecoveryFamily));
        if ((page.key === "recovery" || page.key === "map") && (state.page === "random" || state.page === "keynode")) {
          state.recoveryFamily = state.page;
        }
        state.page = page.key;
        renderApp();
      });
      dom.pageNavGroup.appendChild(button);
    });
  }

  /*
   * Inactive duplicate: final renderFamilyNav/renderResultModes definitions
   * live later in the file. Kept commented so only one implementation is active.
   *
  function renderFamilyNav() {
    dom.familyNavRow.innerHTML = "";
    if (state.page !== "recovery" && state.page !== "map") {
      return;
    }
    const wrapper = createElement("div", "scene-pill-group");
    wrapper.appendChild(createElement("span", "toolbar-label", "恢复策略页情境："));
    families.forEach((family) => {
      const button = createElement("button", "scene-pill", baseScenes[family].label);
      if (state.recoveryFamily === family) {
        button.classList.add("active");
        button.style.background = baseScenes[family].accent;
      }
      button.addEventListener("click", () => {
        syncPlaybackForFamily(family);
        state.recoveryFamily = family;
        renderApp();
      });
      wrapper.appendChild(button);
    });
    dom.familyNavRow.appendChild(wrapper);
  }

  function renderResultModes() {
    dom.resultModeRow.innerHTML = "";
    const family = currentFamily();
    if (!family) {
      return;
    }
    const whatIf = state.whatIfPayloads[family];
    const wrapper = createElement("div", "scene-pill-group");
    wrapper.appendChild(createElement("span", "toolbar-label", "结果模式："));

    const baselineButton = createElement("button", "scene-pill", "基准情境");
    if (state.resultModeByFamily[family] === "baseline") {
      baselineButton.classList.add("active");
      baselineButton.style.background = baseScenes[family].accent;
    }
    baselineButton.addEventListener("click", () => {
      state.resultModeByFamily[family] = "baseline";
      renderApp();
    });
    wrapper.appendChild(baselineButton);

    if (whatIf) {
      const whatIfButton = createElement("button", "scene-pill", "当前推演结果");
      if (state.resultModeByFamily[family] === "whatif") {
        whatIfButton.classList.add("active");
        whatIfButton.style.background = "#7C3AED";
      }
      whatIfButton.addEventListener("click", () => {
        state.resultModeByFamily[family] = "whatif";
        renderApp();
      });
      wrapper.appendChild(whatIfButton);
    }

    dom.resultModeRow.appendChild(wrapper);
  }
  */

  function renderResultBanner() {
    dom.resultBanner.innerHTML = "";
    /*
    const family = currentFamily();
    if (!family) {
      return;
    }
    const whatIf = state.whatIfPayloads[family];
    if (!whatIf || state.resultModeByFamily[family] !== "whatif") {
      return;
    }
    const banner = createElement("section", "panel result-banner-panel");
    const row = createElement("div", "result-banner-row");
    const copy = createElement("div");
    copy.appendChild(createElement("h2", "banner-title", `当前正在查看：${replaceEntityIdsWithNames(whatIf.meta.trigger_node_label || "定点中断推演结果", getSceneBundle(family).current)}`));
    copy.appendChild(
      createElement(
        "div",
        "chart-note",
        "当前页面已切换为节点点击后的新推演结果。你可以直接拖动时间轴和网络图，观察这一节点中断后从传播到恢复的全过程。"
      )
    );
    const actions = createElement("div", "scene-pill-group");
    const back = createElement("button", "ghost-button", "返回基准情境");
    back.addEventListener("click", () => {
      state.resultModeByFamily[family] = "baseline";
      renderApp();
    });
    const clear = createElement("button", "scene-pill", "清除当前推演");
    clear.addEventListener("click", () => {
      state.whatIfPayloads[family] = null;
      state.resultModeByFamily[family] = "baseline";
      renderApp();
    });
    actions.append(back, clear);
    row.append(copy, actions);
    banner.appendChild(row);
    dom.resultBanner.appendChild(banner);
    */
  }

  /*
   * Inactive legacy single-page renderers. The active app uses
   * renderOverviewView/renderSceneView/renderRecoveryView below.
   *
  function legacyRenderOverviewView() {
    const overviewGrid = createElement("div", "overview-grid");

    const scenePanel = createElement("section", "panel");
    const cards = createElement("div", "scene-card-grid");
    families.forEach((family) => {
      cards.appendChild(buildSceneSummaryCard(baseScenes[family]));
    });
    scenePanel.appendChild(cards);

    const comparePanel = createElement("section", "panel");
    comparePanel.append(createSectionHead("", "关键结果对比"));
    const compareGrid = createElement("div", "compare-grid");
    [
      ["恢复天数", "ttr_days", "days"],
      ["平均服务水平", "average_service_level", "percent"],
      ["系统服务水平", "avg_system_service_level", "percent"],
      ["策略总成本", "policy_total_cost", "currency"],
      ["预计中断损失", "estimated_disruption_loss", "currency"],
    ].forEach(([label, key, mode]) => {
      const randomValue = baseScenes.random.summary[key];
      const keynodeValue = baseScenes.keynode.summary[key];
      const card = createElement("article", "compare-card");
      card.appendChild(createElement("span", "", label));
      card.appendChild(createElement("strong", "", `${baseScenes.random.label}：${formatByMode(randomValue, mode)}`));
      card.appendChild(createElement("em", "", `${baseScenes.keynode.label}：${formatByMode(keynodeValue, mode)}`));
      compareGrid.appendChild(card);
    });
    comparePanel.appendChild(compareGrid);

    const timelinePanel = createElement("section", "panel");
    timelinePanel.append(createSectionHead("", "关键阶段时间轴"));
    const timelineGrid = createElement("div", "stage-compare-grid");
    families.forEach((family) => {
      const card = createElement("article", "network-copy-card");
      card.appendChild(createElement("p", "eyebrow", baseScenes[family].label));
      (baseScenes[family].network_snapshots || []).forEach((snapshot) => {
        const row = createElement("div", "stage-row");
        row.appendChild(createElement("strong", "", stageDisplayTitle(snapshot)));
        row.appendChild(createElement("small", "", formatDate(snapshot.snapshot_date)));
        card.appendChild(row);
      });
      timelineGrid.appendChild(card);
    });
    timelinePanel.appendChild(timelineGrid);

    const monthlyPanel = createElement("section", "panel");
    monthlyPanel.append(createSectionHead("", "月度中断节点分布"));
    const monthlyGrid = createElement("div", "mini-chart-grid");
    const monthlyRowsByFamily = Object.fromEntries(
      families.map((family) => [family, baseScenes[family].monthly_disrupted || []])
    );
    const sharedMonths = Array.from(
      new Set(families.flatMap((family) => monthlyRowsByFamily[family].map((row) => String(row.month || ""))))
    ).filter(Boolean).sort();
    const sharedMonthlyMax = Math.max(
      1,
      ...families.flatMap((family) => monthlyRowsByFamily[family].map((row) => Number(row.total_disrupted_nodes || 0)))
    );
    families.forEach((family) => {
      const card = createElement("article", "panel chart-panel compact-panel");
      card.appendChild(createElement("h3", "", baseScenes[family].label));
      card.appendChild(renderMonthlyChart(monthlyRowsByFamily[family], {
        months: sharedMonths,
        maxValue: sharedMonthlyMax,
      }));
      monthlyGrid.appendChild(card);
    });
    monthlyPanel.appendChild(monthlyGrid);

    const durationPanel = createElement("section", "panel");
    durationPanel.append(createSectionHead("", "传播时长对比"));
    const durationGrid = createElement("div", "mini-chart-grid");
    families.forEach((family) => {
      const card = createElement("article", "panel chart-panel compact-panel");
      card.appendChild(createElement("h3", "", overviewDurationTitle(family, baseScenes[family])));
      card.appendChild(renderHorizontalBars(baseScenes[family].propagation_durations || [], {
        labelKey: "label",
        valueKey: "duration_months",
        color: baseScenes[family].accent,
        formatter: (value) => `${formatInteger(value)} 个月`,
      }));
      durationGrid.appendChild(card);
    });
    durationPanel.appendChild(durationGrid);

    overviewGrid.append(scenePanel, comparePanel, timelinePanel, monthlyPanel, durationPanel);
    dom.viewRoot.appendChild(overviewGrid);
  }

  function legacyRenderSceneView(family) {
    const bundle = getSceneBundle(family);
    const scene = bundle.current;
    const selectedIndex = ensureSceneSelection(family, scene);
    const viewport = normalizeViewport(state.viewportByFamily[family], scene.daily.length, selectedIndex);
    state.viewportByFamily[family] = viewport;
    const selected = scene.daily[selectedIndex];
    const stage = resolveCurrentStage(scene, selected.date);

    const topGrid = createElement("div", "scene-top-grid");
    topGrid.appendChild(renderSceneSummaryPanel(scene, family));
    topGrid.appendChild(renderTimeControlPanel(scene, family, selected, stage));
    topGrid.appendChild(renderDetailPanel(scene, family, selected, stage));
    dom.viewRoot.appendChild(topGrid);

    dom.viewRoot.appendChild(renderScenarioNetworkPanel(scene, family, stage, selected.date));

    const trendGrid = createElement("div", "trend-grid");
    sceneTrendDefs.forEach((definition) => {
      const panel = createElement("article", "panel chart-panel");
      panel.append(createChartHead(definition.title, definition.note));
      panel.appendChild(renderLineChart(scene.daily, definition, selectedIndex, (index) => {
        state.selectedIndexByFamily[family] = index;
        state.viewportByFamily[family] = ensureViewportContains(viewport, scene.daily.length, index);
        stopPlay();
        renderApp();
      }, {
        navigator: true,
        ghostNavigator: true,
        windowed: true,
        windowStart: viewport.start,
        windowSize: viewport.size,
        onWindowChange: (start, size) => {
          stopPlay();
          state.viewportByFamily[family] = normalizeViewport(
            { start, size },
            scene.daily.length,
            state.selectedIndexByFamily[family]
          );
          renderApp();
        },
      }));
      panel.appendChild(renderLegend(definition.series));
      trendGrid.appendChild(panel);
    });
    dom.viewRoot.appendChild(trendGrid);

    const bottomGrid = createElement("div", "analysis-grid");
    bottomGrid.appendChild(renderPathsPanel(scene));
    bottomGrid.appendChild(renderEventsPanel(scene, selected.date));
    dom.viewRoot.appendChild(bottomGrid);
  }

  function legacyRenderRecoveryView() {
    const family = state.recoveryFamily;
    const bundle = getSceneBundle(family);
    const scene = bundle.current;
    const selectedIndex = ensureSceneSelection(family, scene);
    const viewport = normalizeViewport(state.viewportByFamily[family], scene.daily.length, selectedIndex);
    state.viewportByFamily[family] = viewport;
    const selected = scene.daily[selectedIndex];
    const stage = resolveCurrentStage(scene, selected.date);

    const topGrid = createElement("div", "scene-top-grid");
    topGrid.appendChild(renderSceneSummaryPanel(scene, family, "恢复策略聚焦"));
    topGrid.appendChild(renderTimeControlPanel(scene, family, selected, stage));
    topGrid.appendChild(renderDetailPanel(scene, family, selected, stage));
    dom.viewRoot.appendChild(topGrid);

    dom.viewRoot.appendChild(renderRecoveryActionPanel(scene, family, stage, selected.date));

    const recoveryGrid = createElement("div", "trend-grid");
    recoveryTrendDefs.forEach((definition) => {
      const panel = createElement("article", "panel chart-panel");
      panel.append(createChartHead(definition.title, definition.note));
      panel.appendChild(renderLineChart(scene.daily, definition, selectedIndex, (index) => {
        state.selectedIndexByFamily[family] = index;
        state.viewportByFamily[family] = ensureViewportContains(viewport, scene.daily.length, index);
        stopPlay();
        renderApp();
      }, {
        navigator: true,
        ghostNavigator: true,
        windowed: true,
        windowStart: viewport.start,
        windowSize: viewport.size,
        onWindowChange: (start, size) => {
          stopPlay();
          state.viewportByFamily[family] = normalizeViewport(
            { start, size },
            scene.daily.length,
            state.selectedIndexByFamily[family]
          );
          renderApp();
        },
      }));
      panel.appendChild(renderLegend(definition.series));
      recoveryGrid.appendChild(panel);
    });
    dom.viewRoot.appendChild(recoveryGrid);

    const policyGrid = createElement("div", "analysis-grid full-width-analysis-grid");
    policyGrid.appendChild(renderPolicyComparisonPanel(scene, family, selectedIndex, viewport));
    dom.viewRoot.appendChild(policyGrid);

    const bottomGrid = createElement("div", "analysis-grid");
    bottomGrid.appendChild(renderEventsPanel(scene, selected.date));
    bottomGrid.appendChild(renderPathsPanel(scene));
    dom.viewRoot.appendChild(bottomGrid);
  }
  */

  function renderOverviewView() {
    const moduleKey = currentModule("overview");
    dom.viewRoot.appendChild(
      renderWorkspaceLayout(
        "overview",
        renderOverviewMain(moduleKey),
        null,
        "总控页面",
        "点击左侧功能块切换总览内容，页面保持单屏展示，不再纵向堆叠。"
      )
    );
  }

  function renderSceneView(family) {
    const bundle = getSceneBundle(family);
    const scene = bundle.current;
    const selectedIndex = ensureSceneSelection(family, scene);
    const viewport = normalizeViewport(state.viewportByFamily[family], scene.daily.length, selectedIndex);
    state.viewportByFamily[family] = viewport;
    const selected = scene.daily[selectedIndex];
    const stage = resolveCurrentStage(scene, selected.date);
    const moduleKey = currentModule(family);

    dom.viewRoot.appendChild(
      renderWorkspaceLayout(
        family,
        renderSceneMain(scene, family, stage, selected.date, selectedIndex, viewport, moduleKey),
        renderSceneAside(scene, family, selected, stage, moduleKey),
        `${scene.label}分析页`,
        "当前页面聚焦传播视角；左侧切换功能块，右侧保留时间控制与节点信息。"
      )
    );
  }

  function renderRecoveryView() {
    const family = state.recoveryFamily;
    const bundle = getSceneBundle(family);
    const scene = bundle.current;
    const selectedIndex = ensureSceneSelection(family, scene);
    const viewport = normalizeViewport(state.viewportByFamily[family], scene.daily.length, selectedIndex);
    state.viewportByFamily[family] = viewport;
    const selected = scene.daily[selectedIndex];
    const stage = resolveCurrentStage(scene, selected.date);
    const moduleKey = currentModule("recovery");

    dom.viewRoot.appendChild(
      renderWorkspaceLayout(
        "recovery",
        renderRecoveryMain(scene, family, stage, selected.date, selectedIndex, viewport, moduleKey),
        renderRecoveryAside(scene, family, selected, stage),
        "恢复动作页",
        "当前页面聚焦恢复动作；左侧切换恢复模块，中间只显示一个主功能块。"
      )
    );
  }

  function renderMapView() {
    ensureChinaMapLoaded();
    const family = state.recoveryFamily || families[0];
    const bundle = getSceneBundle(family);
    const scene = bundle.current;
    const selectedIndex = ensureSceneSelection(family, scene);
    state.viewportByFamily[family] = normalizeViewport(state.viewportByFamily[family], scene.daily.length, selectedIndex);
    const selected = scene.daily[selectedIndex];
    const stage = resolveCurrentStage(scene, selected.date);
    const current = resolveDailyNetworkState(scene.interactive_network?.daily_states || [], selected.date);

    const layout = createElement("div", "map-dashboard");
    layout.appendChild(renderChinaMapPanel(scene, family, selected.date, current));
    const aside = createElement("aside", "map-side-stack");
    aside.appendChild(renderTimeControlPanel(scene, family, selected, stage, { moduleKey: "map_display" }));
    aside.appendChild(renderMapStatsPanel(scene, family, selected, current));
    layout.appendChild(aside);
    dom.viewRoot.appendChild(layout);
  }

  function renderChinaMapPanel(scene, family, selectedDate, current) {
    const panel = createElement("section", "panel map-main-panel");
    const stage = createElement("div", "map-stage");
    stage.appendChild(renderChinaSupplierMapSvg(scene, family, selectedDate, current));
    stage.appendChild(renderMapLegend(scene, current));
    panel.appendChild(stage);
    return panel;
  }

  function renderMapStatsPanel(scene, family, selected, current) {
    const panel = createElement("section", "panel map-stat-panel");
    panel.append(createSectionHead("", "地图态势"));
    const stats = createElement("div", "detail-grid compact-detail-grid");
    stats.appendChild(detailCard("当前日期", formatDate(selected.date)));
    stats.appendChild(detailCard("当前情境", scene.label || baseScenes[family].label));
    stats.appendChild(detailCard("中断供应商", formatInteger(selected.supplier_disrupted_nodes)));
    stats.appendChild(detailCard("恢复动作", formatInteger(Number(selected.active_backup_switches || 0) + Number(selected.active_substitutions || 0) + Number(selected.active_priority_repairs || 0))));
    panel.appendChild(stats);
    panel.appendChild(renderMapSupplierList(scene, current));
    return panel;
  }

  function renderMapSupplierList(scene, current) {
    const list = createElement("div", "map-supplier-list");
    const rows = supplierMapRows(scene, current)
      .filter((row) => row.isKey || isDisruptedStatus(row.status))
      .sort((left, right) => mapStatusRank(right.status) - mapStatusRank(left.status) || Number(right.isKey) - Number(left.isKey) || left.name.localeCompare(right.name, "zh-Hans-CN"));
    if (!rows.length) {
      list.appendChild(createElement("div", "empty-note", "当前日期没有异常供应商。"));
      return list;
    }
    rows.forEach((row) => {
      const item = createElement("article", "map-supplier-card");
      const dot = createElement("span", `map-dot ${mapStatusClass(row.status)}`);
      const copy = createElement("div");
      copy.appendChild(createElement("strong", "", row.name));
      copy.appendChild(createElement("small", "", `${translateVisualStatus(row.status)} · ${formatNumber(row.latitude)}, ${formatNumber(row.longitude)}`));
      item.append(dot, copy);
      list.appendChild(item);
    });
    return list;
  }

  function ensureChinaMapLoaded() {
    if (state.chinaGeoJson || state.chinaMapLoading || state.chinaMapError) {
      return;
    }
    state.chinaMapLoading = true;
    fetch(CHINA_MAP_ASSET, { cache: "force-cache" })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`China map asset failed: ${response.status}`);
        }
        return response.json();
      })
      .then((payload) => {
        state.chinaGeoJson = payload;
        state.chinaMapError = "";
      })
      .catch(() => {
        state.chinaMapError = "完整中国地图静态资源加载失败";
      })
      .finally(() => {
        state.chinaMapLoading = false;
        renderApp();
      });
  }

  function renderChinaSupplierMapSvg(scene, family, selectedDate, current) {
    const width = 1120;
    const height = 660;
    const svg = createSvg(width, height, "china-map-svg");
    const project = (longitude, latitude) => projectChinaPoint(longitude, latitude, width, height);
    const bg = createSvgElement("rect", { x: 0, y: 0, width, height, rx: 18, fill: "#F8FAFC" });
    svg.appendChild(bg);

    const mapGroup = createSvgElement("g", { class: "china-map-layer" });
    svg.appendChild(mapGroup);
    if (!state.chinaGeoJson) {
      const message = state.chinaMapError || "正在加载完整中国地图";
      mapGroup.appendChild(createSvgElement("text", {
        x: width / 2,
        y: height / 2,
        "text-anchor": "middle",
        fill: "#111827",
        "font-size": 22,
        "font-weight": 700,
      }, message));
      return svg;
    }

    appendChinaGeoJsonMap(mapGroup, state.chinaGeoJson, project);

    const rows = supplierMapRows(scene, current);
    const rowById = new Map(rows.map((row) => [row.supplierId, row]));
    const nodeByKey = new Map((scene.interactive_network?.nodes || []).map((node) => [node.node_key, node]));
    (scene.interactive_network?.edges || []).forEach((edge) => {
      if (edge.edge_type !== "supplier_network") {
        return;
      }
      const source = nodeByKey.get(edge.source_key);
      const target = nodeByKey.get(edge.target_key);
      const sourceRow = rowById.get(String(source?.entity_id || ""));
      const targetRow = rowById.get(String(target?.entity_id || ""));
      if (!sourceRow || !targetRow) {
        return;
      }
      const sourcePoint = project(sourceRow.longitude, sourceRow.latitude);
      const targetPoint = project(targetRow.longitude, targetRow.latitude);
      const edgeStatus = String((current.edge_status || {})[edge.edge_key] || "active");
      const style = edgeStyle(edgeStatus);
      mapGroup.appendChild(createSvgElement("line", {
        x1: sourcePoint.x,
        y1: sourcePoint.y,
        x2: targetPoint.x,
        y2: targetPoint.y,
        stroke: style.stroke,
        "stroke-width": Math.max(style.width, edgeStatus === "disrupted" ? 2 : 1),
        "stroke-dasharray": style.dash,
        opacity: edgeStatus === "disrupted" ? 0.72 : 0.18,
      }));
    });

    rows.forEach((row) => {
      const point = project(row.longitude, row.latitude);
      const group = createSvgElement("g", { class: "map-node", transform: `translate(${point.x},${point.y})` });
      group.appendChild(createSvgElement("circle", {
        cx: 0,
        cy: 0,
        r: row.isKey ? 8.5 : 6.5,
        fill: mapStatusColor(row.status),
        stroke: row.isKey ? "#111827" : "#FFFFFF",
        "stroke-width": row.isKey ? 2.6 : 1.8,
      }));
      if (isDisruptedStatus(row.status) || row.isKey) {
        group.appendChild(createSvgElement("text", {
          x: 11,
          y: 4,
          fill: "#0F172A",
          "font-size": 11,
          "font-weight": 700,
        }, shortDisplayName(row.name, 9)));
      }
      group.appendChild(createSvgElement("title", {}, `${row.name} · ${translateVisualStatus(row.status)} · ${formatDate(selectedDate)}`));
      mapGroup.appendChild(group);
    });
    return svg;
  }

  function appendChinaGeoJsonMap(mapGroup, geoJson, project) {
    const features = Array.isArray(geoJson?.features) ? geoJson.features : [];
    features.forEach((feature) => {
      geometryToSvgPaths(feature.geometry, project).forEach((pathData) => {
        if (!pathData) {
          return;
        }
        mapGroup.appendChild(createSvgElement("path", {
          d: pathData,
          class: "china-map-feature",
          fill: "#FFFFFF",
          stroke: "#111827",
          "stroke-width": 0.9,
          "vector-effect": "non-scaling-stroke",
        }));
      });
    });
  }

  function geometryToSvgPaths(geometry, project) {
    if (!geometry) {
      return [];
    }
    if (geometry.type === "Polygon") {
      return [polygonToSvgPath(geometry.coordinates, project)];
    }
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates.map((polygon) => polygonToSvgPath(polygon, project));
    }
    if (geometry.type === "GeometryCollection") {
      return (geometry.geometries || []).flatMap((item) => geometryToSvgPaths(item, project));
    }
    return [];
  }

  function polygonToSvgPath(rings, project) {
    return (rings || [])
      .map((ring) =>
        (ring || [])
          .map((position, index) => {
            const point = project(position[0], position[1]);
            return `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
          })
          .join(" ") + " Z"
      )
      .join(" ");
  }

  function supplierMapRows(scene, current) {
    const geoNodes = Array.isArray(dashboardData?.supplier_geo_nodes) ? dashboardData.supplier_geo_nodes : [];
    const nodeByEntity = new Map((scene.interactive_network?.nodes || []).map((node) => [String(node.entity_id || ""), node]));
    return geoNodes
      .map((item) => {
        const supplierId = String(item.supplier_id || "").trim();
        const node = nodeByEntity.get(supplierId);
        const status = String((current.node_status || {})[`supplier:${supplierId}`] || "available");
        return {
          supplierId,
          name: String(item.supplier_name || formatEntityName(supplierId, scene)),
          latitude: Number(item.latitude),
          longitude: Number(item.longitude),
          isKey: Boolean(item.is_key_node || node?.is_key_node),
          status,
        };
      })
      .filter((row) => row.supplierId && Number.isFinite(row.latitude) && Number.isFinite(row.longitude));
  }

  function projectChinaPoint(longitude, latitude, width, height) {
    const minLon = 73;
    const maxLon = 135;
    const minLat = 18;
    const maxLat = 54;
    return {
      x: 56 + ((Number(longitude) - minLon) / (maxLon - minLon)) * (width - 112),
      y: 44 + ((maxLat - Number(latitude)) / (maxLat - minLat)) * (height - 88),
    };
  }

  function mapStatusRank(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "disrupted" || normalized === "blocked") return 4;
    if (normalized === "recovering") return 3;
    if (normalized === "affected" || normalized === "degraded") return 2;
    return 1;
  }

  function mapStatusClass(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "disrupted" || normalized === "blocked") return "danger";
    if (normalized === "recovering") return "recovering";
    if (normalized === "affected" || normalized === "degraded") return "warning";
    return "normal";
  }

  function mapStatusColor(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "disrupted" || normalized === "blocked") return "#B91C1C";
    if (normalized === "recovering") return "#2563EB";
    if (normalized === "affected" || normalized === "degraded") return "#D97706";
    return "#0F766E";
  }

  function renderMapLegend(scene, current) {
    const legend = createElement("div", "map-legend");
    const presentTypes = new Set(supplierMapRows(scene, current).map((row) => mapStatusClass(row.status)));
    const items = [
      ["normal", "正常供应商"],
      ["warning", "受影响供应商"],
      ["danger", "中断供应商"],
      ["recovering", "恢复中供应商"],
    ].filter(([type]) => presentTypes.has(type));
    (items.length ? items : [["normal", "正常供应商"]]).forEach(([type, label]) => {
      const item = createElement("span", "map-legend-item");
      item.append(createElement("span", `map-dot ${type}`), createElement("span", "", label));
      legend.appendChild(item);
    });
    return legend;
  }

  function currentModule(pageKey = state.page) {
    const defs = pageModuleDefs[pageKey] || [];
    if (!defs.length) {
      return null;
    }
    const current = state.subViewByPage[pageKey];
    if (defs.some((item) => item.key === current)) {
      return current;
    }
    state.subViewByPage[pageKey] = defs[0].key;
    return defs[0].key;
  }

  /*
   * Inactive legacy workspace shell. The active renderWorkspaceLayout
   * definition lives later in the file.
   *
  function renderWorkspaceLayoutLegacy(pageKey, mainNode, asideNodes, title, note) {
    const moduleKey = currentModule(pageKey);
    const layout = createElement("div", "workspace-layout");
    layout.classList.add(`page-${pageKey}`, `module-${moduleKey || "default"}`);
    const sidebar = createElement("aside", "panel workspace-sidebar");
    sidebar.appendChild(renderModuleSidebar(pageKey));

    const center = createElement("section", "workspace-center");
    center.appendChild(renderWorkspaceHeader(title || pageLabel(pageKey), note || ""));

    const main = createElement("section", "workspace-main");
    main.classList.add(`module-${moduleKey || "default"}`);
    if (mainNode) {
      main.appendChild(mainNode);
    }
    center.appendChild(main);

    const aside = createElement("aside", "workspace-aside");
    aside.classList.add(`module-${moduleKey || "default"}`);
    const items = Array.isArray(asideNodes) ? asideNodes : [asideNodes];
    items.filter(Boolean).forEach((item) => aside.appendChild(item));

    layout.append(sidebar, center, aside);
    return layout;
  }
  */

  function renderWorkspaceHeader(title, note) {
    const header = createElement("section", "panel workspace-main-header");
    const copy = createElement("div", "workspace-main-header-copy");
    copy.appendChild(createElement("h2", "workspace-main-title", title || "模块"));
    header.appendChild(copy);
    return header;
  }

  function renderModuleSidebar(pageKey) {
    const defs = pageModuleDefs[pageKey] || [];
    const wrapper = createElement("div", "workspace-nav-list");
    defs.forEach((definition) => {
      const button = createElement("button", "workspace-nav-button", definition.label);
      if (currentModule(pageKey) === definition.key) {
        button.classList.add("active");
        button.style.background = pageAccent(pageKey === "overview" ? "overview" : pageKey);
      }
      button.addEventListener("click", () => {
        state.subViewByPage[pageKey] = definition.key;
        renderApp();
      });
      wrapper.appendChild(button);
    });
    return wrapper;
  }

  function pageLabel(pageKey) {
    return pageDefs.find((item) => item.key === pageKey)?.label || pageKey;
  }

  function createBalancedStack(...nodes) {
    const items = nodes.flat().filter(Boolean);
    const stack = createElement("div", "workspace-main-stack");
    stack.classList.add(`stack-count-${Math.min(Math.max(items.length, 1), 4)}`);
    items.forEach((item) => stack.appendChild(item));
    return stack;
  }

  function createAsideStack(...nodes) {
    const items = nodes.flat().filter(Boolean);
    const stack = createElement("div", "workspace-stack");
    stack.classList.add(`stack-count-${Math.min(Math.max(items.length, 1), 4)}`);
    items.forEach((item) => stack.appendChild(item));
    return stack;
  }

  /*
   * Inactive legacy overview module router. The active renderOverviewMain
   * definition lives at the end of the overview section.
   *
  function renderOverviewMainLegacy(moduleKey) {
    switch (moduleKey) {
      case "metric_compare":
        return createBalancedStack(renderOverviewComparePanel(), renderOverviewMonthlyPanel());
      case "stage_timeline":
        return createBalancedStack(renderOverviewTimelinePanel(), renderOverviewDurationPanel());
      case "monthly_distribution":
        return createBalancedStack(renderOverviewMonthlyPanel(), renderOverviewDurationPanel());
      case "duration_compare":
        return createBalancedStack(renderOverviewDurationPanel(), renderOverviewTimelinePanel());
      case "scene_summary":
      default:
        return createBalancedStack(renderOverviewScenePanel(), renderOverviewComparePanel());
    }
  }
  */

  /*
   * Inactive duplicate: final renderOverviewAside definition lives later.
   *
  function renderOverviewAside(moduleKey) {
    const status = createElement("section", "panel aside-detail-panel");
    status.append(createSectionHead("", "系统状态"));
    const statusGrid = createElement("div", "compact-detail-grid");
    statusGrid.appendChild(detailCard("推演服务", state.apiAvailable ? "已连接" : "未连接"));
    statusGrid.appendChild(detailCard("接口版本", state.apiContractVersion || "-"));
    status.appendChild(statusGrid);

    const jump = createElement("section", "panel aside-entry-panel");
    jump.append(createSectionHead("", "快速进入"));
    const buttons = createElement("div", "workspace-link-grid");
    ["random", "keynode", "recovery", "map"].forEach((pageKey) => {
      const button = createElement("button", "scene-pill", pageLabel(pageKey));
      button.style.background = pageAccent(pageKey);
      button.style.color = "#fff";
      button.addEventListener("click", () => {
        state.page = pageKey;
        renderApp();
      });
      buttons.appendChild(button);
    });
    jump.appendChild(buttons);
    return createAsideStack(status, jump);
  }
  */

  function overviewModuleNote(moduleKey) {
    if (moduleKey === "scene_summary") return "查看两种情境的入口摘要，并快速跳转到对应分析页。";
    if (moduleKey === "metric_compare") return "集中比较恢复天数、平均服务水平、系统服务水平、策略成本与预计中断损失。";
    if (moduleKey === "stage_timeline") return "按阶段列出两种情境下关键网络快照时间点。";
    if (moduleKey === "monthly_distribution") return "查看月度中断节点的峰值变化，适合做演示中的宏观趋势说明。";
    return "查看供应商层、物料层、装配层、产品层的传播持续月数。";
  }

  function renderOverviewScenePanel() {
    const panel = createElement("section", "panel overview-panel overview-scene-panel");
    const cards = createElement("div", "scene-card-grid");
    families.forEach((family) => {
      cards.appendChild(buildSceneSummaryCard(baseScenes[family]));
    });
    panel.appendChild(cards);
    return panel;
  }

  /*
   * Inactive duplicate: final renderOverviewComparePanel definition lives later.
   *
  function renderOverviewComparePanel() {
    const panel = createElement("section", "panel overview-panel overview-compare-panel");
    panel.append(createSectionHead("", "关键结果对比"));
    const compareGrid = createElement("div", "compare-grid");
    [
      ["恢复天数", "ttr_days", "days"],
      ["平均服务水平", "average_service_level", "percent"],
      ["系统服务水平", "avg_system_service_level", "percent"],
      ["策略总成本", "policy_total_cost", "currency"],
      ["预计中断损失", "estimated_disruption_loss", "currency"],
    ].forEach(([label, key, mode]) => {
      const randomValue = baseScenes.random.summary[key];
      const keynodeValue = baseScenes.keynode.summary[key];
      const card = createElement("article", "compare-card");
      card.appendChild(createElement("span", "", label));
      card.appendChild(createElement("strong", "", `${baseScenes.random.label}：${formatByMode(randomValue, mode)}`));
      card.appendChild(createElement("em", "", `${baseScenes.keynode.label}：${formatByMode(keynodeValue, mode)}`));
      compareGrid.appendChild(card);
    });
    panel.appendChild(compareGrid);
    return panel;
  }
  */

  function renderOverviewTimelinePanel() {
    const panel = createElement("section", "panel overview-panel overview-timeline-panel");
    panel.append(createSectionHead("", "关键阶段时间线"));
    const timelineGrid = createElement("div", "stage-compare-grid");
    families.forEach((family) => {
      const card = createElement("article", "network-copy-card");
      card.appendChild(createElement("p", "eyebrow", baseScenes[family].label));
      (baseScenes[family].network_snapshots || []).forEach((snapshot) => {
        const row = createElement("div", "stage-row");
        row.appendChild(createElement("strong", "", stageDisplayTitle(snapshot)));
        row.appendChild(createElement("small", "", formatDate(snapshot.snapshot_date)));
        card.appendChild(row);
      });
      timelineGrid.appendChild(card);
    });
    panel.appendChild(timelineGrid);
    return panel;
  }

  function renderOverviewMonthlyPanel() {
    const panel = createElement("section", "panel overview-panel overview-monthly-panel");
    panel.append(createSectionHead("", "月度中断节点分布"));
    const monthlyGrid = createElement("div", "mini-chart-grid");
    const monthlyRowsByFamily = Object.fromEntries(
      families.map((family) => [family, baseScenes[family].monthly_disrupted || []])
    );
    const sharedMonths = Array.from(
      new Set(families.flatMap((family) => monthlyRowsByFamily[family].map((row) => String(row.month || ""))))
    ).filter(Boolean).sort();
    const sharedMonthlyMax = Math.max(
      1,
      ...families.flatMap((family) => monthlyRowsByFamily[family].map((row) => Number(row.total_disrupted_nodes || 0)))
    );
    families.forEach((family) => {
      const card = createElement("article", "panel chart-panel compact-panel workspace-chart-panel");
      card.appendChild(createElement("h3", "", baseScenes[family].label));
      card.appendChild(renderMonthlyChart(monthlyRowsByFamily[family], {
        months: sharedMonths,
        maxValue: sharedMonthlyMax,
      }));
      monthlyGrid.appendChild(card);
    });
    panel.appendChild(monthlyGrid);
    return panel;
  }

  function renderOverviewDurationPanel() {
    const panel = createElement("section", "panel overview-panel overview-duration-panel");
    panel.append(createSectionHead("", "传播时长对比"));
    const durationGrid = createElement("div", "mini-chart-grid");
    families.forEach((family) => {
      const card = createElement("article", "panel chart-panel compact-panel workspace-chart-panel");
      card.appendChild(createElement("h3", "", overviewDurationTitle(family, baseScenes[family])));
      card.appendChild(renderHorizontalBars(baseScenes[family].propagation_durations || [], {
        labelKey: "label",
        valueKey: "duration_months",
        color: baseScenes[family].accent,
        formatter: (value) => `${formatInteger(value)} 个月`,
      }));
      durationGrid.appendChild(card);
    });
    panel.appendChild(durationGrid);
    return panel;
  }

  function renderSceneMain(scene, family, stage, selectedDate, selectedIndex, viewport, moduleKey) {
    if (moduleKey === "dynamic_network") {
      const panel = createElement("section", "panel workspace-main-panel");
      panel.append(createSectionHead("", "传播过程网络"));
      panel.appendChild(renderSharedNetworkVisual(scene, family, selectedDate, { mode: "propagation", stage }));
      return panel;
    }
    if (moduleKey === "supply_propagation") {
      return createBalancedStack(
        renderTrendPanel(scene, family, sceneTrendDefs[2], selectedIndex, viewport, {
        title: "供给传播",
        note: "聚焦供应商节点和供应关系边的传播变化。",
        short: true,
      }),
        renderTrendPanel(scene, family, sceneTrendDefs[1], selectedIndex, viewport, {
        title: "供给与需求冲击",
        note: "用来对照供给端中断在需求侧形成的冲击变化。",
        short: true,
      })
      );
    }
    if (moduleKey === "demand_propagation") {
      return createBalancedStack(
        renderTrendPanel(scene, family, sceneTrendDefs[1], selectedIndex, viewport, {
        title: "供给与需求冲击",
        note: "展示需求积压、损失与供给中断叠加影响。",
        short: true,
      }),
        renderTrendPanel(scene, family, sceneTrendDefs[3], selectedIndex, viewport, {
        title: "需求传播与下游阻断",
        note: "突出物料、装配件和产品阻断的下游扩散。",
        short: true,
      })
      );
    }
    if (moduleKey === "node_simulation") {
      const panel = createElement("section", "panel workspace-main-panel");
      panel.append(createChartHead("节点中断推演器", "单击节点加入推演集合，双击节点立即生成新的动态推演结果。"));
      panel.appendChild(renderSharedNetworkVisual(scene, family, selectedDate, { mode: "propagation", stage }));
      return panel;
    }

    return createBalancedStack(
      renderTrendPanel(scene, family, sceneTrendDefs[0], selectedIndex, viewport, {
      title: "服务水平与需求履约",
      note: "聚焦服务水平、需求满足率与系统服务水平的恢复轨迹。",
      short: true,
    }),
      renderTrendPanel(scene, family, sceneTrendDefs[1], selectedIndex, viewport, {
      title: "供给与需求冲击",
      note: "集中展示不可用物料、积压需求与损失需求的变化。",
      short: true,
    })
    );
  }

  function renderSceneAside(scene, family, selected, stage, moduleKey) {
    const items = [
      renderSceneSummaryPanel(scene, family, "情境摘要"),
      renderTimeControlPanel(scene, family, selected, stage, { moduleKey }),
    ];

    if (moduleKey === "dynamic_network") {
      items.push(renderPropagationResultCard(scene, family, stage, selected, selected.date));
      items.push(renderFocusedNodeCard(family));
    } else if (moduleKey === "node_simulation") {
      items.push(renderFocusedNodeCard(family));
      items.push(renderConfiguratorCard(family));
    } else {
      items.push(renderDetailPanel(scene, family, selected, stage, { includeFocus: false }));
      items.push(renderFocusedNodeCard(family));
    }

    const stack = createAsideStack(items);
    stack.classList.add(`aside-stack-${moduleKey || "default"}`);
    return stack;
  }

  function renderRecoveryMain(scene, family, stage, selectedDate, selectedIndex, viewport, moduleKey) {
    if (moduleKey === "recovery_network") {
      const panel = createElement("section", "panel workspace-main-panel");
      panel.append(createSectionHead("", "恢复动作网络"));
      panel.appendChild(renderSharedNetworkVisual(scene, family, selectedDate, { mode: "recovery", stage }));
      return panel;
    }
    if (moduleKey === "policy_compare") {
      return renderPolicyComparisonPanel(scene, family, selectedIndex, viewport);
    }
    if (moduleKey === "impact_paths") {
      return createBalancedStack(
        renderEventsPanel(scene, selectedDate),
        renderPathsPanel(scene)
      );
    }

    return createBalancedStack(
      renderTrendPanel(scene, family, recoveryTrendDefs[0], selectedIndex, viewport, {
      title: "恢复动作激活轨迹",
      note: "按日期跟踪三类恢复动作的累计激活数量。",
      short: true,
    }),
      renderTrendPanel(scene, family, recoveryTrendDefs[1], selectedIndex, viewport, {
      title: "策略累计成本",
      note: "展示策略执行后的累计成本上升轨迹。",
      short: true,
    })
    );
  }

  /* Legacy duplicate recovery aside renderer disabled; final definition is below. */

  function renderTrendPanel(scene, family, definition, selectedIndex, viewport, options = {}) {
    const panel = createElement("section", "panel chart-panel workspace-chart-panel");
    if (options.short) {
      panel.classList.add("short-panel");
    }
    panel.append(createChartHead(options.title || definition.title, options.note || definition.note || ""));
    panel.appendChild(renderLineChart(
      scene.daily,
      definition,
      selectedIndex,
      (index) => selectSceneDate(family, scene.daily.length, index),
      {
        navigator: true,
        ghostNavigator: true,
        windowed: true,
        compact: options.compact !== false,
        ultraCompact: Boolean(options.ultraCompact),
        windowStart: viewport.start,
        windowSize: viewport.size,
        onWindowChange: (start, size) => updateSceneViewport(family, scene.daily.length, start, size),
      }
    ));
    panel.appendChild(renderLegend(definition.series));
    return panel;
  }

  function selectSceneDate(family, total, index) {
    state.selectedIndexByFamily[family] = clamp(index, 0, Math.max(total - 1, 0));
    state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], total, state.selectedIndexByFamily[family]);
    stopPlay();
    renderApp();
  }

  function updateSceneViewport(family, total, start, size) {
    stopPlay();
    state.viewportByFamily[family] = normalizeViewport(
      { start, size },
      total,
      state.selectedIndexByFamily[family]
    );
    renderApp();
  }

  /*
   * Inactive duplicate: final renderSceneSummaryPanel definition lives later.
   *
  function renderSceneSummaryPanel(scene, family, eyebrowText) {
    const panel = createElement("section", "panel scene-summary-panel aside-summary-panel");
    panel.append(createSectionHead(eyebrowText || "", `${scene.label || baseScenes[family].label}`));
    const meta = createElement("div", "scene-meta");
    meta.appendChild(metaItem("情境名称", scene.scenario.scenario_name || scene.scenario.scenario_id || "-"));
    meta.appendChild(metaItem("开始日期", formatDate(scene.scenario.start_date)));
    meta.appendChild(metaItem("持续天数", `${scene.scenario.duration_days || 0} 天`));
    meta.appendChild(metaItem("严重度", formatNumber(scene.scenario.severity)));
    panel.appendChild(meta);
    const kpis = createElement("div", "scene-kpis");
    kpis.appendChild(kpiMini("业务恢复", `${scene.summary.ttr_days ?? "-"} 天`));
    kpis.appendChild(kpiMini("平均服务水平", formatPercent(scene.summary.average_service_level)));
    kpis.appendChild(kpiMini("策略总成本", formatCurrency(scene.summary.policy_total_cost)));
    panel.appendChild(kpis);
    return panel;
  }
  */

  function controlSnapshotsForModule(scene, moduleKey) {
    const snapshots = Array.isArray(scene?.network_snapshots) ? scene.network_snapshots.filter(Boolean) : [];
    const filtered = snapshots.filter((snapshot) => String(snapshot?.snapshot_name || "") !== "t0");
    return filtered.length ? filtered : snapshots;
  }

  /*
   * Inactive duplicate: final renderTimeControlPanel definition lives later.
   *
  function renderTimeControlPanel(scene, family, selected, stage, options = {}) {
    const moduleKey = String(options.moduleKey || "");
    const panel = createElement("section", "panel process-panel aside-control-panel");
    panel.append(createSectionHead("", "动态过程控制"));
    const controller = createElement("div", "timeline-controller");
    const selectedIndex = state.selectedIndexByFamily[family] || 0;
    const progressPercent = scene.daily.length > 1 ? (selectedIndex / (scene.daily.length - 1)) * 100 : 0;

    const slider = createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = String(Math.max(scene.daily.length - 1, 0));
    slider.step = "1";
    slider.value = String(state.selectedIndexByFamily[family]);
    slider.addEventListener("input", (event) => {
      stopPlay();
      state.selectedIndexByFamily[family] = Number(event.target.value || 0);
      state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], scene.daily.length, state.selectedIndexByFamily[family]);
      renderApp();
    });
    controller.appendChild(slider);

    const controls = createElement("div", "timeline-action-row");
    if (["process_overview", "propagation_statistics", "supply_propagation", "demand_propagation", "dynamic_network", "node_simulation"].includes(moduleKey)) {
      controls.classList.add("timeline-action-row-single");
    }
    const playButton = createElement("button", "ghost-button", state.playingFamily === family ? "暂停过程" : "播放过程");
    playButton.addEventListener("click", () => togglePlay(family));
    controls.appendChild(playButton);
    controlSnapshotsForModule(scene, moduleKey).forEach((snapshot) => {
      const button = createElement("button", "stage-chip", stageShortLabel(snapshot));
      if (snapshot.snapshot_name === stage.snapshot_name) {
        button.classList.add("active");
        button.style.background = scene.accent;
      }
      button.addEventListener("click", () => {
        const targetIndex = scene.daily.findIndex((row) => row.date === snapshot.snapshot_date);
        if (targetIndex >= 0) {
          stopPlay();
          state.selectedIndexByFamily[family] = targetIndex;
          state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], scene.daily.length, targetIndex);
          renderApp();
        }
      });
      controls.appendChild(button);
    });
    controller.appendChild(controls);

    const meta = createElement("div", "timeline-meta");
    meta.appendChild(detailCard("当前日期", formatDate(selected.date)));
    meta.appendChild(detailCard("当前阶段", stageShortLabel(stage) || "未识别阶段"));
    meta.appendChild(detailCard("过程进度", `${Math.round(progressPercent)}%`));
    panel.appendChild(controller);
    panel.appendChild(meta);
    panel.appendChild(createElement("div", "stage-caption", buildStageCaption(stage, scene)));
    return panel;
  }
  */

  function renderDetailPanel(scene, family, selected, stage, options = {}) {
    const { includeFocus = true } = options;
    const panel = createElement("section", "panel detail-panel aside-detail-panel");
    panel.append(createSectionHead("", `${formatDate(selected.date)} 详细信息`));
    const grid = createElement("div", "detail-grid");
    grid.appendChild(detailCard("产品服务水平", formatPercent(selected.service_level)));
    grid.appendChild(detailCard("需求满足率", formatPercent(selected.demand_fulfillment_rate)));
    grid.appendChild(detailCard("系统服务水平", formatPercent(selected.system_service_level)));
    grid.appendChild(detailCard("中断供应商", formatInteger(selected.supplier_disrupted_nodes)));
    grid.appendChild(detailCard("阻断物料", formatInteger(selected.material_blocked_nodes)));
    grid.appendChild(detailCard("阻断装配件", formatInteger(selected.assembly_blocked_nodes)));
    grid.appendChild(detailCard("阻断产品", formatInteger(selected.product_blocked_nodes)));
    grid.appendChild(detailCard("累计策略成本", formatCurrency(selected.policy_cumulative_cost)));
    panel.appendChild(grid);

    const focus = state.focusNodeByFamily[family];
    if (includeFocus && focus) {
      const focusPanel = createElement("div", "network-copy-card");
      focusPanel.appendChild(createElement("h3", "", "当前选中节点"));
      const focusGrid = createElement("div", "detail-grid");
      focusGrid.appendChild(detailCard("节点名称", formatEntityName(focus.entity_id, scene)));
      focusGrid.appendChild(detailCard("节点类型", translateNodeType(focus.node_type)));
      focusGrid.appendChild(detailCard("节点状态", translateVisualStatus(focus.visual_status)));
      focusGrid.appendChild(detailCard("关键节点", focus.is_key_node ? "是" : "否"));
      focusPanel.appendChild(focusGrid);
      panel.appendChild(focusPanel);
    }
    return panel;
  }

  function renderConfiguratorCard(family) {
    const selectedNodes = getSelectedNodes(family);
    const scene = getSceneBundle(family).current;
    const card = createElement("div", "network-copy-card configurator-card aside-config-panel");
    card.appendChild(createElement("h3", "", "节点中断推演"));

    const selectedGrid = createElement("div", "detail-grid compact-detail-grid");
    selectedGrid.appendChild(detailCard("已选数量", `${selectedNodes.length} 个`));
    selectedGrid.appendChild(detailCard("已选节点", selectedNodes.length ? selectedNodes.map((node) => formatNodeName(node, scene)).join("、") : "未选择"));
    selectedGrid.appendChild(detailCard("关键节点数", formatInteger(selectedNodes.filter((node) => node.is_key_node).length)));
    selectedGrid.appendChild(detailCard("恢复策略", "等效替代、备供切换、优先抢修"));
    card.appendChild(selectedGrid);

    const actions = createElement("div", "selector-action-row");
    const startButton = createElement("button", "ghost-button", state.isSubmittingWhatIf ? "正在执行推演…" : "生成动态推演");
    startButton.disabled = state.isSubmittingWhatIf || !state.apiAvailable || !selectedNodes.length;
    startButton.addEventListener("click", () => triggerWhatIf(family));
    const clearButton = createElement("button", "scene-pill", "清空选择");
    clearButton.disabled = !selectedNodes.length;
    clearButton.addEventListener("click", () => {
      state.selectedNodeByFamily[family] = [];
      state.focusNodeByFamily[family] = null;
      renderApp();
    });
    const backButton = createElement("button", "scene-pill", "返回基准");
    backButton.addEventListener("click", () => {
      state.resultModeByFamily[family] = "baseline";
      renderApp();
    });
    actions.append(startButton, clearButton, backButton);
    card.appendChild(actions);

    if (!state.apiAvailable) {
      card.appendChild(createElement("small", "", "如需实时生成节点推演，请先启动本地服务。"));
    } else if (!selectedNodes.length) {
      card.appendChild(createElement("small", "", `请先在左侧网络图中选择节点；${selectionRuleText(family)}`));
    } else {
      card.appendChild(createElement("small", "", state.apiMessage || "已连接本地推演服务，可继续生成新的动态推演。"));
    }
    return card;
  }

  function renderScenarioNetworkLegend(mode = "propagation") {
    const legend = createElement("div", "network-legend");
    const items = mode === "recovery"
      ? [
          ["line", "#277DA1", "备供切换边"],
          ["line", "#8E44AD", "等效替代边"],
          ["node", "#60A5FA", "恢复中的节点"],
          ["outline", "#0F766E", "已恢复节点"],
          ["outline", "#FF2DAA", "关键节点边框"],
          ["node", "#9A3412", "仍未恢复节点"],
        ]
      : [
          ["node", "#22C55E", "可用节点"],
          ["node", "#FFB703", "受影响节点"],
          ["node", "#9A3412", "中断/阻断节点"],
          ["line", "#C1121F", "中断边"],
          ["line", "#277DA1", "备供切换边"],
          ["line", "#8E44AD", "等效替代边"],
          ["outline", "#FF2DAA", "关键节点边框"],
        ];
    items.forEach(([type, color, label]) => {
      const item = createElement("span", "network-legend-item");
      const mark = createElement("span", `network-legend-mark ${type}`);
      if (type === "outline") {
        mark.style.borderColor = color;
      } else {
        mark.style.background = color;
      }
      item.append(mark, createElement("span", "", label));
      legend.appendChild(item);
    });
    return legend;
  }

  function renderSharedNetworkVisual(scene, family, selectedDate, options = {}) {
    const mode = options.mode || "propagation";
    const layoutKey = sceneLayoutKey(family);
    const visual = createElement("div", `network-visual ${mode === "recovery" ? "recovery-visual" : "propagation-visual"}`);
    if (scene.interactive_network && scene.interactive_network.daily_states && scene.interactive_network.daily_states.length) {
      const controlBar = createElement("div", "network-control-bar");
      const toolbar = createElement("div", "network-toolbar");
      const zoomOut = createElement("button", "scene-pill", "缩小");
      zoomOut.addEventListener("click", () => adjustNetworkZoom(family, -0.12));
      const zoomIn = createElement("button", "scene-pill", "放大");
      zoomIn.addEventListener("click", () => adjustNetworkZoom(family, 0.12));
      const resetViewButton = createElement("button", "scene-pill", "重置视角");
      resetViewButton.addEventListener("click", () => {
        state.networkViewByFamily[family] = { scale: 1, panX: 0, panY: 0 };
        renderApp();
      });
      const resetButton = createElement("button", "scene-pill", "重置布局");
      resetButton.addEventListener("click", () => {
        state.layoutOverridesByScene[layoutKey] = {};
        renderApp();
      });
      const clearFocus = createElement("button", "scene-pill", "清除聚焦");
      clearFocus.addEventListener("click", () => {
        state.focusNodeByFamily[family] = null;
        renderApp();
      });
      toolbar.append(zoomOut, zoomIn, resetViewButton, resetButton, clearFocus);

      const filterRow = createElement("div", "network-filter-row");
      const filters = mode === "recovery" ? recoveryNetworkFilterOptions() : networkFilterOptions();
      const activeFilter = mode === "recovery" ? state.recoveryFilterByFamily[family] : state.networkFilterByFamily[family];
      filters.forEach((filter) => {
        const button = createElement("button", "metric-chip", filter.label);
        if (activeFilter === filter.value) {
          button.classList.add("active");
          button.style.background = baseScenes[family].accent;
        }
        button.addEventListener("click", () => {
          if (mode === "recovery") {
            state.recoveryFilterByFamily[family] = filter.value;
          } else {
            state.networkFilterByFamily[family] = filter.value;
          }
          renderApp();
        });
        filterRow.appendChild(button);
      });
      controlBar.append(toolbar, filterRow);
      visual.appendChild(controlBar);
      visual.appendChild(renderScenarioNetworkLegend(mode));
      visual.appendChild(renderDynamicNetwork(scene.interactive_network, selectedDate, family, { mode, scene }));
      return visual;
    }

    const stage = options.stage || {};
    if (stage.figure_path) {
      const img = createElement("img");
      img.src = stage.figure_path;
      img.alt = stageDisplayTitle(stage) || (mode === "recovery" ? "恢复动作网络" : "传播过程网络");
      visual.appendChild(img);
      return visual;
    }

    visual.appendChild(createElement("div", "empty-note", "当前情境暂无可展示网络。"));
    return visual;
  }

  function renderScenarioNetworkPanel(scene, family, stage, selectedDate) {
    const panel = createElement("section", "panel network-panel propagation-network-panel");
    panel.append(createSectionHead("", "传播过程网络"));
    const layout = createElement("div", "network-layout");
    const copy = createElement("div", "network-copy propagation-copy");
    const currentRow = scene.daily.find((row) => row.date === selectedDate) || scene.daily[0] || {};
    layout.append(
      renderSharedNetworkVisual(scene, family, selectedDate, { mode: "propagation", stage }),
      copy
    );
    copy.appendChild(renderPropagationResultCard(scene, family, stage, currentRow, selectedDate));
    copy.appendChild(renderFocusedNodeCard(family));
    if (scene.interactive_network && scene.interactive_network.daily_states && scene.interactive_network.daily_states.length) {
      copy.appendChild(renderConfiguratorCard(family));
    }
    panel.appendChild(layout);
    return panel;
  }

  function renderRecoveryActionPanel(scene, family, stage, selectedDate) {
    const panel = createElement("section", "panel network-panel recovery-network-panel");
    panel.append(createSectionHead("", "恢复动作网络"));
    const layout = createElement("div", "network-layout");
    const copy = createElement("div", "network-copy recovery-copy");
    const currentRow = scene.daily.find((row) => row.date === selectedDate) || scene.daily[0] || {};
    layout.append(
      renderSharedNetworkVisual(scene, family, selectedDate, { mode: "recovery", stage }),
      copy
    );
    copy.appendChild(renderRecoveryControlCard(scene, family, currentRow, selectedDate));
    copy.appendChild(renderRecoverySelectorCard(family));
    panel.appendChild(layout);
    return panel;
  }

  function renderPropagationResultCard(scene, family, stage, currentRow, selectedDate) {
    const panel = createElement("section", "panel detail-panel aside-detail-panel");
    panel.append(createSectionHead("", "当前传播结果"));
    const grid = createElement("div", "detail-grid");
    grid.appendChild(detailCard("中断供应商", formatInteger(currentRow.supplier_disrupted_nodes)));
    grid.appendChild(detailCard("受影响物料", formatInteger(currentRow.material_affected_nodes)));
    grid.appendChild(detailCard("阻断物料", formatInteger(currentRow.material_blocked_nodes)));
    grid.appendChild(detailCard("阻断装配件", formatInteger(currentRow.assembly_blocked_nodes)));
    grid.appendChild(detailCard("阻断产品", formatInteger(currentRow.product_blocked_nodes)));
    grid.appendChild(detailCard("当前结果", state.resultModeByFamily[family] === "whatif" ? "节点推演结果" : "基准传播结果"));
    panel.appendChild(grid);
    return panel;
  }

  function renderFocusedNodeCard(family, options = {}) {
    const { hideWhenEmpty = false } = options;
    const scene = getSceneBundle(family).current;
    const card = createElement("div", "network-copy-card aside-focus-panel");
    card.appendChild(createElement("h3", "", "当前焦点节点"));
    const focus = state.focusNodeByFamily[family];
    if (!focus) {
      if (hideWhenEmpty) {
        return null;
      }
      card.appendChild(createElement("div", "chart-note", "在左侧传播网络中单击任一节点，可查看节点状态并把它加入推演集合。"));
      return card;
    }
    const grid = createElement("div", "detail-grid compact-detail-grid");
    grid.appendChild(detailCard("节点名称", formatEntityName(focus.entity_id, scene)));
    grid.appendChild(detailCard("节点类型", translateNodeType(focus.node_type)));
    grid.appendChild(detailCard("当前状态", translateVisualStatus(focus.visual_status)));
    grid.appendChild(detailCard("关键节点", focus.is_key_node ? "是" : "否"));
    card.appendChild(grid);
    return card;
  }

  /*
   * Inactive duplicate: final renderRecoveryControlCard definition lives later.
   *
  function renderRecoveryControlCard(scene, family, currentRow, selectedDate) {
    const card = createElement("div", "network-copy-card recovery-console-card aside-detail-panel");
    card.appendChild(createElement("h3", "", "恢复动作控制台"));
    card.appendChild(createElement("small", "", `${formatDate(selectedDate)} · ${policyProfileLabel(state.policyProfileByFamily[family])}`));
    const recoveryContext = buildRecoveryContext(
      scene,
      scene.interactive_network,
      resolveDailyNetworkState(scene.interactive_network?.daily_states || [], selectedDate),
      selectedDate
    );
    const stats = createElement("div", "snapshot-stat-grid");
    stats.appendChild(detailCard("当前主导恢复动作", resolveDominantRecoveryAction(currentRow)));
    stats.appendChild(detailCard("激活备供切换数", formatInteger(currentRow.active_backup_switches)));
    stats.appendChild(detailCard("激活等效替代数", formatInteger(currentRow.active_substitutions)));
    stats.appendChild(detailCard("激活优先抢修数", formatInteger(currentRow.active_priority_repairs)));
    stats.appendChild(detailCard("当前累计策略成本", formatCurrency(currentRow.policy_cumulative_cost)));
    stats.appendChild(detailCard("仍未恢复关键节点", formatInteger(recoveryContext.unresolvedKeyKeys.size)));
    card.appendChild(stats);

    const eventsTitle = createElement("div", "mini-card-head");
    eventsTitle.appendChild(createElement("strong", "", "最近 3 条恢复事件"));
    eventsTitle.appendChild(createElement("span", "mini-card-note", "按当前日期向前回看"));
    card.appendChild(eventsTitle);
    const eventList = createElement("div", "mini-event-list");
    const events = getRecentRecoveryEvents(scene, selectedDate, 3);
    if (!events.length) {
      eventList.appendChild(createElement("div", "empty-note compact-note", "当前日期之前暂无恢复事件。"));
    } else {
      events.forEach((row) => {
        const item = createElement("article", "mini-event-card");
        item.appendChild(createElement("strong", "", row.policy_type_name || translatePolicyType(row.policy_type)));
        item.appendChild(createElement("small", "", `${translatePolicyAction(row.action)} · ${row.target_id || "-"}`));
        item.appendChild(createElement("small", "", row.activate_date ? `生效日：${formatDate(row.activate_date)}` : `记录日：${formatDate(row.date)}`));
        eventList.appendChild(item);
      });
    }
    card.appendChild(eventList);
    return card;
  }
  */

  /*
   * Inactive duplicate: final renderRecoverySelectorCard definition lives later.
   *
  function renderRecoverySelectorCard(family) {
    const selectedNodes = getSelectedNodes(family);
    const scene = getSceneBundle(family).current;
    const card = createElement("div", "network-copy-card recovery-selector-card aside-config-panel");
    card.appendChild(createElement("h3", "", "当前推演对象"));
    const grid = createElement("div", "detail-grid compact-detail-grid");
    grid.appendChild(detailCard("当前节点集合", selectedNodes.length ? selectedNodes.map((node) => formatNodeName(node, scene)).join("、") : "未选择"));
    grid.appendChild(detailCard("当前结果模式", state.resultModeByFamily[family] === "whatif" ? "节点推演结果" : "基准情境"));
    card.appendChild(grid);
    const actions = createElement("div", "selector-action-row");
    const backSceneButton = createElement("button", "ghost-button", "返回情境页继续选点");
    backSceneButton.addEventListener("click", () => {
      stopPlay();
      state.page = family;
      renderApp();
    });
    actions.appendChild(backSceneButton);
    if (state.whatIfPayloads[family]) {
      const keepResultButton = createElement("button", "scene-pill", "查看当前推演恢复过程");
      keepResultButton.addEventListener("click", () => {
        stopPlay();
        state.resultModeByFamily[family] = "whatif";
        state.subViewByPage.recovery = "recovery_network";
        state.page = "recovery";
        renderApp();
      });
      actions.appendChild(keepResultButton);
    }
    card.appendChild(actions);
    return card;
  }
  */

  function renderPolicyComparisonPanel(scene, family, selectedIndex, viewport) {
    const panel = createElement("section", "panel policy-comparison-panel");

    if (!scene.policy_profiles || !scene.policy_profiles.length || !scene.policy_comparison_time_series || !scene.policy_comparison_time_series.length) {
      const isWhatIf = state.resultModeByFamily[family] === "whatif" && Boolean(state.whatIfPayloads[family]);
      panel.appendChild(
        createElement(
          "div",
          "empty-note",
          isWhatIf
            ? "当前推演结果未附带策略对比序列。请重启本地服务后清除当前推演并重新生成，旧推演结果不会自动补齐多策略序列。"
            : "当前结果未附带策略对比序列。"
        )
      );
      return panel;
      panel.appendChild(createElement("div", "empty-note", "当前结果未附带策略对比序列。"));
      return panel;
    }

    const sortedDates = Array.from(
      new Set(scene.policy_comparison_time_series.map((row) => String(row.date || "")).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));
    const series = scene.policy_profiles.map((profile, index) => {
      const key = `policy_profile_${index}`;
      return {
        key,
        label: policyProfileLabel(profile.policy_profile, profile.policy_label),
        color: policyColor(profile.policy_profile),
      };
    });

    const metricDefs = [
      { key: "total_interrupted_nodes", label: "全链中断节点" },
      { key: "supplier_disrupted_nodes", label: "供应商中断节点" },
      { key: "downstream_interrupted_nodes", label: "下游阻断节点" },
    ];
    const grid = createElement("div", "policy-comparison-grid");
    metricDefs.forEach((metric) => {
      const rowsByDate = new Map(sortedDates.map((date) => [date, { date }]));
      scene.policy_profiles.forEach((profile, index) => {
        const rows = scene.policy_comparison_time_series
          .filter((row) => row.policy_profile === profile.policy_profile)
          .sort((a, b) => String(a.date).localeCompare(String(b.date)));
        rows.forEach((row) => {
          const date = String(row.date || "");
          if (rowsByDate.has(date)) {
            rowsByDate.get(date)[`policy_profile_${index}`] = Number(row[metric.key] || 0);
          }
        });
      });

      const chartRows = sortedDates.map((date) => rowsByDate.get(date));
      const safeSelectedIndex = clamp(selectedIndex, 0, Math.max(chartRows.length - 1, 0));
      const card = createElement("article", "policy-comparison-card");
      card.appendChild(createElement("h3", "", metric.label));
      card.appendChild(renderLineChart(
        chartRows,
        {
          title: metric.label,
          mode: "count",
          xLabel: "日期",
          yLabel: "节点数",
          series,
        },
        safeSelectedIndex,
        (index) => {
          state.selectedIndexByFamily[family] = index;
          state.viewportByFamily[family] = ensureViewportContains(viewport, chartRows.length, index);
          stopPlay();
          renderApp();
        },
        {
          navigator: false,
          ghostNavigator: false,
          windowed: false,
          compact: true,
          ultraCompact: true,
        }
      ));
      grid.appendChild(card);
    });
    panel.appendChild(grid);
    panel.appendChild(renderLegend(series));
    return panel;
  }

  function renderPathsPanel(scene) {
    const panel = createElement("section", "panel");
    panel.append(createSectionHead("", "关键路径与物料清单影响链"));
    const grid = createElement("div", "paths-grid");
    if (!scene.impacted_paths || !scene.impacted_paths.length) {
      grid.appendChild(createElement("div", "empty-note", "当前场景没有可展示的关键路径。"));
    } else {
      scene.impacted_paths.forEach((pathRow) => {
        const card = createElement("article", "path-card");
        const header = createElement("div", "path-header");
        const left = createElement("div");
        left.appendChild(createElement("strong", "", formatEntityName(pathRow.item_id, scene)));
        left.appendChild(createElement("small", "", `根因：${translateRootCause(pathRow.root_cause)}`));
        const status = createElement("span", "status-badge", `${translateImpactDimension(pathRow.impact_dimension)} / ${translateImpactStatus(pathRow.impact_status)}`);
        status.style.background = badgeColor(pathRow.impact_dimension);
        status.style.color = "#fff";
        header.append(left, status);
        const flow = createElement("div", "path-flow");
        const segments = replaceEntityIdsWithNames(pathRow.path, scene).split("->").map((item) => item.trim()).filter(Boolean);
        segments.forEach((segment, index) => {
          flow.appendChild(createElement("span", "node-chip", segment));
          if (index < segments.length - 1) {
            flow.appendChild(createElement("span", "arrow-chip", "→"));
          }
        });
        card.append(header, createElement("small", "", `${translateImpactLevel(pathRow.impact_level)}层影响`), flow);
        grid.appendChild(card);
      });
    }
    panel.appendChild(grid);
    return panel;
  }

  function renderEventsPanel(scene, selectedDate) {
    const panel = createElement("section", "panel");
    panel.append(createSectionHead("", "策略事件时间线"));
    const list = createElement("div", "event-list");
    const rows = (scene.policy_events || [])
      .slice()
      .sort((a, b) => String(a.date).localeCompare(String(b.date)))
      .map((row) => ({ ...row, dateGap: Math.abs(dayDistance(row.date, selectedDate)) }))
      .sort((a, b) => a.dateGap - b.dateGap || String(a.date).localeCompare(String(b.date)))
      .slice(0, 10);
    if (!rows.length) {
      list.appendChild(createElement("div", "empty-note", "当前场景没有策略事件。"));
    } else {
      rows.forEach((row) => {
        const card = createElement("article", "event-card");
        const top = createElement("div", "event-row");
        top.appendChild(createElement("strong", "", row.policy_type_name || row.policy_type || "策略事件"));
        top.appendChild(createElement("small", "", formatDate(row.date)));
        card.appendChild(top);
        card.appendChild(createElement("small", "", `${translatePolicyAction(row.action)} · ${translateTargetType(row.target_type)} / ${formatEntityName(row.target_id, scene)}`));
        card.appendChild(createElement("small", "", `成本：${formatCurrency(row.cost)}${row.activate_date ? ` · 生效日：${formatDate(row.activate_date)}` : ""}`));
        list.appendChild(card);
      });
    }
    panel.appendChild(list);
    return panel;
  }

  async function triggerWhatIf(family, node) {
    if (node) {
      if (!toggleSelectedNode(family, node, true)) {
        state.apiMessage = selectionRuleText(family);
        renderApp();
        return;
      }
    }
    const targetNodes = getSelectedNodes(family);
    if (state.isSubmittingWhatIf || !state.apiAvailable || !targetNodes.length) {
      renderApp();
      return;
    }
    state.isSubmittingWhatIf = true;
    stopPlay();
    const scene = getSceneBundle(family).current;
    const nodeLabel = targetNodes.map((item) => formatNodeName(item, scene)).join("、");
    state.apiMessage = `正在为 ${nodeLabel} 生成新的动态推演结果…`;
    renderApp();
    try {
      const response = await fetchJson(buildApiUrl("/api/whatif-run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scene_family: family,
          node_keys: targetNodes.map((item) => item.node_key),
          policy_profile: "time_priority_interrupt",
        }),
      });
      if (!response || !response.ok || !response.dashboard_payload) {
        throw new Error((response && response.error) || "推演失败");
      }
      state.whatIfPayloads[family] = response.dashboard_payload;
      state.resultModeByFamily[family] = "whatif";
      const whatIfScene = response.dashboard_payload.scenes.whatif;
      state.lastWhatIf = {
        family,
        node_label: replaceEntityIdsWithNames(response.node_label, whatIfScene),
      };
      state.policyProfileByFamily[family] = "time_priority_interrupt";
      const startIndex = Math.max(0, whatIfScene.daily.findIndex((row) => row.date === whatIfScene.scenario.start_date));
      state.selectedIndexByFamily[family] = startIndex >= 0 ? startIndex : 0;
      state.viewportByFamily[family] = createViewport(whatIfScene.daily.length, state.selectedIndexByFamily[family]);
      state.focusNodeByFamily[family] = null;
      state.networkViewByFamily[family] = { scale: 1, panX: 0, panY: 0 };
      state.apiMessage = `已完成 ${replaceEntityIdsWithNames(response.node_label, whatIfScene)} 的定点中断推演，当前页已切换到新结果。`;
    } catch (error) {
      state.apiMessage = `推演失败：${error.message || error}`;
    } finally {
      state.isSubmittingWhatIf = false;
      renderApp();
    }
  }

  function togglePlay(family) {
    if (state.playingFamily === family) {
      stopPlay();
      return;
    }
    stopPlay();
    state.playingFamily = family;
    state.timer = window.setInterval(() => {
      const scene = getSceneBundle(family).current;
      if (state.selectedIndexByFamily[family] >= scene.daily.length - 1) {
        stopPlay();
        return;
      }
      state.selectedIndexByFamily[family] += 1;
      state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], scene.daily.length, state.selectedIndexByFamily[family]);
      renderApp();
    }, 900);
    renderApp();
  }

  function stopPlay() {
    if (state.timer) {
      window.clearInterval(state.timer);
    }
    state.timer = null;
    state.playingFamily = null;
  }

  function currentFamily() {
    if (state.page === "random" || state.page === "keynode") {
      return state.page;
    }
    if (state.page === "recovery" || state.page === "map") {
      return state.recoveryFamily;
    }
    return null;
  }

  function resolvePageFamily(pageKey, recoveryFamily = state.recoveryFamily) {
    if (pageKey === "random" || pageKey === "keynode") {
      return pageKey;
    }
    if (pageKey === "recovery" || pageKey === "map") {
      return recoveryFamily;
    }
    return null;
  }

  function syncPlaybackForFamily(nextFamily) {
    if (!state.playingFamily) {
      return;
    }
    if (state.playingFamily !== nextFamily) {
      stopPlay();
    }
  }

  function getSceneBundle(family) {
    const baseline = baseScenes[family];
    const whatIfPayload = state.whatIfPayloads[family];
    const useWhatIf = state.resultModeByFamily[family] === "whatif" && whatIfPayload;
    return {
      baseline,
      current: useWhatIf ? whatIfPayload.scenes.whatif : baseline,
      reference: useWhatIf ? whatIfPayload.scenes.reference : baseline,
    };
  }

  function getWhatIfScene(family) {
    const payload = state.whatIfPayloads[family];
    return payload?.scenes?.whatif || null;
  }

  function ensureSceneSelection(family, scene) {
    const maxIndex = Math.max((scene.daily || []).length - 1, 0);
    const current = clamp(Number(state.selectedIndexByFamily[family] || 0), 0, maxIndex);
    state.selectedIndexByFamily[family] = current;
    return current;
  }

  function resolveCurrentStage(scene, dateText) {
    const snapshots = (scene.network_snapshots || []).slice().sort((a, b) => String(a.snapshot_date).localeCompare(String(b.snapshot_date)));
    if (!snapshots.length) {
      return {};
    }
    let current = snapshots[0];
    snapshots.forEach((snapshot) => {
      if (String(snapshot.snapshot_date) <= String(dateText)) {
        current = snapshot;
      }
    });
    return current;
  }

  function renderSelectorGraph(graph, family) {
    const scene = getSceneBundle(family).current;
    const width = 960;
    const height = 520;
    const svg = createSvg(width, height, "chart-svg network-svg");
    const bounds = graphBounds(graph.nodes);
    const scaleX = createLinearScale(bounds.minX, bounds.maxX, 64, width - 64);
    const scaleY = createLinearScale(bounds.maxY, bounds.minY, 44, height - 44);
    const selectedNodes = getSelectedNodes(family);

    graph.edges.forEach((edge) => {
      const source = graph.nodes.find((node) => node.node_key === edge.source_key);
      const target = graph.nodes.find((node) => node.node_key === edge.target_key);
      if (!source || !target) {
        return;
      }
      svg.appendChild(createSvgElement("line", {
        x1: scaleX(source.x), y1: scaleY(source.y),
        x2: scaleX(target.x), y2: scaleY(target.y),
        stroke: "#cbd5e1", "stroke-width": 1.1, opacity: 0.6,
      }));
    });

    graph.nodes.forEach((node) => {
      const isSelected = selectedNodes.some((item) => item.node_key === node.node_key);
      const selectable = isNodeSelectableForWhatIf(family, node);
      const group = createSvgElement("g", {
        transform: `translate(${scaleX(node.x)},${scaleY(node.y)})`,
        class: "selector-node",
        cursor: state.apiAvailable && selectable ? "pointer" : "not-allowed",
        opacity: selectable ? (selectedNodes.length && !isSelected ? 0.34 : 1) : 0.28,
      });
      const shape = selectorNodeShape(node);
      if (isSelected) {
        shape.setAttribute("fill", "#dbeafe");
        shape.setAttribute("stroke", "#2563EB");
        shape.setAttribute("stroke-width", "3.2");
      }
      group.appendChild(shape);
      group.appendChild(createSvgElement("text", {
        x: 0, y: 18, "text-anchor": "middle",
        fill: "#111827", "font-size": 9.5, "font-weight": 700,
      }, shortDisplayName(formatNodeName(node, scene), 8)));
      group.appendChild(createSvgElement("title", {}, `${nodeTitleText(node, null, scene)}${selectable ? "" : " · 当前情境不可选"}`));
      group.addEventListener("click", () => {
        if (!toggleSelectedNode(family, node)) {
          state.apiMessage = selectionRuleText(family);
        }
        renderApp();
      });
      if (state.apiAvailable && selectable) {
        group.addEventListener("dblclick", () => triggerWhatIf(family, node));
      }
      svg.appendChild(group);
    });
    return svg;
  }

  function renderDynamicNetwork(network, selectedDate, family, options = {}) {
    const scene = options.scene || getSceneBundle(family).current;
    const width = 1040;
    const height = 620;
    const svg = createSvg(width, height, "chart-svg network-svg");
    const layoutKey = sceneLayoutKey(family);
    const nodes = applyLayoutOverrides(network.nodes, state.layoutOverridesByScene[layoutKey]);
    const nodeByKey = new Map(nodes.map((node) => [node.node_key, node]));
    const bounds = graphBounds(nodes);
    const scaleX = createLinearScale(bounds.minX, bounds.maxX, 72, width - 72);
    const scaleY = createLinearScale(bounds.maxY, bounds.minY, 52, height - 52);
    const inverseX = createInverseLinearScale(bounds.minX, bounds.maxX, 72, width - 72);
    const inverseY = createInverseLinearScale(bounds.maxY, bounds.minY, 52, height - 52);
    const current = resolveDailyNetworkState(network.daily_states, selectedDate);
    const mode = options.mode || "propagation";
    const recoveryContext = mode === "recovery"
      ? buildRecoveryContext(options.scene || getSceneBundle(family).current, network, current, selectedDate)
      : null;
    const view = state.networkViewByFamily[family] || { scale: 1, panX: 0, panY: 0 };
    const filterValue = mode === "recovery"
      ? (state.recoveryFilterByFamily[family] || "recovery")
      : (state.networkFilterByFamily[family] || "all");
    const selectedNodes = getSelectedNodes(family);
    const selectedNodeKeys = new Set(selectedNodes.map((item) => item.node_key));
    const edgeRefs = new Map();
    const nodeRefs = new Map();
    const camera = createSvgElement("g", {
      transform: `translate(${view.panX},${view.panY}) scale(${view.scale})`,
    });
    const backdrop = createSvgElement("rect", {
      x: 0,
      y: 0,
      width,
      height,
      fill: "transparent",
      cursor: "grab",
    });
    svg.appendChild(backdrop);
    svg.appendChild(camera);
    const relatedKeys = collectRelatedNodeKeys(network.edges, state.focusNodeByFamily[family]?.entity_id, nodeByKey)
      || (mode === "recovery"
        ? collectRecoveryFocusKeys(network, recoveryContext)
        : collectProcessFocusKeys(network.edges, current, nodeByKey));
    const edges = network.edges.slice().sort((left, right) => edgePriority((current.edge_status || {})[left.edge_key]) - edgePriority((current.edge_status || {})[right.edge_key]));
    edges.forEach((edge) => {
      const source = nodeByKey.get(edge.source_key);
      const target = nodeByKey.get(edge.target_key);
      if (!source || !target) {
        return;
      }
      const status = (current.edge_status || {})[edge.edge_key];
      const style = edgeStyle(status);
      const visible = mode === "recovery"
        ? edgeMatchesRecoveryFilter(edge, filterValue, recoveryContext)
        : edgeMatchesFilter(edge, source, target, status, filterValue, current);
      const touchesSelected = selectedNodeKeys.has(source.node_key) || selectedNodeKeys.has(target.node_key);
      const focused = touchesSelected || !relatedKeys || (relatedKeys.has(source.node_key) && relatedKeys.has(target.node_key));
      const line = createSvgElement("line", {
        x1: scaleX(source.x), y1: scaleY(source.y),
        x2: scaleX(target.x), y2: scaleY(target.y),
        stroke: style.stroke, "stroke-width": style.width,
        "stroke-dasharray": style.dash, opacity: visible ? (focused ? style.opacity : Math.max(style.opacity * 0.18, 0.08)) : 0.04,
      });
      camera.appendChild(line);
      edgeRefs.set(edge.edge_key, line);
    });

    nodes.forEach((node) => {
      const status = (current.node_status || {})[node.node_key] || "stable";
      const fill = nodeStatusColor(status);
      const focusedNode = state.focusNodeByFamily[family];
      const isFocused = focusedNode && focusedNode.entity_id === node.entity_id;
      const isSelectedForWhatIf = selectedNodeKeys.has(node.node_key);
      const selectableForWhatIf = mode !== "recovery" && isNodeSelectableForWhatIf(family, node);
      const visible = mode === "recovery"
        ? nodeMatchesRecoveryFilter(node, filterValue, recoveryContext)
        : (filterValue === "process"
          ? (!relatedKeys || relatedKeys.has(node.node_key))
          : nodeMatchesFilter(node, status, filterValue, current));
      const isRelated = isSelectedForWhatIf || !relatedKeys || relatedKeys.has(node.node_key);
      const isRecoveredByPolicy = mode === "recovery" && recoveryContext?.recoveredKeys.has(node.node_key);
      const isUnresolvedKey = mode === "recovery" && recoveryContext?.unresolvedKeyKeys.has(node.node_key);
      const group = createSvgElement("g", {
        transform: `translate(${scaleX(node.x)},${scaleY(node.y)})`,
        class: "draggable-node",
        cursor: "grab",
        opacity: visible ? (isRelated ? 1 : 0.24) : 0.05,
      });
      const common = {
        fill,
        stroke: isFocused
          ? "#111827"
          : (isSelectedForWhatIf
            ? "#2563EB"
            : (isRecoveredByPolicy
              ? "#0F766E"
              : (isUnresolvedKey ? "#C1121F" : (node.is_key_node ? "#FF2DAA" : "#22313F")))),
        "stroke-width": isFocused ? 3.2 : (isSelectedForWhatIf ? 3 : (isRecoveredByPolicy || isUnresolvedKey || node.is_key_node ? 2.5 : 1.4)),
      };
      if (node.node_type === "supplier") {
        group.appendChild(createSvgElement("circle", { cx: 0, cy: 0, r: 10, ...common }));
      } else if (node.node_type === "assembly") {
        group.appendChild(createSvgElement("polygon", { points: "0,-12 12,0 0,12 -12,0", ...common }));
      } else if (node.node_type === "product") {
        group.appendChild(createSvgElement("polygon", { points: "0,-13 12,10 -12,10", ...common }));
      } else {
        group.appendChild(createSvgElement("rect", { x: -10, y: -10, width: 20, height: 20, rx: 3, ...common }));
      }
      group.appendChild(createSvgElement("text", {
        x: 0, y: 19, "text-anchor": "middle",
        fill: "#111827", "font-size": 10.4, "font-weight": 700,
      }, shortDisplayName(formatNodeName(node, scene), 8)));
      group.appendChild(createSvgElement("title", {}, `${nodeTitleText(node, status, scene)}${mode !== "recovery" && !selectableForWhatIf ? " · 当前情境不可选" : ""}`));
      attachNodeDrag(group, {
        node,
        family,
        layoutKey,
        svg,
        scaleX,
        scaleY,
        inverseX,
        inverseY,
        nodesByKey: nodeByKey,
        edges,
        edgeRefs,
        onClick: () => {
          if (mode !== "recovery") {
            if (!toggleSelectedNode(family, node)) {
              state.apiMessage = selectionRuleText(family);
            }
          }
          state.focusNodeByFamily[family] = {
            node_key: node.node_key,
            entity_id: node.entity_id,
            node_type: node.node_type,
            is_key_node: node.is_key_node,
            visual_status: status,
          };
          renderApp();
        },
      });
      camera.appendChild(group);
      nodeRefs.set(node.node_key, group);
    });
    attachNetworkViewportHandlers(svg, backdrop, camera, family);
    return svg;
  }

  function renderLineChart(rows, definition, selectedIndex, onSelect, options = {}) {
    const width = 900;
    const height = options.ultraCompact ? (options.navigator ? 220 : 190) : (options.compact ? (options.navigator ? 272 : 228) : (options.navigator ? 360 : 290));
    const navigatorHeight = options.navigator ? (options.ultraCompact ? 18 : (options.compact ? 24 : 40)) : 0;
    const navigatorGap = options.navigator ? (options.ultraCompact ? 6 : (options.compact ? 10 : 16)) : 0;
    const margin = {
      top: 16,
      right: 18,
      bottom: options.navigator ? (options.ultraCompact ? 44 : (options.compact ? 62 : 92)) : 34,
      left: 54,
    };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const seriesList = definition.series.map((series) => ({
      ...series,
      values: rows.map((row) => Number(row[series.key] || 0)),
    }));
    const allValues = seriesList.flatMap((series) => series.values);
    let minValue = Math.min(...allValues);
    let maxValue = Math.max(...allValues);
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      minValue = 0;
      maxValue = 1;
    }
    if (definition.mode === "ratio") {
      minValue = 0;
      maxValue = 1;
    } else if (minValue === maxValue) {
      maxValue = minValue + 1;
    }

    const svg = createSvg(width, height, "chart-svg");
    const plot = createSvgElement("g", { transform: `translate(${margin.left},${margin.top})` });
    svg.appendChild(plot);

    const useWindow = Boolean(
      options.navigator
      || options.windowed
      || Number.isFinite(options.windowStart)
      || Number.isFinite(options.windowSize)
    );
    const view = useWindow
      ? normalizeViewport({ start: options.windowStart, size: options.windowSize }, rows.length, selectedIndex)
      : { start: 0, size: rows.length || 1 };
    const viewStart = view.start;
    const viewEnd = Math.min(rows.length - 1, view.start + view.size - 1);
    const visibleSpan = Math.max(viewEnd - viewStart, 1);

    for (let i = 0; i < 4; i += 1) {
      const y = (innerHeight / 3) * i;
      plot.appendChild(createSvgElement("line", {
        x1: 0, y1: y, x2: innerWidth, y2: y, stroke: "#dbe5f0", "stroke-width": 1,
      }));
    }
    plot.appendChild(createSvgElement("line", {
      x1: 0, y1: innerHeight, x2: innerWidth, y2: innerHeight,
      stroke: "#cbd5e1", "stroke-width": 1.2,
    }));
    plot.appendChild(createSvgElement("line", {
      x1: 0, y1: 0, x2: 0, y2: innerHeight,
      stroke: "#cbd5e1", "stroke-width": 1.2,
    }));

    const xScale = (index) => {
      if (rows.length <= 1 || viewStart === viewEnd) return innerWidth / 2;
      return ((index - viewStart) / visibleSpan) * innerWidth;
    };
    const yScale = (value) => innerHeight - ((value - minValue) / (maxValue - minValue || 1)) * innerHeight;

    plot.appendChild(createSvgElement("line", {
      x1: xScale(selectedIndex), y1: 0, x2: xScale(selectedIndex), y2: innerHeight,
      stroke: "#94a3b8", "stroke-dasharray": "4 4", "stroke-width": 1.5,
    }));

    seriesList.forEach((series) => {
      const visibleValues = series.values
        .map((value, idx) => ({ value, idx }))
        .filter((item) => item.idx >= viewStart && item.idx <= viewEnd);
      const base = visibleValues.map((item) => `${xScale(item.idx)},${yScale(item.value)}`).join(" ");
      plot.appendChild(createSvgElement("polyline", {
        points: base, fill: "none", stroke: series.color,
        "stroke-width": 2.2, "stroke-linejoin": "round", "stroke-linecap": "round", opacity: 0.22,
      }));

      const focus = visibleValues
        .filter((item) => item.idx >= selectedIndex)
        .map((item) => `${xScale(item.idx)},${yScale(item.value)}`)
        .join(" ");
      plot.appendChild(createSvgElement("polyline", {
        points: focus, fill: "none", stroke: series.color,
        "stroke-width": 3.4, "stroke-linejoin": "round", "stroke-linecap": "round",
      }));

      plot.appendChild(createSvgElement("circle", {
        cx: xScale(selectedIndex), cy: yScale(series.values[selectedIndex]),
        r: 5, fill: "#fff", stroke: series.color, "stroke-width": 2.4,
      }));
    });

    uniqueSorted([viewStart, Math.floor((viewStart + viewEnd) / 2), viewEnd, selectedIndex])
      .forEach((tickIndex) => {
        plot.appendChild(createSvgElement("text", {
          x: xScale(tickIndex), y: innerHeight + 20, "text-anchor": "middle",
          fill: "#64748b", "font-size": 11,
        }, shortDate(rows[tickIndex].date)));
      });

    [0, 1, 2, 3].forEach((step) => {
      const value = minValue + ((maxValue - minValue) / 3) * (3 - step);
      plot.appendChild(createSvgElement("text", {
        x: -10, y: (innerHeight / 3) * step + 4, "text-anchor": "end",
        fill: "#64748b", "font-size": 12,
      }, definition.mode === "ratio" ? formatPercent(value, 0) : compactNumber(value)));
    });
    plot.appendChild(createSvgElement("text", {
      x: innerWidth / 2,
      y: options.navigator ? innerHeight + navigatorGap + navigatorHeight + (options.ultraCompact ? 18 : (options.compact ? 20 : 28)) : innerHeight + 34,
      "text-anchor": "middle",
      fill: "#64748b",
      "font-size": 12,
    }, definition.xLabel || "日期"));
    plot.appendChild(createSvgElement("text", {
      x: -innerHeight / 2,
      y: -44,
      transform: "rotate(-90)",
      "text-anchor": "middle",
      fill: "#64748b",
      "font-size": 12,
    }, definition.yLabel || (definition.mode === "ratio" ? "比例" : "数量")));

    const tooltip = createSvgElement("g", { opacity: "0" });
    const tooltipWidth = Math.max(
      168,
      Math.min(
        300,
        54 + Math.max(...seriesList.map((series) => String(series.label || "").length)) * 14
      )
    );
    const tooltipBox = createSvgElement("rect", {
      x: 0, y: 0, width: tooltipWidth, height: 28 + seriesList.length * 16, rx: 10,
      fill: "rgba(15,23,42,0.92)",
    });
    const tooltipTitle = createSvgElement("text", {
      x: 12, y: 18, fill: "#f8fafc", "font-size": 12.5, "font-weight": 700,
    });
    tooltip.appendChild(tooltipBox);
    tooltip.appendChild(tooltipTitle);
    const tooltipRows = seriesList.map((series, idx) => {
      const row = createSvgElement("text", {
        x: 12, y: 38 + idx * 16, fill: "#e2e8f0", "font-size": 12,
      });
      tooltip.appendChild(row);
      return { row, series };
    });
    plot.appendChild(tooltip);

    const hit = createSvgElement("rect", {
      x: 0, y: 0, width: innerWidth, height: innerHeight,
      fill: "transparent", cursor: "grab",
    });
    let dragging = false;

    const showTooltip = (index) => {
      const safeIndex = clamp(index, 0, rows.length - 1);
      const anchorX = clamp(xScale(safeIndex) + 12, 0, Math.max(innerWidth - tooltipWidth - 6, 0));
      const anchorY = 10;
      tooltip.setAttribute("transform", `translate(${anchorX},${anchorY})`);
      tooltip.setAttribute("opacity", "1");
      tooltipTitle.textContent = formatDate(rows[safeIndex].date);
      tooltipRows.forEach(({ row, series }) => {
        const raw = Number(rows[safeIndex][series.key] || 0);
        const display = definition.mode === "ratio" ? formatPercent(raw) : compactNumber(raw);
        row.textContent = `${series.label}：${display}`;
      });
    };
    const hideTooltip = () => {
      if (!dragging) {
        tooltip.setAttribute("opacity", "0");
      }
    };

    const updateIndexFromClientX = (clientX, rect = svg.getBoundingClientRect()) => {
      const localX = clientX - rect.left - margin.left;
      const ratio = clamp(localX / innerWidth, 0, 1);
      const next = viewStart + Math.round(ratio * visibleSpan);
      onSelect(clamp(next, 0, rows.length - 1));
    };
    const hoverIndexFromClientX = (clientX, rect = svg.getBoundingClientRect()) => {
      const localX = clientX - rect.left - margin.left;
      const ratio = clamp(localX / innerWidth, 0, 1);
      return clamp(viewStart + Math.round(ratio * visibleSpan), 0, rows.length - 1);
    };

    hit.addEventListener("click", (event) => {
      updateIndexFromClientX(event.clientX);
    });
    hit.addEventListener("pointerdown", (event) => {
      dragging = true;
      hit.setAttribute("cursor", "grabbing");
      const dragRect = svg.getBoundingClientRect();
      const handleMove = (moveEvent) => {
        const hoverIndex = hoverIndexFromClientX(moveEvent.clientX, dragRect);
        showTooltip(hoverIndex);
        updateIndexFromClientX(moveEvent.clientX, dragRect);
      };
      const endDrag = () => {
        if (!dragging) return;
        dragging = false;
        hit.setAttribute("cursor", "grab");
        hideTooltip();
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", endDrag);
        window.removeEventListener("pointercancel", endDrag);
      };
      window.addEventListener("pointermove", handleMove);
      window.addEventListener("pointerup", endDrag);
      window.addEventListener("pointercancel", endDrag);
      showTooltip(hoverIndexFromClientX(event.clientX, dragRect));
      updateIndexFromClientX(event.clientX, dragRect);
    });
    hit.addEventListener("pointermove", (event) => {
      if (dragging) return;
      const hoverIndex = hoverIndexFromClientX(event.clientX);
      showTooltip(hoverIndex);
    });
    hit.addEventListener("pointerleave", hideTooltip);
    if (options.navigator && typeof options.onWindowChange === "function") {
      hit.addEventListener("wheel", (event) => {
        event.preventDefault();
        const direction = event.deltaY > 0 ? 2 : -2;
        const nextSize = clamp(view.size + direction, 6, rows.length);
        const hoverIndex = hoverIndexFromClientX(event.clientX);
        const nextStart = clamp(hoverIndex - Math.round(nextSize / 2), 0, Math.max(0, rows.length - nextSize));
        options.onWindowChange(nextStart, nextSize);
      }, { passive: false });
    }
    plot.appendChild(hit);

    if (options.navigator && rows.length > 1) {
      const ghostNavigator = Boolean(options.ghostNavigator);
      const navTop = margin.top + innerHeight + navigatorGap;
      const navGroup = createSvgElement("g", { transform: `translate(${margin.left},${navTop})` });
      const navYScale = (value) => navigatorHeight - ((value - minValue) / (maxValue - minValue || 1)) * navigatorHeight;
      const navXScale = (index) => (rows.length <= 1 ? innerWidth / 2 : (innerWidth / (rows.length - 1)) * index);
      svg.appendChild(navGroup);

      navGroup.appendChild(createSvgElement("rect", {
        x: 0, y: 0, width: innerWidth, height: navigatorHeight,
        rx: 10,
        fill: ghostNavigator ? "transparent" : "#eff6ff",
        stroke: ghostNavigator ? "transparent" : "#bfdbfe",
      }));

      const navSeries = seriesList[0];
      if (navSeries) {
        navGroup.appendChild(createSvgElement("polyline", {
          points: navSeries.values.map((value, idx) => `${navXScale(idx)},${navYScale(value)}`).join(" "),
          fill: "none",
          stroke: ghostNavigator ? "transparent" : "#93c5fd",
          "stroke-width": 2,
          "stroke-linejoin": "round",
          "stroke-linecap": "round",
        }));
      }

      const windowX = navXScale(viewStart);
      const windowWidth = Math.max(18, navXScale(viewEnd) - navXScale(viewStart));
      navGroup.appendChild(createSvgElement("rect", {
        x: windowX,
        y: 1.5,
        width: windowWidth,
        height: navigatorHeight - 3,
        rx: 9,
        fill: ghostNavigator ? "transparent" : "rgba(37,99,235,0.18)",
        stroke: ghostNavigator ? "transparent" : "#2563eb",
        "stroke-width": 1.8,
      }));
      [windowX, windowX + windowWidth].forEach((handleX) => {
        navGroup.appendChild(createSvgElement("rect", {
          x: handleX - 3,
          y: 8,
          width: 6,
          height: navigatorHeight - 16,
          rx: 3,
          fill: ghostNavigator ? "transparent" : "#2563eb",
        }));
      });
      if (!ghostNavigator) {
        navGroup.appendChild(createSvgElement("text", {
          x: windowX + windowWidth / 2,
          y: navigatorHeight / 2 + 4,
          "text-anchor": "middle",
          class: "navigator-label",
        }, ""));
      }

      const navHit = createSvgElement("rect", {
        x: 0, y: 0, width: innerWidth, height: navigatorHeight,
        fill: "transparent", cursor: "grab",
      });
      let navMode = null;
      const minSize = Math.min(10, rows.length);

      const updateWindowFromClientX = (clientX, rect = svg.getBoundingClientRect()) => {
        const localX = clamp(clientX - rect.left - margin.left, 0, innerWidth);
        const index = clamp(Math.round((localX / innerWidth) * (rows.length - 1)), 0, rows.length - 1);
        let start = viewStart;
        let end = viewEnd;
        if (navMode === "move") {
          const centerOffset = Math.round((view.size - 1) / 2);
          start = clamp(index - centerOffset, 0, Math.max(0, rows.length - view.size));
          end = Math.min(rows.length - 1, start + view.size - 1);
        } else if (navMode === "left") {
          start = clamp(index, 0, Math.max(0, end - minSize + 1));
        } else if (navMode === "right") {
          end = clamp(index, Math.min(rows.length - 1, start + minSize - 1), rows.length - 1);
        } else {
          start = clamp(index - Math.round((view.size - 1) / 2), 0, Math.max(0, rows.length - view.size));
          end = Math.min(rows.length - 1, start + view.size - 1);
        }
        options.onWindowChange?.(start, end - start + 1);
      };

      navHit.addEventListener("pointerdown", (event) => {
        const rect = svg.getBoundingClientRect();
        const localX = clamp(event.clientX - rect.left - margin.left, 0, innerWidth);
        const leftHandle = windowX;
        const rightHandle = windowX + windowWidth;
        if (Math.abs(localX - leftHandle) <= 10) {
          navMode = "left";
        } else if (Math.abs(localX - rightHandle) <= 10) {
          navMode = "right";
        } else if (localX >= windowX && localX <= windowX + windowWidth) {
          navMode = "move";
        } else {
          navMode = "jump";
        }
        navHit.setAttribute("cursor", "grabbing");
        const dragRect = svg.getBoundingClientRect();
        const handleMove = (moveEvent) => {
          if (!navMode) return;
          updateWindowFromClientX(moveEvent.clientX, dragRect);
        };
        const endNavigatorDrag = () => {
          if (!navMode) return;
          navMode = null;
          navHit.setAttribute("cursor", "grab");
          window.removeEventListener("pointermove", handleMove);
          window.removeEventListener("pointerup", endNavigatorDrag);
          window.removeEventListener("pointercancel", endNavigatorDrag);
        };
        window.addEventListener("pointermove", handleMove);
        window.addEventListener("pointerup", endNavigatorDrag);
        window.addEventListener("pointercancel", endNavigatorDrag);
        updateWindowFromClientX(event.clientX, dragRect);
      });
      navHit.addEventListener("dblclick", () => {
        options.onWindowChange?.(0, rows.length);
      });
      navGroup.appendChild(navHit);
    }
    return svg;
  }

  function renderHorizontalBars(rows, config) {
    const container = createElement("div", "bar-list");
    if (!rows.length) {
      container.appendChild(createElement("div", "empty-note", "当前场景没有可展示的数据。"));
      return container;
    }
    const maxValue = Math.max(...rows.map((row) => Number(row[config.valueKey] || 0)), 1);
    rows.forEach((row) => {
      const value = Number(row[config.valueKey] || 0);
      const item = createElement("div", "bar-item");
      const top = createElement("div", "bar-item-top");
      top.appendChild(createElement("span", "", formatBarLabel(row[config.labelKey] || "-")));
      top.appendChild(createElement("strong", "", config.formatter(value)));
      const track = createElement("div", "bar-track");
      const fill = createElement("div", "bar-fill");
      fill.style.width = `${(value / maxValue) * 100}%`;
      fill.style.background = config.color;
      track.appendChild(fill);
      item.append(top, track);
      container.appendChild(item);
    });
    return container;
  }

  function renderMonthlyChart(rows, options = {}) {
    const width = 820;
    const height = 284;
    const margin = { top: 26, right: 18, bottom: 56, left: 64 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const svg = createSvg(width, height, "chart-svg");
    const plot = createSvgElement("g", { transform: `translate(${margin.left},${margin.top})` });
    svg.appendChild(plot);

    if (!rows || !rows.length) {
      svg.appendChild(createSvgElement("text", { x: width / 2, y: height / 2, "text-anchor": "middle", fill: "#64748b" }, "暂无数据"));
      return svg;
    }

    const keys = [
      ["supplier_disrupted_nodes", "#E11D48"],
      ["material_disrupted_nodes", "#B23A48"],
      ["assembly_disrupted_nodes", "#EF4444"],
      ["product_disrupted_nodes", "#374151"],
    ];
    const rowByMonth = new Map(rows.map((row) => [String(row.month || ""), row]));
    const months = (options.months && options.months.length ? options.months : rows.map((row) => String(row.month || ""))).filter(Boolean);
    const rawMaxValue = Math.max(Number(options.maxValue || 0), ...rows.map((row) => Number(row.total_disrupted_nodes || 0)), 1);
    const maxValue = Math.max(rawMaxValue + 2, Math.ceil((rawMaxValue * 1.12) / 2) * 2);
    const band = innerWidth / Math.max(months.length, 1);
    const monthCenterX = (index) => index * band + band * 0.5;
    const barWidth = Math.min(band * 0.42, 96);
    const peakValue = Math.max(...months.map((month) => Number((rowByMonth.get(month) || {}).total_disrupted_nodes || 0)), 0);

    [0, 0.5, 1].forEach((ratio) => {
      const y = innerHeight - ratio * innerHeight;
      plot.appendChild(createSvgElement("line", {
        x1: 0, y1: y, x2: innerWidth, y2: y,
        stroke: "#e2e8f0", "stroke-width": 1,
      }));
      plot.appendChild(createSvgElement("text", {
        x: -10, y: y + 4, "text-anchor": "end",
        fill: "#64748b", "font-size": 13,
      }, compactNumber(maxValue * ratio)));
    });
    plot.appendChild(createSvgElement("line", {
      x1: 0, y1: innerHeight, x2: innerWidth, y2: innerHeight,
      stroke: "#cbd5e1", "stroke-width": 1.2,
    }));
    plot.appendChild(createSvgElement("line", {
      x1: 0, y1: 0, x2: 0, y2: innerHeight,
      stroke: "#cbd5e1", "stroke-width": 1.2,
    }));

    months.forEach((month, index) => {
      const row = rowByMonth.get(month) || { month };
      const centerX = monthCenterX(index);
      const barX = centerX - barWidth / 2;
      let stack = innerHeight;
      keys.forEach(([key, color]) => {
        const value = Number(row[key] || 0);
        const block = (value / maxValue) * innerHeight;
        stack -= block;
        plot.appendChild(createSvgElement("rect", {
          x: barX, y: stack, width: barWidth, height: block, rx: 4, fill: color, opacity: 0.88,
        }));
      });
      const totalValue = Number(row.total_disrupted_nodes || 0);
      const totalY = innerHeight - (totalValue / maxValue) * innerHeight;
      plot.appendChild(createSvgElement("circle", { cx: centerX, cy: totalY, r: 4, fill: "#1D3557" }));
      if (totalValue === peakValue && peakValue > 0) {
        plot.appendChild(createSvgElement("text", {
          x: centerX,
          y: Math.max(totalY - 12, 12),
          "text-anchor": "middle",
          fill: "#1D3557",
          "font-size": 13,
          "font-weight": 700,
        }, `峰值 ${compactNumber(totalValue)}`));
      }
      if (index > 0) {
        const previousMonth = months[index - 1];
        const previous = rowByMonth.get(previousMonth) || { total_disrupted_nodes: 0 };
        const previousY = innerHeight - (Number(previous.total_disrupted_nodes || 0) / maxValue) * innerHeight;
        plot.appendChild(createSvgElement("line", {
          x1: monthCenterX(index - 1), y1: previousY,
          x2: centerX, y2: totalY,
          stroke: "#1D3557", "stroke-width": 2,
        }));
      }
      plot.appendChild(createSvgElement("text", {
        x: centerX, y: innerHeight + 20, "text-anchor": "middle",
        fill: "#64748b", "font-size": 13,
      }, month));
    });
    plot.appendChild(createSvgElement("text", {
      x: innerWidth / 2,
      y: innerHeight + 42,
      "text-anchor": "middle",
      fill: "#64748b",
      "font-size": 14,
    }, "月份"));
    plot.appendChild(createSvgElement("text", {
      x: -innerHeight / 2,
      y: -42,
      transform: "rotate(-90)",
      "text-anchor": "middle",
      fill: "#64748b",
      "font-size": 14,
    }, "节点数"));
    return svg;
  }

  function renderLegend(series) {
    const wrapper = createElement("div", "chart-legend");
    series.forEach((item) => {
      const row = createElement("div", "legend-item");
      const swatch = createElement("span", "legend-swatch");
      swatch.style.background = item.color;
      row.append(swatch, createElement("span", "", item.label));
      wrapper.appendChild(row);
    });
    return wrapper;
  }

  function selectorNodeShape(node) {
    const common = {
      fill: "#ffffff",
      stroke: node.is_key_node ? "#FF2DAA" : "#334155",
      "stroke-width": node.is_key_node ? 2.4 : 1.4,
    };
    if (node.node_type === "supplier") {
      return createSvgElement("circle", { cx: 0, cy: 0, r: 9, ...common });
    }
    if (node.node_type === "assembly") {
      return createSvgElement("polygon", { points: "0,-11 11,0 0,11 -11,0", ...common });
    }
    if (node.node_type === "product") {
      return createSvgElement("polygon", { points: "0,-12 11,9 -11,9", ...common });
    }
    return createSvgElement("rect", { x: -9, y: -9, width: 18, height: 18, rx: 3, ...common });
  }

  function createViewport(total, selectedIndex) {
    const size = clamp(Math.min(18, Math.max(10, total || 1)), 1, Math.max(total || 1, 1));
    return normalizeViewport({ start: Math.max(0, selectedIndex - Math.floor(size / 2)), size }, total, selectedIndex);
  }

  function normalizeViewport(viewport, total, selectedIndex) {
    const safeTotal = Math.max(total || 1, 1);
    const size = clamp(Number(viewport?.size || Math.min(18, safeTotal)), 1, safeTotal);
    const maxStart = Math.max(0, safeTotal - size);
    let start = clamp(Number(viewport?.start || 0), 0, maxStart);
    if (Number.isFinite(selectedIndex) && (selectedIndex < start || selectedIndex > start + size - 1)) {
      start = clamp(selectedIndex - Math.floor(size / 2), 0, maxStart);
    }
    return { start, size };
  }

  function ensureViewportContains(viewport, total, selectedIndex) {
    return normalizeViewport(viewport, total, selectedIndex);
  }

  function resolveDailyNetworkState(dailyStates, selectedDate) {
    if (!dailyStates || !dailyStates.length) {
      return { node_status: {}, edge_status: {} };
    }
    const exact = dailyStates.find((item) => item.date === selectedDate);
    if (exact) {
      return exact;
    }
    let current = dailyStates[0];
    dailyStates.forEach((item) => {
      if (String(item.date) <= String(selectedDate)) {
        current = item;
      }
    });
    return current;
  }

  function edgeStyle(status) {
    const normalized = String(status || "active").toLowerCase();
    if (normalized === "backup_active") return { stroke: "#277DA1", width: 2.2, dash: "", opacity: 0.82 };
    if (normalized === "substituted") return { stroke: "#8E44AD", width: 2.2, dash: "", opacity: 0.82 };
    if (normalized === "standby") return { stroke: "#9AA9BA", width: 1.2, dash: "6 4", opacity: 0.48 };
    if (normalized === "disrupted") return { stroke: "#C1121F", width: 1.45, dash: "3 3", opacity: 0.68 };
    return { stroke: "#8FA3B8", width: 1.05, dash: "", opacity: 0.42 };
  }

  function edgePriority(status) {
    const normalized = String(status || "active").toLowerCase();
    if (normalized === "active") return 0;
    if (normalized === "standby") return 1;
    if (normalized === "disrupted") return 2;
    if (normalized === "backup_active") return 3;
    if (normalized === "substituted") return 4;
    return 0;
  }

  function nodeStatusColor(status) {
    const normalized = String(status || "stable").toLowerCase();
    if (normalized === "available" || normalized === "active") return "#22C55E";
    if (normalized === "affected" || normalized === "degraded") return "#FFB703";
    if (normalized === "disrupted" || normalized === "blocked") return "#9A3412";
    if (normalized === "recovering") return "#60A5FA";
    return "#94A3B8";
  }

  function networkFilterOptions() {
    const base = contract.network_filters || [];
    if (base.some((item) => item.value === "process")) {
      return base;
    }
    return [{ value: "process", label: "当前过程" }, ...base];
  }

  function recoveryNetworkFilterOptions() {
    return [
      { value: "recovery", label: "恢复动作总览" },
      { value: "backup", label: "备供切换" },
      { value: "substitution", label: "等效替代" },
      { value: "repair", label: "优先抢修" },
      { value: "unresolved", label: "仍未恢复" },
    ];
  }

  function policyProfileOptions() {
    return contract.policy_profiles || [];
  }

  function policyProfileLabel(value, fallbackLabel) {
    if (value === "time_priority_interrupt") {
      return "当前恢复策略";
    }
    const match = policyProfileOptions().find((item) => item.value === value);
    return match ? match.label : fallbackLabel || value || "未指定";
  }

  function getSelectedNodes(family) {
    const value = state.selectedNodeByFamily[family];
    const selected = Array.isArray(value) ? value.filter(Boolean) : (value ? [value] : []);
    return selected.filter((node) => isNodeSelectableForWhatIf(family, node));
  }

  function toggleSelectedNode(family, node, forceAdd = false) {
    if (!isNodeSelectableForWhatIf(family, node)) {
      return false;
    }
    const selected = getSelectedNodes(family);
    const exists = selected.some((item) => item.node_key === node.node_key);
    if (exists && !forceAdd) {
      state.selectedNodeByFamily[family] = selected.filter((item) => item.node_key !== node.node_key);
      return true;
    }
    if (!exists) {
      state.selectedNodeByFamily[family] = [...selected, node];
    }
    return true;
  }

  function isNodeSelectableForWhatIf(family, node) {
    if (!node) return false;
    if (family === "random") {
      return !Boolean(node.is_key_node);
    }
    if (family === "keynode") {
      return Boolean(node.is_key_node);
    }
    return true;
  }

  function selectionRuleText(family) {
    if (family === "random") {
      return "随机中断情境只能选择非关键节点。";
    }
    if (family === "keynode") {
      return "关键节点中断情境只能选择关键节点。";
    }
    return "请按当前情境规则选择可中断节点。";
  }

  function isDisruptedStatus(status) {
    return ["disrupted", "blocked", "affected", "degraded", "recovering"].includes(String(status || "").toLowerCase());
  }

  function isPolicyEdgeStatus(status) {
    return ["backup_active", "substituted", "standby"].includes(String(status || "").toLowerCase());
  }

  function nodeMatchesFilter(node, status, filterValue) {
    const normalized = String(filterValue || "all").toLowerCase();
    if (normalized === "all") return true;
    if (normalized === "process") return isDisruptedStatus(status);
    if (normalized === "key") return Boolean(node.is_key_node);
    if (normalized === "disrupted") return isDisruptedStatus(status);
    if (normalized === "supplier") return node.node_type === "supplier";
    if (normalized === "item") return node.node_type !== "supplier";
    if (normalized === "policy") return Boolean(node.is_key_node) || isDisruptedStatus(status);
    return true;
  }

  function edgeMatchesFilter(edge, source, target, status, filterValue, current) {
    const normalized = String(filterValue || "all").toLowerCase();
    const sourceStatus = (current.node_status || {})[source.node_key] || "stable";
    const targetStatus = (current.node_status || {})[target.node_key] || "stable";
    if (normalized === "all") return true;
    if (normalized === "process") {
      const hasProcess = Object.values(current.node_status || {}).some((item) => isDisruptedStatus(item))
        || Object.values(current.edge_status || {}).some((item) => String(item || "").toLowerCase() === "disrupted" || isPolicyEdgeStatus(item));
      if (!hasProcess) return true;
      return String(status || "").toLowerCase() === "disrupted"
        || isPolicyEdgeStatus(status)
        || isDisruptedStatus(sourceStatus)
        || isDisruptedStatus(targetStatus);
    }
    if (normalized === "key") return Boolean(source.is_key_node || target.is_key_node);
    if (normalized === "disrupted") return isDisruptedStatus(sourceStatus) || isDisruptedStatus(targetStatus) || String(status || "").toLowerCase() === "disrupted";
    if (normalized === "supplier") return source.node_type === "supplier" || target.node_type === "supplier";
    if (normalized === "item") return source.node_type !== "supplier" && target.node_type !== "supplier";
    if (normalized === "policy") return isPolicyEdgeStatus(status);
    return true;
  }

  function collectRelatedNodeKeys(edges, focusedEntityId, nodeByKey) {
    if (!focusedEntityId) {
      return null;
    }
    const match = Array.from(nodeByKey.values()).find((node) => node.entity_id === focusedEntityId);
    if (!match) {
      return null;
    }
    const related = new Set([match.node_key]);
    (edges || []).forEach((edge) => {
      if (edge.source_key === match.node_key || edge.target_key === match.node_key) {
        related.add(edge.source_key);
        related.add(edge.target_key);
      }
    });
    return related;
  }

  function collectProcessFocusKeys(edges, current, nodeByKey) {
    const focused = new Set();
    Object.entries(current.node_status || {}).forEach(([nodeKey, status]) => {
      if (isDisruptedStatus(status)) {
        focused.add(nodeKey);
      }
    });
    (edges || []).forEach((edge) => {
      const edgeStatus = (current.edge_status || {})[edge.edge_key];
      if (
        String(edgeStatus || "").toLowerCase() === "disrupted"
        || isPolicyEdgeStatus(edgeStatus)
        || focused.has(edge.source_key)
        || focused.has(edge.target_key)
      ) {
        focused.add(edge.source_key);
        focused.add(edge.target_key);
      }
    });
    return focused.size ? focused : null;
  }

  function buildRecoveryContext(scene, network, current, selectedDate) {
    const nodes = network?.nodes || [];
    const edges = network?.edges || [];
    const nodeByEntity = new Map(nodes.map((node) => [String(node.entity_id || ""), node]));
    const backupEdgeKeys = new Set();
    const substitutionEdgeKeys = new Set();
    const backupNodeKeys = new Set();
    const substitutionNodeKeys = new Set();
    const recoveringKeys = new Set();
    const recoveredKeys = new Set();
    const unresolvedKeyKeys = new Set();
    const repairNodeKeys = new Set();

    Object.entries(current?.edge_status || {}).forEach(([edgeKey, status]) => {
      const normalized = String(status || "").toLowerCase();
      const edge = edges.find((item) => item.edge_key === edgeKey);
      if (normalized === "backup_active") {
        backupEdgeKeys.add(edgeKey);
        if (edge) {
          backupNodeKeys.add(edge.source_key);
          backupNodeKeys.add(edge.target_key);
        }
      }
      if (normalized === "substituted") {
        substitutionEdgeKeys.add(edgeKey);
        if (edge) {
          substitutionNodeKeys.add(edge.source_key);
          substitutionNodeKeys.add(edge.target_key);
        }
      }
    });

    Object.entries(current?.node_status || {}).forEach(([nodeKey, status]) => {
      const normalized = String(status || "").toLowerCase();
      const node = nodes.find((item) => item.node_key === nodeKey);
      if (normalized === "recovering") {
        recoveringKeys.add(nodeKey);
        repairNodeKeys.add(nodeKey);
      }
      if (node?.is_key_node && ["disrupted", "blocked", "affected", "degraded", "recovering"].includes(normalized)) {
        unresolvedKeyKeys.add(nodeKey);
      }
    });

    (scene.policy_events || []).forEach((row) => {
      if (!row.date || String(row.date) > String(selectedDate)) {
        return;
      }
      const targetNode = nodeByEntity.get(String(row.target_id || ""));
      if (String(row.policy_type) === "backup_supplier_switch") {
        if (targetNode) {
          backupNodeKeys.add(targetNode.node_key);
        }
        const supplierNode = nodeByEntity.get(String(row.supplier_id || ""));
        if (supplierNode) {
          backupNodeKeys.add(supplierNode.node_key);
        }
        return;
      }
      if (String(row.policy_type) === "equivalent_material_substitution") {
        if (targetNode) {
          substitutionNodeKeys.add(targetNode.node_key);
        }
        const substituteNode = nodeByEntity.get(String(row.substitute_item_id || row.source_item_id || ""));
        if (substituteNode) {
          substitutionNodeKeys.add(substituteNode.node_key);
        }
        return;
      }
      if (String(row.policy_type) !== "priority_repair" || !targetNode) {
        return;
      }
      repairNodeKeys.add(targetNode.node_key);
      if (row.activate_date && String(row.activate_date) <= String(selectedDate)) {
        const currentStatus = String((current?.node_status || {})[targetNode.node_key] || "").toLowerCase();
        if (["stable", "available", "active"].includes(currentStatus)) {
          recoveredKeys.add(targetNode.node_key);
        } else {
          recoveringKeys.add(targetNode.node_key);
        }
      }
    });

    const recoveryNodeKeys = new Set([
      ...backupNodeKeys,
      ...substitutionNodeKeys,
      ...recoveringKeys,
      ...recoveredKeys,
      ...unresolvedKeyKeys,
      ...repairNodeKeys,
    ]);
    const recoveryEdgeKeys = new Set([...backupEdgeKeys, ...substitutionEdgeKeys]);
    edges.forEach((edge) => {
      if (
        recoveryNodeKeys.has(edge.source_key)
        || recoveryNodeKeys.has(edge.target_key)
        || recoveryEdgeKeys.has(edge.edge_key)
      ) {
        recoveryNodeKeys.add(edge.source_key);
        recoveryNodeKeys.add(edge.target_key);
      }
    });

    return {
      backupEdgeKeys,
      substitutionEdgeKeys,
      backupNodeKeys,
      substitutionNodeKeys,
      recoveringKeys,
      recoveredKeys,
      unresolvedKeyKeys,
      repairNodeKeys,
      recoveryNodeKeys,
      recoveryEdgeKeys,
    };
  }

  function collectRecoveryFocusKeys(network, context) {
    if (!context) {
      return null;
    }
    const focused = new Set(context.recoveryNodeKeys);
    (network?.edges || []).forEach((edge) => {
      if (
        context.recoveryEdgeKeys.has(edge.edge_key)
        || focused.has(edge.source_key)
        || focused.has(edge.target_key)
      ) {
        focused.add(edge.source_key);
        focused.add(edge.target_key);
      }
    });
    return focused.size ? focused : null;
  }

  function nodeMatchesRecoveryFilter(node, filterValue, context) {
    if (!context) {
      return true;
    }
    const normalized = String(filterValue || "recovery").toLowerCase();
    if (normalized === "recovery") return context.recoveryNodeKeys.has(node.node_key);
    if (normalized === "backup") return context.backupNodeKeys.has(node.node_key);
    if (normalized === "substitution") return context.substitutionNodeKeys.has(node.node_key);
    if (normalized === "repair") return context.repairNodeKeys.has(node.node_key) || context.recoveringKeys.has(node.node_key) || context.recoveredKeys.has(node.node_key);
    if (normalized === "unresolved") return context.unresolvedKeyKeys.has(node.node_key);
    return true;
  }

  function edgeMatchesRecoveryFilter(edge, filterValue, context) {
    if (!context) {
      return true;
    }
    const normalized = String(filterValue || "recovery").toLowerCase();
    if (normalized === "recovery") {
      return context.recoveryEdgeKeys.has(edge.edge_key)
        || context.recoveryNodeKeys.has(edge.source_key)
        || context.recoveryNodeKeys.has(edge.target_key);
    }
    if (normalized === "backup") {
      return context.backupEdgeKeys.has(edge.edge_key)
        || context.backupNodeKeys.has(edge.source_key)
        || context.backupNodeKeys.has(edge.target_key);
    }
    if (normalized === "substitution") {
      return context.substitutionEdgeKeys.has(edge.edge_key)
        || context.substitutionNodeKeys.has(edge.source_key)
        || context.substitutionNodeKeys.has(edge.target_key);
    }
    if (normalized === "repair") {
      return context.repairNodeKeys.has(edge.source_key) || context.repairNodeKeys.has(edge.target_key);
    }
    if (normalized === "unresolved") {
      return context.unresolvedKeyKeys.has(edge.source_key) || context.unresolvedKeyKeys.has(edge.target_key);
    }
    return true;
  }

  function getRecentRecoveryEvents(scene, selectedDate, limit = 3) {
    return (scene.policy_events || [])
      .filter((row) => String(row.date || "") <= String(selectedDate))
      .slice()
      .sort((a, b) => String(b.activate_date || b.date || "").localeCompare(String(a.activate_date || a.date || "")))
      .slice(0, limit);
  }

  function resolveDominantRecoveryAction(row) {
    const options = [
      { key: "active_substitutions", label: "等效替代优先缓解" },
      { key: "active_backup_switches", label: "备供切换补位" },
      { key: "active_priority_repairs", label: "优先抢修并行" },
    ];
    const top = options
      .map((item) => ({ ...item, value: Number(row?.[item.key] || 0) }))
      .sort((left, right) => right.value - left.value)[0];
    if (top && top.value > 0) {
      return top.label;
    }
    if (Number(row?.policy_cumulative_cost || 0) > 0) {
      return "恢复动作推进中";
    }
    return "恢复准备中";
  }

  function adjustNetworkZoom(family, delta) {
    const current = state.networkViewByFamily[family] || { scale: 1, panX: 0, panY: 0 };
    state.networkViewByFamily[family] = {
      ...current,
      scale: clamp(Number(current.scale || 1) + delta, 0.7, 2.4),
    };
    renderApp();
  }

  function buildSceneSummaryCard(scene) {
    const card = createElement("article", "scene-card");
    card.style.background = scene.accent_soft;
    const header = createElement("div", "scene-card-header");
    const group = createElement("div");
    group.appendChild(createElement("p", "eyebrow", scene.label));
    group.appendChild(createElement("h3", "", scene.scenario.scenario_name || scene.scenario.scenario_id || "-"));
    header.appendChild(group);
    const tag = createElement("span", "scene-type-tag", scenarioTypeDisplay(scene.scenario));
    tag.style.background = scene.accent;
    header.appendChild(tag);
    card.appendChild(header);
    const meta = createElement("div", "scene-meta");
    meta.appendChild(metaItem("开始日期", formatDate(scene.scenario.start_date)));
    meta.appendChild(metaItem("目标对象", formatScenarioTargetDisplay(scene.scenario, scene)));
    meta.appendChild(metaItem("恢复天数", `${scene.summary.ttr_days ?? "-"} 天`));
    meta.appendChild(metaItem("平均服务水平", formatPercent(scene.summary.average_service_level)));
    card.appendChild(meta);
    return card;
  }

  function createSectionHead(eyebrow, title) {
    const head = createElement("div", "section-head");
    const box = createElement("div");
    if (eyebrow) {
      box.appendChild(createElement("p", "eyebrow", eyebrow));
    }
    box.appendChild(createElement("h2", "", title));
    head.appendChild(box);
    return head;
  }

  function createScenarioSummaryHead(title) {
    const text = String(title || "").trim();
    const suffix = "节点中断推演";
    const nodeName = text.endsWith(suffix) ? text.slice(0, -suffix.length).trim() : text;
    const head = createElement("div", "section-head scenario-summary-head");
    const heading = createElement("h2", "scenario-title-line");
    const name = createElement("span", "scenario-title-node", nodeName || "-");
    const tag = createElement("span", "scenario-title-suffix", suffix);
    name.title = nodeName || "-";
    tag.title = suffix;
    heading.title = text || suffix;
    heading.append(name, tag);
    head.appendChild(heading);
    return head;
  }

  function scenarioTypeDisplay(scenario) {
    const scenarioType = String(scenario?.scenario_type || "");
    const scenarioTypeName = String(scenario?.scenario_type_name || "");
    if (scenarioType === "random_distributed_node_disruption") {
      return "随机中断";
    }
    if (scenarioType === "keynode_distributed_disruption") {
      return "关键节点中断";
    }
    if (scenarioTypeName.includes("集中中断")) {
      return scenarioTypeName.replace("集中中断", "中断");
    }
    return scenarioTypeName || scenarioType || "情境";
  }

  /*
   * Inactive duplicate: final createChartHead definition lives later.
   *
  function createChartHead(title, note) {
    const head = createElement("div", "chart-head");
    const box = createElement("div");
    box.appendChild(createElement("h3", "", title));
    if (note) {
      box.appendChild(createElement("div", "chart-note", note));
    }
    head.appendChild(box);
    return head;
  }
  */

  function formatScenarioTarget(scenario) {
    const targetType = translateTargetType(scenario?.target_type);
    const rawTarget = String(scenario?.target_id || "-");
    const readableTarget = rawTarget.replace(/,/g, "、");
    const compactTarget = readableTarget.length > 34 ? `${readableTarget.slice(0, 34)}…` : readableTarget;
    return `${targetType} / ${compactTarget}`;
  }

  function extractEntityDisplayName(label, entityId) {
    const idText = String(entityId || "").trim();
    const raw = String(label || "").replace(/\r/g, "").trim();
    if (!raw) {
      return "";
    }
    const parts = raw.split("\n").map((item) => item.trim()).filter(Boolean);
    const namedPart = parts.find((item) => item !== "..." && item !== "…" && !item.includes(idText));
    if (namedPart) {
      return namedPart;
    }
    const fallback = parts[parts.length - 1] || raw;
    if (fallback === "..." || fallback === "…") {
      return "";
    }
    const cleaned = fallback.replace(/^关键\s*/u, "").replace(idText, "").trim();
    return cleaned || "";
  }

  function buildSceneEntityNameMap(scene) {
    const map = new Map();
    Object.entries(dashboardData?.entity_name_lookup || {}).forEach(([entityId, entityName]) => {
      const id = String(entityId || "").trim();
      const name = String(entityName || "").trim();
      if (id && name && name !== "..." && name !== "…") {
        map.set(id, name);
      }
    });
    const nodes = scene?.interactive_network?.nodes || [];
    nodes.forEach((node) => {
      const entityId = String(node.entity_id || "").trim();
      if (!entityId || map.has(entityId)) {
        return;
      }
      const displayName = extractEntityDisplayName(node.short_label || node.label, entityId);
      if (displayName) {
        map.set(entityId, displayName);
      }
    });
    return map;
  }

  function formatScenarioTargetDisplay(scenario, scene) {
    const targetType = translateTargetType(scenario?.target_type);
    const rawTarget = String(scenario?.target_id || "-");
    const ids = rawTarget.split(/[,\s，、]+/u).map((item) => item.trim()).filter(Boolean);
    const entityNameMap = buildSceneEntityNameMap(scene);
    const names = (ids.length ? ids : [rawTarget]).map((item) => entityNameMap.get(item)).filter(Boolean);
    if (!names.length) {
      return targetType.includes("集合") ? "" : targetType;
    }
    const shownNames = names.slice(0, 3);
    const suffix = names.length > shownNames.length ? `等${names.length}个` : "";
    return `${shownNames.join("、")}${suffix}`;
  }

  function formatEntityName(entityId, scene) {
    const id = String(entityId || "").trim();
    if (!id || id === "-") {
      return "-";
    }
    const globalName = dashboardData?.entity_name_lookup?.[id];
    if (globalName) {
      return String(globalName);
    }
    return buildSceneEntityNameMap(scene).get(id) || id;
  }

  function formatNodeName(node, scene) {
    if (!node) {
      return "-";
    }
    const entityId = String(node.entity_id || "").trim();
    const directName = extractEntityDisplayName(node.short_label || node.label, entityId);
    return directName || formatEntityName(entityId, scene);
  }

  function formatEntityListText(value, scene, maxShown = 3) {
    const ids = String(value || "")
      .split(/[,\s，、]+/u)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!ids.length) {
      return "-";
    }
    const names = ids.map((id) => formatEntityName(id, scene));
    const shown = names.slice(0, maxShown);
    const suffix = names.length > shown.length ? `等${names.length}个` : "";
    return `${shown.join("、")}${suffix}`;
  }

  function replaceEntityIdsWithNames(value, scene) {
    return String(value || "-").replace(/\b(?:SID|MID)\d{4}\b/g, (entityId) => formatEntityName(entityId, scene));
  }

  function shortDisplayName(value, maxLength = 8) {
    const text = String(value || "-").replace(/^关键\s*/u, "").trim() || "-";
    return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
  }

  function nodeTitleText(node, status, scene) {
    const parts = [formatNodeName(node, scene), translateNodeType(node?.node_type)];
    if (status) {
      parts.push(translateVisualStatus(status));
    }
    if (node?.is_key_node) {
      parts.push("关键节点");
    }
    return parts.filter(Boolean).join(" · ");
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }
    return element;
  }

  function createSvg(width, height, className) {
    return createSvgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      class: className,
      xmlns: "http://www.w3.org/2000/svg",
    });
  }

  function createSvgElement(tagName, attributes, text) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tagName);
    Object.entries(attributes || {}).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }
    return element;
  }

  function metaItem(label, value) {
    const item = createElement("div", "meta-item");
    item.appendChild(createElement("span", "", label));
    item.appendChild(createElement("strong", "", value));
    return item;
  }

  function kpiMini(label, value) {
    const item = createElement("div", "kpi-mini");
    item.appendChild(createElement("span", "", label));
    item.appendChild(createElement("strong", "", value));
    return item;
  }

  function detailCard(label, value) {
    const card = createElement("div", "detail-card");
    card.appendChild(createElement("span", "", label));
    const strong = createElement("strong", "", value);
    strong.title = String(value ?? "");
    card.appendChild(strong);
    return card;
  }

  function graphBounds(nodes) {
    const xs = nodes.map((node) => Number(node.x || 0));
    const ys = nodes.map((node) => Number(node.y || 0));
    return {
      minX: Math.min(...xs, 0),
      maxX: Math.max(...xs, 1),
      minY: Math.min(...ys, 0),
      maxY: Math.max(...ys, 1),
    };
  }

  function createLinearScale(domainMin, domainMax, rangeMin, rangeMax) {
    if (domainMin === domainMax) {
      const middle = (rangeMin + rangeMax) / 2;
      return () => middle;
    }
    return (value) => rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
  }

  function createInverseLinearScale(domainMin, domainMax, rangeMin, rangeMax) {
    if (rangeMin === rangeMax) {
      const middle = (domainMin + domainMax) / 2;
      return () => middle;
    }
    return (value) => domainMin + ((value - rangeMin) / (rangeMax - rangeMin)) * (domainMax - domainMin);
  }

  function sceneLayoutKey(family) {
    return `${family}:${state.resultModeByFamily[family]}`;
  }

  function applyLayoutOverrides(nodes, overrides) {
    return (nodes || []).map((node) => {
      const override = overrides?.[node.node_key];
      return override ? { ...node, x: override.x, y: override.y } : { ...node };
    });
  }

  function svgLocalPoint(svg, clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    const viewBox = svg.viewBox.baseVal;
    return {
      x: ((clientX - rect.left) / rect.width) * viewBox.width,
      y: ((clientY - rect.top) / rect.height) * viewBox.height,
    };
  }

  function attachNodeDrag(group, context) {
    const {
      node,
      family,
      layoutKey,
      svg,
      scaleX,
      scaleY,
      inverseX,
      inverseY,
      nodesByKey,
      edges,
      edgeRefs,
      onClick,
    } = context;
    let dragging = false;
    let moved = false;

    const updateEdges = () => {
      edges.forEach((edge) => {
        if (edge.source_key !== node.node_key && edge.target_key !== node.node_key) return;
        const line = edgeRefs.get(edge.edge_key);
        if (!line) return;
        const source = nodesByKey.get(edge.source_key);
        const target = nodesByKey.get(edge.target_key);
        line.setAttribute("x1", String(scaleX(source.x)));
        line.setAttribute("y1", String(scaleY(source.y)));
        line.setAttribute("x2", String(scaleX(target.x)));
        line.setAttribute("y2", String(scaleY(target.y)));
      });
    };

    group.addEventListener("pointerdown", (event) => {
      dragging = true;
      moved = false;
      group.setPointerCapture?.(event.pointerId);
      group.setAttribute("cursor", "grabbing");
      event.preventDefault();
      event.stopPropagation();
    });
    group.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      moved = true;
      const point = svgLocalPoint(svg, event.clientX, event.clientY);
      const currentView = state.networkViewByFamily[family] || { scale: 1, panX: 0, panY: 0 };
      const normalizedX = (point.x - Number(currentView.panX || 0)) / Math.max(Number(currentView.scale || 1), 0.01);
      const normalizedY = (point.y - Number(currentView.panY || 0)) / Math.max(Number(currentView.scale || 1), 0.01);
      const nextX = inverseX(normalizedX);
      const nextY = inverseY(normalizedY);
      node.x = nextX;
      node.y = nextY;
      nodesByKey.set(node.node_key, node);
      group.setAttribute("transform", `translate(${scaleX(node.x)},${scaleY(node.y)})`);
      updateEdges();
    });
    const finishDrag = (event) => {
      if (!dragging) return;
      dragging = false;
      group.releasePointerCapture?.(event.pointerId);
      group.setAttribute("cursor", "grab");
      if (moved) {
        state.layoutOverridesByScene[layoutKey] = {
          ...(state.layoutOverridesByScene[layoutKey] || {}),
          [node.node_key]: { x: node.x, y: node.y },
        };
      } else {
        onClick?.();
      }
    };
    group.addEventListener("pointerup", finishDrag);
    group.addEventListener("pointercancel", finishDrag);
    group.addEventListener("lostpointercapture", () => {
      dragging = false;
      group.setAttribute("cursor", "grab");
    });
  }

  function attachNetworkViewportHandlers(svg, backdrop, camera, family) {
    const syncCamera = (nextView) => {
      state.networkViewByFamily[family] = nextView;
      camera.setAttribute("transform", `translate(${nextView.panX},${nextView.panY}) scale(${nextView.scale})`);
    };
    let panning = false;
    let startPoint = null;
    let startView = null;
    backdrop.addEventListener("pointerdown", (event) => {
      if (event.target !== backdrop) {
        return;
      }
      panning = true;
      startPoint = svgLocalPoint(svg, event.clientX, event.clientY);
      startView = { ...(state.networkViewByFamily[family] || { scale: 1, panX: 0, panY: 0 }) };
      backdrop.setPointerCapture?.(event.pointerId);
      backdrop.setAttribute("cursor", "grabbing");
    });
    backdrop.addEventListener("pointermove", (event) => {
      if (!panning || !startPoint || !startView) {
        return;
      }
      const point = svgLocalPoint(svg, event.clientX, event.clientY);
      syncCamera({
        ...startView,
        panX: startView.panX + (point.x - startPoint.x),
        panY: startView.panY + (point.y - startPoint.y),
      });
    });
    const finishPan = (event) => {
      if (!panning) {
        return;
      }
      panning = false;
      startPoint = null;
      startView = null;
      backdrop.releasePointerCapture?.(event.pointerId);
      backdrop.setAttribute("cursor", "grab");
    };
    backdrop.addEventListener("pointerup", finishPan);
    backdrop.addEventListener("pointercancel", finishPan);
    backdrop.addEventListener("lostpointercapture", () => {
      panning = false;
      startPoint = null;
      startView = null;
      backdrop.setAttribute("cursor", "grab");
    });
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const point = svgLocalPoint(svg, event.clientX, event.clientY);
      const current = state.networkViewByFamily[family] || { scale: 1, panX: 0, panY: 0 };
      const nextScale = clamp(Number(current.scale || 1) + (event.deltaY > 0 ? -0.08 : 0.08), 0.7, 2.4);
      const ratio = nextScale / Math.max(Number(current.scale || 1), 0.01);
      syncCamera({
        scale: nextScale,
        panX: point.x - (point.x - current.panX) * ratio,
        panY: point.y - (point.y - current.panY) * ratio,
      });
    }, { passive: false });
  }

  function shortDate(value) {
    const text = String(value || "");
    return text.length >= 10 ? text.slice(5) : text;
  }

  function formatDate(value) {
    if (!value) return "-";
    const text = String(value);
    return text.length >= 10 ? text.slice(0, 10) : text;
  }

  function formatInteger(value) {
    return Number.isFinite(Number(value)) ? `${Math.round(Number(value))}` : "-";
  }

  function formatNumber(value, digits = 2) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(digits).replace(/\.00$/, "") : "-";
  }

  function formatPercent(value, digits = 1) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(digits).replace(/\.0$/, "")}%` : "-";
  }

  function formatCurrency(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `¥${numeric.toFixed(0)}` : "-";
  }

  function formatByMode(value, mode) {
    if (mode === "percent") return formatPercent(value);
    if (mode === "currency") return formatCurrency(value);
    if (mode === "days") return `${formatInteger(value)} 天`;
    return formatNumber(value);
  }

  function formatBarLabel(value) {
    const map = {
      backup_coverage: "备用覆盖率",
      priority_repair_lead_days: "优先抢修提前天数",
      priority_repair_days: "优先抢修天数",
      backup_switch_time_days: "备供切换耗时",
      substitution_availability: "等效替代可用率",
    };
    return map[String(value || "")] || String(value || "-");
  }

  function compactNumber(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    if (Math.abs(numeric) >= 10000) return `${(numeric / 10000).toFixed(1)}万`;
    return `${Math.round(numeric)}`;
  }

  function dayDistance(dateA, dateB) {
    const a = new Date(String(dateA));
    const b = new Date(String(dateB));
    return Math.round((a - b) / 86400000);
  }

  function uniqueSorted(values) {
    return Array.from(new Set(values.filter((value) => Number.isFinite(value) && value >= 0))).sort((a, b) => a - b);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function debounce(fn, wait) {
    let timer = null;
    return function debounced() {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(), wait);
    };
  }

  function buildStageCaption(stage, scene) {
    if (!stage || !stage.snapshot_name) return "当前日期尚未对应到关键阶段。";
    if (scene.interactive_network) {
      return `当前日期已切换到“${stageShortLabel(stage)}”阶段，并按日更新节点与边状态。`;
    }
    return `当前日期映射到“${stageShortLabel(stage)}”阶段，展示对应网络状态。`;
  }

  function stageDisplayTitle(stage) {
    return cleanStageText(stage?.snapshot_title || stageShortLabel(stage) || "阶段");
  }

  function cleanStageText(value) {
    return String(value || "")
      .replace(/网络快照/g, "网络状态")
      .replace(/快照/g, "状态")
      .replace(/状态状态/g, "状态");
  }

  function badgeColor(dimension) {
    const key = String(dimension || "").toLowerCase();
    if (key.includes("supply") || key.includes("供应")) return "#2A6F97";
    if (key.includes("demand") || key.includes("需求")) return "#F59E0B";
    return "#C8553D";
  }

  function policyColor(profile) {
    const map = {
      time_priority_interrupt: "#0F766E",
      baseline: "#166534",
      all_policies: "#1D4ED8",
      no_policy: "#D62828",
      only_backup_switch: "#F97316",
      only_substitution: "#A855F7",
      only_priority_repair: "#0891B2",
    };
    return map[String(profile)] || "#334155";
  }

  function pageAccent(pageKey) {
    if (pageKey === "overview") return "#111827";
    if (pageKey === "random") return "#0F766E";
    if (pageKey === "keynode") return "#B91C1C";
    if (pageKey === "map") return "#2563EB";
    return "#1D4ED8";
  }

  function stageShortLabel(snapshot) {
    const key = String(snapshot?.snapshot_name || "");
    const map = {
      t0: "冲击前",
      t_start: "冲击开始",
      t_supply_peak: "冲击峰值",
      t_policy_start: "恢复动作启动",
      t_recovery: "业务恢复",
    };
    return map[key] || cleanStageText(snapshot?.snapshot_title || "阶段");
  }

  function translateTargetType(value) {
    const map = {
      node_group: "节点集合",
      supplier_group: "供应商集合",
      supplier: "供应商",
      item: "物料",
      assembly: "装配件",
      product: "产品",
    };
    return map[String(value || "")] || String(value || "-");
  }

  function translateNodeType(value) {
    const map = {
      supplier: "供应商",
      material: "物料",
      assembly: "装配件",
      product: "产品",
    };
    return map[String(value || "")] || String(value || "-");
  }

  function translateVisualStatus(value) {
    const map = {
      available: "可用",
      active: "可用",
      affected: "受影响",
      degraded: "降级",
      disrupted: "中断",
      blocked: "阻断",
      recovering: "恢复中",
      stable: "稳定",
      standby: "待命",
      backup_active: "备用已激活",
      substituted: "已替代",
    };
    return map[String(value || "").toLowerCase()] || String(value || "-");
  }

  function translateImpactDimension(value) {
    const map = {
      supply: "供应",
      demand: "需求",
      fusion: "融合",
    };
    return map[String(value || "").toLowerCase()] || String(value || "-");
  }

  function translateImpactStatus(value) {
    const map = {
      failed: "失败",
      unavailable: "不可用",
      backlog: "积压",
      affected: "受影响",
      blocked: "阻断",
      lost: "损失",
    };
    return map[String(value || "").toLowerCase()] || String(value || "-");
  }

  function translateImpactLevel(value) {
    const map = {
      material: "物料",
      assembly: "装配件",
      product: "产品",
      supplier: "供应商",
    };
    return map[String(value || "").toLowerCase()] || String(value || "-");
  }

  function translateRootCause(value) {
    const map = {
      supply_constraint: "供应约束",
      demand_constraint: "需求约束",
      fusion_failure: "融合失败",
    };
    return map[String(value || "").toLowerCase()] || "未标注";
  }

  function translatePolicyType(value) {
    const map = {
      backup_supplier_switch: "备供切换",
      equivalent_material_substitution: "等效替代",
      priority_repair: "优先抢修",
    };
    return map[value] || value || "恢复事件";
  }

  function translatePolicyAction(value) {
    const map = {
      schedule_supplier_repair: "安排供应商修复",
      schedule_material_repair: "安排物料修复",
      schedule_backup_switch: "安排备供切换",
      schedule_substitution: "安排等效替代",
      activate_backup_switch: "激活备供切换",
      activate_substitution: "激活等效替代",
      activate_priority_repair: "激活优先抢修",
    };
    return map[String(value || "").toLowerCase()] || "执行";
  }

  function resolveApiBase() {
    if (window.location && /^https?:$/i.test(window.location.protocol)) {
      return window.location.origin;
    }
    return "http://127.0.0.1:8765";
  }

  function buildApiUrl(pathname) {
    return new URL(pathname, state.apiBase).toString();
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload && payload.error ? payload.error : `请求失败（状态码 ${response.status}）`);
    }
    return payload;
  }

  function renderFamilyNav() {
    dom.familyNavRow.innerHTML = "";
    if (state.page !== "recovery" && state.page !== "map") {
      return;
    }
    const wrapper = createElement("div", "scene-pill-group");
    families.forEach((family) => {
      const button = createElement("button", "scene-pill", baseScenes[family].label);
      if (state.recoveryFamily === family) {
        button.classList.add("active");
        button.style.background = baseScenes[family].accent;
      }
      button.addEventListener("click", () => {
        syncPlaybackForFamily(family);
        state.recoveryFamily = family;
        renderApp();
      });
      wrapper.appendChild(button);
    });
    dom.familyNavRow.appendChild(wrapper);
  }

  function renderResultModes() {
    dom.resultModeRow.innerHTML = "";
    const family = currentFamily();
    if (!family || (state.page !== "recovery" && state.page !== "map")) {
      return;
    }
    const whatIf = state.whatIfPayloads[family];
    if (!whatIf) {
      return;
    }
    const wrapper = createElement("div", "scene-pill-group result-mode-pills");

    const modeButton = createElement(
      "button",
      "scene-pill ghost-button",
      state.resultModeByFamily[family] === "whatif" ? "返回基准情境" : "查看当前推演结果"
    );
    modeButton.addEventListener("click", () => {
      state.resultModeByFamily[family] = state.resultModeByFamily[family] === "whatif" ? "baseline" : "whatif";
      renderApp();
    });
    wrapper.appendChild(modeButton);

    const clearButton = createElement("button", "scene-pill", "清除当前推演");
    clearButton.addEventListener("click", () => {
      state.whatIfPayloads[family] = null;
      state.resultModeByFamily[family] = "baseline";
      renderApp();
    });
    wrapper.appendChild(clearButton);

    dom.resultModeRow.appendChild(wrapper);
  }

  /* Legacy duplicate recovery aside renderer disabled; final definition is below. */

  function shouldShowRecoverySelector(family) {
    return state.resultModeByFamily[family] === "whatif" || Boolean(state.whatIfPayloads[family]) || getSelectedNodes(family).length > 0;
  }

  function renderTimeControlPanel(scene, family, selected, stage, options = {}) {
    const moduleKey = String(options.moduleKey || "");
    const panel = createElement("section", "panel process-panel aside-control-panel");
    panel.append(createSectionHead("", "动态过程控制"));
    const controller = createElement("div", "timeline-controller");
    const selectedIndex = state.selectedIndexByFamily[family] || 0;
    const progressPercent = scene.daily.length > 1 ? (selectedIndex / (scene.daily.length - 1)) * 100 : 0;

    const slider = createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = String(Math.max(scene.daily.length - 1, 0));
    slider.step = "1";
    slider.value = String(state.selectedIndexByFamily[family]);
    slider.addEventListener("input", (event) => {
      stopPlay();
      state.selectedIndexByFamily[family] = Number(event.target.value || 0);
      state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], scene.daily.length, state.selectedIndexByFamily[family]);
      renderApp();
    });
    controller.appendChild(slider);

    const controls = createElement("div", "timeline-action-row");
    if (["process_overview", "propagation_statistics", "supply_propagation", "demand_propagation", "dynamic_network", "node_simulation"].includes(moduleKey)) {
      controls.classList.add("timeline-action-row-single");
    }
    const playButton = createElement("button", "ghost-button", state.playingFamily === family ? "暂停过程" : "播放过程");
    playButton.addEventListener("click", () => togglePlay(family));
    controls.appendChild(playButton);
    controlSnapshotsForModule(scene, moduleKey).forEach((snapshot) => {
      const button = createElement("button", "stage-chip", stageShortLabel(snapshot));
      if (snapshot.snapshot_name === stage.snapshot_name) {
        button.classList.add("active");
        button.style.background = scene.accent;
      }
      button.addEventListener("click", () => {
        const targetIndex = scene.daily.findIndex((row) => row.date === snapshot.snapshot_date);
        if (targetIndex >= 0) {
          stopPlay();
          state.selectedIndexByFamily[family] = targetIndex;
          state.viewportByFamily[family] = ensureViewportContains(state.viewportByFamily[family], scene.daily.length, targetIndex);
          renderApp();
        }
      });
      controls.appendChild(button);
    });
    controller.appendChild(controls);

    const meta = createElement("div", "timeline-meta");
    meta.appendChild(detailCard("当前日期", formatDate(selected.date)));
    meta.appendChild(detailCard("当前阶段", stageShortLabel(stage) || "未识别阶段"));
    meta.appendChild(detailCard("过程进度", `${Math.round(progressPercent)}%`));
    panel.appendChild(controller);
    panel.appendChild(meta);
    return panel;
  }

  function renderRecoveryControlCard(scene, family, currentRow, selectedDate) {
    const card = createElement("div", "network-copy-card recovery-console-card aside-detail-panel");
    card.appendChild(createElement("h3", "", "恢复动作控制台"));
    card.appendChild(createElement("small", "", `${formatDate(selectedDate)} · ${policyProfileLabel(state.policyProfileByFamily[family])}`));
    const recoveryContext = buildRecoveryContext(
      scene,
      scene.interactive_network,
      resolveDailyNetworkState(scene.interactive_network?.daily_states || [], selectedDate),
      selectedDate
    );
    const stats = createElement("div", "snapshot-stat-grid");
    stats.appendChild(detailCard("当前主导恢复动作", resolveDominantRecoveryAction(currentRow)));
    stats.appendChild(detailCard("激活备供切换数", formatInteger(currentRow.active_backup_switches)));
    stats.appendChild(detailCard("激活等效替代数", formatInteger(currentRow.active_substitutions)));
    stats.appendChild(detailCard("激活优先抢修数", formatInteger(currentRow.active_priority_repairs)));
    stats.appendChild(detailCard("当前累计策略成本", formatCurrency(currentRow.policy_cumulative_cost)));
    stats.appendChild(detailCard("仍未恢复关键节点", formatInteger(recoveryContext.unresolvedKeyKeys.size)));
    card.appendChild(stats);
    return card;
  }

  function renderRecoverySelectorCard(family) {
    const selectedNodes = getSelectedNodes(family);
    const scene = getSceneBundle(family).current;
    const card = createElement("div", "network-copy-card recovery-selector-card aside-config-panel");
    card.appendChild(createElement("h3", "", "当前推演对象"));
    const grid = createElement("div", "detail-grid compact-detail-grid");
    grid.appendChild(detailCard("当前节点集合", selectedNodes.length ? selectedNodes.map((node) => formatNodeName(node, scene)).join("、") : "未选择"));
    grid.appendChild(detailCard("当前结果模式", state.resultModeByFamily[family] === "whatif" ? "节点推演结果" : "基准情境"));
    card.appendChild(grid);
    const actions = createElement("div", "selector-action-row");
    const backSceneButton = createElement("button", "ghost-button", "返回情境页继续选点");
    backSceneButton.addEventListener("click", () => {
      stopPlay();
      state.page = family;
      renderApp();
    });
    actions.appendChild(backSceneButton);
    if (state.whatIfPayloads[family]) {
      const keepResultButton = createElement("button", "scene-pill", "查看当前推演恢复过程");
      keepResultButton.addEventListener("click", () => {
        stopPlay();
        state.resultModeByFamily[family] = "whatif";
        state.subViewByPage.recovery = "recovery_network";
        state.page = "recovery";
        renderApp();
      });
      actions.appendChild(keepResultButton);
    }
    card.appendChild(actions);
    return card;
  }

  function renderWorkspaceLayout(pageKey, mainNode, asideNodes, title, note) {
    const moduleKey = currentModule(pageKey);
    const layout = createElement("div", "workspace-layout");
    layout.classList.add(`page-${pageKey}`, `module-${moduleKey || "default"}`);

    const sidebar = createElement("aside", "panel workspace-sidebar");
    sidebar.appendChild(renderModuleSidebar(pageKey));

    const center = createElement("section", "workspace-center");
    const main = createElement("section", "workspace-main");
    main.classList.add(`module-${moduleKey || "default"}`);
    if (mainNode) {
      main.appendChild(mainNode);
    }
    center.appendChild(main);

    const items = Array.isArray(asideNodes) ? asideNodes : [asideNodes];
    const visibleAsideItems = items.filter(Boolean);
    if (visibleAsideItems.length) {
      const aside = createElement("aside", "workspace-aside");
      aside.classList.add(`module-${moduleKey || "default"}`);
      visibleAsideItems.forEach((item) => aside.appendChild(item));
      layout.append(sidebar, center, aside);
    } else {
      layout.classList.add("no-aside");
      layout.append(sidebar, center);
    }
    return layout;
  }

  function createChartHead(title, note) {
    const head = createElement("div", "chart-head");
    const box = createElement("div");
    box.appendChild(createElement("h3", "", title));
    head.appendChild(box);
    return head;
  }

  function renderSceneSummaryPanel(scene, family, eyebrowText) {
    const panel = createElement("section", "panel scene-summary-panel aside-summary-panel");
    const title = replaceEntityIdsWithNames(scene.label || baseScenes[family].label, scene);
    const useScenarioLine = state.resultModeByFamily[family] === "whatif";
    panel.append(useScenarioLine ? createScenarioSummaryHead(title) : createSectionHead("", title));
    const meta = createElement("div", "scene-meta compact-summary-grid");
    meta.appendChild(metaItem("开始日期", formatDate(scene.scenario.start_date)));
    meta.appendChild(metaItem("持续天数", `${scene.scenario.duration_days || 0} 天`));
    meta.appendChild(metaItem("平均服务水平", formatPercent(scene.summary.average_service_level)));
    meta.appendChild(metaItem("策略总成本", formatCurrency(scene.summary.policy_total_cost)));
    panel.appendChild(meta);
    return panel;
  }

  function renderOverviewComparePanel() {
    const panel = createElement("section", "panel overview-panel overview-compare-panel");
    panel.append(createSectionHead("", "关键结果对比"));
    const compareGrid = createElement("div", "compare-grid compare-grid-overview");
    [
      ["恢复天数", "ttr_days", "days"],
      ["平均服务水平", "average_service_level", "percent"],
      ["系统服务水平", "avg_system_service_level", "percent"],
      ["策略总成本", "policy_total_cost", "currency"],
      ["预计中断损失", "estimated_disruption_loss", "currency"],
    ].forEach(([label, key, mode]) => {
      const randomValue = baseScenes.random.summary[key];
      const keynodeValue = baseScenes.keynode.summary[key];
      const card = createElement("article", "compare-card");
      card.appendChild(createElement("span", "", label));
      card.appendChild(createElement("strong", "", `${baseScenes.random.label}：${formatByMode(randomValue, mode)}`));
      card.appendChild(createElement("em", "", `${baseScenes.keynode.label}：${formatByMode(keynodeValue, mode)}`));
      compareGrid.appendChild(card);
    });
    panel.appendChild(compareGrid);
    return panel;
  }

  function renderOverviewAside(moduleKey) {
    const status = createElement("section", "panel aside-detail-panel");
    status.append(createSectionHead("", "系统状态"));
    const statusGrid = createElement("div", "compact-detail-grid");
    statusGrid.appendChild(detailCard("推演服务", state.apiAvailable ? "已连接" : "未连接"));
    statusGrid.appendChild(detailCard("接口版本", state.apiContractVersion || "-"));
    status.appendChild(statusGrid);

    const jump = createElement("section", "panel aside-entry-panel");
    jump.append(createSectionHead("", "快速进入"));
    const buttons = createElement("div", "workspace-link-grid");
    ["random", "keynode", "recovery"].forEach((pageKey) => {
      const button = createElement("button", "scene-pill", pageLabel(pageKey));
      button.style.background = pageAccent(pageKey);
      button.style.color = "#fff";
      button.addEventListener("click", () => {
        state.page = pageKey;
        renderApp();
      });
      buttons.appendChild(button);
    });
    jump.appendChild(buttons);
    return createAsideStack(status, jump);
  }

  function renderRecoveryAside(scene, family, selected, stage) {
    const moduleKey = currentModule("recovery");
    const items = [
      renderSceneSummaryPanel(scene, family, "恢复策略摘要"),
      renderTimeControlPanel(scene, family, selected, stage, { moduleKey }),
    ];

    if (moduleKey === "recovery_overview" || moduleKey === "recovery_network") {
      items.push(renderRecoveryControlCard(scene, family, selected, selected.date));
    }

    if (moduleKey === "recovery_network" || moduleKey === "policy_compare" || moduleKey === "impact_paths") {
      items.push(renderRecoverySelectorCard(family));
    }

    return createAsideStack(items);
  }
  function createOverviewModuleShell(moduleKey, ...panels) {
    const shell = createElement("div", `overview-module-shell overview-module-${moduleKey}`);
    panels.flat().filter(Boolean).forEach((panel) => shell.appendChild(panel));
    return shell;
  }

  /*
   * Inactive duplicate: final renderOverviewMain definition lives later.
   *
  function renderOverviewMain(moduleKey) {
    switch (moduleKey) {
      case "metric_compare":
        return createOverviewModuleShell(
          "metric_compare",
          renderOverviewComparePanel(),
          renderOverviewMonthlyPanel()
        );
      case "stage_timeline":
        return createOverviewModuleShell(
          "stage_timeline",
          renderOverviewTimelinePanel(),
          renderOverviewDurationPanel()
        );
      case "monthly_distribution":
        return createOverviewModuleShell(
          "monthly_distribution",
          renderOverviewMonthlyPanel(),
          renderOverviewDurationPanel()
        );
      case "duration_compare":
        return createOverviewModuleShell(
          "duration_compare",
          renderOverviewDurationPanel(),
          renderOverviewTimelinePanel()
        );
      case "scene_summary":
      default:
        return createOverviewModuleShell(
          "scene_summary",
          renderOverviewScenePanel(),
          renderOverviewComparePanel()
        );
    }
  }
  */

  function createOverviewCanvas(moduleKey, title, bodyClass) {
    const panel = createElement("section", `panel overview-canvas-panel overview-canvas-${moduleKey}`);
    if (title) {
      panel.appendChild(createSectionHead("", title));
    } else {
      panel.classList.add("no-section-title");
    }
    const body = createElement("div", `overview-canvas-body ${bodyClass || ""}`);
    panel.appendChild(body);
    return { panel, body };
  }

  function createOverviewMetricCard(label, key, mode) {
    const card = createElement("article", "overview-metric-card");
    card.appendChild(createElement("span", "", label));
    const main = createElement("strong", "", `${baseScenes.random.label}：${formatByMode(baseScenes.random.summary[key], mode)}`);
    const sub = createElement("em", "", `${baseScenes.keynode.label}：${formatByMode(baseScenes.keynode.summary[key], mode)}`);
    card.append(main, sub);
    return card;
  }

  function createOverviewMetricsGrid() {
    const grid = createElement("div", "overview-metric-card-grid");
    [
      ["恢复天数", "ttr_days", "days"],
      ["平均服务水平", "average_service_level", "percent"],
      ["系统服务水平", "avg_system_service_level", "percent"],
      ["策略总成本", "policy_total_cost", "currency"],
      ["预计中断损失", "estimated_disruption_loss", "currency"],
    ].forEach(([label, key, mode]) => {
      grid.appendChild(createOverviewMetricCard(label, key, mode));
    });
    return grid;
  }

  function createOverviewChartCard(title, chartNode, className) {
    const card = createElement("article", `overview-chart-card ${className || ""}`);
    card.appendChild(createElement("h3", "", title));
    const body = createElement("div", "overview-chart-body");
    body.appendChild(chartNode);
    card.appendChild(body);
    return card;
  }

  function createOverviewMonthlyCharts() {
    const grid = createElement("div", "overview-chart-grid overview-chart-grid-two");
    const monthlyRowsByFamily = Object.fromEntries(
      families.map((family) => [family, baseScenes[family].monthly_disrupted || []])
    );
    const sharedMonths = Array.from(
      new Set(families.flatMap((family) => monthlyRowsByFamily[family].map((row) => String(row.month || ""))))
    ).filter(Boolean).sort();
    const sharedMonthlyMax = Math.max(
      1,
      ...families.flatMap((family) => monthlyRowsByFamily[family].map((row) => Number(row.total_disrupted_nodes || 0)))
    );
    families.forEach((family) => {
      grid.appendChild(createOverviewChartCard(
        baseScenes[family].label,
        renderMonthlyChart(monthlyRowsByFamily[family], {
          months: sharedMonths,
          maxValue: sharedMonthlyMax,
        }),
        `overview-${family}-chart`
      ));
    });
    return grid;
  }

  function createOverviewDurationCharts() {
    const grid = createElement("div", "overview-duration-grid");
    families.forEach((family) => {
      const scene = baseScenes[family];
      const card = createElement("article", `overview-duration-card overview-${family}-duration`);
      card.appendChild(createElement("h3", "", overviewDurationTitle(family, scene)));
      const rows = scene.propagation_durations || [];
      const maxValue = Math.max(1, ...rows.map((row) => Number(row.duration_months || 0)));
      const list = createElement("div", "overview-duration-list");
      rows.forEach((row) => {
        const value = Number(row.duration_months || 0);
        const item = createElement("div", "overview-duration-row");
        const head = createElement("div", "overview-duration-row-head");
        head.appendChild(createElement("span", "", row.label || "-"));
        head.appendChild(createElement("strong", "", `${formatInteger(value)} 个月`));
        const track = createElement("div", "overview-duration-track");
        const fill = createElement("div", "overview-duration-fill");
        fill.style.width = `${Math.max(4, (value / maxValue) * 100)}%`;
        fill.style.background = scene.accent;
        track.appendChild(fill);
        item.append(head, track);
        list.appendChild(item);
      });
      card.appendChild(list);
      grid.appendChild(card);
    });
    return grid;
  }

  function overviewDurationTitle(family, scene) {
    if (family === "random" || family === "keynode") return "中断传播时长";
    return scene?.label || baseScenes[family]?.label || "-";
  }

  function createOverviewStageCards() {
    const grid = createElement("div", "overview-stage-grid");
    families.forEach((family) => {
      const card = createElement("article", `overview-stage-card overview-${family}-stage`);
      card.appendChild(createElement("h3", "", baseScenes[family].label));
      const list = createElement("div", "overview-stage-list");
      (baseScenes[family].network_snapshots || []).forEach((snapshot) => {
        const row = createElement("div", "overview-stage-row");
        row.appendChild(createElement("strong", "", stageDisplayTitle(snapshot)));
        row.appendChild(createElement("span", "", formatDate(snapshot.snapshot_date)));
        list.appendChild(row);
      });
      card.appendChild(list);
      grid.appendChild(card);
    });
    return grid;
  }

  function createOverviewSceneCards() {
    const grid = createElement("div", "overview-scene-card-grid overview-scene-card-grid-compact");
    families.forEach((family) => {
      const scene = baseScenes[family];
      const card = createElement("article", `overview-summary-card overview-${family}-summary`);
      card.style.background = scene.accent_soft;
      const header = createElement("div", "overview-summary-card-header");
      const titleBox = createElement("div", "overview-summary-title");
      titleBox.appendChild(createElement("span", "overview-card-eyebrow", scene.label));
      titleBox.appendChild(createElement("h3", "", scene.scenario.scenario_name || scene.scenario.scenario_id || "-"));
      const tag = createElement("span", "scene-type-tag", scenarioTypeDisplay(scene.scenario));
      tag.style.background = scene.accent;
      header.append(titleBox, tag);
      const facts = createElement("div", "overview-summary-facts");
      facts.appendChild(metaItem("开始日期", formatDate(scene.scenario.start_date)));
      facts.appendChild(metaItem("目标对象", formatScenarioTargetDisplay(scene.scenario, scene)));
      facts.appendChild(metaItem("恢复天数", `${scene.summary.ttr_days ?? "-"} 天`));
      facts.appendChild(metaItem("平均服务水平", formatPercent(scene.summary.average_service_level)));
      card.append(header, facts);
      grid.appendChild(card);
    });
    return grid;
  }

  function createOverviewFamilyMetricCard(family, label, key, mode, wide = false) {
    const scene = baseScenes[family];
    const card = createElement("article", "overview-family-metric-card");
    if (wide) {
      card.classList.add("wide");
    }
    card.appendChild(createElement("span", "overview-family-metric-label", label));
    card.appendChild(createElement("strong", "overview-family-metric-value", formatByMode(scene.summary[key], mode)));
    return card;
  }

  function createOverviewFamilyMetricsGrid(family) {
    const grid = createElement("div", "overview-family-metrics-grid");
    [
      ["恢复天数", "ttr_days", "days", false],
      ["平均服务水平", "average_service_level", "percent", false],
      ["系统服务水平", "avg_system_service_level", "percent", false],
      ["策略总成本", "policy_total_cost", "currency", false],
      ["预计中断损失", "estimated_disruption_loss", "currency", true],
    ].forEach(([label, key, mode, wide]) => {
      grid.appendChild(createOverviewFamilyMetricCard(family, label, key, mode, wide));
    });
    return grid;
  }

  function createOverviewFamilyStageSection(family) {
    const section = createElement("section", "overview-family-section overview-family-stage-section");
    section.appendChild(createOverviewFamilyMetricsGrid(family));
    const list = createElement("div", "overview-family-stage-list");
    (baseScenes[family].network_snapshots || []).forEach((snapshot) => {
      const row = createElement("div", "overview-family-stage-row");
      row.appendChild(createElement("strong", "", stageDisplayTitle(snapshot)));
      row.appendChild(createElement("span", "", formatDate(snapshot.snapshot_date)));
      list.appendChild(row);
    });
    section.appendChild(list);
    return section;
  }

  function createOverviewFamilyColumn(family) {
    const scene = baseScenes[family];
    const column = createElement("article", `overview-family-column overview-family-column-${family}`);

    const hero = createElement("section", "overview-family-hero");

    const header = createElement("div", "overview-family-header");
    header.appendChild(createElement("h3", "", scene.label));

    const facts = createElement("div", "overview-family-facts");
    facts.appendChild(metaItem("开始日期", formatDate(scene.scenario.start_date)));
    facts.appendChild(metaItem("目标对象", formatScenarioTargetDisplay(scene.scenario, scene)));
    hero.append(header, facts);

    column.append(hero, createOverviewFamilyStageSection(family));
    return column;
  }

  function renderOverviewSceneCanvas() {
    const { panel, body } = createOverviewCanvas("scene_summary", "", "overview-summary-body");
    body.classList.add("overview-dual-family-body");
    const grid = createElement("div", "overview-family-grid");
    families.forEach((family) => {
      grid.appendChild(createOverviewFamilyColumn(family));
    });
    body.append(grid);
    return panel;
  }

  function createOverviewFamilyStageList(family) {
    const list = createElement("div", "overview-family-stage-list");
    (baseScenes[family].network_snapshots || []).forEach((snapshot) => {
      const row = createElement("div", "overview-family-stage-row");
      row.appendChild(createElement("strong", "", stageDisplayTitle(snapshot)));
      row.appendChild(createElement("span", "", formatDate(snapshot.snapshot_date)));
      list.appendChild(row);
    });
    return list;
  }

  function createOverviewSharedMetricsSection() {
    const section = createElement("section", "overview-family-section overview-family-shared-section");
    section.appendChild(createElement("h4", "overview-family-section-title", "关键指标"));
    const grid = createElement("div", "overview-family-section-grid overview-family-section-grid-metrics");
    families.forEach((family) => {
      const column = createElement("div", `overview-family-section-column overview-family-section-column-${family}`);
      column.appendChild(createOverviewFamilyMetricsGrid(family));
      grid.appendChild(column);
    });
    section.appendChild(grid);
    return section;
  }

  function createOverviewSharedStageSection() {
    const section = createElement("section", "overview-family-section overview-family-shared-section overview-family-stage-section");
    section.appendChild(createElement("h4", "overview-family-section-title", "阶段过程"));
    const grid = createElement("div", "overview-family-section-grid overview-family-section-grid-stage");
    families.forEach((family) => {
      const column = createElement("div", `overview-family-section-column overview-family-section-column-${family}`);
      column.appendChild(createOverviewFamilyStageList(family));
      grid.appendChild(column);
    });
    section.appendChild(grid);
    return section;
  }

  function renderOverviewMetricCanvas() {
    const { panel, body } = createOverviewCanvas("metric_compare", "关键结果对比", "overview-metric-body");
    body.appendChild(createOverviewMetricsGrid());
    return panel;
  }

  function renderOverviewStageCanvas() {
    const { panel, body } = createOverviewCanvas("stage_timeline", "关键阶段时间线", "overview-stage-body");
    body.appendChild(createOverviewStageCards());
    return panel;
  }

  function renderOverviewMonthlyCanvas() {
    const { panel, body } = createOverviewCanvas("monthly_distribution", "月度中断节点分布", "overview-monthly-body");
    body.appendChild(createOverviewMonthlyCharts());
    return panel;
  }

  function renderOverviewDurationCanvas() {
    const { panel, body } = createOverviewCanvas("duration_compare", "传播时长对比", "overview-duration-body");
    body.appendChild(createOverviewDurationCharts());
    return panel;
  }

  function renderOverviewPropagationCanvas() {
    const { panel, body } = createOverviewCanvas("propagation_statistics", "", "overview-propagation-body");
    body.appendChild(createOverviewMonthlyCharts());
    body.appendChild(createOverviewDurationCharts());
    return panel;
  }

  function renderOverviewStageProcessCanvas() {
    const { panel, body } = createOverviewCanvas("stage_process", "阶段过程", "overview-stage-process-body");
    body.appendChild(createOverviewStageCards());
    return panel;
  }

  function renderOverviewMain(moduleKey) {
    switch (moduleKey) {
      case "propagation_statistics":
        return renderOverviewPropagationCanvas();
      case "scene_summary":
      default:
        return renderOverviewSceneCanvas();
    }
  }
})();
