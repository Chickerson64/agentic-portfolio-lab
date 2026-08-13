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
  refreshPrices,
  buildResearch,
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
const validation = (tradeId = null) => ({ status: "PASSED", validation_timestamp: "2026-08-11T12:00:00+00:00", validated_trade_id: tradeId, rules: [{ rule_id: "RISK-1", status: "PASSED", reason: "Within policy", actual_value: null, allowed_threshold: null }] });
const reviewer = () => ({ decision: "APPROVE", reviewed_at: "2026-08-11T12:10:00+00:00", findings: [{ severity: "INFO", category: "EVIDENCE_USAGE", message: "Evidence cited.", related_evidence_ids: ["ev-1"], related_recommendation_field: "evidence" }] });
const approval = () => ({ decision: "APPROVED", decision_maker_id: "human-1", decided_at: "2026-08-11T12:20:00+00:00", comment: "Approved." });
const execution = () => ({
  executed_trade_id: "executed-1", validated_trade_id: "validated-1", security: security(), action: "BUY",
  executed_quantity: "0.50000000", execution_price: "200", executed_notional: "100.00000000", currency: "USD",
  source_provider_identity: "demo-provider", market_date: "2026-08-11", price_convention: "regular-session-close",
  executed_at: "2026-08-11T12:30:00+00:00", execution_source: "simulated",
});
const decision = ({ action = "HOLD", withReviewer = true, withApproval = true, withExecution = false } = {}) => ({
  decision_cycle_id: "cycle-1", portfolio_id: "portfolio-1", manager_type: "VALUE", constitution_version: "value-v1.0.0",
  research_batch_id: "batch-1", journaled_at: "2026-08-11T12:05:00+00:00", produced_at: "2026-08-11T12:00:00+00:00",
  recommendation: recommendation(action), validation: validation(withExecution ? "validated-1" : null),
  reviewer: withReviewer ? reviewer() : null, approval: withApproval ? approval() : null, execution: withExecution ? execution() : null,
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
assert.equal(normalizeDecision(null), null);

const buyView = normalizeDecision(decision({ action: "BUY", withExecution: true }));
assert.equal(buyView.recommendation.targetWeight, "0.25");
assert.equal(buyView.execution.executedTradeId, "executed-1");
assert.equal(buyView.execution.validatedTradeId, "validated-1");
assert.equal(buyView.execution.security.ticker, "MSFT");

const researchView = normalizeResearch(research());
assert.equal(researchView.packets[0].candidateId, "candidate-1");
assert.equal(researchView.packets[0].evidence[0].sourceDate, "2026-08-10");
assert.equal(researchView.packets[0].evidence[0].claimSupported, "Cash generation continued.");
assert.equal(normalizeResearch(null), null);

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

const originalFetch = globalThis.fetch;
globalThis.fetch = async (url) => {
  const path = new URL(url).pathname;
  if (path === "/decisions/latest" || path === "/research/latest") return { status: 404, ok: false };
  const payloads = {
    "/health": { status: "ok", state_mode: "synthetic-in-memory", persisted: false, synthetic: true },
    "/dashboard": dashboard(),
    "/decisions": { entries_newest_first: [], chart_points_oldest_first: [] },
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
assert.throws(() => normalizeResearch({ ...research(), packets: [{ ticker: "MSFT" }] }), ApiContractError);
assert.throws(() => normalizeHistory({ entries_newest_first: [], chart_points_oldest_first: [{ timestamp: "now" }] }), ApiContractError);

console.log("frontend mapping tests: ok");
