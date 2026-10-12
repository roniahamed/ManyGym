# Backend Coding Standards

Standards for writing, reviewing, and maintaining clean, predictable, testable backend code.

## Core Principles

- Prefer clarity over cleverness.
- Keep responsibilities explicit.
- Keep feature ownership clear.
- Put logic in the correct layer.
- Prefer cohesive, small modules.
- Avoid unnecessary abstractions and dependencies.
- Optimize for maintainability and testability.

## Project Structure

Common Django structure:

```text
project/
├── config/          # framework/configuration
├── apps/            # feature modules
├── integrations/    # external providers
├── common/          # genuinely shared code
├── tests/           # shared test utilities
└── scripts/         # operational commands
```

Feature modules may contain:

```text
apps/<feature>/
├── models.py
├── services.py
├── selectors.py
├── tasks.py
├── permissions.py
├── admin.py
├── rest_api/v1/
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
└── tests/
```

Do not create layers that provide no real value.

## Layer Responsibilities

```text
HTTP/API
→ authentication, authorization, parsing, response

Serializer
→ input/output validation and representation

Selector
→ read/query logic

Service
→ business workflows, writes, transactions, orchestration

Model
→ persistence, relationships, constraints, small local behavior

Task
→ asynchronous execution

Integration
→ external provider communication

Common
→ genuinely shared infrastructure
```

Do not mix responsibilities unnecessarily.

## Naming

Use explicit, intent-based names.

Good:

```text
create_order
approve_application
get_user_orders
calculate_invoice_total

OrderCreateSerializer
OrderDetailSerializer

get_order_by_id
list_available_products
```

Avoid:

```text
process
handle_data
do_action
helper
common_helper
utils2
data
```

Services should describe business actions. Selectors should describe queries. Serializers should describe API use cases.

## Views

Views should:

1. authenticate
2. authorize
3. parse/validate input
4. call a service or selector
5. return the response

Avoid:

- large business workflows
- multi-model orchestration
- external API calls
- complex branching

## Serializers

Use serializers for:

- request validation
- field validation
- response representation
- API shape

Avoid:

- complete business workflows
- multi-model orchestration
- external calls
- hidden writes
- major state transitions

## Services

Services own:

- business rules
- write workflows
- state transitions
- transactions
- multi-model operations
- orchestration
- side effects

Services must not depend on HTTP request/response concerns.

Split large services by workflow.

## Selectors

Selectors own reusable read logic:

- filtering
- ordering
- list/detail queries
- annotations
- aggregates
- relationship loading

Selectors should normally be read-only.

## Models

Models should focus on:

- fields
- relationships
- constraints
- simple invariants
- small local methods/properties

Avoid large workflows, network calls, orchestration, or hidden side effects in `save()`/`delete()`.

## Validation

Use the appropriate layer:

```text
API input          → Serializer
Model invariant    → Model / DB constraint
Business workflow  → Service
```

Avoid unnecessary validation duplication.

## Transactions

Use transactions when related writes must succeed or fail together.

Keep transaction scopes small. Avoid slow external calls inside transactions unless required.

## Database

Always consider:

- query count
- N+1 queries
- indexes
- relationship loading
- pagination
- filtering
- ordering
- aggregation

Use `select_related()` and `prefetch_related()` appropriately.

Never load large growing datasets blindly.

## Exceptions

Use explicit domain exceptions:

```text
InsufficientBalanceError
ResourceUnavailableError
OrderStateConflictError
OwnershipViolationError
```

Avoid generic `Exception`.

Do not expose raw database/provider/infrastructure errors to API consumers.

## Dependencies

Keep dependency direction intentional:

```text
API → Services / Selectors → Models
Services → Tasks / Integrations / Selectors / Models
Selectors → Models
```

Avoid circular imports and unnecessary cross-feature coupling.

Use public service/selector interfaces when one feature needs another.

## Common & Utilities

`common/` should contain only genuinely shared code.

Avoid giant `utils.py` files.

