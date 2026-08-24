import assert from "node:assert/strict";

globalThis.window = { location: { search: "" } };
const {
  ApiError,
  ApiContractError,
  apiClient,
  loadApplication,
  normalizeDashboard,
  normalizeDecision,
  normalizeResearch,
  normalizeHistory,
  normalizePriceRefresh,
  normalizeBuildResearch,
  normalizeBootstrapOverview,
  refreshPrices,
  buildResearch,
  bootstrapOverview,
  runValueManager,
  recordDecisionOutcome,
  executePaperTrade,
  isExecutionEnabled,
  bindShellCommands,
} = await import("./app.js");

const security = (ticker = "MSFT") => ({ ticker, security_type: "EQUITY", exchange: "NASDAQ", currency: "USD" });
const position = () => ({ security: security(), quantity: "1", observed_price: "340", total_cost_basis: "180", market_value: "340", unrealized_gain_loss: "160" });
const portfolio = (id = "portfolio-1") => ({
  portfolio_id: id, portfolio_name: "Managed Value", base_currency: "USD", starting_capital: "1000",
  created_at: "2026-08-10T12:00:00+00:00", decision_cycle_id: "cycle-1", status: "active",
  as_of_timestamp: "2026-08-11T12:00:00+00:00", cash_value: "450", invested_value: "670", total_value: "1120",
  unrealized_gain_loss: "210", source_provider_identity: "demo-provider", market_date: "2026-08-11",
  source_price_timestamp: "2026-08-11T12:00:00+00:00", price_convention: "regular-session-close", positions: [position()],
});
const evidence = () => ({ evidence_id: "ev-1", source_type: "FILING", source_title: "Quarterly report", source_date: "2026-08-10", claim_supported: "Cash generation continued." });
const recommendation = (action = "HOLD") => ({
  action, ticker: action === "BUY" ? "MSFT" : null, target_weight: action === "BUY" ? "0.25" : null,
  decision_rationale: "Mechanically valid decision.", investment_thesis: action === "BUY" ? "Durable cash flow." : null,
  valuation: "Valuation context.", risks: ["Competition"], confidence_score: 80, evidence: [evidence()],
  why_not_spy: "Security-specific opportunity.", thesis_invalidation: ["Cash flow deteriorates"], review_triggers: ["Material earnings change"],
});
const validation = (tradeId = null) => ({ status: "PASSED", validation_timestamp: "2026-08-11T12:00:00+00:00", validated_trade_id: tradeId, rules: [{ rule_id: "RISK-1", status: "PASSED", reason: "Within policy", actual_value: null, allowed_threshold: null, layer: "SYSTEM_SAFETY", policy_version: "safety-v1", input_references: ["portfolio"] }] });
const policyEvaluation = ({ mechanicallyExecutable = true, advisoryFindings = [] } = {}) => ({
  policy_kind: "CURRENT", investment_constitution_version: "investment-v1", investment_constitution_hash: "investment-hash",
  system_safety_envelope_version: "safety-v1", system_safety_envelope_hash: "safety-hash",
  manager_risk_constitution_version: "manager-risk-v1", manager_risk_constitution_hash: "manager-risk-hash",
  mechanically_executable: mechanicallyExecutable,
  advisory_findings: advisoryFindings,
});
const materialAdvisory = () => ({ finding_id: "NORMAL_STARTER_GUIDANCE_DEVIATION", severity: "MATERIAL", reason: "Starter guidance differs from the normal starter guidance.", actual_value: "0.25", guidance_value: "0.10", input_references: ["recommendation.target_weight"] });
const reviewer = () => ({ decision: "APPROVE", reviewed_at: "2026-08-11T12:10:00+00:00", findings: [{ severity: "INFO", category: "EVIDENCE_USAGE", message: "Evidence cited.", related_evidence_ids: ["ev-1"], related_recommendation_field: "evidence" }] });
const approval = () => ({ decision: "APPROVED", decision_maker_id: "human-1", decided_at: "2026-08-11T12:20:00+00:00", comment: "Approved." });
const execution = () => ({
  executed_trade_id: "executed-1", validated_trade_id: "validated-1", security: security(), action: "BUY",
  executed_quantity: "0.50000000", execution_price: "200", executed_notional: "100.00000000", currency: "USD",
  source_provider_identity: "demo-provider", market_date: "2026-08-11", price_convention: "regular-session-close",
  executed_at: "2026-08-11T12:30:00+00:00", execution_source: "simulated",
});
const decision = ({ action = "HOLD", withReviewer = true, withApproval = true, withExecution = false, readiness = null, policy = policyEvaluation(), validationResult = validation(withExecution ? "validated-1" : null) } = {}) => ({
  decision_cycle_id: "cycle-1", portfolio_id: "portfolio-1", manager_type: "VALUE", constitution_version: "value-v1.0.0",
  research_batch_id: "batch-1", journaled_at: "2026-08-11T12:05:00+00:00", produced_at: "2026-08-11T12:00:00+00:00",
  recommendation: recommendation(action), validation: validationResult,
  policy_evaluation: policy,
  reviewer: withReviewer ? reviewer() : null, approval: withApproval ? approval() : null, execution: withExecution ? execution() : null,
  execution_readiness: readiness ?? { executable: false, reason_code: action === "HOLD" ? "HOLD" : "NOT_APPROVED", decision_cycle_id: "cycle-1", action, security: action === "BUY" ? security() : null, approval_status: withApproval ? "APPROVED" : null, validation_status: "PASSED" },
});
const research = () => ({
  batch_id: "batch-1", decision_cycle_id: "cycle-1", portfolio_id: "portfolio-1", manager_type: "VALUE",
  created_at: "2026-08-10T12:00:00+00:00", as_of_timestamp: "2026-08-10T12:00:00+00:00",
  packets: [{ packet_id: "packet-1", candidate_id: "candidate-1", ticker: "MSFT", security_type: "EQUITY", exchange: "NASDAQ", currency: "USD", company_name: "Microsoft", sector: "Technology", industry: "Software", as_of_timestamp: "2026-08-10T12:00:00+00:00", evidence: [evidence()], sections: [{ section_id: "BUSINESS_OVERVIEW", content: "Enterprise software", missing_data: null, evidence_ids: ["ev-1"] }] }],
});
const history = () => ({
  entries_newest_first: [
    { history_entry_id: "history-hold", decision_cycle_id: "cycle-1", decision_timestamp: "2026-08-11T12:00:00+00:00", action: "HOLD", ticker: "n/a", target_weight: "n/a", reviewer_outcome: "APPROVE", approval_outcome: "APPROVED", research_batch_id: "batch-1", research_packet_id: null, execution: { status: "No execution — HOLD", executed_trade_id: null, validated_trade_id: null, security: null, action: null, execution_price: null, quantity: null, notional: null, executed_at: null } },
    { history_entry_id: "history-buy", decision_cycle_id: "cycle-0", decision_timestamp: "2026-08-10T12:00:00+00:00", action: "BUY", ticker: "MSFT", target_weight: "25%", reviewer_outcome: "APPROVE", approval_outcome: "APPROVED", research_batch_id: "batch-0", research_packet_id: "packet-1", execution: { status: "Simulated execution", executed_trade_id: "executed-1", validated_trade_id: "validated-1", security: security(), action: "BUY", execution_price: "200", quantity: "0.50000000", notional: "100.00000000", executed_at: "2026-08-10T12:30:00+00:00" } },
  ],
  chart_points_oldest_first: [{ timestamp: "2026-08-10T12:00:00+00:00", portfolio_value: "1000", managed_return: "0", benchmark_return: "0", absolute_alpha: "0" }],
});
const dashboard = () => ({
  portfolio: portfolio(), benchmark: { benchmark_security: security("SPY"), snapshot: portfolio("benchmark-1") },
  performance: { managed_portfolio_id: "portfolio-1", benchmark_portfolio_id: "benchmark-1", currency: "USD", managed_cumulative_return: "0.12", benchmark_cumulative_return: "0.08", absolute_alpha: "0.04", relative_alpha: "0.037", as_of_timestamp: "2026-08-11T12:00:00+00:00" },
  latest_decision: decision(), research: research(), history: history(), benchmark_fulfillment_status: "PENDING_NO_ELIGIBLE_PRICE",
});

