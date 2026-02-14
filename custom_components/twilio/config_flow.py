"""Config flow for Twilio integration."""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.schema_config_entry_flow import SchemaOptionsFlowHandler
from homeassistant.helpers.selector import (
    SelectOptionDict,
    TextSelector,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    CONF_CALL_TARGETS,
    CONF_CALL_TARGETS_BY_NUMBER,
    CONF_FROM_NUMBER,
    CONF_PHONE_NUMBERS,
    CONF_SMS_TARGETS,
    CONF_SMS_TARGETS_BY_NUMBER,
    CONF_SENSOR_CLEANUP_HOURS,
    DEFAULT_SENSOR_CLEANUP_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


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
    return [
        str(number).strip()
        for number in value
        if str(number).strip() and PHONE_PATTERN.match(str(number).strip())
    ]


def _targets_to_text(targets: list[str]) -> str:
    """Convert target list to editable text."""
    return "\n".join(targets)


def _parse_targets_text(value: Any) -> list[str]:
    """Parse targets from text or list inputs into validated phone numbers."""
    if isinstance(value, list):
        # Defensive: selector payloads can come back as lists in some frontends.
        return _normalize_selected_numbers(value)

    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[,\n;]", value) if part.strip()]
        return [part for part in parts if PHONE_PATTERN.match(part)]

    return []


def _build_number_selection_schema(
    default_numbers: list[str],
    options: list[str],
) -> vol.Schema:
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


def _existing_targets_by_number(
    options: dict[str, Any], selected_numbers: list[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return per-number SMS and Call targets with legacy fallback."""
    sms_targets = _normalize_selected_numbers(options.get(CONF_SMS_TARGETS, []))
    call_targets = _normalize_selected_numbers(options.get(CONF_CALL_TARGETS, []))

    raw_sms_by_number = options.get(CONF_SMS_TARGETS_BY_NUMBER, {})
    if not isinstance(raw_sms_by_number, dict):
        raw_sms_by_number = {}
    raw_call_by_number = options.get(CONF_CALL_TARGETS_BY_NUMBER, {})
    if not isinstance(raw_call_by_number, dict):
        raw_call_by_number = {}

    sms_by_number: dict[str, list[str]] = {}
    call_by_number: dict[str, list[str]] = {}
    for number in selected_numbers:
        sms_by_number[number] = _normalize_selected_numbers(
            raw_sms_by_number.get(number, sms_targets)
        )
        call_by_number[number] = _normalize_selected_numbers(
            raw_call_by_number.get(number, call_targets)
        )

    return sms_by_number, call_by_number


def _build_single_targets_schema(
    sms_targets: list[str],
    call_targets: list[str],
) -> vol.Schema:
    """Build target mapping schema for one Twilio number."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_SMS_TARGETS,
                default=_targets_to_text(_normalize_selected_numbers(sms_targets)),
            ): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.TEL,
                    multiple=True,
                    multiline=False,
                ),
            ),
            vol.Optional(
                CONF_CALL_TARGETS,
                default=_targets_to_text(_normalize_selected_numbers(call_targets)),
            ): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.TEL,
                    multiple=True,
                    multiline=False,
                ),
            ),
        }
    )


