"""Processes, subprocesses and locks: the pip runner, the build workspace, the sandbox runtime and its harness, the lock modules.

Layer of the packages package (memo dev/143, B1). Kept import-free so no layer
import can start a cycle; import the module you need explicitly.
"""
