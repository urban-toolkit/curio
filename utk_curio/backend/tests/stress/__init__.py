"""Multi-user load harness: many users running the shipped examples at once.

The E2E suite answers "does this dataflow work?" for one user in a browser.
This package answers "does it still work when N of them do it together?" by
driving the same examples over the same HTTP endpoints the canvas uses, with no
browser -- which is what makes 100 concurrent users affordable in CI. In rooms
of a few users, each also opens a tab of a shared dataflow, a pycrdt doc synced
over Socket.IO as the canvas syncs it, and types and drags in it.

See ``run.py`` for the entry point, ``driver.py`` for one user's session,
``sockets.py`` for its tab, and ``backend_probe.py`` for what is read of the
backend's process and its doc files.
"""
