"""Validate native service configuration, then launch uvicorn without a shell."""

import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path("/usr/lib/initiative")
ENV_FILE = Path("/etc/initiative/server.env")

#: The proxies trusted to name a request's client when FORWARDED_ALLOW_IPS is
#: unset: this machine, its container networks and the LAN. The same list as
#: the image's start.sh.
LOCAL_NETWORKS = (
    "127.0.0.0/8,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,"
    "169.254.0.0/16,fc00::/7,fe80::/10"
)


def command(config: dict[str, str | None]) -> list[str]:
    """Translate explicitly supported listener settings to uvicorn arguments."""
    for name in ("SECRET_KEY", "DATABASE_URL", "APP_URL"):
        if not config.get(name):
            raise ValueError(f"Set {name} in {ENV_FILE} before starting Initiative")
    host = config.get("INITIATIVE_HOST") or "127.0.0.1"
    port = int(config.get("INITIATIVE_PORT") or "8173")
    if not 1 <= port <= 65535:
        raise ValueError("INITIATIVE_PORT must be between 1 and 65535")
    proxy = config.get("BEHIND_PROXY", "false")
    if proxy not in ("true", "false"):
        raise ValueError("BEHIND_PROXY must be true or false")
    args = [
        str(ROOT / ".venv/bin/python"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--env-file",
        str(ENV_FILE),
        "--host",
        host,
        "--port",
        str(port),
        "--proxy-headers" if proxy == "true" else "--no-proxy-headers",
        "--forwarded-allow-ips",
        config.get("FORWARDED_ALLOW_IPS") or LOCAL_NETWORKS,
    ]
    return args


def main() -> None:
    if os.geteuid() == 0:
        raise SystemExit("Run Initiative as the initiative service user")
    try:
        # Parse dotenv, never execute shell commands from the configuration file.
        config = {**dotenv_values(ENV_FILE), **os.environ}
        args = command(config)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    os.chdir(ROOT)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ.setdefault("HOME", "/var/lib/initiative")
    # mini-racer's musllinux wheel requires Alpine's glibc compatibility shim;
    # editor subprocesses must inherit this too.
    if (ROOT / "ALPINE_RUNTIME").exists():
        os.environ["LD_PRELOAD"] = "/lib/libgcompat.so.0"
    os.execv(args[0], args)


if __name__ == "__main__":
    main()
