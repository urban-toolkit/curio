# Vendored Autark packages

Curio installs these four Autark packages from the tarballs in this folder instead of from npm, until the Autark fixes below are released. Tracking issue: #474.

| Package | Version | Integrity |
|---|---|---|
| `@urban-toolkit/autk-db` | `3.0.2-curio.2` | `sha512-0QBrbj/G7bc7rvZep0ozFI4b1fm+eRSV80IL5zQfiwZcl3itHzuCqw9xfXTGu8kkiUuvJIQJoo8Q96udIoUT0w==` |
| `@urban-toolkit/autk-compute` | `3.0.1-curio.1` | `sha512-+8OLfGZgFqd7Mr3TevACdecWyThJScc+tNjarmvqjBLKMcBEHtlmKqqWJ6nEo2pS8xZ7JLRdlYHKzwoHRzfxBQ==` |
| `@urban-toolkit/autk-map` | `3.0.1-curio.1` | `sha512-KPX2vUufmpN6k3p3yAZaAm31zchtEUhK4eYcQZxqOlGv+eyxzhjyxqecB9AXvVyG8557kP11YC3hOG0Wh1e33g==` |
| `@urban-toolkit/autk-plot` | `3.0.1-curio.1` | `sha512-9dq1WqP4CAi7XlPggFdSFd4Rgq4WY32Ffg6mXp8E7deU3WOAUXKpIw5ypS+DT5YJ0N7TwQdyFRXpPS2+wKqH1g==` |

`@urban-toolkit/autk-core` is not vendored: it stays the published `3.0.1`, which all four pin exactly.

## Source

Autark `main` at `77c8b32108c90d4f949519771540d152dfda83a6`, with these pull requests merged into it:

| Autark PR | Head | Packages | What it fixes |
|---|---|---|---|
| #101 `fix/agg-geometry-type` | `f494891a8b1545c3de5d81cbe28288edcc1ac51d` | autk-db | A building layer's `agg_geometry` is a GEOMETRY column, and a part whose building footprint union fails keeps its own geometry. |
| #102 `fix/published-type-paths` | `2a551f37e160cd76477882ae35548bb84d601195` | autk-db, autk-compute, autk-map, autk-plot | The published `.d.ts` files import `autk-core` instead of `../../autk-core/src`, so their types resolve. |
| #103 `fix/spatial-join-count` | `c053f976d7eb4b4754ba918ff5461bdc97345133` | autk-db | A spatial join's `count('*')` counts only matched rows, so an unmatched row counts 0. |
| #105 `fix/compute-global-arrays` | `fdddab989ad74220afb4e3f304ad9001e2a856ed` | autk-compute | A compute shader reads its array and matrix inputs in place from storage buffers, instead of copying them into function-local arrays, which some GPU drivers refuse to compile. |
| #107 `feat/osm-bbox-query-area` | `c647f64f0229acbe4119e919f4192efda2f1d0a1` | autk-db | `loadOsm` takes a WGS84 bounding box as well as named areas: no boundaries request, the box is the boundary, and every layer query is constrained to it. |

## How the tarballs were built

In a clone of Autark at the commits above:

1. `npm install` (Autark keeps no lockfile), then `make build`, `make typecheck`, `make package-validate` and the vitest suite.
2. `npm version --no-git-tag-version 3.0.2-curio.2` in `autk-db` (from #101, #102, #103 and #107), and `3.0.1-curio.1` in `autk-compute`, `autk-map` and `autk-plot`. The distinct versions keep webpack's cache from serving a published build under the same version.
3. `npm pack` in each of the four packages.

## How Curio uses them

- `utk_curio/frontend/urban-workflows/package.json` lists the four as `file:vendor/autark/<tarball>` dependencies, and its `overrides` point each one at that dependency (`"$@urban-toolkit/<package>"`), so `@urban-toolkit/autk-grammar` resolves to the same copies.
- The repository root `package.json` installs the same autk-db tarball for the sandbox's Node process, so the reference runner and the browser run the same autk-db.
- The `Dockerfile`'s `runtime_base` stage copies this folder before `npm ci`.

`npm ls @urban-toolkit/autk-db @urban-toolkit/autk-compute @urban-toolkit/autk-map @urban-toolkit/autk-plot @urban-toolkit/autk-core` shows one copy of each, in both the frontend and the root trees.

## Switching back to published releases

Each package can go back on its own, once the pull requests it carries are released:

- autk-compute: after Autark #105 and #102.
- autk-db: after Autark #101, #103, #107 and #102.
- autk-map and autk-plot: after Autark #102.

For each released package:

1. Delete its tarball and its `overrides` entry, and set its published range in the frontend `package.json`. Drop the direct autk-map and autk-plot entries once they are no longer vendored, since only autk-grammar needs them.
2. For autk-db, also set the root `package.json` back to the published range.
3. When this folder is empty, remove it and the `Dockerfile` `COPY` line.
4. Regenerate both lockfiles with Node 26, and clear `node_modules/.cache/webpack`.
5. Check `npm ls` in both trees: one copy of each package. A release that bumps autk-core would otherwise bring in a second one.
