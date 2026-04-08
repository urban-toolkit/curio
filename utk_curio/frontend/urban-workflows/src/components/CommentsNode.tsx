import React, { useState } from "react";
import { NodeContainer } from "./styles";
import { CommentsList, IComment } from "./comments/CommentsList";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faUpDownLeftRight } from "@fortawesome/free-solid-svg-icons";
import "./Node.css"

export default function CommentsNode({ data }) {
  const [showComments, setShowComments] = useState(false);
  const [comments, setComments] = useState<IComment[]>([]);

  const addComment = (comment: IComment) => {
    setComments([...comments, comment]);
  };

  const deleteComment = (commentId: number) => {
    setComments(comments.filter((comment) => comment.id !== commentId));
  };

  const toggleResolveComment = (commentId: number) => {
    setComments(
      comments.map((comment) => {
        if (comment.id === commentId) {
          comment.resolved = !comment.resolved;
        }
        return comment;
      })
    );
  };

  return (
    <NodeContainer
      nodeId={data.nodeId}
      styles={{ width: "auto", height: "auto" }}
      disableComments={true}
    >
      <FontAwesomeIcon icon={faUpDownLeftRight} />
      <CommentsList
        comments={comments}
        addComment={addComment}
        deleteComment={deleteComment}
        toggleResolveComment={toggleResolveComment}
      />
    </NodeContainer>
  );
}
