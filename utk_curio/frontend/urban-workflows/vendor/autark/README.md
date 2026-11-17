Curio installs two Autark packages from the tarballs in this folder, in place of their npm releases, until the pull requests below are released.

## autk-map

`urban-toolkit-autk-map-4.1.1-curio.4.tgz` is `@urban-toolkit/autk-map` packed from four urban-toolkit/autark PRs, applied in this order on top of autk-map 4.1.1:

- #118 at `60cebe0e5f91590866ed0db3f6d7e87018ecb885`: a raster's colors built with one color function, not a d3 scale per cell;
- #120 at `9452be13b4e112380315bb3cf4769f729911eb99`: a destroyed map releases its shared SSAO textures (three GPU textures per map, kept until garbage collection before);
- #121 at `3dba8d33b2ef5b60bd06f277aab39147424357a6`: a continuous legend's first label starts at its ramp's start and its last ends at the ramp's end, so a long last label is not cut at the legend's edge;
- #122 at `30833c6eb7d6e18c63e887c1ccfc50b81e079736`: numbers under a categorical color map are drawn in the color of their legend label, not in the color whose index is the number.

Curio installs it in place of autk-map 4.1.1 from npm until Autark releases these changes. autk-grammar asks for autk-map `^4.1.1`, which the prerelease does not satisfy, so the frontend's `overrides` give autk-grammar this copy too.

## autk-grammar

`urban-toolkit-autk-grammar-4.5.0-curio.1.tgz` is `@urban-toolkit/autk-grammar` packed from urban-toolkit/autk-grammar #22 at `6a3f210a4def4abb095642b50cba03727beb8fd3` (autk-grammar 4.4.1 plus #22, whose last commit makes it 4.5.0): a map layer's `pointSize`, the radius of each point of a points layer in meters on the ground, which the grammar converts to autk-map's planar units by the Mercator scale at the layer's latitude. Its SHA-256 is `255e822caa2d09f27fdf20d3ad50712a3b0008fa487da1a507f599d4fa95ab3f`, and its npm integrity `sha512-Ig7qgplmqBBHp+lAiZDzJknD/BH0zrWvuRqu9ZSOtpNorBq8I9KvEDYJLu5MtZDhZH2fyUg5LhuNi4jVWGGfTg==`.

It was built in a clean checkout of that commit, with Node 26:

1. `npm ci` at the repository's root;
2. `npm run build` in `grammar`, then in `adapters/autk`, which also writes `build/autk-grammar-schema.json`;
3. `npm pkg set version=4.5.0-curio.1` in `adapters/autk`, so the version changes in the packed copy only;
4. `npm pack` of `adapters/autk`.

Curio's vendored schema (`utk_curio/backend/app/agents/schemas/autk-grammar.v1.json`) is that tarball's `build/autk-grammar-schema.json`, written by `python scripts/sync_autk_schema.py --tarball utk_curio/frontend/urban-workflows/vendor/autark/urban-toolkit-autk-grammar-4.5.0-curio.1.tgz`. Its record names the tarball, and `--check` compares the copy with it.

autk-grammar has another open pull request, #20, whose `pointSize` is a radius in planar units passed straight to autk-map. A release with that meaning would draw `"pointSize": 2` at about 1.5 m at Chicago instead of 2 m.

## Switching back to npm

Each package goes back on its own once a release carries its pull requests:

- autk-map: after autark #118, #120, #121 and #122;
- autk-grammar: after a release that carries #22's `pointSize`, in meters on the ground.

For autk-grammar, set `utk_curio/frontend/urban-workflows/package.json` to the release, update the lockfile, delete the tarball, run `python scripts/sync_autk_schema.py --version <release>`, and update `utk_curio/backend/tests/test_autark_packages.py`.
