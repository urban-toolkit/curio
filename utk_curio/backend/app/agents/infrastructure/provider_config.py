"""Which LLM answers a run: the account's LLM configurations and the deployment.

:func:`resolve_llm` is the one resolver. Every route, job and service asks it,
and it needs only the storage key, so it works in job threads, which have no
request. The fallback order:

- A **hosted guest** (a guest on an instance launched with ``--deploy``) runs
  on the guest configuration, Curio's default endpoint and model, for every
  agent. Every visitor shares that account, so it never opens a
  configurations file.
- An **internal** agent (a built-in that runs only as a delegate) always runs
  on its caller's configuration.
- Any other agent runs on what was **chosen for it** in API Settings: one of
  the account's configurations, one of this Curio's models (a pick,
  ``llm_configs.pick_choice``) or Curio's default.
- With no choice, a **delegated** agent (``caller`` given) runs on its
  caller's configuration, and an attached one on the account's **default**
  (a configuration or a pick), else **Curio's default** (the first model of
  the first endpoint in the operator's endpoint file,
  ``config.DEFAULT_LLM_ENDPOINTS``), else the run is refused.
- A reference that does not resolve (a choice or a default naming no
  configuration, Curio's default when the file is gone, a pick whose endpoint
  the file no longer has or whose model that endpoint no longer lists, an
  unreadable file) is refused. It never falls back to another configuration.

No page ever sees the host of one of this Curio's endpoints (``shown_host``).

This Curio's endpoints are offered only **whole**. There is no per-field
inheritance: a configuration of the user's own never borrows the operator's
key or URL, and the operator's endpoints are reachable only as Curio's default
or as a pick, which names one endpoint of the file and one of its models, and
takes that endpoint's type, URL and key.

Without ``--deploy`` the shared guest is the one local user: it owns its
configurations like any account, and its Curio's default is everyone's.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.infrastructure import llm_configs
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.common.user_storage import GUEST_KEY

SOURCE_ASSIGNED = "assigned"
SOURCE_CALLER = "caller"
SOURCE_DEFAULT = "default"
SOURCE_DEPLOYMENT = "deployment"
SOURCE_GUEST = "guest"
DEPLOYMENT_LABEL = "Curio's default"
GUEST_LABEL = "Guest configuration"


def pick_label(endpoint_name: str) -> str:
    """How a run on a pick of *endpoint_name*'s models is named."""
    return f"Curio · {endpoint_name}"


class ProviderConfigError(ValueError):
    """No LLM configuration answers this caller: a 400 whose remedy opens API Settings."""

    def __init__(self, message: str, *, agent_id: str | None = None):
        super().__init__(message)
        self.agent_id = agent_id

    @property
    def remedy(self) -> dict:
        return {"kind": "llm-config", **({"agentId": self.agent_id} if self.agent_id else {})}


def _settings():
    from utk_curio.backend import config

    return config


def _is_guest(user_key: str, guest: bool | None) -> bool:
    return bool(guest) if guest is not None else user_key == GUEST_KEY


def is_hosted_guest(user_key: str, *, guest: bool | None = None) -> bool:
    """A guest on an instance launched with ``--deploy``."""
    return _is_guest(user_key, guest) and not _settings().CURIO_NO_AUTH


def deployment_endpoints() -> tuple:
    """This Curio's own endpoints (``llm_endpoint.Endpoint``), read at call
    time; empty when the operator named no endpoint file."""
    return tuple(_settings().DEFAULT_LLM_ENDPOINTS or ())


def deployment_endpoint(name: str):
    """The endpoint of the file named *name*, or None."""
    return next((endpoint for endpoint in deployment_endpoints() if endpoint.name == name), None)


def pick_refusal(choice: str) -> str | None:
    """Why the pick *choice* does not run on this Curio, or None. One
    sentence for a save and a run alike, naming what is offered."""
    return llm_configs.pick_refusal(choice, deployment_endpoints())


def _on_endpoint(endpoint, model: str, **fields) -> ProviderConfig:
    return ProviderConfig(
        api_key=endpoint.api_key, api_type=endpoint.api_type, base_url=endpoint.base_url,
        model=model, on_deployment=True, **fields,
    )


def deployment_config(user_key: str, *, guest: bool | None = None) -> ProviderConfig | None:
    """Curio's default: the first endpoint of the file with its first model,
    or None when the operator named no endpoint file. A hosted guest answers
    with it as the guest configuration."""
    endpoints = deployment_endpoints()
    if not endpoints:
        return None
    hosted = is_hosted_guest(user_key, guest=guest)
    return _on_endpoint(
        endpoints[0], endpoints[0].models[0],
        label=GUEST_LABEL if hosted else DEPLOYMENT_LABEL,
        source=SOURCE_GUEST if hosted else SOURCE_DEPLOYMENT,
    )


def build_config(user_key: str, config_id: str, record: dict, *, source: str,
                 guest: bool | None = None, agent_id: str | None = None) -> ProviderConfig:
    """The ProviderConfig one stored configuration answers with."""
    return ProviderConfig(
        api_key=record.get("apiKey") or "", api_type=record.get("apiType") or "openai_compatible",
        base_url=record.get("baseUrl") or "", model=record.get("model") or "",
        config_id=config_id, label=record.get("label") or "", source=source,
    )


