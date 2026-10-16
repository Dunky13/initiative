#!/bin/sh
set -e

# Resolve uvicorn/alembic/python from the uv-managed venv even if the runtime
# overrode the image's ENV PATH (e.g. Synology re-applying a stale container env).
export PATH="/app/.venv/bin:$PATH"

ARGS="app.main:app --host 0.0.0.0 --port 8173"

if [ "${BEHIND_PROXY:-false}" = "true" ]; then
    # The loopback, private and link-local ranges: a proxy on this host, its
    # container network or the LAN. A proxy anywhere else is named in
    # FORWARDED_ALLOW_IPS.
    FORWARDED_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.0/8,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,fc00::/7,fe80::/10}"
    ARGS="$ARGS --proxy-headers --forwarded-allow-ips=$FORWARDED_IPS"
fi

# shellcheck disable=SC2086
exec uvicorn $ARGS
