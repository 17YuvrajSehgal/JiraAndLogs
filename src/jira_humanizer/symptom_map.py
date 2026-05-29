"""Fault → symptom paraphrase: what the reporter actually saw.

Implements Rule 2 from LLM-Jira-enhancement.md §3. This file is the
**only** place the lab's fault taxonomy is mapped to user-facing
language. The mapping deliberately translates fault families into
symptom phrases that share vocabulary with what a human would write
into a Jira ticket — without naming the fault.

Lookup contract:
  symptom_for(scenario_family, severity, affected_service)
  -> SymptomDescription with:
       * `headline`: one-line public-facing description ("checkout 5xx at payment step")
       * `evidence_hints`: bullet phrases the LLM may quote ("p95 spike on checkout")
       * `severity_phrasing`: how the reporter would express urgency
                              ("customer-reported", "site-wide impact")

The mapping is **lossy on purpose**. Multiple faults map to the same
symptom (cart-redis and redis-restart both surface as "cart not
loading after add"), and the LLM never has a way to disambiguate.
"""

from __future__ import annotations

from dataclasses import dataclass


SYMPTOM_MAP_VERSION = "v1.0.0"


@dataclass(frozen=True)
class SymptomDescription:
    headline: str
    evidence_hints: tuple[str, ...]
    severity_phrasing: str
    # The reporter's emotional framing — different vocabularies for
    # different fault shapes. "intermittent" is much more anxious than
    # "spike then settled".
    reporter_framing: str


