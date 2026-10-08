"""Curio: two settings, made before any module here imports the library.

OpenCV's wheel bundles its own OpenBLAS, which starts a thread per CPU when
``cv2`` is imported. A node's process may start only so many (the sandbox's
RLIMIT_NPROC), and on a host with many CPUs OpenBLAS fails to start them and
kills the node. SCOUT's code uses OpenCV for images, not linear algebra, so one
thread is enough.

matplotlib keeps its cache in the home folder, and a node run as the sandbox's
execution user cannot write there, so it warns on stderr. A folder of this
user's own in the temp folder.

An operator's own setting of either stands."""
import os
import tempfile

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), f"matplotlib-{os.getuid()}"))
