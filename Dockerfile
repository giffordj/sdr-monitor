# Overlay image: reuse the prebuilt upstream sdr-hub image (nginx, supervisord,
# gnuradio, vendored static libs) and replace only the application source in /app.
#
# NOTE: build from shajen/sdr-hub, NOT shajen/sdr-monitor. The sdr-monitor image
# has no nginx/supervisord and a different entrypoint, so the container would
# start nothing and Traefik returns "bad gateway". The base entrypoint/CMD is
# inherited on purpose (do not override ENTRYPOINT, that also clears CMD).
# Digest pinned 2026-10-17 (linux/amd64 manifest). The base ships gnuradio,
# nginx, supervisord, mosquitto, librtlsdr/SoapyRTLSDR and the scanner binary.
ARG SDR_HUB_IMAGE=shajen/sdr-hub:2.2.2@sha256:3c3d19559631a37dc5a99142e92702a23a6864a997305706e632214763cae54b
# ---- SoapySDR + SoapyRTLSDR (current upstream) ------------------------------
# Distros hold back: noble ships SoapySDR 0.8.1 / SoapyRTLSDR 0.3.3. Build the
# current upstream releases from source (SoapySDR 0.9.0, SoapyRTLSDR 0.3.4 with
# the uninitialised-tunerGain fix). The ABI bump 0.8 -> 0.9 moves the soname
# (libSoapySDR.so.0.9) and the module directory (modules0.9), so the scanner is
# rebuilt against this stage instead of the distro 0.8 headers.
FROM ${SDR_HUB_IMAGE} AS soapy-builder
USER root
ARG SOAPYSDR_REPO=https://github.com/pothosware/SoapySDR.git
ARG SOAPYSDR_COMMIT=8b0970debaec4cb206ba76d0a2ef986feaf39534
ARG SOAPYRTLSDR_REPO=https://github.com/pothosware/SoapyRTLSDR.git
ARG SOAPYRTLSDR_COMMIT=5b544e3d3a7ae97952742f42f8bb110fe62c3cd8
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config git ca-certificates \
        libusb-1.0-0-dev librtlsdr-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone "${SOAPYSDR_REPO}" /soapy && \
    cd /soapy && git checkout "${SOAPYSDR_COMMIT}" && \
    cmake -S /soapy -B /soapy/build -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_INSTALL_PREFIX=/usr/local && \
    cmake --build /soapy/build -j"$(nproc)" && \
    cmake --install /soapy/build && ldconfig
RUN git clone "${SOAPYRTLSDR_REPO}" /soapyrtlsdr && \
    cd /soapyrtlsdr && git checkout "${SOAPYRTLSDR_COMMIT}" && \
    cmake -S /soapyrtlsdr -B /soapyrtlsdr/build -DCMAKE_BUILD_TYPE=Release \
          -DCMAKE_PREFIX_PATH=/usr/local && \
    cmake --build /soapyrtlsdr/build -j"$(nproc)" && \
    cmake --install /soapyrtlsdr/build

# ---- patched scanner -------------------------------------------------------
# Build our scanner fork (public, GPLv3) at a pinned commit and replace the
# base image's binary. The fork carries the recorder flush fix (missing/0 ms
# recordings), honest "scanner" source labels and a range-processor cap - see
# https://github.com/giffordj/rtl-sdr-scanner-cpp (credits in its README).
# The builder uses the SAME base image so GNU Radio link versions match the
# runtime exactly, and links the SoapySDR 0.9 from soapy-builder.
FROM ${SDR_HUB_IMAGE} AS scanner-builder
USER root
ARG SCANNER_REPO=https://github.com/giffordj/rtl-sdr-scanner-cpp.git
ARG SCANNER_COMMIT=8097cec228ef880165b3a41b5e062ccc399f052e
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
        libboost-dev libspdlog-dev nlohmann-json3-dev libpaho-mqttpp-dev \
        libpaho-mqtt-dev libcli11-dev libsoapysdr-dev gnuradio-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=soapy-builder /usr/local /usr/local
RUN ldconfig && \
    git clone "${SCANNER_REPO}" /src && \
    cd /src && git checkout "${SCANNER_COMMIT}" && \
    cmake -S /src -B /src/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/usr/local && \
    cmake --build /src/build --target auto_sdr -j"$(nproc)" && \
    ldd /src/build/auto_sdr | grep -q "libSoapySDR.so.0.9"

# ---- librtlsdr (canonical osmocom) -----------------------------------------
# Build upstream rtl-sdr v2.0.3 from the canonical repo
# (https://gitea.osmocom.org/sdr/rtl-sdr - the GitHub osmocom/rtl-sdr repo is a
# mirror) instead of Ubuntu's 2.0.1. It brings the USB-transfer-error hang fix
# (device-loss detection in the async loop), the r82xx retune speed/precision
# series and V4 Lite support. Upstream 2.0.2+ sets SOVERSION 0; patch it back
# to 2 so SoapyRTLSDR and the distro rtl-sdr tools keep resolving .so.2.
FROM ${SDR_HUB_IMAGE} AS rtlsdr-builder
USER root
ARG RTLSDR_REPO=https://gitea.osmocom.org/sdr/rtl-sdr
ARG RTLSDR_COMMIT=797f8143266d983c56d8f35d2d442527529dd8a5
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config libusb-1.0-0-dev git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone "${RTLSDR_REPO}" /src && \
    cd /src && git checkout "${RTLSDR_COMMIT}" && \
    sed -i 's/SOVERSION 0/SOVERSION 2/' src/CMakeLists.txt && \
    cmake -S /src -B /src/build -DCMAKE_BUILD_TYPE=Release -DINSTALL_UDEV_RULES=OFF && \
    cmake --build /src/build -j"$(nproc)"

