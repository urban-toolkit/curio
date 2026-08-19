# Dev/89 — Agent-authored node packages and custom node kinds

Date: 2026-08-19  
Status: approved 2026-08-19 — implementation in progress per the §9 commit breakdown  
Evidence base: `docs/EXTENDING.md`, `docs/schemas/node-package.v4.json`, package factory/install/runtime registries, `dev/48`, `dev/16`, `dev/84`, current built-in agent roster and prompts, and the suppliedx Dataflow Builder reference recording plus its extracted concept frames.

**DOD clarification (2026-08-19).** The reference recording does not require a research execution environment inside the node. The Node Researcher proof is a presentation-only custom node: a post-it-like square whose fixed body is populated from an agent reply (for the proof, web-search results), rendered as safe plain text or Markdown, and assigned a configurable per-node color. It does not run Python, perform the web search itself, require a generated backend endpoint, or depend on the future backend sandbox/restart lifecycle.

## 1. Problem Statement

Curio can already load node packages with multiple templates, Python and JavaScript dependency declarations, package-owned source files, and dynamically loaded custom behavior bundles. The human-facing package factory can also create or replace an installed package. The agent surface, however, exposes only a narrow `node.template.create` fallback owned by Node Builder. Its current proposal contract describes a single template with starter content; it does not author a package-level behavior bundle, package assets, multiple templates, dependency constraints, or a safe extension of an existing package.

The mismatch matters because a “totally customizable” node is not merely a node instance or template manifest entry. Under `docs/EXTENDING.md`, a genuinely new look or interaction requires a package-level `behaviorScript` whose pre-built JavaScript registers a React behavior hook. A sophisticated node may also need package assets, JavaScript libraries bundled into that behavior script, Python dependencies for sandbox code, or backend endpoints for external APIs and long-running work. The existing Node Builder abstraction is too narrow to own and review all of those package-level effects.

The expected behavior is:

- Node Builder continues to reuse installed templates first and creates ordinary node instances when a suitable template exists.
- When no suitable template exists, Node Builder can request a new node kind through a package-authoring specialist instead of trying to synthesize a partial template itself.
- Dataflow Builder can delegate package-level work for a plan, including creating a new package or extending an eligible existing package with one or more templates.
- The result is a reviewable, installable package draft that follows `docs/EXTENDING.md`: valid manifest, sources, compiled `scripts/behaviors.js` when custom UI/behavior is needed, integrity hashes, documentation, dependencies, and template descriptors.
- Applying the reviewed result installs or replaces the package, adds it to the current project lockfile, refreshes the runtime registry, and only then creates requested node instances.
- For the Node Researcher proof of done, the created template renders a compact post-it-style square with the agent’s fixed web-search result text in its body, optionally formatted through a safe Markdown previewer. Each node instance can set its own post-it background color without creating or rebuilding another template/package. It is a display node, not a generic code editor or executable research node.

## 2. Scope

Included:

- A new `agent.package-builder` composite/specialist with package authoring and extension capabilities.
- Delegation from Node Builder and Dataflow Builder.
- A compatibility path for the existing `node.template.create` intent.
- New reviewed package-draft proposal contracts for creating a package or extending an installed, user-editable package.
- Manifest templates, source starters, package README/license text, `behaviorScript`, behavior source and compiled bundle, icons/assets allowed by the archive format, Python/JS/package dependency declarations, and integrity generation.
- Safe build, validation, install/replace, project-lockfile update, runtime registry refresh, and requested node instantiation.
- Node Researcher as the first vertical proof: one custom JS presentation behavior, fixed agent-supplied text, a post-it/Markdown appearance, and per-node color configuration. No Python source or dependency is needed for this proof.
- Backend agent tools/services, package-domain authoring/build services, frontend review UI and registry/canvas synchronization, capability schemas/prompts, and tests.

Related paths to check:

- `utk_curio/backend/app/agents/{builtin.py,tools.py,services.py,delegation.py,content.py}` and agent prompts.
- `utk_curio/backend/app/packages/{factory.py,manifest.py,installer.py,routes.py,services.py,dependency_scanner.py}`.
- `utk_curio/frontend/urban-workflows/src/registry/*`, package APIs, install review UI, agent review cards, and canvas mutation bridge.
- `utk_curio/frontend/urban-workflows/webpack.packages.config.js` only as evidence for the bundle contract; runtime agent-authored packages must not require editing this first-party build list.
- `docs/EXTENDING.md` and `docs/schemas/node-package.v4.json`.

Out of scope for the first slice:

- Automatically publishing agent-authored packages to the global catalog.
- Modifying read-only/built-in packages in place.
- Arbitrary generated Flask blueprints loaded into the running Curio backend. The first slice should use pure frontend behavior or the existing Python/JavaScript execution surfaces.
- Installing arbitrary npm packages into Curio’s main frontend at runtime. Package JS dependencies must be compiled into the package behavior bundle, with Curio runtime externals allowlisted.
- Silent creation, compilation, installation, replacement, publishing, or graph mutation.

