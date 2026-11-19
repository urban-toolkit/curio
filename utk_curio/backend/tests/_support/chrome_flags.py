"""The flags the test suites launch Chrome with, by platform and GPU path.

``browser_type_launch_args`` in ``tests/conftest.py`` launches the system
Chrome (bundled Chromium when there is none) with what ``launch_flags``
returns. They are kept here, apart from the fixture and free of side effects,
so that a unit test reads them without loading the root conftest
(``tests/test_chrome_flags.py``).

On **Windows and macOS** the set is intentionally minimal:
``--enable-unsafe-webgpu`` lets Dawn expose adapters in non-secure contexts
and on unstable configs, ``--enable-unsafe-swiftshader`` lets Dawn fall back
to a software adapter on hosts without a hardware GPU. We deliberately do
*not* pass ``--use-angle=*`` or ``--enable-features=Vulkan,...`` there: those
are the flags urban-toolkit/autark uses on macOS to force Metal/Vulkan paths,
but on Windows they make Dawn ask for a Vulkan adapter the host doesn't have
and ``requestAdapter()`` returns null. Real Chrome on Windows defaults to
D3D12 and works correctly when left alone. Verified empirically on Chrome 148
/ Windows 11 against https://example.com: the adapter is created with the
minimal flags and disappears the moment either of the autark flags is added.

On **Linux** those flags are not enough: Playwright's default
``headless=True`` launches Chrome's *old* headless mode, which has no WebGPU
at all, so ``requestAdapter()`` returns null and the ``AUTK_GRAMMAR``
map/plot nodes crash in ``createShaderModule``. We instead opt into Chrome's
*new* headless (which shares the full browser/GPU stack): ``headless`` is set
to ``False`` so Playwright does not inject the old ``--headless``, and
``--headless=new`` then drives true headless. The page is served from
``http://localhost:8080`` (a secure context), satisfying WebGPU's
secure-context requirement. The backend is selected by
``CURIO_WEBGPU_BACKEND`` (default ``swiftshader``), see ``HARDWARE`` and
``SWIFTSHADER``.
"""

#: Windows and macOS, and a headed run on Linux.
MINIMAL = (
    "--enable-unsafe-webgpu",
    "--enable-unsafe-swiftshader",
)

#: Linux with ``CURIO_WEBGPU_BACKEND=hardware``: test-gpu's GPU runners
#: (NVIDIA). Let Dawn pick the real hardware Vulkan adapter; do NOT pass any
#: SwiftShader flag (that would force the software adapter and defeat the
#: point). The compute examples 06/07 only run here.
HARDWARE = (
    "--headless=new",
    "--enable-unsafe-webgpu",
    "--ignore-gpu-blocklist",
    "--enable-features=Vulkan",
    "--use-angle=vulkan",
    # Headless has no window to present to; without this, Chrome in a
    # container (arcade's GPU runners) gives up on Vulkan and WebGPU falls
    # back to SwiftShader.
    "--disable-vulkan-surface",
)

#: Linux otherwise: every CPU job (e2e-desktop, test-isolated) and a local
#: run. Force Chrome's bundled SwiftShader software adapter so the *map*
#: examples still render; the compute examples crash software WebGPU and are
#: not expected to run on this path.
#:
#: Chrome's Vulkan stays off here. Turned on (``--enable-features=Vulkan``),
#: Chrome takes the Vulkan driver of the machine it runs on: a utk desktop's
#: NVIDIA GPU, where Skia then draws every page (GaneshVulkan), while a hosted
#: or arcade CPU runner has no Vulkan driver and draws with GL over
#: SwiftShader (GaneshGL), so the same chart close-up read up to 15% apart.
#: Off, every runner draws alike, and WebGL and WebGPU still come up on
#: SwiftShader.
SWIFTSHADER = (
    "--headless=new",
    "--enable-unsafe-webgpu",
    "--enable-unsafe-swiftshader",
    "--use-webgpu-adapter=swiftshader",
    "--use-angle=swiftshader",
    "--ignore-gpu-blocklist",
)


def launch_flags(platform: str, headless: bool, backend: str) -> tuple[bool, list[str]]:
    """Playwright's ``headless`` and Chrome's flags, for ``sys.platform``, the
    ``headless`` pytest-playwright asked for and ``CURIO_WEBGPU_BACKEND``
    (``hardware``, or anything else for SwiftShader)."""
    if not platform.startswith("linux") or not headless:
        return headless, list(MINIMAL)
    # False so Playwright does not add the old --headless; --headless=new does.
    return False, list(HARDWARE if backend == "hardware" else SWIFTSHADER)
