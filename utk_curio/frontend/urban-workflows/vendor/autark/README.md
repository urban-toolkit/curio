Curio installs two Autark packages from the tarballs in this folder, in place of their npm releases, until the pull requests below are released.

## autk-map

`urban-toolkit-autk-map-4.1.1-curio.4.tgz` is `@urban-toolkit/autk-map` packed from four urban-toolkit/autark PRs, applied in this order on top of autk-map 4.1.1:

- #118 at `60cebe0e5f91590866ed0db3f6d7e87018ecb885`: a raster's colors built with one color function, not a d3 scale per cell;
- #120 at `9452be13b4e112380315bb3cf4769f729911eb99`: a destroyed map releases its shared SSAO textures (three GPU textures per map, kept until garbage collection before);
- #121 at `3dba8d33b2ef5b60bd06f277aab39147424357a6`: a continuous legend's first label starts at its ramp's start and its last ends at the ramp's end, so a long last label is not cut at the legend's edge;
- #122 at `30833c6eb7d6e18c63e887c1ccfc50b81e079736`: numbers under a categorical color map are drawn in the color of their legend label, not in the color whose index is the number.

Curio installs it in place of autk-map 4.1.1 from npm until Autark releases these changes. autk-grammar asks for autk-map `^4.1.1`, which the prerelease does not satisfy, so the frontend's `overrides` give autk-grammar this copy too.

## autk-grammar

`urban-toolkit-autk-grammar-5.0.0-curio.2.tgz` is `@urban-toolkit/autk-grammar` packed from urban-toolkit/autk-grammar #22's branch `feat/point-size` at `80c6cfd8cd6523af32b7429b339d9520803e3ad0`, the commit that bumps it to 5.0.0, a release candidate of 5.0.0: autk-grammar 4.4.1 with #20 (5.0.0's keys), #21 (`workspace`) and #22 (a map layer's `pointSize`, the radius of each point of a points layer in meters on the ground, which the grammar converts to autk-map's planar units by the Mercator scale at the layer's latitude), and 5.0.0's exports, its `./data` entry among them. Its SHA-256 is `56b12ec9f0c53bcda25a5bdaf9d8d6606d7772298109140d97029088f60a3dd7`, and its npm integrity `sha512-JVzQh+XRDs9WP8JkVVNDS0CuhwCTXUW7iWd+39xUy8t2LjaoVE2OxPfa5wggLQ9GJGs0zNMxTvBOYP3tkF7vPQ==`.

It was built in a clean checkout of that commit, with Node 26:

1. `npm ci` at the repository's root;
2. `npm run build` in `grammar`, then in `adapters/autk`, which also writes the `./data` entry and `build/autk-grammar-schema.json`;
3. `npm pkg set version=5.0.0-curio.2` in `adapters/autk`, so the version changes in the packed copy only;
4. `npm pack` of `adapters/autk`.

Curio's vendored schema (`utk_curio/backend/app/agents/schemas/autk-grammar.v1.json`) is that tarball's `build/autk-grammar-schema.json`, written by `python scripts/sync_autk_schema.py --tarball utk_curio/frontend/urban-workflows/vendor/autark/urban-toolkit-autk-grammar-5.0.0-curio.2.tgz`. Its record names the tarball, and `--check` compares the copy with it.

## Switching back to npm

Each package goes back on its own once a release carries its pull requests:

- autk-map: after autark #118, #120, #121 and #122;
- autk-grammar: once 5.0.0 is on npm.

For autk-grammar, set `utk_curio/frontend/urban-workflows/package.json` to the release, update the lockfile, delete the tarball, run `python scripts/sync_autk_schema.py --version <release>`, and update `utk_curio/backend/tests/test_autark_packages.py`.
