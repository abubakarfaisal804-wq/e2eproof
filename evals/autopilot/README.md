# Autopilot deterministic evaluations

`fixtures/local-cycle.json` is a complete, non-live observation fixture for local and
CI evaluation. The Autopilot tests use it to verify baseline selection, idempotent
replay, active-slot behavior, terminal outcomes, policy gates, missing observations,
locking, recovery, and audit integrity.

The fixture records a point-in-time repository state. It is test data, not a claim
about current customers, revenue, distribution, or security. The scheduled workflow
overlays it with live read-only GitHub observations before planning.
