"""Curio: OpenCV's wheel bundles its own OpenBLAS, which starts a thread per
CPU when ``cv2`` is imported. A node's process may start only so many (the
sandbox's RLIMIT_NPROC), and on a host with many CPUs OpenBLAS fails to start
them and kills the node. SCOUT's code uses OpenCV for images, not linear
algebra, so one thread is enough. Set before any module here imports ``cv2``;
an operator's own setting stands."""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