def pick_config(choice: str, *, source: str, agent_id: str | None = None) -> ProviderConfig:
    """The ProviderConfig a pick of one of this Curio's models answers with:
    that endpoint's type, URL and key with the picked model. A pick the
    endpoint file no longer offers is refused, never replaced."""
    refusal = pick_refusal(choice)
    if refusal:
        raise ProviderConfigError(refusal, agent_id=agent_id)
    endpoint_name, model = llm_configs.parse_pick(choice)
    return _on_endpoint(deployment_endpoint(endpoint_name), model,
                        label=pick_label(endpoint_name), source=source)


def resolve_llm(user_key: str, agent_id: str | None = None, *,
                caller: ProviderConfig | None = None, guest: bool | None = None) -> ProviderConfig:
    """The configuration a run of *agent_id* answers with (see the module
    docstring for the order). ``caller`` is the delegating run's configuration.
    ``guest`` says whether the caller is a guest when the storage key alone
    cannot (a guest that is not the shared one)."""
    from dataclasses import replace

    from utk_curio.backend.app.agents.domain import builtin

    if caller is not None and caller.source == SOURCE_GUEST:
        return caller
    if is_hosted_guest(user_key, guest=guest):
        config = deployment_config(user_key, guest=True)
        if config is None:
            raise ProviderConfigError(
                "LLM is not available for guest users at this time.", agent_id=agent_id
            )
        return config
    internal = bool(agent_id) and agent_id in builtin.internal_agent_ids()
    if internal and caller is not None:
        return replace(caller, source=SOURCE_CALLER)
    try:
        doc = llm_configs.default_store().read(user_key)
    except llm_configs.LlmConfigError as exc:
        raise ProviderConfigError(f"{exc}. Fix it in API Settings.", agent_id=agent_id) from exc
    chosen = doc["agents"].get(agent_id) if agent_id and not internal else None
    if chosen == llm_configs.CHOICE_DEPLOYMENT:
        config = deployment_config(user_key, guest=guest)
        if config is None:
            raise ProviderConfigError(
                f"{agent_id} is set to Curio's default, which this Curio no longer "
                "offers. Choose another for it in API Settings.",
                agent_id=agent_id,
            )
        return replace(config, source=SOURCE_ASSIGNED)
    if llm_configs.is_pick(chosen):
        return pick_config(chosen, source=SOURCE_ASSIGNED, agent_id=agent_id)
    if chosen:
        record = doc["configs"].get(chosen)
        if record is None:
            raise ProviderConfigError(
                f"The LLM configuration chosen for {agent_id} no longer exists. Choose "
                "another in API Settings.",
                agent_id=agent_id,
            )
        return build_config(user_key, chosen, record, source=SOURCE_ASSIGNED,
                            guest=guest, agent_id=agent_id)
    if caller is not None:
        return replace(caller, source=SOURCE_CALLER)
    default_id = doc["default"]
    if llm_configs.is_pick(default_id):
        return pick_config(default_id, source=SOURCE_DEFAULT, agent_id=agent_id)
    if default_id:
        record = doc["configs"].get(default_id)
        if record is None:
            raise ProviderConfigError(
                "Your default LLM configuration no longer exists. Choose another in API Settings.",
                agent_id=agent_id,
            )
        return build_config(user_key, default_id, record, source=SOURCE_DEFAULT,
                            guest=guest, agent_id=agent_id)
    config = deployment_config(user_key, guest=guest)
    if config is None:
        raise ProviderConfigError(
            "No LLM configuration answers this run. Add one in API Settings, or ask your "
            "Curio operator to configure a default.",
            agent_id=agent_id,
        )
    return config


def shown_host(config: ProviderConfig) -> str:
    """What a page may see of the endpoint *config* runs on: the host of a
    configuration of the user's own, and nothing of this Curio's endpoint."""
    if config.on_deployment:
        return ""
    return llm_configs.base_url_host(config.base_url, config.api_type)


def llm_pin(config: ProviderConfig) -> dict:
    """What a run records about the configuration that answered it: never the
    key, and never the host of this Curio's own endpoint."""
    return {
        "configId": config.config_id,
        "label": config.label,
        "baseUrlHost": shown_host(config),
        "source": config.source,
    }


def redact_error(text: object, config: ProviderConfig | None) -> str:
    """Provider error text without the call's own key and without this
    Curio's endpoint (``providers.redacted_text``), for anything persisted,
    streamed, logged or returned."""
    from utk_curio.backend.app.agents.infrastructure.providers import redacted_text

    return redacted_text(text, config)


def storage_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _deployment_payload(user_key: str, guest: bool) -> dict:
    """What a page is told of this Curio's endpoints: their names and models,
    never a URL, a host or a key."""
    config = deployment_config(user_key, guest=guest)
    return {
        "label": config.label if config else DEPLOYMENT_LABEL,
        "apiType": config.api_type if config else None,
        "model": config.model if config else None,
        "endpoints": [
            {"name": endpoint.name, "models": list(endpoint.models)} for endpoint in deployment_endpoints()
        ],
    }


def _answers(config: ProviderConfig) -> dict:
    return {
        "source": config.source, "configId": config.config_id,
        "label": config.label, "model": config.model, "apiType": config.api_type,
        "baseUrlHost": shown_host(config),
    }


