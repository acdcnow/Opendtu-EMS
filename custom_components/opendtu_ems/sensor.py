"""Sensor that reports the installed EMS bundle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EmsBundleData
from .const import BUNDLE_PACKAGE, DOMAIN, TARGET_DASHBOARD, TARGET_PACKAGE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[EmsBundleData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the single bundle sensor."""
    async_add_entities([EmsBundleSensor(entry)])


class EmsBundleSensor(SensorEntity):
    """Version of the bundled package plus what the integration did."""

    _attr_should_poll = False
    _attr_name = "EMS bundle"
    _attr_icon = "mdi:package-variant-closed-check"

    def __init__(self, entry: ConfigEntry[EmsBundleData]) -> None:
        """Remember the entry - its runtime_data is the report."""
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_bundle"

    @property
    def native_value(self) -> str | None:
        """The version of the bundled package."""
        return self._entry.runtime_data.bundle_version

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What was installed, where, and whether a restart is pending."""
        data = self._entry.runtime_data
        package = data.result_for(BUNDLE_PACKAGE)
        return {
            "package": TARGET_PACKAGE,
            "package_version": package.installed_version if package else None,
            "package_action": package.action if package else None,
            "dashboard": TARGET_DASHBOARD,
            "packages_configured": data.packages_configured,
            "restart_required": data.changed,
            "update_available": bool(data.updates_available),
        }
