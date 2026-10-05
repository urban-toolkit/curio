"""Small ONNX models and NetCDF files, built when a test runs.

``tiny_onnx_model`` writes an ONNX model by hand in protobuf's wire format, so
making one needs no library: one ``Add`` node, ``Y = X + B``, where ``X`` is a
float tensor of shape ``[1, 3]`` and ``B`` the constant ``[1, 2, 3]``.

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

#: ``TensorProto.FLOAT``.
_FLOAT = 1


def _varint(value: int) -> bytes:
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


def _value_info(name: str, dims: list[int]) -> bytes:
    shape = b"".join(_bytes(1, _int(1, dim)) for dim in dims)
    tensor_type = _int(1, _FLOAT) + _bytes(2, shape)
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
