"""Whether the execution user can still read what it must not.

seccomp does not stop ``open()``, and reading a file is what a data node
legitimately does. So if ``instance/urban_workflow.db`` is world-readable, an
isolated child reads every password hash with no escape required at all. This
suite covers the decision logic for that.

The permission arithmetic is deliberately a pure function taking stat-like
values, so the whole truth table runs on Windows too. Only the chmod half needs
POSIX, and that part is marked.
"""

import os
import stat
import sys
import unittest.mock

from utk_curio.sandbox.isolation import hardening, supervisor

posix_only = unittest.skipIf(
    sys.platform == "win32", "chmod semantics do not apply on Windows"
)


class FakeStat:
    """Just enough of os.stat_result for the pure logic."""

    def __init__(self, mode, uid=1000, gid=1000):
        self.st_mode = mode
        self.st_uid = uid
        self.st_gid = gid


class TestCanAccess(unittest.TestCase):
    """The truth table, runnable anywhere."""

    def test_owner_read(self):
        self.assertTrue(
            hardening.can_access(FakeStat(0o400, uid=1000), uid=1000, gid=1000)
        )
        self.assertFalse(
            hardening.can_access(FakeStat(0o000, uid=1000), uid=1000, gid=1000)
        )

    def test_group_read_applies_when_uid_differs(self):
        path_stat = FakeStat(0o040, uid=0, gid=1000)
        self.assertTrue(hardening.can_access(path_stat, uid=1000, gid=1000))

    def test_other_read_is_the_dangerous_case(self):
        """0644 on the artifact store is what makes the child able to read it."""
        path_stat = FakeStat(0o644, uid=0, gid=0)
        self.assertTrue(hardening.can_access(path_stat, uid=1000, gid=1000))

    def test_owner_only_denies_everyone_else(self):
        path_stat = FakeStat(0o600, uid=0, gid=0)
        self.assertFalse(hardening.can_access(path_stat, uid=1000, gid=1000))

    def test_owner_bits_do_not_leak_to_others(self):
        """A file owned by root at 0600 must not read as accessible to 1000."""
        path_stat = FakeStat(0o600, uid=0, gid=0)
        self.assertFalse(hardening.can_access(path_stat, uid=1000, gid=999))

    def test_write_checks_the_write_bits(self):
        readable_only = FakeStat(0o444, uid=0, gid=0)
        self.assertTrue(hardening.can_access(readable_only, uid=1, gid=1))
        self.assertFalse(
            hardening.can_access(readable_only, uid=1, gid=1, write=True)
        )

    def test_the_ci_umask_case_is_flagged(self):
        """docker-compose.ci.yml uses umask 000, so files land 0666."""
        path_stat = FakeStat(0o666, uid=0, gid=0)
        self.assertTrue(hardening.can_access(path_stat, uid=1000, gid=1000))


class TestDescribeExposure(unittest.TestCase):

    def test_a_readable_path_is_reported_with_its_mode(self):
        finding = hardening.describe_exposure(
            "instance", FakeStat(0o644, uid=0, gid=0),
            uid=1000, gid=1000, reason="the user database",
        )
        self.assertIsNotNone(finding)
        self.assertIn("instance", finding)
        self.assertIn("the user database", finding)
        self.assertIn("rw-r--r--", finding)

    def test_an_owner_only_path_is_not_reported(self):
        self.assertIsNone(
            hardening.describe_exposure(
                "instance", FakeStat(0o600, uid=0, gid=0),
                uid=1000, gid=1000, reason="x",
            )
        )

    def test_root_as_the_execution_user_is_always_reported(self):
        """Mode bits are irrelevant to root, and pretending otherwise would lie."""
        finding = hardening.describe_exposure(
            "instance", FakeStat(0o600, uid=0, gid=0),
            uid=0, gid=0, reason="x",
        )
        self.assertIsNotNone(finding)
        self.assertIn("root", finding)
        self.assertIn("CURIO_EXEC_USER", finding)


