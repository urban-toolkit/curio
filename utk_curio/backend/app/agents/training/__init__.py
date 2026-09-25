"""Fine-tuning on Curio's own approved example fixtures (memo dev/122, ``DEC-078``).

Four modules, three of them pure:

- :mod:`.dataset` builds the chat-format training rows from approved
  ``train``-split fixtures, with the oracle's plan bytes as the target.
- :mod:`.consent` states what would leave the install and records the act of
  agreeing to send it.
- :mod:`.records` is the on-disk job record, append-only in its events.
- :mod:`.gate` decides whether a trained model has been evaluated on the
  held-out split — deterministically, and never by asking a model.

Nothing here trains anything by itself: the provider owns the job (see
``providers.fine_tuning_capabilities`` and its four primitives), and the
service layer that stitches them together is the only part that touches both
the store and the endpoint.
"""
