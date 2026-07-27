# Implementation Memo: Standardize Agent Package IDs on the `agent.` Prefix

## 1. Problem Statement

The prompt-backed agent examples currently use `curio.` package IDs, which does not clearly distinguish agent artifacts from existing Curio node packages and other product namespaces. Agent package identities must begin with `agent.` consistently across manifests, artifact directories, delegates, commands, requirements, examples, and traceability.

## 2. Scope

Included: replace only the fourteen planned prompt-agent ID prefixes and matching artifact-directory examples from `curio.` to `agent.`. Out of scope: existing node package IDs such as `curio.builtin`, dataset IDs, application module names, product branding, and unrelated source paths.

## 3. Recommended Implementation Approach

Apply a direct namespace substitution while preserving every agent’s stable suffix. For example, `curio.node-explainer` becomes `agent.node-explainer`, and `agents/curio.node-explainer@1/` becomes `agents/agent.node-explainer@1/`.

## 4. Data and State Handling

The prefix is part of the immutable agent identity. No alias is needed before implementation because these IDs are planning-only. Once released, future renames require an explicit manifest alias/migration strategy rather than silent substitution.

## 5. UI and UX Requirements

Palette references and technical metadata display `agent.<id>@<version>`, consistent with the approved product concept. Human-readable agent names remain unchanged.

## 6. Edge Cases

- Do not rename `curio.builtin` or other node packages.
- Do not alter the `utk_curio` Python/frontend directory names.
- Update delegated-agent IDs and pseudocode commands, not only roster tables.
- Ensure no mixed `curio.`/`agent.` identities remain for the fourteen agents.

## 7. Testing Strategy

Search all planning and related architecture documents for the old fourteen IDs and old `agents/curio.` artifact examples. Verify all new IDs begin with `agent.` and unrelated Curio namespaces remain intact.

## 8. Acceptance Criteria

- Every planned prompt-backed package ID begins with `agent.`.
- All artifact path, command, delegate, blocker, and requirement examples use the new IDs.
- No unrelated package or code namespace is renamed.

## 9. Recommended Commit Breakdown

One focused documentation commit updating the namespace decision and every affected reference atomically.

## 10. Engineering Quality Checklist

- [ ] Fourteen agent IDs use `agent.` consistently.
- [ ] Artifact directories use the matching manifest ID.
- [ ] Delegates and runtime commands use the matching ID.
- [ ] Old prompt-agent IDs are absent.
- [ ] Existing node/dataset namespaces are unchanged.

