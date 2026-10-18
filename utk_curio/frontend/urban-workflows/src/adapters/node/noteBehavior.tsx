/**
 * The Note node: a title and simple markdown on a color of its own, a way to
 * annotate a dataflow. A person writes it in the node; the Researcher writes
 * its findings into notes. It has no port and nothing to run.
 */
import React from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { NoteBody } from "../../components/notes/NoteBody";

export const useNoteBehavior: NodeBehaviorHook = (data) => ({
  contentComponent: <NoteBody data={data} />,
  disablePlay: true,
});