const dashboardView = normalizeDashboard(dashboard());
assert.equal(dashboardView.portfolio.totalValue, "1120");
assert.equal(typeof dashboardView.portfolio.totalValue, "string");
assert.equal(dashboardView.benchmark.security.ticker, "SPY");
assert.equal(dashboardView.performance.absoluteAlpha, "0.04");
assert.equal(dashboardView.history.chartPoints[0].portfolioValue, "1000");
assert.equal("total_value" in dashboardView.portfolio, false);

const holdView = normalizeDecision(decision({ withReviewer: false, withApproval: false }));
assert.equal(holdView.recommendation.action, "HOLD");
assert.equal(holdView.recommendation.ticker, null);
assert.equal(holdView.reviewer, null);
assert.equal(holdView.approval, null);
assert.equal(holdView.execution, null);
assert.equal(holdView.executionReadiness.reasonCode, "HOLD");
assert.equal(holdView.policyEvaluation.mechanicallyExecutable, true);
assert.deepEqual(holdView.policyEvaluation.advisoryFindings, []);
assert.equal(normalizeDecision(null), null);

const advisoryPolicyView = normalizeDecision(decision({
  action: "BUY",
  policy: policyEvaluation({ advisoryFindings: [materialAdvisory()] }),
}));
assert.equal(advisoryPolicyView.policyEvaluation.policyKind, "CURRENT");
assert.equal(advisoryPolicyView.policyEvaluation.managerRiskConstitutionVersion, "manager-risk-v1");
assert.equal(advisoryPolicyView.policyEvaluation.advisoryFindings[0].severity, "MATERIAL");
assert.equal(advisoryPolicyView.policyEvaluation.advisoryFindings[0].reason, "Starter guidance differs from the normal starter guidance.");

