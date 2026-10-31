# Waveform module

ScopeHost 0.3.0 waveform model, archive, measurements, device-style PNG renderer and canvas were imported from the user's `E:/CODE/scope` project. `ORIGIN.json` records SHA256 of each original file. The source project is unchanged; no runtime path or dependency on it is required.

- `model.py`, `archive.py`, `measurements.py`: NumPy/standard-library core. Archives keep ScopeHost format version 1; optional `test_context` stores automation metadata and is ignored by the original reader.
- `screen_render.py`: Qt-free rendering. The integration adds pixel min/max envelopes to preserve narrow spikes, coupling/offset and voltage statistics. PNGs are reconstructions of the captured samples, not instrument screen pixel transfers.
- `ui/scope_view.py`, `ui/fonts.py`: adapted to PyQt5 signals, event coordinates and font database. No device I/O is permitted in the canvas.
- `record.py`: frozen settings and samples, validates inputs and writes matching CSV/PNG/NPZ/JSON. Existing CSV column names remain compatible. Legacy timed CSV files can be viewed; missing settings are derived only for display and identified as historical CSV.
- `ui/viewer.py`: offline inspection with local zoom, cursors, reference and FFT. View changes use copies of settings; stored samples and original settings stay intact.

The automation instrument layer remains the sole acquisition owner. ScopeHost transport/session code is not imported. Channel settings and trigger/time settings are read while the acquisition is stopped, before resuming it. The effective spacing of the transferred waveform defines its time axis and FFT; it does not imply the scope's maximum ADC sampling rate.

Steady DS1000E records preserve the automation driver's existing VAV anchoring behavior; `dc_anchor_shift` records any correction and the original ADC codes remain available. Transition records preserve the documented conversion and zero reference. The test criterion and sampled waveform are recorded independently for ripple: its AC waveform does not represent the separate DC regulation measurement.
