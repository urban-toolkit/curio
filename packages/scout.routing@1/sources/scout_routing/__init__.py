"""Curio: matplotlib, which osmnx imports, keeps its cache in the home folder,
and a node run as the sandbox's execution user cannot write there, so it warns
on stderr. A folder of this user's own in the temp folder; an operator's own
setting stands."""
import os
import tempfile

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), f"matplotlib-{os.getuid()}"))
