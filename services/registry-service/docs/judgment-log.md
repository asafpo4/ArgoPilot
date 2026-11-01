# Judgment log

Each entry: what the coding agent suggested, what we decided, and why.

## 1. Where to turn database failures into HTTP 503

- **Suggested:** the agent first planned to put the 503 mapping in `db.py`.
- **Decided:** the mapping goes in `errors.py`, as an exception handler for `sqlite3.OperationalError`. `db.py` only opens the connection.
- **Why:** `db.py` should not know about HTTP status codes. Keeping all error responses in one file means the problem+json format is defined in one place.

## 2. Defaults for the unclear points in the task

- **Suggested:** the agent listed 12 unclear points, each with a default. For example: unknown farm in `?farm_id=` returns `200 []`, and unknown routes return `NOT_FOUND`.
- **Decided:** use the defaults, with two changes. No environment variable for the database path. Tests override the database dependency to point at a temporary copy.
- **Why:** fewer extras, since the task says not to add anything it does not ask for. Tests must not change the real `registry.db`.

## 3. PATCH must run the same checks as POST

- **Suggested:** the first plan did not say that PATCH re-checks the rules.
- **Decided:** PATCH merges the new fields into the existing plot, then runs the same validation on the result. A duplicate name on the same farm returns 409 `CONFLICT`. An empty farm name on PATCH returns 422 `VALIDATION`.
- **Why:** otherwise PATCH could bypass the rules that POST enforces. The spec applies the rules to plots, not to one HTTP method.

## 4. Commit locally, publish later

- **Suggested:** commit after each step.
- **Decided:** commit is done locally. Publishing (push to GitHub) waits until the user asks for it.
- **Why:** a push is visible to anyone with repo access and is hard to undo. Local commits are enough to keep history.
