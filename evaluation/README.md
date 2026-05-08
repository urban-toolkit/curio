# Evaluation Scripts

This folder contains the reproducibility scripts referenced by the project README.

| File | Purpose |
|---|---|
| `check_fidelity.py` | Compare replayed final graph state against the original session graph. |
| `plot_overhead.py` | Read `sample_sessions/results/latency.csv` and write `../docs/assets/overhead_plot.png`. |
| `run_synthetic_events.js` | Browser-console stress test for event capture latency. |
| `check_scalability.py` | Report event counts, snapshot counts, snapshot sizes, and replay seek timing. |
| `load_sample_session.py` | Import or inspect a sample session JSON file. |

Store generated logs, CSV files, configs, and sample sessions under `sample_sessions/results/`.
