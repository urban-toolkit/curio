"""Read an OpenStreetMap ``.osm.pbf`` with the standard library.

``read_pbf`` decodes the file format (https://wiki.openstreetmap.org/wiki/PBF_Format)
by hand: blobs of zlib-compressed protobuf messages, dense nodes, ways and
relations. It gives what ``scripts/build_example_pbfs.py``'s ``cut`` takes:
nodes as ``{id: (lon, lat, tags)}``, ways as ``{id: (refs, tags)}`` and
relations as ``{id: (members, tags)}``, a member being ``(type, ref, role)``
with type ``"n"``, ``"w"`` or ``"r"``, plus the header's box (south, west,
north, east, or None), writing program and replication timestamp.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import NamedTuple

_MEMBER_TYPES = {0: "n", 1: "w", 2: "r"}


class Extract(NamedTuple):
    nodes: dict
    ways: dict
    relations: dict
    box: tuple[float, float, float, float] | None
    generator: str
    timestamp: int | None


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(buf: bytes) -> dict[int, list]:
    """A message's fields: number to the list of its values (an int for a
    varint, bytes for a length-delimited field)."""
    fields: dict[int, list] = {}
    pos, end = 0, len(buf)
    while pos < end:
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.setdefault(number, []).append(value)
    return fields


def _ints(fields: dict[int, list], number: int) -> list[int]:
    """A repeated integer field, packed or not."""
    out: list[int] = []
    for value in fields.get(number, []):
        if isinstance(value, int):
            out.append(value)
            continue
        pos = 0
        while pos < len(value):
            item, pos = _varint(value, pos)
            out.append(item)
    return out


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _int64(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def _deltas(values: list[int]) -> list[int]:
    out, total = [], 0
    for value in values:
        total += _zigzag(value)
        out.append(total)
    return out


def _one(fields: dict[int, list], number: int, default=None):
    values = fields.get(number)
    return values[-1] if values else default


def _blobs(data: bytes):
    pos = 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        pos += 4
        header = _fields(data[pos:pos + length])
        pos += length
        size = _one(header, 3)
        blob = _fields(data[pos:pos + size])
        pos += size
        if 1 in blob:
            raw = _one(blob, 1)
        elif 3 in blob:
            raw = zlib.decompress(_one(blob, 3))
        else:
            raise ValueError("only raw and zlib blobs are supported")
        yield _one(header, 1).decode(), raw


def _tags(keys: list[int], vals: list[int], strings: list[str]) -> dict:
    return {strings[k]: strings[v] for k, v in zip(keys, vals)}


def read_pbf(path: str | Path) -> Extract:
    nodes: dict = {}
    ways: dict = {}
    relations: dict = {}
    box = None
    generator = ""
    timestamp = None
    for kind, raw in _blobs(Path(path).read_bytes()):
        block = _fields(raw)
        if kind == "OSMHeader":
            if 1 in block:
                bbox = _fields(_one(block, 1))
                left, right, top, bottom = (_zigzag(_one(bbox, i)) / 1e9 for i in (1, 2, 3, 4))
                box = (bottom, left, top, right)
            generator = _one(block, 16, b"").decode()
            stamp = _one(block, 32)
            timestamp = _int64(stamp) if stamp is not None else None
            continue
        if kind != "OSMData":
            continue
        strings = [s.decode() for s in _fields(_one(block, 1, b"")).get(1, [])]
        granularity = _one(block, 17, 100)
        lat_offset = _int64(_one(block, 19, 0))
        lon_offset = _int64(_one(block, 20, 0))

        def degrees(offset: int, value: int) -> float:
            return (offset + granularity * value) / 1e9

        for group_bytes in block.get(2, []):
            group = _fields(group_bytes)
            for node_bytes in group.get(1, []):
                node = _fields(node_bytes)
                nodes[_zigzag(_one(node, 1))] = (
                    degrees(lon_offset, _zigzag(_one(node, 9))),
                    degrees(lat_offset, _zigzag(_one(node, 8))),
                    _tags(_ints(node, 2), _ints(node, 3), strings),
                )
            for dense_bytes in group.get(2, []):
                dense = _fields(dense_bytes)
                ids = _deltas(_ints(dense, 1))
                lats = _deltas(_ints(dense, 8))
                lons = _deltas(_ints(dense, 9))
                keys_vals = _ints(dense, 10)
                pos = 0
                for node_id, lat, lon in zip(ids, lats, lons):
                    tags = {}
                    while keys_vals and keys_vals[pos] != 0:
                        tags[strings[keys_vals[pos]]] = strings[keys_vals[pos + 1]]
                        pos += 2
                    pos += 1 if keys_vals else 0
                    nodes[node_id] = (degrees(lon_offset, lon), degrees(lat_offset, lat), tags)
            for way_bytes in group.get(3, []):
                way = _fields(way_bytes)
                ways[_int64(_one(way, 1))] = (_deltas(_ints(way, 8)), _tags(_ints(way, 2), _ints(way, 3), strings))
            for relation_bytes in group.get(4, []):
                relation = _fields(relation_bytes)
                members = [
                    (_MEMBER_TYPES[t], ref, strings[role])
                    for t, ref, role in zip(_ints(relation, 10), _deltas(_ints(relation, 9)), _ints(relation, 8))
                ]
                relations[_int64(_one(relation, 1))] = (
                    members, _tags(_ints(relation, 2), _ints(relation, 3), strings),
                )
    return Extract(nodes, ways, relations, box, generator, timestamp)
