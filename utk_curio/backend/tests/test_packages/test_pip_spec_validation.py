"""A Python requirement is a name plus a version, and nothing else.

``pip install`` reads an argv element as a URL to download and build, or as an
option that repoints the whole resolve. Both execute attacker-chosen code on the
Curio host. Nothing in the package subsystem validated Python names: the
libraries route checked only ``isinstance(str)``, manifest ingestion checked
only that ``dependencies.python`` was a dict, and the build-time dependency
review validated the *constraint* while leaving the name alone.

This is not shell injection. Every call site builds a list argv with no
``shell=True``, so no metacharacter is interpreted. The exposure is that pip
itself accepts more than package names in that position.

The guard lives in ``pip_runner`` rather than only at the route because the
route is one of seven paths to pip; the other six carry manifest-declared names
that never pass a request handler.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.pip_runner import (
    PipSpecError,
    _spec_argv,
    validate_python_requirement,
)


class TestRefusedRequirements:
    @pytest.mark.parametrize(
        "name",
        [
            "https://evil.example/x.tar.gz",   # pip builds the sdist: setup.py runs
            "http://evil.example/x.zip",
            "git+https://evil.example/repo",
            "--index-url=http://attacker/simple",  # repoints the resolve
            "--extra-index-url=http://attacker",
            "-r",                               # reads a requirements file
            "-rrequirements.txt",
            "./local/path",
            "../escape",
            "/abs/path/pkg.whl",
            "pkg; rm -rf /",
            "pkg && curl evil",
            "pkg\nother",
            "",
            "   ",
        ],
    )
    def test_non_package_names_are_refused(self, name):
        with pytest.raises(PipSpecError):
            validate_python_requirement(name)

    def test_the_same_names_cannot_reach_an_argv_entry(self):
        with pytest.raises(PipSpecError):
            _spec_argv("https://evil.example/x.tar.gz", "")

    @pytest.mark.parametrize(
        "spec",
        ["; rm -rf /", "https://evil", "--index-url=x", "1.0 && curl evil", "$(id)"],
    )
    def test_bad_constraints_are_refused(self, spec):
        with pytest.raises(PipSpecError):
            validate_python_requirement("requests", spec)


class TestRealRequirementsStillWork:
    @pytest.mark.parametrize(
        "name",
        ["requests", "scikit-learn", "ruamel.yaml", "zope.interface", "a", "torch"],
    )
    def test_ordinary_names_pass(self, name):
        validate_python_requirement(name)

    @pytest.mark.parametrize(
        "spec", ["", "*", ">=2.0", "~=4.30", "==1.5.0", "!=2.0", "1.2.3", "^0.14", ">=1.0,<2.0"],
    )
    def test_every_spec_shape_the_runner_documents_passes(self, spec):
        validate_python_requirement("requests", spec)

    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("", "requests"),
            ("*", "requests"),
            (">=2.0", "requests>=2.0"),
            ("^0.14", "requests~=0.14"),
            ("1.2.3", "requests==1.2.3"),
        ],
    )
    def test_argv_entries_are_unchanged_for_valid_input(self, spec, expected):
        assert _spec_argv("requests", spec) == expected
