"""Whether a file is an ONNX model, decided without onnxruntime.

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
"""

from __future__ import annotations

from typing import BinaryIO

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
