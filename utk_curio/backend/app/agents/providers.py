"""Provider-neutral chat-completion port.

This is the one place raw LLM-provider SDKs are used, so LLM/provider behavior
stays out of the route/flow/node modules (the ``agents/`` ownership boundary in
the plan's module-encapsulation memo). Callers resolve a :class:`ProviderConfig`
(e.g. from the user's LLM settings or the aiconn default) and hand it to
:func:`run_chat_completion`; they never import ``openai`` / ``anthropic`` /
``google.generativeai`` directly.

The dispatch below was extracted verbatim from ``app/api/routes.py::_call_llm``
(behavior-preserving) and is the seam a future LangChain adapter would sit behind.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

from dataclasses import dataclass




@dataclass(frozen=True)
class ProviderConfig:
    """Resolved, provider-neutral connection config for one chat completion.

    ``api_type`` selects the backend: ``"anthropic"``, ``"gemini"``, or
    ``"openai_compatible"`` (the default, used by OpenAI, the aiconn sage200
    endpoint, Ollama, vLLM, etc.). ``base_url`` applies only to the
    openai-compatible backend; the others ignore it.
    """

    api_key: str
    api_type: str
    base_url: str
    model: str


def _capture_usage(usage_out: dict | None, input_tokens, output_tokens) -> None:
    """Record Actual token usage into the caller's sink (memo dev/37).

    Best-effort: only populated when the provider reports both counts; the sink
    stays empty otherwise. Never estimated (memo dev/11's labeling rule)."""
    if usage_out is None:
        return
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        usage_out["inputTokens"] = input_tokens
        usage_out["outputTokens"] = output_tokens


def run_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
) -> str:
    """Dispatch an LLM chat completion to the configured provider.

    ``messages`` is the OpenAI-style ``[{"role", "content"}, ...]`` list. Returns
    the assistant reply text. ``max_output_tokens`` is the effective resource
    policy (memo dev/24); when unset the anthropic backend keeps its former
    4096 and the others use provider defaults.
    """
    api_type = config.api_type
    if api_type == "testing":
        # Scripted, deterministic, no network. Guarded on CURIO_TESTING inside
        # run_scripted_completion, so this branch cannot be reached on a real
        # deployment even if a config names it. See agents/testing_provider.py.
        from utk_curio.backend.app.agents.testing_provider import (
            run_scripted_completion,
        )

        return run_scripted_completion(messages, usage_out=usage_out)
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        resp = client.messages.create(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=max_output_tokens or 4096,
        )
        usage = getattr(resp, "usage", None)
        _capture_usage(
            usage_out, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)
        )
        return resp.content[0].text
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        history = []
        for m in chat_messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})
        last_user_msg = chat_messages[-1]["content"] if chat_messages else ""
        system_instruction = "\n".join(system_parts) if system_parts else None
        gen_model = genai.GenerativeModel(config.model, system_instruction=system_instruction)
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        response = chat.send_message(last_user_msg, **send_kwargs)
        meta = getattr(response, "usage_metadata", None)
        _capture_usage(
            usage_out,
            getattr(meta, "prompt_token_count", None),
            getattr(meta, "candidates_token_count", None),
        )
        return response.text
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        create_kwargs = {"model": config.model, "messages": messages}
        if max_output_tokens:
            create_kwargs["max_tokens"] = max_output_tokens
        completion = client.chat.completions.create(**create_kwargs)
        usage = getattr(completion, "usage", None)
        _capture_usage(
            usage_out, getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        )
        return completion.choices[0].message.content


