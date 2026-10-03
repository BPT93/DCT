# Planning and attendance

## Setup and permissions

1. Configure the company and a site timezone. Add posts and responsible site supervisors.
2. Create guards with company-unique codes, operational eligibility, authorized sites and any required qualifications. A guard does not need a user account.
3. Configure working-time and attendance policies on the company. Templates use the site's timezone.

Managers and assigned supervisors create and publish schedules. Supervisors can generate drafts from a readable template without editing the template. Managers and HR officers approve attendance allocations, overtime and attendance period locks. Supervisors record actual attendance and submit corrections; they cannot approve allocations or corrections. Record rules restrict supervisors to their sites and authorized site guards. Finance consumes approved allocation quantities.

## Scheduling

A shift is the coverage requirement at one site/post, with an explicit UTC start/end and required guard count. One assignment per guard connects a guard to that shift. Coverage is independent of the guard's user account. Publishing a shortage is allowed and leaves the missing coverage visible.

Templates define local start/end, unpaid scheduled break hours, required guards, qualifications and weekdays (`0` Monday through `6` Sunday). An end time at or before the start means the next local day. The local start date owns an overnight shift for reporting, including month boundaries.

Use **Generate Draft Roster**, choose a template and a range of up to 366 days, and preview before generating. Existing template/date keys are shown and skipped. Generated shifts always start as drafts. Changing a template does not rewrite generated shifts. **Copy Next Week** preserves local wall times and creates draft assignments. Repeating the action for the same source shift returns the same copied shift.

Datetimes are stored in UTC. Generation converts each local boundary separately, so elapsed time changes correctly over daylight-saving transitions. A local boundary in the spring gap or repeated autumn hour is flagged and blocks generation for that range. Create an explicit shift for that date with the intended UTC interval; this application does not guess which occurrence was intended.

Assignments reject inactive/ineligible guards, unauthorized sites, company mismatches, missing/expired qualifications, approved leave and overlapping assignments. Intervals use `[start, end)`: a check at exactly the previous end does not overlap. Separate minimum-rest rules may still require an override for adjacent shifts.

Default policy is 8 hours minimum rest and 12 hours maximum elapsed shift duration. Zero disables the relevant limit. A permitted rest/maximum-hours override requires an operations manager and a saved reason. Overlap and approved-leave checks cannot be overridden. Employee row serialization protects checks across concurrent transactions, including assignments hidden by another supervisor's site scope.

Publishing freezes shift times, site, post, required coverage and qualifications. Replace a guard with the **Replace Guard** action and a reason. The old assignment, replacement assignment, actor, timestamp and reason remain available. A replacement of an assignment that already has attendance allocations requires a separate shift for the remaining interval so recorded work keeps its original assignment.

Approved time off created or approved after publication sets `leave_conflict` on affected assignments and removes them from assigned coverage. It preserves the published roster and requires a reviewed replacement. Refusal/cancellation of leave refreshes the flag.

## Actual attendance and allocations

`hr.attendance` is the actual event source. Record real check-in/check-out events through **Actual Attendance** or permitted standard imports. Security guards are excluded from native automatic-checkout and technical-absence generation, even when those company settings are enabled; non-security employees retain the normal Odoo behavior. Guards receive DCT review exceptions instead of invented raw events. The DCT workflows do not add native Odoo overtime to the custom calculation.

**Allocate Attendance** intersects each completed raw attendance interval with an assignment. Repeat clicks skip existing exact intervals. Multiple intervals support breaks and partial attendance. Open events must receive a real checkout before allocation.

An allocation must be a positive interval inside a completed raw event, belong to the same guard/company and overlap its published assignment. No two allocations for the guard can overlap, even on different assignments. Explicit allocations can include approved worked overtime beyond the scheduled bounds; automatic reconciliation clips to scheduled bounds. Supervisors must review and extend an allocation explicitly when overtime is supported by the raw event.

Allocation hours are elapsed hours. Breaks in actual work must be represented by separate checkout/check-in intervals; the template's break hours reduce scheduled hours only. This avoids silently inventing raw break events. Native `hr.attendance.worked_hours` can differ because Odoo's employee calendar may deduct calendar lunch intervals. Billing and payroll use DCT approved allocation hours and this documented interval policy.

Formulas:

- Scheduled hours = elapsed shift hours minus configured scheduled break hours.
- Worked hours = sum of allocation interval hours.
- Approved hours = sum of approved allocation hours.
- Proposed overtime = maximum of worked hours minus scheduled hours and zero.
- Approved overtime = a separate authorized snapshot, permitted only after every allocation is approved.
- Lateness = positive difference between first relevant raw check-in and scheduled start.
- Early departure = positive difference between scheduled end and last relevant closed event after the shift ends.

Approved allocations are frozen. Consumed payroll hours also freeze their approved overtime snapshot. Suspected absence and incidents never create deductions automatically.

## Current status and exceptions

Current status uses the actual current time, independently of report date filters:

- **On Duty** requires a published, non-leave-conflicted assignment covering now and attendance covering now.
- **Scheduled** is a future published assignment.
- **On Leave** is an assignment affected by approved leave.
- **Late / Not Checked In** is a started assignment without relevant attendance before the absence grace expires.
- **Suspected Absence** begins after the company absence grace (default 30 minutes) with no relevant raw attendance.
- **Missing Checkout** is an open event more than the checkout grace past scheduled end (default 2 hours), or older than the maximum live open duration (default 16 hours).
- Other cases are **Off Duty**. Unscheduled employees are not automatically absent.

Suspected absence remains an exception requiring review. **Attendance Exceptions** records a resolution, actor and review time without creating a payroll or billing penalty. Company-enabled automation inspects the recent 31 days, records each assignment/kind once and creates internal supervisor activities without duplicates. Rosters are generated only for enabled companies and opted-in templates; all output remains draft. The dispatcher runs one company at a time.

## Corrections and locked periods

Create an **Attendance Correction** with a site, actual attendance, proposed values and reason. The original values are captured on creation. Submit for manager/HR approval. Approval rejects stale requests when another edit changed the original event, applies the requested real values, records approval history and resets unconsumed allocation/overtime approvals for review.

Corrections cannot invalidate the interval boundaries of existing allocations. They cannot rewrite attendance already consumed by approved payroll/billing or an approved attendance period. For those cases, use a separately approved financial adjustment or the controlled credit/rebilling workflow; the original evidence remains unchanged. The basic correction workflow does not create replacement raw events, fabricate checkouts, or automatically calculate retrospective payroll adjustments.

**Attendance Period Locks** freeze employee intervals after allocations are reviewed. Open checkouts prevent locking. Locked periods cannot be edited or deleted, and later raw events/allocations overlapping them are rejected. Period boundaries use UTC; choose them to represent the intended local payroll/reporting boundary.

## Verification

`tests/test_planning.py` covers overlap/adjacency, eligibility/site authorization, rest overrides, immutable workflow and RPC quantities, overnight/month boundaries, DST gap/fold/elapsed duration, repeated generation/copying, replacement history, partial attendance, allocation approval, overtime, corrections, locked periods, attendance status, approved leave and qualification expiry. Additional permission-mode tests run as an actual manager and site supervisor, including repeated preview/generation and denied supervisor approval.

`tools/test_planning_concurrency.py` requires a disposable database whose name starts with `dct_security_test_`. It commits fictional fixtures and runs two independent PostgreSQL transactions for overlapping assignments, overlapping allocations, repeated roster generation and publication racing with adding a guard. Serialization failures use fresh-cursor retries like Odoo. Drop the test database afterward. See the main README/test evidence for commands and results actually run; the existence of a test is not proof that it passed.
