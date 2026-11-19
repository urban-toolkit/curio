#!/usr/bin/env python3
"""Store a QDQ ONNX model's int8 zero points as uint8 ones, 128 higher.

    python scripts/onnx_zero_points_to_uint8.py <model.onnx>              rewrite it in place
    python scripts/onnx_zero_points_to_uint8.py <model.onnx> --out PATH  write the result to PATH
    python scripts/onnx_zero_points_to_uint8.py <model.onnx> --list      say what would change, write nothing

A QDQ export quantizes its tensors with QuantizeLinear and DequantizeLinear
nodes. Each int8 zero point those nodes read becomes the uint8 one 128 higher,
and so do the int8 tensors it quantizes: a QuantizeLinear that reads it is
typed uint8 and gives q + 128 where it gave q, and an int8 initializer a
DequantizeLinear reads with it is stored 128 higher. DequantizeLinear gives
(q - zero point) * scale, so the graph computes the same values.

onnxruntime fuses a QDQ graph into integer kernels by the types it finds.
With int8 weights, an x86 CPU without VNNI (AVX2 only: AMD Zen 2 and 3, Intel
before Ice Lake) runs a kernel whose sums of pairs of products saturate at 16
bits, so its results differ from those of CPUs with VNNI or AMX, which compute
exactly. With uint8 weights every x86 CPU computes exactly. DDRNet23-Slim's
graph (``packages/model.curio.ddrnet23-slim@1``) is Qualcomm AI Hub's export
after this script.

It refuses, writing nothing, a model it cannot change without changing what
the graph computes, or without its external data:

- a tensor it would change is in external data;
- an int8 initializer it would change is read other than as the zero point of
  a QuantizeLinear or DequantizeLinear, or as the input of a DequantizeLinear
  whose zero point it changes, or is also a graph input;
- a QuantizeLinear output it would type uint8 is a graph output, or is read
  other than by a DequantizeLinear whose zero point it changes, or the
  QuantizeLinear names its output's type (``output_dtype``);
- a DequantizeLinear whose zero point it changes reads anything else;
- a node holds a subgraph, or the model holds functions of its own;
- an int8 tensor is left after the change: an initializer, a graph input,
  output or value info, or a node's tensor attribute (a Constant's value).

Only the .onnx file is read and written: external data beside it (a .data
file) stays as it is. It imports nothing but the standard library.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

#: ``TensorProto.DataType``.
UINT8, INT8 = 2, 3
#: What a zero point is stored higher by.
OFFSET = 128

#: The ONNX protobuf fields this reads, by message.
MODEL_GRAPH, MODEL_FUNCTIONS = 7, 25
GRAPH_NODE, GRAPH_INITIALIZER, GRAPH_INPUT, GRAPH_OUTPUT, GRAPH_VALUE_INFO, GRAPH_SPARSE_INITIALIZER = 1, 5, 11, 12, 13, 15
NODE_INPUT, NODE_OUTPUT, NODE_OP_TYPE, NODE_ATTRIBUTE, NODE_DOMAIN = 1, 2, 4, 5, 7
ATTRIBUTE_NAME, ATTRIBUTE_TENSOR, ATTRIBUTE_GRAPH, ATTRIBUTE_TENSORS, ATTRIBUTE_GRAPHS = 1, 5, 6, 10, 11
ATTRIBUTE_SPARSE_TENSOR, ATTRIBUTE_SPARSE_TENSORS = 22, 23
SPARSE_VALUES = 1
TENSOR_DIMS, TENSOR_DATA_TYPE, TENSOR_INT32_DATA, TENSOR_NAME, TENSOR_RAW_DATA = 1, 2, 5, 8, 9
TENSOR_EXTERNAL_DATA, TENSOR_DATA_LOCATION = 13, 14
#: ``TensorProto.DataLocation.EXTERNAL``.
EXTERNAL = 1
VALUE_INFO_NAME, VALUE_INFO_TYPE = 1, 2
TYPE_TENSOR, TENSOR_TYPE_ELEMENT = 1, 1

QUANTIZE, DEQUANTIZE = "QuantizeLinear", "DequantizeLinear"
#: The domain names of ONNX's own operators.
ONNX_DOMAINS = ("", "ai.onnx")
#: The input of QuantizeLinear and DequantizeLinear that is the zero point.
ZERO_POINT = 2


class Refused(ValueError):
    """A model this script does not change; the message holds a line per reason."""


class Tensor(NamedTuple):
    name: str
    data_type: int | None
    values: int
    external: bool


class Node(NamedTuple):
    op: str
    domain: str
    inputs: list
    outputs: list
    attributes: list
    tensors: list
    subgraph: bool

    def is_op(self, op: str) -> bool:
        return self.op == op and self.domain in ONNX_DOMAINS

    def label(self) -> str:
        return f"{self.op} {', '.join(self.outputs) or '(no output)'}"


class Graph(NamedTuple):
    initializers: dict
    sparse_initializers: list
    nodes: list
    inputs: list
    outputs: list
    value_infos: list
    functions: bool


class Conversion(NamedTuple):
    """The model with its int8 zero points as uint8 ones, and what changed."""

    model: bytes
    #: The zero points stored as uint8, each with how many values it holds.
    zero_points: dict
    #: The int8 initializers stored as uint8 because a DequantizeLinear reads
    #: them with a zero point that changed, with how many values each holds.
    quantized: dict
    #: The QuantizeLinear outputs typed uint8.
    retyped: list
    #: How many graph inputs, outputs and value infos were retyped.
    value_infos: int


# ---------------------------------------------------------------------------
# Protobuf's wire format
# ---------------------------------------------------------------------------

def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if not value:
            out.append(byte)
            return bytes(out)
        out.append(byte | 0x80)


def _signed(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def fields(buf: bytes):
    """Each field of one protobuf message, in order: ``(number, wire type,
    value, the field's own bytes)``. A varint's value is an int, any other
    field's its bytes."""
    pos, end = 0, len(buf)
    while pos < end:
        start = pos
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"not an ONNX model: protobuf wire type {wire}")
        if pos > end:
            raise ValueError("not an ONNX model: a field runs past the end of its message")
        yield number, wire, value, buf[start:pos]


