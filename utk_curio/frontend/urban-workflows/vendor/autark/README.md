`urban-toolkit-autk-map-4.1.1-curio.3.tgz` is `@urban-toolkit/autk-map` packed from three urban-toolkit/autark PRs, applied in this order on top of autk-map 4.1.1:

- #118 at `60cebe0e5f91590866ed0db3f6d7e87018ecb885`: a raster's colors built with one color function, not a d3 scale per cell;
- #120 at `9452be13b4e112380315bb3cf4769f729911eb99`: a destroyed map releases its shared SSAO textures (three GPU textures per map, kept until garbage collection before);
- #121 at `3dba8d33b2ef5b60bd06f277aab39147424357a6`: a continuous legend's first label starts at its ramp's start and its last ends at the ramp's end, so a long last label is not cut at the legend's edge.

Curio installs it in place of autk-map 4.1.1 from npm until Autark releases these changes.
