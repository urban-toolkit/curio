"""The palette a node's appearance is checked and drawn in.

``noteColors.json`` in the frontend's ``src/contracts/`` holds it: the colors a
note's appearance can name, the default, the two inks, the two link colors and
the contrast an ink must reach. The built-in Note draws with that file, and
this module reads it (``utk_curio/common/shared_constants.py``) and hands it to
the rules of ``domain/node_appearance.py``, which read no file.
"""

from __future__ import annotations

from utk_curio.backend.app.packages.domain.node_appearance import NotePalette
from utk_curio.common import shared_constants

#: The palette Curio ships, as the frontend draws it.
NOTE_PALETTE: NotePalette = NotePalette.from_json(shared_constants.read("noteColors"))
