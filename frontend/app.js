const API_BASE = new URLSearchParams(window.location.search).get("api") || "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export class ApiContractError extends Error {
  constructor(message) { super(`Unexpected API response: ${message}`); }
}

export const apiClient = {
  async get(path, { allowNotFound = false } = {}) {
    let response;
    try { response = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } }); }
    catch { throw new ApiError(0, "The local API is unavailable. Start the FastAPI server and try again."); }
    if (response.status === 404 && allowNotFound) return null;
    if (!response.ok) throw new ApiError(response.status, `The API returned ${response.status}.`);
    return response.json();
  },
  async post(path) {
    let response;
    try { response = await fetch(`${API_BASE}${path}`, { method: "POST", headers: { Accept: "application/json" } }); }
    catch { throw new ApiError(0, "The local API is unavailable. Start the FastAPI server and try again."); }
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(response.status, payload?.detail?.message || `The API returned ${response.status}.`);
    return payload;
  },
};

function contractFailure(context, expectation) { throw new ApiContractError(`${context} must include ${expectation}.`); }
function record(value, context) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) contractFailure(context, "an object");
  return value;
}
function field(value, key, context) {
  const source = record(value, context);
  if (!Object.hasOwn(source, key)) contractFailure(context, `required field '${key}'`);
  return source[key];
}
function text(value, context) {
  if (typeof value !== "string") contractFailure(context, "a string");
  return value;
}
function number(value, context) {
  if (typeof value !== "number" || !Number.isFinite(value)) contractFailure(context, "a finite number");
  return value;
}
function boolean(value, context) {
  if (typeof value !== "boolean") contractFailure(context, "a boolean");
  return value;
}
function list(value, context) {
  if (!Array.isArray(value)) contractFailure(context, "an array");
  return value;
}
function nullableText(value, context) { return value === null ? null : text(value, context); }
function nullableRecord(value, context) { return value === null ? null : record(value, context); }
function textList(value, context) { return list(value, context).map((item, index) => text(item, `${context}[${index}]`)); }

function normalizeSecurity(payload, context) {
  return {
    ticker: text(field(payload, "ticker", context), `${context}.ticker`),
    securityType: text(field(payload, "security_type", context), `${context}.security_type`),
    exchange: text(field(payload, "exchange", context), `${context}.exchange`),
    currency: text(field(payload, "currency", context), `${context}.currency`),
  };
}

function normalizePortfolio(payload, context) {
  const positions = list(field(payload, "positions", context), `${context}.positions`).map((position, index) => {
    const item = `${context}.positions[${index}]`;
    return {
      security: normalizeSecurity(field(position, "security", item), `${item}.security`),
      quantity: text(field(position, "quantity", item), `${item}.quantity`),
      observedPrice: text(field(position, "observed_price", item), `${item}.observed_price`),
      totalCostBasis: text(field(position, "total_cost_basis", item), `${item}.total_cost_basis`),
      marketValue: text(field(position, "market_value", item), `${item}.market_value`),
      unrealizedGainLoss: text(field(position, "unrealized_gain_loss", item), `${item}.unrealized_gain_loss`),
    };
  });
  return {
    portfolioId: text(field(payload, "portfolio_id", context), `${context}.portfolio_id`),
    portfolioName: text(field(payload, "portfolio_name", context), `${context}.portfolio_name`),
    baseCurrency: text(field(payload, "base_currency", context), `${context}.base_currency`),
    startingCapital: text(field(payload, "starting_capital", context), `${context}.starting_capital`),
    createdAt: text(field(payload, "created_at", context), `${context}.created_at`),
    decisionCycleId: nullableText(field(payload, "decision_cycle_id", context), `${context}.decision_cycle_id`),
    status: text(field(payload, "status", context), `${context}.status`),
    asOfTimestamp: text(field(payload, "as_of_timestamp", context), `${context}.as_of_timestamp`),
    cashValue: text(field(payload, "cash_value", context), `${context}.cash_value`),
    investedValue: text(field(payload, "invested_value", context), `${context}.invested_value`),
    totalValue: text(field(payload, "total_value", context), `${context}.total_value`),
    unrealizedGainLoss: text(field(payload, "unrealized_gain_loss", context), `${context}.unrealized_gain_loss`),
    sourceProviderIdentity: text(field(payload, "source_provider_identity", context), `${context}.source_provider_identity`),
    marketDate: text(field(payload, "market_date", context), `${context}.market_date`),
    sourcePriceTimestamp: text(field(payload, "source_price_timestamp", context), `${context}.source_price_timestamp`),
    priceConvention: text(field(payload, "price_convention", context), `${context}.price_convention`),
    positions,
  };
}