def stream_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
):
    """Streaming twin of :func:`run_chat_completion`: yields reply-text deltas.

    Same provider dispatch and message handling; each yielded string is an
    incremental chunk of the assistant reply (memo ``dev/22``, SSE runtime).
    Callers that stop iterating close the underlying provider stream.
    """
    api_type = config.api_type
    if api_type == "testing":
        # The scripted reply, delivered as a single chunk. Splitting it would
        # only test the splitter: what the SSE runtime needs from a provider
        # is a deterministic sequence of deltas, and one is a sequence.
        from utk_curio.backend.app.agents.testing_provider import (
            run_scripted_completion,
        )

        yield run_scripted_completion(messages, usage_out=usage_out)
        return
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        with client.messages.stream(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=max_output_tokens or 4096,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
            try:
                usage = getattr(stream.get_final_message(), "usage", None)
                _capture_usage(
                    usage_out,
                    getattr(usage, "input_tokens", None),
                    getattr(usage, "output_tokens", None),
                )
            except Exception:
                pass  # usage is best-effort; the reply already streamed
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        history = []
        for m in chat_messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})
        last_user_msg = chat_messages[-1]["content"] if chat_messages else ""
        system_instruction = "\n".join(system_parts) if system_parts else None
        gen_model = genai.GenerativeModel(config.model, system_instruction=system_instruction)
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        last_chunk = None
        for chunk in chat.send_message(last_user_msg, stream=True, **send_kwargs):
            last_chunk = chunk
            text = getattr(chunk, "text", "")
            if text:
                yield text
        meta = getattr(last_chunk, "usage_metadata", None)
        _capture_usage(
            usage_out,
            getattr(meta, "prompt_token_count", None),
            getattr(meta, "candidates_token_count", None),
        )
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        create_kwargs = {
            "model": config.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_output_tokens:
            create_kwargs["max_tokens"] = max_output_tokens
        stream = client.chat.completions.create(**create_kwargs)
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                _capture_usage(
                    usage_out,
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                )
            choices = getattr(chunk, "choices", None) or []
            delta = choices[0].delta if choices else None
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text


class ModelListingUnavailable(RuntimeError):
    """The endpoint could not be asked what it serves.

    Carries the reason so AI Settings can say *why* the list is missing rather
    than only that it is: a rejected key, an unreachable host and an endpoint
    with no listing route are three different things for the user to fix.
    """


def list_provider_models(config: ProviderConfig) -> list[str]:
    """The model ids *config*'s endpoint says it serves.

    Lives here for the same reason every other provider call does: this module
    is the one place raw provider SDKs are imported (see the module docstring).
    The route used to import ``openai`` directly, which also meant Anthropic and
    Gemini were reported as unlistable when in fact nobody had asked them
    (#241) - both SDKs have had a models endpoint for some time.

    Raises :class:`ModelListingUnavailable` when the endpoint cannot answer. The
    caller decides what to do about that; ``model_catalog`` holds the fallback.
    """
    api_type = (config.api_type or "").strip()

    if not (config.api_key or "").strip():
        # No credential means no listing anywhere: OpenAI, Anthropic and Gemini
        # all authenticate their models endpoint. Refusing here rather than
        # sending "no-key" keeps a user who has not pasted a key yet from
        # waiting out a socket timeout for a foregone 401.
        raise ModelListingUnavailable(
            "Add an API key above to ask this provider what it serves."
        )

    try:
        if api_type == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=config.api_key, timeout=20.0)
            return sorted(
                {m.id for m in client.models.list() if getattr(m, "id", None)}
            )

        if api_type == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=config.api_key)
            out: set[str] = set()
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", None) or []
                # Embedding and tuning-only models are listed too, and offering
                # one as the chat model produces a failure at the first agent
                # run rather than here.
                if "generateContent" not in methods:
                    continue
                name = getattr(m, "name", "") or ""
                # The API returns "models/gemini-2.0-flash"; every other place
                # in Curio names the bare id.
                out.add(name.split("/", 1)[-1] if name.startswith("models/") else name)
            return sorted(n for n in out if n)

        # openai_compatible (default), which also covers Ollama, vLLM, Groq, ...
        from openai import OpenAI

        kwargs: dict = {"api_key": config.api_key, "timeout": 20.0}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        listing = OpenAI(**kwargs).models.list()
        return sorted({m.id for m in listing.data if getattr(m, "id", None)})
    except Exception as exc:  # noqa: BLE001 - every SDK failure is one answer here
        # A rejected key, an unreachable host and an endpoint without a models
        # route all mean "cannot offer a live choice".
        raise ModelListingUnavailable(f"Could not list models: {exc}") from exc


# ---------------------------------------------------------------------------
# Fine-tuning (memo dev/122, ``DEC-078``)
# ---------------------------------------------------------------------------
#
# Same rule as everything above: the SDK is imported here and nowhere else, and
# the answer to "can this endpoint do it" is obtained by ASKING the endpoint.
# A table of which providers support tuning would drift exactly the way the
# table of model ids drifted (#241) and could say nothing about a custom
# endpoint — and "OpenAI-compatible" spans endpoints that implement the tuning
# routes and endpoints that implement only chat (Ollama, LM Studio, vLLM).
#
# These calls do not pass through ``agents/egress.py``, for the same reason no
# other provider call does: that chokepoint polices URLs a MODEL chose, while
# this host is one the account holder typed into AI Settings. It is also the
# only option — ``egress.fetch`` has no request body and caps responses, so it
# cannot express a training-file upload.


