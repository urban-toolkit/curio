"""What a node's run writes of progress bars, caught as the sandbox catches it.

A run of a node keeps what its code writes to stderr as the node's output: the
sandbox's in-process worker and an isolated child both swap ``sys.stderr`` for
a buffer while the node's code runs (``contextlib.redirect_stderr``), and tqdm
writes a bar to the ``sys.stderr`` of the moment the bar is made, each refresh
after a carriage return. Transformers draws a "Loading weights" bar as it reads
a checkpoint's weights, while its progress bars are on, as they are unless
someone turns them off, and how many refreshes the bar shows depends on how
fast the load goes. Example 31's Track Objects showed one line of it more on
some runs than on others, which moved the example's full page 0.13% (#1567's
runs 44524194665 and 44524199660).

A test runs a node inside :func:`stderr_of_a_run`, after
:func:`transformers_bars_on`; :func:`assert_no_bar` holds what the run wrote,
and :func:`assert_bars_draw` checks that a bar drawn afterwards, with tqdm or
with Transformers, still shows. Transformers and tqdm are imported inside the
functions, so a checkout without them fails each test that calls one.
"""
from __future__ import annotations

import contextlib
import io


@contextlib.contextmanager
def stderr_of_a_run():
    """A buffer that catches what goes to stderr inside the block, as the
    sandbox catches a node run's stderr."""
    caught = io.StringIO()
    with contextlib.redirect_stderr(caught):
        yield caught


def transformers_bars_on(monkeypatch) -> None:
    """Transformers' progress bars on for the test, as they are by default,
    whatever an earlier test in this process left them as."""
    from transformers.utils import logging

    monkeypatch.setattr(logging, "_tqdm_active", True)


def assert_no_bar(said: str, node: str) -> None:
    """*said*, what a run of *node* wrote to stderr, holds no progress bar:
    no "Loading weights" and no carriage return, which starts each refresh of
    a tqdm bar."""
    assert "Loading weights" not in said and "\r" not in said, (
        f"A run of {node} wrote a progress bar to its stderr, which its node shows as its output, one line "
        f"more or fewer from run to run: {said!r}"
    )


def assert_bars_draw() -> None:
    """Transformers' progress bars are on, and a bar a node's code draws now,
    with tqdm or with Transformers, shows in its run's stderr."""
    import tqdm
    from transformers.utils import logging

    assert logging.is_progress_bar_enabled(), "Transformers' progress bars were left off after the run"
    with stderr_of_a_run() as caught:
        for _ in tqdm.tqdm(range(2), desc="A bar of tqdm's"):
            pass
        for _ in logging.tqdm(range(2), desc="A bar of Transformers'"):
            pass
    said = caught.getvalue()
    assert "A bar of tqdm's" in said and "A bar of Transformers'" in said, (
        f"A bar a node's code draws after the run does not show in its stderr: {said!r}"
    )