def _length_field(number: int, payload: bytes) -> bytes:
    return _encode_varint((number << 3) | 2) + _encode_varint(len(payload)) + payload


def _varint_field(number: int, value: int) -> bytes:
    return _encode_varint(number << 3) + _encode_varint(value)


def _varints(wire: int, value) -> list[int]:
    """The values of a repeated varint field's entry, packed or not, signed."""
    if wire != 2:
        return [_signed(value)]
    values, pos = [], 0
    while pos < len(value):
        item, pos = _varint(value, pos)
        values.append(_signed(item))
    return values


# ---------------------------------------------------------------------------
# Reading a graph
# ---------------------------------------------------------------------------

def _tensor(buf: bytes) -> Tensor:
    name, data_type, values, external = "", None, 1, False
    for number, wire, value, _raw in fields(buf):
        if number == TENSOR_NAME:
            name = value.decode("utf-8")
        elif number == TENSOR_DATA_TYPE:
            data_type = value
        elif number == TENSOR_DIMS:
            for dim in _varints(wire, value):
                values *= dim
        elif number == TENSOR_EXTERNAL_DATA or (number == TENSOR_DATA_LOCATION and value == EXTERNAL):
            external = True
    return Tensor(name, data_type, values, external)


def _sparse_values(buf: bytes) -> Tensor | None:
    return next((_tensor(value) for number, _w, value, _r in fields(buf) if number == SPARSE_VALUES), None)


def _value_info(buf: bytes) -> tuple[str, int | None]:
    """A ``ValueInfoProto``'s name and, for a tensor, its element type."""
    name, element = "", None
    for number, _wire, value, _raw in fields(buf):
        if number == VALUE_INFO_NAME:
            name = value.decode("utf-8")
        elif number == VALUE_INFO_TYPE:
            for kind, _w, tensor_type, _r in fields(value):
                if kind == TYPE_TENSOR:
                    for part, _w2, element_type, _r2 in fields(tensor_type):
                        if part == TENSOR_TYPE_ELEMENT:
                            element = element_type
    return name, element