class TestAudit(unittest.TestCase):

    def test_missing_paths_are_not_reported(self):
        """A fresh workspace has no instance/ yet; warning would be noise."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(hardening.audit(tmp, uid=1000, gid=1000), [])

    def test_an_exposed_path_is_reported(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "instance"))
            with unittest.mock.patch.object(
                hardening, "can_access", return_value=True
            ):
                findings = hardening.audit(tmp, uid=1000, gid=1000)
        self.assertEqual(len(findings), 1)
        self.assertIn("instance", findings[0])

    def test_every_sensitive_path_carries_a_reason(self):
        """The log line has to explain why the path matters."""
        for relative, reason in hardening.SENSITIVE_PATHS:
            with self.subTest(path=relative):
                self.assertTrue(reason and len(reason) > 10, relative)

    def test_the_user_database_and_artifact_store_are_both_covered(self):
        covered = {relative for relative, _ in hardening.SENSITIVE_PATHS}
        self.assertIn("instance", covered)
        self.assertIn(".curio/data", covered)


class TestApplyAndReport(unittest.TestCase):

    def test_no_exec_user_is_reported_as_no_filesystem_boundary(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            findings, fatal = hardening.apply_and_report(
                tmp, tmp, uid=None, gid=None, hosted=False
            )
        self.assertEqual(len(findings), 1)
        self.assertIn("CURIO_EXEC_USER", findings[0])
        self.assertFalse(fatal, "a local launch must not be blocked")

    def test_no_exec_user_is_fatal_for_a_hosted_instance(self):
        """Believing you are isolated while node code reads the DB is worse
        than not starting."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _findings, fatal = hardening.apply_and_report(
                tmp, tmp, uid=None, gid=None, hosted=True
            )
        self.assertTrue(fatal)

    def test_the_finding_says_what_still_applies(self):
        """Partial protection should not read as no protection."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            findings, _fatal = hardening.apply_and_report(
                tmp, tmp, uid=None, gid=None, hosted=False
            )
        self.assertIn("Resource limits", findings[0])


class TestTheModelWeightsAreNeverWritableByNodeCode(unittest.TestCase):
    """The folder ``--model-weights-dir`` names, where the server downloads
    the weights a model package's fetch names and isolated node code reads
    them in place, is kept as Node's packages are: the boot opens it to every
    account's reads and takes group and other writes away, and the audit asks
    the opposite question, whether node code could write it, where a file it
    changed would be the model every account's later runs load. The
    execution user here is an account other than the files' owner, whatever
    account the test runs as, unless a test says otherwise."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.weights = os.path.join(self.tmp, "model-weights")
        self.entry = os.path.join(self.weights, "model.x@1", "models", "checkpoint")
        os.makedirs(self.entry)
        for folder in (self.weights, os.path.join(self.weights, "model.x@1"),
                       os.path.dirname(self.entry), self.entry):
            os.chmod(folder, 0o755)
        for name in ("config.json", "model.safetensors"):
            path = os.path.join(self.entry, name)
            with open(path, "wb") as handle:
                handle.write(b"weights")
            os.chmod(path, 0o644)
        self.exec_uid = os.getuid() + 4242

    def tearDown(self):
        self._tmp.cleanup()

    def test_folders_0755_and_files_0644_of_another_account_are_not_reported(self):
        self.assertEqual(hardening.audit_model_weights(self.weights, uid=self.exec_uid, gid=None), [])

    def test_a_file_or_a_folder_the_execution_user_could_write_is_reported(self):
        weights_file = os.path.join(self.entry, "model.safetensors")
        os.chmod(weights_file, 0o666)
        os.chmod(self.entry, 0o777)

        findings = hardening.audit_model_weights(self.weights, uid=self.exec_uid, gid=None)

        self.assertEqual(len(findings), 2, findings)
        self.assertTrue(any(weights_file in finding and "-rw-rw-rw-" in finding for finding in findings), findings)
        self.assertTrue(any(self.entry in finding and "drwxrwxrwx" in finding for finding in findings), findings)
        self.assertTrue(all("model weights" in finding for finding in findings), findings)

    def test_a_folder_its_group_may_write_is_reported_for_a_member(self):
        os.chmod(self.entry, 0o775)
        group = os.stat(self.entry).st_gid

        findings = hardening.audit_model_weights(self.weights, uid=self.exec_uid, gid=group)

        self.assertEqual(len(findings), 1, findings)
        self.assertIn(self.entry, findings[0])

    def test_a_link_is_neither_followed_nor_reported(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.chmod(outside, 0o777)
        os.symlink(outside, os.path.join(self.entry, "elsewhere"))

        self.assertEqual(hardening.audit_model_weights(self.weights, uid=self.exec_uid, gid=None), [])

    def test_without_the_folder_or_an_execution_user_there_is_nothing_to_ask(self):
        os.chmod(self.entry, 0o777)
        self.assertEqual(hardening.audit_model_weights(None, uid=self.exec_uid, gid=None), [])
        self.assertEqual(hardening.audit_model_weights(self.weights, uid=None, gid=None), [])

    def _boot(self, uid):
        """``apply_and_report`` as a hosted sandbox's start runs it with
        ``--model-weights-dir``: its findings that name the weights folder,
        and whether it refuses to start."""
        launch = os.path.join(self.tmp, "launch")
        shared = os.path.join(launch, ".curio", "data")
        os.makedirs(shared, exist_ok=True)
        findings, fatal = hardening.apply_and_report(
            launch, shared, uid=uid, gid=None, hosted=True, model_weights_dir=self.weights,
        )
        return [finding for finding in findings if self.weights in finding], fatal

    def test_the_boot_opens_them_to_every_accounts_reads_and_takes_other_writes_away(self):
        """Whatever modes they came with, as for Node's packages: every folder
        0755, every file 0644, a file any class may run 0755; then nothing
        there is node code's to write."""
        folder_modes = {self.weights: 0o700, self.entry: 0o777}
        file_modes = {
            os.path.join(self.entry, "config.json"): (0o600, 0o644),
            os.path.join(self.entry, "model.safetensors"): (0o666, 0o644),
        }
        tool = os.path.join(self.entry, "tool")
        with open(tool, "wb") as handle:
            handle.write(b"#!/bin/sh\n")
        file_modes[tool] = (0o744, 0o755)
        for folder, mode in folder_modes.items():
            os.chmod(folder, mode)
        for path, (before, _after) in file_modes.items():
            os.chmod(path, before)

        weights_findings, _fatal = self._boot(self.exec_uid)

        self.assertEqual(weights_findings, [])
        for folder in folder_modes:
            self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o755, folder)
        for path, (before, after) in file_modes.items():
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), after, f"{path} was 0o{before:03o}")
        with open(os.path.join(self.entry, "model.safetensors"), "rb") as handle:
            self.assertEqual(handle.read(), b"weights")

    def test_a_hosted_instance_refuses_to_start_while_the_execution_user_owns_a_folder_there(self):
        """The boot cannot take an owner's write away: a folder the
        execution user owns is reported, and a hosted instance refuses to
        start. As root the test gives the entry folder to another account;
        otherwise the test's own account, which owns the tree, is the
        execution user."""
        if os.getuid() == 0:
            exec_uid = 4243
            os.chown(self.entry, exec_uid, -1)
        else:
            exec_uid = os.getuid()

        weights_findings, fatal = self._boot(exec_uid)

        self.assertTrue(fatal)
        self.assertTrue([finding for finding in weights_findings if f"{self.entry}," in finding], weights_findings)


