"""Writes ``cuda_mlp.npy``, the weights of the tiny MLP ``test_cuda_mlp.py`` runs on the GPU.

A 64 to 32 to 10 float32 network, kept as one flat array in the order w1
(64x32), b1 (32), w2 (32x10), b2 (10): 2,410 values. They come from a seeded
generator, so the file can always be made again, and ``test_cuda_mlp.py``
checks that the committed file is exactly what this script writes.

Run:  python -m utk_curio.sandbox.tests.cuda_mlp_weights
"""

from pathlib import Path

import numpy as np

SEED = 20261105
#: Units per layer, input first.
LAYERS = (64, 32, 10)
WEIGHTS_FILE = Path(__file__).with_name("cuda_mlp.npy")


def make_weights() -> np.ndarray:
    """Each layer's weights, then its bias, uniform within 1/sqrt(fan-in), as one float32 array."""
    rng = np.random.default_rng(SEED)
    parts = []
    for fan_in, fan_out in zip(LAYERS, LAYERS[1:]):
        bound = 1.0 / np.sqrt(fan_in)
        parts.append(rng.uniform(-bound, bound, size=fan_in * fan_out))
        parts.append(rng.uniform(-bound, bound, size=fan_out))
    return np.concatenate(parts).astype(np.float32)


def layers(flat: np.ndarray) -> list:
    """``[(w, b), ...]`` from the flat array, each ``w`` shaped (fan-in, fan-out)."""
    out, at = [], 0
    for fan_in, fan_out in zip(LAYERS, LAYERS[1:]):
        w = flat[at:at + fan_in * fan_out].reshape(fan_in, fan_out)
        at += fan_in * fan_out
        b = flat[at:at + fan_out]
        at += fan_out
        out.append((w, b))
    if at != flat.size:
        raise ValueError(f"{flat.size} values for layers {LAYERS}, which take {at}")
    return out


if __name__ == "__main__":
    np.save(WEIGHTS_FILE, make_weights())
    print(f"wrote {WEIGHTS_FILE} ({WEIGHTS_FILE.stat().st_size} bytes)")