def _node(buf: bytes) -> Node:
    op, domain, inputs, outputs, attributes, tensors, subgraph = "", "", [], [], [], [], False
    for number, _wire, value, _raw in fields(buf):
        if number == NODE_OP_TYPE:
            op = value.decode("utf-8")
        elif number == NODE_DOMAIN:
            domain = value.decode("utf-8")
        elif number == NODE_INPUT:
            inputs.append(value.decode("utf-8"))
        elif number == NODE_OUTPUT:
            outputs.append(value.decode("utf-8"))
        elif number == NODE_ATTRIBUTE:
            for part, _w, item, _r in fields(value):
                if part == ATTRIBUTE_NAME:
                    attributes.append(item.decode("utf-8"))
                elif part in (ATTRIBUTE_TENSOR, ATTRIBUTE_TENSORS):
                    tensors.append(_tensor(item))
                elif part in (ATTRIBUTE_SPARSE_TENSOR, ATTRIBUTE_SPARSE_TENSORS):
                    sparse = _sparse_values(item)
                    if sparse is not None:
                        tensors.append(sparse)
                elif part in (ATTRIBUTE_GRAPH, ATTRIBUTE_GRAPHS):
                    subgraph = True
    return Node(op, domain, inputs, outputs, attributes, tensors, subgraph)


def _graph_bytes(model: bytes) -> bytes:
    graph = next((value for number, _w, value, _r in fields(model) if number == MODEL_GRAPH), None)
    if graph is None:
        raise ValueError("not an ONNX model: no graph")
    return graph


def read_graph(model: bytes) -> Graph:
    """The parts of *model*'s main graph this script reads."""
    initializers, sparse, nodes, inputs, outputs, value_infos = {}, [], [], [], [], []
    for number, _wire, value, _raw in fields(_graph_bytes(model)):
        if number == GRAPH_INITIALIZER:
            tensor = _tensor(value)
            initializers[tensor.name] = tensor
        elif number == GRAPH_SPARSE_INITIALIZER:
            values = _sparse_values(value)
            if values is not None:
                sparse.append(values)
        elif number == GRAPH_NODE:
            nodes.append(_node(value))
        elif number == GRAPH_INPUT:
            inputs.append(_value_info(value))
        elif number == GRAPH_OUTPUT:
            outputs.append(_value_info(value))
        elif number == GRAPH_VALUE_INFO:
            value_infos.append(_value_info(value))
    functions = any(number == MODEL_FUNCTIONS for number, _w, _v, _r in fields(model))
    return Graph(initializers, sparse, nodes, inputs, outputs, value_infos, functions)


def int8_tensors(model: bytes) -> list[str]:
    """Every int8 tensor *model*'s main graph holds, each as ``<what> <name>``:
    its initializers, graph inputs, outputs and value infos, and its nodes'
    tensor attributes, such as a Constant's value. An external tensor's type
    is in the .onnx file, so external data is not read."""
    graph = read_graph(model)
    found = [f"initializer {t.name}" for t in graph.initializers.values() if t.data_type == INT8]
    found += [f"sparse initializer {t.name}" for t in graph.sparse_initializers if t.data_type == INT8]
    for what, infos in (("input", graph.inputs), ("output", graph.outputs), ("value info", graph.value_infos)):
        found += [f"{what} {name}" for name, element in infos if element == INT8]
    for node in graph.nodes:
        found += [f"tensor attribute of {node.label()}" for t in node.tensors if t.data_type == INT8]
    return found


# ---------------------------------------------------------------------------
# The change
# ---------------------------------------------------------------------------

def _as_uint8(buf: bytes) -> bytes:
    """An int8 ``TensorProto`` as the uint8 one 128 higher."""
    out = bytearray()
    for number, wire, value, raw in fields(buf):
        if number == TENSOR_DATA_TYPE:
            out += _varint_field(TENSOR_DATA_TYPE, UINT8)
        elif number == TENSOR_RAW_DATA:
            out += _length_field(TENSOR_RAW_DATA, bytes((byte + OFFSET) & 0xFF for byte in value))
        elif number == TENSOR_INT32_DATA:
            higher = b"".join(_encode_varint(item + OFFSET) for item in _varints(wire, value))
            out += _length_field(TENSOR_INT32_DATA, higher)
        else:
            out += raw
    return bytes(out)