const legacyPolicyView = normalizeDecision({
  ...decision(),
  policy_evaluation: {
    policy_kind: "LEGACY_MECHANICAL", investment_constitution_version: null, investment_constitution_hash: null,
    system_safety_envelope_version: null, system_safety_envelope_hash: null,
    manager_risk_constitution_version: null, manager_risk_constitution_hash: null,
    mechanically_executable: true, advisory_findings: [],
  },
});
assert.equal(legacyPolicyView.policyEvaluation.policyKind, "LEGACY_MECHANICAL");
assert.equal(legacyPolicyView.policyEvaluation.systemSafetyEnvelopeVersion, null);
assert.equal(legacyPolicyView.policyEvaluation.managerRiskConstitutionHash, null);
assert.deepEqual(legacyPolicyView.policyEvaluation.advisoryFindings, []);

const buyView = normalizeDecision(decision({ action: "BUY", withExecution: true }));
assert.equal(buyView.recommendation.targetWeight, "0.25");
assert.equal(buyView.execution.executedTradeId, "executed-1");
assert.equal(buyView.execution.validatedTradeId, "validated-1");
assert.equal(buyView.execution.security.ticker, "MSFT");
assert.equal(buyView.executionReadiness.security.ticker, "MSFT");

for (const reasonCode of ["HOLD", "NOT_APPROVED", "REJECTED", "VALIDATION_FAILED", "ALREADY_EXECUTED"]) {
  assert.equal(isExecutionEnabled(normalizeDecision(decision({ action: reasonCode === "HOLD" ? "HOLD" : "BUY", readiness: { executable: false, reason_code: reasonCode, decision_cycle_id: "cycle-1", action: reasonCode === "HOLD" ? "HOLD" : "BUY", security: reasonCode === "HOLD" ? null : security(), approval_status: null, validation_status: "PASSED" } }))), false);
}
const readyDecision = normalizeDecision(decision({ action: "BUY", readiness: { executable: true, reason_code: "READY", decision_cycle_id: "cycle-1", action: "BUY", security: security(), approval_status: "APPROVED", validation_status: "PASSED" } }));
assert.equal(isExecutionEnabled(readyDecision), true);