Explicit follow-ups, rather than permanently excluded capabilities:

- **Follow-up A — Curio package backend sandbox.** Define a permissioned, process-isolated runtime for generated server-side package code. It must not import generated Flask blueprints into Curio’s host backend process. It needs a versioned request/response contract, per-package filesystem and network policy, resource quotas, secret mediation, dependency isolation, health checks, audit logs, and termination controls.
- **Follow-up B — activation and restart lifecycle.** Define how a newly installed or upgraded backend-bearing package becomes active: start/hot-load versus controlled Curio restart, readiness probes, in-flight request/job draining, version routing, rollback to the prior healthy package, crash-loop handling, and clear user-visible “restart required/activating/failed” states. Follow-up B depends on the sandbox contract from Follow-up A.
- **Follow-up C — agent-driven recolor of existing notes.** A narrow reviewed `node.appearance.write` mutation pinned to the current appearance digest, letting an agent propose recoloring an already-created post-it. The first slice covers agent-selected color at node creation and direct user edits through the node’s color control only; it ships no agent mutation for existing-node appearance.

The first-slice build worker and visual-preview sandbox described below isolate compilation and preview only; they do not execute a package as a production backend service and therefore do not substitute for Follow-up A.

## 3. Recommended Implementation Approach

### Recommendation and ownership

Create a new **Package Builder** agent. Do not broaden Package Recommendation into authoring.

The current Package Recommendation contract and prompt explicitly say it “never authors a package” and ground every recommendation in the catalog. That separation is valuable: recommendation is read-mostly discovery plus reviewed install; authoring is a code-generation, build, integrity, replacement, and supply-chain-sensitive workflow.

Use this delegation topology:

```text
Dataflow Builder
  ├─ Node Builder ── package.create-or-extend ──> Package Builder
  └─ package.create-or-extend ─────────────────> Package Builder

Node Builder
  ├─ node.create (reuse installed template)
  └─ node.template.create (compatibility intent)
       └─ delegates package.create-or-extend to Package Builder

Package Recommendation
  └─ catalog discovery / dependency identification / reviewed install only
```

- **Node Builder** owns the decision “reuse an existing node type or request a new kind” and owns creation/configuration of node instances.
- **Package Builder** owns the package artifact: new or extended package, template definitions, behavior source/bundle, dependencies, assets, integrity, validation, and reviewed install/replace proposal.
- **Dataflow Builder** delegates to Node Builder for per-node work. It delegates directly to Package Builder when the plan calls for a coherent multi-template package or extension, avoiding repeated single-template package rewrites.
- **Package Recommendation** remains unchanged and can still identify an existing catalog package before Package Builder is invoked. Package Builder is reached only after reuse/catalog discovery cannot satisfy the need or the user explicitly requests authoring/extension.

### Capabilities and tools

Add capabilities such as:

- `package.build`: create a complete new node package draft.
- `package.extend`: add or revise templates in an installed user-editable package while preserving untouched files and templates.
- `node.kind.author`: author one custom node kind within a package; exposed by Package Builder and used by Node Builder delegation.

`package.create-or-extend` (used in the delegation topology above) is the delegation intent name, not a fourth capability: it is the request Node Builder and Dataflow Builder send to Package Builder, which resolves it to `package.build` for a new package or `package.extend` for an installed user-editable one.

Prefer one package-domain mutate tool, for example `package.draft.apply`, with a discriminated proposal payload (`mode: create | extend`). Agent tools should call a package-domain service; they must not duplicate manifest, archive, dependency, or integrity logic.

Keep `node.template.create` as a compatibility-level Node Builder action so existing prompts/tests and the user mental model remain coherent, but change its implementation boundary: it mints or delegates a package-authoring request and ultimately receives the canonical created template ID. Do not maintain a second single-template factory path beside Package Builder.

Extend requested post-install node instances and `node.create` additively with optional `appearance: { backgroundColor }`. Validation/normalization is owned by one shared node-appearance utility used by proposal minting, package-build output validation, Apply, spec serialization, and the frontend behavior. Existing callers that omit `appearance` remain byte-for-byte compatible. Agent-requested recolor of an existing post-it is deferred to the reviewed `node.appearance.write` mutation defined as Follow-up C; direct user changes through the node’s color control remain ordinary canvas edits and are in the first slice.

### Artifact pipeline

