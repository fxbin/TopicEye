# Stabilization Architecture Review

Parent: #2

## Current system shape

TopicEye is a layered application with these important boundaries:

- **Frontend**: user interaction, query/state/error/loading presentation.
- **FastAPI API**: HTTP contracts, auth/session, validation and orchestration entry points.
- **Service layer**: extraction, enrichment, classification, analysis, trending and product workflows.
- **Repository/ORM + Alembic**: transactional OLTP persistence and schema evolution.
- **Scheduler/background execution**: APScheduler source sync, cleanup, trends and persisted analysis-job dispatch/recovery.
- **Analytics**: DuckDB analytical layer with intended SQLAlchemy/OLTP fallback for degraded operation.
- **External I/O**: source feeds/pages, OAuth, LLM providers, files/PDF and optional alert integrations.

## Architecture finding

The architecture is not primarily suffering from a missing framework or missing abstraction. The stabilization risk comes from **cross-boundary state and lifecycle behavior**:

1. request lifetime vs background task lifetime;
2. scheduler process ownership vs deployment worker topology;
3. database lease/commit/rollback vs process interruption;
4. persistent job recovery vs duplicate execution/idempotency;
5. DuckDB availability vs fallback correctness;
6. external I/O failures vs retries/timeouts/test determinism;
7. dependency upgrades vs ASGI/auth/parser behavior.

For this iteration, architecture work therefore favors **explicit contracts + observability + deterministic tests** over new architectural layers.

## Stability invariants

### Data
- A failed source/job attempt must not leave permanent ambiguous state without a recovery path.
- Recovery/retry must be idempotent or protected against duplicate side effects.
- Transaction boundaries stay in service/repository workflows; no opportunistic cross-layer commits.
- Schema changes use Alembic and provide forward/rollback validation per repository policy.

### Scheduler / lifecycle
- There must be an explicit supported scheduler ownership topology.
- Startup in degraded analytics mode must not silently break core OLTP reads.
- Shutdown must cancel/await owned background tasks or deliberately transfer ownership to durable jobs.
- Unhandled background task exceptions must be observable.

### External I/O
- Production calls have bounded timeout/retry behavior appropriate to the operation.
- Unit tests do not rely on public network.
- Integration tests that use external services are explicit and separable from default CI.

### API/frontend contract
- Errors are distinguishable from empty-success states.
- Primary pages have explicit loading/error/empty/success handling.
- Changes to response schemas are covered by contract tests before parallel FE/BE work.

## Change strategy

Do not perform a broad rewrite. Use vertical slices:

`reproduce → write/adjust regression → smallest behavioral fix → focused tests → full relevant CI → independent verification`

When a reliability audit reveals a concrete bug, split it into a dedicated issue so architecture hardening does not become an unreviewable mega-PR.

## Observability requirements for stabilization

Use existing request IDs and job tracking where possible. For intermittent P0/P1 defects, capture at least one stable correlation key (request ID, source ID, analysis job ID, scheduler job ID) plus timestamps and state transitions. Avoid logging secrets or raw tokens.

## Decisions deferred

- Replacing APScheduler.
- Moving to a separate queue/worker system.
- Replacing DuckDB.
- Large frontend state-management rewrite.

These require evidence that current architecture cannot satisfy the defined invariants, not merely preference.