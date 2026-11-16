"""Small ONNX models and NetCDF files, built when a test runs.

``tiny_onnx_model`` writes an ONNX model by hand in protobuf's wire format, so
making one needs no library: one ``Add`` node, ``Y = X + B``, where ``X`` is a
float tensor of shape ``[1, 3]`` and ``B`` the constant ``[1, 2, 3]``.
``tiny_qdq_model`` writes a quantized one the same way: QuantizeLinear and
DequantizeLinear nodes with int8 zero points, as a QDQ export holds them.

``netcdf_file`` writes one weather variable the way a WRF output file holds it
(``Time``, ``south_north`` and ``west_east`` dimensions, with ``XLAT`` and
``XLONG`` beside it), in any of the four formats netCDF4 writes. netCDF4 is
imported inside it, so a module that imports this one still loads where
netCDF4 is missing.
"""

from __future__ import annotations

import struct
from pathlib import Path

#: The formats netCDF4 writes, and the bytes each file starts with.
NETCDF_SIGNATURES = {
    "NETCDF3_CLASSIC": b"CDF\x01",
    "NETCDF3_64BIT_OFFSET": b"CDF\x02",
    "NETCDF3_64BIT_DATA": b"CDF\x05",
    "NETCDF4": b"\x89HDF\r\n\x1a\n",
}

#: What ``tiny_onnx_model`` adds to its input.
ADDEND = (1.0, 2.0, 3.0)

#: What ``tiny_qdq_model`` gives: each tensor it dequantizes.
QDQ_OUTPUTS = ("W_dequantized", "X_dequantized", "B_dequantized")

#: ``TensorProto.FLOAT`` and ``TensorProto.INT8``.
_FLOAT = 1
_INT8 = 3


