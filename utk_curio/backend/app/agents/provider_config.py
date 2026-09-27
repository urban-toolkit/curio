"""Which LLM answers a run: the account's LLM configurations and the deployment.

:func:`resolve_llm` is the one resolver. Every route, job and service asks it,
and it needs only the storage key, so it works in job threads, which have no
request. The fallback order:

- A **hosted guest** (a guest on an instance launched with ``--deploy``) runs
  on the guest configuration, ``GUEST_LLM_*``, for every agent. Every visitor
  shares that account, so it never opens a configurations file.
- A **delegated** run (``caller`` given) runs on its caller's configuration.
- Otherwise the account's **default configuration** answers, else the
  **deployment default** (``CURIO_DEFAULT_LLM_*``, offered when the operator
  set a model), else the run is refused.
- A reference that does not resolve (a default naming no configuration, a
  This Curio install configuration whose deployment withdrew its endpoint, an
  unreadable file) is refused. It never falls back to another configuration.

The deployment is offered only **whole**. There is no per-field inheritance: a
configuration of the user's own never borrows the operator's key or URL, and
the operator's endpoint is reachable only as the Deployment default or as a
This Curio install configuration, which takes the deployment's type, URL and
key with a model the user picks.

Without ``--deploy`` the shared guest is the one local user: it owns its
configurations like any account, and its deployment is ``GUEST_LLM_*``.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import llm_configs
from utk_curio.backend.app.agents.providers import ProviderConfig
from utk_curio.backend.app.common.user_storage import GUEST_KEY

SOURCE_DEFAULT = "default"
SOURCE_DEPLOYMENT = "deployment"
SOURCE_GUEST = "guest"
DEPLOYMENT_LABEL = "Deployment default"
GUEST_LABEL = "Guest configuration"


class ProviderConfigError(ValueError):
    """No LLM configuration answers this caller: a 400 whose remedy opens AI Settings."""

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


def deployment_endpoint(user_key: str, *, guest: bool | None = None) -> tuple[str, str, str] | None:
    """``(api_type, base_url, api_key)`` of the deployment's own endpoint as this
    caller may use it, read at call time, or None when the operator configured
    none. A guest's is ``GUEST_LLM_*`` and needs its key."""
    cfg = _settings()
    if _is_guest(user_key, guest):
        api_type, base_url, api_key = cfg.GUEST_LLM_API_TYPE, cfg.GUEST_LLM_BASE_URL, cfg.GUEST_LLM_API_KEY
        if not api_key:
            return None
    else:
        api_type, base_url, api_key = cfg.DEFAULT_LLM_API_TYPE, cfg.DEFAULT_LLM_BASE_URL, cfg.DEFAULT_LLM_API_KEY
        if not (api_key or base_url):
            return None
    return (api_type or "openai_compatible", base_url or "", api_key or "")


def deployment_config(user_key: str, *, guest: bool | None = None) -> ProviderConfig | None:
    """The Deployment default: the deployment's endpoint with the model the
    operator set, or None when there is no such endpoint or no model."""
    cfg = _settings()
    is_guest = _is_guest(user_key, guest)
    model = cfg.GUEST_LLM_MODEL if is_guest else cfg.DEFAULT_LLM_MODEL
    endpoint = deployment_endpoint(user_key, guest=guest)
    if endpoint is None or not model:
        return None
    api_type, base_url, api_key = endpoint
    return ProviderConfig(
        api_key=api_key, api_type=api_type, base_url=base_url, model=model,
        label=GUEST_LABEL if is_guest and is_hosted_guest(user_key, guest=guest) else DEPLOYMENT_LABEL,
        source=SOURCE_GUEST if is_hosted_guest(user_key, guest=guest) else SOURCE_DEPLOYMENT,
    )


def build_config(user_key: str, config_id: str, record: dict, *, source: str,
                 guest: bool | None = None, agent_id: str | None = None) -> ProviderConfig:
    """The ProviderConfig one stored configuration answers with."""
    trained = record.get("origin") == llm_configs.ORIGIN_TRAINED
    label = record.get("label") or ""
    if record.get("endpoint") == llm_configs.ENDPOINT_DEPLOYMENT:
        endpoint = deployment_endpoint(user_key, guest=guest)
        if endpoint is None:
            raise ProviderConfigError(
                f"The configuration {label!r} uses this Curio install's endpoint, which it no "
                "longer offers. Choose another configuration in AI Settings.",
                agent_id=agent_id,
            )
        api_type, base_url, api_key = endpoint
    else:
        api_type = record.get("apiType") or "openai_compatible"
        base_url = record.get("baseUrl") or ""
        api_key = record.get("apiKey") or ""
    return ProviderConfig(
        api_key=api_key, api_type=api_type, base_url=base_url, model=record.get("model") or "",
        config_id=config_id, label=label, source=source, trained=trained,
    )


