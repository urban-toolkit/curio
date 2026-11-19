"""The flags the suites launch Chrome with (``_support/chrome_flags.py``).

A CPU job (e2e-desktop, test-isolated) must draw a page the same way on every
runner it lands on. With Chrome's Vulkan turned on, Chrome draws with the
Vulkan driver of the machine it runs on: on a utk desktop that is its NVIDIA
GPU (Skia's GaneshVulkan), while a hosted or arcade CPU runner has no Vulkan
driver and draws with GL over SwiftShader (GaneshGL). The same chart close-up
then read up to 15% apart between them, against a 5% budget (probe runs
44426534869, 44426538850 and 44426542464).
"""
import ast
from pathlib import Path

import pytest

from utk_curio.backend.tests._support import chrome_flags

#: CURIO_WEBGPU_BACKEND values that mean the CPU path: anything but hardware.
CPU_BACKENDS = ("swiftshader", "", "anything-but-hardware")


def _features(args, switch):
    """Every feature the given switch (--enable-features or --disable-features) names."""
    names = []
    for arg in args:
        if arg.startswith(switch + "="):
            names += arg.split("=", 1)[1].split(",")
    return names


@pytest.mark.parametrize("backend", CPU_BACKENDS)
def test_a_cpu_jobs_chrome_never_turns_vulkan_on(backend):
    _headless, args = chrome_flags.launch_flags("linux", True, backend)
    assert "Vulkan" not in _features(args, "--enable-features"), (
        f"the CPU path turns Chrome's Vulkan on, so on a machine with a Vulkan "
        f"driver Chrome draws with that GPU: {args}")
    assert not [a for a in args if a.startswith("--use-vulkan")], args
    assert "--use-angle=vulkan" not in args, args


@pytest.mark.parametrize("backend", CPU_BACKENDS)
def test_a_cpu_jobs_chrome_runs_webgl_and_webgpu_on_swiftshader(backend):
    headless, args = chrome_flags.launch_flags("linux", True, backend)
    assert headless is False, "Playwright would add the old --headless, which has no WebGPU"
    assert "--headless=new" in args, args
    assert "--use-angle=swiftshader" in args, args
    assert "--use-webgpu-adapter=swiftshader" in args, args
    assert "--enable-unsafe-webgpu" in args, args


def test_the_gpu_job_keeps_chrome_on_its_gpu_through_vulkan():
    headless, args = chrome_flags.launch_flags("linux", True, "hardware")
    assert headless is False
    assert "--headless=new" in args, args
    assert "Vulkan" in _features(args, "--enable-features"), args
    assert "--use-angle=vulkan" in args, args
    assert "--disable-vulkan-surface" in args, args
    assert not [a for a in args if "swiftshader" in a], args


@pytest.mark.parametrize("platform,headless", [
    ("darwin", True), ("win32", True), ("linux", False),
])
def test_elsewhere_the_flags_stay_minimal(platform, headless):
    assert chrome_flags.launch_flags(platform, headless, "swiftshader") == (
        headless, list(chrome_flags.MINIMAL))
    assert chrome_flags.launch_flags(platform, headless, "hardware") == (
        headless, list(chrome_flags.MINIMAL))


def test_the_fixture_takes_its_flags_from_chrome_flags_alone():
    """browser_type_launch_args (tests/conftest.py) names no Chrome switch of
    its own and asks launch_flags once, so the flags these tests read are the
    ones Chrome gets."""
    tree = ast.parse(Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"))
    fixture = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "browser_type_launch_args")
    switches = [node.value for node in ast.walk(fixture)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith("--")]
    assert switches == [], f"browser_type_launch_args names switches of its own: {switches}"
    calls = [node for node in ast.walk(fixture)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "launch_flags"]
    assert len(calls) == 1, "browser_type_launch_args should take its flags from launch_flags once"