class FineTuningUnavailable(RuntimeError):
    """This endpoint cannot fine-tune, and this is why.

    A sibling of :class:`ModelListingUnavailable` and for the same reason: "no
    such feature here", "your key lacks the scope" and "the host is
    unreachable" are three different things for a user to act on, so the reason
    travels with the refusal instead of being flattened into a boolean.
    """


#: Job statuses Curio normalizes to. ``raw_status`` on the job keeps whatever
#: the endpoint actually said, because a status we have never seen must not be
#: displayed as one we have.
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

_OPENAI_STATUS_MAP = {
    "validating_files": "queued",
    "queued": "queued",
    "pending": "queued",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


@dataclass(frozen=True)
class FineTuningCapabilities:
    """What *this* endpoint said about tuning, and when it said it."""

    supported: bool
    reason: str
    base_models: tuple = ()
    surface: str = ""            # "openai_compatible_v1" when recognised
    probed_at: str = ""

    def as_dict(self) -> dict:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "baseModels": list(self.base_models),
            "surface": self.surface,
            "probedAt": self.probed_at,
        }


@dataclass(frozen=True)
class FineTuningJob:
    """One tuning job as the endpoint reports it."""

    id: str
    status: str                  # one of JOB_STATUSES
    raw_status: str = ""
    base_model: str = ""
    trained_model: str | None = None
    trained_tokens: int | None = None
    error: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "rawStatus": self.raw_status,
            "baseModel": self.base_model,
            "trainedModel": self.trained_model,
            "trainedTokens": self.trained_tokens,
            "error": self.error,
        }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _openai_client(config: ProviderConfig, *, timeout: float = 30.0):
    from openai import OpenAI

    kwargs: dict = {"api_key": config.api_key or "no-key", "timeout": timeout}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)


def _status_code_of(exc: Exception) -> int | None:
    for attribute in ("status_code", "status", "http_status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def fine_tuning_capabilities(config: ProviderConfig) -> FineTuningCapabilities:
    """Ask *config*'s endpoint whether it can fine-tune.

    Never raises: an unanswerable endpoint is an answer with a reason, which is
    what a settings panel needs in order to say *why* rather than only *no*
    (the dev/11 posture: show Unavailable, never a substitute).
    """
    api_type = (config.api_type or "").strip()
    probed_at = _now_iso()

    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_fine_tuning_capabilities(probed_at=probed_at)

    if api_type == "anthropic":
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Anthropic's API has no fine-tuning endpoint: it publishes "
                "Messages, Message Batches, Token Counting, Models, Files and "
                "Skills, plus the beta Agents, Sessions and Environments APIs. "
                "Nothing here can tune a Claude model."
            ),
            probed_at=probed_at,
        )

    if api_type == "gemini":
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Gemini tunes through its tunedModels API, a different contract "
                "Curio has not implemented. Chat and model listing work as usual."
            ),
            probed_at=probed_at,
        )

    if not (config.api_key or "").strip():
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Add an API key above: every endpoint authenticates its "
                "fine-tuning routes, so there is nothing to ask yet."
            ),
            probed_at=probed_at,
        )

    # openai_compatible (the default) — and being OpenAI-compatible for chat
    # says nothing about tuning, so the routes are what get asked.
    try:
        client = _openai_client(config, timeout=20.0)
        client.fine_tuning.jobs.list(limit=1)
    except Exception as exc:  # noqa: BLE001 - one answer per failure shape
        status = _status_code_of(exc)
        if status in (401, 403):
            return FineTuningCapabilities(
                supported=False,
                reason=(
                    f"This key cannot list fine-tuning jobs ({status}). The "
                    "endpoint may still support tuning — a key with the scope "
                    "would tell us."
                ),
                probed_at=probed_at,
            )
        if status in (404, 405, 501):
            return FineTuningCapabilities(
                supported=False,
                reason=(
                    f"This endpoint serves chat but not fine-tuning ({status} "
                    "from its fine-tuning route). Ollama, LM Studio and vLLM "
                    "answer this way."
                ),
                probed_at=probed_at,
            )
        return FineTuningCapabilities(
            supported=False,
            reason=f"Could not ask this endpoint about fine-tuning: {exc}",
            probed_at=probed_at,
        )

    return FineTuningCapabilities(
        supported=True,
        reason="This endpoint answers its fine-tuning routes.",
        base_models=_openai_tunable_models(config),
        surface="openai_compatible_v1",
        probed_at=probed_at,
    )


