"""A dataflow run and its per-node steps, and the outputs a dashboard
viewer's runs keep (:class:`DashboardStepOutput`).

A run is one press of Run All (no target), of a node's play button
(``target_node_id`` set), or an automatic run after a widget or Parameter
change (``target_node_ids``: the nodes the change touched and those below
them, #845), executed on the server. Each node it touches has a step that says
what happened to it, when, and what it printed.

Deleting a project deletes its runs: the backref below cascades through the
ORM, because SQLite does not enforce foreign keys here. ``create_app`` imports
this module so the backref exists before any project is deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from utk_curio.backend.extensions import db

TRIGGERS = ("all", "node", "rerun", "auto")
RUN_STATUSES = (
    "queued", "running", "succeeded", "failed", "needs_canvas", "cancelled", "interrupted",
)
ACTIVE_RUN_STATUSES = ("queued", "running")
#: What a run does with a node (``execution/run_plan.node_role``).
STEP_ROLES = ("run", "forward", "browser", "missing")
STEP_STATUSES = (
    "pending", "running", "ok", "error", "skipped", "forwarded", "browser",
    "waiting", "cancelled", "interrupted",
)


def _uuid() -> str:
    return str(uuid4())


def _now():
    return datetime.now(timezone.utc)


def naive_utc_now():
    """Now, as naive UTC: what a DateTime column hands back, so a cutoff
    compared in SQL means the same on SQLite and Postgres."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DataflowRun(db.Model):
    __tablename__ = "dataflow_run"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    trigger = db.Column(db.String(16), nullable=False)
    target_node_id = db.Column(db.String(255), nullable=True)
    # A run of several nodes: their ids, as a JSON list.
    target_node_ids = db.Column(db.Text, nullable=True)
    rerun_of = db.Column(db.String(36), nullable=True)
    spec_revision = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="queued")
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    ok_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    skipped_count = db.Column(db.Integer, nullable=False, default=0)
    waiting_count = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text, nullable=True)
    # Which backend process ran it; a run left active by an earlier process
    # was interrupted by the restart.
    boot_id = db.Column(db.String(36), nullable=True)

    project = db.relationship(
        "Project",
        backref=db.backref("runs", cascade="all, delete-orphan"),
    )
    steps = db.relationship(
        "DataflowRunStep",
        backref="run",
        cascade="all, delete-orphan",
        order_by=lambda: (DataflowRunStep.level, DataflowRunStep.id),
    )

    __table_args__ = (
        db.Index("ix_dataflow_run_project_created", "project_id", "created_at"),
        db.Index("ix_dataflow_run_user_created", "user_id", "created_at"),
    )

    @property
    def target_ids(self) -> list:
        """The nodes a run of several nodes ran; empty for any other run."""
        return json.loads(self.target_node_ids) if self.target_node_ids else []

    @property
    def whole_dataflow(self) -> bool:
        return not self.target_node_id and not self.target_node_ids

    def __repr__(self):
        return f"<DataflowRun {self.id!r} {self.status!r}>"


class DataflowRunStep(db.Model):
    __tablename__ = "dataflow_run_step"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(36), db.ForeignKey("dataflow_run.id"), nullable=False)
    node_id = db.Column(db.String(255), nullable=False)
    label = db.Column(db.Text, nullable=True)
    node_type = db.Column(db.String(255), nullable=True)
    level = db.Column(db.Integer, nullable=False, default=0)
    role = db.Column(db.String(16), nullable=False, default="run")
    status = db.Column(db.String(16), nullable=False, default="pending")
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    output_path = db.Column(db.Text, nullable=True)
    output_type = db.Column(db.String(64), nullable=True)
    installed_dataset_id = db.Column(db.String(255), nullable=True)
    code_sha256 = db.Column(db.String(64), nullable=True)
    stdout_tail = db.Column(db.Text, nullable=True)
    stderr_tail = db.Column(db.Text, nullable=True)
    skip_reason = db.Column(db.Text, nullable=True)
    # The library the step's code could not import, as the reply's
    # ``missingModule`` (JSON), so a canvas opened later offers its install.
    missing_module = db.Column(db.Text, nullable=True)
    # The outputs the run could not install in the Data Catalog, as a save's
    # ``dataset_install_warnings`` lists them (JSON).
    install_warnings = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("run_id", "node_id", name="uq_dataflow_run_step_node"),
    )

    def __repr__(self):
        return f"<DataflowRunStep {self.run_id!r} {self.node_id!r} {self.status!r}>"


class DashboardStepOutput(db.Model):
    """One output a dashboard viewer's run made (``runs/viewer.py``), kept so
    that the next viewer who picks the same values gets it with no run.

    *step_key* hashes what made it: the step's code with the values written
    in, its inputs, the owner's packages and the datasets the code reads, and
    Curio's version. Its artifacts carry a session of their own
    (``common/dashboard_sessions.py``), which the sandbox forgets when the
    entry goes. An entry built on a result a viewer's browser sent is
    *private_to* that run: only its tab reads it. Deleting the project deletes
    its entries.
    """

    __tablename__ = "dashboard_step_output"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id"), nullable=False)
    node_id = db.Column(db.String(255), nullable=False)
    step_key = db.Column(db.String(64), nullable=False)
    session_id = db.Column(db.String(64), nullable=False)
    # The output as the sandbox answered it (JSON), and its artifact id.
    output = db.Column(db.Text, nullable=False)
    output_path = db.Column(db.String(255), nullable=False)
    # Every artifact its session made (JSON): the output's own and, for a
    # node that hands on several values, theirs. A read names one of these.
    artifact_ids = db.Column(db.Text, nullable=False, default="[]")
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    # A digest of the run token of the one tab that may read it.
    private_to = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=naive_utc_now)
    used_at = db.Column(db.DateTime, nullable=False, default=naive_utc_now)

    project = db.relationship(
        "Project",
        backref=db.backref("dashboard_outputs", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.Index("ix_dashboard_step_output_key", "project_id", "step_key"),
        db.Index("ix_dashboard_step_output_path", "project_id", "output_path"),
        db.Index("ix_dashboard_step_output_created", "created_at"),
    )

    def __repr__(self):
        return f"<DashboardStepOutput {self.project_id!r} {self.node_id!r} {self.step_key[:8]!r}>"