const renderDecisionCenter = async (rawDecision, label) => {
  const targets = Object.fromEntries(["#app", "#overview", "#decision", "#research", "#research-document", "#portfolio", "#history", "#portfolio-name", "#health-status", "#refresh-prices", "#build-research", "#bootstrap-overview"].map((selector) => [selector, { innerHTML: "", textContent: "", addEventListener() {}, querySelectorAll() { return []; } }]));
  globalThis.document = {
    querySelector: (selector) => targets[selector] ?? null,
    querySelectorAll: () => [],
    getElementById: () => null,
  };
  globalThis.fetch = async (url) => {
    const path = new URL(url).pathname;
    const payloads = {
      "/health": { status: "ok", state_mode: "sqlite", persisted: true, synthetic: false },
      "/dashboard": { ...dashboard(), latest_decision: rawDecision },
      "/decisions/latest": rawDecision,
      "/research/latest": research(),
      "/decisions": history(),
      "/portfolio": portfolio(),
      "/performance": dashboard().performance,
    };
    return { status: 200, ok: true, json: async () => payloads[path] };
  };
  const renderModule = await import(`./app.js?decision-center=${label}`);
  await renderModule.start();
  return targets["#decision"].innerHTML;
};

const currentNoFindingMarkup = await renderDecisionCenter(decision({
  action: "BUY",
  readiness: { executable: true, reason_code: "READY", decision_cycle_id: "cycle-1", action: "BUY", security: security(), approval_status: "APPROVED", validation_status: "PASSED" },
}), "current-no-findings");
assert.match(currentNoFindingMarkup, /Manager Risk/);
assert.match(currentNoFindingMarkup, /No Manager Risk advisory findings were recorded/);
assert.match(currentNoFindingMarkup, /Recorded yes/);
assert.match(currentNoFindingMarkup, /Ready for paper execution/);
assert.match(currentNoFindingMarkup, /<span>Target weight<\/span><strong>25\.00%<\/strong>/);

const legacyMarkup = await renderDecisionCenter({
  ...decision({ action: "BUY" }),
  policy_evaluation: {
    policy_kind: "LEGACY_MECHANICAL", investment_constitution_version: null, investment_constitution_hash: null,
    system_safety_envelope_version: null, system_safety_envelope_hash: null,
    manager_risk_constitution_version: null, manager_risk_constitution_hash: null,
    mechanically_executable: true, advisory_findings: [],
  },
}, "legacy-mechanical");
const legacySystemSafetyMarkup = legacyMarkup.match(/<article class="surface policy-panel system-safety">([\s\S]*?)<\/article>/)?.[1];
assert.ok(legacySystemSafetyMarkup);
assert.match(legacySystemSafetyMarkup, /<h2>Not recorded<\/h2>/);
assert.match(legacySystemSafetyMarkup, /<span class="policy-status">NOT RECORDED<\/span>/);
assert.doesNotMatch(legacySystemSafetyMarkup, /PASSED|FAILED/);
assert.match(legacyMarkup, /Legacy mechanical validation/);
assert.match(legacyMarkup, /<article class="surface policy-panel legacy-mechanical">[\s\S]*?<span class="policy-status">PASSED<\/span>/);

const advisoryExecutableMarkup = await renderDecisionCenter(decision({
  action: "BUY",
  policy: policyEvaluation({ advisoryFindings: [materialAdvisory()] }),
  readiness: { executable: true, reason_code: "READY", decision_cycle_id: "cycle-1", action: "BUY", security: security(), approval_status: "APPROVED", validation_status: "PASSED" },
}), "current-material-advisory");
assert.match(advisoryExecutableMarkup, /MATERIAL advisory/);
assert.match(advisoryExecutableMarkup, /Starter guidance differs from the normal starter guidance/);
assert.match(advisoryExecutableMarkup, /Ready for paper execution/);
assert.doesNotMatch(advisoryExecutableMarkup, /NOT EXECUTABLE/);

const mechanicallyBlockedMarkup = await renderDecisionCenter(decision({
  action: "BUY",
  policy: policyEvaluation({ mechanicallyExecutable: false }),
  validationResult: { ...validation(), status: "FAILED" },
  readiness: { executable: false, reason_code: "VALIDATION_FAILED", decision_cycle_id: "cycle-1", action: "BUY", security: security(), approval_status: "APPROVED", validation_status: "FAILED" },
}), "mechanically-blocked");
assert.match(mechanicallyBlockedMarkup, /Recorded no/);
assert.match(mechanicallyBlockedMarkup, /Hard deterministic result: FAILED/);
assert.match(mechanicallyBlockedMarkup, /VALIDATION_FAILED/);
assert.match(mechanicallyBlockedMarkup, /NOT EXECUTABLE/);
assert.doesNotMatch(mechanicallyBlockedMarkup, /Ready for paper execution/);
delete globalThis.document;