function normalizePerformance(payload, context) {
  return {
    managedPortfolioId: text(field(payload, "managed_portfolio_id", context), `${context}.managed_portfolio_id`),
    benchmarkPortfolioId: text(field(payload, "benchmark_portfolio_id", context), `${context}.benchmark_portfolio_id`),
    currency: text(field(payload, "currency", context), `${context}.currency`),
    managedCumulativeReturn: text(field(payload, "managed_cumulative_return", context), `${context}.managed_cumulative_return`),
    benchmarkCumulativeReturn: text(field(payload, "benchmark_cumulative_return", context), `${context}.benchmark_cumulative_return`),
    absoluteAlpha: text(field(payload, "absolute_alpha", context), `${context}.absolute_alpha`),
    relativeAlpha: text(field(payload, "relative_alpha", context), `${context}.relative_alpha`),
    asOfTimestamp: text(field(payload, "as_of_timestamp", context), `${context}.as_of_timestamp`),
  };
}

function normalizeEvidence(payload, context) {
  return {
    evidenceId: text(field(payload, "evidence_id", context), `${context}.evidence_id`),
    sourceType: text(field(payload, "source_type", context), `${context}.source_type`),
    sourceTitle: text(field(payload, "source_title", context), `${context}.source_title`),
    sourceDate: text(field(payload, "source_date", context), `${context}.source_date`),
    claimSupported: text(field(payload, "claim_supported", context), `${context}.claim_supported`),
  };
}

function normalizeRecommendation(payload, context) {
  return {
    action: text(field(payload, "action", context), `${context}.action`),
    ticker: nullableText(field(payload, "ticker", context), `${context}.ticker`),
    targetWeight: nullableText(field(payload, "target_weight", context), `${context}.target_weight`),
    decisionRationale: text(field(payload, "decision_rationale", context), `${context}.decision_rationale`),
    investmentThesis: nullableText(field(payload, "investment_thesis", context), `${context}.investment_thesis`),
    valuation: text(field(payload, "valuation", context), `${context}.valuation`),
    risks: textList(field(payload, "risks", context), `${context}.risks`),
    confidenceScore: number(field(payload, "confidence_score", context), `${context}.confidence_score`),
    evidence: list(field(payload, "evidence", context), `${context}.evidence`).map((item, index) => normalizeEvidence(item, `${context}.evidence[${index}]`)),
    whyNotSpy: text(field(payload, "why_not_spy", context), `${context}.why_not_spy`),
    thesisInvalidation: textList(field(payload, "thesis_invalidation", context), `${context}.thesis_invalidation`),
    reviewTriggers: textList(field(payload, "review_triggers", context), `${context}.review_triggers`),
  };
}

function normalizeValidation(payload, context) {
  return {
    status: text(field(payload, "status", context), `${context}.status`),
    validationTimestamp: text(field(payload, "validation_timestamp", context), `${context}.validation_timestamp`),
    validatedTradeId: nullableText(field(payload, "validated_trade_id", context), `${context}.validated_trade_id`),
    rules: list(field(payload, "rules", context), `${context}.rules`).map((rule, index) => {
      const item = `${context}.rules[${index}]`;
      return {
        ruleId: text(field(rule, "rule_id", item), `${item}.rule_id`),
        status: text(field(rule, "status", item), `${item}.status`),
        reason: text(field(rule, "reason", item), `${item}.reason`),
        actualValue: nullableText(field(rule, "actual_value", item), `${item}.actual_value`),
        allowedThreshold: nullableText(field(rule, "allowed_threshold", item), `${item}.allowed_threshold`),
      };
    }),
  };
}

function normalizeReviewer(payload, context) {
  if (payload === null) return null;
  return {
    decision: text(field(payload, "decision", context), `${context}.decision`),
    reviewedAt: text(field(payload, "reviewed_at", context), `${context}.reviewed_at`),
    findings: list(field(payload, "findings", context), `${context}.findings`).map((finding, index) => {
      const item = `${context}.findings[${index}]`;
      return {
        severity: text(field(finding, "severity", item), `${item}.severity`),
        category: text(field(finding, "category", item), `${item}.category`),
        message: text(field(finding, "message", item), `${item}.message`),
        relatedEvidenceIds: textList(field(finding, "related_evidence_ids", item), `${item}.related_evidence_ids`),
        relatedRecommendationField: nullableText(field(finding, "related_recommendation_field", item), `${item}.related_recommendation_field`),
      };
    }),
  };
}