def _typed(buf: bytes, element: int) -> bytes:
    """A tensor's ``ValueInfoProto`` with *element* as its element type."""
    out = bytearray()
    for number, _wire, value, raw in fields(buf):
        if number != VALUE_INFO_TYPE:
            out += raw
            continue
        type_out = bytearray()
        for kind, _w, tensor_type, kind_raw in fields(value):
            if kind != TYPE_TENSOR:
                type_out += kind_raw
                continue
            tensor_out = bytearray()
            for part, _w2, _value, part_raw in fields(tensor_type):
                tensor_out += _varint_field(TENSOR_TYPE_ELEMENT, element) if part == TENSOR_TYPE_ELEMENT else part_raw
            type_out += _length_field(TYPE_TENSOR, bytes(tensor_out))
        out += _length_field(VALUE_INFO_TYPE, bytes(type_out))
    return bytes(out)


def _problems(graph: Graph, zero_points: set, quantized: set, retyped: set) -> list[str]:
    """Why changing *zero_points*, *quantized* and *retyped* would change what
    *graph* computes, or could not be done in the .onnx file."""
    problems = []
    if graph.functions:
        problems.append("the model holds functions of its own, which this does not read")
    changed = zero_points | quantized

    def changes_zero_point(node: Node) -> bool:
        return ((node.is_op(QUANTIZE) or node.is_op(DEQUANTIZE)) and len(node.inputs) > ZERO_POINT
                and node.inputs[ZERO_POINT] in zero_points)

    for node in graph.nodes:
        if node.subgraph:
            problems.append(f"{node.label()} holds a subgraph, which this does not read")
        if node.is_op(QUANTIZE) and changes_zero_point(node) and "output_dtype" in node.attributes:
            problems.append(f"{node.label()} names its output's type (output_dtype), which would not be uint8")
        reads_quantized = node.is_op(DEQUANTIZE) and changes_zero_point(node)
        for slot, name in enumerate(node.inputs):
            if name in changed:
                as_zero_point = slot == ZERO_POINT and (node.is_op(QUANTIZE) or node.is_op(DEQUANTIZE))
                if not (as_zero_point or (slot == 0 and reads_quantized)):
                    problems.append(f"{name} is input {slot} of {node.label()}, which would read it 128 higher")
            if name in retyped and not (slot == 0 and reads_quantized):
                problems.append(f"{name}, a QuantizeLinear output this would type uint8, is input {slot} of "
                                f"{node.label()}, which would read it 128 higher")
        if reads_quantized and node.inputs[0] not in changed and node.inputs[0] not in retyped:
            problems.append(f"{node.label()} reads {node.inputs[0]} with the zero point "
                            f"{node.inputs[ZERO_POINT]}, and {node.inputs[0]} is not a tensor this changes")
    graph_inputs = {name for name, _element in graph.inputs}
    graph_outputs = {name for name, _element in graph.outputs}
    problems += [f"{name} is also a graph input, which a caller could feed as int8"
                 for name in sorted(changed & graph_inputs)]
    problems += [f"{name} is a graph output, which would give values 128 higher" for name in sorted(retyped & graph_outputs)]
    problems += [f"{name} is in external data, which this does not rewrite"
                 for name in sorted(changed) if graph.initializers[name].external]
    return problems