const researchView = normalizeResearch(research());
assert.equal(researchView.packets[0].candidateId, "candidate-1");
assert.equal(researchView.packets[0].evidence[0].sourceDate, "2026-08-10");
assert.equal(researchView.packets[0].evidence[0].claimSupported, "Cash generation continued.");
assert.equal(researchView.screeningRunId, null);
assert.deepEqual(researchView.selected, []);
assert.equal(normalizeResearch(null), null);
const researched = normalizeResearch({
  ...research(),
  screening_run_id: "screen-1",
  selected: [{ security: security("MSFT"), slot_role: "RANKED" }],
});
assert.equal(researched.screeningRunId, "screen-1");
assert.equal(researched.selected[0].slotRole, "RANKED");
assert.equal(researched.selected[0].security.ticker, "MSFT");
assert.equal("rank_key" in researched.selected[0], false);
assert.equal("rankKey" in researched.selected[0], false);

const historyView = normalizeHistory(history());
assert.equal(historyView.entries[0].execution.status, "No execution — HOLD");
assert.equal(historyView.entries[1].execution.executedTradeId, "executed-1");
assert.equal(historyView.entries[1].execution.validatedTradeId, "validated-1");
assert.deepEqual(normalizeHistory({ entries_newest_first: [], chart_points_oldest_first: [] }), { entries: [], chartPoints: [] });
assert.throws(() => normalizeHistory(null), ApiContractError);

assert.deepEqual(
  normalizePriceRefresh({ refreshed_tickers: ["MSFT", "SPY"], provider_identity: "twelve-data", latest_source_timestamp: "2026-08-13T20:00:00+00:00", price_convention: "twelve-data-quote-close-field" }),
  { refreshedTickers: ["MSFT", "SPY"], providerIdentity: "twelve-data", latestSourceTimestamp: "2026-08-13T20:00:00+00:00", priceConvention: "twelve-data-quote-close-field" },
);
assert.deepEqual(
  normalizeBuildResearch({ batch_id: "batch-1", decision_cycle_id: "cycle-1", packet_count: 5, source_provider_identity: "alpha-vantage", as_of_timestamp: "2026-08-13T20:00:00+00:00" }),
  { batchId: "batch-1", decisionCycleId: "cycle-1", packetCount: 5, provider: "alpha-vantage", asOfTimestamp: "2026-08-13T20:00:00+00:00" },
);
assert.deepEqual(
  normalizeBootstrapOverview({
    fetched: [security("MSFT")],
    skipped: [security("AAPL")],
    remaining: [security("GOOGL")],
    request_count: 1,
    provider_identity: "alpha-vantage",
  }),
  {
    fetched: [{ ticker: "MSFT", securityType: "EQUITY", exchange: "NASDAQ", currency: "USD" }],
    skipped: [{ ticker: "AAPL", securityType: "EQUITY", exchange: "NASDAQ", currency: "USD" }],
    remaining: [{ ticker: "GOOGL", securityType: "EQUITY", exchange: "NASDAQ", currency: "USD" }],
    requestCount: 1,
    providerIdentity: "alpha-vantage",
  },
);

const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const refreshButton = { disabled: false, textContent: "Refresh prices" };
const refreshStatus = { textContent: "" };
const pendingPost = deferred();
let postRequest;
let reloadCount = 0;
globalThis.fetch = async (url, options) => {
  postRequest = { url, options };
  return pendingPost.promise;
};
const successfulRefresh = refreshPrices({ button: refreshButton, status: refreshStatus, reload: async () => { reloadCount += 1; } });
assert.equal(refreshButton.disabled, true);
assert.equal(refreshButton.textContent, "Refreshing prices…");
assert.equal(refreshStatus.textContent, "Requesting Twelve Data observations…");
pendingPost.resolve({ ok: true, json: async () => ({ refreshed_tickers: ["MSFT", "SPY"], provider_identity: "twelve-data", latest_source_timestamp: "2026-08-13T20:00:00+00:00", price_convention: "twelve-data-quote-close-field" }) });
await successfulRefresh;
assert.equal(new URL(postRequest.url).pathname, "/commands/refresh-prices");
assert.equal(postRequest.options.method, "POST");
assert.equal(reloadCount, 1);
assert.equal(refreshButton.disabled, false);
assert.equal(refreshButton.textContent, "Refresh prices");
assert.match(refreshStatus.textContent, /Prices refreshed from twelve-data/);
assert.match(refreshStatus.textContent, /twelve-data-quote-close-field/);

