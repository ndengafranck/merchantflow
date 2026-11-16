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
**Resolved (D-017).** Revoking an installation ends its sessions. Revoking a
workspace device closes that workspace and leaves the session, because the
same browser may legitimately work in other workspaces.

### O-007 Password reset
Not implemented. Needs an email (or SMS) provider. Until then an operator
resets passwords with `manage.py changepassword`.

### O-020 Should new devices need the owner's approval?
**Why it matters:** without approval, anyone who knows a member's password
can use a new or cookie-cleared browser straight away, so revoking a device
does not keep out a person who still has the password (D-019).
**Current default:** no approval; first entry authorises (D-018), as
instructed. **To decide:** approval for all roles, for affiliates only, or
never; and who approves when the owner is unavailable.

### O-021 Should an owner be able to end a member's sessions?
An owner can revoke a member's workspace device but not their installation
(D-020). **To decide:** whether that is enough, or whether suspending a
membership should also revoke that member's devices in the workspace.
**Current default:** suspension blocks access immediately; device rows are
left as they are.

### O-022 Limit on installations per user
Each login from an unrecognised browser creates an installation row.
**Current default:** unlimited. **To decide:** a cap, and cleanup of
installations not used for a long time.

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
