"""Every Solve bound in one place: attempts, rounds, deadlines, waits, workers, egress calls, and text caps (memos dev/127, dev/131).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import os as _os

from utk_curio.backend.app.agents.domain import content


# Solve concurrency (dev/52, DEC-048): the dev/15 manifest's
# maxParallelChildren — a runtime constant until policy demands tuning.
_SOLVE_MAX_WORKERS = 3


# A hard-crashed solve leaves the transient "solving" phase behind; a marker
# older than this is treated as stale so the user is never wedged.
#: dev/118: measured from ``solvingSince``, which every wave boundary
#: refreshes — so "stale" means "no wave completed for 15 minutes", not "the
#: batch started 15 minutes ago".
_SOLVE_STALE_SECONDS = 15 * 60


# dev/67-9 (DEC-054): the Simulation Mode driver — one transition function,
# step and auto cannot diverge; every state persists before it is emitted.
_SIMULATE_STALE_SECONDS = 15 * 60


# An auto run is bounded by construction: every action either advances one
# ref's state machine or pauses — this cap is a runaway backstop only.
_SIMULATE_MAX_ACTIONS = 500


# dev/67-7: bounded self-correction — an initial generation plus corrective
# regenerations, each re-validated by actually running the dataflow.
#
# dev/127: the bound used to be a hard, unconfigurable 2 (three attempts), and
# the owner's failing batch spent it in 25 SECONDS against a 300 s sandbox
# timeout and a 45-minute batch deadline: the loop stopped for want of a round
# with both budgets essentially untouched. It is now a round cap AND a per-node
# wall budget, whichever binds first, both env-overridable on the
# ``exec_timeout_s`` pattern (an unusable value falls back rather than raising).
# dev/128 (owner instruction): "change the fix attempts to 10 and 15 mins at
# max". The knob is stated in ATTEMPTS, the way the instruction and the failure
# sentence both read, rather than in corrections-after-the-first.
#
# dev/129 (the same day, refined): "the validation runtime should keep trying to
# solve for at least 15 mins, with many retries as possible". A failing round
# takes seconds, so an attempt cap of ten stopped the loop with fourteen
# minutes unspent. The default cap therefore sits ABOVE what a quarter hour
# affords — the CLOCK is the bound, and `stoppedBy` reports `budget` in the
# normal case — while the knob stays a real cap for a deployment (or a test)
# that wants a tighter one.
DEFAULT_SOLVE_ATTEMPTS = 40


DEFAULT_SOLVE_NODE_BUDGET_S = 15 * 60


# dev/131 (owner instruction): "The DFB must continue to manage the data flow
# until the user requests to stop by pressing a button, or until a timeout of 15
# minutes occurs." That is the SESSION's budget — the batch used to make one
# pass and exit (thirteen seconds, in the owner's dataflow `224d23a2`), leaving
# a node that was one dataset selection away from finishing.
DEFAULT_SOLVE_SESSION_DEADLINE_S = 15 * 60


def _positive_int_env(name: str, default: int) -> int:

    raw = _os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value > 0 else default


def solve_max_attempts() -> int:
    """``CURIO_SOLVE_MAX_ATTEMPTS`` — how many times the loop may try, counting
    the first generation (dev/128: the owner's ten)."""
    return _positive_int_env("CURIO_SOLVE_MAX_ATTEMPTS", DEFAULT_SOLVE_ATTEMPTS)


def solve_correction_rounds() -> int:
    """Corrections after the first generation — ``solve_max_attempts() - 1``,
    kept as its own reading because that is what the loop's docstring and the
    egress budget are written in terms of."""
    return max(solve_max_attempts() - 1, 0)


def solve_session_deadline_s() -> int:
    """``CURIO_SOLVE_SESSION_DEADLINE`` — how long ONE Solve session keeps
    managing the dataflow before it gives the time back (dev/131). The user's
    Stop ends it sooner; nothing else does while work remains."""
    return _positive_int_env(
        "CURIO_SOLVE_SESSION_DEADLINE", DEFAULT_SOLVE_SESSION_DEADLINE_S
    )


def solve_node_budget_s() -> int:
    """``CURIO_SOLVE_NODE_BUDGET`` — the wall-clock budget one node's repair
    loop may spend (dev/128: the owner's fifteen minutes). Checked at round
    BOUNDARIES: a round already running is never killed (its own sandbox
    timeout bounds it), but no new round starts past the budget."""
    return _positive_int_env("CURIO_SOLVE_NODE_BUDGET", DEFAULT_SOLVE_NODE_BUDGET_S)


#: The widest the loop may ever go, whatever the env says — the trail, the
#: transcript part and the egress budget are all sized from it. dev/129: the
#: owner's instruction is that TIME is the bound ("keep trying to solve for at
#: least 15 mins, with many retries as possible"), so this is a safety net
#: rather than the normal stop: sized so that a quarter hour of seconds-long
#: rounds cannot exhaust it by accident, and so that a typo in the env cannot
#: run one node forever.
MAX_SOLVE_ATTEMPTS = 40


#: dev/127: how far the walk looks through nodes that produced no artifact of
#: their own (a data pool, a simple view) before giving up.
_UPSTREAM_WALK_MAX_DEPTH = 4


_UPSTREAM_ROWS_MAX = 12


#: dev/115 F6 closure (2026-09-09): a run's egress budget describes what the
#: run legitimately does — every external candidate row the card may carry,
#: each allowed one redirect (a normal answer, not a cost the user should read
#: as "refused — budget spent"). ``egress.MAX_CALLS_PER_RUN`` stays the bound
#: on the MODEL's own web.fetch/web.search calls, a different budget.
_RUN_EGRESS_CALLS = content._CANDIDATES_MAX_ROWS_PER_LANE * 2


#: dev/118 (DEC-075): a Solve batch's wall-clock budget. Every node may cost
#: up to three rounds of a sandbox run each; the budget is what stops a wide
#: plan from running past any reasonable wait — what it did not reach reverts
#: to ``pending`` with the reason, and Retry continues from there.
DEFAULT_SOLVE_BATCH_DEADLINE_S = 45 * 60


def solve_batch_deadline_s() -> int:
    """``CURIO_SOLVE_BATCH_DEADLINE`` in seconds; an unusable value falls back
    to the default (the ``exec_timeout_s`` pattern)."""

    raw = _os.environ.get("CURIO_SOLVE_BATCH_DEADLINE")
    if raw is None or not str(raw).strip():
        return DEFAULT_SOLVE_BATCH_DEADLINE_S
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_SOLVE_BATCH_DEADLINE_S
    return value if value > 0 else DEFAULT_SOLVE_BATCH_DEADLINE_S


#: dev/131: how long the session pauses between two passes that changed
#: nothing — long enough for a user to answer, short enough to pick up their
#: answer promptly, and always stop-aware. Env-overridable so a test suite can
#: run a whole session without sleeping.
DEFAULT_SOLVE_SESSION_WAIT_S = 10


#: A hard bound on passes, so a clock that misbehaves cannot spin forever.
_SOLVE_MAX_PASSES = 200


def solve_session_wait_s() -> int:
    """``CURIO_SOLVE_SESSION_WAIT`` — the pause between two passes that changed
    nothing (dev/131)."""
    return _positive_int_env("CURIO_SOLVE_SESSION_WAIT", DEFAULT_SOLVE_SESSION_WAIT_S)


#: dev/116: the verified loop's own egress budget — per failed round up to five
#: real requests (the gate's probe, the composed request and its redirect, the
#: keyed probe), over the first round plus the corrections, with slack.
_LOOP_EGRESS_CALLS = 4 * DEFAULT_SOLVE_ATTEMPTS + 2


_VALIDATE_STALE_SECONDS = 15 * 60


#: dev/115: how many URLs a failed round probes for the correction's evidence.
_CORRECTION_URL_PROBES = 2


#: dev/115: bounded attempt-trail fields (the card renders them inert).
_ATTEMPT_DETAIL_CHARS = 300


_ATTEMPT_STDERR_CHARS = 1200


#: dev/127: the candidate a failed round actually ran, kept ON the attempt so
#: the transcript can show what was tried. Bounded — a trail is a record, not
#: a copy of the project (a five-round trail costs tens of KB, not MB).
_ATTEMPT_CODE_CHARS = 4000


_CODE_TRUNCATION_MARKER = "\n… [truncated: the attempt's code exceeded the trail's bound]"


#: dev/127: how many repeated candidates before the correction ESCALATES.
#: dev/116 tells the model it repeated itself and lets it try again; dev/129
#: keeps the loop going (the owner's "as many retries as possible") but makes
#: each repeat louder, and stops only at the hard count — a stuck model must
#: not spend a quarter hour of provider calls on copies.
_MAX_REPEATED_ATTEMPTS = 2


_MAX_REPEATED_ATTEMPTS_HARD = 8


#: dev/127: how many nodes' attempt trails ride ONE Solve turn. Beyond this the
#: card names how many were elided; each is still readable in its own node's
#: agent chat.
_MAX_ATTEMPT_PARTS = 8


#: How many consecutive repeat-only passes a node gets before the session
#: stops re-attempting it: the builder is handing back the code that already
#: failed, so another pass would spend a provider call to learn the same
#: thing. Its diagnosis and trail stay; the session moves on to what can
#: progress (and ends "blocked" when nothing can).
_MAX_WEAK_PASSES = 3


#: How many attempt rows one node's trail keeps across a whole session. The
#: transcript part shows the last few (dev/127's cap); this is the record.
_MAX_TRAIL_ATTEMPTS = 40


_PROSE_DECLINE_MAX_CHARS = 400