def resolve_llm(user_key: str, agent_id: str | None = None, *,
                caller: ProviderConfig | None = None, guest: bool | None = None) -> ProviderConfig:
    """The configuration a run of *agent_id* answers with (see the module
    docstring for the order). ``guest`` says whether the caller is a guest when
    the storage key alone cannot (a guest that is not the shared one)."""
    if is_hosted_guest(user_key, guest=guest):
        config = deployment_config(user_key, guest=True)
        if config is None:
            raise ProviderConfigError(
                "LLM is not available for guest users at this time.", agent_id=agent_id
            )
        return config
    if caller is not None:
        return caller
    try:
        doc = llm_configs.default_store().read(user_key)
    except llm_configs.LlmConfigError as exc:
        raise ProviderConfigError(f"{exc}. Fix it in AI Settings.", agent_id=agent_id) from exc
    default_id = doc["default"]
    if default_id:
        record = doc["configs"].get(default_id)
        if record is None:
            raise ProviderConfigError(
                "Your default LLM configuration no longer exists. Choose another in AI Settings.",
                agent_id=agent_id,
            )
        return build_config(user_key, default_id, record, source=SOURCE_DEFAULT,
                            guest=guest, agent_id=agent_id)
    config = deployment_config(user_key, guest=guest)
    if config is None:
        raise ProviderConfigError(
            "No LLM configuration answers this run. Add one in AI Settings, or ask your "
            "Curio operator to configure a default.",
            agent_id=agent_id,
        )
    return config


def llm_pin(config: ProviderConfig) -> dict:
    """What a run records about the configuration that answered it: never the key."""
    return {
        "configId": config.config_id,
        "label": config.label,
        "baseUrlHost": llm_configs.base_url_host(config.base_url, config.api_type),
        "source": config.source,
    }


def redact_error(text: object, config: ProviderConfig | None) -> str:
    """Provider error text with the call's own key taken out, for anything
    persisted, streamed, logged or returned."""
    from utk_curio.common.redaction import redact

    message = str(text)
    if config is None or not config.api_key:
        return message
    return redact(message, {"llm-api-key": config.api_key}) or message


def storage_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _deployment_payload(user_key: str, guest: bool) -> dict:
    endpoint = deployment_endpoint(user_key, guest=guest)
    config = deployment_config(user_key, guest=guest)
    return {
        "label": config.label if config else DEPLOYMENT_LABEL,
        "endpointOffered": endpoint is not None,
        "apiType": endpoint[0] if endpoint else None,
        "baseUrlHost": llm_configs.base_url_host(endpoint[1], endpoint[0]) if endpoint else None,
        "model": config.model if config else None,
    }


def llm_listing(user) -> dict:
    """``GET /api/agents/llm``: the account's configurations without keys, its
    default, the deployment's offer, what answers a run now, and whether this
    account may change any of it."""
    from utk_curio.backend import config as settings
    from utk_curio.backend.app.users.capabilities import llm_config_refusal

    user_key = storage_key(user)
    guest = bool(getattr(user, "is_guest", False))
    deployment = _deployment_payload(user_key, guest)
    refusal = llm_config_refusal(user)
    try:
        active_config = resolve_llm(user_key, guest=guest)
        active = {
            "source": active_config.source, "configId": active_config.config_id,
            "label": active_config.label, "model": active_config.model,
            "apiType": active_config.api_type,
            "baseUrlHost": llm_configs.base_url_host(active_config.base_url, active_config.api_type),
        }
    except ProviderConfigError as exc:
        active = {"source": None, "error": str(exc)}
    if is_hosted_guest(user_key, guest=guest):
        configs, default = [], None
    else:
        store = llm_configs.default_store()
        configs = store.list(user_key)
        default = store.default_id(user_key)
        for entry in configs:
            if entry["endpoint"] == llm_configs.ENDPOINT_DEPLOYMENT:
                entry["apiType"] = deployment["apiType"] or ""
                entry["baseUrlHost"] = deployment["baseUrlHost"] or ""
    return {
        "configs": configs,
        "default": default,
        "deployment": deployment,
        "active": active,
        "editable": refusal is None,
        "reason": refusal,
        "shared": bool(guest and settings.CURIO_NO_AUTH),
        "maxConfigs": llm_configs.MAX_CONFIGS_PER_USER,
    }
