"""Set up the OpenDTU Zero-Export EMS integration.

The EMS itself is a Home Assistant package (one YAML file) - this integration
installs that file (and the ready-made dashboard view) into the configuration
folder, keeps it up to date and reports what it did:

* `<config>/packages/opendtu_ems.yaml` - the package itself
* `<config>/opendtu_ems/ems-overview.yaml` - the everyday Lovelace view
* `<config>/opendtu_ems/ems-expert.yaml` - the diagnostics/tuning Lovelace view

A local file is never overwritten without keeping a `<file>.bak` copy, and a
local file from a newer release is left alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv

from .bundle import (
    AVAILABLE,
    CURRENT,
    FAILED,
    InstallResult,
    install_file,
    packages_configured,
    read_version,
)
from .const import (
    BUNDLE_DASHBOARD,
    BUNDLE_DIR,
    BUNDLE_FILES,
    BUNDLE_PACKAGE,
    CONF_INSTALL,
    DOMAIN,
    NAME,
    NOTIFICATION_PACKAGES,
    NOTIFICATION_RESULT,
    PACKAGES_SNIPPET,
    SERVICE_INSTALL,
    TARGET_DASHBOARD,
    TARGET_PACKAGE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(frozen=True)
class EmsBundleData:
    """What the integration did on the last run - read by the sensor."""

    results: tuple[InstallResult, ...]
    packages_configured: bool | None
    bundle_version: str | None

    @property
    def changed(self) -> bool:
        """True when at least one file was written."""
        return any(result.changed for result in self.results)

    @property
    def failures(self) -> tuple[InstallResult, ...]:
        """The files that could not be handled."""
        return tuple(result for result in self.results if result.action == FAILED)

    @property
    def updates_available(self) -> tuple[InstallResult, ...]:
        """Files where a newer version is bundled but was not written."""
        return tuple(result for result in self.results if result.update_available)

    def result_for(self, name: str) -> InstallResult | None:
        """The result for one target file name."""
        return next((result for result in self.results if result.name == name), None)


TypeData = EmsBundleData


def install_all(
    config_dir: Path, bundle_dir: Path, *, allow_update: bool = False
) -> EmsBundleData:
    """Install every bundled file. Pure filesystem work, run in an executor."""
    package_source = bundle_dir / BUNDLE_PACKAGE
    results = tuple(
        install_file(bundle_dir / source, config_dir / target,
                     allow_update=allow_update)
        for source, target in BUNDLE_FILES
    )

    bundle_version = None
    if package_source.is_file():
        try:
            bundle_version = read_version(package_source.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover - only on a broken installation
            bundle_version = None

    configuration = config_dir / "configuration.yaml"
    configured: bool | None = None
    if configuration.is_file():
        try:
            configured = packages_configured(configuration.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover - permissions
            configured = None

    return EmsBundleData(results=results, packages_configured=configured,
                         bundle_version=bundle_version)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service that re-installs the bundle on demand."""

    async def handle_install_bundle(call: ServiceCall) -> None:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError("The OpenDTU Zero-Export EMS integration is not set up")
        entry = entries[0]
        # explicit request: replace the installed files (a .bak copy is kept)
        await _async_install(hass, entry, allow_update=True)
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_INSTALL, handle_install_bundle)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Install the bundle (unless the user opted out) and report the result.

    Nothing that already exists is written here - an installed package is only
    replaced when the user runs the service, so hand-edited entity ids survive.
    """
    await _async_install(hass, entry, allow_update=False)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the sensor and drop our notifications."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        persistent_notification.async_dismiss(hass, NOTIFICATION_RESULT)
        persistent_notification.async_dismiss(hass, NOTIFICATION_PACKAGES)
    return unloaded


async def _async_install(hass: HomeAssistant, entry: ConfigEntry, *, allow_update: bool) -> None:
    """Run the install (or only the check) and inform the user."""
    config_dir = Path(hass.config.path())
    bundle_dir = Path(__file__).parent / BUNDLE_DIR

    if entry.data.get(CONF_INSTALL, True):
        data = await hass.async_add_executor_job(
            partial(install_all, config_dir, bundle_dir, allow_update=allow_update)
        )
    else:
        # the user manages the files themselves - still report the state
        data = await hass.async_add_executor_job(_check_only, config_dir, bundle_dir)

    entry.runtime_data = data
    _notify(hass, data)


def _check_only(config_dir: Path, bundle_dir: Path) -> EmsBundleData:
    """Report the state without writing anything."""
    package_source = bundle_dir / BUNDLE_PACKAGE
    bundle_version = None
    if package_source.is_file():
        try:
            bundle_version = read_version(package_source.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover
            bundle_version = None

    results = []
    for source, target in BUNDLE_FILES:
        path = config_dir / target
        version = None
        if path.is_file():
            try:
                version = read_version(path.read_text(encoding="utf-8"))
            except OSError:  # pragma: no cover
                version = None
        results.append(
            InstallResult(CURRENT, Path(target).name, str(path), bundle_version, version)
        )

    configuration = config_dir / "configuration.yaml"
    configured: bool | None = None
    if configuration.is_file():
        try:
            configured = packages_configured(configuration.read_text(encoding="utf-8"))
        except OSError:  # pragma: no cover
            configured = None

    return EmsBundleData(results=tuple(results), packages_configured=configured,
                         bundle_version=bundle_version)


@callback
def _notify(hass: HomeAssistant, data: EmsBundleData) -> None:
    """Tell the user what happened - but only when there is something to tell.

    A restart that finds every file in place stays silent: the state is always
    visible in `sensor.ems_bundle`, and a "nothing to do" notice on every start
    only trains people to ignore the notification area.
    """
    lines: list[str] = []

    if data.failures:
        for failure in data.failures:
            lines.append(f"**{failure.name}** could not be handled: {failure.error}")
    installed = [r for r in data.results if r.changed]
    available = data.updates_available
    if installed:
        for result in installed:
            if result.action == "updated":
                lines.append(
                    f"**{result.name}** updated from {result.installed_version} "
                    f"to {result.version} (backup: `{result.backup}`)"
                )
            else:
                lines.append(f"**{result.name}** installed (version {result.version})")
        lines.append("")
        lines.append(
            "**Restart Home Assistant** (Settings → System → Restart) to create the entities. "
            f"The package is at `{TARGET_PACKAGE}`, the dashboard view at `{TARGET_DASHBOARD}`."
        )
    elif available and not data.failures:
        for result in available:
            lines.append(
                f"A newer **{result.name}** is bundled ({result.version}, you have "
                f"{result.installed_version}). **Nothing was written** - the installed file can "
                "contain your own entity ids."
            )
        lines.append("")
        lines.append(
            "To update: Developer tools → Actions → `opendtu_ems.install_bundle` (the current "
            "file is kept as `.bak`), then **restart Home Assistant**. Compare the two files "
            "first if you edited section 1."
        )
    # A restart that finds everything in place is the normal case and is NOT
    # reported (see the docstring). A leftover result notification is dismissed
    # below instead of being replaced by a "nothing to do" message.

    if data.packages_configured is False:
        lines.append("")
        lines.append(
            "**One line is missing in `configuration.yaml`** - the package is only read when "
            "the packages folder is included:"
        )
        lines.append("")
        lines.append("```yaml")
        lines.append(PACKAGES_SNIPPET)
        lines.append("```")

    if lines:
        persistent_notification.async_create(
            hass, "\n".join(lines), title=NAME, notification_id=NOTIFICATION_RESULT
        )
    else:
        # nothing to report - also clear a notice an earlier run may have left
        persistent_notification.async_dismiss(hass, NOTIFICATION_RESULT)

    if data.packages_configured is False:
        persistent_notification.async_create(
            hass,
            "The EMS package is not loaded until `configuration.yaml` contains:\n\n"
            f"```yaml\n{PACKAGES_SNIPPET}\n```\n\n"
            "If your `packages:` are pulled in from another file, ignore this message.",
            title=f"{NAME}: packages not configured",
            notification_id=NOTIFICATION_PACKAGES,
        )
    else:
        persistent_notification.async_dismiss(hass, NOTIFICATION_PACKAGES)
