"""Pure package rules: the manifest contract, ids and version grammar, families, appearance, dependency scanning, the sandbox wire contract, spec readers. No I/O, no Flask, no subprocess.

Layer of the packages package (memo dev/143, B1). Kept import-free so no layer
import can start a cycle; import the module you need explicitly.
"""
