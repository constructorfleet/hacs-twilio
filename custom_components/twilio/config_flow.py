"""Config flow for Twilio integration."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    SelectOptionDict,
    TextSelector,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    CONF_FROM_NUMBER,
    CONF_PHONE_NUMBERS,
    CONF_SENSOR_CLEANUP_HOURS,
    DEFAULT_SENSOR_CLEANUP_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _async_get_incoming_phone_numbers(
    hass: HomeAssistant, account_sid: str, auth_token: str
) -> list[str]:
    """Fetch incoming Twilio phone numbers for an account."""
    client = Client(account_sid, auth_token)
    numbers = await hass.async_add_executor_job(
        lambda: client.incoming_phone_numbers.list(limit=1000)
    )
    return sorted(
        {
            str(number.phone_number).strip()
            for number in numbers
            if getattr(number, "phone_number", None)
        }
    )


def _normalize_selected_numbers(value: Any) -> list[str]:
    """Normalize selected phone numbers from flow input."""
    if not isinstance(value, list):
        return []
    return [str(number).strip() for number in value if str(number).strip()]


def _build_phone_numbers_schema(default_numbers: list[str], options: list[str]) -> vol.Schema:
    """Build form schema for selecting Twilio phone numbers."""
    select_options: Sequence[SelectOptionDict] = [
        {"value": number, "label": number} for number in options
    ]
    return vol.Schema(
        {
            vol.Optional(
                CONF_PHONE_NUMBERS,
                default=default_numbers,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=select_options,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


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
    _user_data: dict[str, str]
    _available_numbers: list[str]

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
                self._user_data = {
                    CONF_ACCOUNT_SID: user_input[CONF_ACCOUNT_SID],
                    CONF_AUTH_TOKEN: user_input[CONF_AUTH_TOKEN],
                }
                self._available_numbers = []
                try:
                    self._available_numbers = await _async_get_incoming_phone_numbers(
                        self.hass,
                        self._user_data[CONF_ACCOUNT_SID],
                        self._user_data[CONF_AUTH_TOKEN],
                    )
                except TwilioRestException as err:
                    _LOGGER.error("Failed to fetch incoming phone numbers: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error fetching incoming phone numbers")
                    errors["base"] = "unknown"
                else:
                    return await self.async_step_phone_numbers(
                        {
                            CONF_PHONE_NUMBERS: self._available_numbers
                            if len(self._available_numbers) == 1
                            else []
                        }
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

    async def async_step_phone_numbers(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle phone number selection after credentials validation."""
        if user_input is not None:
            selected_numbers = _normalize_selected_numbers(
                user_input.get(CONF_PHONE_NUMBERS, [])
            )
            webhook_id = webhook.async_generate_id()
            webhook_url = webhook.async_generate_url(self.hass, webhook_id)
            options = {
                CONF_PHONE_NUMBERS: selected_numbers,
                # Keep legacy option populated for backward compatibility.
                CONF_FROM_NUMBER: selected_numbers[0] if selected_numbers else "",
            }
            return self.async_create_entry(
                title="Twilio",
                data={
                    CONF_ACCOUNT_SID: self._user_data[CONF_ACCOUNT_SID],
                    CONF_AUTH_TOKEN: self._user_data[CONF_AUTH_TOKEN],
                    CONF_WEBHOOK_ID: webhook_id,
                },
                options=options,
                description_placeholders={"webhook_url": webhook_url},
            )

        default_numbers = self._available_numbers if len(self._available_numbers) == 1 else []
        return self.async_show_form(
            step_id="phone_numbers",
            data_schema=_build_phone_numbers_schema(
                default_numbers=default_numbers,
                options=self._available_numbers,
            ),
        )

    async def async_step_import(
        self, import_config: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Import config from configuration.yaml."""
        if import_config is None:
            return self.async_abort(reason="invalid_auth")

        await self.async_set_unique_id(import_config[CONF_ACCOUNT_SID])
        self._abort_if_unique_id_configured()
        webhook_id = webhook.async_generate_id()
        webhook_url = webhook.async_generate_url(self.hass, webhook_id)
        options: dict[str, Any] = {}
        try:
            numbers = await _async_get_incoming_phone_numbers(
                self.hass,
                import_config[CONF_ACCOUNT_SID],
                import_config[CONF_AUTH_TOKEN],
            )
        except Exception:
            _LOGGER.debug("Failed to fetch incoming phone numbers during import")
        else:
            options[CONF_PHONE_NUMBERS] = numbers
            options[CONF_FROM_NUMBER] = numbers[0] if numbers else ""

        return self.async_create_entry(
            title="Twilio",
            data={
                CONF_ACCOUNT_SID: import_config[CONF_ACCOUNT_SID],
                CONF_AUTH_TOKEN: import_config[CONF_AUTH_TOKEN],
                CONF_WEBHOOK_ID: webhook_id,
            },
            options=options,
            description_placeholders={"webhook_url": webhook_url},
        )


class TwilioOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Twilio options."""

    async def _async_get_phone_number_options(self) -> list[str]:
        """Fetch incoming Twilio phone numbers for this account."""
        account_sid = self.config_entry.data.get(CONF_ACCOUNT_SID)
        auth_token = self.config_entry.data.get(CONF_AUTH_TOKEN)
        if not account_sid or not auth_token:
            return []
        return await _async_get_incoming_phone_numbers(hass=self.hass, account_sid=account_sid, auth_token=auth_token)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_numbers = _normalize_selected_numbers(
                user_input.get(CONF_PHONE_NUMBERS, [])
            )

            user_input[CONF_PHONE_NUMBERS] = selected_numbers
            # Keep legacy option populated for backward compatibility.
            user_input[CONF_FROM_NUMBER] = (
                selected_numbers[0] if selected_numbers else ""
            )
            return self.async_create_entry(title="", data=user_input)

        available_numbers: list[str] = []
        try:
            available_numbers = await self._async_get_phone_number_options()
        except TwilioRestException as err:
            _LOGGER.error("Failed to fetch incoming phone numbers: %s", err)
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error fetching incoming phone numbers")
            errors["base"] = "unknown"

        default_numbers = self.config_entry.options.get(CONF_PHONE_NUMBERS)
        if not isinstance(default_numbers, list):
            fallback_number = self.config_entry.options.get(CONF_FROM_NUMBER, "")
            default_numbers = [fallback_number] if fallback_number else []

        # Preserve already-selected numbers even when the Twilio API doesn't return them.
        for selected in default_numbers:
            if selected and selected not in available_numbers:
                available_numbers.append(selected)
        available_numbers.sort()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                _build_phone_numbers_schema(
                    default_numbers=default_numbers,
                    options=available_numbers,
                ).schema
                | {
                    vol.Optional(
                        CONF_SENSOR_CLEANUP_HOURS,
                        default=self.config_entry.options.get(
                            CONF_SENSOR_CLEANUP_HOURS, DEFAULT_SENSOR_CLEANUP_HOURS
                        ),
                    ): NumberSelector(NumberSelectorConfig(min=1, max=168)),
                }
            ),
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
