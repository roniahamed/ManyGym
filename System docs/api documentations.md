# API Documentation Standards

This document defines the standard for writing and maintaining API documentation for backend projects.

## Goal

API documentation must allow developers to understand and integrate an endpoint without reading its source code.

## Documentation Stack

Recommended:

- OpenAPI as the API contract and source of truth
- drf-spectacular for Django REST Framework
- Swagger UI for interactive exploration
- Redoc / Redocly for reference documentation

Generated schemas must be reviewed and supplemented where necessary.

## Every Endpoint Must Document

- HTTP method
- endpoint path
- summary
- description
- authentication
- permissions/roles
- ownership rules
- path parameters
- query parameters
- request body
- success response
- error responses
- request example
- success example
- failure example
- side effects when applicable

## Authentication & Authorization

Document:

- whether authentication is required
- authentication mechanism/token type
- required role or permission
- object ownership
- organization/tenant restrictions
- role-specific behavior

Authentication and authorization must be documented separately.

## Request Documentation

Document important:

- fields
- types
- required/optional status
- nullable behavior
- defaults
- enum values
- validation rules
- business rules

Do not rely only on automatically generated serializer documentation.

## Response Documentation

Document:

- HTTP status
- response schema
- important fields
- pagination metadata
- relevant headers

The documented response must match the actual API response.

## Examples

Examples must:

- match the real schema
- use valid enum values
- use realistic IDs and values
- represent realistic business scenarios

Important endpoints must include request and response examples.

Avoid meaningless placeholders such as:

```text
foo
bar
123
test@example.com
```

when realistic values are possible.

## Error Documentation

Document meaningful errors, including where applicable:

- `400` Bad Request
- `401` Unauthorized
- `403` Forbidden
- `404` Not Found
- `409` Conflict
- `422` Validation Error
- `429` Too Many Requests

Use only statuses the endpoint can actually return.

Keep the error response format consistent across the project.

Example:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Invalid request data.",
  "details": {
    "email": [
      "Enter a valid email address."
    ]
  }
}
```

Business-specific errors should also be documented.

## Pagination, Filtering & Sorting

For list endpoints document:

- pagination type
- default/max page size
- page or cursor parameters
- filters
- search parameters
- sorting parameters
- default ordering

## Workflow & State

For stateful resources document:

- available statuses
- status meaning
- allowed transitions
- who can trigger each transition
- invalid transitions
- transition side effects

Examples:

- orders
- reservations
- subscriptions
- applications
- approvals
- tickets
- verification workflows

## Side Effects

Document important side effects such as:

- notifications
- emails
- refunds
- inventory changes
- background jobs
- audit logs
- cache invalidation
- search indexing

## Idempotency

For operations where duplicate requests matter, document:

- whether the endpoint is idempotent
- idempotency key requirements
- duplicate request behavior
- retry behavior

Especially important for payments, order creation, reservations, and webhooks.

## File Uploads

Document:

- accepted file types
- maximum file size
- file count limits
- ownership rules
- processing behavior
- generated variants
- synchronous/asynchronous processing

Backend rules are the source of truth.

## Search & Location APIs

Document:

- input parameters
- result format
- ranking behavior
- sorting
- pagination
- caching
- rate limits
- external provider
- fallback behavior

For location APIs also document:

- latitude/longitude format
- coordinate system
- radius units
- distance behavior
- reverse-geocoding behavior

## WebSocket APIs

Maintain a separate WebSocket contract when applicable.

Document:

- connection URL
- authentication
- event names
- event direction
- payloads
- error events
- reconnect behavior
- heartbeat/ping
- typing/presence/seen behavior

## Webhooks

Document:

- provider
- endpoint
- authentication/signature verification
- event types
- payload schema
- retry behavior
- duplicate delivery handling
- idempotency
- expected response

Webhook processing must safely handle duplicate deliveries.

## Admin & Staff APIs

Clearly document:

- required role
- required permission
- audit implications
- destructive actions
- archive vs delete
- visibility restrictions
- bulk operations

Clearly label admin/staff-only behavior.

## External Integrations

If an endpoint depends on an external provider, document:

- provider
- purpose
- timeout behavior
- retry behavior
- fallback behavior
- provider limitations
- provider failure behavior

Never expose secrets or credentials in examples.

## API Versioning

If versioning is used, document:

- version strategy
- current version
- deprecated versions
- migration path
- breaking-change policy

Clearly mark deprecated endpoints.

## OpenAPI Authoring

Explicitly define when automatic generation is insufficient:

- summary
- description
- tags
- request schema
- response schema
- examples
- enums
- error responses
- authentication
- deprecation

Review the generated OpenAPI schema before considering an endpoint complete.

## Documentation Maintenance

Update documentation whenever changing:

- endpoint paths
- HTTP methods
- request fields
- response fields
- field types
- validation rules
- enums
- authentication
- permissions
- error formats
- status codes
- pagination
- filters
- sorting
- workflow states
- side effects
- upload rules

Documentation must always reflect the current API implementation.

## Standard Endpoint Structure

Use:

1. Summary
2. Authentication
3. Authorization
4. Request
5. Parameters
6. Request Body
7. Request Example
8. Success Response
9. Success Example
10. Error Responses
11. Error Examples
12. Workflow / State Rules
13. Side Effects
14. Notes

Only include applicable sections.

## Review Checklist

Before marking an endpoint documented:

- [ ] In OpenAPI schema
- [ ] Meaningful summary and description
- [ ] Authentication documented
- [ ] Permissions/roles documented
- [ ] Ownership documented
- [ ] Parameters documented
- [ ] Request body documented
- [ ] Important fields explained
- [ ] Enums documented
- [ ] Success response documented
- [ ] Request example included
- [ ] Success example included
- [ ] Error responses documented
- [ ] Error examples included
- [ ] Pagination/filtering documented
- [ ] Workflow documented when applicable
- [ ] Side effects documented
- [ ] Idempotency documented when applicable
- [ ] Upload rules documented when applicable
- [ ] External dependencies documented when relevant
- [ ] WebSocket/Webhook documented when applicable
- [ ] Admin restrictions clearly labeled
- [ ] Documentation matches implementation
- [ ] Frontend can integrate without reading source code

## Do Not

- rely only on auto-generated schema
- leave admin endpoints undocumented
- omit important examples
- use unrealistic examples everywhere
- document outdated behavior
- use Postman as the only API reference
- hide business rules
- expose secrets
- use inconsistent error formats
- omit authentication or permissions
- leave workflow transitions unexplained
- allow documentation to drift after API changes

## Core Principle

> If a developer must read backend source code to correctly consume an API, the API documentation is incomplete.
