"""Curio's container runs a model on the GPU with the image's CUDA.

The image's CUDA 12.9 is NVIDIA's pip packages that its torch build brings
(the Dockerfile's ``python_base``), NVRTC among them. The GPU and the driver's
``libcuda.so.1`` come from the host: its NVIDIA driver and its NVIDIA
Container Toolkit hand them to a container that asks for a GPU, as test-gpu's
``docker-compose.ci-shards.yml`` does. This runs a tiny MLP, 64 to 32 to 10
units (``cuda_mlp.npy``, written by ``cuda_mlp_weights.py``), with nothing but
ctypes and numpy:

- NVML (``libnvidia-ml.so.1``) reads the driver's release;
- the driver API (``libcuda.so.1``) reads the device and loads and launches
  the kernel;
- NVRTC (``libnvrtc.so.12``) compiles the one kernel, matmul plus bias plus
  an optional ReLU, from CUDA C to a cubin for this device's own
  architecture. A cubin, not PTX: arcade's R550 driver runs CUDA 12.9 under
  minor-version compatibility, which cannot compile a newer toolkit's PTX.

The forward pass must match numpy's on the CPU to within 1e-4.

The tests marked ``cuda`` run only in test-gpu, inside its container, with
``-m cuda``; the sandbox conftest leaves them out of every other run. Without
a usable GPU they fail, never skip, and say what is missing.

Run:  python -m pytest utk_curio/sandbox/tests/test_cuda_mlp.py -m cuda -v -s
"""

import ctypes
import glob
import sys

import numpy as np
import pytest

from utk_curio.sandbox.tests import cuda_mlp_weights

#: The CUDA of the torch build the Dockerfile installs, whose NVRTC this compiles with.
CUDA_VERSION = (12, 9)
#: The largest difference from numpy the GPU's forward pass may show.
TOLERANCE = 1e-4
BATCH = 256

NO_GPU = (
    "the container got no GPU, or the host has no NVIDIA Container Toolkit to hand it one "
    "(docker-compose.ci-shards.yml asks for it: driver nvidia, capabilities [gpu], "
    "NVIDIA_DRIVER_CAPABILITIES=compute,utility)"
)
#: What a driver API error most likely means here, by its CUresult.
CAUSES = {
    35: "the host's NVIDIA driver is older than CUDA 12.9 runs on, which is R525",
    100: "the container sees no GPU device: " + NO_GPU,
    209: "the cubin was not built for this device's architecture",
    804: "the host's driver runs CUDA 12.9 only on a newer driver branch for this GPU",
}

KERNEL = r"""
extern "C" __global__ void dense(const float* x, const float* w, const float* b, float* y,
                                 int rows, int fan_in, int fan_out, int relu)
{
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;
    if (row >= rows || col >= fan_out) return;
    float sum = b[col];
    for (int k = 0; k < fan_in; ++k) sum += x[row * fan_in + k] * w[k * fan_out + col];
    y[row * fan_out + col] = (relu && sum < 0.0f) ? 0.0f : sum;
}
"""

CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR = 75
CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR = 76


def _load(names, why):
    """The first of ``names`` that loads, or a failure that says what its absence means."""
    errors = []
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError as error:
            errors.append(str(error))
    pytest.fail(f"cannot load {names[0]}: {why} ({'; '.join(errors)})")


def _nvrtc():
    """NVRTC 12: NVIDIA's pip package of it (``nvidia/cuda_nvrtc/lib``), else the loader's path."""
    wheels = sorted(path for entry in sys.path for path in glob.glob(f"{entry}/nvidia/cuda_nvrtc/lib/libnvrtc.so.12"))
    return _load([*wheels, "libnvrtc.so.12"],
                 "the image has no CUDA 12 NVRTC (the Dockerfile's torch build brings nvidia-cuda-nvrtc-cu12)")