const failingButton = { disabled: false, textContent: "Refresh prices" };
const failingStatus = { textContent: "" };
let failedReloadCount = 0;
globalThis.fetch = async () => ({ ok: false, status: 502, json: async () => ({ detail: { message: "provider unavailable" } }) });
await refreshPrices({ button: failingButton, status: failingStatus, reload: async () => { failedReloadCount += 1; } });
assert.equal(failedReloadCount, 0);
assert.equal(failingButton.disabled, false);
assert.equal(failingButton.textContent, "Refresh prices");
assert.equal(failingStatus.textContent, "Price refresh failed: provider unavailable");
assert.doesNotMatch(failingStatus.textContent, /Prices refreshed/);

const buildButton = { disabled: false, textContent: "Build research" }, buildStatus = { textContent: "" }, pendingBuild = deferred();
let buildReloads = 0;
globalThis.fetch = async (url, options) => { assert.equal(new URL(url).pathname, "/commands/build-research"); assert.equal(options.method, "POST"); return pendingBuild.promise; };
const building = buildResearch({ button: buildButton, status: buildStatus, reload: async () => { buildReloads += 1; } });
assert.equal(buildButton.disabled, true); assert.equal(buildButton.textContent, "Building research…"); assert.match(buildStatus.textContent, /Building source-attributed/);
pendingBuild.resolve({ ok: true, json: async () => ({ batch_id:"batch", decision_cycle_id:"cycle", packet_count:5, source_provider_identity:"fake-source", as_of_timestamp:"2026-08-13T20:00:00+00:00" }) });
await building;
assert.equal(buildReloads, 1); assert.equal(buildButton.disabled, false); assert.match(buildStatus.textContent, /Research built: 5 packets from fake-source/);
globalThis.fetch = async () => ({ ok:false, status:502, json:async()=>({detail:{message:"source failed"}}) });
await buildResearch({ button: buildButton, status: buildStatus, reload: async () => { throw new Error("must not reload"); } });
assert.equal(buildButton.disabled, false); assert.equal(buildStatus.textContent, "Research build failed: source failed");

const bootstrapButton = { disabled: false, textContent: "Bootstrap OVERVIEW" }, bootstrapStatus = { textContent: "" }, pendingBootstrap = deferred();
let bootstrapReloads = 0;
globalThis.fetch = async (url, options) => { assert.equal(new URL(url).pathname, "/commands/bootstrap-overview"); assert.equal(options.method, "POST"); return pendingBootstrap.promise; };
const bootstrapping = bootstrapOverview({ button: bootstrapButton, status: bootstrapStatus, reload: async () => { bootstrapReloads += 1; } });
assert.equal(bootstrapButton.disabled, true); assert.equal(bootstrapButton.textContent, "Bootstrapping OVERVIEW…");
pendingBootstrap.resolve({ ok: true, json: async () => ({ fetched: [security("MSFT"), security("AAPL")], skipped: [], remaining: [security("GOOGL")], request_count: 2, provider_identity: "alpha-vantage" }) });
await bootstrapping;
assert.equal(bootstrapReloads, 1); assert.equal(bootstrapButton.disabled, false); assert.match(bootstrapStatus.textContent, /OVERVIEW bootstrap: fetched 2 · remaining 1 · 2 requests/);
globalThis.fetch = async () => ({ ok:false, status:503, json:async()=>({detail:{message:"overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH"}}) });
await bootstrapOverview({ button: bootstrapButton, status: bootstrapStatus, reload: async () => { throw new Error("must not reload"); } });
assert.equal(bootstrapButton.disabled, false); assert.match(bootstrapStatus.textContent, /OVERVIEW bootstrap failed: overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH/);