def _openai_tunable_models(config: ProviderConfig) -> tuple:
    """Base models the endpoint says can be tuned, or nothing.

    Nothing is guessed: an endpoint that does not advertise tunability gets an
    empty tuple and the panel asks the user to type a base model, exactly as
    the Model field already works. A hand-written list of "probably tunable"
    ids is the drift #241 was filed about.
    """
    try:
        listing = _openai_client(config, timeout=20.0).models.list()
    except Exception:  # noqa: BLE001 - a missing hint is not a failure
        return ()
    out: set = set()
    for model in getattr(listing, "data", None) or []:
        model_id = getattr(model, "id", None)
        if not model_id:
            continue
        # Only an explicit signal counts. Some endpoints report permissions or
        # capability flags; where none exists the tuple stays empty.
        allows = getattr(model, "allow_fine_tuning", None)
        if allows is None:
            capabilities = getattr(model, "capabilities", None)
            allows = (
                capabilities.get("fine_tuning")
                if isinstance(capabilities, dict)
                else None
            )
        if allows:
            out.add(str(model_id))
    return tuple(sorted(out))


def _require_openai_surface(config: ProviderConfig) -> None:
    api_type = (config.api_type or "").strip()
    if api_type in ("anthropic", "gemini"):
        raise FineTuningUnavailable(
            fine_tuning_capabilities(config).reason
        )


def upload_training_file(
    config: ProviderConfig, *, filename: str, content: bytes
) -> str:
    """Upload a JSONL training file and return the endpoint's file id."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_upload_training_file(filename, content)
    _require_openai_surface(config)
    try:
        result = _openai_client(config).files.create(
            file=(filename, content), purpose="fine-tune",
        )
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not upload the training file: {exc}") from exc
    file_id = getattr(result, "id", None)
    if not file_id:
        raise FineTuningUnavailable(
            "The endpoint accepted the upload but reported no file id."
        )
    return str(file_id)


def create_fine_tuning_job(
    config: ProviderConfig,
    *,
    training_file: str,
    base_model: str,
    suffix: str | None = None,
) -> FineTuningJob:
    """Start a tuning job at the endpoint and return it as reported."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_create_fine_tuning_job(
            training_file=training_file, base_model=base_model, suffix=suffix
        )
    _require_openai_surface(config)
    payload: dict = {"training_file": training_file, "model": base_model}
    if suffix:
        payload["suffix"] = suffix
    try:
        job = _openai_client(config).fine_tuning.jobs.create(**payload)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"The endpoint refused the job: {exc}") from exc
    return _job_from_openai(job, fallback_base_model=base_model)


def get_fine_tuning_job(config: ProviderConfig, job_id: str) -> FineTuningJob:
    """The endpoint's current word on a job."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_get_fine_tuning_job(job_id)
    _require_openai_surface(config)
    try:
        job = _openai_client(config).fine_tuning.jobs.retrieve(job_id)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not read job {job_id}: {exc}") from exc
    return _job_from_openai(job)


def cancel_fine_tuning_job(config: ProviderConfig, job_id: str) -> FineTuningJob:
    """Ask the endpoint to cancel a job; return what it says afterwards.

    A cancel the endpoint refuses (already finished) is that refusal, reported
    — never a local status change that would make the record disagree with the
    provider.
    """
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_cancel_fine_tuning_job(job_id)
    _require_openai_surface(config)
    try:
        job = _openai_client(config).fine_tuning.jobs.cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not cancel job {job_id}: {exc}") from exc
    return _job_from_openai(job)


def _job_from_openai(job, *, fallback_base_model: str = "") -> FineTuningJob:
    raw = str(getattr(job, "status", "") or "")
    error = getattr(job, "error", None)
    message = None
    if error is not None:
        message = getattr(error, "message", None)
        if message is None and isinstance(error, dict):
            message = error.get("message")
        if message is not None:
            message = str(message) or None
    trained_tokens = getattr(job, "trained_tokens", None)
    return FineTuningJob(
        id=str(getattr(job, "id", "") or ""),
        # An unrecognised status stays "running" rather than being called
        # terminal: acting on a status we do not understand is worse than
        # waiting, and raw_status carries the endpoint's own word.
        status=_OPENAI_STATUS_MAP.get(raw.lower(), "running"),
        raw_status=raw,
        base_model=str(getattr(job, "model", "") or fallback_base_model),
        trained_model=(
            str(getattr(job, "fine_tuned_model", "") or "") or None
        ),
        trained_tokens=trained_tokens if isinstance(trained_tokens, int) else None,
        error=message,
    )