function normalizeApproval(payload, context) {
  if (payload === null) return null;
  return {
    decision: text(field(payload, "decision", context), `${context}.decision`),
    decisionMakerId: text(field(payload, "decision_maker_id", context), `${context}.decision_maker_id`),
    decidedAt: text(field(payload, "decided_at", context), `${context}.decided_at`),
    comment: nullableText(field(payload, "comment", context), `${context}.comment`),
  };
}

function normalizeExecution(payload, context) {
  if (payload === null) return null;
  return {
    executedTradeId: text(field(payload, "executed_trade_id", context), `${context}.executed_trade_id`),
    validatedTradeId: text(field(payload, "validated_trade_id", context), `${context}.validated_trade_id`),
    security: normalizeSecurity(field(payload, "security", context), `${context}.security`),
    action: text(field(payload, "action", context), `${context}.action`),
    executedQuantity: text(field(payload, "executed_quantity", context), `${context}.executed_quantity`),
    executionPrice: text(field(payload, "execution_price", context), `${context}.execution_price`),
    executedNotional: text(field(payload, "executed_notional", context), `${context}.executed_notional`),
    currency: text(field(payload, "currency", context), `${context}.currency`),
    sourceProviderIdentity: text(field(payload, "source_provider_identity", context), `${context}.source_provider_identity`),
    marketDate: text(field(payload, "market_date", context), `${context}.market_date`),
    priceConvention: text(field(payload, "price_convention", context), `${context}.price_convention`),
    executedAt: text(field(payload, "executed_at", context), `${context}.executed_at`),
    executionSource: text(field(payload, "execution_source", context), `${context}.execution_source`),
  };
}

export function normalizeDecision(payload) {
  if (payload === null) return null;
  const context = "decision";
  record(payload, context);
  return {
    decisionCycleId: text(field(payload, "decision_cycle_id", context), `${context}.decision_cycle_id`),
    portfolioId: text(field(payload, "portfolio_id", context), `${context}.portfolio_id`),
    managerType: text(field(payload, "manager_type", context), `${context}.manager_type`),
    constitutionVersion: text(field(payload, "constitution_version", context), `${context}.constitution_version`),
    researchBatchId: text(field(payload, "research_batch_id", context), `${context}.research_batch_id`),
    journaledAt: text(field(payload, "journaled_at", context), `${context}.journaled_at`),
    producedAt: text(field(payload, "produced_at", context), `${context}.produced_at`),
    recommendation: normalizeRecommendation(field(payload, "recommendation", context), `${context}.recommendation`),
    validation: normalizeValidation(field(payload, "validation", context), `${context}.validation`),
    reviewer: normalizeReviewer(field(payload, "reviewer", context), `${context}.reviewer`),
    approval: normalizeApproval(field(payload, "approval", context), `${context}.approval`),
    execution: normalizeExecution(field(payload, "execution", context), `${context}.execution`),
  };
}

export function normalizeResearch(payload) {
  if (payload === null) return null;
  const context = "research";
  record(payload, context);
  return {
    batchId: text(field(payload, "batch_id", context), `${context}.batch_id`),
    decisionCycleId: text(field(payload, "decision_cycle_id", context), `${context}.decision_cycle_id`),
    portfolioId: text(field(payload, "portfolio_id", context), `${context}.portfolio_id`),
    managerType: text(field(payload, "manager_type", context), `${context}.manager_type`),
    createdAt: text(field(payload, "created_at", context), `${context}.created_at`),
    asOfTimestamp: text(field(payload, "as_of_timestamp", context), `${context}.as_of_timestamp`),
    packets: list(field(payload, "packets", context), `${context}.packets`).map((packet, index) => {
      const item = `${context}.packets[${index}]`;
      return {
        packetId: text(field(packet, "packet_id", item), `${item}.packet_id`),
        candidateId: text(field(packet, "candidate_id", item), `${item}.candidate_id`),
        ticker: text(field(packet, "ticker", item), `${item}.ticker`),
        securityType: text(field(packet, "security_type", item), `${item}.security_type`),
        exchange: nullableText(field(packet, "exchange", item), `${item}.exchange`),
        currency: nullableText(field(packet, "currency", item), `${item}.currency`),
        companyName: nullableText(field(packet, "company_name", item), `${item}.company_name`),
        sector: nullableText(field(packet, "sector", item), `${item}.sector`),
        industry: nullableText(field(packet, "industry", item), `${item}.industry`),
        asOfTimestamp: text(field(packet, "as_of_timestamp", item), `${item}.as_of_timestamp`),
        evidence: list(field(packet, "evidence", item), `${item}.evidence`).map((evidence, evidenceIndex) => normalizeEvidence(evidence, `${item}.evidence[${evidenceIndex}]`)),
        sections: list(field(packet, "sections", item), `${item}.sections`).map((section, sectionIndex) => {
          const sectionContext = `${item}.sections[${sectionIndex}]`;
          const missingData = nullableRecord(field(section, "missing_data", sectionContext), `${sectionContext}.missing_data`);
          return {
            sectionId: text(field(section, "section_id", sectionContext), `${sectionContext}.section_id`),
            content: nullableText(field(section, "content", sectionContext), `${sectionContext}.content`),
            missingData: missingData === null ? null : {
              reason: text(field(missingData, "reason", `${sectionContext}.missing_data`), `${sectionContext}.missing_data.reason`),
            },
            evidenceIds: textList(field(section, "evidence_ids", sectionContext), `${sectionContext}.evidence_ids`),
          };
        }),
      };
    }),
  };
}

