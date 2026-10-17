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

# The running supervisord uses /etc/supervisor/conf.d/supervisord.conf directly,
# which has no control socket, so supervisorctl could not stop/start the scanner.
# The radio borrows the (single) RTL-SDR from the scanner, so it must be able to
# stop sdr_scanner while listening and start it again afterwards.
RUN printf '\n[unix_http_server]\nfile=/var/run/sdr/supervisor.sock\nchmod=0700\n\n[rpcinterface:supervisor]\nsupervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface\n\n[supervisorctl]\nserverurl=unix:///var/run/sdr/supervisor.sock\n' >> /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000