1. Read the current project package lockfile, installed manifests, template registry, and—when extending—an immutable snapshot/digest of the target package.
2. Produce a bounded structured package draft: manifest fields, complete template list, sources, behavior entry source, assets, README, explicit rationale, and requested node instances.
3. Validate the draft against `node-package.v4`, package policy, safe paths, allowed externals, source-size limits, and dependency policy.
4. Build custom behavior code in an isolated, deterministic builder. Compile TS/JS/TSX to `scripts/behaviors.js`, externalizing only Curio-provided React/ReactFlow/runtime globals. Resolve JS dependencies for the build and bundle them into the artifact; do not rely on browser-time npm installation.
5. Run static safety checks and produce a build report: files, hashes, permissions, Python/JS/package dependencies, bundle size, warnings, and diffs for extension mode.
6. Mint a review proposal. The review shows package/template diff, generated UI preview or screenshot, dependency/permission impact, replacement scope, and nodes that will be inserted after install.
7. On Apply, re-check the base digest, atomically install or replace through the existing installer, update the current project lockfile, refresh package/behavior/template registries, and then create the requested nodes. A failure before the final graph step leaves no partial graph mutation.

The existing factory is the correct lower-level archive/manifest/integrity seam but needs an additive artifact-aware builder API. Today it accepts one source starter per template and derives dependencies from imports; it does not compile behavior source or place arbitrary behavior/assets into the archive. Extend the package domain rather than placing compilation in the agents domain.

### Complete isolated package build service

The first slice requires a real build service, not an in-process helper that invokes a package manager against agent-generated input. It should have the following components and boundaries.

#### 1. Typed build contract and immutable inputs

- A versioned `PackageBuildRequest` with `mode: create | extend`, target coordinate, pinned base digest for extensions, manifest draft, complete text/binary artifact map, behavior entry points, dependency constraints, requested preview templates, and requested post-install node instances.
- Strict request limits: number of files/templates, path length, individual/total source size, asset MIME/type and size, dependency count, and build timeout class.
- Content-address the normalized request before work starts. The build ID and input digest identify retries and make identical successful builds cacheable.
- Treat every generated file as untrusted bytes. The builder receives no user/provider credentials, project transcript, host environment, or writable reference to the installed package store.

#### 2. Extension snapshot and merge planner

- Copy an eligible installed package into a read-only, digest-pinned base snapshot; never build directly in the installed directory.
- Compute a file- and template-level three-way plan: preserved, added, modified, renamed, and removed. V1 rejects implicit removal and behavior-key/template-ID collisions.
- Generalize `preserve_unedited_sources` to preserve all untouched sources, scripts, assets, README/license files, and unknown-but-allowed package files.
- Produce the same normalized diff for the review UI and for Apply-time stale verification so displayed and executed changes cannot diverge.

#### 3. Ephemeral workspace manager

- Allocate a fresh temporary workspace per build with separate `input`, dependency-cache mount, `work`, and `output` directories.
- Mount inputs read-only inside the worker; make only `work` and `output` writable. Never mount the repository, user package store, project files, SSH configuration, cloud credentials, or host package-manager configuration.
- Run as an unprivileged identity with bounded CPU, memory, process count, file descriptors, output bytes, and wall time. Terminate the entire process group on cancellation or timeout.
- Remove the workspace after success/failure according to a short diagnostic-retention policy; retain only sanitized logs and content-addressed outputs needed by an active proposal.

#### 4. Controlled dependency resolver

- Parse static Python and JS imports, then merge them with explicit versioned declarations. Never overwrite explicit constraints with the current scanner’s `"*"` default without surfacing the change.
- Resolve package-to-package dependencies through Curio’s existing resolver.
- Resolve JS packages in a dedicated fetch phase against an operator-approved registry/allowlist, with registry egress only, pinned versions, integrity hashes, license metadata, size limits, and lockfile generation. The compile phase then runs without network access from the verified cache.
- Resolve Python requirements and conflicts for review, but do not install them into the host or execute package code during build. Actual Python installation remains part of the reviewed package installer on Apply.
- Generate a dependency report/SBOM covering direct and transitive JS dependencies plus declared Python/package dependencies. Vulnerability/license policy may warn or block according to deployment policy; results must be visible before Apply.

#### 5. Pinned compiler toolchain

- Use a deployment-pinned builder image/toolchain version rather than the repository’s ambient Node installation. Record that version in the build provenance.
- Compile JS/TS/TSX entry points into one deterministic `scripts/behaviors.js` (plus approved static chunks only if the runtime loader is extended to support them).
- Externalize only the versioned Curio package runtime API, React, ReactDOM when exposed, and ReactFlow. Reject attempts to replace or bundle those host singletons.
- Bundle all other approved JS dependencies into the package artifact. Do not rely on `manifest.dependencies.js` to make modules magically available in the browser.
- Fix locale, timestamps, source ordering, minifier settings, and source-map policy so identical inputs and toolchain versions produce byte-identical output.

#### 6. Static validation and policy gate

