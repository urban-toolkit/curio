"""torch in Curio's image is the CUDA 12.9 build, and it runs on the GPU.

The Dockerfile installs torch 2.13.0+cu129 and torchvision 0.28.0+cu129, whose
wheels bring their own CUDA libraries; the GPU and the driver come from the
host, as for ``test_cuda_mlp.py``. This asks torch for the GPU the container
got (``docker-compose.ci-shards.yml``), checks that torch has kernels for the
device's own architecture (the RTX PRO 6000's sm_120 needs a CUDA 12.8 or later
build), and multiplies two matrices on the GPU against the CPU. On arcade's
R550 driver it runs under CUDA's minor-version compatibility.

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
    assert architecture in torch.cuda.get_arch_list(), (
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
    print(f"torch device: {name}, {architecture}")
    print(f"Largest difference from the CPU's matmul: {difference:.3g}")
    record_property("torch_build", build)
    record_property("torch_device", f"{name}, {architecture}")
    record_property("torch_largest_difference", f"{difference:.3g}")
    assert difference < TOLERANCE, (
        f"the GPU's matmul is {difference:.3g} off the CPU's, over the {TOLERANCE:g} allowed")
