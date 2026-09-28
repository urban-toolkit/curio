"""Split Audio.

Input: a collection's rows, as Data Loading's `curio_collection(...)` returns
them. Every recording becomes one row per window, with the window's level and
peak in dBFS (decibels below full scale) over all of its channels, and a
short WAV of the window, in the recording's channels, that Simple View can
play. A window row keeps the recording's fields, and its `recorded_at` moves
forward by the window's offset. A recording is read one window at a time.

Settings:
- WINDOW_SECONDS: the length of one window.
- MAX_WINDOWS_PER_RECORDING: windows kept from one recording at most.
"""

import datetime
import math
import wave

import av
import numpy as np
import pandas as pd

WINDOW_SECONDS = 5.0
MAX_WINDOWS_PER_RECORDING = 2000

PER_FILE = {
    "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "duration_s",
    "sample_rate", "channels", "codec", "path", "thumbnail", "image_url",
    "audio_url", "probe_error", "geometry",
}


def dbfs(value):
    return round(20 * math.log10(value), 2) if value > 0 else -120.0


def windows(path):
    """``(rate, start, samples)`` per window, where *samples* is one row per
    sample and one column per channel, decoded as it is needed."""
    with av.open(path) as container:
        stream = container.streams.audio[0]
        rate = stream.codec_context.sample_rate or 16000
        resampler = av.AudioResampler(format="s16", layout=stream.codec_context.layout, rate=rate)
        width = max(1, int(WINDOW_SECONDS * rate))
        pending, held, start, made = [], 0, 0, 0

        def decoded():
            for frame in container.decode(stream):
                yield from resampler.resample(frame)
            yield from resampler.resample(None)

        for out in decoded():
            block = out.to_ndarray().reshape(-1, out.layout.nb_channels)
            pending.append(block)
            held += len(block)
            while held >= width:
                joined = np.concatenate(pending)
                yield rate, start, joined[:width]
                made += 1
                if made >= MAX_WINDOWS_PER_RECORDING:
                    return
                rest = joined[width:]
                pending, held, start = ([rest] if len(rest) else []), len(rest), start + width
        if held:
            yield rate, start, np.concatenate(pending)


media = arg
recordings = media[media["kind"] == "audio"]
rows = []
for _, recording in recordings.iterrows():
    if not isinstance(recording["path"], str) or not recording["path"]:
        raise ValueError(
            f"{recording['relpath']} is not on this machine yet; cache the collection's files first"
        )
    for rate, start, window in windows(recording["path"]):
        scaled = window.astype(np.float64) / 32768.0
        t_s = round(start / rate, 3)
        derived = curio_derived_file(
            recording["dataset_id"], recording["file_id"], round(t_s * 1000), kind="audio"
        )
        with wave.open(derived["path"], "wb") as handle:
            handle.setnchannels(window.shape[1])
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(window.astype("<i2").tobytes())
        row = {k: recording[k] for k in recording.index if k not in PER_FILE}
        started = recording.get("recorded_at")
        if isinstance(started, (pd.Timestamp, datetime.datetime)) and not pd.isna(started):
            row["recorded_at"] = started + datetime.timedelta(seconds=t_s)
        row.update({
            "file_id": derived["file_id"],
            "kind": "audio",
            "recording_file_id": recording["file_id"],
            "recording": recording["name"],
            "t_s": t_s,
            "duration_s": round(len(window) / rate, 3),
            "level_dbfs": dbfs(float(np.sqrt(np.mean(scaled ** 2)))),
            "peak_dbfs": dbfs(float(np.max(np.abs(scaled)))),
            "path": derived["path"],
            "thumbnail": derived["thumbnail"],
            "audio_url": derived["audio_url"],
        })
        rows.append(row)

return pd.DataFrame(rows)
