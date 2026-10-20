# Date/time correctness — issue #2915

Issue: <https://github.com/beyonders-studio/initiative/issues/2915>

The investigation started after the **valid date/time review on PR #2912**:
<https://github.com/beyonders-studio/initiative/pull/2912#pullrequestreview-5588710237>.
That review prompted a wider audit; these findings are not attributed to that PR.
Its review response is handled separately. This change delivers the audit fixes in
one PR targeting `dev`; merge, release and deployment are outside this handoff.

## Finding-to-regression map

Paths below are relative to the repository root. Backend tests live beside the
source and run with the repository's PostgreSQL test fixtures.

| Finding | Corrected behavior | Source and regression entry points |
| --- | --- | --- |
| D01 | All-day drag preserves calendar-day spans across 23/25-hour days and midnight gaps. | `frontend/src/components/calendar/CalendarView.tsx`; `CalendarView.datetime.test.tsx` |
| D02 | iCal recurrence exports retain fractional offsets with a defined fixed-offset VTIMEZONE. | `backend/app/services/tenant/ical_service.py`; `ical_service_test.py` |
| D03 | Shifted date-valued recurrence exceptions and extra dates export on the correct UTC day. | `ical_service.py`; `ical_service_test.py` |
| D04 | Fixed task recurrence retains its phase through extra dates, skip/completion and editing; consumed COUNT stays bounded. | `backend/app/services/tenant/task_series.py`, `task_creation.py`, `task_queries.py`, `backend/app/api/v1/tenant_endpoints/tasks.py`; `task_series_test.py`, `project_export_test.py`, `backend/app/db/task_recurrence_anchor_migration_test.py` |
| D05 | Yearly day 29–31 clamping keeps every selected month, including leap years and interval >1. | `frontend/src/lib/recurrence.ts`, `recurrence.test.ts`; `backend/app/core/recurrence_test.py` |
| D06 | Calendar and notice inputs naming instants reject missing offsets with 422, including occurrence query parameters. | `backend/app/schemas/tenant/calendar_event.py`, `post.py`, `post_poll.py`, calendar event endpoints; `calendar_events_test.py`, `posts_test.py` |
| D07 | Completion statistics use completed_at, so later edits do not move completions or change on-time results. | `backend/app/services/tenant/stats_service.py`; `stats_service_test.py` |
| D08 | Declared plug-in datetime columns compare and aggregate instants, with UTC time buckets; text columns retain text semantics. | `backend/app/services/query/rows.py`; `rows_test.py` |
| D09 | PostgreSQL DATE retains date_only metadata through query/describe/canvas responses and table/board rendering. Timestamp formatting still uses the viewer's timezone. | `backend/app/services/query/executor.py`, `backend/app/schemas/sql_query.py`, query/dashboard endpoints; their tests; `frontend/src/lib/widgets/{normalize,format}.test.ts`, table/board and BoardNode tests |
| D10 | iCal import honors DURATION, distinguishing nominal days from elapsed hours across clock changes. | `ical_service.py`; `ical_service_test.py` |
| D11 | Editing unrelated event fields retains exact saved instants, seconds, milliseconds and fold identity. | `frontend/src/components/initiativeTools/events/eventDateTime.ts`, `EventDateTimeFields.tsx`; helper, dialog and EventDetailPage tests |
| D12 | Day/week grids place events by wall-clock hour; backwards-clock spans show their offsets and keep minimum markers in distinct lanes. | `frontend/src/components/calendar/views/shared.tsx`, `DayView.tsx`; `CalendarView.datetime.test.tsx` |
| D13 | Manual input rejects impossible calendar dates and newly ambiguous/nonexistent local times instead of silently normalizing them. | `frontend/src/lib/localDateTime.ts`, `frontend/src/components/ui/date-time-picker.tsx`; their tests |
| D14 | Year/list expansion is bounded by the visible range, without the old 90-day truncation or end-day loss after a midnight gap. | `frontend/src/components/calendar/views/{shared,ListView,YearView}.tsx`; `CalendarView.datetime.test.tsx` |
| D15 | Calendar slot selection reaches the create dialog with its selected hour; valid fold-day defaults retain their resolved end instant. Invalid slots are rejected before Date normalizes them. | `frontend/src/pages/initiativeTools/events/CalendarsPage.tsx`, `CreateEventDialog.tsx`; their tests |
| D16 | A zero-duration repeating task retains both start and due dates. | `backend/app/services/tenant/task_series.py`, `task_creation.py`; `task_series_test.py` |

