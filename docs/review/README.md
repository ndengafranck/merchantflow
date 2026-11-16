# Review probes

`milestone_1_probes.py`, `conftest.py` and `pwa_probe.cjs` are the evidence for
`docs/MILESTONE_1_REVIEW.md`. They were written against commit `67f8586` and
assert the behaviour observed there, including the defects.

They are a historical record and no longer run against the current code: the
device model they probe was replaced by the corrections. Every probe that
demonstrated a defect now has a regression test in `backend/tests/` asserting
the corrected behaviour; the review document maps each finding to its test.
