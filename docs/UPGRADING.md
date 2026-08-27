# Upgrading

Changes that alter how an existing deployment behaves, with what to do about
each. Everything here starts cleanly after an upgrade, which is the reason it
needs writing down: the failure shows up later, in a feature that quietly stops
working or a bill that quietly grows.

Curio warns about each of these at startup when it can detect them (see
`utk_curio/backend/app/upgrade_notices.py`), so check your logs after the first
boot on a new version.

## Agent Catalog release

### The HuggingFace token moved to the account

`HUGGINGFACE_TOKEN` is no longer read. Gated models are unlocked per HuggingFace
account by accepting a licence, so one shared operator secret could never
represent what each user was entitled to download.

- Each user sets their own token in **AI Settings**, which wins.
- For a deployment-wide fallback, set `CURIO_DEFAULT_HUGGINGFACE_TOKEN` or pass
  `--huggingface-token` to `curio.py start`.

Without either, gated model downloads fail with a 401 and public models keep
working.

### Street Vision caches are per user, and the old cache is abandoned

Panoramas, overlays and model weights now live under
`.curio/users/<user-key>/streetvision/`. They used to share one deployment-wide
directory, which was a cross-user read: `/inference/overlay/<image_id>` is
unauthenticated, so anyone who could guess an image id could fetch somebody
else's imagery.

There is no migration, because a shared cache cannot be partitioned between
accounts after the fact. On the first run after upgrading:

- Street View panoramas are re-fetched, against your Google Maps quota.
- Model weights are re-downloaded, once per user rather than once per
  deployment.
- The old `.curio/streetvision/` tree is never read again and is safe to delete.

`STREETVISION_CACHE_DIR` and `STREETVISION_MODEL_CACHE_DIR` are ignored. If you
pointed either at a large volume, note that the per-user caches follow
`CURIO_LAUNCH_CWD` instead.

### Guests need a model named explicitly

`GUEST_LLM_MODEL` used to fall back to a built-in model name. Curio now ships no
model name at all, so a deployment that set only `GUEST_LLM_API_KEY` resolves no
guest provider and guest AI fails at run time.

Set `GUEST_LLM_MODEL`, or set the deployment default (`--llm-model` /
`CURIO_DEFAULT_LLM_MODEL`) that guests inherit.

### AI Settings inherits field by field

A user who filled in only the Model box used to lose the deployment's API key,
base URL and provider type along with it, and their runs went out
unauthenticated. Each field now falls back to the deployment default on its own.

Key and base URL are still not inherited across providers: a user on Anthropic
does not receive the deployment's OpenAI-compatible endpoint or key.

### The test stubs need `CURIO_TESTING`

`/api/testing/*` (including `stub-login`, which issues a session for any
username with no password) now requires `CURIO_TESTING` **as well as** a
non-production `CURIO_ENV`. `CURIO_ENV` defaults to `dev`, so on its own it
gated nothing on a deployment whose operator never set it.

The pytest and Playwright suites set `CURIO_TESTING` already. If you drive these
endpoints from your own tooling, set it there too.
