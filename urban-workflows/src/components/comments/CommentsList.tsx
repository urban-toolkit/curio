import React, { useState } from "react";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowRight,
  faSquareCheck,
  faTrash,
} from "@fortawesome/free-solid-svg-icons";

import { useUserContext } from "../../providers/UserProvider";

export interface IComment {
  id: number;
  text: string;
  user: {
    name: string;
    photo: string;
  };
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
  deleteComment: (commentId: number) => void;
  toggleResolveComment: (commentId: number) => void;
}) => {
  const { user } = useUserContext();
  const [newCommentText, setNewCommentText] = useState("");

  const onAddComment = () => {
    if (newCommentText.trim() === "") return alert("Please write a comment");
    if (!user) return alert("Please login to comment");

    addComment({
      id: comments.length + 1,
      text: newCommentText,
      user: {
        name: user.name,
        photo: user.profile_image,
      },
      canDelete: true,
      resolved: false,
    });

    setNewCommentText("");
  };

  return (
    <div style={containerStyles}>
      {comments.map((comment, index) => (
        <div
          key={index}
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
              src={comment.user.photo}
              alt={comment.user.name}
              style={imageStyles}
            />
            <strong style={{ fontSize: "10px", marginLeft: "5px" }}>
              {comment.user.name}
            </strong>
          </div>

          <p style={{ width: "100%", padding: "5px", fontSize: "10px", wordBreak: "break-word" }}>
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
              onClick={() => toggleResolveComment(comment.id)}
            >
              <FontAwesomeIcon icon={faSquareCheck} style={{...iconStyle, fontSize: "10px", ...(comment.resolved ? { color: "green" } : {})}} />
              <div style={{ marginLeft: "2px", fontSize: "8px" }}>
                {comment.resolved ? "Resolved" : "Resolve"}
              </div>
            </div>

            <FontAwesomeIcon
              icon={faTrash}
              style={{...iconStyle, fontSize: "10px"}}
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

      <div
        style={{ width: "100%", display: "flex", justifyContent: "flex-end" }}
        onClick={onAddComment}
      >
        <FontAwesomeIcon icon={faArrowRight} style={iconStyle} />
      </div>
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