## Decisions and compatibility

- Frontend code continues using JavaScript Date/date-fns. The fix distinguishes
  calendar dates, local wall time, absolute instants and elapsed durations; it is
  not a blanket Temporal migration. No new runtime dependency was added.
- A new or changed ambiguous/nonexistent local time is explicitly rejected with
  a localized error. An unchanged imported timestamp retains its original
  instant, including which side of a repeated hour it names. The UI does not add
  a new timezone or fold-selection control.
- Existing fixed-instant recurrence and rolling tasks' completer-local-day
  semantics remain intentional. Month-end skip semantics for custom RRULEs are
  not silently rewritten. Calendar-window parameters that explicitly document
  naive input as UTC retain that policy.
- Instant-valued calendar and notice write inputs now require `Z` or an explicit
  UTC offset. Date-only values and iCal floating values have separate existing
  resolution paths. Older clients sending timezone-less instant strings receive
  validation errors and must include the offset.
- `QueryColumnDescription.date_only` is additive; numeric epoch values on the wire
  are unchanged. SQL DATE is formatted as a calendar date, while timestamptz and
  other instant-valued fields retain viewer-local formatting.
- The generated API client is regenerated from the backend OpenAPI definition.
  Task reads expose the anchor metadata; project export/import also carries it,
  while older envelopes remain accepted.

## Migration and rollback

`backend/alembic/versions/20261020_0528_fixed_task_recurrence_anchor.py` follows
`20261019_0526`, adding `tasks.recurrence_anchor` (nullable timestamptz) and
`tasks.recurrence_anchor_count` (non-null integer, default 0) to each guild schema.
New guild schemas derive their columns from current model metadata.
At implementation time, open PR #2912 independently adds migration 0527. Both
PRs currently follow 0526; whichever lands second must rebase and chain its
migration to the new head before merging. This PR does not edit #2912's migration.

Backfill uses the current effective carried due/start and the existing consumed
count. A surviving original task cannot prove whether a later intentional
following-series edit changed phase, so the migration preserves the current
continuation rather than guessing historical intent. Already-lost historical
phase cannot be reconstructed. Legacy counts may have included extra dates; the
migration conservatively retains that consumption rather than restarting COUNT.

