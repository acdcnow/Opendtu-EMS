"""Set up the OpenDTU Zero-Export EMS integration.

The EMS itself is a Home Assistant package (one YAML file) - this integration
installs that file (and the ready-made dashboard view) into the configuration
folder, keeps it up to date and reports what it did:

* `<config>/packages/opendtu_ems.yaml` - the package itself
* `<config>/opendtu_ems/ems-overview.yaml` - the Lovelace view

A local file is never overwritten without keeping a `<file>.bak` copy, and a
local file from a newer release is left alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv

from .bundle import (
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

    def result_for(self, name: str) -> InstallResult | None:
        """The result for one target file name."""
        return next((result for result in self.results if result.name == name), None)


TypeData = EmsBundleData


def install_all(config_dir: Path, bundle_dir: Path, *, force: bool = False) -> EmsBundleData:
    """Install both bundled files. Pure filesystem work, run in an executor."""
    package_source = bundle_dir / BUNDLE_PACKAGE
    results = (
        install_file(package_source, config_dir / TARGET_PACKAGE, force=force),
        install_file(bundle_dir / BUNDLE_DASHBOARD, config_dir / TARGET_DASHBOARD, force=force),
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
        await _async_install(hass, entry, force=True)
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_INSTALL, handle_install_bundle)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Install the bundle (unless the user opted out) and report the result."""
    await _async_install(hass, entry, force=False)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the sensor and drop our notifications."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        persistent_notification.async_dismiss(hass, NOTIFICATION_RESULT)
        persistent_notification.async_dismiss(hass, NOTIFICATION_PACKAGES)
    return unloaded


async def _async_install(hass: HomeAssistant, entry: ConfigEntry, *, force: bool) -> None:
    """Run the install (or only the check) and inform the user."""
    config_dir = Path(hass.config.path())
    bundle_dir = Path(__file__).parent / BUNDLE_DIR

    if entry.data.get(CONF_INSTALL, True):
        data = await hass.async_add_executor_job(install_all, config_dir, bundle_dir, force)
    else:
        # the user manages the files themselves - still report the state
        results = await hass.async_add_executor_job(
            _check_only, config_dir, bundle_dir
        )
        data = results

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
    for source, target in ((BUNDLE_PACKAGE, TARGET_PACKAGE),
                           (BUNDLE_DASHBOARD, TARGET_DASHBOARD)):
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
    """Tell the user what happened - the entities only exist after a restart."""
    lines: list[str] = []

    if data.failures:
        for failure in data.failures:
            lines.append(f"**{failure.name}** could not be handled: {failure.error}")
    installed = [r for r in data.results if r.changed]
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
    elif not data.failures:
        package = data.result_for("opendtu_ems.yaml")
        lines.append(
            f"Nothing to do - the installed package is current "
            f"({package.installed_version if package else '-'}) and was not touched."
        )

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
