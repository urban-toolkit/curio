"""Multi-user load harness: many users running the shipped examples at once.

The E2E suite answers "does this dataflow work?" for one user in a browser.
This package answers "does it still work when N of them do it together?" by
driving the same examples over the same HTTP endpoints the canvas uses, with no
browser -- which is what makes 100 concurrent users affordable in CI.

See ``run.py`` for the entry point and ``driver.py`` for one user's session.
"""