def _build_options_payload(
    selected_numbers: list[str],
    sms_by_number: dict[str, list[str]],
    call_by_number: dict[str, list[str]],
    *,
    sensor_cleanup_hours: int | None = None,
) -> dict[str, Any]:
    """Build normalized options payload for storage."""
    normalized_sms_by_number = {
        number: _normalize_selected_numbers(sms_by_number.get(number, []))
        for number in selected_numbers
    }
    normalized_call_by_number = {
        number: _normalize_selected_numbers(call_by_number.get(number, []))
        for number in selected_numbers
    }
    flat_sms = sorted(
        {target for targets in normalized_sms_by_number.values() for target in targets}
    )
    flat_call = sorted(
        {target for targets in normalized_call_by_number.values() for target in targets}
    )
    payload: dict[str, Any] = {
        CONF_PHONE_NUMBERS: selected_numbers,
        CONF_SMS_TARGETS_BY_NUMBER: normalized_sms_by_number,
        CONF_CALL_TARGETS_BY_NUMBER: normalized_call_by_number,
        CONF_SMS_TARGETS: flat_sms,
        CONF_CALL_TARGETS: flat_call,
        CONF_FROM_NUMBER: selected_numbers[0] if selected_numbers else "",
    }
    if sensor_cleanup_hours is not None:
        payload[CONF_SENSOR_CLEANUP_HOURS] = sensor_cleanup_hours
    return payload


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

    VERSION = 2
    _user_data: dict[str, str]
    _available_numbers: list[str]
    _selected_numbers: list[str]
    _target_index: int
    _sms_by_number: dict[str, list[str]]
    _call_by_number: dict[str, list[str]]

    async def __call__(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Dynamically dispatch to async_step_<step_id> handlers."""
        handler = getattr(self, f"async_step_{step_id}", None)
        if handler is None:
            return self.async_abort(reason="unknown")
        return await handler(user_input)

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TwilioOptionsFlowHandler:
        """Get the options flow for this handler."""
        return TwilioOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
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
                    _LOGGER.exception(
                        "Unexpected error fetching incoming phone numbers"
                    )
                    errors["base"] = "unknown"
                else:
                    return await self(
                        "phone_numbers",
                        {
                            CONF_PHONE_NUMBERS: (
                                self._available_numbers
                                if len(self._available_numbers) == 1
                                else []
                            )
                        },
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
            self._selected_numbers = _normalize_selected_numbers(
                user_input.get(CONF_PHONE_NUMBERS, [])
            )
            self._target_index = 0
            self._sms_by_number = {number: [] for number in self._selected_numbers}
            self._call_by_number = {number: [] for number in self._selected_numbers}
            return await self("targets")

        default_numbers = (
            self._available_numbers if len(self._available_numbers) == 1 else []
        )
        return self.async_show_form(
            step_id="phone_numbers",
            data_schema=_build_number_selection_schema(
                default_numbers=default_numbers,
                options=self._available_numbers,
            ),
        )

    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle per-number target mapping during initial setup."""
        if not hasattr(self, "_selected_numbers"):
            self._selected_numbers = []
        if not hasattr(self, "_target_index"):
            self._target_index = 0
        if not hasattr(self, "_sms_by_number"):
            self._sms_by_number = {number: [] for number in self._selected_numbers}
        if not hasattr(self, "_call_by_number"):
            self._call_by_number = {number: [] for number in self._selected_numbers}

        if not self._selected_numbers:
            webhook_id = webhook.async_generate_id()
            webhook_url = webhook.async_generate_url(self.hass, webhook_id)
            return self.async_create_entry(
                title="Twilio",
                data={
                    CONF_ACCOUNT_SID: self._user_data[CONF_ACCOUNT_SID],
                    CONF_AUTH_TOKEN: self._user_data[CONF_AUTH_TOKEN],
                    CONF_WEBHOOK_ID: webhook_id,
                },
                options=_build_options_payload(
                    selected_numbers=[],
                    sms_by_number={},
                    call_by_number={},
                ),
                description_placeholders={"webhook_url": webhook_url},
            )

        current_number = self._selected_numbers[self._target_index]

        if user_input is not None:
            self._sms_by_number[current_number] = _parse_targets_text(
                user_input.get(CONF_SMS_TARGETS, "")
            )
            self._call_by_number[current_number] = _parse_targets_text(
                user_input.get(CONF_CALL_TARGETS, "")
            )
            self._target_index += 1

            if self._target_index >= len(self._selected_numbers):
                webhook_id = webhook.async_generate_id()
                webhook_url = webhook.async_generate_url(self.hass, webhook_id)
                return self.async_create_entry(
                    title="Twilio",
                    data={
                        CONF_ACCOUNT_SID: self._user_data[CONF_ACCOUNT_SID],
                        CONF_AUTH_TOKEN: self._user_data[CONF_AUTH_TOKEN],
                        CONF_WEBHOOK_ID: webhook_id,
                    },
                    options=_build_options_payload(
                        selected_numbers=self._selected_numbers,
                        sms_by_number=self._sms_by_number,
                        call_by_number=self._call_by_number,
                    ),
                    description_placeholders={"webhook_url": webhook_url},
                )

        current_number = self._selected_numbers[self._target_index]
        return self.async_show_form(
            step_id="targets",
            data_schema=_build_single_targets_schema(
                sms_targets=self._sms_by_number.get(current_number, []),
                call_targets=self._call_by_number.get(current_number, []),
            ),
            description_placeholders={"phone_number": current_number},
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
            options = _build_options_payload(
                selected_numbers=numbers,
                sms_by_number={number: [] for number in numbers},
                call_by_number={number: [] for number in numbers},
            )

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


class TwilioOptionsFlowHandler(SchemaOptionsFlowHandler):
    """Handle Twilio options."""

    _selected_numbers: list[str]
    _cleanup_hours: int
    _target_index: int
    _sms_by_number: dict[str, list[str]]
    _call_by_number: dict[str, list[str]]

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow handler."""
        super().__init__(config_entry, options_flow={})

    async def __call__(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Dynamically dispatch to async_step_<step_id> handlers."""
        handler = getattr(self, f"async_step_{step_id}", None)
        if handler is None:
            return self.async_abort(reason="unknown")
        return await handler(user_input)

    async def _async_get_phone_number_options(self) -> list[str]:
        """Fetch incoming Twilio phone numbers for this account."""
        account_sid = self.config_entry.data.get(CONF_ACCOUNT_SID)
        auth_token = self.config_entry.data.get(CONF_AUTH_TOKEN)
        if not account_sid or not auth_token:
            return []
        return await _async_get_incoming_phone_numbers(
            hass=self.hass, account_sid=account_sid, auth_token=auth_token
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options (step 1: select Twilio numbers)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_numbers = _normalize_selected_numbers(
                user_input.get(CONF_PHONE_NUMBERS, [])
            )
            self._selected_numbers = selected_numbers
            self._target_index = 0
            self._cleanup_hours = int(
                user_input.get(
                    CONF_SENSOR_CLEANUP_HOURS,
                    self.config_entry.options.get(
                        CONF_SENSOR_CLEANUP_HOURS, DEFAULT_SENSOR_CLEANUP_HOURS
                    ),
                )
            )
            sms_by_number, call_by_number = _existing_targets_by_number(
                options=dict(self.config_entry.options),
                selected_numbers=self._selected_numbers,
            )
            self._sms_by_number = sms_by_number
            self._call_by_number = call_by_number
            return await self("targets")

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
                _build_number_selection_schema(
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

    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options (step 2: per-number target settings)."""
        if not hasattr(self, "_selected_numbers"):
            default_numbers = self.config_entry.options.get(CONF_PHONE_NUMBERS, [])
            self._selected_numbers = (
                default_numbers if isinstance(default_numbers, list) else []
            )
        if not hasattr(self, "_target_index"):
            self._target_index = 0
        if not hasattr(self, "_cleanup_hours"):
            self._cleanup_hours = int(
                self.config_entry.options.get(
                    CONF_SENSOR_CLEANUP_HOURS, DEFAULT_SENSOR_CLEANUP_HOURS
                )
            )
        if not hasattr(self, "_sms_by_number") or not hasattr(self, "_call_by_number"):
            sms_by_number, call_by_number = _existing_targets_by_number(
                options=dict(self.config_entry.options),
                selected_numbers=self._selected_numbers,
            )
            self._sms_by_number = sms_by_number
            self._call_by_number = call_by_number

        if not self._selected_numbers:
            return self.async_create_entry(
                title="",
                data=_build_options_payload(
                    selected_numbers=[],
                    sms_by_number={},
                    call_by_number={},
                    sensor_cleanup_hours=self._cleanup_hours,
                ),
            )

        current_number = self._selected_numbers[self._target_index]

        if user_input is not None:
            self._sms_by_number[current_number] = _parse_targets_text(
                user_input.get(CONF_SMS_TARGETS, "")
            )
            self._call_by_number[current_number] = _parse_targets_text(
                user_input.get(CONF_CALL_TARGETS, "")
            )
            self._target_index += 1

            if self._target_index >= len(self._selected_numbers):
                return self.async_create_entry(
                    title="",
                    data=_build_options_payload(
                        selected_numbers=self._selected_numbers,
                        sms_by_number=self._sms_by_number,
                        call_by_number=self._call_by_number,
                        sensor_cleanup_hours=self._cleanup_hours,
                    ),
                )

        current_number = self._selected_numbers[self._target_index]
        return self.async_show_form(
            step_id="targets",
            data_schema=_build_single_targets_schema(
                sms_targets=self._sms_by_number.get(current_number, []),
                call_targets=self._call_by_number.get(current_number, []),
            ),
            description_placeholders={"phone_number": current_number},
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
