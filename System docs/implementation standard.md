# Backend Implementation Standards

This document defines the implementation rules for building backend features consistently.

## Core Principles

- Follow the agreed backend architecture.
- Prefer modular monolith architecture unless there is a clear reason otherwise.
- Organize code by feature/domain.
- Keep the database as the source of truth.
- Write database-aware, performance-conscious code from the start.
- Keep external services behind backend integrations.
- Route frontend data through backend APIs.
- Keep backend contracts aligned with real frontend flows.
- Keep product rules configurable when they are data/policy driven.
- Separate API, service, selector, task, and integration responsibilities.
- Keep domain rules inside their owning feature.
- Finish critical flows completely; do not leave core TODO gaps.
- Keep files reasonably scoped.

## Architecture

Use a structure similar to:

```text
project/
├── config/          # project/framework wiring
├── apps/            # feature modules
├── integrations/    # external services
├── common/          # shared framework-level helpers
├── tests/           # shared/integration tests
└── scripts/         # operational/seed commands
```

A feature may contain:

```text
apps/<feature>/
├── models.py
├── api/v1/views.py
├── api/v1/serializers.py
├── api/v1/urls.py
├── services.py
├── selectors.py
├── tasks.py
├── permissions.py
├── admin.py
└── tests/
```

Do not turn a modular monolith into microservices without a real architectural need.

## Layer Responsibilities

```text
Views / Serializers
→ HTTP handling, request parsing, response formatting, auth/permission entry

Services
→ write-side business logic, transactions, state changes, orchestration

Selectors
→ read queries, filtering, aggregates, optimized retrieval

Tasks
→ asynchronous processing and background work

Integrations
→ external provider communication

Models
→ persistence, relationships, constraints, simple local behavior
```

Avoid:

- fat views
- fat serializers
- hidden cross-feature writes
- duplicated query logic
- business workflows in the wrong layer

## Database

Treat the database as the source of truth.

Do:

- create explicit migrations for schema changes
- use appropriate foreign keys and constraints
- use status enums/state modeling where appropriate
- use indexes intentionally
- use `select_related()` and `prefetch_related()`
- paginate/limit large queries
- review transaction boundaries
- preserve historical records when history matters
- keep financial, pricing, membership, and other critical values explicit
- add audit fields where appropriate

Do not:

- use cache as a permanent fix for bad queries
- store critical workflow state only in JSON
- use nullable fields instead of proper state modeling
- delete important historical records to satisfy current UI needs
- ship obvious inefficient queries in core flows

## API Implementation

- Version APIs consistently, e.g. `/api/v1/`.
- Keep response shapes stable after integration begins.
- Use consistent pagination.
- Add filters/search parameters intentionally.
- Make retry-prone write operations idempotent where appropriate.
- Keep frontend-dependent product rules backend-controlled.
- Do not expose raw external-provider payloads directly to clients.
- Keep admin and user API surfaces clearly separated.
- Document every implemented endpoint.

## External Services

Keep provider-specific code inside `integrations/`.

Examples include:

- authentication providers
- payment providers
- storage/media providers
- search engines
- geocoding/map providers
- messaging providers

Do not call protected external services directly from the frontend.

Do not expose internal infrastructure such as search or data-service ports publicly.

Do not use Redis as durable primary storage.

## Search and Location

For search/map infrastructure:

- expose search through backend APIs
- expose location search/reverse geocoding through backend APIs
- cache repeated requests where appropriate
- use background jobs for indexing/reindexing
- keep search indexes denormalized only as needed for query performance
- keep search infrastructure separate from primary application data

External search indexes are not the source of truth.

## Media

For uploaded media:

- validate ownership and content type
- keep upload handling behind backend APIs
- store originals in the configured storage provider
- move heavy optimization/resizing to background jobs
- store generated variants in structured data when needed
- preserve historical references where required

Do not perform heavy media processing inside request/response execution.

## Authentication and Security

- Verify third-party authentication through trusted backend/provider SDKs.
- Map provider identities to local accounts explicitly.
- Protect private/dashboard endpoints with authentication.
- Enforce object ownership on mutations.
- Rate-limit sensitive endpoints.
- Keep private verification or sensitive documents protected.
- Never trust client-provided role claims.
- Apply role/permission checks to admin and moderation operations.
- Do not expose sensitive/private data before business rules allow it.

## Configurable Product Rules

Rules that may change through administration or policy should generally be data-driven.

Examples:

- plans
- packages
- limits
- prices
- durations
- policies
- CMS content
- configurable thresholds

Do not hardcode values that are expected to change operationally.

When historical behavior matters, preserve snapshots of the rules/values used at the time.

## Background Jobs

Use background tasks for work such as:

- media processing
- search indexing
- notifications
- recommendation refresh
- recalculation
- reports/digests
- cleanup
- synchronization

Tasks should:

- be idempotent where practical
- have explicit retry behavior
- contain enough identifiers to recover context
- log or persist failures when important

Do not hide business-critical failures inside asynchronous processing.

## Testing

Every implemented backend module should have tests.

Test:

- services
- selectors where query behavior matters
- API flows
- permissions
- core business rules
- state transitions
- integration boundaries
- race-prone operations
- failure cases
- regressions

Critical flows involving money, inventory, membership, identity, approvals, or concurrent state changes require stronger coverage.

Do not rely only on manual Postman testing.

## Documentation

Keep implementation documentation synchronized with the codebase.

Update relevant documentation when architecture, schema, infrastructure, or major behavior changes.

Typical project documentation may include:

```text
docs/
├── backend-architecture.md
├── backend-plan.md
├── dependency-audit.md
├── database-erd.dbml
├── api-conventions.md
├── deployment.md
└── operations.md
```

Do not keep final architectural decisions only in chat history.

## Delivery Workflow

Before implementing a backend feature:

1. Check the backend implementation plan.
2. Check whether the database schema supports the flow.
3. Identify the owning feature module.
4. Define the API contract.
5. Implement using the correct layers.
6. Add required async/integration behavior.
7. Add tests.
8. Update documentation where required.

Before marking a feature complete:

- migration exists if schema changed
- tests cover core behavior
- permissions are enforced
- async side effects are handled
- cache/index invalidation is handled
- API documentation is updated
- architecture/schema documentation is updated when necessary
- no critical TODO gaps remain

## File Organization

Keep modules focused.

Split code when:

- a service handles unrelated workflows
- views become difficult to scan
- serializers contain unrelated API concerns
- selectors become a collection of unrelated queries
- one file becomes a dumping ground

Do not keep growing a file simply because all code belongs to the same broad feature.

## Comments

Use comments only when they add context.

Good reasons:

- unusual business rules
- transaction/query decisions
- provider limitations
- non-obvious implementation constraints

Avoid comments that merely narrate obvious code.

## Short Version

Build backend features as a disciplined modular system:

- feature-owned logic
- database-first correctness
- stable API contracts
- backend-controlled business rules
- isolated integrations
- asynchronous heavy work
- secure authentication/authorization
- tested critical flows
- maintained documentation
- production-safe delivery

## Core Principle

> A backend feature is complete only when its architecture, database behavior, API contract, security, background work, tests, and required documentation are implemented consistently and safely.
