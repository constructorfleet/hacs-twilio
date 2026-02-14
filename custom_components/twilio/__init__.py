"""Support for Twilio."""

from __future__ import annotations

import logging

from twilio.rest import Client
from twilio.http.async_http_client import AsyncTwilioHttpClient
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook as webhook_component
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_entry_flow, config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    CONF_CALL_TARGETS,
    CONF_CALL_TARGETS_BY_NUMBER,
    CONF_FROM_NUMBER,
    CONF_PHONE_NUMBERS,
    CONF_SMS_TARGETS,
    CONF_SMS_TARGETS_BY_NUMBER,
    DEFAULT_TRANSCRIBE_LANGUAGE,
    DATA_TWILIO,
    DOMAIN,
    ATTR_CALL_SID,
    ATTR_DTMF_DIGITS,
    SERVICE_SEND_DTMF,
    SERVICE_START_RECORDING,
    SERVICE_PAUSE,
    SERVICE_MAKE_CALL,
    SERVICE_SEND_MMS,
)
from .services import (
    async_make_call,
    async_pause_call,
    async_send_mms,
    async_send_dtmf,
    async_start_recording,
)
from .webhook import handle_webhook

_LOGGER = logging.getLogger(__name__)
_SERVICES_REGISTERED = "services_registered"

