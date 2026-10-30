"""What stays the owner's when an editor the owner invited drives a dataflow's agents.

An invited editor (``projects/access.py``) works with the dataflow's agents as
its owner does, on the owner's model and key, in chats the owner and the
editors share. Two things wait for the owner, since they change the owner's
account rather than the dataflow:

* an install a proposal makes, a tool of :data:`ACCOUNT_INSTALL_TOOLS` (the
  tools ``src/contracts/agentInstalls.json`` names, which the review card reads
  too): only the owner applies or dismisses it (:func:`install_refusal`), in
  the same chat;
* a download into the Data Catalog that confirming a dataset selection would
  make (:func:`download_refusal`).

An editor who asks for either is refused with a 403 that names the owner. The
same review holds what an editor asks the owner to add to the dataflow from
the editor's own Data Catalog (``datasets/application/editor_requests.py``),
and only the owner applies or dismisses it too (:func:`owners_review`).
"""

from __future__ import annotations

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.common import shared_constants

#: The tools whose Apply installs into an account, which the dataflow's owner reviews.
ACCOUNT_INSTALL_TOOLS = frozenset(shared_constants.read("agentInstalls")["tools"])


def install_refusal(user_key: str, project_id: str, attachment_id: str, proposal_id: str,
                    owner: str) -> str | None:
    """Why an editor the owner invited may not apply or dismiss the proposal
    *proposal_id*: it installs into the account of *owner*, the dataflow's
    owner by name. None for any other proposal, and for one the attachment
    does not hold, which the apply refuses as it does for anyone."""
    spec = projects_storage.read_spec(user_key, project_id)
    proposal = attachments.find_proposal(spec, attachment_id, proposal_id) if isinstance(spec, dict) else None
    if not isinstance(proposal, dict) or proposal.get("tool") not in ACCOUNT_INSTALL_TOOLS:
        return None
    return owners_review(owner)


def owners_review(owner: str) -> str:
    """What an editor the owner invited is told who applies or dismisses an
    install, which waits for *owner*, the dataflow's owner by name."""
    return (
        f"This install waits for {owner}, who owns this dataflow: an install changes "
        "their account, so they review it."
    )


def download_refusal(owner: str) -> str:
    """What an editor the owner invited is told whose dataset selection
    would download a source into the Data Catalog: it waits for *owner*."""
    return (
        f"Downloading a source into the Data Catalog waits for {owner}, who owns this "
        "dataflow: ask them to confirm it."
    )
