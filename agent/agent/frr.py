"""
FRR (FRRouting) daemon management on edge nodes.

Writes the FRR config received from the controller to /etc/frr/frr.conf,
ensures bgpd and bfdd are enabled in the daemons file, then reloads or
starts the FRR service.
"""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

FRR_CONFIG_FILE = "/etc/frr/frr.conf"
FRR_DAEMONS_FILE = "/etc/frr/daemons"

# Daemons we need enabled
_REQUIRED_DAEMONS = {"bgpd": "yes", "bfdd": "yes"}


def is_available() -> bool:
    """Return True if FRR is installed on this system."""
    return Path("/usr/lib/frr/bgpd").exists() or Path("/usr/sbin/bgpd").exists()


def _ensure_daemons() -> None:
    """Make sure bgpd and bfdd are enabled in the FRR daemons file."""
    p = Path(FRR_DAEMONS_FILE)
    if not p.exists():
        logger.warning("FRR daemons file not found at %s — skipping", FRR_DAEMONS_FILE)
        return

    original = p.read_text()
    lines = original.splitlines(keepends=True)
    found: set[str] = set()
    result: list[str] = []

    for line in lines:
        matched = False
        for daemon, value in _REQUIRED_DAEMONS.items():
            if line.startswith(f"{daemon}="):
                result.append(f"{daemon}={value}\n")
                found.add(daemon)
                matched = True
                break
        if not matched:
            result.append(line)

    # Append any daemon lines that were missing entirely
    for daemon, value in _REQUIRED_DAEMONS.items():
        if daemon not in found:
            result.append(f"{daemon}={value}\n")

    updated = "".join(result)
    if updated != original:
        p.write_text(updated)
        logger.info(
            "Updated FRR daemons file (enabled: %s)", ", ".join(_REQUIRED_DAEMONS)
        )


def apply_config(config: str) -> None:
    """Write FRR config and reload (or start) the FRR service.

    This is a no-op if FRR is not installed.
    """
    if not is_available():
        logger.debug("FRR not installed — skipping config apply")
        return

    _ensure_daemons()

    # Atomic write so FRR never reads a half-written file
    p = Path(FRR_CONFIG_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".conf.tmp")
    tmp.write_text(config)
    os.chmod(tmp, 0o640)
    tmp.replace(p)
    logger.info("Wrote FRR config to %s", FRR_CONFIG_FILE)

    # Reload if already running, otherwise enable and start
    try:
        active = subprocess.run(
            ["systemctl", "is-active", "frr"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if active == "active":
            subprocess.run(["systemctl", "reload", "frr"], check=True)
            logger.info("Reloaded FRR daemon")
        else:
            subprocess.run(["systemctl", "enable", "--now", "frr"], check=True)
            logger.info("Started FRR daemon")
    except Exception as exc:
        logger.warning("Could not reload/start FRR: %s", exc)
