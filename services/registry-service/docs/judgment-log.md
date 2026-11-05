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

## 5. Which `code` to use for 405 Method Not Allowed

- **Suggested:** the task lists only four codes (`VALIDATION`, `NOT_FOUND`, `CONFLICT`, `UNAVAILABLE`), and none is an exact match for 405. Options were: one of the four, a new code, or no code.
- **Decided:** status 405 with code `VALIDATION`.
- **Why:** the status number already says exactly what happened. The code is the category, and the category is "your request is wrong, fix it". `UNAVAILABLE` would make clients retry forever. `NOT_FOUND` is misleading, because the resource exists. `CONFLICT` is about state, and no state change makes the request succeed. A new code or a missing code breaks the closed list in the task.

## 6. Keep httpx despite the deprecation warning

- **Suggested:** pytest warns that using httpx with `TestClient` is deprecated, and suggests `httpx2`. The user asked whether to switch.
- **Decided:** keep httpx.
- **Why:** the warning does not break anything, the course plan uses httpx, and switching adds a new dependency with no benefit right now.

## 7. Map every sqlite3.OperationalError to 503

- **Suggested:** `sqlite3.OperationalError` covers both "database unavailable" (missing file, locked file) and code bugs (like a missing table). Options: map all of it to 503, or split the cases.
- **Decided:** map all `sqlite3.OperationalError` to 503 `UNAVAILABLE`.
- **Why:** simple and in one place. The bug cases only happen when the code is wrong, and the tests catch them before submission. A missing or broken database file really is "unavailable".

## 8. What counts as an empty farm name

- **Suggested:** the task says a farm name must be non-empty, but does not say what "empty" means.
- **Decided:** strip spaces at the start and end of the name. A name that is empty after stripping is rejected with 422.
- **Why:** a name of only spaces cannot be read or found in a list, so it is empty in practice. Spaces at the edges are not part of the name.

## 9. What PATCH does with an empty body or a null name

- **Suggested:** the task says PATCH changes only the fields sent, but does not say what an empty body or a null name should do.
- **Decided:** an empty body returns 200 with no change. A null name returns 422.
- **Why:** "change only what was sent" means nothing changes when nothing is sent, which is harmless. A farm must always have a name, so null is invalid.

## 10. Check for plots before deleting a farm

- **Suggested:** the database already refuses to delete a farm that has plots, because foreign keys are on.
- **Decided:** check for plots in the route and return 409 `CONFLICT` before deleting. Keep the foreign key as a safety net.
- **Why:** the database error is a different type that no handler catches, so the client would get a 500. The task asks for 409.

## 11. Plot names follow the farm name rule

- **Suggested:** the task requires a non-empty name for farms, but for plots it only says the name is unique inside a farm.
- **Decided:** plot names follow the farm rule. Strip the spaces around the name, and an empty result returns 422.
- **Why:** without stripping, `"North block"` and `"North block "` are different text, so a duplicate name would pass the uniqueness rule.
