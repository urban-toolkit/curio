# Vendored autk-grammar

Curio installs `@urban-toolkit/autk-grammar` from the tarball in this folder instead of from npm, until a release carries the change below. Tracking issue: #474. The other Autark packages, autk-compute, autk-db, autk-map, autk-plot and autk-core, come from npm at 4.0.0.

| Package | Version | Integrity |
|---|---|---|
| `@urban-toolkit/autk-grammar` | `0.3.0-curio.1` | `sha512-R/HbwU0kNh/EnA1fu2eFfJPCVz7OOKcrdQn+4v96xNSg1R3th+AcjgKyz6xA9qRIY+VXvFBM4El2oicpX0DPRQ==` |

## Source

urban-toolkit/autk-grammar pull request #7, `feat/batched-compute-storage-buffers`, at `7da56411a72691cc8adf6e4b55cc2aa00d50cf7f` (`main` at `0.3.0` plus one commit): a batched compute packs as many features as its largest array fits in one storage buffer binding, instead of 2000. autk-compute 4.0.0 reads these arrays from storage buffers.

## How the tarball was built

In a clone of autk-grammar at the commit above: `npm ci`, `npm version --no-git-tag-version 0.3.0-curio.1` in `adapters/autk`, `make build`, then `npm pack` in `adapters/autk`.

## How Curio uses it

- `utk_curio/frontend/urban-workflows/package.json` lists it as a `file:vendor/autark/<tarball>` dependency. autk-grammar 0.3.0 asks for the 3.x Autark packages; the `overrides` there give it the 4.0.0 ones the frontend uses: autk-compute, autk-db, autk-map and autk-plot through their direct dependencies (`"$@urban-toolkit/<package>"`), and autk-core by version.
- The `Dockerfile`'s `frontend_builder` stage copies this folder before `npm install`.

`npm ls @urban-toolkit/autk-db @urban-toolkit/autk-compute @urban-toolkit/autk-map @urban-toolkit/autk-plot @urban-toolkit/autk-grammar @urban-toolkit/autk-core` shows one copy of each.

## Switching to a published release

Once an autk-grammar release carries #7 on Autark 4:

1. Delete this folder, the `Dockerfile` line that copies it, and the grammar's `file:` entry; set the release's version in the frontend `package.json`.
2. Drop the Autark `overrides` the release no longer needs.
3. Regenerate the lockfile with Node 26, and clear `node_modules/.cache/webpack`.
4. Check `npm ls`: one copy of each Autark package.
