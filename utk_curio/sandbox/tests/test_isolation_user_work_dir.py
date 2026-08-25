"""Isolated nodes run in a work directory that belongs to the user.

An isolated child used to run in its per-execution scratch directory, so a
node's relative reads found nothing and its relative writes vanished with the
execution. Running it in the launch directory instead fixed the reads and made
the writes land in the application tree -- or fail outright once ``--exec-user``
denies writing there.

Each user now gets a persistent directory of their own, and the child runs in
it: ``open("out.csv", "w")`` and ``pd.read_csv("out.csv")`` both work, both stay
inside that user's space, and both survive to the next execution.

**Isolated mode only.** In-process execution shares the sandbox's privileges
anyway, so confining its cwd would buy nothing while changing behaviour for
every existing dataflow.

Run:  pytest utk_curio/sandbox/tests/test_isolation_user_work_dir.py -v
"""

import os
import stat
import sys
import unittest

from utk_curio.sandbox.isolation import supervisor

posix_only = unittest.skipIf(
    sys.platform == "win32", "POSIX permissions do not apply on Windows"
)


class TestWhereTheWorkDirectoryLives(unittest.TestCase):

    STORE = os.path.join("/srv", "curio", ".curio", "data")

    def test_it_is_per_user(self):
        a = supervisor.user_work_dir(self.STORE, "7")
        b = supervisor.user_work_dir(self.STORE, "8")
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(os.path.join("users", "7")))

    def test_it_is_stable_across_executions(self):
        """Persistent, unlike the per-execution scratch directory."""
        self.assertEqual(
            supervisor.user_work_dir(self.STORE, "7"),
            supervisor.user_work_dir(self.STORE, "7"),
        )

    def test_the_guest_key_is_a_user_like_any_other(self):
        self.assertTrue(
            supervisor.user_work_dir(self.STORE, "guest").endswith(
                os.path.join("users", "guest")
            )
        )

    def test_it_is_not_inside_the_hardened_user_store(self):
        """The reason it is not `.curio/users/<key>/scratch/`.

        `.curio/users` is 0700 root-owned so a node cannot reach any other
        user's datasets and projects. A child-writable directory inside it
        means relaxing that to 0711 and hardening each `<key>/datasets/`
        separately, as users appear at runtime rather than once at boot. The
        property wanted here -- per user, persistent, writable -- does not need
        that trade.
        """
        work = supervisor.user_work_dir(self.STORE, "7")
        self.assertNotIn(os.path.join(".curio", "users"), work)

    def test_it_shares_a_filesystem_with_the_store(self):
        """Same parent, so staging can still hardlink rather than copy."""
        work = supervisor.user_work_dir(self.STORE, "7")
        self.assertTrue(
            work.startswith(os.path.dirname(os.path.abspath(self.STORE)))
        )


class TestPreparingIt(unittest.TestCase):

    def _prepare(self, tmp, **kwargs):
        path = supervisor.user_work_dir(os.path.join(tmp, "data"), "7")
        return supervisor.prepare_user_work_dir(path, **kwargs)

    def test_it_is_created_on_first_use(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._prepare(tmp)
            self.assertTrue(os.path.isdir(path))

    def test_preparing_twice_keeps_what_is_already_there(self):
        """It is the user's directory: a second execution must not wipe it."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._prepare(tmp)
            keep = os.path.join(path, "out.csv")
            with open(keep, "w", encoding="utf-8") as handle:
                handle.write("a,b\n")

            self._prepare(tmp)

            self.assertTrue(os.path.exists(keep))

    @posix_only
    def test_it_is_private_to_the_execution_user(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._prepare(tmp)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    @posix_only
    def test_the_examples_stay_readable_from_it(self):
        """The bundled examples read their data by relative path.

        With the cwd off the launch directory, `docs/examples/...` resolves to
        nothing unless the link is there. This is the mechanism that keeps the
        e2e workflows running.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            launch = os.path.join(tmp, "launch")
            data = os.path.join(launch, "docs", "examples", "data")
            os.makedirs(data)
            with open(os.path.join(data, "thing.txt"), "w", encoding="utf-8") as handle:
                handle.write("42")

            path = self._prepare(tmp, launch_dir=launch)

            linked = os.path.join(path, "docs", "examples", "data", "thing.txt")
            self.assertTrue(os.path.islink(os.path.join(path, "docs")))
            with open(linked, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "42")

    @posix_only
    def test_the_link_is_not_replaced_on_a_later_run(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            launch = os.path.join(tmp, "launch")
            os.makedirs(os.path.join(launch, "docs"))

            first = self._prepare(tmp, launch_dir=launch)
            before = os.readlink(os.path.join(first, "docs"))
            self._prepare(tmp, launch_dir=launch)

            self.assertEqual(os.readlink(os.path.join(first, "docs")), before)

    def test_a_launch_dir_without_docs_is_fine(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            launch = os.path.join(tmp, "launch")
            os.makedirs(launch)

            path = self._prepare(tmp, launch_dir=launch)

            self.assertFalse(os.path.lexists(os.path.join(path, "docs")))


if __name__ == "__main__":
    unittest.main()
