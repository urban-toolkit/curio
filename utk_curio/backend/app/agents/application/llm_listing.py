"""``GET /api/agents/llm``: the account's configurations without keys, its default, the deployment's offer,
what answers a run now, the agents whose configuration it may choose, and whether this account may change any of it.

Application layer of the agents package (re-derived on enh/agent-catalog): cut from
``infrastructure/provider_config.py`` because it composes the configuration store with the agents
roster (``catalog.choosable_agents``), which an infrastructure module must not reach.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.infrastructure import llm_configs


def llm_listing(user) -> dict:
    """``GET /api/agents/llm``: the account's configurations without keys, its
    default, the deployment's offer, what answers a run now, the agents whose
    configuration it may choose (each with its choice and what it answers with
    when attached), and whether this account may change any of it."""
    from utk_curio.backend import config as settings
    from utk_curio.backend.app.users.capabilities import llm_config_refusal

    user_key = agents_provider_config.storage_key(user)
    guest = bool(getattr(user, "is_guest", False))
    deployment = agents_provider_config._deployment_payload(user_key, guest)
    refusal = llm_config_refusal(user)
    try:
        active = agents_provider_config._answers(agents_provider_config.resolve_llm(user_key, guest=guest))
    except agents_provider_config.ProviderConfigError as exc:
        active = {"source": None, "error": str(exc)}
    if agents_provider_config.is_hosted_guest(user_key, guest=guest):
        configs, default, choices, agents = [], None, {}, []
    else:
        store = llm_configs.default_store()
        configs = store.list(user_key)
        default = store.default_id(user_key)
        for entry in configs:
            if entry["endpoint"] == llm_configs.ENDPOINT_DEPLOYMENT:
                entry["apiType"] = deployment["apiType"] or ""
                entry["baseUrlHost"] = deployment["baseUrlHost"] or ""
        stored = store.choices(user_key)
        agents = []
        for row in agents_catalog.choosable_agents(user_key):
            try:
                answers = agents_provider_config._answers(agents_provider_config.resolve_llm(user_key, row["id"], guest=guest))
            except agents_provider_config.ProviderConfigError as exc:
                answers = {"source": None, "error": str(exc)}
            agents.append({**row, "choice": stored.get(row["id"]), "answers": answers})
        choosable = {row["id"] for row in agents}
        choices = {agent_id: chosen for agent_id, chosen in stored.items() if agent_id in choosable}
    return {
        "configs": configs,
        "default": default,
        "assignments": choices,
        "agents": agents,
        "deployment": deployment,
        "active": active,
        "editable": refusal is None,
        "reason": refusal,
        "shared": bool(guest and settings.CURIO_NO_AUTH),
        "maxConfigs": llm_configs.MAX_CONFIGS_PER_USER,
    }
