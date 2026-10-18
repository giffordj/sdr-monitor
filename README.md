# SDR Monitor (fork)

**Our fork of [shajen/sdr-monitor](https://github.com/shajen/sdr-monitor)** — the
Django web panel used by the `sdr-hub` SDR stack (C++ GNU Radio scanner +
web UI for RTL-SDR dongles). Published for credit and reuse; see
[CHANGELOG.md](CHANGELOG.md) for what differs from upstream.

## Highlights of this fork

- **Scanning status page** — per-device liveness (scanner state, last ingest,
  last transmission) built on a worker-refreshed status cache, so pages render
  in milliseconds instead of waiting ~2.4 s on an MQTT round-trip.
- **Cached spectrogram images** — rendered once per data version instead of on
  every request (previously ~0.5 s CPU and 2 MB per row view), with automatic
  invalidation as new data lands and pruning by the cleaner.
- **Live shortwave radio** — server-side `RadioController` (`rtl_fm` + `lame`),
  per-listening dongle selection with **pause-and-borrow** (the scanner releases
  the chosen dongle live over MQTT and gets it back on stop), and a
  Hallicrafters S-120-inspired face (slide-rule dial with band markers,
  tuning/volume/bandspread/B.F.O. knobs, receive rocker, digital readout,
  S-meter).
- **Smaller fixes** — delete option for gain tests, device names kept in sync
  with scanner aliases, alias-safe MQTT topics (spaces/slashes), stale
  gain-test sweep on reconnect, retention/list fixes.

## Maintenance

This fork is maintained by **Jim Gifford**. Updates are made **both manually and
with AI assistance** - parts of the code, documentation and commit messages are
produced with DevPass Code (an AI coding agent working against this repository),
then reviewed, tested and deployed by a human. AI-assisted changes are not
specially tagged; treat everything here as human-reviewed.

## Upstream credit

All original design and the vast majority of the code are by **shajen**:
<https://github.com/shajen/sdr-monitor> and <https://github.com/shajen/sdr-hub>.
See [CREDITS.md](CREDITS.md).

## Bundled components & provenance

The container image is built on the upstream `shajen/sdr-hub` base and adds:

- **Our scanner fork** - `giffordj/rtl-sdr-scanner-cpp` at a pinned commit
  (upstream `shajen/rtl-sdr-scanner-cpp`), built in the image.
- **librtlsdr** - built from the canonical osmocom repo
  <https://gitea.osmocom.org/sdr/rtl-sdr> at a pinned commit (upstream v2.0.3;
  the GitHub `osmocom/rtl-sdr` repo is a mirror). Soname is kept at 2 so
  SoapyRTLSDR and the `rtl_*` tools keep working.
- **SoapySDR / SoapyRTLSDR** - the Ubuntu 0.8.1 / 0.3.3 packages supplied by
  the base image (upstreams: `pothosware/SoapySDR`, `pothosware/SoapyRTLSDR`).
- **Vendored JS/CSS** - committed in `static/libs/` with checksums in
  `ai/CHECKSUMS.sha256` (Bootstrap 5.3.8, bootstrap-icons 1.13.1, moment
  2.31.0, jQuery 3.7.1, mqtt.js 4.3.7).

All third-party components keep their upstream licenses; see `CREDITS.md`.

## License

GPL-3.0, same as upstream — see [LICENSE](LICENSE).

## Running it

This repository is the **web panel only**. It runs on top of the `sdr-hub`
container image (nginx, supervisord, gnuradio, scanner, mosquitto) by
replacing `/app` — see the pinned `SDR_HUB_IMAGE` in the `Dockerfile`.
Configuration is environment-driven (MQTT broker, database, Authelia SSO);
see `monitor/settings.py`.
