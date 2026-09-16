"""#332: each user's node libraries live in a directory of their own.

A library installed through the backend used to land in the one interpreter
the sandbox runs every user's nodes from, so whatever one user installed,
everybody imported. Under ``--isolation=fork`` a node runs in a forked child,
and a child can be handed its own ``sys.path`` -- so the install can be scoped
to the user who asked for it.

This is the directory that holds it. It is the work directory's sibling and
answers all the same questions, with one deliberate inversion: the work
directory belongs to the execution user because a node writes into it, and
this one must not, because it is an import path.

**Isolated mode only.** The in-process worker is one process with one
``sys.modules``; whoever imports a library first makes it importable by
everybody, whatever the path says.

Run:  pytest utk_curio/sandbox/tests/test_isolation_user_overlay_dir.py -v
"""

import os
import stat
import sys
import unittest

from utk_curio.sandbox.isolation import supervisor

posix_only = unittest.skipIf(
    sys.platform == "win32", "POSIX permissions do not apply on Windows"
)


class TestWhereTheOverlayLives(unittest.TestCase):

    STORE = os.path.join("/srv", "curio", ".curio", "data")

    def test_it_is_per_user(self):
        a = supervisor.user_overlay_dir(self.STORE, "7")
        b = supervisor.user_overlay_dir(self.STORE, "8")
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith(os.path.join("users", "7")))

    def test_it_is_stable_across_executions(self):
        """An installed library outlives the execution that needed it."""
        self.assertEqual(
            supervisor.user_overlay_dir(self.STORE, "7"),
            supervisor.user_overlay_dir(self.STORE, "7"),
        )

    def test_the_guest_key_is_a_user_like_any_other(self):
        self.assertTrue(
            supervisor.user_overlay_dir(self.STORE, "guest").endswith(
                os.path.join("users", "guest")
            )
        )

    def test_it_is_not_inside_the_hardened_user_store(self):
        """The same reason the work directory is not, and a sharper one.

        ``.curio/users`` is 0700 root-owned so a node cannot reach any other
        user's datasets and projects. An isolated child must be able to READ
        this tree on every execution, so putting it there would mean relaxing
        exactly the thing hardening exists to hold.
        """
        overlay = supervisor.user_overlay_dir(self.STORE, "7")
        self.assertNotIn(os.path.join(".curio", "users"), overlay)

    def test_it_is_beside_the_work_directory_not_inside_it(self):
        """Siblings. The child's cwd is writable; its import path is not, and
        nesting one in the other would collapse that distinction."""
        work = supervisor.user_work_dir(self.STORE, "7")
        overlay = supervisor.user_overlay_dir(self.STORE, "7")
        self.assertNotEqual(work, overlay)
        self.assertFalse(overlay.startswith(work + os.sep))
        self.assertFalse(work.startswith(overlay + os.sep))


class TestPreparingIt(unittest.TestCase):

    def test_it_is_created_on_first_use(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = supervisor.user_overlay_dir(os.path.join(tmp, "data"), "7")
            self.assertFalse(os.path.isdir(path))
            supervisor.prepare_user_overlay_dir(path)
            self.assertTrue(os.path.isdir(path))

    def test_preparing_twice_keeps_what_is_already_there(self):
        """Libraries survive the next execution; this is not a scratch dir."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = supervisor.user_overlay_dir(os.path.join(tmp, "data"), "7")
            supervisor.prepare_user_overlay_dir(path)
            with open(os.path.join(path, "tinylib.py"), "w") as fh:
                fh.write("VALUE = 1\n")
            supervisor.prepare_user_overlay_dir(path)
            self.assertTrue(os.path.isfile(os.path.join(path, "tinylib.py")))

    @posix_only
    def test_the_child_may_read_it_but_never_write_it(self):
        """The inversion of ``prepare_user_work_dir``, and the whole point.

        This directory is on the child's ``sys.path``. If the execution user
        could write to it, node code could drop a module in and shadow a later
        import -- for itself now, and for every subsequent execution as that
        user. So it is 0755 and stays owned by whoever ran the backend, even
        when an exec uid is supplied.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = supervisor.user_overlay_dir(os.path.join(tmp, "data"), "7")
            supervisor.prepare_user_overlay_dir(path, exec_uid=12345)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o755)
            self.assertTrue(mode & stat.S_IROTH, "the child has to import from it")
            self.assertFalse(mode & stat.S_IWOTH, "and must not be able to write it")
            self.assertNotEqual(os.stat(path).st_uid, 12345)


