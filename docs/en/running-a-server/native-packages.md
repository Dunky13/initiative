---
icon: lucide/package-open
---

# Native server packages

The `initiative-server` packages run the backend, browser app and document editor
directly on a Linux host or an unprivileged Proxmox LXC. They include the locked
Python dependencies and the matching signed phone/desktop update assets. The
installed server needs no Docker runtime, Node.js, Rust compiler or dependency
download step.

The existing `initiative-<version>.deb` is the **desktop client**. Choose a package
whose name starts with **`initiative-server`** for a headless server.

## Supported targets

- Debian 13, with system Python 3.13 and systemd.
- Alpine 3.24, with system Python 3.14 and OpenRC.
- Each release builds separately for amd64/x86_64 and arm64/aarch64.

The native dependencies are built for each target's Python ABI and libc. A Debian
package cannot be installed on Alpine, and a virtual environment copied between
these distributions is not a supported substitute. Major distribution/Python
upgrades require a matching rebuilt server package.

## Install

Provision a PostgreSQL 17 database first, using the connection requirements in
[Installation](installation.md#the-database-connection). The database can be local
or remote. Package installation does not create database accounts, choose database
passwords or run migrations.

Download the package for your distribution and architecture from the release's
**Native server packages** section. Check it against that release's server package
SHA-256 manifest before installing.

On Debian, install the local `.deb` with `apt install ./<downloaded-package>.deb`.
APT resolves the declared distribution dependencies. The `.deb` and checksum
manifest are release downloads, not an APT repository.

On Alpine, install the release's `initiative-server.rsa.pub` into `/etc/apk/keys/`
before using `apk add ./<downloaded-package>.apk`. Obtain and verify the public key
through a trusted channel before installing it. Keep that trust key for subsequent
upgrades. Do not use `--allow-untrusted`. The server `.apk` is an Alpine package;
the separately named Android APK is a phone application.

The package creates the unprivileged `initiative` account and installs a service,
but **does not start it automatically**. This gives you time to configure a private
server and take a database backup before a package transaction can trigger a
schema migration.

## Configure and start

Edit `/etc/initiative/server.env` as root. Set at least:

```dotenv
DATABASE_URL=postgresql+asyncpg://initiative:PERCENT_ENCODED_PASSWORD@127.0.0.1:5432/initiative
SECRET_KEY=REPLACE_WITH_A_STRONG_UNIQUE_KEY
APP_URL=https://tasks.example.org
```

Use `openssl rand -hex 32` to generate the key. Percent-encode special characters
in a database URL password. Preserve the same `SECRET_KEY` across upgrades: it
protects encrypted data as well as sessions.

The server listens on `127.0.0.1:8173` by default. Put a reverse proxy with trusted
HTTPS and WebSocket support in front of it. Set `BEHIND_PROXY=true` and
`FORWARDED_ALLOW_IPS` to the specific proxy addresses you trust. To serve another
interface, explicitly set `INITIATIVE_HOST`; do not expose an unconfigured server
on a public network.

Public registration is disabled in the package's initial configuration. Supply
`FIRST_OWNER_EMAIL` and `FIRST_OWNER_PASSWORD` to bootstrap the first owner, or
temporarily enable registration while creating your first account privately.
Remove the bootstrap password from the configuration once the owner exists, and
leave public registration disabled for an invite-only instance.

The environment file is configuration data, not a shell script. Write dotenv
assignments; shell commands in it are not executed. See [Configuration](configuration.md)
for the other options and [Single sign-on](single-sign-on.md) for connecting
Authentik or another OIDC provider after the public URL works.

On Debian:

```sh
systemctl enable --now initiative-server
systemctl status initiative-server --no-pager
journalctl -u initiative-server -n 100 --no-pager
```

On Alpine:

```sh
rc-update add initiative-server default
rc-service initiative-server start
rc-service initiative-server status
tail -n 100 /var/log/initiative/server.err
```

Check readiness locally:

```sh
curl --fail http://127.0.0.1:8173/api/v1/readyz
```

The first explicit service start runs Initiative's normal database bootstrap and
migrations. A package transaction itself does not contact the database.

## Files, upgrades and removal

| Location | Purpose |
| --- | --- |
| `/usr/lib/initiative` | Package-owned application, dependencies and release assets |
| `/etc/initiative/server.env` | Operator-owned configuration and secrets |
| `/var/lib/initiative/uploads` | Uploaded files |
| `/var/lib/initiative` | Service home and mutable state |
| `/var/log/initiative` | OpenRC service output; Debian also uses the journal |

Keep local uploads under `/var/lib/initiative`. On Debian, a custom `UPLOADS_DIR`
outside that directory also needs a systemd override granting `ReadWritePaths`
for the chosen directory; grant the `initiative` account access to it as well.

Before upgrading, back up the database, PostgreSQL roles, configuration and uploads
as described in [Backups and updates](backups-and-updates.md). Install the new
package with your distribution's package manager. It stops the running service so
old Python processes do not keep running against replaced files. Configuration
and uploaded files are preserved. Review the release notes, then explicitly start
the service again to apply migrations.

Removing the package stops the service and preserves operator configuration and
state. Debian purge removes packaged configuration, but deliberately preserves
uploaded files, database contents and the service account. Delete those separately
only when you intend to destroy the instance.

Installing an older package does not undo a database migration. Restore the
matching pre-upgrade database backup before starting an older application version
if a newer version changed its schema.

## Building and releasing packages

The recipes and lifecycle tests live in `packaging/server/`. Build browser/editor
and OTA assets with `scripts/build-server-assets.sh`, then run
`packaging/server/build.sh` on the matching target distribution. The
`server-packages.yml` workflow performs those steps and installs, upgrades and
removes the resulting packages in clean target environments on both architectures.
Build-time containers are disposable CI tools; they are not part of the installed
server.

Release builds require the existing `OTA_SIGNING_KEY` in the `ota-release`
environment and an RSA PEM `SERVER_APK_SIGNING_KEY` in that environment for Alpine
package signatures. The matching public key is published with the server packages.
The OTA key must match the release keys trusted by the native applications.
Production package publication fails if either required key is absent. Private
keys remain outside the source tree and are never included in artifacts.

Pull-request builds use disposable test keys and a development channel/version
suffix. Their artifacts exercise packaging; they are not production updates and
must not be substituted for signed release packages.
