"""Whether a file is an ONNX model, and what its graph reads, decided without onnxruntime.

An ONNX model is one protobuf message, ``ModelProto``, so it has no magic bytes
to check the way a TIFF or a NetCDF file has. Instead its top-level fields are
read with protobuf's wire format, each field's payload skipped rather than
read, so a large model costs a few small reads:

- every field is well formed: its number is not 0, its wire type is one
  protobuf defines and, for a field ``ModelProto`` names, the type that field
  has;
- ``ir_version`` (field 1, a positive integer) and ``graph`` (field 7, a
  message) are both there;
- no field runs past the end of the file, and the last one ends where the
  file ends.

A text file, an image, an archive or a NetCDF file renamed ``.onnx`` fails the
check. The backend needs no model library for it: onnxruntime arrives with a
node package, which the backend cannot count on importing.

:func:`graph_inputs` reads the arrays a model's graph takes the same way: the
graph's inputs, each with its name, element type and shape, less the ones an
initializer fills (an older export lists its weights as inputs too).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Iterator

#: ``ModelProto``'s fields (onnx.proto) and the wire type each has: 0 is an
#: integer, 2 a string, a message or a repeated message.
_MODEL_FIELDS = {
    1: 0,   # ir_version
    2: 2,   # producer_name
    3: 2,   # producer_version
    4: 2,   # domain
    5: 0,   # model_version
    6: 2,   # doc_string
    7: 2,   # graph
    8: 2,   # opset_import
    14: 2,  # metadata_props
    20: 2,  # training_info
    25: 2,  # functions
    26: 2,  # configuration
}
_IR_VERSION, _GRAPH = 1, 7

#: Bytes a protobuf varint may take.
_MAX_VARINT_BYTES = 10

#: Top-level fields a model may have. A model has a handful; only its opset
#: imports, metadata, training info and functions repeat.
_MAX_FIELDS = 1 << 16

#: The payload each fixed-width wire type carries: 1 is 64-bit, 5 is 32-bit.
_FIXED_WIDTH = {1: 8, 5: 4}


def _varint(handle: BinaryIO) -> int | None:
    value = 0
    for index in range(_MAX_VARINT_BYTES):
        byte = handle.read(1)
        if not byte:
            return None
        value |= (byte[0] & 0x7F) << (7 * index)
        if not byte[0] & 0x80:
            return value
    return None


def is_onnx_model(handle: BinaryIO, size: int) -> bool:
    """True when the *size* bytes *handle* reads from its start are a model."""
    seen: set[int] = set()
    for _ in range(_MAX_FIELDS):
        position = handle.tell()
        if position == size:
            return _IR_VERSION in seen and _GRAPH in seen
        tag = _varint(handle)
        if tag is None:
            return False
        field, wire = tag >> 3, tag & 7
        if field == 0 or _MODEL_FIELDS.get(field, wire) != wire:
            return False
        if wire == 0:
            value = _varint(handle)
            if value is None or (field == _IR_VERSION and value < 1):
                return False
        elif wire in (2, *_FIXED_WIDTH):
            skip = _varint(handle) if wire == 2 else _FIXED_WIDTH[wire]
            # A payload that runs past the file is refused before the skip: a
            # length can decode to more than any offset ``seek`` accepts.
            if skip is None or skip > size - handle.tell():
                return False
            handle.seek(skip, 1)
        else:
            # 3 and 4 are protobuf's groups, which ONNX never uses; 6 and 7
            # are not wire types at all.
            return False
        seen.add(field)
    return False


# ── What a graph reads ─────────────────────────────────────────────────────

#: ``GraphProto``'s fields that hold its weights and its inputs.
_GRAPH_INITIALIZER, _GRAPH_INPUT = 5, 11
#: ``TensorProto.name``.
_TENSOR_NAME = 8
#: ``TensorProto.DataType`` values, by the name numpy gives each.
_ELEMENT_TYPES = {
    1: "float32", 2: "uint8", 3: "int8", 4: "uint16", 5: "int16", 6: "int32", 7: "int64",
    8: "string", 9: "bool", 10: "float16", 11: "float64", 12: "uint32", 13: "uint64",
    14: "complex64", 15: "complex128", 16: "bfloat16",
}
#: The most inputs read, and the longest name.
_MAX_INPUTS = 64
_MAX_NAME_BYTES = 1024


@dataclass(frozen=True)
class GraphInput:
    """One array a graph takes: its *name*, its element type as numpy names it
    (``None`` when it is not a tensor), and its *shape*, one entry a
    dimension: its size, the name a free dimension has, or ``None`` (``None``
    for the whole shape when the graph does not say)."""

    name: str
    dtype: str | None
    shape: tuple[int | str | None, ...] | None


def _fields(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[int, int | None, tuple[int, int] | None]]:
    """``(field, integer, (offset, length))`` for each field of the message in
    ``[start, end)``: the integer of a varint field, the span of a
    length-delimited one, neither for a fixed-width one. Raises ``ValueError``
    for a field that is not well formed or runs past *end*. The caller may
    read elsewhere between two fields."""
    position = start
    while position < end:
        handle.seek(position)
        tag = _varint(handle)
        if tag is None or tag >> 3 == 0:
            raise ValueError("not a protobuf field")
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value = _varint(handle)
            if value is None:
                raise ValueError("a varint runs past the file")
            position = handle.tell()
            yield field, value, None
        elif wire == 2:
            length = _varint(handle)
            here = handle.tell()
            if length is None or length > end - here:
                raise ValueError("a field runs past its message")
            position = here + length
            yield field, None, (here, length)
        elif wire in _FIXED_WIDTH:
            position = handle.tell() + _FIXED_WIDTH[wire]
        else:
            raise ValueError("not a protobuf wire type")
    if position != end:
        raise ValueError("a field runs past its message")


def _text(handle: BinaryIO, span: tuple[int, int]) -> str:
    start, length = span
    if length > _MAX_NAME_BYTES:
        raise ValueError("a name is too long")
    handle.seek(start)
    return handle.read(length).decode("utf-8")


def _tensor_name(handle: BinaryIO, span: tuple[int, int]) -> str:
    start, length = span
    for field, _value, inner in _fields(handle, start, start + length):
        if field == _TENSOR_NAME and inner is not None:
            return _text(handle, inner)
    return ""


def _shape(handle: BinaryIO, span: tuple[int, int]) -> tuple[int | str | None, ...]:
    """``TensorShapeProto``: one entry per ``dim`` (field 1), from its
    ``dim_value`` (1) or ``dim_param`` (2)."""
    dims: list[int | str | None] = []
    start, length = span
    for field, _value, dim in _fields(handle, start, start + length):
        if field != 1 or dim is None:
            continue
        size: int | str | None = None
        for part, number, inner in _fields(handle, dim[0], dim[0] + dim[1]):
            if part == 1 and number is not None:
                size = number
            elif part == 2 and inner is not None:
                size = _text(handle, inner) or None
        dims.append(size)
    return tuple(dims)


def _tensor_type(handle: BinaryIO, span: tuple[int, int]) -> tuple[str | None, tuple | None]:
    """``TypeProto``: a tensor's (field 1) element type and shape."""
    start, length = span
    for field, _value, tensor in _fields(handle, start, start + length):
        if field != 1 or tensor is None:
            continue
        dtype, shape = None, None
        for part, number, inner in _fields(handle, tensor[0], tensor[0] + tensor[1]):
            if part == 1 and number is not None:
                dtype = _ELEMENT_TYPES.get(number)
            elif part == 2 and inner is not None:
                shape = _shape(handle, inner)
        return dtype, shape
    return None, None