class TestTheBackendAndTheSandboxAgree(unittest.TestCase):
    """The backend writes this tree and the sandbox reads it, in two processes
    that never import each other. Two spellings of one path is exactly the kind
    of thing that drifts silently -- a node would simply stop finding its
    libraries, with nothing to say why -- so they are pinned here."""

    def test_the_two_spellings_are_the_same_directory(self):
        import tempfile

        from utk_curio.backend.app.packages import backend_runtime as rt

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CURIO_LAUNCH_CWD"] = tmp
            os.environ["CURIO_SHARED_DATA"] = "./.curio/data/"
            try:
                store = os.path.join(tmp, ".curio", "data")
                self.assertEqual(
                    os.path.realpath(supervisor.user_overlay_dir(store, "7")),
                    os.path.realpath(str(rt.user_node_overlay_dir("7"))),
                )
            finally:
                os.environ.pop("CURIO_LAUNCH_CWD", None)
                os.environ.pop("CURIO_SHARED_DATA", None)

    def test_the_subdirectory_name_is_the_same(self):
        self.assertEqual(supervisor.OVERLAY_SUBDIR, rt_subdir())


def rt_subdir():
    from utk_curio.backend.app.packages import backend_runtime as rt

    return rt._USER_NODE_OVERLAY_SUBDIR


if __name__ == "__main__":
    unittest.main()


class TestTheHardeningAuditAsksTheOppositeQuestion(unittest.TestCase):
    """Every other sensitive path is a finding because the execution user can
    READ it. This one has to be readable, or a user's nodes cannot import the
    libraries they installed. The risk is the write."""

    def _tree(self, tmp, user="7"):
        store = os.path.join(tmp, "data")
        path = supervisor.user_overlay_dir(store, user)
        supervisor.prepare_user_overlay_dir(path)
        return store, path

    def test_a_tree_prepared_the_normal_way_is_clean(self):
        import tempfile

        from utk_curio.sandbox.isolation import hardening

        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._tree(tmp)
            self.assertEqual(
                hardening.audit_node_overlays(store, uid=12345, gid=12345), [],
            )

    @posix_only
    def test_a_world_writable_tree_is_reported(self):
        import tempfile

        from utk_curio.sandbox.isolation import hardening

        with tempfile.TemporaryDirectory() as tmp:
            store, path = self._tree(tmp)
            os.chmod(path, 0o777)
            findings = hardening.audit_node_overlays(store, uid=12345, gid=12345)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("shadow", findings[0])

    @posix_only
    def test_a_tree_owned_by_the_execution_user_is_reported(self):
        """Ownership is the subtler version: 0755 looks fine until you notice
        the owner is the account node code runs as."""
        import tempfile

        from utk_curio.sandbox.isolation import hardening

        with tempfile.TemporaryDirectory() as tmp:
            store, path = self._tree(tmp)
            findings = hardening.audit_node_overlays(
                store, uid=os.stat(path).st_uid, gid=None,
            )
            self.assertEqual(len(findings), 1, findings)

    def test_no_overlays_at_all_is_not_a_finding(self):
        import tempfile

        from utk_curio.sandbox.isolation import hardening

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                hardening.audit_node_overlays(
                    os.path.join(tmp, "data"), uid=12345, gid=12345,
                ),
                [],
            )
