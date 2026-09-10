"""dev/131 (owner correction): a retry carries the CURRENT error, not the same inputs.

*"the keep attempting it should not carry the same inputs, supossing it doesn't
depend on user's actions, it should carry the currently error that is being
given."*

Two halves. The pure part: what a re-attempt carries (the last failed
candidate and its error) and which nodes are parked on the user at all. The
loop part: seeded with that payload, round 0 asks for a CORRECTION — the child
sees the previous attempt and its traceback — instead of another blank first
draft that fails the same way.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import services as services_mod

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "<node>", line 2, in <module>\n    df = arg.head()\n'
    "AttributeError: 'list' object has no attribute 'head'\n"
)
FAILED_CODE = "df = arg.head()\nreturn df"


class TestCarryForwardPayload:
    def test_the_last_failed_attempt_is_what_a_retry_carries(self):
        result = {
            "status": "failed",
            "attempts": [
                {"round": 1, "verdict": "fail", "kind": "input-contract",
                 "detail": "arg is a list", "code": "df = arg\nreturn df"},
                {"round": 2, "verdict": "fail", "kind": "execution-error",
                 "detail": "AttributeError", "stderrTail": TRACEBACK, "code": FAILED_CODE},
            ],
        }
        carry = services_mod._carry_forward_error(result)
        assert carry["code"] == FAILED_CODE
        assert "'list' object has no attribute 'head'" in carry["error"]
        assert carry["kind"] == "execution-error"

    def test_the_stderr_tail_is_preferred_over_the_short_detail(self):
        carry = services_mod._carry_forward_error(
            {"attempts": [{"verdict": "fail", "detail": "short", "stderrTail": TRACEBACK}]}
        )
        assert carry["error"] == TRACEBACK.strip()

    def test_a_passing_attempt_is_skipped_and_a_prose_decline_carries_no_code(self):
        carry = services_mod._carry_forward_error({"attempts": [
            {"verdict": "fail", "kind": "source-missing", "detail": "I cannot invent a URL",
             "code": "I cannot invent a URL", "codeIsProse": True},
            {"verdict": "pass", "detail": "", "code": "return arg[0]"},
        ]})
        assert carry["code"] == ""  # never handed back as code to correct
        assert carry["error"] == "I cannot invent a URL"

    def test_nothing_to_carry_when_there_are_no_attempts_or_no_error(self):
        assert services_mod._carry_forward_error(None) is None
        assert services_mod._carry_forward_error({"status": "pending"}) is None
        assert services_mod._carry_forward_error(
            {"attempts": [{"verdict": "fail", "detail": "  "}]}
        ) is None


class TestWhoIsParkedOnTheUser:
    def test_a_dataset_selection_or_a_missing_key_awaits_the_user(self):
        assert services_mod._awaits_user_action(
            {"status": "pending", "remedy": {"kind": "dataset-selection", "attachmentId": "a1"}}
        ) is True
        assert services_mod._awaits_user_action(
            {"status": "failed", "remedy": {"kind": "connection-key", "host": "api.census.gov"}}
        ) is True

    def test_an_error_the_agent_can_act_on_does_not(self):
        assert services_mod._awaits_user_action({"status": "failed", "error": "boom"}) is False
        assert services_mod._awaits_user_action(None) is False
        # dev/116's saved-key remedy is the agent's to use, not the user's to supply.
        assert services_mod._awaits_user_action(
            {"remedy": {"kind": "use-connection-key", "host": "api.census.gov", "name": "census"}}
        ) is False


class TestTheLoopStartsFromTheCarriedError:
    def _run(self, app, carry):
        from utk_curio.backend.tests.test_agents.test_verified_rounds import CA, _Exec, _rounds

        node = {"id": "n1", "type": CA, "goal": "head of the frame", "content": ""}
        return _rounds(
            app, node, replies=["df = arg[0]\nreturn df.head()"],
            exec_fn=_Exec(), carry_forward=carry,
        )

    def test_round_zero_is_a_correction_and_the_trail_says_so(self, app, tmp_curio):
        events, outcome, inputs = self._run(
            app, {"code": FAILED_CODE, "error": TRACEBACK, "kind": "execution-error"}
        )
        assert outcome["verdict"] == "pass"
        assert inputs[0]["previousAttempt"].startswith("df = arg.head()")
        assert "'list' object has no attribute 'head'" in inputs[0]["validationError"]
        assert any(
            line.startswith("carrying forward the previous attempt's error")
            for line in outcome["roundsTrace"]
        )

    def test_an_error_with_no_code_still_rides(self, app, tmp_curio):
        events, outcome, inputs = self._run(
            app, {"code": "", "error": "the builder declined: no source", "kind": "source-missing"}
        )
        assert "previousAttempt" not in inputs[0]
        assert inputs[0]["validationError"] == "the builder declined: no source"

    def test_an_empty_carry_forward_changes_nothing(self, app, tmp_curio):
        events, outcome, inputs = self._run(app, {"code": "", "error": "   "})
        assert "validationError" not in inputs[0]
        assert not any("carrying forward" in line for line in outcome["roundsTrace"])


class TestWhatAPassIsAllowedToOverwrite:
    def test_a_repeat_only_pass_is_weak_and_a_real_error_is_not(self):
        assert services_mod._weak_failure({"attempts": [
            {"verdict": "fail", "kind": "repeated-attempt", "detail": "same code"},
        ]}) is True
        assert services_mod._weak_failure({"attempts": [
            {"verdict": "fail", "kind": "infrastructure", "detail": "sandbox is down"},
        ]}) is True
        assert services_mod._weak_failure({"attempts": [
            {"verdict": "fail", "kind": "repeated-attempt", "detail": "same code"},
            {"verdict": "fail", "kind": "execution-error", "stderrTail": TRACEBACK},
        ]}) is False
        assert services_mod._weak_failure({"attempts": []}) is False

    def test_a_sandbox_outage_is_never_carried_as_code_to_fix(self):
        # The code never ran: handing it back as "the previous attempt" would
        # make the repeat detector fail the node for being right.
        assert services_mod._carry_forward_error({"attempts": [
            {"verdict": "fail", "kind": "infrastructure", "detail": "sandbox is down",
             "code": FAILED_CODE},
        ]}) is None
        assert services_mod._carry_forward_error({"attempts": [
            {"verdict": "fail", "kind": "precondition", "detail": "the slice has a cycle"},
        ]}) is None

    def test_a_repeat_notice_yields_to_the_error_behind_it(self):
        carry = services_mod._carry_forward_error({"attempts": [
            {"verdict": "fail", "kind": "execution-error", "stderrTail": TRACEBACK,
             "code": FAILED_CODE},
            {"verdict": "fail", "kind": "repeated-attempt", "detail": "same code again",
             "code": FAILED_CODE},
        ]})
        assert "'list' object has no attribute 'head'" in carry["error"]
        assert carry["kind"] == "execution-error"


class TestASessionPassCarriesTheErrorForward:
    """End to end: pass 2 must not repeat pass 1's blank inputs. The child sees
    the failure the node is stuck on, the whole trail is kept across passes,
    and a builder that keeps handing back the same code stops the spin instead
    of burning the whole budget on it."""

    def test_the_second_pass_is_handed_the_first_pass_error_and_the_trail_grows(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        import utk_curio.backend.tests.test_agents.test_verified_rounds as vr

        helper = vr.TestVerifiedSolve()
        user, token = user_and_token
        # Every candidate fails at run time: pass 1 exhausts its rounds, and
        # later passes keep attempting — the owner's requirement — rather than
        # ending the session after one pass.
        ctx = helper._setup(
            client, user, token, monkeypatch, with_stats=False,
            dl_replies=[
                vr.TestVerifiedSolve.LOADER.replace("return df", f"always_bad({i})\nreturn df")
                for i in range(3)
            ],
            exec_outcomes={"always_bad": "Traceback: NameError: always_bad"},
        )
        body = helper._solve(client, token, ctx, verify=True)
        load = body["results"][ctx["load"]]
        assert body["passes"] > 1  # the session kept managing the dataflow
        kinds = [a.get("kind") for a in load["attempts"]]
        # Pass 1's real failures AND the later passes' rounds are both kept.
        assert "execution-error" in kinds and len(load["attempts"]) > 3
        # The diagnosis names what the node is stuck on, not how the loop ended.
        assert "NameError: always_bad" in load["error"]
        # Every later pass was handed the previous error: the child's frames say so.
        frames = [f for f in ctx["dl_calls"] if "validationError" in f]
        assert frames and any("always_bad" in f for f in frames)
        # And the spin is bounded: a builder repeating itself does not get the
        # whole budget (three repeat-only passes, then the session moves on).
        repeat_passes = sum(1 for k in kinds if k == "repeated-attempt")
        assert repeat_passes <= 3 * services_mod._MAX_WEAK_PASSES
        assert helper._node_content(ctx, ctx["load"]) == ""  # nothing failing was written
