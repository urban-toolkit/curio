# Pack warehouse — design reference

This document captures **catalog and resolver evolution**: what is already shipped in-repo (fixture-backed catalog, family index, lineage-aware resolver) versus what remains for a **remote pack registry** and stricter publishing and semver. It complements [Overview](overview.md), [Manifest specification](manifest_spec.md), [Backend](backend.md), and [Frontend](frontend.md).

The actionable checklist is in [§7 Phasing (suggested)](#7-phasing-suggested) below.

---

## 1. Introduction

### Shipped today (fixture-backed)

- **Catalog** lists committed fixtures (`routes.py` → `list_catalog_packs`). Each pack row includes **`familyKey`**, **`channel`**, and the response adds **`families`** (grouped `dirName`s) plus **`catalogCollisions`** when duplicate `(familyKey, channel, version)` tuples appear.
- **Installed packs** use the same projection as catalog rows (including **`familyKey`** / **`channel`**).
- **Fork provenance** exists in the manifest as optional `lineage` — see `utk_curio/backend/app/packs/manifest.py`. Optional **`distribution.channel`** is validated there (default `stable`) via `utk_curio/backend/app/packs/pack_channel.py`.
- **Resolver** (`resolver.py`) walks `pack_deps` using **`<packId>`** only when uniquely resolvable; otherwise manifests must use **`<packId>@<major>`**. Lockfile entries include **`familyKey`** and optional **`lineageRoot`**. Python semver ranges still use the narrow `parse_version` / `parse_range` model (pre-release tails are not fully ordered).

### Roadmap (remote registry and richer semantics)

- **Catalog dedupe and/or family views** using a stable identity (see §2).
- **Publishing policy** that matches what the resolver and warehouse UI can enforce (§3).
- **Resolver precision** so multiple coordinates (majors/forks) are not ambiguous (§4).
- **Optional index** keyed by `lineage.root` for validation, upgrades, and search (§5).
- **Rich semver + channels** for ordering, ranges, and UX (§6).

### Relation to shipped fork UX (installed + palette)

The editor palette and Nodes Hub **My packs** rail already **group installed packs by `lineage.root`** on the frontend (`urban-workflows/src/utils/forkPackLineage.ts`). **Catalog cards intentionally stay flat** until product rules define a default or “authoritative” row per family for install. Once those rules exist (and/or the UI chooses to group by `familyKey`), the frontend can collapse catalog entries using the same mental model as installed packs (`familyKey` ≈ normalized `lineage.root`).

---

## 2. Catalog semantics and dedupe

### Family identity options

| Approach | Dedupe / group key | Strengths | Weaknesses |
|----------|-------------------|-----------|------------|
| A | **`lineage.root`** → canonical `packId@major` | Matches fork lineage already in manifests and UI grouping | Publishing must always set `root` correctly; “root not in catalog” is possible |
| B | **`familyId`** (UUID or stable string) in manifest | Stable even when lineage is absent or renamed | New field, author burden, migration |
| C | **`packId` + channel** (see §6) | Familiar to users | Does not alone distinguish forks that share an id/major story |

**Recommended default:** use **`lineage.root`** as the **family key** for catalog grouping and dedupe rules. Introduce **`familyId` or `catalogSlug`** only if first-party packs need a stable catalog id without lineage.

### Collision and uniqueness

Define a server-side rule for published catalog entries, for example:

- Unique **`(familyKey, channel, version)`** for stable channels, or
- Unique **`dirName`** per artifact with **familyKey** used only for grouping.

Violations should fail validation at index build time (fixtures) or at publish time (future remote registry).

### Frontend rule

**Do not collapse** duplicate-looking catalog cards until the API documents uniqueness and default selection (e.g. “latest stable per family”). Until then, optional **“Fork of …”** copy on cards when `lineage` is present is sufficient.

---

## 3. Publishing policy

Policy should be written down in [Manifest specification](manifest_spec.md), [Overview](overview.md), [Backend — Manifest loading](backend.md#manifest-loading), and [REST API reference](api-reference.md), and enforced in factory/publish paths:

- **Lineage:** `forkedFrom` must differ from this pack’s coordinate; `root` must differ from this pack’s coordinate (already validated in `manifest.py`). Optionally constrain whether `root.packId` must equal this pack’s `packId` for “same-namespace forks”.
- **Major:** treated as part of the **dispatch coordinate** (`packId@major`); breaking changes bump major.
- **Immutability:** a published artifact (directory name + content hash) is not overwritten; new releases are new rows.
- **Duplicate installs:** clarify whether two installed packs may share the same `lineage.root` (multiple forks) — today the UI supports it; resolver/lockfile should not merge their dependency graphs incorrectly.

---

## 4. Resolver evolution

### `pack_deps` precision

Bare **`pack_id`** keys work only when a single installed directory matches (**otherwise** the resolver errors and **`packId@major`** is required — **implemented**). Remaining roadmap items:

- **Major ranges** inside one dep key if product needs semver-style ranges across majors (not the same as pinning `packId@major`).
- Clear policy when multiple installs share a family root (fork overlap); see below.

### Forks in the graph

When multiple installed packs share a **family root**, resolution policy must state whether that is always allowed, or conflicts when kind ids overlap. The lockfile may optionally record **`lineage.root` per entry** for diagnostics and UI.

### Install probe

`POST /api/packs/resolve` (and install flows) should accept **proposed catalog rows** keyed by family + version/channel once those fields exist — align with `routes.py` resolver overrides pattern (`_resolver_overrides_for`).

---

## 5. Global index of `root`

**Purpose:** dedupe validation, “update available in this family”, search, and consistent API responses.

**Fixture-backed (no DB):** build an in-memory index when serving catalog (or at process startup): scan fixture manifests, compute `familyKey` from `lineage.root` (or fallback rule), attach **member list** (dir names, versions, channels).

**Remote registry (future):** persist the same keying in a store backing the registry service.

---

## 6. Rich semver and channels

### Model

- **`version`:** full semver string including **pre-release** (e.g. `1.0.0-beta.1`) and optional build metadata.
- **`channel`:** optional explicit tag (`stable`, `beta`, `rc`, `dev`) or derive a default from pre-release patterns — product choice must be documented.
- **Precedence:** total order on versions (npm-style subset is a common choice); **do not** strip pre-release tails without defining ordering (current `parse_version` limits).

### Backend phases

1. **Display/sort only:** shared comparison used by catalog and fork-member ordering.
2. **Resolver:** extend `parse_version` / `parse_range` and document whether ranges **include** pre-releases (npm rules: `^1.0.0` often excludes prereleases unless the bound is prerelease).
3. **Lockfile / project spec:** optional pin `{ packId, major, channel, constraint }` for reproducibility.

### UX

Channel **badges**, default “Stable” filter, fork-family **select** sorted by semver precedence (not lexical string), optional palette pill next to version.

---

## 7. Phasing (suggested)

1. **Manifest + resolver:** **done (partial)** — `packId@major` edges, ambiguous bare id errors; **remaining:** major *ranges* inside one dep key.
2. **Semver parity:** **not done** — `channel` surfaced; **remaining:** pre-release precedence + channel-aware ranges.
3. **Extended catalog API:** **done (fixture-backed)** — `familyKey`, `families`, `catalogCollisions`; **remaining:** remote registry + authoritative “default release” per family for UI collapse.
4. **Publishing validation** in factory/upload paths (**remaining**).
5. **Frontend:** channel chip **done**; catalog collapse-by-family **remaining** until (3) product rules land.

---

## 8. Related code

| Area | Path |
|------|------|
| Catalog + installed list routes | `utk_curio/backend/app/packs/routes.py` |
| Catalog index + collisions | `utk_curio/backend/app/packs/catalog_family.py` |
| Channel strings | `utk_curio/backend/app/packs/pack_channel.py` |
| Resolver + semver | `utk_curio/backend/app/packs/resolver.py` |
| Manifest + lineage | `utk_curio/backend/app/packs/manifest.py` |
| Frontend API types / calls | `utk_curio/frontend/urban-workflows/src/api/packsApi.ts` |
| Fork grouping (installed / palette) | `utk_curio/frontend/urban-workflows/src/utils/forkPackLineage.ts` |

---

## See also

- [Frontend](frontend.md) — routes, fork-family behaviour in the palette and Nodes Hub, `activePackKey` sync, session storage for fork selection.
- [Backend](backend.md) — storage, installer, seeder.
- [REST API reference](api-reference.md) — `/api/packs` endpoints and payloads.
