# Changelog — changes vs upstream (shajen/sdr-monitor)

All changes by Jim Gifford. Newest first.

Updates to this fork are made **manually and with AI assistance**
(DevPass Code); every change is reviewed, tested and deployed by a human.


## 2026-10-18
- ui(radio): replace the S-120 knobs and the receive rocker with digital controls - volume slider, fine-tune input with +/- buttons, Receive/Standby buttons, and explicit Scanner on/Scanner off buttons
- ui(radio): default volume is 40% (also the knob double-click reset)
- ui(config): scanner and SDR-device selection as tabs in the settings format instead of radio dots (first device selected automatically)
- feat(radio): Listen on a transmission tunes the radio to its frequency/mode and receiving dongle, stops the scanner first, then starts the receiver

## 2026-10-17
- build(deps): build upstream librtlsdr 2.0.3, SoapySDR 0.9.0 and SoapyRTLSDR 0.3.4 from source (distro packages were stale); scanner rebuilt against SoapySDR 0.9
- fix(drawer): spectrogram power legend labels the min/max and tightens the step for narrow ranges (HF rows no longer show a single number)
- fix(drawer): pad and vertically clamp spectrogram time labels, add a blank bottom margin (no more cut-off look) and a dB unit on the power legend; short rows now keep their timing (scaled font, first sample always labelled) and every data row is written
- build(deps): refresh and pin vendored static libs (Bootstrap 5.3.8 bundle+css, icons 1.13.1, moment 2.31.0), drop duplicate bootstrap.js and unused flag-icons; add requirements.lock, yamnet checksums, digest-pinned base image, CI asset check
- fix(radio): B.F.O. knob must not cycle modes while being dragged (click-only control)
- feat(radio): dongle selector (SDR_RADIO_DEVICES) + always-available scanner on/off button; per-device rtl index, borrow serial and HF handling
- ui(sdr): Hallicrafters S-120 inspired radio face - slide-rule dial with HF band rows and markers, functional knobs (tuning/volume/bandspread/BFO), receive rocker, digital readout core
- perf(sdr): cache scanner status (worker-refreshed) and rendered spectrogram images; show cache age on the status page
- ui(sdr): identify scanners by their devices (status page, config selector, gain tester); keep raw id as secondary
- docs: Blog V4 HF needs a real HF antenna (short whips give noise-only spectra)

## 2026-10-16
- fix(sdr): keep Device.name in sync with the scanner alias (panel device list now matches the scanner config)
- docs: verify the image carries the pushed change before recreating (CI lag deployed a stale build once)
- fix(sdr): liveness and list order by end_real_date (rows are daily streams; begin_real_date is the day start)
- feat(sdr): scanning status page - per-device liveness (scanner state + ingest ages) in the app's standard layout
- feat(sdr): delete option for gain tests (list + detail)
- ui(sdr): warn when a device alias contains spaces or slashes

## 2026-10-15
- docs: ingest quirks - alias-based device topics, source relabel, gain-test sweep
- fix: read aliases with spaces/slashes; align row lookup with the unique index
- fix: stop the scanner's hard-coded source label hiding data; auto-unwedge stale gain tests

## 2026-10-10
- rebrand: SDR Monitor (was jg555 SDR) in UI, docs and comments
- ui: show device alias in the SDR device selector label
- feat(radio): pause-and-borrow mode — radio disables its dongle in the scanner live (MQTT), re-enables after; scanner keeps scanning
- docs: dual-dongle setup (NESDR scanner + Blog V4 radio), antenna notes
- feat(radio): dual-dongle support — pin device, skip direct sampling on HF upconverter dongles, keep scanner running

## 2026-10-08
- ci: add hadolint Dockerfile lint step (fail on errors, warn on DL3008)

## 2026-10-04
- feat(settings): move auto-delete noise into the Retention menu
- feat(settings): dedicated 'Keep rules' config menu (per-class retention)
- feat(settings): per-class keep rules for transmissions
- docs: RADIO.md delivered status + AGENTS CI/radio notes

