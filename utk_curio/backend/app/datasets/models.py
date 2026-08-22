"""Per-user dataset index: a queryable mirror of the user-store manifests.

The account dataset store (``.curio/users/<user_key>/datasets/<id>@<major>/``)
is the source of truth for dataset *content*. This table mirrors each store
dir's ``manifest.json`` so catalog reads become keyed lookups instead of a scan
that parses every manifest on every request.

The index is a **derived cache**: it is refreshed from disk by
``repositories.index.reconcile`` (a stat-based sweep) and the catalog still
falls back to reading a manifest directly when a store dir has no row. A stale
or missing row can therefore never hide a user's dataset — worst case the
listing is as slow as it was before the index existed.

Only the per-user store is indexed. The shared hub tree
(``<repo_root>/datasets/``) is git-managed and shared between users, workspace
files appear out-of-band by design, and live node outputs are ephemeral — those
tiers stay scanned.
"""

from datetime import datetime, timezone

from utk_curio.backend.extensions import db


def _now():
    return datetime.now(timezone.utc)


class DatasetIndexEntry(db.Model):
    __tablename__ = "dataset_index_entry"

    id = db.Column(db.Integer, primary_key=True)

    # ── Identity ─────────────────────────────────────────────────────────────
    # On-disk store owner. Deliberately NOT a FK to user.id: the shared guest
    # store is keyed by the literal "guest" (see projects.services._user_dir_key),
    # which is not a user id. Rows are scoped by this string exactly as the
    # filesystem is.
    user_key = db.Column(db.String(64), nullable=False)
    dataset_id = db.Column(db.String(255), nullable=False)
    dir_name = db.Column(db.String(255), nullable=False)
    major = db.Column(db.Integer, nullable=False, default=1)
    # "imported" | "computed" — derived from the dir-name prefix, matching
    # UserDatasetRepository's classification.
    origin = db.Column(db.String(32), nullable=False)

    # ── Manifest metadata mirror ─────────────────────────────────────────────
    title = db.Column(db.Text, nullable=False, default="")
    version = db.Column(db.String(32), nullable=True)
    format = db.Column(db.String(32), nullable=False)
    description = db.Column(db.Text, nullable=True)
    publisher = db.Column(db.Text, nullable=True)
    license = db.Column(db.Text, nullable=True)
    # JSON-encoded list[str] / dict — mirrors the manifest shape verbatim so the
    # row can rebuild a catalog item without re-reading the file.
    tags_json = db.Column(db.Text, nullable=True)
    schema_json = db.Column(db.Text, nullable=True)
    data_file = db.Column(db.Text, nullable=False)
    source_label = db.Column(db.Text, nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    row_count = db.Column(db.Integer, nullable=True)
    feature_count = db.Column(db.Integer, nullable=True)
    group_id = db.Column(db.String(255), nullable=True)
    layer_name = db.Column(db.String(255), nullable=True)

    # ISO strings, stored exactly as the manifest carries them (the catalog item
    # passes them straight through to the client, so parsing/reformatting here
    # would only introduce drift).
    created_at_iso = db.Column(db.String(40), nullable=True)
    updated_at_iso = db.Column(db.String(40), nullable=True)
    source_updated_at_iso = db.Column(db.String(40), nullable=True)

    # ── Lineage (computed datasets) ───────────────────────────────────────────
    producer_node_id = db.Column(db.String(255), nullable=True)
    producer_node_type = db.Column(db.String(255), nullable=True)
    producer_dataflow_id = db.Column(db.String(64), nullable=True)
    producer_dataflow_name = db.Column(db.Text, nullable=True)
    upstream_inputs_json = db.Column(db.Text, nullable=True)

    # ── Freshness ─────────────────────────────────────────────────────────────
    # stat() pair of the mirrored manifest.json. reconcile() re-parses a dir only
    # when this pair changed, so an unchanged store costs one readdir + stat per
    # dir and zero JSON parses.
    manifest_mtime_ns = db.Column(db.BigInteger, nullable=True)
    manifest_size = db.Column(db.Integer, nullable=True)
    indexed_at = db.Column(db.DateTime, default=_now, onupdate=_now, nullable=False)

    # Mirrors migration d4e5f6a7b8c9. Both uniques are per store owner: a dataset
    # id and a dir name are unique within one user's store, never globally (two
    # users can each hold the same hub dataset).
    __table_args__ = (
        db.UniqueConstraint("user_key", "dataset_id", name="uq_dataset_index_user_id"),
        db.UniqueConstraint("user_key", "dir_name", name="uq_dataset_index_user_dir"),
        db.Index("ix_dataset_index_user_origin", "user_key", "origin"),
    )

    def __repr__(self):
        return f"<DatasetIndexEntry {self.user_key!r} {self.dataset_id!r}>"