def _varint(value: int) -> bytes:
    if value < 0:  # an int32 or int64 field's negative value: ten bytes
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _int(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _bytes(field: int, value: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(value)) + value


def _str(field: int, value: str) -> bytes:
    return _bytes(field, value.encode("utf-8"))


def _value_info(name: str, dims: list[int], element: int = _FLOAT) -> bytes:
    shape = b"".join(_bytes(1, _int(1, dim)) for dim in dims)
    tensor_type = _int(1, element) + _bytes(2, shape)
    return _str(1, name) + _bytes(2, _bytes(1, tensor_type))


def tiny_onnx_model() -> bytes:
    """A ``ModelProto`` (IR version 8, opset 13) whose graph adds ``ADDEND``."""
    initializer = (
        _int(1, len(ADDEND)) + _int(2, _FLOAT) + _str(8, "B")
        + _bytes(9, struct.pack(f"<{len(ADDEND)}f", *ADDEND))
    )
    node = _str(1, "X") + _str(1, "B") + _str(2, "Y") + _str(4, "Add")
    graph = (
        _bytes(1, node)
        + _str(2, "tiny")
        + _bytes(5, initializer)
        + _bytes(11, _value_info("X", [1, len(ADDEND)]))
        + _bytes(12, _value_info("Y", [1, len(ADDEND)]))
    )
    opset = _int(2, 13)
    return _int(1, 8) + _str(2, "curio-tests") + _bytes(7, graph) + _bytes(8, opset)


def _tensor(name: str, element: int, dims: list[int], *, raw: bytes | None = None,
            int32: list[int] | None = None, external: str | None = None) -> bytes:
    out = b"".join(_int(1, dim) for dim in dims) + _int(2, element) + _str(8, name)
    if raw is not None:
        out += _bytes(9, raw)
    if int32 is not None:  # packed, as ONNX declares int32_data
        out += _bytes(5, b"".join(_varint(value) for value in int32))
    if external is not None:  # external_data's location, and data_location EXTERNAL
        out += _bytes(13, _str(1, "location") + _str(2, external)) + _int(14, 1)
    return out


def _node(op: str, inputs: list[str], output: str, *, axis: int | None = None) -> bytes:
    out = b"".join(_str(1, name) for name in inputs) + _str(2, output) + _str(4, op)
    if axis is not None:  # an INT attribute (AttributeProto.type 2)
        out += _bytes(5, _str(1, "axis") + _int(3, axis) + _int(20, 2))
    return out


def tiny_qdq_model(*, external_zero_point: bool = False) -> bytes:
    """A ``ModelProto`` (IR version 8, opset 13) in QDQ form, its zero points
    int8, whose outputs (``QDQ_OUTPUTS``) are the three tensors it dequantizes:

    - ``W``, float weights of shape ``[2, 3]``, quantized per row (scales
      0.01 and 0.02, zero points 0 and -3, in ``raw_data``) and dequantized;
    - ``X``, the float input of shape ``[2, 3]``, quantized with scale 0.05
      and zero point 7 (in ``int32_data``) and dequantized;
    - ``B``, int8 weights stored quantized, -128 to 127, dequantized with
      scale 0.5 and zero point -2 (in ``int32_data``, ten bytes).

    W's values saturate both ends of int8, as do those of an X from -10 to 100.
    With *external_zero_point*, W's zero points are in external data
    (``w_zero_point.bin``, which is never written)."""
    w_zero_point = (
        _tensor("w_zero_point", _INT8, [2], external="w_zero_point.bin") if external_zero_point
        else _tensor("w_zero_point", _INT8, [2], raw=struct.pack("<2b", 0, -3))
    )
    initializers = [
        _tensor("W", _FLOAT, [2, 3], raw=struct.pack("<6f", -5.0, 0.0123, 1.5, -2.0, 0.31, 3.0)),
        _tensor("w_scale", _FLOAT, [2], raw=struct.pack("<2f", 0.01, 0.02)),
        w_zero_point,
        _tensor("x_scale", _FLOAT, [], raw=struct.pack("<f", 0.05)),
        _tensor("x_zero_point", _INT8, [], int32=[7]),
        _tensor("B", _INT8, [2, 3], raw=struct.pack("<6b", -128, -1, 0, 1, 64, 127)),
        _tensor("b_scale", _FLOAT, [], raw=struct.pack("<f", 0.5)),
        _tensor("b_zero_point", _INT8, [], int32=[-2]),
    ]
    nodes = [
        _node("QuantizeLinear", ["W", "w_scale", "w_zero_point"], "W_quantized", axis=0),
        _node("DequantizeLinear", ["W_quantized", "w_scale", "w_zero_point"], "W_dequantized", axis=0),
        _node("QuantizeLinear", ["X", "x_scale", "x_zero_point"], "X_quantized"),
        _node("DequantizeLinear", ["X_quantized", "x_scale", "x_zero_point"], "X_dequantized"),
        _node("DequantizeLinear", ["B", "b_scale", "b_zero_point"], "B_dequantized"),
    ]
    graph = (
        b"".join(_bytes(1, node) for node in nodes)
        + _str(2, "tiny-qdq")
        + b"".join(_bytes(5, initializer) for initializer in initializers)
        + _bytes(11, _value_info("X", [2, 3]))
        + b"".join(_bytes(12, _value_info(name, [2, 3])) for name in QDQ_OUTPUTS)
        + _bytes(13, _value_info("W_quantized", [2, 3], _INT8))
        + _bytes(13, _value_info("X_quantized", [2, 3], _INT8))
    )
    opset = _int(2, 13)
    return _int(1, 8) + _str(2, "curio-tests") + _bytes(7, graph) + _bytes(8, opset)


def netcdf_file(path: Path, variable: str = "RAIN", *, fmt: str = "NETCDF4", offset: float = 0.0) -> Path:
    """Write *variable* over two hours and a 3 by 4 grid to *path*.

    The values are ``offset + 0, 1, ..., 23`` in C order, so a test knows every
    cell.
    """
    import netCDF4
    import numpy as np

    values = offset + np.arange(24, dtype="float32").reshape(2, 3, 4)
    lats = np.broadcast_to(np.linspace(41.80, 41.90, 3, dtype="float32")[None, :, None], (2, 3, 4))
    lons = np.broadcast_to(np.linspace(-87.70, -87.55, 4, dtype="float32")[None, None, :], (2, 3, 4))
    with netCDF4.Dataset(path, "w", format=fmt) as ds:
        ds.createDimension("Time", 2)
        ds.createDimension("south_north", 3)
        ds.createDimension("west_east", 4)
        dims = ("Time", "south_north", "west_east")
        ds.createVariable(variable, "f4", dims)[:] = values
        ds.createVariable("XLAT", "f4", dims)[:] = lats
        ds.createVariable("XLONG", "f4", dims)[:] = lons
    return Path(path)
