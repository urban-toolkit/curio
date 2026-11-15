"""Isolated nodes' memory as a cgroup limit, in the parts that run anywhere.

``isolation/node_cgroups.py`` writes cgroups only where a container may
arrange its own: Linux, root, a read-write cgroup v2 mount, and private cgroup
and process namespaces. Anywhere else, a write could move every process of a
host, so :func:`unavailable` is a pure function of what it reads, handed in
here, and each case names why nodes keep the address-space cap.

The rest is what a run's place says of it: a node stopped at its budget is
told its budget, and a SIGKILL with no budget reached is a signal like any
other. And a zygote whose children have a cgroup leaves their allocators as
the sandbox server set them.

What needs a container's cgroups is in ``test_isolation_linux.py``.

Run:  pytest utk_curio/sandbox/tests/test_node_cgroups.py -v
"""

import pytest

#: /proc/self/mountinfo as a container with writable cgroups reads it.
MOUNTINFO_RW = (
    "1078 1077 0:84 / / rw,relatime - overlay overlay rw,lowerdir=/l,upperdir=/u,workdir=/w\n"
    "1083 1081 0:30 / /sys/fs/cgroup rw,nosuid,nodev,noexec,relatime - cgroup2 cgroup rw,nsdelegate\n"
)
#: The same container without Docker's writable-cgroups option.
MOUNTINFO_RO = MOUNTINFO_RW.replace("/sys/fs/cgroup rw,", "/sys/fs/cgroup ro,")
#: A host on cgroup v1: a tmpfs at /sys/fs/cgroup, a mount per controller below it.
MOUNTINFO_V1 = (
    "25 22 0:23 / /sys/fs/cgroup ro,nosuid,nodev,noexec shared:9 - tmpfs tmpfs ro,mode=755\n"
    "30 25 0:27 / /sys/fs/cgroup/memory rw,nosuid,nodev,noexec shared:13 - cgroup cgroup rw,memory\n"
)

#: A container's own namespaces, any inode but the host's.
PRIVATE_CGROUP_NAMESPACE = 4026532610
PRIVATE_PID_NAMESPACE = 4026532611

CONTAINER = {
    "platform": "linux",
    "euid": 0,
    "mountinfo": MOUNTINFO_RW,
    "cgroup_namespace": PRIVATE_CGROUP_NAMESPACE,
    "pid_namespace": PRIVATE_PID_NAMESPACE,
    "own_cgroup": "/",
    "controllers": "cpuset cpu io memory hugetlb pids rdma misc",
}


def test_a_private_writable_cgroup_v2_mount_as_root_holds_nodes():
    from utk_curio.sandbox.isolation import node_cgroups

    assert node_cgroups.unavailable(**CONTAINER) is None
    # And once laid out, from its servers' cgroup.
    assert node_cgroups.unavailable(**{**CONTAINER, "own_cgroup": "/curio"}) is None


@pytest.mark.parametrize("change,reason", [
    ({"platform": "darwin"}, "no-linux"),
    ({"platform": "win32"}, "no-linux"),
    ({"euid": 1000}, "not-root"),
    ({"mountinfo": MOUNTINFO_V1}, "no-cgroup2"),
    ({"mountinfo": ""}, "no-cgroup2"),
    ({"cgroup_namespace": 0xEFFFFFFB}, "host-namespace"),
    ({"pid_namespace": 0xEFFFFFFC}, "host-pid-namespace"),
    ({"mountinfo": MOUNTINFO_RO}, "read-only"),
    ({"own_cgroup": "/../../system.slice/docker-1f2e.scope"}, "outside"),
    ({"controllers": "cpuset cpu io pids"}, "no-memory"),
])
def test_each_missing_condition_keeps_the_address_space_cap_and_says_why(change, reason):
    from utk_curio.sandbox.isolation import node_cgroups

    assert node_cgroups.unavailable(**{**CONTAINER, **change}) == reason
    assert node_cgroups.REASONS[reason]


