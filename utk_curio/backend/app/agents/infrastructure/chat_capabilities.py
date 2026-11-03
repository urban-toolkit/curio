"""What a chat endpoint can do beyond text: call tools natively, and take a JSON
schema for its reply.

A run speaks the fenced ``curio.v1`` protocol unless its LLM configuration can
do better. No OpenAI-compatible route says whether a server supports tools, and
support varies per model, so the answer comes from one of:

- **the table**: Anthropic, Gemini and OpenAI's own endpoint take both, as
  their APIs define them;
- **a trial**: any other OpenAI-compatible server is asked once per model, with
  a charged request offering one tool (``providers.probe_native_tools``),
  asked as a turn is, with the room a model that thinks gets. A reply that
  calls it means native tools; a 400, or a reply that ends without calling
  it, means the fenced protocol. The answer is recorded per account with its
  cause (``model_catalog.remember_chat_capabilities``) and the trial's tokens
  go to the ledger with the configuration's id;
- **the script**: the scripted provider answers what a test scripted, fenced by
  default (``testing_provider.scripted_chat_capabilities``).

An endpoint that cannot be asked right now (offline, a rejected key) gets the
fenced protocol without a record, so it is asked again next time, and so does
a trial its limit cut before the model called the tool, the room included: a
model still thinking says nothing of the tools.

A record kept before answers kept their cause still answers, but for one: the
fenced protocol because "the model answered without calling the tool it was
offered", which the trial, asked then with 32 tokens and no room, also said of
a reply the cap cut while the model was still thinking. That endpoint is asked
again (:func:`_still_holds`).

A run offered native tools that its endpoint refuses (a 400 or 422) carries on
with the fenced protocol. Once that fenced call succeeds, the refusal is the
answer for an endpoint the table does not know
(:func:`record_native_refusal`), so the next run starts fenced.

A manifest's ``providerRequirements`` is a preference: nothing here refuses a
run because its configuration lacks a capability.
"""

from __future__ import annotations

from dataclasses import dataclass

from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig

SOURCE_TABLE = "table"
SOURCE_TRIAL = "trial"
SOURCE_REMEMBERED = "remembered"
SOURCE_SCRIPTED = "scripted"
SOURCE_UNKNOWN = "unknown"

#: The hosts whose OpenAI-compatible API is OpenAI's own.
_OPENAI_HOSTS = ("api.openai.com",)


@dataclass(frozen=True)
class ChatCapabilities:
    tools: bool
    structured_output: bool
    source: str
    reason: str = ""
    seen_at: str | None = None

    @property
    def protocol(self) -> str:
        """``native`` when tools are called natively, else ``fenced``."""
        return "native" if self.tools else "fenced"

    def as_dict(self) -> dict:
        return {
            "tools": self.tools,
            "structuredOutput": self.structured_output,
            "protocol": self.protocol,
            "source": self.source,
            "reason": self.reason,
            "seenAt": self.seen_at,
        }


def _host(base_url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(base_url or "").hostname or "").lower()
    except ValueError:
        return ""


def _from_table(config: ProviderConfig) -> ChatCapabilities | None:
    if config.api_type == "anthropic":
        return ChatCapabilities(True, True, SOURCE_TABLE, "Anthropic's API takes tools and a reply schema")
    if config.api_type == "gemini":
        return ChatCapabilities(True, True, SOURCE_TABLE, "Gemini's API takes tools and a reply schema")
    if config.api_type == "openai_compatible" and _host(config.base_url) in _OPENAI_HOSTS:
        return ChatCapabilities(True, True, SOURCE_TABLE, "OpenAI's API takes tools and a reply schema")
    return None


#: The reason the trial gave, before answers kept their cause, for every reply
#: that held no call: one the model ended without calling the tool, and one
#: the trial's 32 tokens cut while the model was still thinking.
_REASON_BEFORE_CAUSES = "the model answered without calling the tool it was offered"


def _still_holds(remembered: dict) -> bool:
    """Whether a remembered answer still answers. One kept with its cause
    does (a cut trial is never kept). One kept before causes were does
    unless it may have been a cut: the fenced protocol, for
    :data:`_REASON_BEFORE_CAUSES`."""
    if remembered.get("cause"):
        return True
    return bool(remembered.get("tools")) or str(remembered.get("reason") or "") != _REASON_BEFORE_CAUSES


def chat_capabilities(config: ProviderConfig, user_key: str, *, refresh: bool = False) -> ChatCapabilities:
    """What *config* can do beyond text (see the module docstring for where the
    answer comes from). ``refresh`` asks an OpenAI-compatible server again
    instead of using what it said before."""
    from utk_curio.backend.app.agents.repositories import (
        ledger,
        model_catalog,
    )
    from utk_curio.backend.app.agents.infrastructure import providers

    if config.api_type == "testing":
        from utk_curio.backend.app.agents.infrastructure.testing_provider import scripted_chat_capabilities

        scripted = scripted_chat_capabilities()
        return ChatCapabilities(
            bool(scripted.get("tools")), bool(scripted.get("structuredOutput")),
            SOURCE_SCRIPTED, "the scripted provider",
        )
    known = _from_table(config)
    if known is not None:
        return known
    if not refresh:
        remembered = model_catalog.remembered_chat_capabilities(
            user_key, config.api_type, config.base_url, config.model
        )
        if remembered is not None and _still_holds(remembered):
            return ChatCapabilities(
                bool(remembered.get("tools")), bool(remembered.get("structuredOutput")),
                SOURCE_REMEMBERED, str(remembered.get("reason") or ""),
                remembered.get("seenAt") if isinstance(remembered.get("seenAt"), str) else None,
            )
    usage: dict = {}
    tools, reason, cause = providers.probe_native_tools(config, usage_out=usage)
    ledger.record_housekeeping_usage(
        user_key, usage, note="capability-probe", llm_config_id=config.config_id
    )
    if tools is None:
        return ChatCapabilities(False, False, SOURCE_UNKNOWN, reason)
    # A server's reply schema support is not tried: the fenced protocol and the
    # validator stand in for it on every endpoint the table does not know.
    found = ChatCapabilities(tools, False, SOURCE_TRIAL, reason)
    model_catalog.remember_chat_capabilities(
        user_key, config.api_type, config.base_url, config.model,
        {"tools": found.tools, "structuredOutput": found.structured_output, "reason": reason, "cause": cause},
    )
    return found


def record_native_refusal(config: ProviderConfig, user_key: str, reason: str) -> None:
    """Remember that *config*'s endpoint refused a run's native tools, which
    the run's fenced retry then got past. For an endpoint the table knows, the
    table still answers: a refusal there means a tool the run offered was
    malformed, which is logged instead."""
    import logging

    from utk_curio.backend.app.agents.infrastructure import providers
    from utk_curio.backend.app.agents.repositories import model_catalog

    if config.api_type == "testing":
        return
    if _from_table(config) is not None:
        logging.getLogger(__name__).warning(
            "%s refused the native tools a run offered (%s); the run used the fenced protocol",
            config.api_type, reason,
        )
        return
    model_catalog.remember_chat_capabilities(
        user_key, config.api_type, config.base_url, config.model,
        {"tools": False, "structuredOutput": False,
         "reason": f"the endpoint refused a run's native tools: {reason}", "cause": providers.TRIAL_REFUSED},
    )
