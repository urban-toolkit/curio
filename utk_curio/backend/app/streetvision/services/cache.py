"""Per-user on-disk cache for fetched Street View imagery + overlays.

Two cache namespaces, both under the caller's own user directory:

    .curio/users/<user-key>/streetvision/images/     raw JPEG panoramas
    .curio/users/<user-key>/streetvision/overlays/   segmentation overlay PNGs

**Why per user.** This was one deployment-wide directory at
``.curio/streetvision/cache/``, overridable with a ``STREETVISION_CACHE_DIR``
env var. Neither survived, for the same reason: the contents are not shared
infrastructure, they are one person's work. The panoramas were fetched with
that user's own Google Maps key and count against their quota, the overlays
were computed from their runs, and ``/inference/overlay/<image_id>`` serves
them on an unauthenticated route - so a shared directory meant anyone who
could guess an image id could read someone else's imagery. Keying the path by
user closes that, and puts this state where every other piece of Curio's
per-user state already lives.

The user key is resolved in the request and passed down: inference runs on a
detached worker thread with no request context.
"""

import os
from typing import Optional

from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base


def user_root(user_key: str) -> str:
    """``.../users/<user_key>/streetvision/`` (may not exist yet).

    Goes through the shared ``_user_key_segment`` guard, so a key that is
    neither ``guest`` nor numeric raises rather than escaping the user store.
    """
    return str(_users_base() / _user_key_segment(user_key) / "streetvision")


def images_dir(user_key: str) -> str:
    path = os.path.join(user_root(user_key), "images")
    os.makedirs(path, exist_ok=True)
    return path


def overlays_dir(user_key: str) -> str:
    path = os.path.join(user_root(user_key), "overlays")
    os.makedirs(path, exist_ok=True)
    return path


def overlay_path(user_key: str, image_id: str) -> Optional[str]:
    """The on-disk path to one of *this user's* overlay PNGs, or None.

    A miss now also covers "it belongs to somebody else", which is the point.
    """
    stem = os.path.splitext(image_id)[0]
    path = os.path.join(overlays_dir(user_key), f"{stem}_overlay.png")
    return path if os.path.exists(path) else None
