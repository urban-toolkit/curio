"""The dataflow run tables: what a run records, what it may change, how long it
is kept, and that it goes with its dataflow.

``runs`` is imported inside each test, so a checkout without it fails each test
on its own instead of failing the whole collection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _project(db, user, name="Run project", **fields):
    from utk_curio.backend.app.projects.models import Project

    project = Project(
        user_id=user.id, name=name, slug=name.lower().replace(" ", "-"),
        folder_path="/nowhere", **fields,
    )
    db.session.add(project)
    db.session.commit()
    return project


def _run(project, user, **fields):
    from utk_curio.backend.app.runs import repositories as runs

    fields.setdefault("trigger", "all")
    return runs.create_run(project_id=project.id, user_id=user.id, **fields)


def _age(db, run, days):
    run.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.session.commit()


def _step_count(db, run_id):
    from utk_curio.backend.app.runs.models import DataflowRunStep

    return db.session.query(DataflowRunStep).filter_by(run_id=run_id).count()


class TestARun:
    def test_it_starts_queued_with_a_pending_step_per_node_in_level_order(self, db, user_and_token):
        user, _ = user_and_token
        project = _project(db, user)
        run = _run(project, user, spec_revision=3, boot_id="boot-1", steps=[
            {"node_id": "chart", "label": "Chart", "node_type": "curio.builtin/vis-vega",
             "level": 1, "role": "browser"},
            {"node_id": "load", "label": "Load", "node_type": "curio.builtin/data-loading",
             "level": 0},
        ])

        assert run.status == "queued" and run.whole_dataflow
        assert run.spec_revision == 3 and run.boot_id == "boot-1"
        assert [s.node_id for s in run.steps] == ["load", "chart"]
        assert [s.status for s in run.steps] == ["pending", "pending"]
        assert [s.role for s in run.steps] == ["run", "browser"]

    def test_a_run_up_to_one_node_is_the_other_kind(self, db, user_and_token):
        user, _ = user_and_token
        run = _run(_project(db, user), user, trigger="node", target_node_id="load")
        assert not run.whole_dataflow

    def test_unknown_triggers_roles_and_statuses_are_refused(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        with pytest.raises(ValueError):
            _run(project, user, trigger="cron")
        with pytest.raises(ValueError):
            _run(project, user, steps=[{"node_id": "n", "role": "elsewhere"}])
        run = _run(project, user, steps=[{"node_id": "n"}])
        with pytest.raises(ValueError):
            runs.update_run(run.id, status="paused")
        with pytest.raises(ValueError):
            runs.update_step(run.id, "n", status="paused")

    def test_only_outcome_and_timing_can_change(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        run = _run(_project(db, user), user, steps=[{"node_id": "n"}])
        with pytest.raises(ValueError):
            runs.update_run(run.id, project_id="another")
        with pytest.raises(ValueError):
            runs.update_step(run.id, "n", node_id="m")

    def test_a_step_keeps_the_end_of_its_output(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        run = _run(_project(db, user), user, steps=[{"node_id": "n"}])
        long_stderr = "x" * 9000 + "ZeroDivisionError: division by zero"
        step = runs.update_step(
            run.id, "n", status="error", stderr_tail=long_stderr, stdout_tail="ran",
            duration_ms=12,
        )
        assert len(step.stderr_tail) == runs.TAIL_CHARS
        assert step.stderr_tail.endswith("ZeroDivisionError: division by zero")
        assert step.stdout_tail == "ran" and step.status == "error"

    def test_an_unknown_run_or_step_is_not_found(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        run = _run(_project(db, user), user, steps=[{"node_id": "n"}])
        with pytest.raises(runs.NotFoundError):
            runs.update_run("no-such-run", status="running")
        with pytest.raises(runs.NotFoundError):
            runs.update_step(run.id, "ghost", status="running")


class TestListing:
    def test_a_dataflows_runs_come_newest_first_and_filter_by_kind(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        first = _run(project, user)
        node = _run(project, user, trigger="node", target_node_id="n")
        last = _run(project, user)
        _age(db, first, 3)
        _age(db, node, 2)
        _age(db, last, 1)

        assert [r.id for r in runs.list_project_runs(project.id)] == [last.id, node.id, first.id]
        assert [r.id for r in runs.list_project_runs(project.id, whole_dataflow=True)] == [last.id, first.id]
        assert [r.id for r in runs.list_project_runs(project.id, whole_dataflow=False)] == [node.id]

    def test_a_users_runs_filter_by_status_and_skip_other_users(self, db, user_and_token, guest_user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        other, _ = guest_user_and_token
        running = _run(_project(db, user), user)
        _run(_project(db, user, name="Second"), user)
        _run(_project(db, other, name="Theirs"), other)
        runs.update_run(running.id, status="running")

        mine = runs.list_user_runs(user.id)
        assert len(mine) == 2 and all(r.user_id == user.id for r in mine)
        assert [r.id for r in runs.list_user_runs(user.id, status="running")] == [running.id]


class TestRetention:
    def _fill(self, db, project, user, count, **fields):
        return [_run(project, user, steps=[{"node_id": "n"}], **fields) for _ in range(count)]

    def test_the_51st_run_older_than_30_days_goes_with_its_steps(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs
        from utk_curio.backend.app.runs.models import DataflowRun

        user, _ = user_and_token
        project = _project(db, user)
        oldest, *rest = self._fill(db, project, user, runs.KEEP_PER_KIND + 1)
        _age(db, oldest, runs.RETENTION_DAYS + 1)
        oldest_id = oldest.id

        assert runs.prune_project_runs(project.id) == 1
        assert db.session.get(DataflowRun, oldest_id) is None
        assert _step_count(db, oldest_id) == 0, "a pruned run's steps were left behind"
        assert len(runs.list_project_runs(project.id, limit=100)) == runs.KEEP_PER_KIND

    def test_the_51st_run_younger_than_30_days_stays(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        oldest, *rest = self._fill(db, project, user, runs.KEEP_PER_KIND + 1)
        _age(db, oldest, runs.RETENTION_DAYS - 1)

        assert runs.prune_project_runs(project.id) == 0
        assert len(runs.list_project_runs(project.id, limit=100)) == runs.KEEP_PER_KIND + 1

    def test_the_newest_50_stay_however_old(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        for run in self._fill(db, project, user, runs.KEEP_PER_KIND):
            _age(db, run, 400)

        assert runs.prune_project_runs(project.id) == 0

    def test_each_kind_keeps_its_own_50(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        node_run, = self._fill(db, project, user, 1, trigger="node", target_node_id="n")
        _age(db, node_run, 400)
        for run in self._fill(db, project, user, runs.KEEP_PER_KIND):
            _age(db, run, 1)

        # 51 runs in all, but the old one is the only run of its kind.
        assert runs.prune_project_runs(project.id) == 0
        assert [r.id for r in runs.list_project_runs(project.id, whole_dataflow=False)] == [node_run.id]

    def test_an_active_run_is_never_pruned(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs

        user, _ = user_and_token
        project = _project(db, user)
        oldest, *rest = self._fill(db, project, user, runs.KEEP_PER_KIND + 1)
        runs.update_run(oldest.id, status="running")
        _age(db, oldest, 400)

        assert runs.prune_project_runs(project.id) == 0

    def test_a_new_run_prunes_its_dataflow(self, db, user_and_token):
        from utk_curio.backend.app.runs import repositories as runs
        from utk_curio.backend.app.runs.models import DataflowRun

        user, _ = user_and_token
        project = _project(db, user)
        oldest, *rest = self._fill(db, project, user, runs.KEEP_PER_KIND)
        _age(db, oldest, runs.RETENTION_DAYS + 1)
        oldest_id = oldest.id

        _run(project, user)  # the 51st

        assert db.session.get(DataflowRun, oldest_id) is None


class TestRunsGoWithTheirDataflow:
    def test_deleting_a_project_deletes_its_runs_and_steps(self, db, user_and_token):
        from utk_curio.backend.app.projects import services
        from utk_curio.backend.app.runs.models import DataflowRun

        user, _ = user_and_token
        project = _project(db, user)
        kept = _project(db, user, name="Kept")
        doomed = _run(project, user, steps=[{"node_id": "a"}, {"node_id": "b"}])
        survivor = _run(kept, user, steps=[{"node_id": "a"}])
        doomed_id, survivor_id = doomed.id, survivor.id

        services.delete_project(user, project.id)

        assert db.session.query(DataflowRun).filter_by(id=doomed_id).count() == 0
        assert _step_count(db, doomed_id) == 0
        assert db.session.query(DataflowRun).filter_by(id=survivor_id).count() == 1
        assert _step_count(db, survivor_id) == 1

    def test_an_expired_guest_project_takes_its_runs_with_it(self, app, db, guest_user_and_token):
        from utk_curio.backend.app.projects.tasks import cleanup_expired_guest_projects
        from utk_curio.backend.app.runs.models import DataflowRun

        guest, _ = guest_user_and_token
        project = _project(
            db, guest, name="Old guest work",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        run = _run(project, guest, steps=[{"node_id": "a"}])
        run_id = run.id

        assert cleanup_expired_guest_projects(app) == 1

        assert db.session.query(DataflowRun).filter_by(id=run_id).count() == 0
        assert _step_count(db, run_id) == 0
