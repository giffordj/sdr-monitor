# Live radio — SDR Monitor shortwave receiver

A custom, in-panel live receiver ("relive the shortwave days"): tune, listen,
and optionally record. The **scanner stays primary** — when the radio is active
the scanner is stopped, and it is started again when you stop listening.

## Constraints

- **Two RTL-SDR dongles on the SDR host** (dual-dongle mode):
  - `0` = **Nooelec NESDR SMArt v5** (serial `66687725`) — the scanner.
  - `1` = **RTL-SDR Blog V4** (serial `00000001`) — the radio (HF + VHF/UHF).
- **Pause-and-borrow mode** (the default deployment): **both** dongles scan — the
  NESDR over VHF/UHF and the V4 over the shortwave bands (HF ranges in the
  scanner's `data/config.json`). When the radio starts, the server disables the
  V4 in the scanner config **live over MQTT** (`SDR_RADIO_PAUSE_SERIAL=00000001`),
  waits for the scanner to release it, opens it with `rtl_fm`, and re-enables it
  when the radio stops. The NESDR never stops scanning.
- Env: `SDR_RADIO_DEVICE=1`, `SDR_RADIO_HF_UPCONVERTER=1`,
  `SDR_RADIO_PAUSE_SERIAL=00000001`. Use `SDR_RADIO_KEEP_SCANNER=1` instead of
  `PAUSE_SERIAL` if the radio dongle does *not* scan; without any of these the
  original single-dongle hand-off applies (scanner stopped/started around the
  radio).
- The V4 is a 2-interface device: blacklist `dvb_usb_rtl28xxu` (and
  `rtl2832_sdr`) on the host, or the kernel DVB driver claims it.
- **Do not use `-E direct2` on the V4** — its HF upconverter is ~4x stronger.
  (Measured at 9.7 MHz: RMS 0.024 with upconverter vs 0.006 direct sampling.)
- Base image is Ubuntu 24.04 with `librtlsdr` + SoapySDR but **no** CLI tools;
  `rtl-sdr`, `sox` and `lame` are added in the `Dockerfile`.
- The running supervisord (`/etc/supervisor/conf.d/supervisord.conf`) had no
  control socket; the `Dockerfile` appends one so we can
  `supervisorctl stop|start sdr_scanner` for the handoff.

## Architecture

- **`sdr/utils/radio.py` — `RadioController`** (one gunicorn worker, module
  singleton, guarded by a lock):
  - `start(mode, frequency_hz)`: `supervisorctl stop sdr_scanner`, wait for the
    RTL to be released, then launch the pipeline
    `rtl_fm -M <mode> -f <hz> -s <rate> -g <gain> - | sox ... | lame ...`.
  - A producer thread reads the encoded chunks and **fans out** to any connected
    HTTP streaming clients; per-chunk RMS is kept for an S-meter.
  - `tune(...)`: restart the pipeline at the new frequency (brief gap).
  - `record(on)`: tee chunks to a file under `MEDIA_ROOT`; on stop, optionally
    create a `Transmission` row so it shows up in the library.
  - `stop()`: kill the pipeline and `supervisorctl start sdr_scanner`.
- **API** (`sdr/api.py`, staff + `sdr.change_device`):
  - `GET/POST /sdr/api/radio/` — status / start / stop / tune / record.
  - `GET /sdr/api/radio/stream/` — chunked `audio/mpeg`.
- **UI** — new **Radio** page in the nav, styled like a small shortwave set:
  frequency readout in kHz, band selector (SW broadcast bands), mode
  (AM / USB / LSB / FM), volume, S-meter, play/stop, record. Transmissions get a
  **Listen** action that opens the radio at the detected frequency.

## Status (delivered)

All phases shipped and running on the SDR host (image built by CI):

1. **Foundation** — Dockerfile adds `rtl-sdr`/`sox`/`lame` and a supervisord
   control socket (`/var/run/sdr/supervisor.sock`) so the radio can stop/start
   `sdr_scanner` for the dongle handoff.
2. **Backend** — `sdr/utils/radio.py` `RadioController`: scanner stop/start,
   `rtl_fm | lame` MP3 fan-out, per-chunk RMS for an S-meter, MP3 recording
   (registered as a `Transmission`). API: `/sdr/api/radio/` (+ `/stream/`),
   `/sdr/api/scanner/`.
3. **UI** — Radio page/tab (`/sdr/radio/`): shortwave styling, band presets,
   WFM/FM/AM/USB/LSB, RF gain, volume, S-meter, Play/Stop, Record, manual
   **Hz / kHz / MHz** entry, and a **scanner on/off** switch.
4. **Integration** — "Listen" on each transmission tunes the radio.

Field fixes: broadcast FM is `-M wbfm` (not `wfm`) and needs its own rates (a
`-s 48000` override made it silent); gain `0` means rtl_fm *auto*; the stream
generator now ends cleanly on stop (sentinel); nginx needs `proxy_buffering off`
for the live stream.

## Hardware note

The SDR host runs **two dongles**: the NESDR SMArt v5 (~24 MHz–1.7 GHz) feeds the
scanner, and the **RTL-SDR Blog V4** (24 MHz–1.7 GHz + real HF upconverter)
feeds the radio. The V4 is currently on the **RTL-SDR Blog dipole kit** (long
whips) — fine for strong shortwave broadcasters; a long wire or active loop
(MLA-30 / YouLoop) would be the next upgrade for weak-signal DX. The V4 needs
`librtlsdr` with R828D support (confirmed working: `RTL-SDR Blog V4 Detected`).
Recording format = MP3; saved recordings appear in Transmissions with source
`radio`.

## Dongle selection (2026-10-17)

The radio can use **either** dongle; pick it in the radio's *Radio device*
selector (values are the scanner device serials):

- `SDR_RADIO_DEVICES` — JSON list of selectable dongles, in rtl-sdr
  enumeration order:
  `[{"index":0,"serial":"66687725","label":"NESDR VHF/UHF","hf":false},{"index":1,"serial":"00000001","label":"Blog V4 HF","hf":true}]`
  `index` is passed to `rtl_fm -d`; `serial` keys the pause-and-borrow in the
  scanner config; `hf` enables the V4's HF upconverter handling (skips
  `-E direct2`, which is much weaker on the V4).
- Without `SDR_RADIO_DEVICES` the legacy single-dongle settings
  (`SDR_RADIO_DEVICE`/`SDR_RADIO_PAUSE_SERIAL`/`SDR_RADIO_HF_UPCONVERTER`)
  still apply and appear as one entry.
- The default selection is the legacy pause serial (the Blog V4). Switching
  while listening stops and restarts the receiver; the previous dongle is
  re-enabled in the scanner config on stop.
- The radio's **Scanner: on/off** button stops/starts the scanner process
  (`supervisorctl`), independent of the radio session - it is no longer
  disabled while listening.