- Validate the manifest through the production `PackageManifest` parser and `node-package.v4` schema; validate behavior entries, registered behavior keys, template references, ports, editors/engines, asset references, and allowed archive paths.
- Type-check behavior source against a pinned, minimal `@curio/package-runtime` declaration surface. Agent-generated code must not import arbitrary Curio frontend internals.
- Reject forbidden constructs/imports defined by policy, unresolved modules, unexpected network/build plugins, writes outside the workspace, oversized bundles, duplicate registrations, and missing behavior registrations.
- Scan the finished archive, not only sources: safe paths, no symlinks/path traversal, permitted file types, decompressed-size limits, dependency/bundle policy, manifest-to-file correspondence, and complete integrity coverage.
- Static checks reduce risk but do not establish runtime trust; the browser behavior still requires the existing safe runtime boundary and the future backend path requires Follow-up A.

#### 7. Sandboxed visual preview runner

- Load the built behavior in a disposable preview document using the same versioned runtime API as Curio, synthetic bounded input data, and a restrictive CSP/sandbox configuration.
- Disable credentials, persistent storage, project APIs, top-level navigation, popups, and network by default. Mock explicitly declared endpoints for preview rather than calling live services.
- Exercise empty, loading, success, malformed-input, and error states; capture console/runtime errors, registration results, rendered dimensions, and screenshots.
- A preview failure blocks Apply for a custom behavior. The review card uses the captured artifact rather than executing freshly generated code inside the agent chat UI.

#### 8. Deterministic packager and provenance report

- Assemble manifest, preserved/generated sources, compiled behavior, approved assets, README/license, dependency lock/report, and any package-runtime compatibility metadata through one package-domain packager.
- Generate `integrity.json` over every distributable file using stable ordering and timestamps, then validate the produced archive through the same installer path used on Apply.
- Emit a signed or server-authenticated `PackageBuildResult`: input digest, artifact digest, base digest, builder/toolchain version, resolved dependencies and integrities, SBOM, policy findings, test/preview results, file/template diff, archive size, and sanitized logs.
- Store the archive in a private content-addressed staging area. The proposal references the artifact digest; it must not carry mutable filesystem paths or trust model-supplied hashes.

#### 9. Job controller and observable lifecycle

- Expose create/status/event/cancel operations behind the packages domain. Agent services translate these into build-progress content but do not control worker processes directly.
- Use stable phases: `queued`, `resolving`, `compiling`, `validating`, `previewing`, `packaging`, `ready`, plus `failed`, `cancelled`, and `expired`.
- Make retries idempotent by input digest, cap concurrency per user/deployment, and apply backpressure rather than spawning unbounded builds.
- Produce structured, redacted diagnostics with a correlation/build ID. Never return host paths, environment variables, tokens, or raw package-manager configuration to the model or UI.

#### 10. Separate reviewed promotion/install coordinator

- The builder is read-only with respect to installed packages and projects. It can only stage an artifact and report results.
- Apply authenticates the actor, verifies proposal and artifact digests, re-checks extension base/package conflicts and policy, then promotes the exact reviewed archive through the existing atomic installer.
- Update the project lockfile only after package installation succeeds. Refresh package behavior/template registries before creating requested graph nodes.
- Record an operation journal sufficient to recover from a client disconnect and to distinguish `built`, `installed`, `registry-ready`, and `nodes-created`. Repeated Apply resumes or returns the prior result rather than reinstalling blindly.
- Keep the previous editable package artifact until registry activation and node insertion complete, enabling compensation/rollback if post-install activation fails. The UI must report whether rollback completed or manual refresh is required.

These components form the minimum complete service for frontend/sandbox-backed node packages. Follow-up A adds executable generated backend artifacts to the package model; Follow-up B adds their safe activation and restart semantics. Neither follow-up should weaken the build service’s immutable artifact, review, provenance, or promotion boundaries.

### Custom looks and behavior

Represent customization through the mechanism Curio already documents:

- Template manifest controls label, category, icon, ports, editor, engine, and container metadata.
- Package `behaviorScript` registers a custom behavior hook that returns purpose-specific content, handles, controls, loading/progress/error/output UI, and styling.
- Python or JS starter code provides node execution logic where the standard execution behavior is appropriate.
- Package assets are referenced from allowed archive directories and served through the authenticated package-file route.

“Totally customizable” should mean customizable within an explicit package runtime API—not arbitrary access to Curio internals or the DOM. Version that API and expose only supported globals/components/tokens to behavior bundles.

#### Node Researcher DOD profile

The first proof should intentionally exercise the smallest custom-behavior path:

