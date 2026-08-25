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
import unittest
from unittest import mock

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
        self.assertIn("--exec-user", finding)


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
            with mock.patch.object(
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
        self.assertIn("--exec-user", findings[0])
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
        """Tightening them would tighten the staged copy the child reads."""
        for relative in (".curio/data", ".curio/users", "datasets"):
            with self.subTest(relative=relative):
                self.assertIn(relative, hardening.HARDLINK_SOURCES)
        # instance/ is not staged from, so its files are still tightened.
        self.assertNotIn("instance", hardening.HARDLINK_SOURCES)

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
