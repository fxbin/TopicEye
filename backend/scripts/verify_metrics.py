"""Quick verification script for request_metrics module."""

from app.core.request_metrics import get_collector, normalize_path

# Test path normalization
assert normalize_path("/api/v1/topics/123") == "/api/v1/topics/{id}"
assert normalize_path("/api/v1/sources/abc-123-def") == "/api/v1/sources/abc-123-def"  # slug, not an ID
assert normalize_path("/api/v1/analyses/jobs/550e8400-e29b-41d4-a716-446655440000") == "/api/v1/analyses/jobs/{uuid}"
assert normalize_path("/api/v1/contents") == "/api/v1/contents"
assert normalize_path("/") == "/"
print("normalize_path: PASS")

# Test collector
c = get_collector()
c.request_started()
c.request_completed(method="GET", path="/api/v1/topics/123", status=200, duration_seconds=0.05)
c.request_completed(method="POST", path="/api/v1/analyses/batch", status=500, duration_seconds=1.2)
c.rate_limit_hit("/api/v1/auth/login")
c.record_llm_call(
    scene="analysis", status="DONE", duration_seconds=2.5, input_tokens=1000, output_tokens=500, cost_usd=0.02
)

lines = c.render_prometheus()
text = "\n".join(lines)

assert "topiceye_http_requests_total" in text
assert "topiceye_http_request_duration_seconds_bucket" in text
assert "topiceye_http_requests_in_progress" in text
assert "topiceye_http_rate_limit_hits_total" in text
assert "topiceye_http_errors_total" in text
assert "topiceye_llm_calls_total" in text
assert "topiceye_llm_call_duration_seconds_bucket" in text
assert "topiceye_llm_tokens_total" in text
assert "topiceye_llm_cost_total" in text
assert "{id}" in text  # path normalization worked
print("render_prometheus: PASS")
print()
print("Sample metrics output (first 20 lines):")
for line in lines[:20]:
    print(line)
if len(lines) > 20:
    print(f"... ({len(lines)} lines total)")