FROM ${SDR_HUB_IMAGE}

WORKDIR /app
COPY . /app/
# Tighter log rotation than the base image (see config/logrotate.conf): caps
# growth when a program crash-loops and floods /var/log/sdr/.
COPY config/logrotate.conf /etc/logrotate.d/sdr.conf
# The live-radio MP3 stream must not be buffered by nginx, and the long-lived
# response needs a long read timeout. Set both in the http block.
RUN sed -i 's/^http {/http {\n\tproxy_buffering off;\n\tproxy_read_timeout 3600s;\n\tproxy_send_timeout 3600s;/' /etc/nginx/nginx.conf && \
    grep -q proxy_buffering /etc/nginx/nginx.conf
# Drop any bytecode shipped in the base image so Python recompiles from the
# source above (avoids stale .pyc shadowing the updated code).
RUN find /app -type d -name __pycache__ -prune -exec rm -rf {} + && \
    chown -R ubuntu:ubuntu /app/

# Live radio ("SDR Monitor" shortwave receiver): the base image ships librtlsdr and
# SoapySDR but no RTL command-line tools. Add rtl_fm (demod), sox (resampling)
# and lame (MP3 streaming) so the in-panel radio can tune and stream audio.
RUN apt-get update && \
    apt-get install -y --no-install-recommends rtl-sdr sox lame && \
    rm -rf /var/lib/apt/lists/*

# Current upstream SoapySDR 0.9.0 + SoapyRTLSDR 0.3.4 from the soapy-builder
# stage (the distro 0.8.1/0.3.3 are only kept for the base image's unused GNU
# Radio/other modules). The scanner links 0.9; rtl_fm does not use SoapySDR.
COPY --from=soapy-builder /usr/local /usr/local

# The running supervisord uses /etc/supervisor/conf.d/supervisord.conf directly,
# which has no control socket, so supervisorctl could not stop/start the scanner.
# The radio borrows the (single) RTL-SDR from the scanner, so it must be able to
# stop sdr_scanner while listening and start it again afterwards.
RUN printf '\n[unix_http_server]\nfile=/var/run/sdr/supervisor.sock\nchmod=0700\n\n[rpcinterface:supervisor]\nsupervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface\n\n[supervisorctl]\nserverurl=unix:///var/run/sdr/supervisor.sock\n' >> /etc/supervisor/conf.d/supervisord.conf

# Replace the scanner binary with our patched build (recorder flush fix,
# honest source labels, range-processor cap).
COPY --from=scanner-builder /src/build/auto_sdr /usr/bin/auto_sdr
RUN chmod 0755 /usr/bin/auto_sdr

# Replace the distro librtlsdr (2.0.1) with the pinned upstream build (2.0.3)
# and use its rtl_* tools (the rtl_fm USB-error handling lives in the tool as
# well as the library). /usr/local/lib wins via ldconfig; the guard fails the
# build if SoapyRTLSDR would still resolve the distro library.
COPY --from=rtlsdr-builder /src/build/src/librtlsdr.so.2.0.3 /usr/local/lib/librtlsdr.so.2.0.3
COPY --from=rtlsdr-builder /src/build/src/rtl_fm /usr/local/bin/rtl_fm
COPY --from=rtlsdr-builder /src/build/src/rtl_power /usr/local/bin/rtl_power
COPY --from=rtlsdr-builder /src/build/src/rtl_sdr /usr/local/bin/rtl_sdr
COPY --from=rtlsdr-builder /src/build/src/rtl_test /usr/local/bin/rtl_test
RUN ln -sf librtlsdr.so.2.0.3 /usr/local/lib/librtlsdr.so.2 && \
    printf '/usr/local/lib\n' > /etc/ld.so.conf.d/rtlsdr.conf && \
    chmod 0755 /usr/local/bin/rtl_fm /usr/local/bin/rtl_power /usr/local/bin/rtl_sdr /usr/local/bin/rtl_test && \
    ldconfig && \
    test -f /usr/local/lib/SoapySDR/modules0.9/librtlsdrSupport.so && \
    ldd /usr/local/lib/SoapySDR/modules0.9/librtlsdrSupport.so | grep -q 'libSoapySDR.so.0.9' && \
    ldd /usr/local/lib/SoapySDR/modules0.9/librtlsdrSupport.so | grep -q '/usr/local/lib/librtlsdr.so.2' && \
    ldd /usr/bin/auto_sdr | grep -q 'libSoapySDR.so.0.9' && \
    grep -aq 'Blog V4 Lite' /usr/local/lib/librtlsdr.so.2.0.3

EXPOSE 8000
