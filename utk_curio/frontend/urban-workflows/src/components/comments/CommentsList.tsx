import React, { useState } from "react";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowRight,
  faSquareCheck,
  faTrash,
} from "@fortawesome/free-solid-svg-icons";

import { newComment } from "../../utils/nodeComments";
import { useUserContext } from "../../providers/UserProvider";
import { useToastContext } from "../../providers/ToastProvider";

export interface IComment {
  /** A uuid. Was `comments.length + 1`, which collided after any delete. */
  id: string;
  text: string;
  /** Username of the author - the stable identity `canDelete` compares
   *  against, and what is persisted. `user.name` is the display name. */
  author: string;
  /** ISO timestamp. Empty for a comment restored from a spec that predates it. */
  createdAt: string;
  user: {
    name: string;
    photo: string | null;
  };
  /** Derived per viewer on read, never persisted (see utils/nodeComments). */
  canDelete: boolean;
  resolved: boolean;
}

export const CommentsList = ({
  comments,
  addComment,
  deleteComment,
  toggleResolveComment,
}: {
  comments: IComment[];
  addComment: (comment: IComment) => void;
  deleteComment: (commentId: string) => void;
  toggleResolveComment: (commentId: string) => void;
}) => {
  const { user } = useUserContext();
  const { showToast } = useToastContext();
  const [newCommentText, setNewCommentText] = useState("");

  const onAddComment = () => {
    if (newCommentText.trim() === "") { showToast("Please write a comment before submitting.", "warning"); return; }
    if (!user) { showToast("Please sign in to post a comment.", "warning"); return; }

    addComment(
      newComment(newCommentText, {
        username: user.username,
        name: user.name,
        photo: user.profile_image,
      }),
    );

    setNewCommentText("");
  };

  return (
    <div style={containerStyles}>
      {comments.map((comment) => (
        <div
          key={comment.id}
          data-curio-comment="true"
          data-curio-comment-resolved={comment.resolved ? "true" : "false"}
          style={{
            ...commentStyles,
            ...(comment.resolved ? { borderColor: "green" } : {}),
          }}
        >
          <div
            style={{
              width: "100%",
              padding: "5px",
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-start",
              borderBottom: "1px solid #ccc",
              ...(comment.resolved ? { borderColor: "green" } : {}),
            }}
          >
            <img
              src={comment.user.photo ?? undefined}
              alt={comment.user.name}
              style={imageStyles}
            />
            <strong style={{ fontSize: "10px", marginLeft: "5px" }}>
              {comment.user.name}
            </strong>
          </div>

          <p
            style={{
              width: "100%",
              padding: "5px",
              fontSize: "10px",
              wordBreak: "break-word",
            }}
          >
            {comment.text}
          </p>

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "0 6px 3px 6px",
              width: "100%",
            }}
          >
            <div
              style={{
                display: "flex",
                fontSize: "0.5em",
                alignItems: "center",
                width: "100%",
                cursor: "pointer",
                ...(comment.resolved ? { color: "green" } : {}),
              }}
              data-curio-comment-resolve="true"
              onClick={() => toggleResolveComment(comment.id)}
            >
              <FontAwesomeIcon
                icon={faSquareCheck}
                style={{
                  ...iconStyle,
                  fontSize: "10px",
                  ...(comment.resolved ? { color: "green" } : {}),
                }}
              />
              <div style={{ marginLeft: "2px", fontSize: "8px" }}>
                {comment.resolved ? "Resolved" : "Resolve"}
              </div>
            </div>

            <FontAwesomeIcon
              icon={faTrash}
              style={{ ...iconStyle, fontSize: "10px" }}
              data-curio-comment-delete="true"
              onClick={() => deleteComment(comment.id)}
            />
          </div>
        </div>
      ))}

      <textarea
        value={newCommentText}
        onChange={(e) => setNewCommentText(e.target.value)}
        placeholder="Write a comment..."
        style={{ width: "100%", minHeight: "50px", fontSize: "10px" }}
      ></textarea>

      {/* A real button, not a click-handling div: this is the control that
          posts the comment, and it had no role, no accessible name and no way
          to reach it from the keyboard. It also had no test hook, so an e2e
          test could not tell "posted" from "typed but never submitted". */}
      <button
        type="button"
        aria-label="Post comment"
        data-curio-comment-submit="true"
        onClick={onAddComment}
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "flex-end",
          border: 0,
          background: "transparent",
          padding: 0,
          cursor: "pointer",
        }}
      >
        <FontAwesomeIcon icon={faArrowRight} style={iconStyle as any} />
      </button>
    </div>
  );
};

export const iconStyle: CSS.Properties = {
  cursor: "pointer",
  fontSize: "14px",
  color: "#888787",
};

const containerStyles: CSS.Properties = {
  position: "absolute",
  top: "0",
  left: "calc(100% + 10px)",
  width: "150px",
  borderRadius: "5px",
  backgroundColor: "white",
  boxShadow: "0px 0px 5px 0px #ccc",
  padding: "5px",
};

const commentStyles: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  border: "1px solid #ccc",
  borderRadius: "5px",
  margin: "8px 0",
};

const imageStyles: CSS.Properties = {
  width: "15px",
  height: "15px",
  borderRadius: "50%",
};