function normalizeHistoryExecution(payload, context) {
  return {
    status: text(field(payload, "status", context), `${context}.status`),
    executedTradeId: nullableText(field(payload, "executed_trade_id", context), `${context}.executed_trade_id`),
    validatedTradeId: nullableText(field(payload, "validated_trade_id", context), `${context}.validated_trade_id`),
    security: nullableRecord(field(payload, "security", context), `${context}.security`) === null ? null : normalizeSecurity(field(payload, "security", context), `${context}.security`),
    action: nullableText(field(payload, "action", context), `${context}.action`),
    executionPrice: nullableText(field(payload, "execution_price", context), `${context}.execution_price`),
    quantity: nullableText(field(payload, "quantity", context), `${context}.quantity`),
    notional: nullableText(field(payload, "notional", context), `${context}.notional`),
    executedAt: nullableText(field(payload, "executed_at", context), `${context}.executed_at`),
  };
}

export function normalizeHistory(payload) {
  const context = "history";
  record(payload, context);
  return {
    entries: list(field(payload, "entries_newest_first", context), `${context}.entries_newest_first`).map((entry, index) => {
      const item = `${context}.entries_newest_first[${index}]`;
      return {
        historyEntryId: text(field(entry, "history_entry_id", item), `${item}.history_entry_id`),
        decisionCycleId: text(field(entry, "decision_cycle_id", item), `${item}.decision_cycle_id`),
        decisionTimestamp: text(field(entry, "decision_timestamp", item), `${item}.decision_timestamp`),
        action: text(field(entry, "action", item), `${item}.action`),
        ticker: text(field(entry, "ticker", item), `${item}.ticker`),
        targetWeight: text(field(entry, "target_weight", item), `${item}.target_weight`),
        reviewerOutcome: text(field(entry, "reviewer_outcome", item), `${item}.reviewer_outcome`),
        approvalOutcome: text(field(entry, "approval_outcome", item), `${item}.approval_outcome`),
        researchBatchId: text(field(entry, "research_batch_id", item), `${item}.research_batch_id`),
        researchPacketId: nullableText(field(entry, "research_packet_id", item), `${item}.research_packet_id`),
        execution: normalizeHistoryExecution(field(entry, "execution", item), `${item}.execution`),
      };
    }),
    chartPoints: list(field(payload, "chart_points_oldest_first", context), `${context}.chart_points_oldest_first`).map((point, index) => {
      const item = `${context}.chart_points_oldest_first[${index}]`;
      return {
        timestamp: text(field(point, "timestamp", item), `${item}.timestamp`),
        portfolioValue: text(field(point, "portfolio_value", item), `${item}.portfolio_value`),
        managedReturn: text(field(point, "managed_return", item), `${item}.managed_return`),
        benchmarkReturn: text(field(point, "benchmark_return", item), `${item}.benchmark_return`),
        absoluteAlpha: text(field(point, "absolute_alpha", item), `${item}.absolute_alpha`),
      };
    }),
  };
}

export function normalizeDashboard(payload) {
  if (payload === null) contractFailure("dashboard", "an object");
  const context = "dashboard";
  record(payload, context);
  const benchmark = field(payload, "benchmark", context);
  return {
    portfolio: normalizePortfolio(field(payload, "portfolio", context), `${context}.portfolio`),
    benchmark: {
      security: normalizeSecurity(field(benchmark, "benchmark_security", `${context}.benchmark`), `${context}.benchmark.benchmark_security`),
      snapshot: normalizePortfolio(field(benchmark, "snapshot", `${context}.benchmark`), `${context}.benchmark.snapshot`),
    },
    performance: normalizePerformance(field(payload, "performance", context), `${context}.performance`),
    latestDecision: normalizeDecision(field(payload, "latest_decision", context)),
    research: normalizeResearch(field(payload, "research", context)),
    history: normalizeHistory(field(payload, "history", context)),
  };
}