@posix_only
class TestHardenPaths(unittest.TestCase):

    def test_a_world_readable_directory_is_tightened(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "instance")
            os.makedirs(target)
            os.chmod(target, 0o755)

            result = hardening.harden_paths(tmp)

            self.assertIn("instance", result["changed"])
            mode = stat.S_IMODE(os.stat(target).st_mode)
            self.assertEqual(mode, hardening.DIRECTORY_MODE)

    def test_files_inside_are_tightened_too(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "instance")
            os.makedirs(target)
            db = os.path.join(target, "urban_workflow.db")
            with open(db, "w", encoding="utf-8") as handle:
                handle.write("x")
            os.chmod(db, 0o666)

            hardening.harden_paths(tmp)

            self.assertEqual(stat.S_IMODE(os.stat(db).st_mode), hardening.FILE_MODE)

    def test_after_hardening_the_audit_is_clean(self):
        """The two halves have to agree, or hardening is theatre."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for relative, _reason in hardening.SENSITIVE_PATHS:
                path = os.path.join(tmp, relative)
                os.makedirs(path, exist_ok=True)
                os.chmod(path, 0o755)

            hardening.harden_paths(tmp)
            findings = hardening.audit(tmp, uid=os.getuid() + 1,
                                       gid=os.getgid() + 1)
        self.assertEqual(findings, [], findings)

    def test_a_missing_path_is_skipped_not_failed(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = hardening.harden_paths(tmp)
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["failed"], [])

    def test_the_scratch_root_is_traversable_but_not_listable(self):
        """0711: a child can enter its own directory, not enumerate siblings."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = hardening.prepare_scratch_root(tmp, exec_uid=None)
            mode = stat.S_IMODE(os.stat(root).st_mode)
        self.assertEqual(mode, 0o711)


