"""Support for Twilio."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from twilio.rest import Client
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_flow, config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    DATA_TWILIO,
    DOMAIN,
    EVENT_TWILIO_SMS_RECEIVED,
    EVENT_TWILIO_CALL_RECEIVED,
    EVENT_TWILIO_CALL_ENDED,
    EVENT_TWILIO_TRANSCRIPTION,
    EVENT_TWILIO_DTMF,
    ATTR_FROM,
    ATTR_TO,
    ATTR_BODY,
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_TRANSCRIPTION,
    ATTR_DTMF_DIGITS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY]

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

    conf = config[DOMAIN]
    hass.data[DATA_TWILIO] = Client(
        conf.get(CONF_ACCOUNT_SID), conf.get(CONF_AUTH_TOKEN)
    )
    return True


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming webhook from Twilio for inbound messages and calls."""
    try:
        data = dict(await request.post())
        data["webhook_id"] = webhook_id

        # Determine the type of webhook and fire appropriate event
        message_sid = data.get("MessageSid")
        call_sid = data.get("CallSid")
        transcription_sid = data.get("TranscriptionSid")
        digits = data.get("Digits")

        if transcription_sid:
            # Transcription event
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_TRANSCRIPTION: data.get("TranscriptionText", ""),
                "transcription_sid": transcription_sid,
                "transcription_status": data.get("TranscriptionStatus", ""),
            }
            hass.bus.async_fire(EVENT_TWILIO_TRANSCRIPTION, event_data)
            _LOGGER.debug("Transcription received: %s", event_data)

        elif digits:
            # DTMF input event
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_DTMF_DIGITS: digits,
                ATTR_FROM: data.get("From", ""),
                ATTR_TO: data.get("To", ""),
            }
            hass.bus.async_fire(EVENT_TWILIO_DTMF, event_data)
            _LOGGER.debug("DTMF digits received: %s", event_data)

        elif message_sid:
            # SMS/MMS event
            event_data = {
                "message_sid": message_sid,
                ATTR_FROM: data.get("From", ""),
                ATTR_TO: data.get("To", ""),
                ATTR_BODY: data.get("Body", ""),
                "num_media": data.get("NumMedia", "0"),
            }
            # Add media URLs if present
            num_media = int(data.get("NumMedia", 0))
            if num_media > 0:
                media_urls = []
                for i in range(num_media):
                    media_url = data.get(f"MediaUrl{i}")
                    if media_url:
                        media_urls.append(media_url)
                if media_urls:
                    event_data["media_urls"] = media_urls

            hass.bus.async_fire(EVENT_TWILIO_SMS_RECEIVED, event_data)
            _LOGGER.debug("SMS received: %s", event_data)

        elif call_sid:
            # Call event
            call_status = data.get("CallStatus", "")
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_CALL_STATUS: call_status,
                ATTR_FROM: data.get("From", ""),
                ATTR_TO: data.get("To", ""),
                "direction": data.get("Direction", ""),
            }

            if call_status in ["completed", "busy", "no-answer", "failed", "canceled"]:
                # Call ended
                event_data["duration"] = data.get("CallDuration", "0")
                hass.bus.async_fire(EVENT_TWILIO_CALL_ENDED, event_data)
                _LOGGER.debug("Call ended: %s", event_data)
            else:
                # Call received or in progress
                hass.bus.async_fire(EVENT_TWILIO_CALL_RECEIVED, event_data)
                _LOGGER.debug("Call received: %s", event_data)

        # Store all data for reference
        hass.bus.async_fire(f"{DOMAIN}_data_received", dict(data))

        return web.Response(text="", content_type="text/xml")

    except Exception as err:
        _LOGGER.error("Error handling Twilio webhook: %s", err)
        return web.Response(status=500, text="Error processing webhook")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure based on config entry."""
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook_url = webhook.async_generate_url(hass, webhook_id)
    
    webhook.async_register(
        hass, DOMAIN, "Twilio", webhook_id, handle_webhook
    )

    # Store Twilio client and webhook info in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_TWILIO: Client(
            entry.data[CONF_ACCOUNT_SID],
            entry.data[CONF_AUTH_TOKEN],
        ),
        "webhook_id": webhook_id,
        "webhook_url": webhook_url,
    }

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Unregister webhook
        webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])

        # Remove data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async_remove_entry = config_entry_flow.webhook_async_remove_entry
