Curio installs two Autark packages from the tarballs in this folder, each in place of its 4.1.1 release on npm, until Autark releases their changes.

`urban-toolkit-autk-db-4.1.1-curio.2.tgz` is `@urban-toolkit/autk-db` 4.1.1, from its tag `@urban-toolkit/autk-db@4.1.1` (`1faf032b4fe83189246b9966c0ef324f5821c731`), with the three fix commits of urban-toolkit/autark#132 on top, in this order (each at its commit on #132's branch, then as cherry-picked on the tag):

- `8418124bb9078b7759dba7f840da4f798658fad9` (`1c25e26e6a961f70d6a3288ed3c5d5bf2f3cd1cf`): a heatmap's `avg`, `sum`, `min` and `max` bands read their cells from the joined values. In 4.1.1 every cell of those bands is 0.
- `ad20682e34e41ccdfc8a82769a5bd157627ffd42` (`bb2f41ac5535c19eb2394292ace6c8e0ebc38173`): a band with `normalize: true` reads the values the join rescales from 0 to 1. In 4.1.1 it reads the raw values.
- `e45655295bd0831ea6283554cded28f2cc8326e5` (`3b0a2f5b380e2a3755f637fb53f071caed95773f`): each band gets a label of its own. A normalized band's label ends in `_norm`, and bands of one aggregate over different columns name their columns, such as `avg_noise_db`. In 4.1.1 such bands share `<aggregateFn>_<table>`.

It was built with Node 26 from the tag's lockfile. Its `dist/` is 4.1.1's file for file but for those commits' lines in `browser.js` and `node.js` and a comment in `use-cases/build-heatmap/use-case.d.ts`. `npm pkg set version=4.1.1-curio.2`, then `npm pack`. Its dependencies are 4.1.1's.

- SHA-256: `d9a4eb8ac79fb194dc32ac84c47d4e78f6b0546e13da8e804977a61582cbe12e`
- npm integrity: `sha512-vYoV3Q0Juj7KxiCdLcqRJmxm8egmC8EELxcLg5Pz/sg4oONGiW6s9Egizuka0IwcCim9dhS55tdVGrNITxbwwg==`

Both of Curio's npm trees install it: the frontend's `package.json` names it as `file:vendor/autark/urban-toolkit-autk-db-4.1.1-curio.2.tgz`, and the repository's, which installs the sandbox's Node.js packages, as `file:utk_curio/frontend/urban-workflows/vendor/autark/urban-toolkit-autk-db-4.1.1-curio.2.tgz`. A pip install's launcher writes it beside the `package.json` it writes in `.curio/nodejs`. autk-grammar asks for autk-db `^4.1.1`, which the prerelease does not satisfy, so each tree's `overrides` give autk-grammar this copy too.

`urban-toolkit-autk-map-4.1.1-curio.4.tgz` is `@urban-toolkit/autk-map` packed from four urban-toolkit/autark PRs, applied in this order on top of autk-map 4.1.1:

- #118 at `60cebe0e5f91590866ed0db3f6d7e87018ecb885`: a raster's colors built with one color function, not a d3 scale per cell;
- #120 at `9452be13b4e112380315bb3cf4769f729911eb99`: a destroyed map releases its shared SSAO textures (three GPU textures per map, kept until garbage collection before);
- #121 at `3dba8d33b2ef5b60bd06f277aab39147424357a6`: a continuous legend's first label starts at its ramp's start and its last ends at the ramp's end, so a long last label is not cut at the legend's edge;
- #122 at `30833c6eb7d6e18c63e887c1ccfc50b81e079736`: numbers under a categorical color map are drawn in the color of their legend label, not in the color whose index is the number.

The frontend installs it in place of autk-map 4.1.1 from npm. autk-grammar asks for autk-map `^4.1.1`, which the prerelease does not satisfy, so the frontend's `overrides` give autk-grammar this copy too.