- One template, for example `node-researcher-note`, with `editor: none`, schema-required `engine: javascript`, `hasCode: false`, `hasGrammar: false`, `hasWidgets: false`, and no executable node source or Python dependencies. Here `engine` satisfies the current manifest contract; the custom behavior is presentation-only and exposes no Run control.
- One package behavior key and one small TSX/JS entry compiled to `scripts/behaviors.js`.
- Node instance content is the source of truth for the fixed note body. Node/Dataflow Builder copies the relevant agent reply or web-search-results summary into that content when it proposes the node; the node does not repeat the search.
- The behavior renders a roughly square, post-it-like surface with a restrained note color, compact header/title, padded scroll-safe body, readable typography, and no generic code editor or Run control.
- Color is an instance property, not a template identity. The package supplies a default yellow, while Node/Dataflow Builder may set `appearance.backgroundColor` when creating each note. Two notes of different colors still use the same canonical template ID and behavior bundle.
- The canonical persisted shape is `node.metadata.appearance.backgroundColor`; agent proposal/apply and live-canvas payloads expose the typed equivalent `appearance: { backgroundColor }`. Load/save bridges must round-trip it into live `node.data.appearance` rather than dropping it on the next canvas save.
- Accept named palette choices (`yellow`, `pink`, `blue`, `green`, `orange`, `lavender`) mapped centrally to design-token hex values, plus an optional normalized six-digit custom hex color. Reject arbitrary CSS strings, alpha, gradients, URLs, functions, and malformed values. Missing/invalid legacy values fall back to the template’s default yellow.
- The behavior derives foreground, muted text, border, focus-ring, and link colors from the normalized background to maintain WCAG AA contrast. The model never supplies raw text/border CSS.
- The post-it exposes an accessible color control for direct user changes (keyboard-operable labeled swatches plus validated hex input). A manual color change updates `node.data.appearance` and persists through the ordinary canvas-save path; it does not rebuild or replace the package.
- Plain text is always supported. Markdown mode uses a centralized safe Markdown primitive from the versioned Curio package runtime when available; otherwise the package bundles an approved parser/sanitizer. Raw HTML and executable links/scripts are never rendered.
- The body handles long results with wrapping and a bounded scroll/expand treatment instead of expanding the entire canvas or clipping content. Missing content renders a quiet empty-note state.
- Input and output ports are empty for the DOD unless the product separately requires note chaining. Adding ornamental or nonfunctional ports is explicitly avoided.
- Updating the node’s content through the existing reviewed node-content path updates the displayed note without rebuilding the package.

This profile still proves the essential new capability—agent generation, compilation, installation, registration, and rendering of a package-owned custom look—without coupling the DOD to Python execution, research orchestration, custom backend services, or the follow-up activation lifecycle.

## 4. Data and State Handling

- The installed package store and current project’s `spec.dataflow.packages` remain the source of truth. Agent transcripts/proposals are not a second package registry.
- For the Node Researcher DOD, the installed template defines presentation while the created node instance’s persisted content holds the fixed agent-result text. The transcript is copied at proposal time; the rendered node does not maintain a live reference to an agent turn.
- The post-it color belongs to the node instance at `metadata.appearance.backgroundColor`, separate from Markdown content. Derived palette values and contrast colors are computed at render time and are never duplicated into persisted state.
- The package draft is immutable once proposed and carries a SHA-256 digest. Extension proposals also pin the installed target package’s full integrity/manifest digest.
- Derived dependency lists come from imports plus explicit reviewed overrides. Preserve version constraints supplied by the draft; the current factory’s `"*"` import inference is a useful default but insufficient for reproducible agent-authored packages.
- Build state progresses through `drafting → validating → building → preview-ready → review-required → applying → installed → nodes-created`, with terminal `failed`, `dismissed`, or `stale` states.
- This proposal lifecycle wraps the build-service job phases from §3 rather than duplicating them: proposal-level `validating` is draft/schema/policy validation before a job is submitted; the proposal’s `building` state spans the job phases `queued → resolving → compiling → validating → previewing → packaging` (job-level `validating` checks the compiled artifact, not the draft); job `ready` moves the proposal to `preview-ready`, and job `failed`/`cancelled`/`expired` map to the proposal’s terminal `failed` or `stale` states.
- Slow builds stream progress without clearing the plan or canvas. Repeated Apply is idempotent by proposal ID.
- Extension Apply re-reads the target package and refuses with `409 stale` if its pinned digest changed. It never overwrites a newer package silently.
- Preserve untouched templates, sources, scripts, assets, README, and license in extension mode. The existing `preserve_unedited_sources` logic is evidence for this requirement but must be generalized beyond starter files.
- Registry refresh happens only after a successful install/replace. Node creation waits for behavior/template registration and uses canonical IDs from the installed manifest.
- If registry refresh fails after install, report a recoverable “installed; refresh required” state and do not create unresolved canvas nodes until refresh succeeds.

## 5. UI and UX Requirements

- Dataflow Builder plan cards distinguish “Reuse node template,” “Create custom node kind,” and “Create/extend package.”
- A package-build progress card shows the active phase and concise validation/build messages without replacing the plan.
- The review card shows:
  - new package versus extension target;
  - templates added/changed/removed (removal excluded from v1 unless explicitly requested);
  - custom behavior and visual preview;
  - Python, JS, and package dependencies with versions;
  - permissions and build warnings;
  - files changed and whether an installed package will be replaced;
  - node instances to add after installation.
