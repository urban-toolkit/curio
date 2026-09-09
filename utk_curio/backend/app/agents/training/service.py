"""The one seam that touches both the store and the endpoint (dev/122).

Everything else in this package is pure. This module resolves the account's
provider config, builds the set from the fixtures on disk, writes the record,
talks to the endpoint, and folds its answers back — in that order, because the
order is a contract: the consent record is written and flushed *before* the
first byte is uploaded (dev/87: every export appends an audit record before the
content is served).

It deliberately owns no thread and no queue. The provider owns the job.
"""

from __future__ import annotations

import json
from typing import Mapping

from utk_curio.backend.app.agents import builtin, content as content_mod
from utk_curio.backend.app.agents import model_catalog, providers, source_grounding
from utk_curio.backend.app.agents.evaluation.fixtures import load_fixtures
from utk_curio.backend.app.agents.evaluation.report import scrub
from utk_curio.backend.app.agents.training import consent as consent_mod
from utk_curio.backend.app.agents.training import dataset as dataset_mod
from utk_curio.backend.app.agents.training import gate as gate_mod
from utk_curio.backend.app.agents.training import records as records_mod

#: The suffix a trained model carries, so it is recognisable in the endpoint's
#: own console as something Curio produced.
MODEL_SUFFIX = "curio-plans"


