"""``open_files.raise_limit``: up to the hard limit, never down, and a step down
where macOS refuses a soft limit above its per-process maximum."""
import pytest

resource = pytest.importorskip("resource")


class _Limits:
    """getrlimit and setrlimit on a pair of numbers, refusing a soft limit above
    *refuse_above* as macOS refuses one above ``kern.maxfilesperproc``."""

    def __init__(self, soft, hard, refuse_above=None):
        self.limits = (soft, hard)
        self.refuse_above = refuse_above

    def getrlimit(self, which):
        return self.limits

    def setrlimit(self, which, limits):
        if self.refuse_above is not None and limits[0] > self.refuse_above:
            raise ValueError("current limit exceeds maximum limit")
        self.limits = limits


@pytest.fixture
def open_files():
    # Imported per test, so a tree without the module fails each test here
    # while the rest of its unit part still runs.
    from utk_curio.common import open_files
    return open_files


@pytest.fixture
def limits(monkeypatch):
    def make(soft, hard, refuse_above=None):
        fake = _Limits(soft, hard, refuse_above)
        monkeypatch.setattr(resource, "getrlimit", fake.getrlimit)
        monkeypatch.setattr(resource, "setrlimit", fake.setrlimit)
        return fake
    return make


def test_dockers_default_rises_to_the_wanted_limit(open_files, limits):
    fake = limits(1024, 524288)
    assert open_files.raise_limit() == open_files.WANTED
    assert fake.limits == (open_files.WANTED, 524288)


def test_the_soft_limit_stops_at_the_hard_limit(open_files, limits):
    limits(256, 4096)
    assert open_files.raise_limit() == 4096


def test_a_higher_soft_limit_is_kept(open_files, limits):
    fake = limits(1048576, 1048576)
    assert open_files.raise_limit() == 1048576
    assert fake.limits == (1048576, 1048576)


def test_an_unlimited_soft_limit_is_kept(open_files, limits):
    limits(resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    assert open_files.raise_limit() == resource.RLIM_INFINITY


def test_a_refused_limit_steps_down(open_files, limits):
    fake = limits(256, resource.RLIM_INFINITY, refuse_above=24576)
    assert open_files.raise_limit() == 24576
    assert fake.limits[0] == 24576


def test_a_limit_refused_at_every_step_is_left_as_it_was(open_files, limits):
    fake = limits(256, resource.RLIM_INFINITY, refuse_above=1000)
    assert open_files.raise_limit() == 256
    assert fake.limits[0] == 256
