# The dataflow block

The words of the block a run that writes code is given beside its task: what its dataflow can use. A chat run that can write a node's code reads it before the canvas context, and a delegated run that writes code reads it before its task, as a message of its own whose first line is the `dataflow-block` section of `frames.md`. The runtime reads each section below by its name and writes what the section heads after it, one item a line. In a section that says `{count}` or `{tool}`, the runtime writes how many items it left out and the tool that lists them, which it names only to a run that holds that tool.

## datasets

Datasets in this dataflow, each with the line that loads it:

## models

Models in this dataflow, each with the line that loads it:

## keys

Node code keys saved in API Settings, each with the host it is for, how that host takes it, and the line that reads it:

## template

The template of the node being written, with its whole description:

## starter

Its starter:

## functions

Functions its code can import, each from its module as from <module> import <name>, with the first paragraph of its docstring:

## left-out

Left out to keep this context short:

## left-out-datasets

{count} more datasets of this dataflow

## left-out-models

{count} more models of this dataflow

## left-out-keys

{count} more keys

## left-out-description

{count} more characters of its description

## left-out-starter

{count} more lines of its starter

## left-out-functions

{count} more functions its code can import

## read-by

; {tool} lists them