def _driver():
    """The driver API, ``libcuda.so.1``, with the argument types of every call made here."""
    cuda = _load(["libcuda.so.1"], NO_GPU)
    c_int, c_uint, c_size, c_ptr = ctypes.c_int, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p
    signatures = {
        "cuGetErrorName": [c_int, ctypes.POINTER(ctypes.c_char_p)],
        "cuInit": [c_uint],
        "cuDriverGetVersion": [ctypes.POINTER(c_int)],
        "cuDeviceGetCount": [ctypes.POINTER(c_int)],
        "cuDeviceGet": [ctypes.POINTER(c_int), c_int],
        "cuDeviceGetName": [ctypes.c_char_p, c_int, c_int],
        "cuDeviceGetAttribute": [ctypes.POINTER(c_int), c_int, c_int],
        "cuDeviceTotalMem_v2": [ctypes.POINTER(c_size), c_int],
        "cuDevicePrimaryCtxRetain": [ctypes.POINTER(c_ptr), c_int],
        "cuDevicePrimaryCtxRelease_v2": [c_int],
        "cuCtxSetCurrent": [c_ptr],
        "cuCtxSynchronize": [],
        "cuModuleLoadData": [ctypes.POINTER(c_ptr), c_ptr],
        "cuModuleUnload": [c_ptr],
        "cuModuleGetFunction": [ctypes.POINTER(c_ptr), c_ptr, ctypes.c_char_p],
        "cuMemAlloc_v2": [ctypes.POINTER(ctypes.c_uint64), c_size],
        "cuMemFree_v2": [ctypes.c_uint64],
        "cuMemcpyHtoD_v2": [ctypes.c_uint64, c_ptr, c_size],
        "cuMemcpyDtoH_v2": [c_ptr, ctypes.c_uint64, c_size],
        "cuLaunchKernel": [c_ptr, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint, c_ptr,
                           ctypes.POINTER(c_ptr), ctypes.POINTER(c_ptr)],
    }
    for name, argtypes in signatures.items():
        function = getattr(cuda, name)
        function.argtypes = argtypes
        function.restype = c_int
    return cuda


def _check(cuda, result, call):
    """Fail with the driver's name for a CUresult that is not success, and what it likely means."""
    if result == 0:
        return
    name = ctypes.c_char_p()
    cuda.cuGetErrorName(result, ctypes.byref(name))
    label = name.value.decode() if name.value else "an unknown error"
    cause = CAUSES.get(result)
    pytest.fail(f"{call} failed with {label} ({result})" + (f": {cause}" if cause else ""))


def _driver_release():
    """The host driver's release, such as 550.163.01, from NVML."""
    nvml = _load(["libnvidia-ml.so.1"], "NVML is missing, so the container lacks the utility capability; " + NO_GPU)
    if nvml.nvmlInit_v2() != 0:
        pytest.fail("NVML did not start: " + NO_GPU)
    try:
        release = ctypes.create_string_buffer(96)
        if nvml.nvmlSystemGetDriverVersion(release, ctypes.c_uint(len(release))) != 0:
            pytest.fail("NVML gave no driver version")
        return release.value.decode()
    finally:
        nvml.nvmlShutdown()


def _nvrtc_version(nvrtc):
    major, minor = ctypes.c_int(), ctypes.c_int()
    assert nvrtc.nvrtcVersion(ctypes.byref(major), ctypes.byref(minor)) == 0, "nvrtcVersion failed"
    return major.value, minor.value


def _compile_cubin(nvrtc, architecture):
    """The kernel as a cubin for ``architecture`` (such as sm_90), compiled by NVRTC."""
    nvrtc.nvrtcGetErrorString.restype = ctypes.c_char_p
    program = ctypes.c_void_p()

    def check(result, call):
        if result != 0:
            pytest.fail(f"{call} failed: {nvrtc.nvrtcGetErrorString(result).decode()}")

    check(nvrtc.nvrtcCreateProgram(ctypes.byref(program), KERNEL.encode(), b"dense.cu", 0, None, None),
          "nvrtcCreateProgram")
    try:
        options = (ctypes.c_char_p * 1)(f"--gpu-architecture={architecture}".encode())
        compiled = nvrtc.nvrtcCompileProgram(program, 1, options)
        if compiled != 0:
            size = ctypes.c_size_t()
            nvrtc.nvrtcGetProgramLogSize(program, ctypes.byref(size))
            log = ctypes.create_string_buffer(size.value)
            nvrtc.nvrtcGetProgramLog(program, log)
            pytest.fail(f"NVRTC could not compile the kernel for {architecture}: "
                        f"{nvrtc.nvrtcGetErrorString(compiled).decode()}\n{log.value.decode()}")
        size = ctypes.c_size_t()
        check(nvrtc.nvrtcGetCUBINSize(program, ctypes.byref(size)), "nvrtcGetCUBINSize")
        cubin = ctypes.create_string_buffer(size.value)
        check(nvrtc.nvrtcGetCUBIN(program, cubin), "nvrtcGetCUBIN")
        return cubin
    finally:
        nvrtc.nvrtcDestroyProgram(ctypes.byref(program))


