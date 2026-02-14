"""Config flow for Twilio integration."""

from __future__ import annotations

import logging
from typing import Any

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    TextSelector,
    NumberSelector,
    NumberSelectorConfig,
)

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    CONF_SENSOR_CLEANUP_HOURS,
    DEFAULT_SENSOR_CLEANUP_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    if CONF_ACCOUNT_SID not in data:
        raise ValueError("Missing account SID")
    if CONF_AUTH_TOKEN not in data:
        raise ValueError("Missing auth token")
    # Test the credentials by creating a client
    try:
        client = Client(data[CONF_ACCOUNT_SID], data[CONF_AUTH_TOKEN])
        # Try to fetch account info to validate credentials
        await hass.async_add_executor_job(
            lambda: client.api.accounts(data[CONF_ACCOUNT_SID]).fetch()
        )
    except TwilioRestException as err:
        _LOGGER.error("Failed to authenticate with Twilio: %s", err)
        raise InvalidAuth from err
    except Exception as err:
        _LOGGER.exception("Unexpected error validating Twilio credentials")
        raise CannotConnect from err

    return {"title": "Twilio"}


class TwilioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Twilio."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TwilioOptionsFlowHandler:
        """Get the options flow for this handler."""
        return TwilioOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_ACCOUNT_SID])
                self._abort_if_unique_id_configured()
                # Generate webhook ID
                webhook_id = webhook.async_generate_id()
                webhook_url = webhook.async_generate_url(self.hass, webhook_id)

                return self.async_create_entry(
                    title=info["title"],
                    data={
                        CONF_ACCOUNT_SID: user_input[CONF_ACCOUNT_SID],
                        CONF_AUTH_TOKEN: user_input[CONF_AUTH_TOKEN],
                        CONF_WEBHOOK_ID: webhook_id,
                    },
                    description_placeholders={"webhook_url": webhook_url},
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_SID): TextSelector(),
                vol.Required(CONF_AUTH_TOKEN): TextSelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_import(
        self, import_config: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Import config from configuration.yaml."""
        return await self.async_step_user(import_config)


class TwilioOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Twilio options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SENSOR_CLEANUP_HOURS,
                        default=self.config_entry.options.get(
                            CONF_SENSOR_CLEANUP_HOURS, DEFAULT_SENSOR_CLEANUP_HOURS
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=1, max=168)),
                }
            ),
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
