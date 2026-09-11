/**
 * The persisted comment shape (#237).
 *
 * Comments used to live in `NodeContainer`'s local `useState` and were written
 * nowhere, so they disappeared on save and on any remount. These cases pin the
 * two decisions that make the persisted form safe to put in a spec: no avatar
 * (it can be a multi-megabyte data URL) and no `canDelete` (it is a per-viewer
 * permission, so persisting one viewer's answer would mislead every other).
 */
// The shared `src/jestMocks/uuid.ts` returns one constant, which is fine for
// tests that just need *a* uuid but cannot show that ids are distinct. Count
// here instead, because "every comment gets its own id" is the actual claim.
jest.mock("uuid", () => {
  let calls = 0;
  return {
    v4: () => `00000000-0000-4000-8000-${String(++calls).padStart(12, "0")}`,
  };
});

import {
  commentsFromMetadata,
  commentsToMetadata,
  fromPersisted,
  newComment,
  toPersisted,
} from "../../utils/nodeComments";

const ADA = { username: "ada", name: "Ada Lovelace", photo: "data:image/png;base64,AAAA" };
const GRACE = { username: "grace", name: "Grace Hopper", photo: null };

describe("nodeComments", () => {
  it("gives every comment a unique id", () => {
    // The original writer used `comments.length + 1`. Add three, delete the
    // middle one, add another -> two comments share id 3, and delete/resolve
    // then act on whichever the array happened to hold first.
    const ids = [
      newComment("a", ADA).id,
      newComment("b", ADA).id,
      newComment("c", ADA).id,
    ];
    expect(new Set(ids).size).toBe(3);
    for (const id of ids) expect(typeof id).toBe("string");
  });

  it("round-trips text, author and resolved state", () => {
    const live = { ...newComment("needs a second look", ADA), resolved: true };
    const restored = fromPersisted(toPersisted(live), ADA);

    expect(restored).not.toBeNull();
    expect(restored!.id).toBe(live.id);
    expect(restored!.text).toBe("needs a second look");
    expect(restored!.author).toBe("ada");
    expect(restored!.user.name).toBe("Ada Lovelace");
    expect(restored!.createdAt).toBe(live.createdAt);
    expect(restored!.resolved).toBe(true);
  });

  it("never persists the avatar", () => {
    const persisted = toPersisted(newComment("hi", ADA));
    // ADA's photo is a data URL. One copy per comment, in a JSON file that is
    // rewritten on every save, is exactly what this keeps out of the spec.
    expect(JSON.stringify(persisted)).not.toContain("data:image");
    expect(Object.keys(persisted).sort()).toEqual(
      ["author", "authorName", "createdAt", "id", "resolved", "text"].sort(),
    );
  });

  it("never persists canDelete, and derives it per viewer", () => {
    const persisted = toPersisted(newComment("mine", ADA));
    expect(persisted).not.toHaveProperty("canDelete");

    // The author may delete it; another signed-in user may not; and neither
    // may an anonymous viewer following a share link.
    expect(fromPersisted(persisted, ADA)!.canDelete).toBe(true);
    expect(fromPersisted(persisted, GRACE)!.canDelete).toBe(false);
    expect(fromPersisted(persisted, null)!.canDelete).toBe(false);
  });

  it("shows an avatar only for the viewer's own comments", () => {
    // The avatar is not in the spec, so the only one resolvable here is the
    // viewer's own. Everyone else renders without one rather than with a
    // wrong one.
    const persisted = toPersisted(newComment("mine", ADA));
    expect(fromPersisted(persisted, ADA)!.user.photo).toBe(ADA.photo);
    expect(fromPersisted(persisted, GRACE)!.user.photo).toBeNull();
  });

  it("tolerates specs that predate the newer fields", () => {
    // Specs are hand-editable and this field is new; a reader that threw would
    // fail the whole project load over one comment.
    const restored = fromPersisted({ id: "c1", text: "old" }, ADA);
    expect(restored).not.toBeNull();
    expect(restored!.author).toBe("");
    expect(restored!.user.name).toBe("Unknown");
    expect(restored!.createdAt).toBe("");
    expect(restored!.resolved).toBe(false);
    expect(restored!.canDelete).toBe(false);
  });

  it("drops malformed entries instead of failing the load", () => {
    const restored = commentsFromMetadata(
      [{ id: "c1", text: "keep" }, null, "nope", { id: "c2" }, 7],
      ADA,
    );
    expect(restored.map((c) => c.text)).toEqual(["keep"]);
  });

  it("reads a missing or non-array section as no comments", () => {
    expect(commentsFromMetadata(undefined, ADA)).toEqual([]);
    expect(commentsFromMetadata(null, ADA)).toEqual([]);
    expect(commentsFromMetadata({ nope: true }, ADA)).toEqual([]);
    expect(commentsToMetadata([])).toEqual([]);
  });
});
