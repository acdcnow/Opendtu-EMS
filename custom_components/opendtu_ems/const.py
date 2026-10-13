"""Constants for the OpenDTU Zero-Export EMS integration.

The integration is deliberately small: the EMS itself is a Home Assistant
*package* (one YAML file), which this integration installs and keeps up to date.
The control law, the learning and the watchdog stay in that file, so there is
exactly one implementation - see the README and the wiki.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "opendtu_ems"
NAME: Final = "OpenDTU Zero-Export EMS"

# files shipped inside the integration (custom_components/opendtu_ems/bundle/)
BUNDLE_DIR: Final = "bundle"
BUNDLE_PACKAGE: Final = "opendtu_ems.yaml"
BUNDLE_DASHBOARD: Final = "ems-overview.yaml"
BUNDLE_DASHBOARD_EXPERT: Final = "ems-expert.yaml"
BUNDLE_BLUEPRINT: Final = "ems_map_sensors.yaml"

# where they are installed, relative to the Home Assistant config directory
TARGET_PACKAGE: Final = "packages/opendtu_ems.yaml"
TARGET_DASHBOARD: Final = "opendtu_ems/ems-overview.yaml"
TARGET_DASHBOARD_EXPERT: Final = "opendtu_ems/ems-expert.yaml"
TARGET_BLUEPRINT: Final = "blueprints/script/opendtu_ems/ems_map_sensors.yaml"

# every bundled file and its target, in the order they are installed
BUNDLE_FILES: Final = (
    (BUNDLE_PACKAGE, TARGET_PACKAGE),
    (BUNDLE_DASHBOARD, TARGET_DASHBOARD),
    (BUNDLE_DASHBOARD_EXPERT, TARGET_DASHBOARD_EXPERT),
    (BUNDLE_BLUEPRINT, TARGET_BLUEPRINT),
)

# configuration keys
CONF_INSTALL: Final = "install"

# persistent notifications
NOTIFICATION_RESULT: Final = "opendtu_ems_bundle"
NOTIFICATION_PACKAGES: Final = "opendtu_ems_packages"

# services
SERVICE_INSTALL: Final = "install_bundle"

# the section a user has to add to configuration.yaml, once
PACKAGES_SNIPPET: Final = "homeassistant:\n  packages: !include_dir_named packages"
