"""Pure agent rules: manifests, roster, graph topology, contracts, reply schemas, result and failure readers. No I/O, no Flask, no provider.

Layer of the agents package (memo dev/142, B1). Kept import-free so no layer
import can start a cycle; import the module you need explicitly.
"""
