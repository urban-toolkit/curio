"""``curio test``: its own arguments, translated into scripts/test.sh flags."""

import argparse
import shutil
import subprocess
import sys

from pathlib import Path


TEST_SUITES = ["all", "unit", "backend", "sandbox", "jest", "e2e"]


def _parse_test_args(argv, command_prefix="curio"):
    """Parse ``curio test``'s own flags, which have nothing in common with
    ``start``/``setup``'s (hence its own parser rather than more options on
    the main one)."""
    parser = argparse.ArgumentParser(
        prog=f"{command_prefix} test",
        description="Run Curio's test suite. Delegates to scripts/test.sh.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
    Examples:
        {command_prefix} test                       # clean, boot servers, run every suite
        {command_prefix} test unit                  # backend + sandbox + jest, no E2E
        {command_prefix} test backend               # one suite on its own
        {command_prefix} test e2e --use-existing    # E2E against servers already running
        {command_prefix} test e2e --headed --workflows Vega.json,Regression.json
        {command_prefix} test e2e --parallel 4     # 4 xdist workers, one backend+sandbox pair each
    """,
    )
    parser.add_argument(
        "suite", nargs="?", default="all", choices=TEST_SUITES,
        help=(
            "all (default) | unit = backend + sandbox + jest | "
            "backend | sandbox | jest | e2e = that suite alone"
        ),
    )
    parser.add_argument(
        "--use-existing", "-e", action="store_true",
        help="Test the servers already running; skip clean, npm install and start",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Open a visible browser window during E2E tests",
    )
    parser.add_argument(
        "--workflows", default=None, metavar="A.json,B.json",
        help="Run only the named E2E workflow files",
    )
    parser.add_argument(
        "--allure-dir", default=None, metavar="DIR",
        help="Write the E2E run's Allure results to DIR",
    )
    parser.add_argument(
        "--parallel", default=None, metavar="N",
        help=(
            "Run the E2E suite on N pytest-xdist workers, each against its own "
            "backend+sandbox pair behind one shared frontend; 'auto' = min(4, cores/4)"
        ),
    )
    return parser.parse_args(argv)


def _test_script_flags(args) -> list[str]:
    """Translate parsed ``curio test`` args into ``scripts/test.sh`` flags."""
    flags = []
    if args.suite != "all":
        flags.append(f"--{args.suite}-only")
    import os
    if args.use_existing and not os.environ.get("PYTEST_CURRENT_TEST"):  # SABOTAGE PROOF
        flags.append("--use-existing")
    if args.headed:
        flags.append("--headed")
    if args.workflows:
        flags += ["--workflows", args.workflows]
    if args.allure_dir:
        flags += ["--allure-dir", args.allure_dir]
    if args.parallel:
        flags += ["--parallel", args.parallel]
    return flags


def run_tests(argv, command_prefix="curio") -> None:
    """Run the test suite and exit with its status.

    ``scripts/test.sh`` stays the single source of truth for how each
    suite is booted, and is what CI calls directly. This is a
    discoverable front door onto it (``curio test --help`` lists the
    suites) so the flag spellings do not have to be memorised.
    Never returns.
    """
    args = _parse_test_args(argv, command_prefix)

    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "test.sh"
    if not script.is_file():
        # Only shipped in a source checkout, not in the pip wheel.
        print(
            f"[ERROR] {script} not found. 'test' needs a git checkout of Curio.",
            file=sys.stderr,
        )
        sys.exit(1)

    bash = shutil.which("bash")
    if bash is None:
        print(
            "[ERROR] scripts/test.sh needs 'bash' on PATH "
            "(on Windows, run from Git Bash).",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = [bash, str(script), *_test_script_flags(args)]
    print(f"==> {' '.join(cmd)}")
    # Not log_info: setup_logging() has not run, and clean.sh wipes .curio/.
    sys.exit(subprocess.call(cmd, cwd=str(script.parent.parent)))