def _value_info(handle: BinaryIO, span: tuple[int, int]) -> GraphInput:
    """``ValueInfoProto``: its ``name`` (1) and ``type`` (2)."""
    name, dtype, shape = "", None, None
    start, length = span
    for field, _value, inner in _fields(handle, start, start + length):
        if inner is None:
            continue
        if field == 1:
            name = _text(handle, inner)
        elif field == 2:
            dtype, shape = _tensor_type(handle, inner)
    return GraphInput(name=name, dtype=dtype, shape=shape)


def graph_inputs(handle: BinaryIO, size: int) -> list[GraphInput] | None:
    """The arrays the model in the *size* bytes *handle* reads takes, in the
    graph's order, less those an initializer fills. ``None`` when the bytes are
    not a model whose graph can be read. Each field's payload is skipped
    unless it is the graph's or one of its inputs', so a large model costs a
    few small reads."""
    try:
        graph = next(
            (span for field, _value, span in _fields(handle, 0, size) if field == _GRAPH and span is not None),
            None,
        )
        if graph is None:
            return None
        inputs: list[tuple[int, int]] = []
        filled: set[str] = set()
        for field, _value, span in _fields(handle, graph[0], graph[0] + graph[1]):
            if span is None:
                continue
            if field == _GRAPH_INPUT and len(inputs) < _MAX_INPUTS:
                inputs.append(span)
            elif field == _GRAPH_INITIALIZER:
                filled.add(_tensor_name(handle, span))
        out = []
        for span in inputs:
            read = _value_info(handle, span)
            if read.name and read.name not in filled:
                out.append(read)
        return out
    except (ValueError, UnicodeDecodeError, OSError):
        return None
