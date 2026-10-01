"""Everything that reads or writes a package store: the per-user store, defaults, publisher records, seed state, staged build artifacts.

Layer of the packages package (memo dev/143, B1). Kept import-free so no layer
import can start a cycle; import the module you need explicitly.
"""
