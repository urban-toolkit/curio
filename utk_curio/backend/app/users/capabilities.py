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


def install_refusal(user, *, noun: str = "packages") -> str | None:
    """Why *user* may not trigger a pip run here, or ``None`` if they may.

    One rule for every install path. It used to be two: the ``/libraries``
    routes checked the guest rule (#309) and the eight package routes that reach
    the same chokepoint checked nothing at all (#332). The question is the same
    either way, because the interpreter is the same.

    Two parts, in this order, and the order matters:

    1. **No auth means a local run, and a local run always may.** Without
       ``--deploy`` there is no auth, the single local user is signed in as the
       guest, and there is no isolation. One person, one interpreter, their own
       machine: nothing to scope, and nobody to protect them from. Installing
       and removing libraries there is the everyday path.
    2. **A hosted guest may not.** Every anonymous visitor resolves to one
       account, so one visitor's install changes what every other visitor's
       nodes import, and the disk it costs has no owner to account it to.

    There used to be a third: nobody may on a hosted instance that cannot scope
    installs. That instance no longer exists. ``--deploy`` now requires isolated
    node execution and refuses to start without it
    (``main.py::_refuse_unisolated_deploy``), so a signed-in user's install
    always lands in their own overlay. The rule had an escape hatch
    (``--allow-shared-installs``) which went with it: a configuration nobody can
    boot needs no flag to permit it.

    ``None`` passes, as it does for :func:`can_manage_shared_catalog`: that is
    the launcher installing every manifest's dependencies at boot, which has no
    request and no user, and refusing it would refuse startup.

    Read at call time so tests and a reloaded config are honoured.
    """
    from utk_curio.backend import config

    if config.CURIO_NO_AUTH:
        return None
    if user is None:
        return None
    if getattr(user, "is_guest", False):
        return (
            f"Installing {noun} is not available for guest users, because every "
            f"guest shares one account. Sign in with an account to install one."
        )

    return None


def settings_refusal(user) -> str | None:
    """Why *user* may not change the account's catalog settings, or ``None``.

    The same two parts as :func:`install_refusal`: a local run always may, and
    a hosted guest may not, because every guest shares one account and one
    visitor's keyword types would become every visitor's.
    """
    from utk_curio.backend import config

    if config.CURIO_NO_AUTH or user is None:
        return None
    if getattr(user, "is_guest", False):
        return (
            "Changing catalog settings is not available for guest users, because "
            "every guest shares one account. Sign in with an account to change them."
        )
    return None


def library_install_refusal(user) -> str | None:
    """Why *user* may not install or remove a library. See :func:`install_refusal`."""
    return install_refusal(user, noun="libraries")


def package_install_refusal(user) -> str | None:
    """Why *user* may not install a package. See :func:`install_refusal`."""
    return install_refusal(user, noun="packages")