- Apply opens or incorporates the established install-permissions review semantics. Extension mode must call out replacement risk more prominently than a fresh install.
- The Node Researcher DOD demonstrates a custom behavior bundle with the reference’s simple visual intent: a roughly square post-it note, a small researcher title/icon treatment, configurable per-node color, and fixed agent-produced web-search text rendered readably as safe text/Markdown. The creation review shows the selected color as a labeled swatch, and the node offers an accessible palette/custom-hex control for later direct edits. It has no query controls, Run action, research progress state, Python execution, or required ports. Missing text and long/Markdown-rich text must remain visually stable.
- The canvas must not show an unresolved generic fallback during successful apply. Installation, registry refresh, and node insertion should feel like one operation with progress, not a page reload.
- All review controls are keyboard accessible; focus enters the review dialog, returns to the originating card, and status changes are announced. Dependency and conflict meaning must not rely on color alone.

## 6. Edge Cases

- A suitable installed or catalog template exists: reuse or recommend it; do not author a duplicate package.
- The requested extension targets `readOnly: true`: refuse in-place extension and offer a new package/fork with explicit lineage.
- The package coordinate exists but differs from the proposal base digest: mark stale and require regeneration.
- Two package builds target the same coordinate: serialize apply and allow only the proposal whose base digest still matches.
- Generated behavior has syntax/type/bundle errors: no proposal is applyable; preserve diagnostics for revision.
- A JS dependency is incompatible with the builder or attempts to replace an allowlisted external such as React: refuse or require explicit safe resolution; never bundle a second React copy.
- A Python dependency conflicts with installed project packages or lacks a compatible wheel: surface the resolver/install failure; do not update the lockfile or graph.
- Imports are dynamic or cannot be detected: require explicit dependency declaration and mark it for review.
- Malformed ports, duplicate template IDs/behavior keys, unsupported editor/engine combinations, missing assets, oversized bundles, or integrity mismatch: fail validation before review/apply.
- Custom behavior bundle fails at runtime: register the existing generic fallback and show a visible package-behavior error; preserve the node’s data and allow retry after package repair.
- Dependency-registry fetch is unavailable or a dependency lacks integrity metadata: fail during the resolver phase with a retryable diagnostic; never fall back to an unpinned ambient dependency.
- A build times out, exceeds memory/output limits, is cancelled, or the worker crashes: terminate its process group, preserve only redacted diagnostics, clean its workspace, and leave installed/package/project state unchanged.
- Preview code attempts network, storage, navigation, credential, or host-DOM access: the preview sandbox blocks it and the policy result prevents Apply when the requested access is outside the package runtime contract.
- The staged artifact expires before review: mark the proposal expired and rebuild from the immutable request; never rebuild silently during Apply because the reviewed artifact digest would change.
- Node Researcher content contains malformed Markdown, raw HTML, script URLs, oversized headings/tables, or very long unbroken text: sanitize unsafe content, wrap/scroll within the post-it bounds, and preserve readable plain-text fallback.
- A requested color is missing, unknown, malformed, shorthand hex, transparent, or an arbitrary CSS expression: normalize known palette names/six-digit hex only, otherwise refuse the agent proposal with a correction message; legacy stored invalid values render with default yellow.
- A custom color cannot produce accessible text/link/focus contrast even after foreground selection: reject it with an accessible-color explanation rather than silently rendering unreadable text.
- Multiple post-its share one template but use different colors: instance colors remain independent through drag, save/reload, package refresh/upgrade, content edit, and shared-dataflow serialization.
- Reopened plan/drawer: restore build/proposal state from the session; do not restart compilation automatically.
- User removes or edits planned nodes while the build runs: package proposal remains valid, but graph insertion is revalidated and requires an updated preview when targets changed.
- Backend-only capability is requested: first slice must propose a supported frontend/existing-sandbox design or clearly report that generated backend execution awaits the Curio package backend sandbox (Follow-up A) and activation/restart lifecycle (Follow-up B).

## 7. Testing Strategy

Required unit tests:

- Capability/manifest generation for Package Builder and delegation allowlists.
- Draft schema validation, source/asset path validation, behavior-key uniqueness, dependency extraction/override merging, deterministic build output, and base-digest calculation.
- Node-appearance normalization maps named colors centrally, accepts normalized six-digit hex, rejects CSS injection/alpha/malformed values, computes accessible foreground/link/focus colors, and preserves the default for omitted/legacy-invalid values.
- Extension merge preserves every untouched package file and rejects read-only or stale targets.
- Bundle policy externalizes Curio runtime libraries and bundles permitted JS dependencies without a second React copy.
- Workspace isolation, resource/time/output limits, cancellation cleanup, path traversal/symlink rejection, redacted diagnostics, artifact expiry, and content-addressed retry behavior.
- Dependency resolution produces pinned JS lock/integrity data and an SBOM, preserves explicit constraints, blocks disallowed registries/packages, and never mutates the host environment.
- Build provenance and archive digest cover the exact compiler/toolchain, normalized input, compiled output, dependency report, preview result, and final integrity manifest.

