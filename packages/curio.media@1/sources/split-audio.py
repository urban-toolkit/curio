"""Split Audio.

Input: a collection's rows, as Data Loading's `curio_load_collection(...)` returns
them. Every recording becomes one row per window, with the window's level and
peak in dBFS (decibels below full scale) over all of its channels, and a
short WAV of the window, in the recording's channels, that Simple View can
play. A window row keeps the recording's fields, and its `recorded_at` moves
forward by the window's offset. A recording is read one window at a time.

Settings:
- WINDOW_SECONDS: the length of one window.
- MAX_WINDOWS_PER_RECORDING: windows kept from one recording at most.
"""

from media_collections import split_audio

WINDOW_SECONDS = 5.0
MAX_WINDOWS_PER_RECORDING = 2000

return split_audio(
    input_0, curio_derived_file,
    window_seconds=WINDOW_SECONDS, max_windows_per_recording=MAX_WINDOWS_PER_RECORDING,
)
