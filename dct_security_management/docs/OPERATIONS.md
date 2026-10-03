# Operations screens and policies

## Incident handling

Authorized operations managers and site supervisors create incidents in New.
Acknowledgement, investigation, resolution, and closure are sequential actions.
Resolution is required for both resolving and closing. Closed incidents cannot
be edited; a manager can reopen with a recorded reason. Chatter records workflow
and important field changes. Attach evidence through the native chatter.

Critical and overdue incidents create at most one pending activity with the same
summary per authorized responsible user. Activities are limited to assigned site
supervisors and a permitted investigator. Automation must be enabled per company.

## Patrols

Managers configure routes with ordered required/optional checkpoints. Timing
windows are minute offsets from the planned round start. A round must use a guard
authorized for the same site. An optional assignment must cover the whole round.

Starting captures immutable names, order, requirements, instructions and timing
windows. Subsequent route edits affect future rounds only. Open a checkpoint to
record notes/evidence and use Record Completion. Earlier required checkpoints
must be completed or excepted first. Completion records the current timestamp,
acting user and whether it was outside the planned timing window.

A manager can approve a checkpoint exception with a reason. Required pending
checkpoints block closure. Completion percentage is completed checkpoints divided
by all snapshot checkpoints; approved exceptions are retained separately and do
not inflate completion. Optional pending checkpoints remain visible as missed.
All checkpoint evidence is explicitly labelled manual backend entry.

## Supervisor visits

Managers maintain configurable inspection checklists. Starting a visit snapshots
the checklist. Record each item as Pass, Fail, or Not Applicable and add findings.
Required pending items block completion. The actor and timestamp are recorded.
Completed evidence is frozen. Findings and a category can create one linked
incident; repeated actions open that same incident. Existing incidents must belong
to the same site. Photos use standard protected attachments.

## Overview definitions

All sources use the caller's ACLs and record rules; no public route or elevated
read is used. Company selection is limited to enabled user companies. Site
selection must be inside the user's permitted site scope.

Current cards are independent of selected dates:

- Guards: active employee records marked as security guards in the scope.
- On duty: unique guards on a current published assignment without a leave
  conflict and with open native attendance no older than the maximum open hours.
- Guards on leave: scoped guards with approved leave covering the current time,
  including unscheduled guards. Unscheduled employees are not classified absent.
- Active sites: sites whose operational state is Active.
- Active contracts: Active contracts whose effective dates include today.
- Open incidents: incidents not Resolved or Closed.
- Current site staffing: required shift headcount, valid assigned headcount,
  and valid presence; missing is max(required minus present, zero).

Selected-period statistics use inclusive dates in the user's configured timezone,
converted to a half-open UTC interval. Shift and assignment period selection uses
the start timestamp. The report identifies the site's local start date separately
as the owning date of overnight work.

- Uncovered shifts: published shifts starting in the interval whose valid
  assignment count is below the required headcount.
- Attendance exceptions: published assignments starting in the interval marked
  Late, Missing Checkout, or Suspected Absence. These are review flags.
- Closed patrols: closed rounds starting in the interval; the description also
  shows the total non-cancelled rounds.
- Attendance trends: sum scheduled, worked, and approved assignment hours by
  start date. Actual hours come from native attendance allocations.
- Recent operational activities: six most recently updated incident, patrol,
  or supervisor visit records in scope.

Cards open their source records. Finance figures require Finance Officer and
native accounting read permissions. Each currency has separate invoice, cash
settlement, and payroll source links. See FINANCE.md for accounting formulas,
site allocation and estimated payroll cost rules.

## Weekly board

Rows are guards; columns are calendar days in the user's timezone. Overnight
assignments appear on every covered day with full start/end labels. Click a shift
to open its native editor. The plus button creates a draft shift prefilled with
the guard, selected site and an 08:00–16:00 interval; choose the post and confirm
the actual schedule in the form. Publishing still runs backend eligibility,
overlap, rest, qualification and leave checks.

The board shows at most 150 guards and 1,000 assignments and explicitly warns
when truncated. Narrow the site scope or use the native assignment list. Review
Shortages opens published shifts with missing coverage. Attendance/leave warnings
on assignment chips open the same records for review.

## Site map

Leaflet 1.9.4 is bundled locally under BSD 2-Clause; see static/lib/leaflet/LICENSE.
The installation has no tile provider by default and makes no tile requests.
Configure an HTTPS URL template and attribution in the company settings, and
ensure the provider's terms, quotas and privacy requirements permit your usage.
Attribution is always displayed. A tile failure retains the native site list.

Pins use only fixed site latitude/longitude when Coordinates Configured is enabled.
Zero-valued coordinates are supported. Pins show current required and assigned
staffing and a link to the site. They are never live guard GPS positions.

## Reports and validation

Eight print actions are bound to native source lists/forms. Filter and select the
desired period/site/records before printing. Coverage prints shifts; rosters and
attendance print assignments; incidents, patrols, visits, payroll and billing print
their respective records. Each output uses the record's company branding,
source period, generated timestamp and the printing user's timezone. Financial
parsers check the Finance Officer role even for direct report rendering.

Backend regression tests cover transitions, bypass attempts, frozen snapshots,
ordered checkpoints, exception permissions, deduplicated activities/incidents,
site isolation, overview drilldowns and all eight report templates. Runtime test
results are recorded in the main README. The registered frontend tour
`dct_security_dashboard_smoke` verifies the loaded overview and opens the Guards
card into the native list; start it on the Overview action with an authorized user.