class TestWindowsIsANoop(unittest.TestCase):
    """Hardening must not pretend to work where it cannot."""

    @unittest.skipUnless(sys.platform == "win32", "Windows-specific")
    def test_harden_reports_that_it_skipped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = hardening.harden_paths(tmp)
        self.assertEqual(result["skipped"], "not a POSIX host")
        self.assertEqual(result["changed"], [])



class TestTheChildCanReachItsScratchDirectory(unittest.TestCase):
    """Hardening must not lock the child out of the directory it runs in.

    Two ways that went wrong, both found rather than predicted.

    First, the scratch directory used to live *inside* ``.curio/data``, so the
    store had to stay traversable for a child to reach it -- and hardening set
    it to 0700 root-owned anyway, then walked it and reset the scratch root
    too. ``confine`` would have failed at its final chdir and no isolated node
    could have run. The audit stayed clean throughout, because it asks about
    *read* access, which 0700 correctly denies.

    Second, the store's files were tightened to 0600 root-owned. Staging
    hardlinks an artifact into the scratch directory, and a hardlink shares its
    source's inode, so the staged copy became unreadable too: the child could
    not read its own input.

    The scratch root now sits beside the store instead of inside it, which lets
    the store be 0700 with nothing to reach through it, and the files inside a
    hardlink source are left alone. Traversal is an execute bit, so
    ``can_access`` (which is about reading) cannot express it and those checks
    are done directly here.
    """

    @staticmethod
    def _traversable(mode, owner_uid, as_uid):
        if as_uid == 0:
            return True
        if as_uid == owner_uid:
            return bool(mode & stat.S_IXUSR)
        return bool(mode & stat.S_IXOTH)

    def test_the_scratch_root_is_not_inside_the_store(self):
        """The property that lets the store be 0700 at all."""
        store = os.path.join("/srv", "curio", ".curio", "data")
        root = supervisor.scratch_root(store)

        self.assertFalse(
            os.path.abspath(root).startswith(os.path.abspath(store) + os.sep),
            f"{root} is inside {store}",
        )
        # Same parent, so the same filesystem: hardlink in, rename out.
        self.assertEqual(
            os.path.dirname(root), os.path.dirname(os.path.abspath(store))
        )

    def test_every_sensitive_directory_is_fully_denied(self):
        """No read, no list, no traverse, for all of them."""
        self.assertEqual(hardening.DIRECTORY_MODE, 0o700)
        self.assertFalse(self._traversable(hardening.DIRECTORY_MODE, 0, 1001))
        denied = FakeStat(stat.S_IFDIR | hardening.DIRECTORY_MODE, 0, 0)
        self.assertFalse(hardening.can_access(denied, uid=1001, gid=1001))

    def test_the_hardlink_sources_keep_their_file_modes(self):
        """Tightening them would tighten the staged copy the child reads.
        Models ship as model packages, so their weights are under
        ``packages/*/models``; there is no ``models/`` folder to close."""
        for relative in (".curio/data", ".curio/users", "datasets", "packages/*/models", ".curio/fetched"):
            with self.subTest(relative=relative):
                self.assertIn(relative, hardening.HARDLINK_SOURCES)
        # instance/ is not staged from, so its files are still tightened.
        self.assertNotIn("instance", hardening.HARDLINK_SOURCES)
        self.assertNotIn("models", hardening.HARDLINK_SOURCES)
        self.assertNotIn("models", {relative for relative, _why in hardening.SENSITIVE_PATHS})

    @posix_only
    def test_a_staged_artifact_stays_readable_after_hardening(self):
        """The regression, end to end on a real filesystem.

        A hardlink cannot carry permissions of its own, so if hardening
        tightens the source it tightens the staged copy with it.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = os.path.join(tmp, ".curio", "data", "artifacts")
            os.makedirs(artifacts)
            source = os.path.join(artifacts, "a1.parquet")
            with open(source, "w", encoding="utf-8") as handle:
                handle.write("frame")
            os.chmod(source, 0o644)

            scratch = os.path.join(tmp, "scratch")
            os.makedirs(scratch)
            staged = os.path.join(scratch, "in_0.parquet")
            os.link(source, staged)

            hardening.harden_paths(tmp)

            mode = stat.S_IMODE(os.stat(staged).st_mode)
            self.assertTrue(
                mode & stat.S_IROTH,
                f"the staged copy lost its read bit (0o{mode:03o}); the child "
                "could not read its own input",
            )

    @posix_only
    def test_a_staged_fetched_file_stays_readable_after_hardening(self):
        """A catalog file a pip install downloaded reaches a child as a hardlink
        too (``staging.stage_dataset_paths``, ``stage_model_dirs``): hardening
        closes ``.curio/fetched`` and leaves the file's mode, so the staged copy
        stays readable while the folder cannot be walked."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fetched = os.path.join(tmp, ".curio", "fetched")
            files = os.path.join(fetched, "0" * 40, "packages", "model.scout.deep-umbra@1", "models")
            os.makedirs(files)
            os.chmod(fetched, 0o755)
            source = os.path.join(files, "deep_umbra.onnx")
            with open(source, "wb") as handle:
                handle.write(b"graph")
            os.chmod(source, 0o644)

            scratch = os.path.join(tmp, "scratch")
            os.makedirs(scratch)
            staged = os.path.join(scratch, "deep_umbra.onnx")
            os.link(source, staged)

            result = hardening.harden_paths(tmp)

            self.assertIn(".curio/fetched", result["changed"])
            self.assertEqual(stat.S_IMODE(os.stat(fetched).st_mode), hardening.DIRECTORY_MODE)
            mode = stat.S_IMODE(os.stat(staged).st_mode)
            self.assertTrue(
                mode & stat.S_IROTH,
                f"the staged copy lost its read bit (0o{mode:03o}); the child "
                "could not read the fetched file",
            )

    @posix_only
    def test_a_model_packages_weights_are_closed_and_a_staged_copy_stays_readable(self):
        """A shipped model package's weights, ``packages/<dir>/models/``, reach a
        child only as the hardlinks ``stage_model_dirs`` makes: hardening
        closes each such folder and leaves the files' modes, so the staged
        copy stays readable, and the package's code beside it stays open."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            package = os.path.join(tmp, "packages", "model.example.local-relief@1")
            weights = os.path.join(package, "models")
            sources = os.path.join(package, "sources")
            os.makedirs(weights)
            os.makedirs(sources)
            for directory in (weights, sources):
                os.chmod(directory, 0o755)
            source = os.path.join(weights, "local_relief.onnx")
            with open(source, "wb") as handle:
                handle.write(b"graph")
            os.chmod(source, 0o644)
            exposed = hardening.audit(tmp, uid=1001, gid=1001)
            self.assertTrue(
                any("packages/model.example.local-relief@1/models" in finding for finding in exposed),
                exposed,
            )

            scratch = os.path.join(tmp, "scratch")
            os.makedirs(scratch)
            staged = os.path.join(scratch, "local_relief.onnx")
            os.link(source, staged)

            result = hardening.harden_paths(tmp)

            self.assertIn("packages/model.example.local-relief@1/models", result["changed"])
            mode = stat.S_IMODE(os.stat(weights).st_mode)
            self.assertEqual(mode, hardening.DIRECTORY_MODE)
            self.assertFalse(self._traversable(mode, 0, 1001))
            self.assertTrue(stat.S_IMODE(os.stat(staged).st_mode) & stat.S_IROTH)
            self.assertEqual(stat.S_IMODE(os.stat(sources).st_mode), 0o755)
            self.assertEqual(hardening.audit(tmp, uid=1001, gid=1001), [])

    @posix_only
    def test_the_sandboxs_nodejs_packages_are_readable_and_never_writable(self):
        """The boot leaves ``.curio/nodejs``, the Node.js packages a pip
        install's sandbox runs, readable by node code, whose JavaScript nodes
        import them as the execution account, and takes every write away from
        everyone but their owner: a module node code could change would run in
        every later run, and in the backend's own Node, as root. Everyone gets
        read, and execute on a folder and on a file that had it, so a
        package's executable keeps its execute bits and a plain file gains
        none; a tree an earlier boot closed opens again."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, ".curio", "nodejs")
            modules = os.path.join(folder, "node_modules")
            package = os.path.join(modules, "@urban-toolkit", "autk-db")
            binaries = os.path.join(modules, ".bin")
            closed = os.path.join(modules, "closed-by-an-earlier-boot")
            for directory in (package, binaries, closed):
                os.makedirs(directory)
            # Each folder's mode before the boot; every one ends 0755.
            folders = {
                folder: 0o777, modules: 0o777, os.path.dirname(package): 0o777,
                package: 0o777, binaries: 0o755, closed: 0o700,
            }
            # Each file's mode before the boot, and after it.
            files = {
                os.path.join(package, "index.js"): (0o666, 0o644),
                os.path.join(package, "run-by-its-owner"): (0o744, 0o755),
                os.path.join(binaries, "tool"): (0o777, 0o755),
                os.path.join(closed, "index.js"): (0o600, 0o644),
            }
            for path, (before, _after) in files.items():
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("export const loaded = true;\n")
                os.chmod(path, before)
            for directory, before in folders.items():
                os.chmod(directory, before)

            hardening.apply_and_report(
                tmp, os.path.join(tmp, ".curio", "data"), uid=1001, gid=1001, hosted=False,
            )

            for path in [*folders, *files]:
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(
                    mode & 0o022, 0,
                    f"hardening left {os.path.relpath(path, tmp)} at 0o{mode:03o}: node code running as "
                    "the execution account could change a module the sandbox's Node imports",
                )
            for directory in folders:
                mode = stat.S_IMODE(os.stat(directory).st_mode)
                self.assertEqual(
                    mode, 0o755,
                    f"{os.path.relpath(directory, tmp)} is 0o{mode:03o}: the execution account cannot "
                    "read the packages its JavaScript nodes import",
                )
                self.assertTrue(self._traversable(mode, 0, 1001))
            for path, (before, after) in files.items():
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(
                    mode, after,
                    f"{os.path.relpath(path, tmp)} went from 0o{before:03o} to 0o{mode:03o}, not 0o{after:03o}",
                )
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), "export const loaded = true;\n")

    @posix_only
    def test_the_audit_reports_nodes_packages_the_execution_account_could_write(self):
        """The inverse audit, as for the node-library trees: Node's packages
        must stay readable, so what is asked is whether the execution account
        could WRITE anywhere in them, a folder (a module added) or a file (a
        module changed). The boot's hardening takes group and other writes
        away, after which the audit is clean; it cannot take an owner's, so an
        account that owns a folder there is reported still, and a hosted
        instance refuses to start."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            nodejs = os.path.join(tmp, ".curio", "nodejs")
            package = os.path.join(nodejs, "node_modules", "@urban-toolkit", "autk-db")
            os.makedirs(package)
            entry = os.path.join(package, "index.js")
            with open(entry, "w", encoding="utf-8") as handle:
                handle.write("export const loaded = true;\n")
            data = os.path.join(tmp, ".curio", "data")

            def opened():
                """The tree as hardening leaves it: folders 0755, files 0644."""
                for current, _directories, names in os.walk(nodejs):
                    os.chmod(current, 0o755)
                    for name in names:
                        os.chmod(os.path.join(current, name), 0o644)

            def naming(findings, path):
                return [finding for finding in findings if os.path.relpath(path, tmp) in finding]

            opened()
            self.assertEqual(
                naming(hardening.audit_node_packages(tmp, uid=4242, gid=4242), nodejs), [],
                "the audit reports a tree the execution account cannot write",
            )
            for writable, mode in ((package, 0o777), (entry, 0o646)):
                opened()
                os.chmod(writable, mode)
                findings = hardening.audit_node_packages(tmp, uid=4242, gid=4242)
                self.assertTrue(
                    naming(findings, writable),
                    f"the audit does not report {os.path.relpath(writable, tmp)} at 0o{mode:03o}, "
                    f"which node code could change a module through: {findings}",
                )
                hardening.apply_and_report(tmp, data, uid=4242, gid=4242, hosted=False)
                self.assertEqual(naming(hardening.audit_node_packages(tmp, uid=4242, gid=4242), nodejs), [])

            if os.getuid() == 0:
                opened()
                os.chown(package, 4243, 4243)
                findings, fatal = hardening.apply_and_report(tmp, data, uid=4243, gid=4244, hosted=True)
                self.assertTrue(
                    naming(findings, package),
                    f"the boot does not report a package folder the execution account owns: {findings}",
                )
                self.assertTrue(fatal, "a hosted instance whose Node packages node code can write would start")

    @posix_only
    def test_the_store_directory_is_still_locked(self):
        """Leaving the files alone must not leave the store reachable."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, ".curio", "data")
            os.makedirs(os.path.join(store, "artifacts"))
            os.chmod(store, 0o755)

            hardening.harden_paths(tmp)

            mode = stat.S_IMODE(os.stat(store).st_mode)
            self.assertEqual(mode, hardening.DIRECTORY_MODE)
            self.assertFalse(self._traversable(mode, 0, 1001))

    @posix_only
    def test_the_user_database_is_tightened_to_its_files(self):
        """instance/ is not a hardlink source, so recursion still applies."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "instance")
            os.makedirs(target)
            db = os.path.join(target, "urban_workflow.db")
            with open(db, "w", encoding="utf-8") as handle:
                handle.write("x")
            os.chmod(db, 0o666)

            hardening.harden_paths(tmp)

            self.assertEqual(stat.S_IMODE(os.stat(db).st_mode), hardening.FILE_MODE)

    def test_the_audit_still_passes_after_hardening(self):
        store = FakeStat(stat.S_IFDIR | hardening.DIRECTORY_MODE, 0, 0)
        self.assertIsNone(
            hardening.describe_exposure(
                ".curio/data", store, uid=1001, gid=1001, reason="the artifact store"
            )
        )


if __name__ == "__main__":
    unittest.main()