export function normalizeHealth(payload) {
  const context = "health";
  return {
    status: text(field(payload, "status", context), `${context}.status`),
    stateMode: text(field(payload, "state_mode", context), `${context}.state_mode`),
    persisted: boolean(field(payload, "persisted", context), `${context}.persisted`),
    synthetic: boolean(field(payload, "synthetic", context), `${context}.synthetic`),
  };
}

export function normalizePriceRefresh(payload) {
  const context = "price refresh";
  return {
    refreshedTickers: textList(field(payload, "refreshed_tickers", context), `${context}.refreshed_tickers`),
    providerIdentity: text(field(payload, "provider_identity", context), `${context}.provider_identity`),
    latestSourceTimestamp: text(field(payload, "latest_source_timestamp", context), `${context}.latest_source_timestamp`),
    priceConvention: text(field(payload, "price_convention", context), `${context}.price_convention`),
  };
}

export async function loadApplication() {
  const [health, dashboard, decision, research, history] = await Promise.all([
    apiClient.get("/health"),
    apiClient.get("/dashboard"),
    apiClient.get("/decisions/latest", { allowNotFound: true }),
    apiClient.get("/research/latest", { allowNotFound: true }),
    apiClient.get("/decisions"),
  ]);
  return { health: normalizeHealth(health), dashboard: normalizeDashboard(dashboard), decision: normalizeDecision(decision), research: normalizeResearch(research), history: normalizeHistory(history) };
}