Prefer cohesive utility modules, or keep code inside the feature that owns it.

## Files & Functions

Split code when responsibilities become unrelated or difficult to scan/test.

Do not split code merely to increase file count.

Do not create tiny helpers without a readability or reuse benefit.

## Comments

Comments should explain **why**, not obvious **what**.

Avoid comments that merely describe the next line of code.

Use docstrings for public or complex services, selectors, integrations, and reusable utilities.

## Async Tasks

Use tasks for non-blocking work such as:

- emails
- notifications
- heavy processing
- synchronization
- reports
- indexing
- large batches

Consider retries, idempotency, duplicate execution, failure handling, and observability.

## Integrations

Keep provider-specific logic inside `integrations/`.

Handle:

- authentication
- requests
- responses
- provider errors
- retries

Do not scatter provider SDK calls through views, serializers, or models.

## Configuration & Secrets

Never hardcode or commit:

- passwords
- API keys
- tokens
- private keys
- production credentials

Never log secrets or sensitive personal data.

Use environment variables or proper secret management.

## Logging

Log meaningful operational events:

- security/auth events
- integration failures
- task failures
- important workflow failures
- infrastructure failures

Use appropriate log levels and enough context for investigation without exposing sensitive data.

## Migrations

For schema changes:

- create explicit migrations
- review indexes
- review data migration needs
- consider compatibility
- consider deployment/rollback risk
- consider production data size

Prefer small, safe migrations. Use staged migrations for risky/destructive changes.

## Testing

Test important:

- business rules
- services
- permissions
- APIs
- serializers
- selectors where query behavior matters
- workflow transitions
- integrations
- failure cases

Do not test only happy paths.

## Security

Always review:

- authentication
- authorization
- object-level permissions
- input validation
- injection risks
- sensitive data exposure
- file uploads
- rate limiting
- CSRF/CORS where applicable
- secrets
- logging privacy
- dependency vulnerabilities

Authentication alone is not authorization.

## Performance

Look for:

- N+1 queries
- unnecessary DB calls
- oversized querysets
- inefficient serialization
- unnecessary external requests
- missing indexes
- expensive repeated work
- excessive synchronous processing

Optimize based on evidence. Do not use caching to hide poor query design.

## API Compatibility

Keep response shapes consistent and documented.

Before breaking an existing API:

1. identify consumers
2. update documentation
3. update consumers
4. version when appropriate
5. communicate the change

## Code Style

Follow project formatter/linter/type-checker configuration.

For Python, commonly use:

- Ruff
- Ruff formatter or Black
- isort where needed
- mypy where typing is adopted

Use type hints where they improve clarity.

## Constants & Enums

Use named constants/enums for meaningful domain values.

Avoid unexplained magic numbers and strings.

## Operational Safety

Before production changes, consider:

- migrations
- background jobs
- cache invalidation
- deployment ordering
- rollback
- monitoring
- logging
- external provider behavior

## Anti-Patterns

Avoid:

- fat views
- fat serializers
- fat models
- giant utility modules
- generic `process()`/`handle()` functions
- hidden writes
- hidden external calls
- circular imports
- unnecessary coupling
- unbounded queries
- N+1 queries
- secrets in source control
- sensitive logs
- unnecessary dependencies
- premature abstractions
- premature optimization

## Review Checklist

- [ ] Correct module/feature
- [ ] Clear responsibility
- [ ] Good naming
- [ ] Correct layer
- [ ] Efficient queries
- [ ] No N+1
- [ ] Proper transactions
- [ ] Explicit exceptions
- [ ] Correct permissions
- [ ] Safe secrets/logging
- [ ] Safe migrations
- [ ] Tests include failure cases
- [ ] External calls isolated
- [ ] Files remain cohesive
- [ ] No unnecessary abstraction
- [ ] Operational impact reviewed

## Core Principle

> Another developer should quickly understand which feature owns the code, whether it reads or writes, where the business rule lives, how data is queried, how failures are handled, and how the behavior is tested.
