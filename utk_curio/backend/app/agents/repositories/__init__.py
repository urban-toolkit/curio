"""Everything that reads or writes an agent store: definitions, imports, publications, project lockfile, sessions, ledger, model catalog, LLM configurations, catalog settings.

Layer of the agents package (memo dev/142, B1). Kept import-free so no layer
import can start a cycle; import the module you need explicitly.
"""