Required component tests:

- Build progress, package diff, dependency/permission review, custom visual preview, selected-color swatch, stale/error states, keyboard focus, and accessible status text.
- Registry refresh occurs before node insertion and does not flash the generic fallback on success.
- Preview harness blocks credential/storage/network/navigation access, renders the Node Researcher empty, short-text, long-text, and Markdown-rich fixtures, and reports runtime/registration failures without executing generated code in agent chat.
- Post-it color control supports mouse and keyboard selection, announces color names/validation errors, maintains visible focus and AA text/link contrast, and persists named/custom colors without rebuilding the package.

Required integration tests:

- Node Builder reuse-first path remains unchanged.
- `node.template.create` delegates to Package Builder and returns a canonical template ID.
- `node.create`, Package Builder’s requested-node output, the saved spec, apply response, live-canvas bridge, load path, and canvas serializer round-trip `appearance.backgroundColor` without affecting callers that omit it.
- Dataflow Builder delegates one multi-template package step rather than issuing destructive repeated replacements.
- New-package Apply builds, installs, locks, refreshes, and inserts requested nodes.
- Extension Apply preserves old templates/sources/assets and adds the new kind atomically.
- Python dependency install failure, JS build failure, package conflict, stale digest, and registry refresh failure leave graph/package state consistent.
- Injection-resistance tests prove model text cannot trigger build/install/apply and generated packages cannot access unexposed host globals through the supported runtime API.
- A staged artifact cannot be substituted between review and Apply; apply installs only the reviewed digest, is idempotent after disconnect/retry, and restores the prior editable package when activation compensation is required.
- Build workers cannot read repository, project, package-store, environment-secret, or user credential fixtures and cannot reach the network during compilation/preview.

Required DOD regression:

- A recorded end-to-end Node Researcher scenario starts from a Dataflow Builder request containing agent-produced web-search results and a requested post-it color, produces a reviewed custom package/node-kind proposal, installs it, and creates a post-it-style node whose persisted fixed content and per-instance color render through the package JS behavior. Screenshot assertions cover the default palette, at least two distinct instance colors, one valid custom hex color, empty/representative-Markdown/long-result content, accessible contrast, save/reload, direct recolor, and updated-content states against approved baselines derived from the supplied reference. The package declares no Python dependency and the test does not invoke the Python sandbox or a generated backend service.

## 8. Acceptance Criteria

1. `agent.package-recommendation` remains catalog-grounded and cannot author, extend, build, or publish packages.
2. A new Package Builder agent owns `package.build`, `package.extend`, and the package artifact lifecycle.
3. Node Builder reuses installed templates first; when a new kind is justified, its `node.template.create` path delegates to Package Builder rather than using a parallel template-only implementation.
4. Dataflow Builder can delegate a coherent new or extended multi-template package in one plan step and can still delegate individual node instances to Node Builder.
5. A package proposal can include valid templates, Python sources/dependencies, JavaScript behavior source/dependencies, a compiled `behaviorScript`, allowed assets, README, and integrity hashes.
6. JavaScript dependencies required by custom UI are bundled at build time; React/ReactFlow and other approved Curio runtime APIs are externalized and shared.
7. New and extension proposals are reviewed before mutation and display diffs, dependencies, permissions, conflicts, visual preview, and planned node insertions.
8. Apply is atomic from the user’s perspective: validate/re-check, install or replace, update project lockfile, refresh registry, then add nodes. Failures do not leave unresolved nodes or partially replaced packages.
9. Read-only packages cannot be overwritten; extension of an editable package preserves untouched content and refuses stale bases.
10. Node Researcher renders as a package-owned post-it-style square containing fixed agent-produced web-search text through a safe plain-text/Markdown body. Each instance accepts a named palette color or valid six-digit custom hex, persists it independently, derives accessible foreground/link/focus colors, exposes an accessible direct-edit color control, and falls back to yellow for absent legacy values. It has no generic editor, Run control, Python dependency, Python-sandbox call, generated backend call, or required ports; empty, long, unsafe, recolored, saved/reloaded, and updated content render correctly.
11. The isolated builder uses immutable typed inputs, ephemeral restricted workspaces, controlled dependency resolution, a pinned compiler, static policy checks, sandboxed visual preview, deterministic packaging, complete integrity/provenance output, private content-addressed staging, and cancellable observable jobs.
12. The builder has no authority to mutate installed packages, project lockfiles, or graph state; only the authenticated reviewed promotion coordinator can install the exact staged artifact digest.
13. JS dependencies are pinned and integrity-checked during controlled resolution, compiled without network access, and bundled unless they are explicitly allowlisted Curio runtime externals. Python dependencies are resolved for review but are not executed or installed during build.
14. Build and preview workers receive no secrets or project/user-store mounts, enforce resource/output/time limits, redact diagnostics, and clean expired workspaces/artifacts.
15. No agent-generated backend blueprint is dynamically loaded in the first slice. Unsupported backend requirements explicitly identify the Curio backend sandbox as Follow-up A and activation/restart lifecycle as Follow-up B.
16. All required unit, component, integration, security, isolation, deterministic-build, and DOD regression tests pass.

