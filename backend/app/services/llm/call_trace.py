"""Per-logical-call links to the existing physical LlmCallLog records.

This is execution metadata and a reservation fuse, not a second billing ledger.
Prices and usage still come from llm_usage; unavailable evidence stays unknown.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from uuid import uuid4


class LlmTraceBudgetExceeded(RuntimeError):
    """A deliberate local refusal; never retry it or degrade model health."""


@dataclass
class CallBudget:
    max_physical_attempts: int | None = None
    max_cost_usd: Decimal | None = None
    used_attempts: int = 0
    reserved_cost_usd: Decimal = Decimal("0")

    def reserve(self, model, max_tokens: int) -> None:
        if self.max_physical_attempts is not None and self.used_attempts >= self.max_physical_attempts:
            raise LlmTraceBudgetExceeded("physical attempt cap reached")
        upper = Decimal("0")
        if self.max_cost_usd is not None:
            from app.services.llm_usage import pricing_from_model

            pricing = pricing_from_model(model)
            # Legacy billing helpers infer zero from some model names. A
            # transport budget must require an explicit price declaration.
            if any(getattr(model, key, None) is None for key in ("cost_per_1k_input", "cost_per_1k_output")):
                raise LlmTraceBudgetExceeded("cost-capped calls require explicit known unit prices")
            if any(
                pricing.get(key) != round(getattr(model, field) * 1000, 6)
                for key, field in (("input", "cost_per_1k_input"), ("output", "cost_per_1k_output"))
            ):
                raise LlmTraceBudgetExceeded("configured prices disagree with legacy normalized prices")
            window = getattr(model, "context_window", None)
            try:
                rates = [
                    Decimal(str(getattr(model, field))) * 1000 for field in ("cost_per_1k_input", "cost_per_1k_output")
                ]
                extra = getattr(model, "extra_params", None) or {}
                input_rates = [rates[0]] + [
                    Decimal(str(extra.get(key) or 0))
                    for key in ("cost_per_1m_input_cache_hit", "cost_per_1m_input_cache_create")
                ]
                valid_rates = all(rate.is_finite() and rate >= 0 for rate in rates + input_rates)
            except (InvalidOperation, TypeError, ValueError):
                valid_rates = False
            if type(window) is not int or window < 1 or not valid_rates:
                raise LlmTraceBudgetExceeded("cost-capped calls require known unit prices and context window")
            extra = getattr(model, "extra_params", None) or {}
            if any(rates + input_rates) and extra.get("pricing_currency") != "USD":
                raise LlmTraceBudgetExceeded("cost-capped calls require explicitly verified USD pricing")
            # Reserve for the entire declared context window, not a token
            # estimate. Retain reservations after failures of unknown billing.
            input_rate = max(input_rates)
            upper = (Decimal(window) * input_rate + Decimal(max_tokens) * rates[1]) / 1_000_000
            if self.reserved_cost_usd + upper > self.max_cost_usd:
                raise LlmTraceBudgetExceeded("conservative cost reservation exceeds the run cap")
        self.used_attempts += 1
        self.reserved_cost_usd += upper


@dataclass
class CallTrace:
    logical_request_id: str
    budget: CallBudget
    attempts: list[dict] = field(default_factory=list)
    route: dict = field(default_factory=dict)

    def begin_attempt(self, model, request_model: str, max_tokens: int) -> dict:
        self.budget.reserve(model, max_tokens)
        prefix = sha256(self.logical_request_id.encode()).hexdigest()[:24]
        attempt = {
            "request_id": f"llm_{prefix}_{uuid4().hex[:24]}",
            "requested_model": request_model,
            "configured_model_id": getattr(model, "id", None),
            "status": "started",
            "usage": None,
            "persisted": False,
            "cost_usd": None,
        }
        self.attempts.append(attempt)
        return attempt

    def report(self) -> dict:
        cache_hit = bool(self.route.get("cache_hit"))
        complete = all(a["persisted"] and (a["usage"] or {}).get("actual_model") for a in self.attempts)
        cost_known = all(a["cost_usd"] is not None for a in self.attempts)
        # A patched/mock transport with no physical attempts is not usage proof.
        measured = bool(self.attempts) or (
            cache_hit
            and bool(self.route.get("origin_request_id"))
            and self.route.get("origin_usage_linkage_verified") is True
        )
        return {
            "logical_request_id": self.logical_request_id,
            "route": dict(self.route),
            "physical_attempts": [dict(a) for a in self.attempts],
            "cache_hit": cache_hit,
            "usage_linkage_verified": measured and complete,
            "cost_usd": sum(a["cost_usd"] for a in self.attempts) if measured and cost_known else None,
            "cost_basis": "existing LlmCallLog unit-price estimate; not provider invoice",
            "provider_billing_verified": False,
        }


_trace: ContextVar[CallTrace | None] = ContextVar("llm_call_trace", default=None)
_budget: ContextVar[CallBudget | None] = ContextVar("llm_call_budget", default=None)


def current_trace() -> CallTrace | None:
    return _trace.get()


@contextmanager
def llm_call_budget(*, max_physical_attempts: int, max_cost_usd: float | None = None):
    if not 1 <= max_physical_attempts <= 1000:
        raise ValueError("physical attempt cap must be 1..1000")
    amount = Decimal(str(max_cost_usd)) if max_cost_usd is not None else None
    if amount is not None and (not amount.is_finite() or amount <= 0):
        raise ValueError("cost cap must be finite and positive")
    budget = CallBudget(max_physical_attempts=max_physical_attempts, max_cost_usd=amount)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


@contextmanager
def trace_llm_call(logical_request_id: str | None = None):
    trace = CallTrace(logical_request_id or f"logical_{uuid4().hex}", _budget.get() or CallBudget())
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)


def finish_attempt(attempt: dict | None, *, status: str, usage=None, persisted: dict | None = None, error=None):
    if attempt is None:
        return
    attempt["status"] = status
    attempt["error_type"] = type(error).__name__ if error is not None else None
    if usage is not None:
        attempt["usage"] = {
            key: getattr(usage, key)
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "actual_model")
        }
    if isinstance(persisted, dict) and persisted.get("request_id") == attempt["request_id"]:
        attempt["persisted"] = True
        attempt["log_id"] = persisted.get("id")
        # A failed HTTP request with missing usage cannot be priced as zero.
        if (
            usage is not None
            and persisted.get("pricing_currency") == "USD"
            and all(persisted.get(key) is not None for key in ("cost_per_1m_input", "cost_per_1m_output"))
        ):
            attempt["cost_usd"] = persisted.get("total_cost")