## 2026-10-03
- feat(radio): AM(MW)/shortwave bands + HF direct sampling; nginx stream fix
- fix(radio): reap rtl_fm/lame after terminate (zombie leak)
- fix(radio): broadcast FM was silent (wbfm + rates + auto gain); Hz/kHz/MHz entry
- feat(radio): scanner on/off switch + manual frequency entry
- feat(radio): Phase 3 - Radio page/tab with shortwave UI
- fix(radio): module logger was name-mangled inside the class
- feat(radio): server-side live receiver controller + API
- fix(radio): put supervisord control socket in the writable /var/run/sdr
- build(radio): add rtl-sdr/sox/lame and a supervisord control socket
- brand: present as jg555 SDR and credit the original author
- ui(sdr): split config into Scanner settings / SDR device settings tabs
- feat(sdr): server-side scanner config API; drop MQTT from the config UI
- feat(sdr): auto-delete transmissions classified as noise

## 2026-09-30
- ci: use aquasec/trivy image
- ci: fix syft output flag
- ci: add syft SBOM + trivy scan

## 2026-09-29
- docs: allow esphome + ai_scripts in scope; tools/nautobot/vmserver-tools/repo off limits
- docs: scope repo boundaries (docker/sdr-monitor/sdr-hub only)
- ci: t3
- ci: docker job with mounted socket
- ci: host build without checkout
- ci: build sdr-monitor on the host runner
- ci: retrigger build (socket mount)
- ci: build + push sdr-monitor image to registry on push

## 2026-09-28
- docs: deployment uses a read-only SSH deploy key, not an embedded password

## 2026-09-27
- docs: running instance migrated to a dedicated SDR host

## 2026-09-25
- docs: note pi3b deploy-auth limitation and scanner id regeneration

## 2026-09-24
- docs: add AGENTS.md operating directives
- build: override logrotate to cap log growth
- feat(sdr): warn before saving an oversized scanner config

## 2026-09-22
- chore(scripts): drop supervisorctl calls (no supervisor socket in the image)
- build: pin base image to shajen/sdr-hub:2.2.2
- chore: add scripts/deploy.sh and scripts/doctor.sh
- fix(sdr): dropdown value fills its filter input
- fix(sdr): valid filter form so filtering works

## 2026-09-21
- chore: untrack runtime data and gate home page
- chore(sdr): cleanup from review
- ui(sdr): add Back / list links to detail pages; tidy transmission details
- feat(sdr): dashboard home page (BrowSDR-inspired)
- feat(sdr): show scanner config frequencies/bandwidth in MHz
- fix(sdr): clear 'no scanner' hint once scanner data arrives; 15s timeout
- feat(sdr): single natural-language numeric filters
- ui(sdr): natural filter placeholders; don't hang on SDR settings
- ui(sdr): shared visual refresh (inline, no collectstatic)
- feat(sdr): inline group editing + more modulation choices
- refactor(sdr): per-field filter handling, 404 on unknown data format
- chore(sdr): harden views/filters, POST group actions, untrack bytecode
- ui(sdr): put transmissions delete-class/all controls next to Columns
- ui(sdr): move transmissions delete-class/all controls into a toolbar above the table
- feat(sdr): AUTHELIA_ALL_STAFF fallback + log authelia groups
- Merge branch 'main' of the private repository
- Updates
- fix(sdr): hide section-title decorative watermark in all themes
- fix(sdr): don't force section-title watermark span opaque in dark mode
- build: use shajen/sdr-hub base and inherit entrypoint
- Revert "revert(sdr): remove dark mode toggle"
- revert(sdr): remove dark mode toggle
- feat(sdr): spectrogram retention control on the spectrograms page + dark mode
- fix(sdr): inline column toggle (nginx serves only collected static); add spectrogram keep-count retention
- feat(sdr): column toggles, mass-delete in Action column, spectrogram page size
- Updated with Delete Parameters
- fix(sdr): only create Default group when no groups exist
- feat(sdr): accept group frequencies in MHz and harden group add/delete
- build: add overlay Dockerfile and dockerignore
- fix(sdr): restore default group fallback and add authelia forward-auth

## 2026-09-20
- chore: baseline extraction from sdr-hub container