class TrainingServiceError(Exception):
    """Carries the HTTP status the routes should answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _provider_config(user):
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    try:
        return resolve_provider_config(user, require_model=False)
    except ProviderConfigError as exc:
        raise TrainingServiceError(str(exc), 400) from exc


def _provider_identity(config) -> dict:
    return {
        "apiType": config.api_type or "",
        "baseUrlHost": consent_mod.host_of(config.base_url, config.api_type),
    }


def capability(user, user_key: str, *, refresh: bool = True) -> dict:
    """What this account's endpoint says about fine-tuning, live or replayed.

    Mirrors ``provider-models``: a live answer is recorded; when a live answer
    is impossible the recording is served *labelled with the date it was true*,
    because presenting a recording as the present tense is how someone ends up
    staring at a feature their endpoint does not have.
    """
    config = _provider_config(user)
    identity = _provider_identity(config)
    if refresh:
        result = providers.fine_tuning_capabilities(config)
        payload = result.as_dict()
        model_catalog.remember_capability(
            user_key, config.api_type, config.base_url, payload
        )
        return {**payload, "source": "live", "seenAt": None, "provider": identity}
    remembered, seen_at = model_catalog.remembered_capability(
        user_key, config.api_type, config.base_url
    )
    if remembered is None:
        return capability(user, user_key, refresh=True)
    return {
        **remembered,
        "probedAt": seen_at or "",
        "source": "remembered",
        "seenAt": seen_at,
        "provider": identity,
    }


def _roster_for(fixtures) -> tuple:
    """The roster block a run would carry, and its digest.

    Built from the builtin catalog plus whatever packages the eligible fixtures
    require, so the training example's system turn names the templates a real
    run against those examples would name.
    """
    from utk_curio.backend.app.agents.evaluation.report import digest_of
    from utk_curio.backend.app.agents.services import roster_block
    from utk_curio.backend.app.packages.services import (
        _catalog_manifests,
        _template_entry,
    )

    wanted = {"curio.builtin@1"}
    for fixture in fixtures:
        wanted.update(fixture.required.get("packages") or [])
    # The committed catalog, read through the packages domain's own reader —
    # so a template row here is byte-identical to the row a live run's roster
    # carries (DEC-062: one roster, one formatter).
    catalog = _catalog_manifests()
    rows: list = []
    for dir_name in sorted(wanted):
        manifest = catalog.get(dir_name)
        if manifest is None:
            continue
        for template in manifest.templates:
            rows.append(_template_entry(manifest.package_id, template))
    block = roster_block(rows)
    return block, digest_of([row["id"] for row in rows])


def build_set(*, split: str = "train"):
    """The training set for *split*, or a refusal that says why."""
    fixtures = load_fixtures()
    instruction = builtin.read_instruction_text(dataset_mod.DFB_COORD) or ""
    preamble = builtin.read_prompt_text(dataset_mod.DFB_COORD, "system")
    roster, roster_digest = _roster_for(fixtures)
    try:
        return dataset_mod.build_training_set(
            fixtures,
            split=split,
            instruction=instruction,
            preamble=preamble,
            tail=content_mod.tail_instruction(),
            roster=roster,
            roster_digest=roster_digest,
            scrub=scrub,
            credential_finder=source_grounding.credential_literals,
            parse_reply=dataset_mod.plan_target_check,
        ), fixtures
    except dataset_mod.TrainingSetRefused as refusal:
        raise TrainingServiceError(str(refusal), 409) from refusal


def preview(user, *, split: str = "train") -> dict:
    """What would be sent, for a person to read before consenting."""
    config = _provider_config(user)
    training_set, fixtures = build_set(split=split)
    licences = {
        fixture.fixture_id: dataset_mod.licence_of(fixture) or "MIT (this repository)"
        for fixture in fixtures
    }
    statement = consent_mod.statement_for(
        training_set,
        base_url=config.base_url,
        api_type=config.api_type,
        licences=licences,
    )
    return {
        "dataset": training_set.as_dict(),
        "consent": statement.as_dict(),
        "provider": _provider_identity(config),
    }


def start(
    user,
    user_key: str,
    *,
    base_model: str,
    rows_digest: str,
    confirmed: bool,
    split: str = "train",
    price_per_mtoken=None,
) -> dict:
    """Consent, then upload, then submit — in that order, and recorded so.

    Refuses a second in-flight job for the account: a fine-tune costs money and
    a double-click must not spend twice.
    """
    existing = records_mod.in_flight(user_key)
    if existing is not None:
        raise TrainingServiceError(
            f"a training job is already running ({existing.job_id}); wait for it "
            "to finish or cancel it before starting another",
            409,
        )
    if not (base_model or "").strip():
        raise TrainingServiceError(
            "name the base model to train: the endpoint reported no tunable "
            "models, so nothing can be guessed for you",
            400,
        )

    config = _provider_config(user)
    probe = providers.fine_tuning_capabilities(config)
    if not probe.supported:
        raise TrainingServiceError(probe.reason, 409)

    training_set, fixtures = build_set(split=split)
    licences = {
        fixture.fixture_id: dataset_mod.licence_of(fixture) or "MIT (this repository)"
        for fixture in fixtures
    }
    statement = consent_mod.statement_for(
        training_set, base_url=config.base_url, api_type=config.api_type,
        licences=licences,
    )
    try:
        granted = consent_mod.grant(
            statement, user_key=user_key, echoed_digest=rows_digest, confirmed=confirmed
        )
    except consent_mod.ConsentRefused as refusal:
        raise TrainingServiceError(str(refusal), 409) from refusal

    record = records_mod.TrainingRecord(
        job_id=records_mod.new_job_id(),
        provider={**_provider_identity(config), "baseModel": base_model},
        dataset=training_set.as_dict(),
        consent=granted.as_dict(),
    )
    record.append("consented", rowsDigest=granted.rows_digest, rows=granted.rows)
    # BEFORE the first byte: the record is on disk and fsynced, so a crash here
    # reads as "consented, never sent" rather than leaving a silent upload.
    records_mod.write(user_key, record)

    try:
        file_id = providers.upload_training_file(
            config,
            filename=f"{record.job_id}.jsonl",
            content=training_set.content,
        )
        record.append("uploaded", fileId=file_id, bytes=training_set.bytes_len)
        records_mod.write(user_key, record)
        job = providers.create_fine_tuning_job(
            config,
            training_file=file_id,
            base_model=base_model,
            suffix=MODEL_SUFFIX,
        )
    except providers.FineTuningUnavailable as exc:
        record.status = "failed"
        record.error = str(exc)
        record.append("error", detail=str(exc))
        records_mod.write(user_key, record)
        raise TrainingServiceError(str(exc), 502) from exc

    record.append("submitted", providerJobId=job.id, baseModel=job.base_model)
    records_mod.fold_provider_status(record, job)
    record.cost = records_mod.estimate_cost(record, price_per_mtoken)
    records_mod.write(user_key, record)
    return record.as_dict()


def _read_or_refuse(user_key: str, job_id: str):
    """Read a record, mapping a malformed id to a 400 rather than a 500.

    ``records.record_path`` validates the id before it becomes a path segment;
    the route's job is to say so in the shape a client can act on.
    """
    try:
        return records_mod.read(user_key, job_id)
    except records_mod.TrainingRecordError as exc:
        raise TrainingServiceError(str(exc), 400) from exc


def status(user, user_key: str, job_id: str, *, price_per_mtoken=None) -> dict:
    """Ask the endpoint about a job and fold the answer in.

    A terminal record is not re-asked: the provider has said its last word, and
    asking again would only add noise to the event list.
    """
    record = _read_or_refuse(user_key, job_id)
    if record is None:
        raise TrainingServiceError(f"no training job {job_id}", 404)
    if not record.provider_job_id or record.terminal:
        # A terminal job is not re-asked — the provider has said its last word
        # — but the gate is still computed, because whether this model may be
        # activated depends on the corpus as it is NOW.
        payload = record.as_dict()
        payload["gate"] = _gate_payload(user_key, record)
        return payload
    config = _provider_config(user)
    try:
        job = providers.get_fine_tuning_job(config, record.provider_job_id)
    except providers.FineTuningUnavailable as exc:
        # The record keeps its last known state; the reason travels with it
        # rather than becoming a fabricated status.
        payload = record.as_dict()
        payload["statusError"] = str(exc)
        payload["gate"] = _gate_payload(user_key, record)
        return payload
    records_mod.fold_provider_status(record, job)
    record.cost = records_mod.estimate_cost(record, price_per_mtoken)
    if job.status == "succeeded" and job.trained_model:
        model_catalog.remember_trained_model(
            user_key,
            config.api_type,
            config.base_url,
            model=job.trained_model,
            job_id=record.job_id,
            dataset_sha256=str(record.dataset.get("sha256") or ""),
            base_model=job.base_model,
        )
    records_mod.write(user_key, record)
    payload = record.as_dict()
    payload["gate"] = _gate_payload(user_key, record)
    return payload


def cancel(user, user_key: str, job_id: str) -> dict:
    """Ask the endpoint to cancel, and record what it says."""
    record = _read_or_refuse(user_key, job_id)
    if record is None:
        raise TrainingServiceError(f"no training job {job_id}", 404)
    if not record.provider_job_id:
        raise TrainingServiceError(
            "this job was never submitted, so there is nothing to cancel", 409
        )
    config = _provider_config(user)
    try:
        job = providers.cancel_fine_tuning_job(config, record.provider_job_id)
    except providers.FineTuningUnavailable as exc:
        raise TrainingServiceError(str(exc), 409) from exc
    record.append("cancelled", providerJobId=job.id)
    records_mod.fold_provider_status(record, job)
    records_mod.write(user_key, record)
    return record.as_dict()


def _set_account_model(user, model: str) -> str:
    """Point the account at *model*; return what it pointed at before.

    Writes through the users domain's own patch path — the same one AI Settings
    writes — so there is exactly one place an account's model changes, and a
    guest is refused there rather than here.
    """
    from utk_curio.backend.app.users.schemas import UserPatchIn
    from utk_curio.backend.app.users.services import patch_me

    previous = getattr(user, "llm_model", None) or ""
    try:
        patch_me(user, UserPatchIn(llm_model=model))
    except Exception as exc:  # noqa: BLE001 - AuthError carries its own status
        raise TrainingServiceError(
            f"could not change the account's model: {exc}",
            getattr(exc, "status", 400),
        ) from exc
    return previous


def activate(user, user_key: str, job_id: str) -> dict:
    """Point the account at a trained model — once it has been evaluated.

    The gate is checked against the corpus as it is *now*, so an evaluation
    that describes examples which have since moved cannot authorise anything.
    """
    record = _read_or_refuse(user_key, job_id)
    if record is None:
        raise TrainingServiceError(f"no training job {job_id}", 404)
    if record.status != "succeeded":
        raise TrainingServiceError(
            f"this job is {record.status}; there is nothing to activate yet", 409
        )
    fixtures = load_fixtures()
    try:
        checked = gate_mod.check(
            gate=gate_mod.read_gate(user_key, job_id),
            trained_model=record.trained_model,
            corpus_digests=gate_mod.heldout_digests(fixtures),
        )
    except gate_mod.GateRefused as refusal:
        raise TrainingServiceError(str(refusal), 409) from refusal

    previous = _set_account_model(user, str(record.trained_model))
    record.activation = {
        "activatedAt": records_mod._now(),
        "previousModel": previous,
        "rolledBackAt": None,
    }
    record.evaluation = gate_mod.summary(checked)
    record.append(
        "activated", model=record.trained_model, previousModel=previous,
        runId=checked.run_id,
    )
    records_mod.write(user_key, record)
    return record.as_dict()


def rollback(user, user_key: str, job_id: str) -> dict:
    """Put the account back on the model it had before this activation."""
    record = _read_or_refuse(user_key, job_id)
    if record is None:
        raise TrainingServiceError(f"no training job {job_id}", 404)
    if not record.activated:
        raise TrainingServiceError(
            "this job's model is not active, so there is nothing to roll back", 409
        )
    previous = record.activation.get("previousModel") or ""
    _set_account_model(user, previous)
    record.activation = {
        **record.activation,
        "rolledBackAt": records_mod._now(),
    }
    record.append("rolled-back", restoredModel=previous)
    records_mod.write(user_key, record)
    payload = record.as_dict()
    if not previous:
        # Honest: an empty previous model means the account inherits the
        # deployment default again, which is a different thing from a model.
        payload["rollbackNote"] = (
            "the account had no model of its own before, so it now inherits the "
            "deployment's default again"
        )
    else:
        payload["rollbackNote"] = (
            f"the account is back on {previous!r}; if the endpoint no longer "
            "serves it, AI Settings will show it as not listed"
        )
    return payload


def account_model_check(user, user_key: str) -> dict:
    """Whether the account is on a trained model nobody recorded activating.

    An evaluation switches the account's model temporarily (that is how a model
    is measured before it is activated). If that switch is interrupted, the
    account is left on a trained model with no activation record — which this
    reports so the panel can say so, rather than leaving it silent.
    """
    from utk_curio.backend.app.agents import model_catalog

    config = _provider_config(user)
    current = getattr(user, "llm_model", None) or ""
    trained = {
        row["model"]: row
        for row in model_catalog.trained_models(
            user_key, config.api_type, config.base_url
        )
    }
    if current not in trained:
        return {"model": current, "trainedInCurio": False, "unrecorded": False}
    activated = any(
        record.activated and record.trained_model == current
        for record in records_mod.list_records(user_key)
    )
    return {
        "model": current,
        "trainedInCurio": True,
        "unrecorded": not activated,
        "jobId": trained[current].get("jobId"),
    }


def _gate_payload(user_key: str, record) -> dict | None:
    """The gate's numbers when one exists, or the reason it does not satisfy
    activation — so the panel can show what is missing instead of a disabled
    button with no explanation."""
    if not record.trained_model:
        return None
    try:
        found = gate_mod.read_gate(user_key, record.job_id)
    except records_mod.TrainingRecordError as exc:
        return {"satisfied": False, "reason": str(exc)}
    try:
        checked = gate_mod.check(
            gate=found,
            trained_model=record.trained_model,
            corpus_digests=gate_mod.heldout_digests(load_fixtures()),
        )
    except gate_mod.GateRefused as refusal:
        return {"satisfied": False, "reason": str(refusal)}
    return {"satisfied": True, **gate_mod.summary(checked)}


def listing(user_key: str) -> dict:
    records = records_mod.list_records(user_key)
    return {
        "jobs": [record.as_dict() for record in records],
        "inFlight": (records_mod.in_flight(user_key) or None)
        and records_mod.in_flight(user_key).job_id,
    }
