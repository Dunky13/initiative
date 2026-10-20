#!/bin/sh
set -e

# Ensure the uv-managed virtualenv is on PATH even when the runtime re-applies a
# stale PATH captured from a previous image (e.g. Synology Container Manager
# persists the old container's env on upgrade, clobbering the image's ENV PATH).
export PATH="/app/.venv/bin:$PATH"

# Two ways to start, like the database's one owner URL and its three named
# logins (docs/en/running-a-server/installation.md):
#
# * As root, the default. It creates the PUID/PGID user, makes /app/uploads
#   theirs and drops to them before anything else runs, so a bind-mounted
#   folder works without the operator touching its ownership.
# * As a non-root user the runtime chose (a Kubernetes runAsUser, Docker's
#   `--user`), for a deployment that must never start as root. Only root
#   could switch to anyone else, so there is no user to create and nothing to
#   chown; PUID and PGID do not apply, and /app/uploads must already be
#   writable by that user (a Kubernetes fsGroup, or a folder they own).
#
# Either way it says which, once, at the top of the log.
if [ "$(id -u)" -ne 0 ]; then
    echo "container user: $(id -u):$(id -g) from the start (no PUID/PGID, no chown)" >&2
    if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
        echo "container user: PUID/PGID are set and ignored: only a container started as root can switch user" >&2
    fi
    exec "$@"
fi

# Default to UID/GID 1000 if not specified
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

# Validate PUID/PGID are positive integers and not root
case "$APP_UID" in
  ''|*[!0-9]*) echo "ERROR: PUID must be a positive integer, got: '$APP_UID'" >&2; exit 1 ;;
esac
case "$APP_GID" in
  ''|*[!0-9]*) echo "ERROR: PGID must be a positive integer, got: '$APP_GID'" >&2; exit 1 ;;
esac
if [ "$APP_UID" -eq 0 ] || [ "$APP_GID" -eq 0 ]; then
  echo "ERROR: PUID and PGID must not be 0 (root)" >&2; exit 1
fi

# Create group with requested GID (skip if GID already exists).
# Not --system: the default GID 1000 is outside the system range (<=999), which
# makes a strict adduser/useradd refuse it ("gid 1000 is greater than SYS_GID_MAX").
if ! getent group "$APP_GID" >/dev/null 2>&1; then
    addgroup --gid "$APP_GID" app
fi

# Create user with requested UID (skip if UID already exists). See the group note
# above re: --system. --disabled-password/--gecos keep adduser non-interactive.
if ! getent passwd "$APP_UID" >/dev/null 2>&1; then
    # Resolve the group name for the target GID
    APP_GROUP=$(getent group "$APP_GID" | cut -d: -f1)
    adduser --uid "$APP_UID" --ingroup "$APP_GROUP" --no-create-home \
        --disabled-password --gecos "" app
fi

# Ensure uploads directory is writable
chown -R "$APP_UID:$APP_GID" /app/uploads

# Run the command as the requested UID (numeric avoids name-resolution issues)
echo "container user: root at start, then $APP_UID:$APP_GID (PUID/PGID)" >&2
exec gosu "$APP_UID:$APP_GID" "$@"