const runButton = { disabled: false, textContent: "Run Value Manager" }, runStatus = { textContent: "" };
let runReloads = 0;
globalThis.fetch = async (url, options) => {
  assert.equal(new URL(url).pathname, "/commands/run-value-manager");
  assert.equal(options.method, "POST");
  assert.deepEqual(JSON.parse(options.body), { occurred_at: new Date("2026-08-13T20:00").toISOString() });
  return { ok: true, json: async () => decision({ action: "BUY", withApproval: false }) };
};
await runValueManager({ button: runButton, status: runStatus, reload: async () => { runReloads += 1; }, occurredAt: "2026-08-13T20:00" });
assert.equal(runReloads, 1); assert.equal(runButton.disabled, false); assert.match(runStatus.textContent, /Requesting a structured/);

for (const decisionName of ["approve", "reject"]) {
  const outcomeButton = { disabled: false, textContent: decisionName === "approve" ? "Approve" : "Reject" };
  const outcomeStatus = { textContent: "" };
  let reloaded = 0, confirmed = 0;
  globalThis.fetch = async (url, options) => {
    assert.equal(new URL(url).pathname, `/commands/decisions/cycle-1/${decisionName}`);
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { decision_maker_id: "operator-1", decided_at: new Date("2026-08-13T20:05").toISOString(), comment: "audit note" });
    return { ok: true, json: async () => decision({ action: "BUY", withApproval: false }) };
  };
  await recordDecisionOutcome({ decision: normalizeDecision(decision({ action: "BUY", withApproval: false })), decisionName, button: outcomeButton, status: outcomeStatus, reload: async () => { reloaded += 1; }, decisionMakerId: "operator-1", decidedAt: "2026-08-13T20:05", comment: "audit note", confirmDecision: () => { confirmed += 1; return true; } });
  assert.equal(confirmed, 1); assert.equal(reloaded, 1); assert.equal(outcomeButton.disabled, false);
  assert.equal(outcomeButton.textContent, decisionName === "approve" ? "Approve" : "Reject");
}
const failedOutcomeButton = { disabled: false, textContent: "Approve" }, failedOutcomeStatus = { textContent: "" };
globalThis.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: { message: "validation failed" } }) });
await recordDecisionOutcome({ decision: normalizeDecision(decision({ action: "BUY", withApproval: false })), decisionName: "approve", button: failedOutcomeButton, status: failedOutcomeStatus, reload: async () => { throw new Error("must not reload"); }, decisionMakerId: "operator-1", decidedAt: "2026-08-13T20:05", comment: null, confirmDecision: () => true });
assert.equal(failedOutcomeButton.disabled, false); assert.equal(failedOutcomeButton.textContent, "Approve"); assert.match(failedOutcomeStatus.textContent, /Decision approve failed: validation failed/);

const executionButton = { disabled: false, textContent: "Execute Paper Trade" }, executionStatus = { textContent: "" }, pendingExecution = deferred();
let executionReloads = 0, executionConfirmations = 0, executionRequest;
globalThis.fetch = async (url, options) => { executionRequest = { url, options }; return pendingExecution.promise; };
const executing = executePaperTrade({ decision: readyDecision, button: executionButton, status: executionStatus, reload: async () => { executionReloads += 1; }, executedAt: "2026-08-13T20:10", confirmExecution: () => { executionConfirmations += 1; return true; } });
assert.equal(executionConfirmations, 1);
assert.equal(executionButton.disabled, true);
assert.equal(executionButton.textContent, "Executing Paper Trade…");
assert.match(executionStatus.textContent, /deterministic backend/);
pendingExecution.resolve({ ok: true, json: async () => ({ decision_cycle_id: "cycle-1" }) });
await executing;
const executionUrl = new URL(executionRequest.url);
assert.equal(executionUrl.pathname, "/commands/decisions/cycle-1/execute-paper-trade");
assert.equal(executionUrl.searchParams.get("executed_at"), new Date("2026-08-13T20:10").toISOString());
assert.equal(executionRequest.options.method, "POST");
assert.equal("body" in executionRequest.options, false);
assert.equal(executionReloads, 1);
assert.equal(executionButton.disabled, false);
assert.equal(executionButton.textContent, "Execute Paper Trade");

