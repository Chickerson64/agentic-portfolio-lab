"""Alpha Vantage adapter; its JSON schema is contained in this module."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from typing import Callable, Mapping, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.research_provider import (
    NormalizedBalanceFacts,
    NormalizedCashFlowFacts,
    NormalizedEarningsFacts,
    NormalizedIncomeFacts,
    NormalizedOverviewFacts,
    ResearchProviderConfigurationError,
    ResearchProviderError,
    SourceResearchDocument,
    SourceResearchRecord,
)

_URL = "https://www.alphavantage.co/query"
JsonTransport = Callable[[str], Mapping[str, object]]
Sleep = Callable[[float], None]


def _transport(url: str) -> Mapping[str, object]:
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310 -- fixed HTTPS URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchProviderError(f"Alpha Vantage request failed: {error}") from error
    if not isinstance(payload, dict):
        raise ResearchProviderError("Alpha Vantage response must be a JSON object")
    return cast(Mapping[str, object], payload)


class AlphaVantageResearchProvider:
    """Alpha Vantage adapter.

    ``get_company_research`` is the v0.1 three-endpoint path (OVERVIEW,
    INCOME_STATEMENT, EARNINGS). Research v2 uses the per-endpoint ``fetch_*``
    methods so the existing operator command does not jump to five calls.
    """

    def __init__(self, *, api_key: str | None = None, transport: JsonTransport = _transport, sleep: Sleep = time.sleep, pace_seconds: float = 12) -> None:
        self._api_key, self._transport, self._sleep, self._pace = api_key, transport, sleep, pace_seconds
        self._has_requested = False

    def _require_key(self) -> str:
        key = self._api_key or os.environ.get("ALPHA_VANTAGE_API_KEY")
        if not key or not key.strip():
            raise ResearchProviderConfigurationError("ALPHA_VANTAGE_API_KEY is required to build research")
        return key

    def get_company_research(self, security: SecurityIdentity) -> SourceResearchDocument:
        key = self._require_key()
        overview = self._query("OVERVIEW", security.ticker, key)
        income = self._query("INCOME_STATEMENT", security.ticker, key)
        earnings = self._query("EARNINGS", security.ticker, key)
        self._verify_identity(overview, security)
        return SourceResearchDocument(
            security=security, provider_identity="alpha-vantage", overview=self._overview_record(overview, security),
            income_statement=self._income_record(income, security), earnings=self._earnings_record(earnings, security),
        )

    def fetch_overview(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedOverviewFacts:
        del as_of
        payload = self._query("OVERVIEW", security.ticker, self._require_key())
        self._verify_identity(payload, security)
        return self._overview_record(payload, security)

    def fetch_income_statement(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedIncomeFacts:
        payload = self._query("INCOME_STATEMENT", security.ticker, self._require_key())
        self._verify_symbol(payload, security, "INCOME_STATEMENT")
        reports = self._selected_quarterly_reports(payload, "quarterlyReports", "INCOME_STATEMENT", as_of=as_of, limit=4)
        periods = tuple(self._income_from_report(report) for report in reports)
        latest = periods[0]
        return NormalizedIncomeFacts(
            latest.source,
            latest.fiscal_date_ending,
            latest.reported_currency,
            latest.total_revenue,
            latest.gross_profit,
            latest.operating_income,
            latest.net_income,
            periods,
        )

    def fetch_balance_sheet(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedBalanceFacts:
        payload = self._query("BALANCE_SHEET", security.ticker, self._require_key())
        self._verify_symbol(payload, security, "BALANCE_SHEET")
        reports = self._selected_quarterly_reports(payload, "quarterlyReports", "BALANCE_SHEET", as_of=as_of, limit=4)
        periods = tuple(self._balance_from_report(report) for report in reports)
        latest = periods[0]
        return NormalizedBalanceFacts(
            latest.source,
            latest.fiscal_date_ending,
            latest.reported_currency,
            latest.cash,
            latest.debt,
            latest.current_assets,
            latest.current_liabilities,
            latest.shares_outstanding,
            periods,
        )

    def fetch_cash_flow(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedCashFlowFacts:
        payload = self._query("CASH_FLOW", security.ticker, self._require_key())
        self._verify_symbol(payload, security, "CASH_FLOW")
        reports = self._selected_quarterly_reports(payload, "quarterlyReports", "CASH_FLOW", as_of=as_of, limit=4)
        periods = tuple(self._cash_flow_from_report(report) for report in reports)
        latest = periods[0]
        return NormalizedCashFlowFacts(
            latest.source,
            latest.fiscal_date_ending,
            latest.reported_currency,
            latest.operating_cash_flow,
            latest.capex,
            latest.buybacks,
            latest.issuance,
            periods,
        )

    def fetch_earnings(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedEarningsFacts:
        payload = self._query("EARNINGS", security.ticker, self._require_key())
        self._verify_symbol(payload, security, "EARNINGS")
        if as_of is None:
            return self._earnings_record(payload, security)
        report = self._selected_quarterly_reports(payload, "quarterlyEarnings", "EARNINGS", as_of=as_of, limit=1)[0]
        return self._earnings_from_report(report)

    def _query(self, function: str, ticker: str, key: str) -> Mapping[str, object]:
        if self._has_requested: self._sleep(self._pace)
        self._has_requested = True
        payload = self._transport(f"{_URL}?{urlencode({'function': function, 'symbol': ticker, 'apikey': key})}")
        if any(field in payload for field in ("Error Message", "Information", "Note")):
            raise ResearchProviderError(f"Alpha Vantage {function} error: {payload.get('Error Message') or payload.get('Information') or payload.get('Note')}")
        return payload

    @staticmethod
    def _optional(payload: Mapping[str, object], field: str) -> str | None:
        return AlphaVantageResearchProvider._value(payload.get(field))

    @staticmethod
    def _value(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() and value.strip().lower() not in {"none", "n/a"} else None

    def _date(self, payload: Mapping[str, object], field: str, label: str) -> date:
        value = self._optional(payload, field)
        if value is None:
            raise ResearchProviderError(f"Alpha Vantage {label} lacks {field} source date")
        try: return date.fromisoformat(value)
        except ValueError as error: raise ResearchProviderError(f"Alpha Vantage {label} has invalid {field} source date") from error

    def _verify_identity(self, payload: Mapping[str, object], security: SecurityIdentity) -> None:
        if self._optional(payload, "Symbol") != security.ticker: raise ResearchProviderError("Alpha Vantage overview symbol does not match requested security")
        if self._optional(payload, "Currency") != security.currency: raise ResearchProviderError("Alpha Vantage overview currency does not match requested security")
        if self._exchange(self._optional(payload, "Exchange")) != self._exchange(security.exchange): raise ResearchProviderError("Alpha Vantage overview exchange does not match requested security")
        if self._asset_type(self._optional(payload, "AssetType")) != security.security_type: raise ResearchProviderError("Alpha Vantage overview asset type does not match requested security")

    @staticmethod
    def _exchange(value: str | None) -> str:
        if value is None: raise ResearchProviderError("Alpha Vantage overview lacks exchange")
        return "".join(character for character in value.upper() if character.isalnum())
    @staticmethod
    def _asset_type(value: str | None) -> str:
        if value is None: raise ResearchProviderError("Alpha Vantage overview lacks AssetType")
        mapping={"COMMONSTOCK":"EQUITY", "ETF":"ETF"}; normalized="".join(value.upper().split())
        if normalized not in mapping: raise ResearchProviderError("Alpha Vantage overview AssetType cannot verify requested security")
        return mapping[normalized]

    def _record(self, source_type: str, title: str, source_date: date, values: Mapping[str, object]) -> SourceResearchRecord:
        return SourceResearchRecord(source_type, title, source_date, tuple((key, normalized) for key, value in values.items() if (normalized := self._value(value)) is not None))

    def _overview_record(self, payload: Mapping[str, object], security: SecurityIdentity) -> NormalizedOverviewFacts:
        values={"company_name":self._optional(payload,"Name"),"description":self._optional(payload,"Description"),"sector":self._optional(payload,"Sector"),"industry":self._optional(payload,"Industry"),"market_cap":self._optional(payload,"MarketCapitalization"),"pe_ratio":self._optional(payload,"PERatio"),"peg_ratio":self._optional(payload,"PEGRatio"),"price_to_book_ratio":self._optional(payload,"PriceToBookRatio"),"eps":self._optional(payload,"EPS"),"revenue_per_share":self._optional(payload,"RevenuePerShareTTM"),"profit_margin":self._optional(payload,"ProfitMargin"),"operating_margin":self._optional(payload,"OperatingMarginTTM"),"return_on_equity":self._optional(payload,"ReturnOnEquityTTM"),"quarterly_revenue_growth":self._optional(payload,"QuarterlyRevenueGrowthYOY"),"quarterly_earnings_growth":self._optional(payload,"QuarterlyEarningsGrowthYOY"),"fifty_two_week_high":self._optional(payload,"52WeekHigh"),"fifty_two_week_low":self._optional(payload,"52WeekLow"),"analyst_target_price":self._optional(payload,"AnalystTargetPrice"),"beta":self._optional(payload,"Beta"),"dividend_yield":self._optional(payload,"DividendYield"),"latest_quarter":self._optional(payload,"LatestQuarter"),"shares_outstanding":self._optional(payload,"SharesOutstanding"),"price_to_sales":self._optional(payload,"PriceToSalesRatioTTM")}
        source=self._record("ALPHA_VANTAGE_OVERVIEW","Alpha Vantage company overview",self._date(payload,"LatestQuarter","OVERVIEW"),values)
        return NormalizedOverviewFacts(source,values["company_name"],values["description"],security.exchange,security.currency,security.security_type,values["sector"],values["industry"],values["market_cap"],values["pe_ratio"],values["peg_ratio"],values["eps"],values["revenue_per_share"],values["profit_margin"],values["operating_margin"],values["return_on_equity"],values["quarterly_revenue_growth"],values["quarterly_earnings_growth"],values["fifty_two_week_high"],values["fifty_two_week_low"],values["analyst_target_price"],values["price_to_book_ratio"],values["beta"],values["dividend_yield"],values["latest_quarter"],values["shares_outstanding"],values["price_to_sales"])

    def _income_record(self, payload: Mapping[str, object], security: SecurityIdentity) -> NormalizedIncomeFacts:
        if self._optional(payload, "symbol") != security.ticker: raise ResearchProviderError("Alpha Vantage INCOME_STATEMENT symbol does not match requested security")
        reports = payload.get("quarterlyReports")
        if not isinstance(reports, list) or not reports or not isinstance(reports[0], dict): raise ResearchProviderError("Alpha Vantage INCOME_STATEMENT lacks quarterly reports")
        report = cast(Mapping[str, object], reports[0])
        source = self._record("ALPHA_VANTAGE_INCOME_STATEMENT", "Alpha Vantage quarterly income statement", self._date(report, "fiscalDateEnding", "INCOME_STATEMENT"), {"total_revenue": report.get("totalRevenue"), "gross_profit": report.get("grossProfit"), "operating_income": report.get("operatingIncome"), "net_income": report.get("netIncome")})
        return NormalizedIncomeFacts(source, self._optional(report,"fiscalDateEnding"), self._optional(report,"reportedCurrency"), self._optional(report,"totalRevenue"), self._optional(report,"grossProfit"), self._optional(report,"operatingIncome"), self._optional(report,"netIncome"))

    def _earnings_record(self, payload: Mapping[str, object], security: SecurityIdentity) -> NormalizedEarningsFacts:
        if self._optional(payload, "symbol") != security.ticker: raise ResearchProviderError("Alpha Vantage EARNINGS symbol does not match requested security")
        reports = payload.get("quarterlyEarnings")
        if not isinstance(reports, list) or not reports or not isinstance(reports[0], dict): raise ResearchProviderError("Alpha Vantage EARNINGS lacks quarterly earnings")
        report = cast(Mapping[str, object], reports[0])
        return self._earnings_from_report(report)

    def _verify_symbol(self, payload: Mapping[str, object], security: SecurityIdentity, label: str) -> None:
        if self._optional(payload, "symbol") != security.ticker:
            raise ResearchProviderError(f"Alpha Vantage {label} symbol does not match requested security")

    def _selected_quarterly_reports(
        self,
        payload: Mapping[str, object],
        list_key: str,
        label: str,
        *,
        as_of: datetime | None,
        limit: int,
    ) -> list[Mapping[str, object]]:
        reports = payload.get(list_key)
        if not isinstance(reports, list) or not reports:
            raise ResearchProviderError(f"Alpha Vantage {label} lacks quarterly reports")
        cutoff = as_of.date() if as_of is not None else None
        selected: list[Mapping[str, object]] = []
        for item in reports:
            if not isinstance(item, dict):
                continue
            report = cast(Mapping[str, object], item)
            if cutoff is not None:
                ending = self._optional(report, "fiscalDateEnding")
                if ending is None:
                    continue
                try:
                    ending_date = date.fromisoformat(ending)
                except ValueError:
                    continue
                if ending_date > cutoff:
                    continue
            selected.append(report)
            if len(selected) >= limit:
                break
        if not selected:
            raise ResearchProviderError(f"Alpha Vantage {label} lacks quarterly reports")
        return selected

    def _income_from_report(self, report: Mapping[str, object]) -> NormalizedIncomeFacts:
        source = self._record(
            "ALPHA_VANTAGE_INCOME_STATEMENT",
            "Alpha Vantage quarterly income statement",
            self._date(report, "fiscalDateEnding", "INCOME_STATEMENT"),
            {
                "total_revenue": report.get("totalRevenue"),
                "gross_profit": report.get("grossProfit"),
                "operating_income": report.get("operatingIncome"),
                "net_income": report.get("netIncome"),
            },
        )
        return NormalizedIncomeFacts(
            source,
            self._optional(report, "fiscalDateEnding"),
            self._optional(report, "reportedCurrency"),
            self._optional(report, "totalRevenue"),
            self._optional(report, "grossProfit"),
            self._optional(report, "operatingIncome"),
            self._optional(report, "netIncome"),
        )

    def _cash_from_report(self, report: Mapping[str, object]) -> tuple[str | None, str | None]:
        primary = self._optional(report, "cashAndCashEquivalentsAtCarryingValue")
        if primary is not None:
            return primary, None
        fallback = self._optional(report, "cashAndShortTermInvestments")
        if fallback is not None:
            return fallback, "cashAndShortTermInvestments"
        return None, None

    def _balance_from_report(self, report: Mapping[str, object]) -> NormalizedBalanceFacts:
        cash, cash_field = self._cash_from_report(report)
        values: dict[str, object] = {
            "cash": cash,
            "debt": self._optional(report, "shortLongTermDebtTotal"),
            "current_assets": self._optional(report, "totalCurrentAssets"),
            "current_liabilities": self._optional(report, "totalCurrentLiabilities"),
            "shares_outstanding": self._optional(report, "commonStockSharesOutstanding"),
        }
        if cash_field is not None:
            values["cash_field"] = cash_field
        source = self._record(
            "ALPHA_VANTAGE_BALANCE_SHEET",
            "Alpha Vantage quarterly balance sheet",
            self._date(report, "fiscalDateEnding", "BALANCE_SHEET"),
            values,
        )
        return NormalizedBalanceFacts(
            source,
            self._optional(report, "fiscalDateEnding"),
            self._optional(report, "reportedCurrency"),
            cash,
            self._optional(report, "shortLongTermDebtTotal"),
            self._optional(report, "totalCurrentAssets"),
            self._optional(report, "totalCurrentLiabilities"),
            self._optional(report, "commonStockSharesOutstanding"),
        )

    def _cash_flow_from_report(self, report: Mapping[str, object]) -> NormalizedCashFlowFacts:
        source = self._record(
            "ALPHA_VANTAGE_CASH_FLOW",
            "Alpha Vantage quarterly cash flow",
            self._date(report, "fiscalDateEnding", "CASH_FLOW"),
            {
                "operating_cash_flow": report.get("operatingCashflow"),
                "capex": report.get("capitalExpenditures"),
                "buybacks": report.get("paymentsForRepurchaseOfCommonStock"),
                "issuance": report.get("proceedsFromIssuanceOfCommonStock"),
            },
        )
        return NormalizedCashFlowFacts(
            source,
            self._optional(report, "fiscalDateEnding"),
            self._optional(report, "reportedCurrency"),
            self._optional(report, "operatingCashflow"),
            self._optional(report, "capitalExpenditures"),
            self._optional(report, "paymentsForRepurchaseOfCommonStock"),
            self._optional(report, "proceedsFromIssuanceOfCommonStock"),
        )

    def _earnings_from_report(self, report: Mapping[str, object]) -> NormalizedEarningsFacts:
        source = self._record(
            "ALPHA_VANTAGE_EARNINGS",
            "Alpha Vantage quarterly earnings",
            self._date(report, "reportedDate", "EARNINGS"),
            {
                "reported_eps": report.get("reportedEPS"),
                "estimated_eps": report.get("estimatedEPS"),
                "surprise": report.get("surprise"),
                "surprise_percentage": report.get("surprisePercentage"),
            },
        )
        return NormalizedEarningsFacts(
            source,
            self._optional(report, "reportedDate"),
            self._optional(report, "fiscalDateEnding"),
            self._optional(report, "reportedEPS"),
            self._optional(report, "estimatedEPS"),
            self._optional(report, "surprise"),
            self._optional(report, "surprisePercentage"),
        )
