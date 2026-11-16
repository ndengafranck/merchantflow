# Open decisions

Business rules that are not settled. Each has a safe default so work can
continue. Nothing here has been silently implemented as a rule.

## Relevant now

### O-001 How do affiliates without email sign in?
**Why it matters:** many independent sellers in Cameroon use a phone number
and WhatsApp, not email. **Current default:** email login only (D-002); the
user model already stores a phone number. **To decide:** phone + password,
phone + one-time code (needs an SMS or WhatsApp provider and budget), or
email only. **Deadline:** before affiliate onboarding (Milestone 2).

### O-002 What can an owner grant a manager?
The brief says managers have "access according to owner-granted permissions".
**Current default:** a fixed, conservative set: managers can view members and
manage devices, and cannot change memberships. **To decide:** the list of
grantable permissions. The capability mechanism (D-007) is ready for it.

### O-003 Who can create a workspace, and how are members invited?
**Why it matters:** public sign-up, invitation links, and operator-created
workspaces have different abuse and support profiles. **Current default:**
operator-only, through management commands (D-010).

### O-004 Can a workspace have co-owners?
**Current default:** no, exactly one (D-004).

### O-005 Session lifetime
**Current default:** 14 days, fixed from login. **To decide:** shorter for
owners? Sliding expiry? Forced re-login before payouts?

### O-006 Should revoking a device also sign that browser out?
**Current default:** no (D-009). Doing it needs sessions to be tied to
devices, which belongs with the sync design.

### O-007 Password reset
Not implemented. Needs an email (or SMS) provider. Until then an operator
resets passwords with `manage.py changepassword`.

## Relevant to later milestones (recorded so they are not forgotten)

| ID | Question | Blocks |
|---|---|---|
| O-010 | Refund and partial-refund accounting, and its effect on commissions | Payments, commissions |
| O-011 | Taxes and unusual discounts in the commission base | Orders, commissions |
| O-012 | Rounding rule for percentage commissions in XAF | Commissions |
| O-013 | Import behaviour for each historical workbook format | Excel import |
| O-014 | Data-retention periods and permanent deletion | Archiving |
| O-015 | Offline conflict-resolution policies per record type | Sync |
| O-016 | Multiple-location inventory | Inventory |
| O-017 | Reporting definitions (what counts as revenue, when) | Reports |
| O-018 | Is a customer shared across affiliates in a workspace, given affiliates must not see each other's customers? | Customers, orders |
| O-019 | UI language: English, French or both | All screens |