const failedExecutionButton = { disabled: false, textContent: "Execute Paper Trade" }, failedExecutionStatus = { textContent: "" };
globalThis.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: { message: "no eligible persisted PriceObservation exists for execution" } }) });
await executePaperTrade({ decision: readyDecision, button: failedExecutionButton, status: failedExecutionStatus, reload: async () => { throw new Error("must not reload"); }, executedAt: "2026-08-13T20:10", confirmExecution: () => true });
assert.equal(failedExecutionButton.disabled, false);
assert.equal(failedExecutionButton.textContent, "Execute Paper Trade");
assert.match(failedExecutionStatus.textContent, /Paper execution failed: no eligible persisted PriceObservation/);

const shellRefreshButton = {
  disabled: false,
  textContent: "Refresh prices",
  listener: null,
  addEventListener(type, listener) { assert.equal(type, "click"); this.listener = listener; },
};
const shellBuildButton = {
  disabled: false,
  textContent: "Build research",
  listener: null,
  addEventListener(type, listener) { assert.equal(type, "click"); this.listener = listener; },
};
const shellBootstrapButton = {
  disabled: false,
  textContent: "Bootstrap OVERVIEW",
  listener: null,
  addEventListener(type, listener) { assert.equal(type, "click"); this.listener = listener; },
};
const shellStatus = { textContent: "" };
globalThis.document = {
  querySelector(selector) {
    return { "#refresh-prices": shellRefreshButton, "#build-research": shellBuildButton, "#bootstrap-overview": shellBootstrapButton, "#health-status": shellStatus }[selector] ?? null;
  },
};
bindShellCommands(globalThis.document);
globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: { message: "provider unavailable" } }) });
await shellRefreshButton.listener({ button: 0, type: "click" });
assert.equal(shellRefreshButton.disabled, false);
assert.equal(shellRefreshButton.textContent, "Refresh prices");
assert.equal(shellStatus.textContent, "Price refresh failed: provider unavailable");
globalThis.fetch = async () => ({ ok: false, status: 502, json: async () => ({ detail: { message: "research provider unavailable" } }) });
await shellBuildButton.listener({ button: 0, type: "click" });
assert.equal(shellBuildButton.disabled, false);
assert.equal(shellBuildButton.textContent, "Build research");
assert.equal(shellStatus.textContent, "Research build failed: research provider unavailable");
globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: { message: "overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH" } }) });
await shellBootstrapButton.listener({ button: 0, type: "click" });
assert.equal(shellBootstrapButton.disabled, false);
assert.equal(shellBootstrapButton.textContent, "Bootstrap OVERVIEW");
assert.match(shellStatus.textContent, /OVERVIEW bootstrap failed: overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH/);
delete globalThis.document;

const originalFetch = globalThis.fetch;
globalThis.fetch = async (url) => {
  const path = new URL(url).pathname;
  if (path === "/decisions/latest" || path === "/research/latest") return { status: 404, ok: false };
  const payloads = {
    "/health": { status: "ok", state_mode: "synthetic-in-memory", persisted: false, synthetic: true },
    "/dashboard": dashboard(),
    "/decisions": { entries_newest_first: [], chart_points_oldest_first: [] },
    "/portfolio": portfolio(),
    "/performance": dashboard().performance,
  };
  return { status: 200, ok: true, json: async () => payloads[path] };
};
const stateWithoutLatestResources = await loadApplication();
assert.equal(stateWithoutLatestResources.decision, null);
assert.equal(stateWithoutLatestResources.research, null);
assert.deepEqual(stateWithoutLatestResources.history, { entries: [], chartPoints: [] });

globalThis.fetch = async () => ({ status: 404, ok: false });
await assert.rejects(
  () => apiClient.get("/decisions"),
  (error) => error instanceof ApiError && error.status === 404,
);
globalThis.fetch = originalFetch;

assert.equal(new ApiError(404, "not found").status, 404);
assert.throws(() => normalizeDashboard({}), ApiContractError);
assert.throws(() => normalizeDecision({ ...decision(), recommendation: { action: "BUY" } }), ApiContractError);
assert.throws(() => { const { policy_evaluation, ...missingPolicyDecision } = decision(); normalizeDecision(missingPolicyDecision); }, ApiContractError);
assert.throws(() => normalizeResearch({ ...research(), packets: [{ ticker: "MSFT" }] }), ApiContractError);
assert.throws(() => normalizeHistory({ entries_newest_first: [], chart_points_oldest_first: [{ timestamp: "now" }] }), ApiContractError);

console.log("frontend mapping tests: ok");
