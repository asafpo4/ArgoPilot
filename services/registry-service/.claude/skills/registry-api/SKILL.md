---
name: registry-api
description: API conventions for registry-service. Use this skill whenever adding, changing, or fixing an endpoint, route, router, request/response model, error handler, or endpoint test in registry-service, even for a small tweak like a new field, a PATCH handler, or a list route. Covers /v1 routing, response shape, PATCH semantics, RFC 9457 error format with stable codes, required tests, and when to ask instead of guessing.
---

# registry-api

These are the conventions every endpoint in registry-service follows. Clients
and other services build against them, so a deviation in one endpoint breaks
assumptions made for all the others. Each rule below says why it exists, so
you can apply it correctly in cases the list doesn't spell out.

## Routing and responses

**Put every route under `/v1`.**
Versioning in the path lets us make breaking changes later under `/v2`
without disturbing existing clients. An unversioned route can't be retired
cleanly.

**Return lists as JSON arrays. No rows means `200` and `[]`.**
Clients iterate the body directly. A wrapper object, a `404`, or a `null` for
an empty result forces every caller to special-case "nothing here", and an
empty collection is a valid answer, not an error.

**Return only the fields the spec lists. Never add fields on your own.**
Every field in a response becomes a contract that clients may depend on and
that we then have to keep. Extras (internal ids, timestamps, convenience
flags) can also leak data the spec deliberately left out. Use an explicit
response model so extra attributes on the DB row can't slip through. If a
field seems missing, ask (see the last section) rather than add it.

**Make PATCH change only the fields present in the request body.**
PATCH means partial update. Overwriting omitted fields with defaults or
`None` silently destroys data a client never meant to touch. Distinguish
"field absent" from "field set to null" (for example with
`model_dump(exclude_unset=True)`), and leave absent fields as they were.

## Errors

**Every error is `application/problem+json` (RFC 9457) with a stable `code`.**
A single machine-readable error format means clients write one error handler.
The `code` is what they branch on, so it must never change when the human
text does. Use exactly these:

| code          | status | when                                             |
|---------------|--------|--------------------------------------------------|
| `VALIDATION`  | 422    | request is malformed or fails validation         |
| `NOT_FOUND`   | 404    | the addressed resource doesn't exist             |
| `CONFLICT`    | 409    | the request clashes with current state           |
| `UNAVAILABLE` | 503    | a dependency is down; send a `Retry-After` header |

Body shape: `type`, `title`, `status`, `detail`, plus `code`. Set the
`Content-Type` header to `application/problem+json`, not `application/json`.
The shape is fixed so clients parse every error the same way. Example 404:
```json
{"type": "about:blank", "title": "Not Found", "status": 404, "code": "NOT_FOUND", "detail": "No entry with id 42."}
```

**Send `Retry-After` on every 503.**
Without it clients guess a retry interval and tend to hammer a service that is
already struggling.

**Never let FastAPI's default error body reach a client.**
Its `{"detail": ...}` shape (including the default 422 from request
validation) has no `code` and isn't problem+json, so any path that falls
through to it breaks the one-error-format promise. Reuse the handlers in
`errors.py` (`main.py` registers them); if one is missing for a case you hit (validation errors,
unhandled `HTTPException`s), add it rather than working around it. Check the
response for your new route, not just the handler code.

## Tests and verification

**Give every endpoint tests for the success case and every failure case it can
return.**
Error handling is where conventions silently rot, and failure paths are the
ones nobody exercises by hand. List the failure codes the endpoint can
produce (a path id can be `NOT_FOUND`, a body can be `VALIDATION`, a unique
field can be `CONFLICT`, a dependency can be `UNAVAILABLE`) and write one test
per code. Assert the status, the `application/problem+json` content type, the
`code`, and for 503 the `Retry-After` header. For success, assert the exact
set of fields, so an accidental extra field fails the test. For PATCH, assert
that omitted fields are unchanged.
Copy the pattern of the existing tests in `tests/`, and check a new route's response in a test, not only in the handler code.

**Run `uv run pytest` before saying the work is done.**
"Should work" isn't evidence. Run the full suite, since a change to a shared
handler or model can break other endpoints. Report the real result; if
something fails, say so and fix it or explain it, never claim done.

## When the spec is silent

**If the spec doesn't say what to do in some case, ask. Don't invent behavior.**
Invented behavior looks like a decision but nobody made it, and once clients
rely on it, it's a contract. Typical gaps: which fields a response includes,
whether a duplicate is `CONFLICT` or an upsert, what a PATCH with an empty
body does, how deletes behave. Stop, state the specific question and the
options you see (with your recommendation), and wait for the answer. A short
question costs far less than an endpoint that has to be redone.