PLATFORMS = [Platform.SENSOR, Platform.NOTIFY]

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_SID): cv.string,
                vol.Required(CONF_AUTH_TOKEN): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Twilio component."""
    if DOMAIN not in config:
        return True
    if not hass.config_entries.async_entries(DOMAIN) and DOMAIN in config:
        conf = config[DOMAIN]
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={
                    CONF_ACCOUNT_SID: conf.get(CONF_ACCOUNT_SID),
                    CONF_AUTH_TOKEN: conf.get(CONF_AUTH_TOKEN),
                },
            ),
        )
    return True


def _normalize_option_list(value: object) -> list[str]:
    """Normalize list options into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry options to the latest schema."""
    _LOGGER.debug("Migrating Twilio config entry from version %s", entry.version)

    if entry.version > 2:
        _LOGGER.error(
            "Cannot migrate Twilio config entry with unsupported version %s",
            entry.version,
        )
        return False

    if entry.version == 1:
        options = dict(entry.options)

        phone_numbers = _normalize_option_list(options.get(CONF_PHONE_NUMBERS))
        if not phone_numbers:
            fallback_number = options.get(CONF_FROM_NUMBER, "")
            if isinstance(fallback_number, str) and fallback_number.strip():
                phone_numbers = [fallback_number.strip()]

        sms_targets = _normalize_option_list(options.get(CONF_SMS_TARGETS))
        call_targets = _normalize_option_list(options.get(CONF_CALL_TARGETS))
        sms_targets_by_number = options.get(CONF_SMS_TARGETS_BY_NUMBER, {})
        if not isinstance(sms_targets_by_number, dict):
            sms_targets_by_number = {}
        call_targets_by_number = options.get(CONF_CALL_TARGETS_BY_NUMBER, {})
        if not isinstance(call_targets_by_number, dict):
            call_targets_by_number = {}

        migrated_sms_targets_by_number: dict[str, list[str]] = {}
        migrated_call_targets_by_number: dict[str, list[str]] = {}
        for number in phone_numbers:
            migrated_sms_targets_by_number[number] = _normalize_option_list(
                sms_targets_by_number.get(number, sms_targets)
            )
            migrated_call_targets_by_number[number] = _normalize_option_list(
                call_targets_by_number.get(number, call_targets)
            )

        options[CONF_PHONE_NUMBERS] = phone_numbers
        options[CONF_FROM_NUMBER] = phone_numbers[0] if phone_numbers else ""
        options[CONF_SMS_TARGETS] = sms_targets
        options[CONF_CALL_TARGETS] = call_targets
        options[CONF_SMS_TARGETS_BY_NUMBER] = migrated_sms_targets_by_number
        options[CONF_CALL_TARGETS_BY_NUMBER] = migrated_call_targets_by_number

        hass.config_entries.async_update_entry(entry, options=options, version=2)

    _LOGGER.info("Twilio config entry migration to version %s successful", entry.version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure based on config entry."""
    # Store Twilio client and webhook info in hass.data
    hass.data.setdefault(DOMAIN, {})

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook_url = webhook_component.async_generate_url(hass, webhook_id)

    # Reload/setup can race with stale webhook handlers; replace defensively.
    webhook_component.async_unregister(hass, webhook_id)
    webhook_component.async_register(hass, DOMAIN, "Twilio", webhook_id, handle_webhook)

    # Create async HTTP client for Twilio
    http_client = AsyncTwilioHttpClient()
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_TWILIO: Client(
            entry.data[CONF_ACCOUNT_SID],
            entry.data[CONF_AUTH_TOKEN],
            http_client=http_client,
        ),
        "webhook_id": webhook_id,
        "webhook_url": webhook_url,
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))

    if not hass.data[DOMAIN].get(_SERVICES_REGISTERED):
        # Register services once for the integration domain.
        hass.services.async_register(
            DOMAIN,
            SERVICE_MAKE_CALL,
            lambda call: async_make_call(hass, call),
            schema=vol.Schema(
                {
                    vol.Required("to"): cv.string,
                    vol.Required("from_number"): cv.string,
                    vol.Optional("message", default=""): cv.string,
                    vol.Optional("transcription", default=False): cv.boolean,
                    vol.Optional(
                        "language_code", default=DEFAULT_TRANSCRIBE_LANGUAGE
                    ): cv.string,
                    vol.Optional("profanity_filter", default=False): cv.boolean,
                    vol.Optional("automatic_punctuation", default=False): cv.boolean,
                    vol.Optional("transcription_pause", default=10): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=3600)
                    ),
                    vol.Optional("webhook_method", default="POST"): cv.string,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MMS,
            lambda call: async_send_mms(hass, call),
            schema=vol.Schema(
                {
                    vol.Required("to"): cv.string,
                    vol.Required("from_number"): cv.string,
                    vol.Required("media_url"): vol.Any(cv.string, [cv.string]),
                    vol.Optional("body", default=""): cv.string,
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_DTMF,
            lambda call: async_send_dtmf(hass, call),
            schema=vol.Schema(
                {
                    vol.Required(ATTR_CALL_SID): cv.string,
                    vol.Required(ATTR_DTMF_DIGITS): cv.string,
                }
            ),
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_START_RECORDING,
            lambda call: async_start_recording(hass, call),
            schema=vol.Schema(
                {
                    vol.Required(ATTR_CALL_SID): cv.string,
                    vol.Optional("max_length", default=3600): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=14400)
                    ),
                    vol.Optional(
                        "recording_status_callback", default=False
                    ): cv.boolean,
                    vol.Optional("transcribe", default=False): cv.boolean,
                    vol.Optional("transcribe_callback", default=False): cv.boolean,
                }
            ),
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_PAUSE,
            lambda call: async_pause_call(hass, call),
            schema=vol.Schema(
                {
                    vol.Required(ATTR_CALL_SID): cv.string,
                    vol.Optional("length", default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=3600)
                    ),
                }
            ),
        )
        hass.data[DOMAIN][_SERVICES_REGISTERED] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Unregister webhook
        webhook_component.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])

        # Remove data
        hass.data[DOMAIN].pop(entry.entry_id)

        remaining_clients = [
            entry_data
            for entry_data in hass.data[DOMAIN].values()
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data
        ]
        if not remaining_clients:
            # Unregister services once the last Twilio entry is removed.
            hass.services.async_remove(DOMAIN, SERVICE_MAKE_CALL)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_MMS)
            hass.services.async_remove(DOMAIN, SERVICE_SEND_DTMF)
            hass.services.async_remove(DOMAIN, SERVICE_START_RECORDING)
            hass.services.async_remove(DOMAIN, SERVICE_PAUSE)
            hass.data[DOMAIN].pop(_SERVICES_REGISTERED, None)

    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async_remove_entry = config_entry_flow.webhook_async_remove_entry
