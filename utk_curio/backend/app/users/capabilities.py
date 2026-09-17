"""Account capability predicates.

One place to answer "may this account do X?" for rules that turn on WHO the
caller is rather than on what they own. Ownership questions stay with the
resource (``CatalogMutations._assert_is_publisher``); this module answers the
prior question of whether the account may touch shared state at all.

Lives under ``users/`` so datasets, packages and agents can all import it
without the circular-import dance ``packages/services.py`` works around with a
local copy of ``_user_dir_key``.
"""
from __future__ import annotations


def is_shared_guest(user) -> bool:
    """True for the one account every guest sign-in resolves to.

    ``users.services.signin_guest`` always returns the row named by
    ``CURIO_SHARED_GUEST_USERNAME``, so every visitor browsing as a guest is
    literally the same ``User``. Any rule that compares identity therefore
    cannot tell two guests apart -- including ``manifest.publisher ==
    str(user)``, because ``User.__repr__`` yields the same string for all of
    them.
    """
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    return bool(
        user is not None
        and getattr(user, "is_guest", False)
        and getattr(user, "username", None) == CURIO_SHARED_GUEST_USERNAME
    )


def can_manage_shared_catalog(user) -> bool:
    """Whether *user* may publish to, or remove from, a shared catalog tree.

    A shared catalog is global: one directory tree every account reads. A write
    there is not scoped to the writer, so it needs an account the platform can
    hold responsible for it. The shared guest is not one -- it is a single row
    shared by every anonymous visitor, so "the publisher" and "some other
    guest" are the same principal and an ownership check cannot separate them
    (#222).

    Note this is deliberately NOT a check on the *dataset*: a guest may still
    import, compute and delete datasets in the guest store. What it withholds
    is reaching into state other accounts can see.

    ``None`` passes. It is the internal/system caller -- the context that
    publishes as ``"Data Catalog"`` rather than as a user -- and it cannot
    arrive from a request, because every dataset route is behind
    ``@require_auth``. Authentication is the route's job; this predicate only
    answers the question authentication cannot: whether a real, distinguishable
    account is behind the call.
    """
    return not is_shared_guest(user)


def library_install_refusal(user) -> str | None:
    """Why *user* may not install or remove a library, or ``None`` if they may.

    The shared guest is every anonymous visitor at once, so one visitor's
    install changes what every other visitor's nodes import, and the disk it
    costs has no owner to account it to. Without auth the one local user IS
    the shared guest, so this applies only when auth is on.

    Not conditional on isolation. Under ``--deploy`` an install lands in the
    caller's own overlay, which scopes it away from signed-in accounts but
    not from the next anonymous visitor: they share the one guest key.

    Read at call time so tests (and a reloaded config) are honoured.
    """
    from utk_curio.backend import config

    if not config.CURIO_NO_AUTH and getattr(user, "is_guest", False):
        return (
            "Installing libraries is not available for guest users. Sign in "
            "with an account to install one."
        )
    return None