def _forward_on_the_gpu(cuda, function, x, layers):
    """The MLP's output for ``x``: one launch of the kernel per layer, ReLU on all but the last."""
    allocated = []

    def allocate(nbytes):
        pointer = ctypes.c_uint64()
        _check(cuda, cuda.cuMemAlloc_v2(ctypes.byref(pointer), nbytes), "cuMemAlloc")
        allocated.append(pointer)
        return pointer

    def upload(array):
        array = np.ascontiguousarray(array, dtype=np.float32)
        pointer = allocate(array.nbytes)
        _check(cuda, cuda.cuMemcpyHtoD_v2(pointer, array.ctypes.data, array.nbytes), "cuMemcpyHtoD")
        return pointer

    block = 16
    rows = x.shape[0]
    try:
        current = upload(x)
        for index, (w, b) in enumerate(layers):
            fan_in, fan_out = w.shape
            out = allocate(rows * fan_out * 4)
            relu = 1 if index < len(layers) - 1 else 0
            arguments = [current, upload(w), upload(b), out,
                         ctypes.c_int(rows), ctypes.c_int(fan_in), ctypes.c_int(fan_out), ctypes.c_int(relu)]
            parameters = (ctypes.c_void_p * len(arguments))(
                *(ctypes.cast(ctypes.pointer(argument), ctypes.c_void_p) for argument in arguments))
            grid = ((fan_out + block - 1) // block, (rows + block - 1) // block, 1)
            _check(cuda, cuda.cuLaunchKernel(function, *grid, block, block, 1, 0, None, parameters, None),
                   "cuLaunchKernel")
            _check(cuda, cuda.cuCtxSynchronize(), "cuCtxSynchronize")
            current = out
        result = np.empty((rows, layers[-1][0].shape[1]), dtype=np.float32)
        _check(cuda, cuda.cuMemcpyDtoH_v2(result.ctypes.data, current, result.nbytes), "cuMemcpyDtoH")
        return result
    finally:
        for pointer in allocated:
            cuda.cuMemFree_v2(pointer)


def _forward_on_the_cpu(x, layers):
    for index, (w, b) in enumerate(layers):
        x = x @ w + b
        if index < len(layers) - 1:
            x = np.maximum(x, 0)
    return x


@pytest.mark.cuda
def test_the_image_carries_cuda_12_9_nvrtc(record_property):
    """The NVRTC the MLP compiles with is the CUDA of the Dockerfile's torch build."""
    nvrtc_version = _nvrtc_version(_nvrtc())
    assert nvrtc_version == CUDA_VERSION, f"NVRTC is CUDA {nvrtc_version}, not the Dockerfile's {CUDA_VERSION}"
    print("CUDA NVRTC: {}.{}".format(*nvrtc_version))
    record_property("cuda_nvrtc", "{}.{}".format(*nvrtc_version))


@pytest.mark.cuda
def test_a_tiny_mlp_runs_on_the_gpu_and_matches_numpy(record_property):
    """The forward pass on the GPU, through NVRTC and the driver API, against numpy's on the CPU."""
    layers = cuda_mlp_weights.layers(np.load(cuda_mlp_weights.WEIGHTS_FILE))
    x = np.random.default_rng(1).standard_normal((BATCH, cuda_mlp_weights.LAYERS[0])).astype(np.float32)
    nvrtc = _nvrtc()
    cuda = _driver()
    release = _driver_release()

    _check(cuda, cuda.cuInit(0), "cuInit")
    driver_cuda = ctypes.c_int()
    _check(cuda, cuda.cuDriverGetVersion(ctypes.byref(driver_cuda)), "cuDriverGetVersion")
    count = ctypes.c_int()
    _check(cuda, cuda.cuDeviceGetCount(ctypes.byref(count)), "cuDeviceGetCount")
    if count.value < 1:
        pytest.fail("the driver lists no GPU: " + NO_GPU)
    device = ctypes.c_int()
    _check(cuda, cuda.cuDeviceGet(ctypes.byref(device), 0), "cuDeviceGet")
    name = ctypes.create_string_buffer(256)
    _check(cuda, cuda.cuDeviceGetName(name, len(name), device), "cuDeviceGetName")
    major, minor = ctypes.c_int(), ctypes.c_int()
    _check(cuda, cuda.cuDeviceGetAttribute(ctypes.byref(major), CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR, device),
           "cuDeviceGetAttribute")
    _check(cuda, cuda.cuDeviceGetAttribute(ctypes.byref(minor), CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MINOR, device),
           "cuDeviceGetAttribute")
    memory = ctypes.c_size_t()
    _check(cuda, cuda.cuDeviceTotalMem_v2(ctypes.byref(memory), device), "cuDeviceTotalMem")

    toolkit = _nvrtc_version(nvrtc)
    cubin = _compile_cubin(nvrtc, f"sm_{major.value}{minor.value}")

    context = ctypes.c_void_p()
    _check(cuda, cuda.cuDevicePrimaryCtxRetain(ctypes.byref(context), device), "cuDevicePrimaryCtxRetain")
    try:
        _check(cuda, cuda.cuCtxSetCurrent(context), "cuCtxSetCurrent")
        module = ctypes.c_void_p()
        _check(cuda, cuda.cuModuleLoadData(ctypes.byref(module), ctypes.cast(cubin, ctypes.c_void_p)),
               "cuModuleLoadData")
        try:
            function = ctypes.c_void_p()
            _check(cuda, cuda.cuModuleGetFunction(ctypes.byref(function), module, b"dense"), "cuModuleGetFunction")
            on_the_gpu = _forward_on_the_gpu(cuda, function, x, layers)
        finally:
            cuda.cuModuleUnload(module)
    finally:
        cuda.cuDevicePrimaryCtxRelease_v2(device)

    on_the_cpu = _forward_on_the_cpu(x, layers)
    difference = float(np.abs(on_the_gpu.astype(np.float64) - on_the_cpu.astype(np.float64)).max())
    device_line = (f"{name.value.decode()}, compute {major.value}.{minor.value}, "
                   f"{memory.value // (1024 * 1024):,} MiB")
    versions = (f"CUDA {toolkit[0]}.{toolkit[1]} (NVRTC); driver {release} "
                f"(CUDA {driver_cuda.value // 1000}.{driver_cuda.value % 1000 // 10})")
    print(f"CUDA device: {device_line}")
    print(f"CUDA versions: {versions}")
    print(f"Largest difference from numpy: {difference:.3g} over {on_the_gpu.size:,} outputs")
    record_property("cuda_device", device_line)
    record_property("cuda_versions", versions)
    record_property("cuda_largest_difference", f"{difference:.3g}")
    assert on_the_gpu.shape == on_the_cpu.shape
    assert difference < TOLERANCE, (
        f"the GPU's forward pass is {difference:.3g} off numpy's, over the {TOLERANCE:g} allowed")


def test_the_committed_weights_are_the_scripts():
    """``cuda_mlp.npy`` is exactly what ``cuda_mlp_weights.py`` writes, so it can be made again."""
    committed = np.load(cuda_mlp_weights.WEIGHTS_FILE)
    assert committed.dtype == np.float32
    assert np.array_equal(committed, cuda_mlp_weights.make_weights()), (
        "cuda_mlp.npy differs from the script's output: run python -m utk_curio.sandbox.tests.cuda_mlp_weights")
    assert [w.shape for w, _ in cuda_mlp_weights.layers(committed)] == [(64, 32), (32, 10)]