The review of PR #2917 identified that the initial backfill test used the
privileged setup connection, hiding the migration login's row-security
restrictions. That [valid finding](https://github.com/beyonders-studio/initiative/pull/2917#discussion_r4328945602)
was reproduced with the configured provisioning login: it owns the task table,
has neither superuser nor BYPASSRLS privileges, and has no request context. With
forced row security still active, the backfill silently left anchors empty and
counts at zero. The regression now connects as that actual login and checks
the deployed ownership and row-security conditions explicitly.

Lifting row security also exposed a write-guard failure under that login:
task/ancestor guards reject updates without request context. The backfill now
temporarily lifts forced row security and suspends the task table's user
triggers in the migration transaction, restoring both in `finally`. Only the
two new recurrence fields are updated; archive, trash and hold state is
preserved. A savepoint around the update lets cleanup run after a SQL error
without masking the original error. A failed upgrade rolls back its schema
and data changes along with the temporary protection changes.

The downgrade drops the two added columns. Code can be rolled back, but dropping
anchor state and later re-upgrading cannot recover intervening phase history.
Back up the database before an operational downgrade. No production migration or
deployment was performed as part of this task.

## Validation

The initial combined frontend run passed **146 tests in 15 files**. The shared
calendar/locale follow-up passed **441 tests in 3 files** (overlapping calendar
coverage; these counts are not additive). The production Vite bundle built.
Backend query/calendar endpoint validation passed **104 tests**; the final
recurrence/statistics/query batch passed **322 tests**. The branch was then rebased
onto `efbef4e7a` (the shared recurrence owner from PR #2914), preserving that
refactor. The post-integration batch passed **288 tests**, including the added
fixed-to-rolling COUNT lifecycle regression and all shared completion/skip callers.

The PR #2917 review follow-up passed **6 actual-provisioner migration tests**.
The combined migration/recurrence follow-up passed **58 tests**; **370** static
backfill-order cases were skipped because those revisions create no table.
That batch covers the six migration cases, task-series lifecycles, per-guild
migration routing and rollback, and the new-table backfill-order guard.

A real browser loaded the actual CalendarView and DateTimePicker components with
fixture data, in Europe/Amsterdam, at 1280px and 390px widths. It confirmed 09:00
at the 09:00 row, separate lanes for overlapping backwards-clock markers, a 15:00
slot callback, and no horizontal overflow at 390px. Typing February 30, a spring
gap time and an autumn fold time produced an error without changing the saved
value. This is component/browser evidence, not a signed-in application journey
or external calendar-provider compatibility proof.

![Desktop component verification](datetime-calendar-desktop.png)

![Mobile component verification](datetime-calendar-mobile.png)

Independent source review found additional edit/carry, fold-default, lane and
midnight-gap cases; regression tests reproduced them and the fixes passed.
Cross-provider review was skipped because that reviewer subscription is
unavailable. No skipped review is represented as approval.

No production migration, release or deployment was attempted. External calendar
clients and device WebViews were not exercised.

## Calendar expansion CI follow-up

The [backend run on the review-fix head](https://github.com/beyonders-studio/initiative/actions/runs/39480736350/job/118828685988)
finished with **1 failed, 11,849 passed and 371 skipped**. Its sole failure,
`calendar_entries_test.py::test_guild_entries_give_each_occurrence_of_a_repeat`,
reproduced locally: lowering the occurrence limit to seven still returned
eight events with HTTP 200 instead of the expected 422.

`calendar_events.occurrences` had captured `recurrence.MAX_EXPANDED` in a default
argument at import time. It now resolves that default at call time, while
retaining an explicitly supplied remaining budget, including zero. The existing
rejection assertions remain in place. Added boundary checks accept windows
that fit exactly and reject windows that exhaust the budget across guilds.

The original failing test was reproduced before the fix. After the fix, the
combined calendar aggregate, calendar event, recurrence core and task-series
batch passed **192 tests**:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -n 0 \
  app/api/v1/tenant_endpoints/calendar_entries_test.py \
  app/api/v1/tenant_endpoints/calendar_events_test.py \
  app/core/recurrence_test.py \
  app/services/tenant/task_series_test.py --tb=short -q
```


## Maintainer review follow-up

The [maintainer review](https://github.com/beyonders-studio/initiative/pull/2917#pullrequestreview-5590996288)
identified unnecessary row copies and repeated anchor derivation. Query
evaluation now builds normalized row dictionaries only when the declared
fields include a date; other evaluations use the original mappings. All
**93 query-evaluator tests** passed, including datetime comparisons and text
fields that look like dates.

`task_series.anchor_from_dates` now owns the Python derivation of the effective
carried due/start date and consumed count. Task edits, legacy imports and the
model listener call it at their existing write boundaries. The migration SQL
remains a self-contained revision snapshot.

`next_dates` uses the same pure helper as a local fallback without setting ORM
fields. The new read-purity regression failed before the change because it
changed `(None, 0)` anchor state and dirtied the task. Completion and skip now
initialize a missing fixed anchor before changing dates or releasing carry,
preserving the original phase even when the next occurrence is an extra date.
Regression coverage includes carried dates, zero-duration spans, retained COUNT
and the absence of ORM dirty state after a read.

The focused recurrence/import batch passed **29 tests**. The migration rollback
fixture now inserts its deliberately malformed legacy carry via SQL after a
valid model save: shared write-time derivation otherwise rejects it before the
migration is reached. Its original SQL-error, protection-restoration and data
rollback assertions remain in place.

Another **111 tests** passed across task creation, task/status endpoints,
calendar aggregation and the actual-provisioner migration suite. Together
with the 93 evaluator and 29 recurrence/import tests, these are **233 focused
tests** across distinct files. The additional integration command was:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -n 0 \
  app/services/tenant/task_creation_test.py \
  app/api/v1/tenant_endpoints/tasks_test.py \
  app/api/v1/tenant_endpoints/task_statuses_test.py \
  app/api/v1/tenant_endpoints/calendar_entries_test.py \
  app/db/task_recurrence_anchor_migration_test.py --tb=short -q
```

## Dependency security CI follow-up

The [security scan on the maintainer-fix head](https://github.com/beyonders-studio/initiative/actions/runs/39491006587/job/118863870024)
flagged `follow-redirects` 1.16.0, reached through Axios in
`frontend/pnpm-lock.yaml`. The upstream advisories
[CVE-2026-111755](https://github.com/follow-redirects/follow-redirects/security/advisories/GHSA-8r9p-f939-6h3c)
and [CVE-2026-111756](https://github.com/follow-redirects/follow-redirects/security/advisories/GHSA-q3jh-wrc6-jgq8)
both identify 1.16.1 as patched. The generated lockfile update changes only
that package version, integrity and Axios reference; direct dependency ranges
and security scan policy are unchanged.

The lockfile was regenerated from `frontend` with the pinned pnpm version:

```sh
pnpm update follow-redirects --depth Infinity --no-save --lockfile-only
```

Trivy **0.70.0**, matching CI's version and filesystem flags, scanned tracked
source snapshots with vulnerability, secret and misconfiguration scanning,
HIGH/CRITICAL severity and `ignore-unfixed`. The original snapshot reproduced
the two CVEs; replacing only the frontend lockfile produced **zero** findings
under that policy. The scan kept the checkout's ignored environment files out
of its input, matching CI's tracked source.

A frozen installation confirmed Axios resolves `follow-redirects` 1.16.1.
All **50 tests in the three API-client suites** passed and the production Vite
bundle built:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm exec vitest run src/api --maxWorkers=2
pnpm exec vite build
```

## Reproducible checks

Run from the repository root with the documented dependencies and PostgreSQL
test environment configured. The pre-push hook executes the same quality checks
as CI; the PR records its result separately from remote CI.

```sh
scripts/ci/check
```

The review regression uses a separate connection from the configured migration
URL, pointed at the checkout's isolated test database. It checks active,
archived, trashed and held tasks, carried continuation and consumed COUNT,
restored row security and triggers, Python failure cleanup, and SQL failure
rollback with the original error preserved:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -n 0 \
  app/db/task_recurrence_anchor_migration_test.py
```

The broader review follow-up ran:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -n 0 \
  app/db/task_recurrence_anchor_migration_test.py \
  app/services/tenant/task_series_test.py \
  app/db/guild_migrations_test.py \
  app/db/migration_backfill_order_test.py
```

The post-integration backend batch covers the moved shared owner and all its
completion/skip callers, plus the migration and calendar API boundaries:

```sh
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -n 0 \
  app/services/tenant/task_series_test.py \
  app/services/tenant/task_creation_test.py \
  app/api/v1/tenant_endpoints/tasks_test.py \
  app/api/v1/tenant_endpoints/task_statuses_test.py \
  app/services/tenant/project_export_test.py \
  app/db/task_recurrence_anchor_migration_test.py \
  app/api/v1/tenant_endpoints/calendar_events_test.py \
  app/core/recurrence_test.py
```

Additional database-backed coverage ran the query executor, query endpoints,
canvas date metadata, plug-in statement responses, statistics lifecycle, notice
inputs and iCal service tests. Frontend coverage ran calendar/date-picker,
event form/detail/page, recurrence editor, widget normalization/formatting,
table/board scene and locale-key tests with at most two workers. Production
bundling used `pnpm exec vite build` from `frontend`.