const string = (value, fallback = "—") => value == null || value === "" ? fallback : String(value);
const money = (value, currency = "USD") => value == null ? "—" : `${currency} ${String(value)}`;
const percent = (value) => value == null ? "—" : `${(Number.parseFloat(value) * 100).toFixed(2)}%`;
const dateTime = (value) => value ? new Date(value).toLocaleString() : "—";
const initials = (ticker) => string(ticker, "—").slice(0, 2);
const esc = (value) => string(value).replace(/[&<>'"]/g, (character) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[character]);
const app = typeof document === "undefined" ? null : document.querySelector("#app");
let refreshStatus = null;

function chart(points) {
  if (!points.length) return `<div class="empty-state">No performance snapshots are available.</div>`;
  const values = points.map((point) => [Number(point.managedReturn), Number(point.benchmarkReturn)]).flat();
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const path = (key) => points.map((point, index) => `${index ? "L" : "M"}${(index / Math.max(points.length - 1, 1)) * 100} ${100 - ((Number(point[key]) - min) / span) * 90 - 5}`).join(" ");
  return `<svg class="chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Managed and SPY return history"><path class="managed" d="${path("managedReturn")}"/><path class="benchmark" d="${path("benchmarkReturn")}"/></svg><div class="chart-labels"><span>${esc(dateTime(points[0].timestamp))}</span><span>${esc(dateTime(points.at(-1).timestamp))}</span></div>`;
}

function nav() { return `<section class="view active" id="overview"></section><section class="view" id="decision"></section><section class="view" id="research"></section><section class="view" id="portfolio"></section><section class="view" id="history"></section>`; }
function renderOverview(state) {
  const { portfolio, benchmark, performance, history } = state.dashboard;
  const holdings = portfolio.positions.slice(0, 4).map((position) => `<div class="holding-row"><i class="symbol">${esc(initials(position.security.ticker))}</i><div class="holding-main"><strong>${esc(position.security.ticker)}</strong><small>${esc(money(position.marketValue, position.security.currency))}</small></div><span class="weight">${esc(position.quantity)} shares</span></div>`).join("");
  const activity = history.entries.slice(0, 4).map((entry) => `<div class="history-row"><i class="symbol">${esc(entry.action === "HOLD" ? "—" : initials(entry.ticker))}</i><div class="history-main"><strong>${esc(entry.action)} ${esc(entry.ticker)}</strong><small>${esc(entry.execution.status)} · ${esc(dateTime(entry.decisionTimestamp))}</small></div></div>`).join("");
  document.querySelector("#overview").innerHTML = `<div class="page-heading"><div><span class="kicker">Portfolio command center</span><h1>Portfolio state at a glance</h1><p>Read-only state from the deterministic application API.</p></div><div class="cycle-id"><span class="kicker">Valuation</span><strong>${esc(dateTime(portfolio.asOfTimestamp))}</strong><small>${esc(portfolio.sourceProviderIdentity)} · ${esc(portfolio.priceConvention)}</small></div></div><section class="overview-hero surface"><div><span class="kicker">Managed portfolio value</span><strong class="value">${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong><p><b class="${Number(performance.managedCumulativeReturn) >= 0 ? "positive" : "negative"}">${esc(percent(performance.managedCumulativeReturn))}</b> since baseline</p><small class="muted">Cash ${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</small></div><div><span class="kicker">Performance snapshot</span><h2>Managed vs. SPY</h2>${chart(history.chartPoints)}</div><div><span class="kicker">Comparable benchmark</span><strong class="value">${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong><p>SPY · ${esc(percent(performance.benchmarkCumulativeReturn))}</p><strong class="${Number(performance.absoluteAlpha) >= 0 ? "positive" : "negative"}">${esc(percent(performance.absoluteAlpha))} alpha</strong></div></section><div class="metric-grid"><article class="metric-card"><span>Managed Value</span><strong>${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>SPY Benchmark</span><strong>${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong></article><article class="metric-card"><span>Absolute Alpha</span><strong class="${Number(performance.absoluteAlpha) >= 0 ? "positive" : "negative"}">${esc(percent(performance.absoluteAlpha))}</strong></article><article class="metric-card"><span>Available Cash</span><strong>${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</strong></article></div><div class="two-col"><article class="surface"><div class="surface-head"><div><span class="kicker">Portfolio</span><h2>Holdings preview</h2></div><button class="text-button" data-view-jump="portfolio">All holdings →</button></div>${holdings || "<p class=muted>No positions are held.</p>"}</article><article class="surface"><div class="surface-head"><div><span class="kicker">AI decision journal</span><h2>Recent activity</h2></div><button class="text-button" data-view-jump="history">Full history →</button></div>${activity || "<p class=muted>No decision history is available.</p>"}</article></div>`;
}
function renderDecision(state) {
  const target = document.querySelector("#decision"); const decision = state.decision;
  if (!decision) { target.innerHTML = empty("No latest decision", "The API reports no latest decision. No recommendation is being inferred."); return; }
  const r = decision.recommendation, execution = decision.execution, reviewer = decision.reviewer, approval = decision.approval;
  const lifecycle = [["Manager decided", `${r.action} · ${r.confidenceScore}/100`, decision.producedAt], ["Code validated", decision.validation.status, decision.validation.validationTimestamp], ["Reviewer", reviewer ? reviewer.decision : "Not reviewed", reviewer?.reviewedAt], ["Human approval", approval ? approval.decision : "Not approved", approval?.decidedAt], ["Execution", execution ? `${execution.action} ${execution.security.ticker}` : r.action === "HOLD" ? "No execution — HOLD" : "No execution", execution?.executedAt]].map(([name, status, time]) => `<div><span class="kicker">${esc(name)}</span><strong>${esc(status)}</strong><small>${esc(dateTime(time))}</small></div>`).join("");
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Decision center</span><h1>Verified decision lifecycle</h1><p>Recommendation, deterministic validation, review, and approval are separate artifacts.</p></div><div class="cycle-id"><span class="kicker">Decision cycle</span><strong>${esc(decision.decisionCycleId)}</strong><small>${esc(decision.constitutionVersion)}</small></div></div><article class="decision-hero"><div class="decision-main"><div class="recommendation-top"><i class="symbol">${esc(initials(r.ticker))}</i><div><span class="kicker">Latest manager recommendation</span><h2>${esc(r.action)} ${esc(r.ticker)}</h2><p>${esc(r.valuation)}</p></div><span class="chip ${r.action === "BUY" ? "buy" : "hold"}">${esc(r.action)}</span></div><p class="thesis">${esc(r.decisionRationale)}</p><div class="facts"><div><span>Target weight</span><strong>${esc(percent(r.targetWeight))}</strong></div><div><span>Confidence</span><strong>${esc(r.confidenceScore)}/100</strong></div><div><span>Execution</span><strong>${esc(execution ? `${execution.executedQuantity} shares` : "None")}</strong></div></div><section class="section-card"><span class="kicker">Why not SPY</span><p>${esc(r.whyNotSpy)}</p></section></div><aside class="confidence"><span class="kicker">Evidence confidence</span><strong class="value">${esc(r.confidenceScore)}</strong><p>${esc(r.evidence.length)} cited evidence item(s)</p><p class="muted">${esc(reviewer ? `${reviewer.findings.length} reviewer finding(s)` : "Reviewer absent")}</p></aside></article><section class="lifecycle"><div class="surface-head"><div><span class="kicker">Verified lifecycle</span><h2>How this became portfolio state</h2></div></div><div class="lifecycle-grid">${lifecycle}</div></section><div class="two-col"><article class="surface"><span class="kicker">Thesis and risks</span><h2>Decision memo</h2><p class="thesis">${esc(r.investmentThesis ?? "No investment thesis — HOLD")}</p><h3>Risks</h3><ul>${r.risks.map((risk) => `<li>${esc(risk)}</li>`).join("")}</ul></article><article class="surface"><span class="kicker">Execution lineage</span><h2>${execution ? "Simulated execution" : "No execution"}</h2>${execution ? `<p>${esc(execution.action)} ${esc(execution.executedQuantity)} ${esc(execution.security.ticker)} @ ${esc(money(execution.executionPrice, execution.currency))}</p><small class="muted">Executed trade ${esc(execution.executedTradeId)} · validated trade ${esc(execution.validatedTradeId)}</small>` : `<p class="muted">${r.action === "HOLD" ? "HOLD correctly produced no execution." : "No execution artifact is available."}</p>`}</article></div>`;
}
function renderResearch(state) {
  const target = document.querySelector("#research"), research = state.research;
  if (!research) { target.innerHTML = empty("No latest research", "The API reports no authoritative ResearchBatch for the latest decision."); return; }
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Research workspace</span><h1>Source-backed research packets</h1><p>Research is immutable input; it is not a recommendation.</p></div><div class="cycle-id"><span class="kicker">Research batch</span><strong>${esc(research.batchId)}</strong><small>${esc(research.packets.length)} packets</small></div></div><div class="packet-list"><aside class="packet-nav">${research.packets.map((item, index) => `<button class="packet-button ${index === 0 ? "active" : ""}" data-packet-index="${index}"><strong>${esc(item.ticker)}</strong><small>${esc(item.companyName)}</small></button>`).join("")}</aside><article class="surface document" id="research-document"></article></div>`;
  const paint = (selected) => { const packet = research.packets[selected]; document.querySelector("#research-document").innerHTML = `<span class="kicker">${esc(packet.packetId)}</span><h2>${esc(packet.companyName)}</h2><p class="muted">${esc(packet.exchange)} · ${esc(packet.industry)} · ${esc(packet.currency)}</p>${packet.sections.map((section) => `<section class="section-card"><h3>${esc(section.sectionId)}</h3><p>${esc(section.content ?? `Missing data: ${section.missingData?.reason ?? "unspecified"}`)}</p><small class="muted">Evidence: ${esc(section.evidenceIds.join(", ") || "none")}</small></section>`).join("")}<h3>Evidence</h3><table class="evidence-table"><thead><tr><th>ID</th><th>Source</th><th>Date</th><th>Claim</th></tr></thead><tbody>${packet.evidence.map((evidence) => `<tr><td>${esc(evidence.evidenceId)}</td><td>${esc(evidence.sourceType)} · ${esc(evidence.sourceTitle)}</td><td>${esc(evidence.sourceDate)}</td><td>${esc(evidence.claimSupported)}</td></tr>`).join("")}</tbody></table>`; };
  paint(0); target.querySelectorAll("[data-packet-index]").forEach((button) => button.addEventListener("click", () => { target.querySelectorAll("[data-packet-index]").forEach((node) => node.classList.remove("active")); button.classList.add("active"); paint(Number(button.dataset.packetIndex)); }));
}
function renderPortfolio(state) {
  const target = document.querySelector("#portfolio"), { portfolio, benchmark, performance, history } = state.dashboard;
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Deterministic state</span><h1>Portfolio & performance</h1><p>Values are supplied by comparable API valuations.</p></div><div class="cycle-id"><span class="kicker">Price convention</span><strong>${esc(portfolio.priceConvention)}</strong><small>${esc(portfolio.sourceProviderIdentity)}</small></div></div><div class="metric-grid"><article class="metric-card"><span>Total value</span><strong>${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>Invested value</span><strong>${esc(money(portfolio.investedValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>Cash</span><strong>${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>SPY benchmark</span><strong>${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong></article></div><article class="surface table-wrap"><div class="surface-head"><div><span class="kicker">Current positions</span><h2>Holdings</h2></div><span class="chip">${esc(portfolio.status)}</span></div><table class="holdings"><thead><tr><th>Security</th><th>Quantity</th><th>Cost basis</th><th>Close</th><th>Market value</th><th>Unrealized</th></tr></thead><tbody>${portfolio.positions.map((position) => `<tr><td><strong>${esc(position.security.ticker)}</strong></td><td>${esc(position.quantity)}</td><td>${esc(money(position.totalCostBasis, position.security.currency))}</td><td>${esc(money(position.observedPrice, position.security.currency))}</td><td>${esc(money(position.marketValue, position.security.currency))}</td><td class="${Number(position.unrealizedGainLoss) >= 0 ? "positive" : "negative"}">${esc(money(position.unrealizedGainLoss, position.security.currency))}</td></tr>`).join("")}</tbody></table></article><article class="surface"><span class="kicker">Performance history</span><h2>Managed vs. SPY</h2>${chart(history.chartPoints)}<p class="muted">Managed ${esc(percent(performance.managedCumulativeReturn))} · SPY ${esc(percent(performance.benchmarkCumulativeReturn))} · Alpha ${esc(percent(performance.absoluteAlpha))}</p></article>`;
}
function renderHistory(state) {
  const target = document.querySelector("#history"), history = state.history;
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Immutable lineage</span><h1>Decision & portfolio history</h1><p>Entries are returned newest first by the application API.</p></div><div class="cycle-id"><span class="kicker">Visible history</span><strong>${esc(history.entries.length)} entries</strong></div></div><div class="history-list">${history.entries.map((entry) => `<article class="history-row"><i class="symbol">${esc(entry.action === "HOLD" ? "—" : initials(entry.ticker))}</i><div class="history-main"><span class="kicker">${esc(entry.execution.status)}</span><strong>${esc(entry.action)} ${esc(entry.ticker)}</strong><small>Reviewer: ${esc(entry.reviewerOutcome)} · Approval: ${esc(entry.approvalOutcome)} · ${esc(dateTime(entry.decisionTimestamp))}</small>${entry.execution.executedTradeId ? `<small>Execution ${esc(entry.execution.executedTradeId)} → validated ${esc(entry.execution.validatedTradeId)} · ${esc(entry.execution.quantity)} ${esc(entry.execution.security.ticker)} @ ${esc(entry.execution.executionPrice)}</small>` : ""}</div><code>${esc(entry.decisionCycleId)}</code></article>`).join("") || "<section class=empty-state>No decision history is available.</section>"}</div>`;
}
function empty(title, message) { return `<section class="empty-state"><span class="kicker">No data</span><h1>${esc(title)}</h1><p>${esc(message)}</p></section>`; }
function render(state) {
  app.innerHTML = nav(); document.querySelector("#portfolio-name").textContent = state.dashboard.portfolio.portfolioName;
  document.querySelector("#health-status").textContent = refreshStatus || `${state.health.stateMode} · ${state.health.persisted ? "persisted" : "in-memory"}${state.health.synthetic ? " · demo" : ""}`;
  renderOverview(state); renderDecision(state); renderResearch(state); renderPortfolio(state); renderHistory(state);
  document.querySelectorAll("[data-view],[data-view-jump]").forEach((button) => button.addEventListener("click", () => { const view = button.dataset.view || button.dataset.viewJump; document.querySelectorAll(".view").forEach((section) => section.classList.toggle("active", section.id === view)); document.querySelectorAll("[data-view]").forEach((node) => node.classList.toggle("active", node.dataset.view === view)); }));
}
function renderFailure(error) {
  const template = document.querySelector("#error-template"); const node = template.content.cloneNode(true);
  node.querySelector("h1").textContent = error.status >= 500 ? "API state is unavailable" : "Unable to load the operator interface";
  node.querySelector("p").textContent = error.message; node.querySelector("[data-retry]").addEventListener("click", start);
  app.replaceChildren(node); document.querySelector("#health-status").textContent = "API unavailable";
}
export async function start() { app.innerHTML = `<section class="loading-state"><span class="spinner"></span><h1>Loading deterministic portfolio state</h1><p>Reading the local API contract.</p></section>`; try { render(await loadApplication()); } catch (error) { renderFailure(error); } }
export async function refreshPrices({ button = document.querySelector("#refresh-prices"), status = document.querySelector("#health-status"), reload = start } = {}) {
  button.disabled = true; button.textContent = "Refreshing prices…"; status.textContent = "Requesting Twelve Data observations…";
  try {
    const result = normalizePriceRefresh(await apiClient.post("/commands/refresh-prices"));
    refreshStatus = `Prices refreshed from ${result.providerIdentity} · ${dateTime(result.latestSourceTimestamp)} · ${result.priceConvention}`;
    status.textContent = refreshStatus;
    await reload();
  } catch (error) {
    refreshStatus = `Price refresh failed: ${error.message}`;
    status.textContent = refreshStatus;
  } finally {
    button.disabled = false; button.textContent = "Refresh prices";
  }
}
if (app) { document.querySelector("#refresh-prices").addEventListener("click", refreshPrices); start(); }
