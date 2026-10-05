"""HTTP endpoints for the Agents Catalog — ``/api/agents`` (memo dev/142, B4; re-derived on enh/agent-catalog).

One blueprint, registered from the resource modules that import it: ``attachments``, ``catalog``, ``lifecycle``, ``llm``, ``proposals``, ``solve``, ``turns``. Handler bodies are the ones ``routes.py`` had; ``routes/common.py`` holds the blueprint and the shared helpers.
"""

from utk_curio.backend.app.agents.routes.common import (
    _error,
    _llm_for_attachment,
    _map_agent_errors,
    _provider_error,
    _svc_error,
    agents_bp,
)
from utk_curio.backend.app.agents.routes import (
    attachments,
    catalog,
    lifecycle,
    llm,
    proposals,
    solve,
    turns,
)

__all__ = ["_error", "_llm_for_attachment", "_map_agent_errors", "_provider_error", "_svc_error", "agents_bp"]
