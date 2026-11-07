"""torch in Curio's image is the CUDA 12.9 build, and it runs on the GPU.

The Dockerfile installs torch 2.13.0+cu129 and torchvision 0.28.0+cu129, whose
wheels bring their own CUDA libraries; the GPU and the driver come from the
host, as for ``test_cuda_mlp.py``. This asks torch for the GPU the container
got (``docker-compose.ci-shards.yml``), checks that torch has kernels the
device runs (the RTX PRO 6000's sm_120 needs a CUDA 12.8 or later build), and
multiplies two matrices on the GPU against the CPU. On arcade's R550 driver it
runs under CUDA's minor-version compatibility.

Kernels the device runs: CUDA runs a cubin built for sm_XY on any device of
compute capability X.Z with Z >= Y, so the wheel's sm_86 serves utk-desktop-03's
RTX 4080 (sm_89), which the cu129 wheels build no cubin of their own for. A cubin
with a feature suffix (sm_90a) runs on its own architecture only. PTX does not
count: under minor-version compatibility (arcade) the driver cannot compile a
newer toolkit's PTX, so the device needs a cubin.

Marked ``cuda``: test-gpu runs it in its container with ``-m cuda``, beside
``test_cuda_mlp.py``. Without a usable GPU it fails, never skips.

Run:  python -m pytest utk_curio/sandbox/tests/test_cuda_torch.py -m cuda -v -s
"""

import pytest

#: The CUDA version of the torch build the Dockerfile installs.
TORCH_CUDA = "12.9"
#: The largest difference from the CPU's product a float32 matmul on the GPU may show.
TOLERANCE = 1e-3

NO_GPU = (
    "the container got no GPU, or the host has no NVIDIA Container Toolkit to hand it one "
    "(docker-compose.ci-shards.yml asks for it)"
)


def kernels_for(major, minor, arch_list):
    """The cubins in torch's arch list that a device of this compute capability runs."""
    runs = []
    for arch in arch_list:
        kind, _, number = arch.partition("_")
        digits = number.rstrip("abcdefghijklmnopqrstuvwxyz")
        if kind != "sm" or len(digits) < 2 or not digits.isdigit():
            continue
        built = (int(digits[:-1]), int(digits[-1]))
        if digits != number:
            fits = built == (major, minor)
        else:
            fits = built[0] == major and built[1] <= minor
        if fits:
            runs.append(arch)
    return runs


@pytest.mark.cuda
def test_torch_is_the_cuda_12_9_build_and_multiplies_on_the_gpu(record_property):
    """torch's CUDA build sees the GPU, has kernels for it, and its product matches the CPU's."""
    try:
        import torch
    except ImportError as error:
        pytest.fail(f"torch does not import ({error}); the Dockerfile's python_base installs it")
    assert torch.version.cuda == TORCH_CUDA, (
        f"torch {torch.__version__} is built for CUDA {torch.version.cuda}, not the Dockerfile's {TORCH_CUDA}")
    if not torch.cuda.is_available():
        pytest.fail(f"torch {torch.__version__} sees no GPU: {NO_GPU}")

    name = torch.cuda.get_device_name(0)
    major, minor = torch.cuda.get_device_capability(0)
    architecture = f"sm_{major}{minor}"
    kernels = kernels_for(major, minor, torch.cuda.get_arch_list())
    assert kernels, (
        f"torch {torch.__version__} has no kernels for {name} ({architecture}): "
        f"it has {torch.cuda.get_arch_list()}")

    generator = torch.Generator().manual_seed(1)
    a = torch.randn(256, 256, generator=generator)
    b = torch.randn(256, 256, generator=generator)
    on_the_gpu = (a.to("cuda") @ b.to("cuda")).cpu()
    difference = (on_the_gpu - a @ b).abs().max().item()

    build = f"torch {torch.__version__} (CUDA {torch.version.cuda}), torchvision "
    try:
        import torchvision

        build += torchvision.__version__
    except ImportError as error:
        pytest.fail(f"torchvision does not import ({error}); the Dockerfile's python_base installs it")
    print(f"torch build: {build}")
    print(f"torch device: {name}, {architecture}, runs {', '.join(kernels)}")
    print(f"Largest difference from the CPU's matmul: {difference:.3g}")
    record_property("torch_build", build)
    record_property("torch_device", f"{name}, {architecture}")
    record_property("torch_largest_difference", f"{difference:.3g}")
    assert difference < TOLERANCE, (
        f"the GPU's matmul is {difference:.3g} off the CPU's, over the {TOLERANCE:g} allowed")