def convert(model: bytes) -> Conversion:
    """*model*, the bytes of an ONNX file, with every int8 zero point its
    QuantizeLinear and DequantizeLinear nodes read stored as the uint8 one 128
    higher, the int8 initializers DequantizeLinear reads with them too, and
    the outputs of the QuantizeLinear nodes that read them typed uint8: the
    same values, on uint8 tensors. Raises :class:`Refused` for a model it
    cannot change that way (the module's docstring lists why), and
    ``ValueError`` for a file that is not an ONNX model."""
    graph = read_graph(model)
    int8 = {name for name, tensor in graph.initializers.items() if tensor.data_type == INT8}
    zero_points, quantized, retyped = set(), set(), []
    for node in graph.nodes:
        if (node.is_op(QUANTIZE) or node.is_op(DEQUANTIZE)) and len(node.inputs) > ZERO_POINT:
            if node.inputs[ZERO_POINT] in int8:
                zero_points.add(node.inputs[ZERO_POINT])
    for node in graph.nodes:
        if len(node.inputs) <= ZERO_POINT or node.inputs[ZERO_POINT] not in zero_points:
            continue
        if node.is_op(QUANTIZE):
            retyped += node.outputs[:1]
        elif node.is_op(DEQUANTIZE) and node.inputs[0] in int8:
            quantized.add(node.inputs[0])
    problems = _problems(graph, zero_points, quantized, set(retyped))
    if problems:
        raise Refused("\n".join(problems))
    changed, retyped_names = zero_points | quantized, set(retyped)
    graph_out, value_infos = bytearray(), 0
    for number, _wire, value, raw in fields(_graph_bytes(model)):
        if number == GRAPH_INITIALIZER and _tensor(value).name in changed:
            graph_out += _length_field(number, _as_uint8(value))
        elif number in (GRAPH_INPUT, GRAPH_OUTPUT, GRAPH_VALUE_INFO) and _value_info(value)[0] in retyped_names \
                and _value_info(value)[1] == INT8:
            graph_out += _length_field(number, _typed(value, UINT8))
            value_infos += 1
        else:
            graph_out += raw
    out = b"".join(
        _length_field(MODEL_GRAPH, bytes(graph_out)) if number == MODEL_GRAPH else raw
        for number, _wire, _value, raw in fields(model)
    )
    left = int8_tensors(out)
    if left:
        shown = ", ".join(left[:8]) + (f" and {len(left) - 8} more" if len(left) > 8 else "")
        raise Refused(f"int8 tensors would be left after the change, so its kernels would still read int8: {shown}")
    return Conversion(
        model=out,
        zero_points={name: graph.initializers[name].values for name in sorted(zero_points)},
        quantized={name: graph.initializers[name].values for name in sorted(quantized)},
        retyped=retyped,
        value_infos=value_infos,
    )


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def _write(target: Path, data: bytes, like: Path) -> None:
    """Write *data* to *target* through a temporary file beside it, so the
    file is never half written; it takes *like*'s permission bits."""
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temporary, os.stat(like).st_mode & 0o7777)
        os.replace(temporary, target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def main(argv=None, *, out=None, err=None) -> int:
    """The command; returns its exit status: 0 when it wrote the model or had
    nothing to change, 1 when it refused or could not read or write."""
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(
        description="Store a QDQ ONNX model's int8 zero points as uint8 ones, 128 higher: "
                    "the same values, on uint8 tensors.",
    )
    parser.add_argument("model", type=Path, help="the .onnx file")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--out", type=Path, metavar="PATH", help="write the result to PATH, not over the model")
    where.add_argument("--list", action="store_true", help="say what would change, and write nothing")
    args = parser.parse_args(argv)
    try:
        conversion = convert(args.model.read_bytes())
    except Refused as exc:
        print(f"{args.model}: not changed, nothing written:", file=err)
        for line in str(exc).splitlines():
            print(f"  {line}", file=err)
        return 1
    except OSError as exc:
        print(f"{args.model}: {exc.strerror or exc}", file=err)
        return 1
    except (ValueError, IndexError) as exc:
        print(f"{args.model}: not an ONNX model this reads ({str(exc) or type(exc).__name__})", file=err)
        return 1
    if not conversion.zero_points:
        print(f"{args.model}: no int8 zero point; nothing written.", file=out)
        return 0
    count = len(conversion.zero_points)
    print(f"{args.model}: {'would store' if args.list else 'stores'} {count} int8 zero "
          f"point{'s' if count != 1 else ''} as uint8, 128 higher, and types {len(conversion.retyped)} "
          f"QuantizeLinear outputs uint8 ({conversion.value_infos} value infos):", file=out)
    for name, values in conversion.zero_points.items():
        print(f"  zero point {name}: {values} value{'s' if values != 1 else ''}", file=out)
    for name, values in conversion.quantized.items():
        print(f"  quantized tensor {name}: {values} value{'s' if values != 1 else ''}", file=out)
    if args.list:
        print("Nothing written (--list).", file=out)
        return 0
    target = args.out or args.model
    try:
        _write(target, conversion.model, args.model)
    except OSError as exc:
        print(f"{target}: {exc.strerror or exc}", file=err)
        return 1
    print(f"Wrote {target}.", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
