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
  async post(path, body = undefined) {
    let response;
    try { response = await fetch(`${API_BASE}${path}`, { method: "POST", headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) }); }
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
  if (payload === null) return null;
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
        layer: text(field(rule, "layer", item), `${item}.layer`),
        policyVersion: nullableText(field(rule, "policy_version", item), `${item}.policy_version`),
        inputReferences: textList(field(rule, "input_references", item), `${item}.input_references`),
      };
    }),
  };
}

function normalizePolicyEvaluation(payload, context) {
  return {
    policyKind: text(field(payload, "policy_kind", context), `${context}.policy_kind`),
    investmentConstitutionVersion: nullableText(field(payload, "investment_constitution_version", context), `${context}.investment_constitution_version`),
    investmentConstitutionHash: nullableText(field(payload, "investment_constitution_hash", context), `${context}.investment_constitution_hash`),
    systemSafetyEnvelopeVersion: nullableText(field(payload, "system_safety_envelope_version", context), `${context}.system_safety_envelope_version`),
    systemSafetyEnvelopeHash: nullableText(field(payload, "system_safety_envelope_hash", context), `${context}.system_safety_envelope_hash`),
    managerRiskConstitutionVersion: nullableText(field(payload, "manager_risk_constitution_version", context), `${context}.manager_risk_constitution_version`),
    managerRiskConstitutionHash: nullableText(field(payload, "manager_risk_constitution_hash", context), `${context}.manager_risk_constitution_hash`),
    mechanicallyExecutable: boolean(field(payload, "mechanically_executable", context), `${context}.mechanically_executable`),
    advisoryFindings: list(field(payload, "advisory_findings", context), `${context}.advisory_findings`).map((finding, index) => {
      const item = `${context}.advisory_findings[${index}]`;
      return {
        findingId: text(field(finding, "finding_id", item), `${item}.finding_id`),
        severity: text(field(finding, "severity", item), `${item}.severity`),
        reason: text(field(finding, "reason", item), `${item}.reason`),
        actualValue: nullableText(field(finding, "actual_value", item), `${item}.actual_value`),
        guidanceValue: nullableText(field(finding, "guidance_value", item), `${item}.guidance_value`),
        inputReferences: textList(field(finding, "input_references", item), `${item}.input_references`),
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

function normalizeExecutionReadiness(payload, context) {
  const value = record(payload, context);
  const securityPayload = nullableRecord(field(value, "security", context), `${context}.security`);
  return {
    executable: boolean(field(value, "executable", context), `${context}.executable`),
    reasonCode: text(field(value, "reason_code", context), `${context}.reason_code`),
    decisionCycleId: text(field(value, "decision_cycle_id", context), `${context}.decision_cycle_id`),
    action: text(field(value, "action", context), `${context}.action`),
    security: securityPayload === null ? null : normalizeSecurity(securityPayload, `${context}.security`),
    approvalStatus: nullableText(field(value, "approval_status", context), `${context}.approval_status`),
    validationStatus: text(field(value, "validation_status", context), `${context}.validation_status`),
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
    policyEvaluation: normalizePolicyEvaluation(field(payload, "policy_evaluation", context), `${context}.policy_evaluation`),
    reviewer: normalizeReviewer(field(payload, "reviewer", context), `${context}.reviewer`),
    approval: normalizeApproval(field(payload, "approval", context), `${context}.approval`),
    execution: normalizeExecution(field(payload, "execution", context), `${context}.execution`),
    executionReadiness: normalizeExecutionReadiness(field(payload, "execution_readiness", context), `${context}.execution_readiness`),
  };
}

// This is deliberately a direct rendering of the backend contract, not an
// eligibility calculation. Quote selection and all execution rules remain API-owned.
export function isExecutionEnabled(decision) {
  return decision?.executionReadiness?.executable === true;
}

export function normalizeResearch(payload) {
  if (payload === null) return null;
  const context = "research";
  record(payload, context);
  const selectedPayload = Object.hasOwn(payload, "selected") ? list(field(payload, "selected", context), `${context}.selected`) : [];
  return {
    batchId: text(field(payload, "batch_id", context), `${context}.batch_id`),
    decisionCycleId: text(field(payload, "decision_cycle_id", context), `${context}.decision_cycle_id`),
    portfolioId: text(field(payload, "portfolio_id", context), `${context}.portfolio_id`),
    managerType: text(field(payload, "manager_type", context), `${context}.manager_type`),
    createdAt: text(field(payload, "created_at", context), `${context}.created_at`),
    asOfTimestamp: text(field(payload, "as_of_timestamp", context), `${context}.as_of_timestamp`),
    screeningRunId: Object.hasOwn(payload, "screening_run_id") ? nullableText(field(payload, "screening_run_id", context), `${context}.screening_run_id`) : null,
    selected: selectedPayload.map((item, index) => {
      const itemContext = `${context}.selected[${index}]`;
      return {
        security: normalizeSecurity(field(item, "security", itemContext), `${itemContext}.security`),
        slotRole: text(field(item, "slot_role", itemContext), `${itemContext}.slot_role`),
      };
    }),
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
    benchmarkFulfillmentStatus: text(field(payload, "benchmark_fulfillment_status", context), `${context}.benchmark_fulfillment_status`),
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
export function normalizePriceRefreshStatus(payload) {
  if (payload === null) return null;
  const context = "price refresh status";
  return { operationId: text(field(payload, "operation_id", context), `${context}.operation_id`), status: text(field(payload, "status", context), `${context}.status`), startedAt: text(field(payload, "started_at", context), `${context}.started_at`), completedAt: nullableText(field(payload, "completed_at", context), `${context}.completed_at`), providerIdentity: text(field(payload, "provider_identity", context), `${context}.provider_identity`), expectedSecurityCount: number(field(payload, "expected_security_count", context), `${context}.expected_security_count`), persistedObservationCount: field(payload, "persisted_observation_count", context), latestSourceTimestamp: nullableText(field(payload, "latest_source_timestamp", context), `${context}.latest_source_timestamp`), failureCode: nullableText(field(payload, "failure_code", context), `${context}.failure_code`), failureMessage: nullableText(field(payload, "failure_message", context), `${context}.failure_message`), reportedAt: text(field(payload, "reported_at", context), `${context}.reported_at`), freshnessSeconds: field(payload, "freshness_seconds", context) };
}
export function normalizeBuildResearch(payload) {
  const context = "research build";
  return { batchId: text(field(payload, "batch_id", context), `${context}.batch_id`), decisionCycleId: text(field(payload, "decision_cycle_id", context), `${context}.decision_cycle_id`), packetCount: number(field(payload, "packet_count", context), `${context}.packet_count`), provider: text(field(payload, "source_provider_identity", context), `${context}.source_provider_identity`), asOfTimestamp: text(field(payload, "as_of_timestamp", context), `${context}.as_of_timestamp`) };
}
export function normalizeBootstrapOverview(payload) {
  const context = "overview bootstrap";
  const identities = (value, key) => list(field(payload, key, context), `${context}.${key}`).map((item, index) => normalizeSecurity(item, `${context}.${key}[${index}]`));
  return {
    fetched: identities(payload, "fetched"),
    skipped: identities(payload, "skipped"),
    remaining: identities(payload, "remaining"),
    requestCount: number(field(payload, "request_count", context), `${context}.request_count`),
    providerIdentity: text(field(payload, "provider_identity", context), `${context}.provider_identity`),
  };
}

export async function loadApplication() {
  const [health, dashboard, decision, research, history, portfolio, performance, priceRefresh] = await Promise.all([
    apiClient.get("/health"),
    apiClient.get("/dashboard"),
    apiClient.get("/decisions/latest", { allowNotFound: true }),
    apiClient.get("/research/latest", { allowNotFound: true }),
    apiClient.get("/decisions"),
    apiClient.get("/portfolio"),
    apiClient.get("/performance"),
    apiClient.get("/price-refresh/latest", { allowNotFound: true }),
  ]);
  return {
    health: normalizeHealth(health),
    dashboard: normalizeDashboard(dashboard),
    decision: normalizeDecision(decision),
    research: normalizeResearch(research),
    history: normalizeHistory(history),
    portfolio: normalizePortfolio(portfolio, "portfolio"),
    performance: normalizePerformance(performance, "performance"),
    priceRefresh: normalizePriceRefreshStatus(priceRefresh),
  };
}

const string = (value, fallback = "—") => value == null || value === "" ? fallback : String(value);
const decimal = (value, { maximumFractionDigits = 2, minimumFractionDigits = 0 } = {}) => {
  if (value == null || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits, minimumFractionDigits }).format(parsed);
};
const money = (value, currency = "USD") => value == null ? "—" : `${currency} ${decimal(value, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
const quantity = (value) => decimal(value, { maximumFractionDigits: 8 });
const percent = (value) => value == null ? "—" : `${(Number.parseFloat(value) * 100).toFixed(2)}%`;
const dateTime = (value) => value ? new Date(value).toLocaleString() : "—";
const currentLocalDateTime = (now = new Date()) => {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};
const dateParts = (value) => {
  if (!value) return { day: "—", month: "", year: "" };
  const date = new Date(value);
  return {
    day: new Intl.DateTimeFormat("en-US", { day: "2-digit" }).format(date),
    month: new Intl.DateTimeFormat("en-US", { month: "short" }).format(date),
    year: new Intl.DateTimeFormat("en-US", { year: "numeric" }).format(date),
  };
};
const initials = (ticker) => string(ticker, "—").slice(0, 2);
const esc = (value) => string(value).replace(/[&<>'"]/g, (character) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[character]);
const app = typeof document === "undefined" ? null : document.querySelector("#app");
let refreshStatus = null;
function refreshSummary(operation) {
  if (!operation) return null;
  if (operation.status === "IN_PROGRESS") return `Refreshing prices since ${dateTime(operation.startedAt)} via ${operation.providerIdentity}.`;
  if (operation.status === "FAILED") return `Price refresh failed: ${operation.failureMessage || operation.failureCode}.`;
  const minutes = Math.floor(Number(operation.freshnessSeconds) / 60);
  const age = minutes < 1 ? "less than a minute" : `${minutes} minute${minutes === 1 ? "" : "s"}`;
  return `Prices refreshed ${age} ago · ${dateTime(operation.latestSourceTimestamp)} · ${operation.providerIdentity} · ${operation.persistedObservationCount} prices.`;
}

function chart(points) {
  if (points.length < 2) return `<div class="chart-empty"><div><strong>Performance trend unavailable</strong><br><span>At least two synchronized managed and SPY valuations are required.</span></div></div>`;
  const values = points.map((point) => [Number(point.managedReturn), Number(point.benchmarkReturn)]).flat();
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const path = (key) => points.map((point, index) => `${index ? "L" : "M"}${(index / Math.max(points.length - 1, 1)) * 100} ${100 - ((Number(point[key]) - min) / span) * 90 - 5}`).join(" ");
  return `<div class="chart-wrap"><svg class="chart" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Managed and SPY return history">${[20,40,60,80].map((y) => `<line class="grid-line" x1="0" y1="${y}" x2="100" y2="${y}"/>`).join("")}<path class="benchmark" d="${path("benchmarkReturn")}"/><path class="managed" d="${path("managedReturn")}"/></svg><div class="chart-labels"><span>${esc(dateTime(points[0].timestamp))}</span><span>${esc(dateTime(points.at(-1).timestamp))}</span></div></div>`;
}

function nav() { return `<section class="view active" id="overview"></section><section class="view" id="decision"></section><section class="view" id="research"></section><section class="view" id="portfolio"></section><section class="view" id="history"></section>`; }
function renderOverview(state) {
  const { portfolio, benchmark, performance, history } = state.dashboard;
  const holdings = portfolio.positions.slice(0, 4).map((position) => `<div class="holding-row"><i class="symbol">${esc(initials(position.security.ticker))}</i><div class="holding-main"><strong>${esc(position.security.ticker)}</strong><small>${esc(money(position.marketValue, position.security.currency))}</small></div><span class="weight">${esc(quantity(position.quantity))} shares</span></div>`).join("");
  const activity = history.entries.slice(0, 4).map((entry) => `<div class="holding-row"><i class="symbol">${esc(entry.action === "HOLD" ? "—" : initials(entry.ticker))}</i><div class="history-main"><strong>${esc(entry.action)} ${esc(entry.ticker)}</strong><small>${esc(entry.execution.status)} · ${esc(dateTime(entry.decisionTimestamp))}</small></div></div>`).join("");
  const benchmarkPosition = benchmark.snapshot.positions[0];
  const benchmarkDetail = benchmarkPosition
    ? `${esc(quantity(benchmarkPosition.quantity))} ${esc(benchmarkPosition.security.ticker)} · ${esc(money(benchmarkPosition.marketValue, benchmarkPosition.security.currency))}`
    : `Cash ${esc(money(benchmark.snapshot.cashValue, benchmark.snapshot.baseCurrency))}`;
  const controls = state.health.persisted ? `<article class="surface command-panel"><section class="command-block"><span class="kicker">Weekly funding</span><h2>Paired Cash Event</h2><p>Apply the same external contribution to managed and benchmark portfolios.</p><form id="cash-event-form" class="command-form"><div class="field"><label for="cash-amount">Amount</label><input id="cash-amount" name="amount" inputmode="decimal" value="1000" aria-label="Cash amount"></div><div class="field"><label for="cash-currency">Currency</label><input id="cash-currency" name="currency" value="USD" aria-label="Currency"></div><div class="field wide"><label for="cash-source">Source</label><input id="cash-source" name="source" value="manual deposit" aria-label="Source"></div><div class="field wide"><div class="field-label"><label for="cash-effective">Effective time</label><button type="button" class="now-button" data-now-target="cash-effective">Use current time</button></div><input id="cash-effective" name="effective_at" type="datetime-local" aria-label="Effective time" required></div><button class="refresh-button" type="submit">Apply Cash Event</button></form><div class="status-line">Managed cash ${esc(money(portfolio.cashValue, portfolio.baseCurrency))} · Benchmark cash ${esc(money(benchmark.snapshot.cashValue, benchmark.snapshot.baseCurrency))}</div></section><section class="command-block"><span class="kicker">Benchmark fulfillment</span><h2>SPY benchmark</h2><p>${benchmarkDetail}</p><div class="status-line"><i class="status-dot"></i><strong>${esc(state.dashboard.benchmarkFulfillmentStatus)}</strong></div><div class="command-form"><div class="field wide"><div class="field-label"><label for="benchmark-fulfilled-at">Fulfillment time</label><button type="button" class="now-button" data-now-target="benchmark-fulfilled-at">Use current time</button></div><input id="benchmark-fulfilled-at" type="datetime-local" aria-label="Benchmark fulfillment time" required></div><button class="quiet-button outline" id="fulfill-benchmark" type="button">Fulfill SPY Benchmark</button></div><small class="muted">Uses a persisted provider-attributed SPY quote; no regular-session-close claim.</small></section></article>` : "";
  const alpha = performance
    ? `<strong class="${Number(performance.absoluteAlpha) >= 0 ? "positive" : "negative"}">${esc(percent(performance.absoluteAlpha))}</strong>`
    : `<strong class="muted">Unavailable</strong>`;
  document.querySelector("#overview").innerHTML = `<div class="page-heading"><div><span class="kicker">Portfolio command center</span><h1>Portfolio state at a glance</h1><p>${state.health.persisted ? "Durable" : "Current"} state from the deterministic application API.</p></div><div class="cycle-id"><span class="kicker">Valuation</span><strong>${esc(dateTime(portfolio.asOfTimestamp))}</strong><small>${esc(portfolio.sourceProviderIdentity)} · ${esc(portfolio.priceConvention)}</small></div></div><section class="overview-hero surface"><div><span class="kicker">Managed portfolio value</span><strong class="value">${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong><small class="muted">Cash ${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</small></div><div><div class="surface-head"><div><span class="kicker">Performance snapshot</span><h2>Managed vs. SPY</h2></div><div class="chart-legend"><span class="managed">Managed</span><span class="spy">SPY</span></div></div>${chart(history.chartPoints)}</div><div><span class="kicker">Comparable benchmark</span><strong class="value">${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong><p class="muted">${benchmarkDetail}</p><span class="chip">${esc(state.dashboard.benchmarkFulfillmentStatus)}</span></div></section>${controls}<div class="metric-grid"><article class="metric-card"><span>Managed value</span><strong>${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>SPY benchmark</span><strong>${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong><small>${benchmarkDetail}</small></article><article class="metric-card"><span>Absolute alpha</span>${alpha}</article><article class="metric-card"><span>Available cash</span><strong>${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</strong></article></div><div class="two-col"><article class="surface"><div class="surface-head"><div><span class="kicker">Portfolio</span><h2>Holdings preview</h2></div><button class="text-button" data-view-jump="portfolio">All holdings →</button></div>${holdings || `<div class="empty-state"><strong>No managed positions</strong><p>The managed portfolio currently holds cash only.</p></div>`}</article><article class="surface"><div class="surface-head"><div><span class="kicker">AI decision journal</span><h2>Recent activity</h2></div><button class="text-button" data-view-jump="history">Full history →</button></div>${activity || "<p class=muted>No decision history is available.</p>"}</article></div>`;
  const form = document.querySelector("#cash-event-form");
  if (form) form.addEventListener("submit", async (event) => { event.preventDefault(); const data = new FormData(form); try { await apiClient.post("/commands/cash-events", { amount: data.get("amount"), currency: data.get("currency"), source: data.get("source"), effective_at: new Date(data.get("effective_at")).toISOString() }); await start(); } catch (error) { refreshStatus = `Cash Event failed: ${error.message}`; document.querySelector("#health-status").textContent = refreshStatus; } });
  const fulfill = document.querySelector("#fulfill-benchmark");
  if (fulfill) fulfill.addEventListener("click", async () => { const value = document.querySelector("#benchmark-fulfilled-at").value; if (!value) { refreshStatus = "Benchmark fulfillment requires a caller-supplied timestamp."; document.querySelector("#health-status").textContent = refreshStatus; return; } try { await apiClient.post(`/commands/fulfill-benchmark?fulfilled_at=${encodeURIComponent(new Date(value).toISOString())}`); await start(); } catch (error) { refreshStatus = `Benchmark fulfillment pending: ${error.message}`; document.querySelector("#health-status").textContent = refreshStatus; } });
}
function policyPresentation(policyEvaluation, validation) {
  const isLegacy = policyEvaluation.systemSafetyEnvelopeVersion === null;
  const systemSafetyStatus = isLegacy ? "NOT RECORDED" : validation.status;
  const safetyIdentity = policyEvaluation.systemSafetyEnvelopeVersion === null
    ? `<p class="muted">Policy: ${esc(policyEvaluation.policyKind)}. System Safety and Investment Constitution evaluations were not recorded for this legacy decision.</p>`
    : `<p class="muted">Policy: ${esc(policyEvaluation.policyKind)} · Investment Constitution: ${esc(policyEvaluation.investmentConstitutionVersion ?? "Unavailable")} · ${esc(policyEvaluation.investmentConstitutionHash ?? "Unavailable")}</p><p class="muted">System Safety Envelope: ${esc(policyEvaluation.systemSafetyEnvelopeVersion)} · ${esc(policyEvaluation.systemSafetyEnvelopeHash ?? "Unavailable")}</p>`;
  const safetyRules = validation.rules.map((rule) => `<li><strong>${esc(rule.ruleId)} · ${esc(rule.status)}</strong><br>${esc(rule.reason)}<small class="muted">Policy: ${esc(rule.policyVersion ?? "Unavailable")} · Inputs: ${esc(rule.inputReferences.join(", ") || "Not recorded")}</small></li>`).join("") || "<li>No System Safety rule results were recorded.</li>";
  const managerRiskIdentity = policyEvaluation.managerRiskConstitutionVersion === null
    ? `<p class="muted">Legacy policy record: Manager Risk advisory assessment was not recorded.</p>`
    : `<p class="muted">Constitution: ${esc(policyEvaluation.managerRiskConstitutionVersion)} · ${esc(policyEvaluation.managerRiskConstitutionHash ?? "Unavailable")}</p>`;
  const advisoryFindings = policyEvaluation.advisoryFindings.length === 0
    ? `<p class="muted">${policyEvaluation.managerRiskConstitutionVersion === null ? "No Manager Risk assessment is recorded for this legacy policy." : "No Manager Risk advisory findings were recorded."}</p>`
    : `<ul class="decision-notes advisory-findings">${policyEvaluation.advisoryFindings.map((finding) => `<li><span class="advisory-severity">${esc(finding.severity)} advisory</span><strong>${esc(finding.findingId)}</strong><p>${esc(finding.reason)}</p><small class="muted">Actual: ${esc(finding.actualValue ?? "Unavailable")} · Guidance: ${esc(finding.guidanceValue ?? "Unavailable")} · Inputs: ${esc(finding.inputReferences.join(", ") || "Not recorded")}</small></li>`).join("")}</ul>`;
  const systemSafetyContent = isLegacy
    ? safetyIdentity
    : `${safetyIdentity}<p class="muted">Hard deterministic result: ${esc(validation.status)}.</p><p class="mechanical-state"><span>Mechanically executable</span><strong>${esc(policyEvaluation.mechanicallyExecutable ? "Recorded yes" : "Recorded no")}</strong><small>Backend-reported validation provenance; not paper-execution readiness.</small></p><ul class="decision-notes">${safetyRules}</ul>`;
  const legacyMechanicalResult = isLegacy
    ? `<article class="surface policy-panel legacy-mechanical"><div class="surface-head"><div><span class="kicker">Legacy mechanical validation</span><h2>Recorded result</h2></div><span class="policy-status">${esc(validation.status)}</span></div><p class="muted">This result predates System Safety and is displayed as legacy mechanical validation only.</p><p class="mechanical-state"><span>Mechanically executable</span><strong>${esc(policyEvaluation.mechanicallyExecutable ? "Recorded yes" : "Recorded no")}</strong><small>Backend-reported validation provenance; not paper-execution readiness.</small></p><ul class="decision-notes">${safetyRules}</ul></article>`
    : "";
  return `<section class="policy-center" aria-label="Policy evaluation"><div class="policy-center-head"><div><span class="kicker">Policy evaluation</span><h2>Decision safeguards</h2></div><p class="muted">Execution readiness remains a separate backend-reported state.</p></div><div class="two-col policy-panels"><article class="surface policy-panel system-safety"><div class="surface-head"><div><span class="kicker">System Safety</span><h2>${isLegacy ? "Not recorded" : "Hard deterministic layer"}</h2></div><span class="policy-status">${esc(systemSafetyStatus)}</span></div>${systemSafetyContent}</article><article class="surface policy-panel manager-risk"><div class="surface-head"><div><span class="kicker">Manager Risk</span><h2>Advisory layer</h2></div><span class="advisory-label">Advisory only</span></div>${managerRiskIdentity}${advisoryFindings}</article></div>${legacyMechanicalResult}</section>`;
}
function renderDecision(state) {
  const target = document.querySelector("#decision"); const decision = state.decision;
  if (!decision) {
    const control = state.health.persisted
      ? `<article class="surface command-card"><span class="kicker">Value Manager</span><h2>Run Value Manager</h2><p class="muted">Create the next recommendation from the latest authoritative research batch.</p><div class="command-form"><div class="field wide"><div class="field-label"><label for="value-manager-occurred-at">Decision timestamp</label><button type="button" class="now-button" data-now-target="value-manager-occurred-at">Use current time</button></div><input id="value-manager-occurred-at" type="datetime-local" aria-label="Decision timestamp" required></div><button class="refresh-button" id="run-value-manager" type="button">Run Value Manager</button></div></article>`
      : "";
    target.innerHTML = `${empty("No latest decision", "The API reports no latest decision. No recommendation is being inferred.")}${control}`;
    document.querySelector("#run-value-manager")?.addEventListener("click", () => runValueManager());
    return;
  }
  const r = decision.recommendation, execution = decision.execution, reviewer = decision.reviewer, approval = decision.approval;
  const policyPanels = policyPresentation(decision.policyEvaluation, decision.validation);
  const lifecycle = [["Manager decided", `${r.action} · ${r.confidenceScore}/100`, decision.producedAt], ["Code validated", decision.validation.status, decision.validation.validationTimestamp], ["Reviewer", reviewer ? reviewer.decision : "Not reviewed", reviewer?.reviewedAt], ["Human approval", approval ? approval.decision : "Not approved", approval?.decidedAt], ["Execution", execution ? `${execution.action} ${execution.security.ticker}` : r.action === "HOLD" ? "No execution — HOLD" : "No execution", execution?.executedAt]].map(([name, status, time]) => `<div><span class="kicker">${esc(name)}</span><strong>${esc(status)}</strong><small>${esc(dateTime(time))}</small></div>`).join("");
  const runControl = state.health.persisted && state.research?.decisionCycleId !== decision.decisionCycleId
    ? `<article class="surface command-card"><span class="kicker">New authoritative research</span><h2>Run Value Manager</h2><p class="muted">A newer research batch is available for a journaled recommendation.</p><div class="command-form"><div class="field wide"><div class="field-label"><label for="value-manager-occurred-at">Decision timestamp</label><button type="button" class="now-button" data-now-target="value-manager-occurred-at">Use current time</button></div><input id="value-manager-occurred-at" type="datetime-local" aria-label="Decision timestamp" required></div><button class="refresh-button" id="run-value-manager" type="button">Run Value Manager</button></div></article>`
    : "";
  const outcomeControls = state.health.persisted && !approval
    ? `<article class="surface command-card"><span class="kicker">Human decision</span><h2>Approval gate</h2><p class="muted">Validation: ${esc(decision.validation.status)} · readiness: ${esc(decision.executionReadiness.reasonCode)}</p><div class="command-form"><div class="field"><label for="decision-maker-id">Operator ID</label><input id="decision-maker-id" value="local-operator" aria-label="Decision maker ID" required></div><div class="field wide"><div class="field-label"><label for="decision-decided-at">Decision timestamp</label><button type="button" class="now-button" data-now-target="decision-decided-at">Use current time</button></div><input id="decision-decided-at" type="datetime-local" aria-label="Decision timestamp" required></div><div class="field wide"><label for="decision-comment">Audit comment</label><input id="decision-comment" aria-label="Decision comment (optional)" placeholder="Optional comment"></div><button class="refresh-button" id="approve-decision" type="button">Approve</button><button class="quiet-button outline" id="reject-decision" type="button">Reject</button></div></article>`
    : "";
  const readiness = decision.executionReadiness;
  const executionControl = state.health.persisted && isExecutionEnabled(decision)
    ? `<article class="surface command-card"><span class="kicker">Execution readiness</span><h2>Ready for paper execution</h2><p class="muted">The backend will select the eligible persisted quote and calculate the simulated fill.</p><div class="command-form"><div class="field wide"><div class="field-label"><label for="execution-executed-at">Execution timestamp</label><button type="button" class="now-button" data-now-target="execution-executed-at">Use current time</button></div><input id="execution-executed-at" type="datetime-local" aria-label="Execution timestamp" required></div><button class="refresh-button" id="execute-paper-trade" type="button">Execute Paper Trade</button></div></article>`
    : `<article class="surface command-card"><div class="surface-head"><div><span class="kicker">Execution readiness</span><h2>${esc(readiness.reasonCode)}</h2></div><span class="chip ${readiness.reasonCode === "HOLD" ? "hold" : ""}">${esc(readiness.executable ? "READY" : "NOT EXECUTABLE")}</span></div><p class="muted">Approval: ${esc(readiness.approvalStatus ?? "Not recorded")} · Validation: ${esc(readiness.validationStatus)}</p></article>`;
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Decision center</span><h1>Verified decision lifecycle</h1><p>Recommendation, deterministic validation, review, and approval are separate artifacts.</p></div><div class="cycle-id"><span class="kicker">Decision cycle</span><strong>${esc(decision.decisionCycleId)}</strong><small>${esc(decision.constitutionVersion)}</small></div></div><article class="decision-hero"><div class="decision-main"><div class="recommendation-top"><i class="symbol">${esc(initials(r.ticker))}</i><div><span class="kicker">Latest AI recommendation</span><h2>${esc(r.action)} ${esc(r.ticker)}</h2><p>${esc(r.valuation)}</p></div><span class="chip ${r.action === "BUY" ? "buy" : "hold"}">${esc(r.action)}</span></div><p class="thesis">${esc(r.decisionRationale)}</p><div class="facts"><div><span>Target weight</span><strong>${esc(percent(r.targetWeight))}</strong></div><div><span>Confidence</span><strong>${esc(r.confidenceScore)}/100</strong></div><div><span>Execution</span><strong>${esc(execution ? `${quantity(execution.executedQuantity)} shares` : "None")}</strong></div></div><section class="section-card"><span class="kicker">Why not SPY</span><p>${esc(r.whyNotSpy)}</p></section></div><aside class="confidence"><span class="kicker">Evidence confidence</span><div><strong class="value">${esc(r.confidenceScore)}<small>/100</small></strong></div><div class="score-track"><i style="width:${Math.max(0, Math.min(100, r.confidenceScore))}%"></i></div><p>${esc(r.evidence.length)} cited evidence item(s)</p><p class="muted">${esc(reviewer ? `${reviewer.findings.length} reviewer finding(s)` : "Reviewer absent")}</p></aside></article><section class="lifecycle"><div class="surface-head"><div><span class="kicker">Verified lifecycle</span><h2>How this became portfolio state</h2></div><span class="chip">${esc(approval?.decision ?? "IN PROGRESS")}</span></div><div class="lifecycle-grid">${lifecycle}</div></section>${policyPanels}<div class="two-col"><article class="surface"><span class="kicker">Thesis and risks</span><h2>Decision memo</h2><p class="thesis">${esc(r.investmentThesis ?? "No investment thesis — HOLD")}</p><h3>Risks</h3><ul class="decision-notes">${r.risks.map((risk) => `<li>${esc(risk)}</li>`).join("")}</ul></article><article class="surface"><span class="kicker">Execution lineage</span><h2>${execution ? "Simulated execution" : "No execution"}</h2>${execution ? `<p>${esc(execution.action)} ${esc(quantity(execution.executedQuantity))} ${esc(execution.security.ticker)} @ ${esc(money(execution.executionPrice, execution.currency))}</p><small class="muted">Executed trade ${esc(execution.executedTradeId)} · validated trade ${esc(execution.validatedTradeId)}</small>` : `<p class="muted">${r.action === "HOLD" ? "HOLD correctly produced no execution." : "No execution artifact is available."}</p>`}</article></div>${runControl}${outcomeControls}${executionControl}`;
  document.querySelector("#run-value-manager")?.addEventListener("click", () => runValueManager());
  const outcome = (decisionName) => recordDecisionOutcome({ decision, decisionName });
  document.querySelector("#approve-decision")?.addEventListener("click", () => outcome("approve"));
  document.querySelector("#reject-decision")?.addEventListener("click", () => outcome("reject"));
  document.querySelector("#execute-paper-trade")?.addEventListener("click", () => executePaperTrade({ decision }));
}
function researchSectionMarkup(section) {
  if (section.content == null) {
    return `<p class="muted">Missing data: ${esc(section.missingData?.reason ?? "unspecified")}</p>`;
  }
  const matches = [...section.content.matchAll(/(?:^|;\s*)([a-z][a-z0-9_]*)\s*:\s*/gi)];
  if (matches.length > 1) {
    const fields = matches.map((match, index) => ({
      label: match[1],
      value: section.content.slice(match.index + match[0].length, matches[index + 1]?.index ?? section.content.length).replace(/;\s*$/, "").trim(),
    }));
    return `<dl class="research-fields">${fields.map((item) => `<div><dt>${esc(item.label.replaceAll("_", " "))}</dt><dd>${esc(item.value)}</dd></div>`).join("")}</dl>`;
  }
  return `<p>${esc(section.content)}</p>`;
}

function slotRoleForPacket(research, packet) {
  const selected = research.selected ?? [];
  const match = selected.find((item) => (
    item.security.ticker === packet.ticker
    && item.security.securityType === packet.securityType
    && item.security.exchange === packet.exchange
    && item.security.currency === packet.currency
  ));
  return match?.slotRole ?? null;
}

function renderResearch(state) {
  const target = document.querySelector("#research"), research = state.research;
  if (!research) { target.innerHTML = empty("No latest research", "The API reports no authoritative ResearchBatch for the latest decision."); return; }
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Research workspace</span><h1>Source-backed research packets</h1><p>Research is immutable input; it is not a recommendation.</p></div><div class="cycle-id"><span class="kicker">Research batch</span><strong>${esc(research.batchId)}</strong><small>${esc(research.packets.length)} packets</small></div></div><div class="packet-list"><aside class="packet-nav">${research.packets.map((item, index) => {
    const slotRole = slotRoleForPacket(research, item);
    return `<button class="packet-button ${index === 0 ? "active" : ""}" data-packet-index="${index}"><strong>${esc(item.ticker)}</strong><small>${esc(item.companyName)}${slotRole ? ` · ${esc(slotRole)}` : ""}</small></button>`;
  }).join("")}</aside><article class="surface document" id="research-document"></article></div>`;
  const paint = (selected) => {
    const packet = research.packets[selected];
    const slotRole = slotRoleForPacket(research, packet);
    document.querySelector("#research-document").innerHTML = `<span class="kicker">${esc(packet.packetId)}</span><h2>${esc(packet.companyName)}</h2><p class="muted">${esc(packet.exchange)} · ${esc(packet.industry)} · ${esc(packet.currency)}${slotRole ? ` · researched as ${esc(slotRole)}` : ""}</p><div class="research-sections">${packet.sections.map((section) => `<section class="section-card"><span class="kicker">Source-backed section</span><h3>${esc(section.sectionId.replaceAll("_", " "))}</h3>${researchSectionMarkup(section)}<small>Evidence: ${esc(section.evidenceIds.join(", ") || "none")}</small></section>`).join("")}<section class="evidence-wrap"><div class="surface-head"><div><span class="kicker">Provenance</span><h3>Evidence</h3></div><span class="chip">${esc(packet.evidence.length)} ITEMS</span></div><table class="evidence-table"><thead><tr><th>ID</th><th>Source</th><th>Date</th><th>Claim supported</th></tr></thead><tbody>${packet.evidence.map((evidence) => `<tr><td>${esc(evidence.evidenceId)}</td><td>${esc(evidence.sourceType)} · ${esc(evidence.sourceTitle)}</td><td>${esc(evidence.sourceDate)}</td><td>${esc(evidence.claimSupported)}</td></tr>`).join("")}</tbody></table></section></div>`;
  };
  paint(0); target.querySelectorAll("[data-packet-index]").forEach((button) => button.addEventListener("click", () => { target.querySelectorAll("[data-packet-index]").forEach((node) => node.classList.remove("active")); button.classList.add("active"); paint(Number(button.dataset.packetIndex)); }));
}
function holdingGroup({ portfolio, ownerLabel, ownerType, ownerClass }) {
  const positionRows = portfolio.positions.map((position) => `<tr><td><div class="owned-security"><i class="symbol">${esc(initials(position.security.ticker))}</i><span><strong>${esc(position.security.ticker)}</strong><small>Owned by ${esc(ownerLabel)}</small></span></div></td><td>${esc(quantity(position.quantity))}</td><td>${esc(money(position.totalCostBasis, position.security.currency))}</td><td>${esc(money(position.observedPrice, position.security.currency))}</td><td>${esc(money(position.marketValue, position.security.currency))}</td><td class="${Number(position.unrealizedGainLoss) >= 0 ? "positive" : "negative"}">${esc(money(position.unrealizedGainLoss, position.security.currency))}</td></tr>`).join("");
  const cashRow = `<tr class="cash-holding"><td><div class="owned-security"><i class="symbol">$</i><span><strong>Cash</strong><small>Owned by ${esc(ownerLabel)}</small></span></div></td><td>—</td><td>—</td><td>—</td><td>${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</td><td>—</td></tr>`;
  return `<article class="surface holding-group ${esc(ownerClass)}"><div class="holding-group-head"><div class="owner-identity"><i>${esc(ownerType === "Benchmark portfolio" ? "SPY" : "AI")}</i><div><span class="kicker">${esc(ownerType)}</span><h2>${esc(ownerLabel)}</h2><small>${esc(portfolio.portfolioId)}</small></div></div><div class="owner-total"><span class="ownership-chip">${esc(ownerType === "Benchmark portfolio" ? "BENCHMARK" : "MANAGED")}</span><strong>${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong><small>${esc(portfolio.status)}</small></div></div><div class="table-wrap"><table class="holdings"><thead><tr><th>Holding</th><th>Quantity</th><th>Cost basis</th><th>Close</th><th>Market value</th><th>Unrealized</th></tr></thead><tbody>${positionRows}${cashRow}</tbody></table></div></article>`;
}

function renderPortfolio(state) {
  const target = document.querySelector("#portfolio"), { portfolio, benchmark, performance, history } = state.dashboard;
  const portfolioGroups = [
    { portfolio, ownerLabel: portfolio.portfolioName, ownerType: "AI manager portfolio", ownerClass: "manager-owned" },
    { portfolio: benchmark.snapshot, ownerLabel: "SPY Benchmark", ownerType: "Benchmark portfolio", ownerClass: "benchmark-owned" },
  ];
  const comparison = performance
    ? `<p class="muted">Managed ${esc(percent(performance.managedCumulativeReturn))} · SPY ${esc(percent(performance.benchmarkCumulativeReturn))} · Alpha ${esc(percent(performance.absoluteAlpha))}</p>`
    : `<p class="muted">Performance comparison is unavailable until synchronized managed and benchmark valuations exist.</p>`;
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Experiment ownership</span><h1>My Holdings</h1><p>Every manager and benchmark portfolio, grouped by owner.</p></div><div class="cycle-id"><span class="kicker">Price convention</span><strong>${esc(portfolio.priceConvention)}</strong><small>${esc(portfolio.sourceProviderIdentity)}</small></div></div><div class="metric-grid"><article class="metric-card"><span>Value Manager</span><strong>${esc(money(portfolio.totalValue, portfolio.baseCurrency))}</strong><small>${esc(portfolio.positions.length)} securities · ${esc(money(portfolio.cashValue, portfolio.baseCurrency))} cash</small></article><article class="metric-card"><span>SPY Benchmark</span><strong>${esc(money(benchmark.snapshot.totalValue, benchmark.snapshot.baseCurrency))}</strong><small>${esc(benchmark.snapshot.positions.length)} securities · ${esc(state.dashboard.benchmarkFulfillmentStatus)}</small></article><article class="metric-card"><span>Managed invested value</span><strong>${esc(money(portfolio.investedValue, portfolio.baseCurrency))}</strong></article><article class="metric-card"><span>Managed available cash</span><strong>${esc(money(portfolio.cashValue, portfolio.baseCurrency))}</strong></article></div><section class="ownership-directory"><div class="surface-head"><div><span class="kicker">Ownership directory</span><h2>Portfolios</h2></div><span class="directory-count">${esc(portfolioGroups.length)} portfolios</span></div><div class="holdings-groups">${portfolioGroups.map(holdingGroup).join("")}</div></section><article class="surface performance-surface"><div class="surface-head"><div><span class="kicker">Comparable valuations</span><h2>Performance history</h2></div><div class="chart-legend"><span class="managed">Managed</span><span class="spy">SPY</span></div></div>${chart(history.chartPoints)}${comparison}</article>`;
}
function renderHistory(state) {
  const target = document.querySelector("#history"), history = state.history;
  target.innerHTML = `<div class="page-heading"><div><span class="kicker">Immutable lineage</span><h1>Decision & portfolio history</h1><p>Every state change remains linked to its decision cycle and execution artifacts.</p></div><div class="cycle-id"><span class="kicker">Visible history</span><strong>${esc(history.entries.length)} entries</strong><small>Newest first</small></div></div><div class="history-list">${history.entries.map((entry) => {
    const date = dateParts(entry.decisionTimestamp);
    return `<article class="history-row"><time class="history-date"><strong>${esc(date.day)}</strong><span>${esc(date.month)}<br>${esc(date.year)}</span></time><i class="symbol">${esc(entry.action === "HOLD" ? "—" : initials(entry.ticker))}</i><div class="history-main"><span class="kicker">${esc(entry.execution.status)}</span><strong>${esc(entry.action)} ${esc(entry.ticker)}</strong><small>Reviewer: ${esc(entry.reviewerOutcome)} · Human approval: ${esc(entry.approvalOutcome)} · Target: ${esc(entry.targetWeight)}</small>${entry.execution.executedTradeId ? `<small>Execution ${esc(entry.execution.executedTradeId)} → validated ${esc(entry.execution.validatedTradeId)} · ${esc(quantity(entry.execution.quantity))} ${esc(entry.execution.security.ticker)} @ ${esc(money(entry.execution.executionPrice, entry.execution.security.currency))}</small>` : ""}</div><code title="${esc(entry.decisionCycleId)}">${esc(entry.decisionCycleId)}</code></article>`;
  }).join("") || "<section class=empty-state>No decision history is available.</section>"}</div>`;
}
function empty(title, message) { return `<section class="empty-state"><span class="kicker">No data</span><h1>${esc(title)}</h1><p>${esc(message)}</p></section>`; }
function render(state) {
  app.innerHTML = nav(); document.querySelector("#portfolio-name").textContent = state.dashboard.portfolio.portfolioName;
  document.querySelector("#health-status").textContent = refreshStatus || refreshSummary(state.priceRefresh) || `${state.health.stateMode} · ${state.health.persisted ? "persisted" : "in-memory"}${state.health.synthetic ? " · demo" : ""}`;
  renderOverview(state); renderDecision(state); renderResearch(state); renderPortfolio(state); renderHistory(state); bindCurrentTimeButtons();
  document.querySelectorAll("[data-view],[data-view-jump]").forEach((button) => button.addEventListener("click", () => { const view = button.dataset.view || button.dataset.viewJump; document.querySelectorAll(".view").forEach((section) => section.classList.toggle("active", section.id === view)); document.querySelectorAll("[data-view]").forEach((node) => node.classList.toggle("active", node.dataset.view === view)); }));
}

function bindCurrentTimeButtons() {
  document.querySelectorAll("[data-now-target]").forEach((button) => button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.nowTarget);
    if (input) {
      input.value = currentLocalDateTime();
      input.focus();
    }
  }));
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
    if (error.status === 0) {
      refreshStatus = "Refresh connection lost; checking durable refresh status on reconnect.";
      try { refreshStatus = null; await reload(); } catch { refreshStatus = "Refresh connection lost; checking durable refresh status on reconnect."; /* The API is still unavailable; this is not provider evidence. */ }
    } else refreshStatus = `Price refresh failed: ${error.message}`;
    if (refreshStatus !== null) status.textContent = refreshStatus;
  } finally {
    button.disabled = false; button.textContent = "Refresh prices";
  }
}
export async function buildResearch({ button = document.querySelector("#build-research"), status = document.querySelector("#health-status"), reload = start } = {}) {
  button.disabled = true; button.textContent = "Building research…"; status.textContent = "Building source-attributed Alpha Vantage research…";
  try {
    const result = normalizeBuildResearch(await apiClient.post("/commands/build-research"));
    refreshStatus = `Research built: ${result.packetCount} packets from ${result.provider} · ${dateTime(result.asOfTimestamp)}`;
    status.textContent = refreshStatus; await reload();
  } catch (error) { refreshStatus = `Research build failed: ${error.message}`; status.textContent = refreshStatus; }
  finally { button.disabled = false; button.textContent = "Build research"; }
}
export async function bootstrapOverview({ button = document.querySelector("#bootstrap-overview"), status = document.querySelector("#health-status"), reload = start } = {}) {
  button.disabled = true; button.textContent = "Bootstrapping OVERVIEW…"; status.textContent = "Filling cached Alpha Vantage OVERVIEW rows…";
  try {
    const result = normalizeBootstrapOverview(await apiClient.post("/commands/bootstrap-overview"));
    refreshStatus = `OVERVIEW bootstrap: fetched ${result.fetched.length} · remaining ${result.remaining.length} · ${result.requestCount} requests`;
    status.textContent = refreshStatus; await reload();
  } catch (error) { refreshStatus = `OVERVIEW bootstrap failed: ${error.message}`; status.textContent = refreshStatus; }
  finally { button.disabled = false; button.textContent = "Bootstrap OVERVIEW"; }
}

export async function runValueManager({ button = document.querySelector("#run-value-manager"), status = document.querySelector("#health-status"), reload = start, occurredAt = document.querySelector("#value-manager-occurred-at")?.value } = {}) {
  if (!occurredAt) { status.textContent = "Run Value Manager requires a caller-supplied timestamp."; return; }
  button.disabled = true; button.textContent = "Running Value Manager…"; status.textContent = "Requesting a structured Value Manager recommendation…";
  try {
    await apiClient.post("/commands/run-value-manager", { occurred_at: new Date(occurredAt).toISOString() });
    refreshStatus = "Value Manager decision journaled."; await reload();
  } catch (error) { refreshStatus = `Value Manager failed: ${error.message}`; status.textContent = refreshStatus; }
  finally { button.disabled = false; button.textContent = "Run Value Manager"; }
}

export async function recordDecisionOutcome({ decision, decisionName, button = document.querySelector(`#${decisionName}-decision`), status = document.querySelector("#health-status"), reload = start, decisionMakerId, decidedAt, comment, confirmDecision } = {}) {
  const maker = decisionMakerId ?? document.querySelector("#decision-maker-id")?.value;
  const effectiveDecidedAt = decidedAt ?? document.querySelector("#decision-decided-at")?.value;
  const effectiveComment = comment === undefined ? document.querySelector("#decision-comment")?.value || null : comment;
  const confirmation = confirmDecision ?? window.confirm;
  if (!maker || !effectiveDecidedAt) { status.textContent = "Human decision requires an operator ID and caller-supplied timestamp."; return; }
  if (typeof confirmation === "function" && !confirmation(`Confirm ${decisionName} for this immutable decision cycle?`)) return;
  button.disabled = true; button.textContent = `${decisionName === "approve" ? "Approving" : "Rejecting"}…`;
  try {
    await apiClient.post(`/commands/decisions/${encodeURIComponent(decision.decisionCycleId)}/${decisionName}`, { decision_maker_id: maker, decided_at: new Date(effectiveDecidedAt).toISOString(), comment: effectiveComment });
    refreshStatus = `Decision ${decisionName}d and persisted.`; await reload();
  } catch (error) { refreshStatus = `Decision ${decisionName} failed: ${error.message}`; status.textContent = refreshStatus; }
  finally { button.disabled = false; button.textContent = decisionName === "approve" ? "Approve" : "Reject"; }
}

export async function executePaperTrade({ decision, button = document.querySelector("#execute-paper-trade"), status = document.querySelector("#health-status"), reload = start, executedAt, confirmExecution } = {}) {
  const effectiveExecutedAt = executedAt ?? document.querySelector("#execution-executed-at")?.value;
  const confirmation = confirmExecution ?? window.confirm;
  if (!effectiveExecutedAt) { status.textContent = "Paper execution requires a caller-supplied timestamp."; return; }
  if (typeof confirmation === "function" && !confirmation("Confirm this approved BUY for simulated paper execution?")) return;
  button.disabled = true; button.textContent = "Executing Paper Trade…";
  status.textContent = "Submitting approved paper execution to the deterministic backend…";
  try {
    await apiClient.post(`/commands/decisions/${encodeURIComponent(decision.decisionCycleId)}/execute-paper-trade?executed_at=${encodeURIComponent(new Date(effectiveExecutedAt).toISOString())}`);
    refreshStatus = "Paper trade executed and persisted.";
    await reload();
  } catch (error) {
    refreshStatus = `Paper execution failed: ${error.message}`;
    status.textContent = refreshStatus;
  } finally {
    button.disabled = false;
    button.textContent = "Execute Paper Trade";
  }
}

export function bindShellCommands(documentObject = document) {
  documentObject.querySelector("#refresh-prices").addEventListener("click", () => refreshPrices());
  documentObject.querySelector("#build-research").addEventListener("click", () => buildResearch());
  documentObject.querySelector("#bootstrap-overview").addEventListener("click", () => bootstrapOverview());
}

if (app) { bindShellCommands(); start(); }
