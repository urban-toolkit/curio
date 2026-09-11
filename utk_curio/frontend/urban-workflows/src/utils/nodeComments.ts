/**
 * The persisted shape of a node's comments, and the mappers to and from the
 * live `IComment` the UI renders.
 *
 * Comments used to live only in `NodeContainer`'s `useState`, so they vanished
 * on save and on every remount - reopening a saved project lost the lot (#237).
 * They now round-trip through `metadata.comments`, alongside
 * `metadata.appearance` and `metadata.keywords`.
 *
 * Two things are deliberately NOT persisted:
 *
 * - **The avatar.** `IComment.user.photo` carries `user.profile_image`, which
 *   may be a full data URL. Writing one into `spec.trill.json` per comment
 *   would bloat the spec by megabytes for something the client can resolve
 *   itself. The author is stored by name; the avatar is a render-time lookup.
 * - **`canDelete`.** It is a permission, not a fact about the comment, and it
 *   depends on who is looking. Deriving it on read means a shared dataflow
 *   cannot hand a visitor a comment that claims they may delete it.
 *
 * `author` is the username (stable identity, what the permission compares);
 * `authorName` is the display name.
 */
import { v4 as uuid } from "uuid";

import type { IComment } from "../components/comments/CommentsList";

/** One comment as it is written to `node.metadata.comments`. */
export interface PersistedComment {
  id: string;
  text: string;
  author: string;
  authorName: string;
  createdAt: string;
  resolved: boolean;
}

/** The author identity a live comment is built against. */
export interface CommentAuthor {
  username: string;
  name: string;
  photo: string | null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Build a fresh live comment. Ids are uuids: the old `comments.length + 1`
 *  collided as soon as anything was deleted, so two comments could share an id
 *  and delete/resolve would hit whichever came first. */
export function newComment(text: string, author: CommentAuthor): IComment {
  return {
    id: uuid(),
    text,
    author: author.username,
    createdAt: new Date().toISOString(),
    user: { name: author.name, photo: author.photo },
    canDelete: true,
    resolved: false,
  };
}

export function toPersisted(comment: IComment): PersistedComment {
  return {
    id: comment.id,
    text: comment.text,
    author: comment.author,
    authorName: comment.user.name,
    createdAt: comment.createdAt,
    resolved: !!comment.resolved,
  };
}

/**
 * Rehydrate one persisted comment. Tolerant by design: a spec is hand-editable
 * and older ones predate several of these fields, so a malformed entry loses
 * only itself (`null`) and never fails the load.
 */
export function fromPersisted(
  raw: unknown,
  viewer: CommentAuthor | null,
): IComment | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (!isNonEmptyString(value.text)) return null;

  const author = typeof value.author === "string" ? value.author : "";
  const authorName = isNonEmptyString(value.authorName)
    ? value.authorName
    : author || "Unknown";

  return {
    id: isNonEmptyString(value.id) ? value.id : uuid(),
    text: value.text,
    author,
    createdAt: isNonEmptyString(value.createdAt) ? value.createdAt : "",
    // The avatar is never persisted; only the viewer's own is knowable here.
    user: {
      name: authorName,
      photo: viewer && author && viewer.username === author ? viewer.photo : null,
    },
    canDelete: !!viewer && !!author && viewer.username === author,
    resolved: value.resolved === true,
  };
}

/** Whole-list read, dropping entries that could not be rehydrated. */
export function commentsFromMetadata(
  raw: unknown,
  viewer: CommentAuthor | null,
): IComment[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((entry) => fromPersisted(entry, viewer))
    .filter((c): c is IComment => c !== null);
}

/** Whole-list write. */
export function commentsToMetadata(comments: IComment[]): PersistedComment[] {
  return (comments || []).map(toPersisted);
}