def test_a_root_launch_in_the_hosts_namespaces_writes_nothing_even_where_it_could():
    """Root on a host, its cgroup2 mount read-write: the one case where a write
    would reach every process of the host."""
    from utk_curio.sandbox.isolation import node_cgroups

    host = {**CONTAINER, "cgroup_namespace": 0xEFFFFFFB, "pid_namespace": 0xEFFFFFFC,
            "own_cgroup": "/user.slice/user-0.slice/session-1.scope"}
    assert node_cgroups.unavailable(**host) == "host-namespace"


def test_every_reason_is_short_enough_for_the_monitor():
    from utk_curio.sandbox.isolation import node_cgroups

    for key, words in node_cgroups.REASONS.items():
        assert 0 < len(words) <= 120, key


def test_memory_events_are_read_as_counters():
    from utk_curio.sandbox.isolation import node_cgroups

    events = "low 0\nhigh 0\nmax 18\noom 1\noom_kill 3\n"
    assert node_cgroups.counters(events) == {"low": 0, "high": 0, "max": 18, "oom": 1, "oom_kill": 3}
    assert node_cgroups.counters("") == {}


LIMITS = {"memory_mb": 24576, "cpu_seconds": 300}


def _describe(**kwargs):
    from utk_curio.sandbox.isolation import supervisor

    return supervisor.describe_child_death(wall_timeout=300, limits=LIMITS, **kwargs)


def test_a_node_stopped_at_its_budget_is_told_its_budget():
    from utk_curio.sandbox.isolation import supervisor

    memory = {"limit": "cgroup", "budget_hit": True, "peak_bytes": None}
    message = _describe(exit_code=None, signal_number=9, timed_out=False, memory=memory)
    assert message.startswith(
        "This node used more than its memory budget of 24576 MB (--exec-memory-mb), so it was stopped."
    ), message
    assert "peak" not in message
    assert supervisor.classify_child_death(None, 9, False, memory=memory) == "oom"


def test_where_the_kernel_says_the_peak_the_message_names_it():
    memory = {"limit": "cgroup", "budget_hit": True, "peak_bytes": 24576 * 1024 * 1024}
    message = _describe(exit_code=None, signal_number=9, timed_out=False, memory=memory)
    assert "Its peak was 24576 MB." in message, message


def test_a_sigkill_with_no_budget_reached_reads_signal_9():
    """The place's memory.events tells the two apart, so a node killed for
    another reason is not told it ran out of memory."""
    from utk_curio.sandbox.isolation import supervisor

    memory = {"limit": "cgroup", "budget_hit": False, "peak_bytes": None}
    message = _describe(exit_code=None, signal_number=9, timed_out=False, memory=memory)
    assert message == "This node was killed by signal 9.", message
    assert supervisor.classify_child_death(None, 9, False, memory=memory) == "signal"


def test_a_deadline_is_still_a_deadline_in_a_place():
    memory = {"limit": "cgroup", "budget_hit": False, "peak_bytes": None}
    message = _describe(exit_code=None, signal_number=9, timed_out=True, memory=memory)
    assert "--exec-timeout" in message


def test_under_a_cgroup_the_zygote_leaves_the_servers_allocators():
    """The address-space cap's fitting (the arena cap, Arrow on glibc) is the
    cap's alone: under a cgroup the children keep what the server has, an
    operator's own pool among it."""
    from utk_curio.sandbox.isolation import lifecycle, node_cgroups

    server = {"MALLOC_ARENA_MAX": "96", "ARROW_DEFAULT_MEMORY_POOL": "mimalloc", "PATH": "/bin"}
    env = lifecycle.zygote_environment({"memory_mb": 4096}, server, memory_limit=node_cgroups.CGROUP)
    assert env == server
    capped = lifecycle.zygote_environment({"memory_mb": 4096}, server,
                                          memory_limit=node_cgroups.ADDRESS_SPACE)
    assert (capped["MALLOC_ARENA_MAX"], capped["ARROW_DEFAULT_MEMORY_POOL"]) == ("16", "system")
