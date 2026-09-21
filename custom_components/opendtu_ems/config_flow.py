"""Config flow for the OpenDTU Zero-Export EMS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_INSTALL, DOMAIN, NAME, PACKAGES_SNIPPET, TARGET_DASHBOARD, TARGET_PACKAGE


class OpenDtuEmsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask once whether the YAML package should be placed in the config folder."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the single setup step."""
        # one installation is enough - the package is a singleton
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INSTALL, default=True): bool,
                }
            ),
            description_placeholders={
                "package": TARGET_PACKAGE,
                "dashboard": TARGET_DASHBOARD,
                "snippet": PACKAGES_SNIPPET,
            },
        )
