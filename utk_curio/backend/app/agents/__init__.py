"""Hookable-agents backend module.

Owns the agent-manifest contract, capability model, and (in later phases)
the definition/import/project-template/attachment lifecycle. Kept as a
self-contained ``agents/`` package with narrow public entry points so agent
and LLM behavior does not leak into flow/node/dataset modules.

User-facing overview: ``docs/AGENT-CATALOG.md``. Canonical manifest spec:
``docs/schemas/agent-package.v1.json``.
"""
