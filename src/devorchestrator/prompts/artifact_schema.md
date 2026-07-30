# Artifact: <task title>
_Issue: <id> | Branch: <branch> | Generated: <YYYY-MM-DD>_

## Context
- One bullet per real finding from reading the codebase. Cite concrete paths.
- Existing patterns the implementation must follow (naming, error handling, layering).
- Libraries already available — never propose adding a dependency that is present.
- Risks and gotchas, stated plainly. This section is where research earns its keep.

## Sub-tasks
- [ ] One imperative, independently checkable step.
- [ ] Ordered so each builds on the previous.
- [ ] Include a test-writing sub-task.

## Files to Create / Modify
- `path/to/file.py` — what changes here
- `path/to/new_file.py` — new file, what it holds
- `tests/test_thing.py` — new file, what it covers

## Acceptance Criteria
- [ ] Observable, verifiable outcome — not "code is clean".
- [ ] Includes the check commands that must pass (e.g. `ruff check`, `pytest`).

## Implementation Notes
- Anything the implementer needs that is not a sub-task: sequencing, edge cases,
  a decision made during research and why the alternative was rejected.