## 9. Recommended Commit Breakdown

- Commit 1: Add Package Builder capability contracts, roster/prompt, delegation wiring, and tests.
- Commit 2: Add typed package build request/result models, content-addressed staging, extension snapshots, generalized preservation/diff logic, and tests.
- Commit 3: Add restricted ephemeral worker/workspace controller, lifecycle events, cancellation/cleanup, resource limits, and isolation tests.
- Commit 4: Add controlled JS/Python/package dependency resolution, lock/integrity/SBOM reporting, policy gates, and tests.
- Commit 5: Add pinned deterministic behavior compiler, Curio runtime externals contract, final archive validation/provenance, and reproducibility/security tests.
- Commit 6: Add sandboxed visual preview runner and empty/loading/success/error screenshot/runtime validation.
- Commit 7: Add reviewed package proposal and promotion coordinator with exact-digest install/replace, rollback journal, project lockfile update, and stale protection.
- Commit 8: Add frontend progress/review/diff/preview UI, typed node-appearance round-trip, accessible post-it color control/contrast derivation, and registry-before-canvas synchronization.
- Commit 9: Implement the Node Researcher reference package through the new capability and add end-to-end visual/regression coverage.
- Commit 10: Update `docs/EXTENDING.md`, capability documentation, decisions, build ledger, and record Follow-up A (Curio backend sandbox), Follow-up B (activation/restart lifecycle), and Follow-up C (`node.appearance.write` agent recolor).

## 10. Engineering Quality Checklist

- [ ] Package authoring logic lives in the packages domain, not duplicated in agent services.
- [ ] Package Recommendation remains separate from Package Builder.
- [ ] Node Builder keeps reuse-first behavior and one compatibility path for `node.template.create`.
- [ ] Types and schemas cover new/create versus extend and every artifact class explicitly.
- [ ] Builds are isolated, deterministic, bounded, and produce reviewable reports.
- [ ] Workers receive no secrets or host/project/package-store write access; dependency fetch and networkless compile/preview phases are separated.
- [ ] JS dependencies are locked/integrity-checked and SBOM/provenance data describes the exact reviewed artifact.
- [ ] Generated behavior is type-checked against the versioned Curio package runtime and rendered in a restrictive disposable preview.
- [ ] Dependency inference does not erase explicit reproducible constraints without review.
- [ ] Extension merges preserve untouched files and use digest-based stale protection.
- [ ] Build staging and reviewed promotion are separate authorities; install/replace, lockfile, registry refresh, rollback, and graph insertion have predictable recovery semantics.
- [ ] Custom behaviors use a versioned, minimal Curio runtime API and share host React instances.
- [ ] Loading, empty, error, success, and fallback behavior are accessible and visually stable.
- [ ] Post-it colors are instance-scoped, validated centrally, contrast-safe, review-visible, keyboard-editable, and preserved across apply/save/reload without package rebuilds.
- [ ] Tests cover core behavior, conflicts, races, malformed output, security boundaries, and the Node Researcher DOD.
- [ ] Documentation follows `docs/EXTENDING.md` and is updated when the supported package runtime API changes.
- [ ] Generated backend execution and activation are not smuggled into v1; Follow-up A/B boundaries and dependencies are documented.

## Evidence-backed decision summary

- **Why not option 1 alone (expand Package Recommendation):** its implemented roster description and prompt explicitly prohibit authoring, while dev/16/dev/84 define it as catalog discovery, dependency identification, and reviewed installation. Expanding it would mix trusted catalog facts with generated supply-chain artifacts and invalidate its grounding guarantees.
- **Why option 2 is needed (new Package Builder):** `docs/EXTENDING.md` defines a new custom-looking node as a package-level artifact involving templates, behavior hooks/bundles, optional assets and dependencies. This is a coherent specialist boundary and is larger than node-instance construction.
- **How option 3 should continue (Node Builder strategy):** preserve `node.template.create` as the reuse-first fallback at the Node Builder UX/capability boundary, but implement it by delegating the `package.create-or-extend` intent (backed by `node.kind.author`) to Package Builder. Node Builder then instantiates the returned canonical template.
- **Where Dataflow Builder fits:** it delegates ordinary node steps to Node Builder and delegates directly to Package Builder only for package-scale work (multiple related templates or an explicit package extension). This matches the current composite orchestration model and avoids repeated whole-package replacement.