# scenario_family -> symptom. Families not in the map fall back to a
# generic "elevated errors on {service}" symptom so we never leak the
# fault taxonomy by exposing missing-key behavior.
_FAMILY_TO_SYMPTOM: dict[str, SymptomDescription] = {
    "cart-redis": SymptomDescription(
        headline="users seeing add-to-cart not persisting; cart looks empty after refresh",
        evidence_hints=(
            "cart endpoint returning errors",
            "cart writes appear to fail intermittently",
            "high error rate on cartservice",
        ),
        severity_phrasing="customer-reported, multiple users affected",
        reporter_framing="frustrated — users keep retrying and losing items",
    ),
    "payment-outage": SymptomDescription(
        headline="checkout failing at the payment step",
        evidence_hints=(
            "payment requests timing out",
            "checkout 5xx after card submission",
            "rising error rate at checkout->payment",
        ),
        severity_phrasing="revenue-impacting, customers cannot complete orders",
        reporter_framing="urgent — direct revenue impact",
    ),
    "productcatalog-latency": SymptomDescription(
        headline="category and product pages loading slowly, frequent timeouts",
        evidence_hints=(
            "catalog responses above 3s p95",
            "frontend showing slow product grids",
            "checkout pre-validation hanging",
        ),
        severity_phrasing="degraded UX site-wide",
        reporter_framing="customers complaining about slow site",
    ),
    "productcatalog-outage": SymptomDescription(
        headline="category pages returning errors / missing product listings",
        evidence_hints=(
            "5xx on /product endpoints",
            "empty category pages",
            "frontend showing broken thumbnails",
        ),
        severity_phrasing="catalog browsing broken",
        reporter_framing="customer impact: people can't browse",
    ),
    "currency-outage": SymptomDescription(
        headline="prices showing wrong currency / falling back to default",
        evidence_hints=(
            "currency conversion timing out",
            "prices displayed in fallback currency",
        ),
        severity_phrasing="cosmetic but visible",
        reporter_framing="confused customers; pricing looks wrong",
    ),
    "shipping-outage": SymptomDescription(
        headline="checkout failing at the shipping calculation step",
        evidence_hints=(
            "shipping quote requests failing",
            "checkout stuck at delivery options",
        ),
        severity_phrasing="checkout-blocking",
        reporter_framing="urgent — orders not completing",
    ),
    "ad-outage": SymptomDescription(
        headline="recommended ads not loading on product pages",
        evidence_hints=(
            "ad slots empty",
            "ad service responses slow or missing",
        ),
        severity_phrasing="non-critical, no order impact",
        reporter_framing="noticed by ads team monitoring",
    ),
    "recommendation-outage": SymptomDescription(
        headline="product recommendations not showing on home/product pages",
        evidence_hints=(
            "recommendation API errors",
            "empty 'you may also like' sections",
        ),
        severity_phrasing="conversion impact, not order-blocking",
        reporter_framing="noticed via dashboards",
    ),
    "email-outage": SymptomDescription(
        headline="order confirmation emails not going out",
        evidence_hints=(
            "email queue backing up",
            "customers asking where their confirmation is",
        ),
        severity_phrasing="customer-visible but no order loss",
        reporter_framing="CS forwarded several inquiries",
    ),
    "checkout-outage": SymptomDescription(
        headline="checkout page returning errors / not loading at all",
        evidence_hints=(
            "checkout endpoint 5xx",
            "cart-to-checkout transition failing",
        ),
        severity_phrasing="revenue-blocking, urgent",
        reporter_framing="urgent — total checkout failure",
    ),
    "checkout-restart": SymptomDescription(
        headline="checkout briefly unavailable, came back after ~30 seconds",
        evidence_hints=(
            "transient errors during a short window",
            "checkout health flapped",
        ),
        severity_phrasing="brief impact, recovered",
        reporter_framing="brief blip, paged but resolved fast",
    ),
    "frontend-restart": SymptomDescription(
        headline="site briefly unavailable, came back ~30s later",
        evidence_hints=(
            "all frontends restarted around the same time",
            "users got a brief outage page",
        ),
        severity_phrasing="brief site-wide blip",
        reporter_framing="paged, but site recovered quickly",
    ),
    "frontend-traffic-pressure": SymptomDescription(
        headline="site slow / sporadic errors under load",
        evidence_hints=(
            "frontend latency rising with traffic",
            "occasional 503s on hot pages",
        ),
        severity_phrasing="degraded under peak load",
        reporter_framing="noisy alerts but no clear single cause",
    ),
    "recovered-in-window": SymptomDescription(
        headline="errors spiked and then settled before we could investigate",
        evidence_hints=(
            "brief spike on error dashboard",
            "self-recovered within a couple minutes",
        ),
        severity_phrasing="self-resolved, monitoring",
        reporter_framing="not sure if worth a ticket; capturing for tracking",
    ),
    "post-deploy-churn": SymptomDescription(
        headline="elevated errors right after the last deploy, settled within a few minutes",
        evidence_hints=(
            "errors started ~T+0 of the rollout",
            "rolled through and stabilised",
        ),
        severity_phrasing="brief churn post-rollout",
        reporter_framing="watching — looks like normal post-deploy",
    ),
    "single-pod-restart-healthy-replication": SymptomDescription(
        headline="single pod restarted, traffic re-routed to remaining replicas",
        evidence_hints=(
            "one replica went down briefly",
            "no customer-visible impact",
        ),
        severity_phrasing="contained, no impact",
        reporter_framing="recorded for tracking, no action needed",
    ),
    "third-party-blip": SymptomDescription(
        headline="brief failures attributed to an upstream third-party API",
        evidence_hints=(
            "errors correlate with external dependency",
            "third-party status page reflects an issue",
        ),
        severity_phrasing="not our problem, but customer-visible",
        reporter_framing="capturing for the record; will follow vendor",
    ),
    "scheduled-job-spike": SymptomDescription(
        headline="brief error spike during a scheduled job window",
        evidence_hints=(
            "error rate aligns with cron timing",
            "no customer-visible impact",
        ),
        severity_phrasing="contained, job-related",
        reporter_framing="ack — known noisy job window",
    ),
    "latency-near-miss-partial-recovery": SymptomDescription(
        headline="latency degraded then partially recovered, never fully resolved",
        evidence_hints=(
            "p95 climbed then stabilised at an elevated baseline",
            "no clear root cause yet",
        ),
        severity_phrasing="ongoing watch",
        reporter_framing="not sure if it's worth paging; capturing for tracking",
    ),
    "flapping-pod": SymptomDescription(
        headline="intermittent errors, hard to reproduce consistently",
        evidence_hints=(
            "error rate bouncing up and down",
            "individual requests sometimes succeed",
        ),
        severity_phrasing="intermittent — needs investigation",
        reporter_framing="frustrating, hard to pin down",
    ),
    "slow-leak-saturation": SymptomDescription(
        headline="error rate climbing gradually over the last hour",
        evidence_hints=(
            "memory usage trending up",
            "errors started subtle, getting worse",
        ),
        severity_phrasing="trending, will hit critical if not addressed",
        reporter_framing="not urgent yet, but escalating",
    ),
    "network-partition": SymptomDescription(
        headline="intermittent connectivity issues between services",
        evidence_hints=(
            "calls between certain services failing",
            "other paths look healthy",
        ),
        severity_phrasing="partial outage, partial visibility",
        reporter_framing="suspect networking; need infra-team eyes",
    ),
    "dns-outage": SymptomDescription(
        headline="some service-to-service calls failing with name-resolution errors",
        evidence_hints=(
            "lookups failing for specific service hostnames",
            "other hostnames resolving normally",
        ),
        severity_phrasing="partial — only some calls affected",
        reporter_framing="weird — only some services impacted",
    ),
    "network-latency": SymptomDescription(
        headline="latency between two specific services is unusually high",
        evidence_hints=(
            "RTT between those services elevated",
            "no error count spike, just slowness",
        ),
        severity_phrasing="degraded, but functional",
        reporter_framing="slow but working; not paging yet",
    ),
    "resource-saturation": SymptomDescription(
        headline="resource utilisation high on one service, performance degrading",
        evidence_hints=(
            "CPU/memory near capacity",
            "throughput dropping under load",
        ),
        severity_phrasing="capacity-driven, will need scaling",
        reporter_framing="we're hitting limits — short-term and longer-term fix needed",
    ),
    "baseline-normal": SymptomDescription(
        headline="dashboard looks normal but a CS forward came in",
        evidence_hints=(
            "no signal in our metrics",
            "single customer report, hard to verify",
        ),
        severity_phrasing="unverified",
        reporter_framing="probably nothing, capturing in case it recurs",
    ),
}


_DEFAULT_SYMPTOM = SymptomDescription(
    headline="elevated errors / degraded performance on {service}",
    evidence_hints=(
        "error rate elevated relative to baseline",
        "latency above normal range",
    ),
    severity_phrasing="needs investigation",
    reporter_framing="seeing issues, opening this for tracking",
)


def symptom_for(scenario_family: str, *, affected_service: str = "") -> SymptomDescription:
    """Return the symptom paraphrase the LLM will see.

    The lookup is **case-insensitive** to defend against the family
    string showing up in different cases across the corpus. If the
    family is unknown, the generic fallback is returned — never raise,
    because that would expose family-set membership to a caller.

    `affected_service` is substituted into the `{service}` placeholder
    in the fallback symptom. It does NOT change the lookup key (we
    never want a service name to alter which symptom is shown).
    """
    key = (scenario_family or "").lower().strip()
    sym = _FAMILY_TO_SYMPTOM.get(key, _DEFAULT_SYMPTOM)
    if "{service}" in sym.headline:
        svc = affected_service or "the affected service"
        return SymptomDescription(
            headline=sym.headline.format(service=svc),
            evidence_hints=sym.evidence_hints,
            severity_phrasing=sym.severity_phrasing,
            reporter_framing=sym.reporter_framing,
        )
    return sym
