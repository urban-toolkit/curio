"""Autark grammar schemas for tests of the agents' readers of it.

``passes_by_reference`` writes a schema's compute passes as autk-grammar 5
writes them, whatever the vendored schema holds, so the readers' tests do not
depend on which release is vendored.
"""
from __future__ import annotations

import json

#: What the GPGPU pass and the render pass of ``passes_by_reference`` say of
#: themselves.
GPGPU_DESCRIPTION = "A pass that runs a shader over a table."
RENDER_DESCRIPTION = "A pass that renders."
#: The description of the GPGPU pass's ``wgslFunction``.
SHADER_DESCRIPTION = "The shader's body."


def _gpgpu_branch(output: str) -> dict:
    text = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "type": {"const": "gpgpu", "type": "string"},
            "dataRef": {"description": "The table the shader runs over.", **text},
            "attributes": {"type": "object", "additionalProperties": text},
            "wgslFunction": {"description": SHADER_DESCRIPTION, **text},
            "outputColumnName": text,
            "outputColumns": {"type": "array", "items": text},
        },
        "required": ["attributes", "dataRef", output, "wgslFunction"],
    }


def passes_by_reference(schema: dict) -> dict:
    """A copy of *schema* whose ``ComputeSpec`` lists a GPGPU pass and a render
    pass by reference, the GPGPU pass one branch per way of naming its output
    (``outputColumnName`` or ``outputColumns``) and the render pass
    ``"type": "render"``, as autk-grammar 5 writes them."""
    schema = json.loads(json.dumps(schema))
    schema["definitions"].update({
        "ComputeSpec": {
            "description": "One entry of `compute`: a GPGPU pass or a render pass.",
            "anyOf": [{"$ref": "#/definitions/GpgpuComputeSpec"}, {"$ref": "#/definitions/RenderComputeSpec"}],
        },
        "GpgpuComputeSpec": {
            "description": GPGPU_DESCRIPTION,
            "anyOf": [_gpgpu_branch("outputColumnName"), _gpgpu_branch("outputColumns")],
        },
        "RenderComputeSpec": {
            "type": "object",
            "description": RENDER_DESCRIPTION,
            "properties": {
                "type": {"const": "render", "type": "string"},
                "outputTableName": {"type": "string"},
                "layers": {"type": "array"},
                "viewpoints": {"type": "object"},
                "aggregation": {"type": "object"},
            },
            "required": ["type", "outputTableName", "layers", "viewpoints", "aggregation"],
        },
    })
    return schema
