Curio installs two Autark packages from the tarballs in this folder, each in place of its 4.1.1 release on npm, until Autark releases their changes.

`urban-toolkit-autk-db-4.1.1-curio.1.tgz` is `@urban-toolkit/autk-db` 4.1.1, from its tag `@urban-toolkit/autk-db@4.1.1` (`1faf032b4fe83189246b9966c0ef324f5821c731`), with one commit of urban-toolkit/autark#132 on top:

- `8418124d` (`1c25e26c` on the tag): a heatmap's `avg`, `sum`, `min` and `max` bands read their cells from the joined values. In 4.1.1 every cell of those bands is 0.

It was built with Node 26 from the tag's lockfile, and its `dist/` is 4.1.1's file for file but for the two lines of that commit in `browser.js` and `node.js`. `npm pkg set version=4.1.1-curio.1`, then `npm pack`. Its dependencies are 4.1.1's.

- SHA-256: `9bfd2dab6d335a1c186892e1ff22cd97fd40add063a61bbd286f20f77e80c7bb`
- npm integrity: `sha512-2UOMzWt8JLqgDTnaD/3r1HtcSovir+h/QYTuZ+QC0oSsWUDYVgtmgLJ478VlluXn+uHTR/Dmzg5JcB98QeIs0g==`

Both of Curio's npm trees install it: the frontend's `package.json` names it as `file:vendor/autark/urban-toolkit-autk-db-4.1.1-curio.1.tgz`, and the repository's, which installs the sandbox's Node.js packages, as `file:utk_curio/frontend/urban-workflows/vendor/autark/urban-toolkit-autk-db-4.1.1-curio.1.tgz`. A pip install's launcher writes it beside the `package.json` it writes in `.curio/nodejs`. autk-grammar asks for autk-db `^4.1.1`, which the prerelease does not satisfy, so each tree's `overrides` give autk-grammar this copy too.

`urban-toolkit-autk-map-4.1.1-curio.4.tgz` is `@urban-toolkit/autk-map` packed from four urban-toolkit/autark PRs, applied in this order on top of autk-map 4.1.1:

- #118 at `60cebe0e5f91590866ed0db3f6d7e87018ecb885`: a raster's colors built with one color function, not a d3 scale per cell;
- #120 at `9452be13b4e112380315bb3cf4769f729911eb99`: a destroyed map releases its shared SSAO textures (three GPU textures per map, kept until garbage collection before);
- #121 at `3dba8d33b2ef5b60bd06f277aab39147424357a6`: a continuous legend's first label starts at its ramp's start and its last ends at the ramp's end, so a long last label is not cut at the legend's edge;
- #122 at `30833c6eb7d6e18c63e887c1ccfc50b81e079736`: numbers under a categorical color map are drawn in the color of their legend label, not in the color whose index is the number.

The frontend installs it in place of autk-map 4.1.1 from npm. autk-grammar asks for autk-map `^4.1.1`, which the prerelease does not satisfy, so the frontend's `overrides` give autk-grammar this copy too.
