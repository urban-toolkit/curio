"""The sandbox locks the state and data folders wherever a start keeps them.

``hardening.SENSITIVE_PATHS`` names its paths relative to the launch folder:
``.curio/data``, ``.curio/users``, ``.curio/budgets`` and the others. A start
can keep them elsewhere: ``--state-dir`` moves the ``.curio`` folder, and
``CURIO_SHARED_DATA`` names the artifact store. The sandbox hardened and
audited only the launch folder's paths, so with an execution user node code
could read the moved ones (every session's artifacts, every user's store),
and a hosted start did not refuse to serve.
"""

import os
import stat
import tempfile
import unittest
import unittest.mock

from utk_curio.sandbox.isolation import hardening

#: An execution account that owns none of the test's folders.
EXEC_UID = os.getuid() + 4242
EXEC_GID = os.getgid() + 4242

#: The state folder's paths of SENSITIVE_PATHS, as the state folder has them.
IN_THE_STATE_FOLDER = ("users", "budgets", "discovery", "fetched")


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _open_folder(path):
    os.makedirs(path, exist_ok=True)
    os.chmod(path, 0o755)
    return path


class Start:
    """A launch folder, a state folder and a data folder outside both, as
    ``--state-dir`` and ``CURIO_SHARED_DATA`` place them, each folder readable
    by every account."""

    def __init__(self, root):
        self.launch = _open_folder(os.path.join(root, "launch"))
        self.state = _open_folder(os.path.join(root, "state"))
        self.data = _open_folder(os.path.join(root, "data"))
        for name in IN_THE_STATE_FOLDER:
            _open_folder(os.path.join(self.state, name))

    def apply(self, *, hosted=False):
        return _apply(self.launch, self.data, hosted=hosted, state_dir=self.state)


def _apply(launch, data, *, hosted=False, **state):
    """``apply_and_report`` as the sandbox's start runs it, with Node's
    packages left out: they are the sandbox's own, outside the test's folders,
    and another test's to check."""
    with unittest.mock.patch.object(hardening, "node_package_trees", return_value=[]):
        return hardening.apply_and_report(
            launch, data, uid=EXEC_UID, gid=EXEC_GID, hosted=hosted, **state,
        )


class TestTheMovedFoldersAreLocked(unittest.TestCase):

    def test_every_folder_of_the_state_folder_is_locked(self):
        with tempfile.TemporaryDirectory() as root:
            start = Start(root)

            findings, fatal = start.apply(hosted=True)

            for name in IN_THE_STATE_FOLDER:
                with self.subTest(folder=name):
                    self.assertEqual(_mode(os.path.join(start.state, name)), hardening.DIRECTORY_MODE)
        self.assertEqual(findings, [])
        self.assertFalse(fatal)

    def test_the_artifact_store_its_variable_names_is_locked(self):
        with tempfile.TemporaryDirectory() as root:
            start = Start(root)

            _apply(start.launch, start.data)

            self.assertEqual(_mode(start.data), hardening.DIRECTORY_MODE)

    def test_the_files_of_a_moved_store_keep_their_modes(self):
        """A staged input is a hardlink to its store's file, which the child
        reads: the store's folder is the lock, never its files."""
        with tempfile.TemporaryDirectory() as root:
            start = Start(root)
            artifact = os.path.join(start.data, "artifacts", "a.parquet")
            dataset = os.path.join(start.state, "users", "1", "datasets", "d.csv")
            for path in (artifact, dataset):
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("x")
                os.chmod(path, 0o644)

            start.apply()

            self.assertEqual(_mode(artifact), 0o644)
            self.assertEqual(_mode(dataset), 0o644)

    def test_the_launch_folders_own_state_is_still_locked(self):
        """What a start before --state-dir kept in the launch folder stays as
        sensitive."""
        with tempfile.TemporaryDirectory() as root:
            start = Start(root)
            old_store = _open_folder(os.path.join(start.launch, ".curio", "data"))

            start.apply()

            self.assertEqual(_mode(old_store), hardening.DIRECTORY_MODE)


class TestAMovedFolderLeftOpenIsReported(unittest.TestCase):

    def test_a_hosted_start_refuses_to_serve_a_moved_folder_it_could_not_lock(self):
        with tempfile.TemporaryDirectory() as root:
            start = Start(root)

            with unittest.mock.patch.object(hardening, "_tighten", return_value=False):
                findings, fatal = start.apply(hosted=True)

        for path in [os.path.join(start.state, name) for name in IN_THE_STATE_FOLDER] + [start.data]:
            with self.subTest(path=path):
                self.assertTrue(
                    [finding for finding in findings if path in finding],
                    f"no finding names {path}: {findings}",
                )
        self.assertTrue(fatal)


class TestWhereTheStartKeepsItsPaths(unittest.TestCase):

    def test_a_start_that_moved_nothing_moved_no_path(self):
        with tempfile.TemporaryDirectory() as launch:
            self.assertEqual(
                hardening.moved_paths(
                    launch, state_dir=os.path.join(launch, ".curio"),
                    shared_data_dir=os.path.join(launch, ".curio", "data"),
                ),
                {},
            )
            self.assertEqual(hardening.moved_paths(launch), {})

    def test_every_path_of_the_state_folder_moves_with_it(self):
        with tempfile.TemporaryDirectory() as root:
            launch, state = os.path.join(root, "launch"), os.path.join(root, "state")

            moved = hardening.moved_paths(launch, state_dir=state)

        in_the_state_folder = {
            pattern for pattern, _reason in hardening.SENSITIVE_PATHS
            if pattern.startswith(".curio/")
        }
        self.assertEqual(set(moved), in_the_state_folder)
        for pattern, path in moved.items():
            with self.subTest(pattern=pattern):
                self.assertEqual(path, os.path.join(state, pattern[len(".curio/"):]))

    def test_a_folder_that_holds_the_launch_folder_moves_nothing(self):
        """Locking it would lock the execution user out of Curio's own files."""
        with tempfile.TemporaryDirectory() as root:
            launch = os.path.join(root, "launch")
            for holder in (launch, root):
                with self.subTest(folder=holder):
                    self.assertEqual(
                        hardening.moved_paths(launch, state_dir=holder, shared_data_dir=holder), {},
                    )

    def test_the_store_its_variable_names_wins_over_the_state_folders(self):
        with tempfile.TemporaryDirectory() as root:
            launch, state, data = (os.path.join(root, name) for name in ("launch", "state", "data"))

            moved = hardening.moved_paths(launch, state_dir=state, shared_data_dir=data)

        self.assertEqual(moved[".curio/data"], data)
        self.assertEqual(moved[".curio/users"], os.path.join(state, "users"))

    def test_a_state_folder_that_links_to_the_launch_folders_moves_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            launch = os.path.join(root, "launch")
            os.makedirs(os.path.join(launch, ".curio"))
            link = os.path.join(root, "state")
            os.symlink(os.path.join(launch, ".curio"), link)

            self.assertEqual(hardening.moved_paths(launch, state_dir=link), {})


if __name__ == "__main__":
    unittest.main()
