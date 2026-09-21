"""Bundle installation logic.

Deliberately free of Home Assistant imports (only the standard library), so it
can be tested without a Home Assistant installation - see
`tests/validate_integration.py`.

The rules are chosen so that a user's local edits are never silently lost:

* nothing installed            -> install the bundled file
* installed, identical         -> do nothing
* installed, older header      -> back up as `<file>.bak` and install
* installed, newer header      -> keep it (the user is ahead of the release)
* installed, same version but different content (local edits) -> keep it
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# the package header carries "#  version 1.5.1  ·  2026-09-20  ·  see CHANGELOG.md"
VERSION_RE = re.compile(r"^#\s*version\s+(\d+\.\d+\.\d+)", re.MULTILINE)
PACKAGES_RE = re.compile(r"^\s*packages\s*:", re.MULTILINE)

# actions reported back to the user
INSTALLED = "installed"
UPDATED = "updated"
CURRENT = "current"
FAILED = "failed"

# the suffix a replaced file is kept under
BACKUP_SUFFIX = ".bak"


@dataclass(frozen=True)
class InstallResult:
    """What happened to one bundled file."""

    action: str
    name: str
    target: str
    version: str | None = None
    installed_version: str | None = None
    backup: str | None = None
    error: str | None = None

    @property
    def changed(self) -> bool:
        """True when the target file was written (a restart is needed then)."""
        return self.action in (INSTALLED, UPDATED)


def read_version(text: str) -> str | None:
    """Return the version from the package header comment, if it has one."""
    match = VERSION_RE.search(text)
    return match.group(1) if match else None


def parse_version(version: str | None) -> tuple[int, ...]:
    """Turn "1.5.10" into (1, 5, 10) so versions compare numerically."""
    if not version:
        return (0,)
    return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)


def packages_configured(configuration_yaml: str) -> bool:
    """True when `configuration.yaml` mentions a `packages:` key.

    A best effort check: the key can live under `homeassistant:` or come from an
    include. When it is missing the integration notifies the user instead of
    guessing - it never edits `configuration.yaml` itself.
    """
    return PACKAGES_RE.search(configuration_yaml) is not None


def install_file(source: Path, target: Path, *, force: bool = False) -> InstallResult:
    """Install/refresh one file. Never raises - problems come back as `FAILED`."""
    name = target.name
    if not source.is_file():
        return InstallResult(FAILED, name, str(target), error=f"bundle file missing: {source}")

    try:
        text = source.read_text(encoding="utf-8")
    except OSError as err:
        return InstallResult(FAILED, name, str(target), error=f"cannot read bundle: {err}")

    version = read_version(text)

    installed = None
    if target.is_file():
        try:
            installed = target.read_text(encoding="utf-8")
        except OSError as err:
            return InstallResult(FAILED, name, str(target), error=f"cannot read target: {err}")

    installed_version = read_version(installed) if installed is not None else None

    if installed is not None and not force:
        if installed == text:
            return InstallResult(CURRENT, name, str(target), version, installed_version)
        if parse_version(installed_version) > parse_version(version):
            # a local file from a newer release - leave it alone
            return InstallResult(CURRENT, name, str(target), version, installed_version)
        if parse_version(installed_version) == parse_version(version):
            # same version, different bytes: the user edited it on purpose
            return InstallResult(CURRENT, name, str(target), version, installed_version)

    backup: Path | None = None
    try:
        if installed is not None:
            backup = target.with_name(target.name + BACKUP_SUFFIX)
            backup.write_text(installed, encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as err:
        return InstallResult(FAILED, name, str(target), version, installed_version, error=str(err))

    return InstallResult(
        UPDATED if installed is not None else INSTALLED,
        name,
        str(target),
        version,
        installed_version,
        str(backup) if backup else None,
    )
