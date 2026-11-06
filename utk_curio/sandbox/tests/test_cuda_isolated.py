"""A node in an isolated child reaches the GPU through torch, at the deploy's budget.

The deploy runs each node in a child the zygote forks, as the ``curio-exec``
account, under the seccomp filter and an address-space cap of the zygote's
footprint plus ``--exec-memory-mb``: 24576 MB on dev and flow (deploy.yml's
site file), where torch's CUDA libraries map and CUDA starts. This starts such
a zygote itself, as ``test_isolation_linux.py``'s ``isolated_dropped`` does,
and runs a node there that imports torch, asks for the GPU and multiplies two
matrices on it against the CPU.

Marked ``cuda``: test-gpu runs it in its container with ``-m cuda``, beside
``test_cuda_torch.py``. Without the GPU, the account or the seccomp filter it
fails, never skips.

Run:  python -m pytest utk_curio/sandbox/tests/test_cuda_isolated.py -m cuda -v -s
"""

import os
import pwd

import pytest

#: The account the deploy's children run as, which the Dockerfile creates.
EXEC_USER = "curio-exec"
#: Each node's budget on dev and flow (deploy.yml's site file), in MB.
BUDGET_MB = 24576
#: The largest difference from the CPU's product a float32 matmul on the GPU may show.
TOLERANCE = 1e-3

NO_GPU = (
    "the container got no GPU, or the host has no NVIDIA Container Toolkit to hand it one "
    "(docker-compose.ci-shards.yml asks for it)"
)

#: The node, as a function body: what its child is, and torch on the GPU from inside it.
NODE = '''\
    import os
    import resource

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch

    with open("/proc/self/status") as status:
        seccomp = next(line.split()[1] for line in status if line.startswith("Seccomp:"))
    seen = {
        "uid": os.getuid(),
        "seccomp": seccomp,
        "address_space": resource.getrlimit(resource.RLIMIT_AS)[0],
        "torch": torch.__version__,
        "cuda": torch.cuda.is_available(),
    }
    if seen["cuda"]:
        generator = torch.Generator().manual_seed(1)
        a = torch.randn(256, 256, generator=generator)
        b = torch.randn(256, 256, generator=generator)
        seen["difference"] = ((a.cuda() @ b.cuda()).cpu() - a @ b).abs().max().item()
        major, minor = torch.cuda.get_device_capability(0)
        seen["device"] = f"{torch.cuda.get_device_name(0)}, sm_{major}{minor}"
    return seen
'''


@pytest.fixture
def isolated_as_deployed(tmp_path_factory, monkeypatch):
    """A zygote whose children run as the deploy's do: as ``curio-exec``, under
    the seccomp filter, at the deploy's budget."""
    from utk_curio.sandbox.isolation import lifecycle, runner
    from utk_curio.sandbox.util.db import init_db, release_connection

    if os.getuid() != 0:
        pytest.fail("the zygote drops to the execution account only when started as root, "
                    "as test-gpu starts this in its container")
    try:
        pwd.getpwnam(EXEC_USER)
    except KeyError:
        pytest.fail(f"the {EXEC_USER} account does not exist; the Dockerfile creates it")
    try:
        import pyseccomp  # noqa: F401
    except ImportError as error:
        pytest.fail(f"pyseccomp does not import ({error}), so a child would run with no seccomp filter")

    root = tmp_path_factory.mktemp("cuda-isolated", numbered=True)
    # pytest makes its folders 0700 and root's: 0711 up to the first folder the
    # account can traverse, so the child reaches its scratch folder and lists none.
    folder = root
    while not os.stat(folder).st_mode & 0o001:
        os.chmod(folder, 0o711)
        folder = folder.parent

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(root))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(root / "data"))
    monkeypatch.setenv("CURIO_EXEC_SOCKET", str(root / "zygote.sock"))
    # torch's import and CUDA's start take seconds, more on a busy runner.
    monkeypatch.setenv("CURIO_EXEC_TIMEOUT", "180")
    monkeypatch.setenv("CURIO_EXEC_MEMORY_MB", str(BUDGET_MB))
    monkeypatch.setenv("CURIO_EXEC_USER", EXEC_USER)

    release_connection()
    init_db()
    os.chmod(root / "data", 0o711)

    config = runner.IsolationConfig.from_environment()
    lifecycle.ensure_running(config, exec_user=EXEC_USER, require_seccomp=True)
    try:
        yield config
    finally:
        lifecycle.shutdown()
        release_connection()


@pytest.mark.cuda
def test_a_node_in_an_isolated_child_reaches_the_gpu_through_torch(isolated_as_deployed, record_property):
    """As ``curio-exec``, under seccomp and the deploy's cap, torch imports, sees the
    GPU and multiplies on it as the CPU does."""
    from utk_curio.sandbox.isolation import runner
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = runner.execute_isolated(
        NODE, "", "curio.builtin/computation-analysis", "",
        save_dataset=False, config=isolated_as_deployed,
    )
    if not result["output"]["path"]:
        cause = ("its budget is too small to map torch's CUDA libraries"
                 if "failed to map segment" in result["stderr"] else "see its error")
        pytest.fail(f"the node failed in its isolated child, {cause}: {result['stderr'][-2000:]}")
    seen = load_from_duckdb(result["output"]["path"])

    exec_uid = pwd.getpwnam(EXEC_USER).pw_uid
    assert seen["uid"] == exec_uid, f"the child ran as uid {seen['uid']}, not {EXEC_USER} ({exec_uid})"
    assert seen["seccomp"] == "2", f"the child's seccomp mode is {seen['seccomp']}, not the filter's 2"
    budget = BUDGET_MB << 20
    assert budget < seen["address_space"] < budget + (8 << 30), (
        f"the child's address space is capped at {seen['address_space']} bytes, "
        f"not its footprint plus {BUDGET_MB} MB")
    if not seen["cuda"]:
        pytest.fail(f"torch {seen['torch']} sees no GPU in the isolated child: {NO_GPU}")

    print(f"Isolated child: uid {seen['uid']}, seccomp {seen['seccomp']}, "
          f"address space {seen['address_space'] >> 20} MiB, torch {seen['torch']}")
    print(f"Isolated child's device: {seen['device']}")
    print(f"Largest difference from the CPU's matmul: {seen['difference']:.3g}")
    record_property("isolated_child_address_space_mib", str(seen["address_space"] >> 20))
    record_property("isolated_child_device", seen["device"])
    record_property("isolated_child_largest_difference", f"{seen['difference']:.3g}")
    assert seen["difference"] < TOLERANCE, (
        f"the GPU's matmul in the isolated child is {seen['difference']:.3g} off the CPU's, "
        f"over the {TOLERANCE:g} allowed")
