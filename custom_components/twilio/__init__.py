"""Support for Twilio."""

from __future__ import annotations

import logging
from typing import Any
import urllib.parse

from aiohttp import web
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
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
    SERVICE_SEND_DTMF,
    SERVICE_START_RECORDING,
    SERVICE_PAUSE,
    SERVICE_MAKE_CALL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY, Platform.SENSOR]

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

    # Register services
    async def async_make_call(call) -> ServiceResponse:
        """Make a voice call and return call information."""
        to_number = call.data.get("to")
        message = call.data.get("message", "")
        from_number = call.data.get("from_number")

        if not to_number:
            _LOGGER.error("'to' number is required for make_call service")
            return None

        # Get the Twilio client and from_number
        client = None
        default_from = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data:
                client = entry_data[DATA_TWILIO]
                break

        if not client:
            _LOGGER.error("Twilio client not found")
            return None

        # Use provided from_number or try to find a configured one
        if not from_number:
            # Try to get from notify platform config
            _LOGGER.warning("No from_number provided, call may fail without configured number")
            return None

        try:
            # Create simple TwiML for the message
            if message.startswith(("http://", "https://")):
                twiml_url = message
            else:
                twiml_url = "https://twimlets.com/message?Message="
                twiml_url += urllib.parse.quote(message, safe="")

            # Make the call
            twilio_call = await hass.async_add_executor_job(
                lambda: client.calls.create(
                    to=to_number,
                    from_=from_number,
                    url=twiml_url,
                )
            )

            call_sid = twilio_call.sid
            call_status = twilio_call.status

            # Fire event for call initiated
            hass.bus.fire(
                "twilio_call_initiated",
                {
                    ATTR_CALL_SID: call_sid,
                    ATTR_TO: to_number,
                    ATTR_FROM: from_number,
                    ATTR_CALL_STATUS: call_status,
                    "direction": "outbound-api",
                },
            )

            # Wait a moment for sensor to be created
            await hass.async_add_executor_job(lambda: __import__('time').sleep(0.5))

            # Try to get the entity_id of the sensor
            entity_id = f"sensor.twilio_call_{call_sid[:8]}".lower()

            _LOGGER.info("Call initiated to %s with SID %s", to_number, call_sid)

            return {
                "call_sid": call_sid,
                "entity_id": entity_id,
                "status": call_status,
                "to": to_number,
                "from": from_number,
            }

        except Exception as err:
            _LOGGER.error("Failed to make call to %s: %s", to_number, err)
            return None

    async def async_send_dtmf(call):
        """Send DTMF digits to an active call."""
        call_sid = call.data.get(ATTR_CALL_SID)
        digits = call.data.get(ATTR_DTMF_DIGITS)

        if not call_sid or not digits:
            _LOGGER.error("call_sid and digits are required for send_dtmf service")
            return

        # Get the Twilio client
        client = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data:
                client = entry_data[DATA_TWILIO]
                break

        if not client:
            _LOGGER.error("Twilio client not found")
            return

        try:
            # Create TwiML with Play verb to send DTMF digits
            # Add 'w' between digits for half-second pauses
            twiml = VoiceResponse()
            # Format digits: 'w' creates a 0.5s pause before each digit
            formatted_digits = 'w' + 'w'.join(digits)
            twiml.play(digits=formatted_digits)

            # Convert TwiML to URL-encoded string
            twiml_str = str(twiml)
            twiml_url = f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

            # Update the call with the new TwiML
            await hass.async_add_executor_job(
                lambda: client.calls(call_sid).update(url=twiml_url, method="POST")
            )
            _LOGGER.info("Sent DTMF digits '%s' to call %s", digits, call_sid)
        except Exception as err:
            _LOGGER.error("Failed to send DTMF digits to call %s: %s", call_sid, err)

    async def async_start_recording(call):
        """Start recording an active call."""
        call_sid = call.data.get(ATTR_CALL_SID)

        if not call_sid:
            _LOGGER.error("call_sid is required for start_recording service")
            return

        # Get the Twilio client and webhook URL
        client = None
        webhook_url = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data:
                client = entry_data[DATA_TWILIO]
                webhook_url = entry_data.get("webhook_url")
                break

        if not client:
            _LOGGER.error("Twilio client not found")
            return

        try:
            # Get optional parameters
            max_length = call.data.get("max_length", 3600)  # Default 1 hour
            recording_status_callback = call.data.get("recording_status_callback", False)
            transcribe = call.data.get("transcribe", False)
            transcribe_callback = call.data.get("transcribe_callback", False)

            # Create TwiML with Record verb
            twiml = VoiceResponse()
            record_params = {
                "max_length": max_length,
            }

            # Add recording status callback if webhook URL is configured
            if recording_status_callback and webhook_url:
                record_params["recording_status_callback"] = webhook_url
                record_params["recording_status_callback_method"] = "POST"
                record_params["recording_status_callback_event"] = ["in-progress", "completed", "absent"]

            # Add transcription if requested
            if transcribe:
                record_params["transcribe"] = True
                if transcribe_callback and webhook_url:
                    record_params["transcribe_callback"] = webhook_url

            twiml.record(**record_params)

            # Convert TwiML to URL-encoded string
            twiml_str = str(twiml)
            twiml_url = f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

            # Update the call with the new TwiML
            await hass.async_add_executor_job(
                lambda: client.calls(call_sid).update(url=twiml_url, method="POST")
            )
            _LOGGER.info("Started recording for call %s", call_sid)
        except Exception as err:
            _LOGGER.error("Failed to start recording for call %s: %s", call_sid, err)

    async def async_pause_call(call):
        """Pause an active call for a specified duration."""
        call_sid = call.data.get(ATTR_CALL_SID)
        length = call.data.get("length", 1)

        if not call_sid:
            _LOGGER.error("call_sid is required for pause service")
            return

        # Get the Twilio client
        client = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data:
                client = entry_data[DATA_TWILIO]
                break

        if not client:
            _LOGGER.error("Twilio client not found")
            return

        try:
            # Create TwiML with Pause verb
            twiml = VoiceResponse()
            twiml.pause(length=length)

            # Convert TwiML to URL-encoded string
            twiml_str = str(twiml)
            twiml_url = f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

            # Update the call with the new TwiML
            await hass.async_add_executor_job(
                lambda: client.calls(call_sid).update(url=twiml_url, method="POST")
            )
            _LOGGER.info("Paused call %s for %s seconds", call_sid, length)
        except Exception as err:
            _LOGGER.error("Failed to pause call %s: %s", call_sid, err)

    # Register the services
    hass.services.async_register(
        DOMAIN,
        SERVICE_MAKE_CALL,
        async_make_call,
        schema=vol.Schema({
            vol.Required("to"): cv.string,
            vol.Required("from_number"): cv.string,
            vol.Optional("message", default=""): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_DTMF,
        async_send_dtmf,
        schema=vol.Schema({
            vol.Required(ATTR_CALL_SID): cv.string,
            vol.Required(ATTR_DTMF_DIGITS): cv.string,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_RECORDING,
        async_start_recording,
        schema=vol.Schema({
            vol.Required(ATTR_CALL_SID): cv.string,
            vol.Optional("max_length", default=3600): vol.All(vol.Coerce(int), vol.Range(min=1, max=14400)),
            vol.Optional("recording_status_callback", default=False): cv.boolean,
            vol.Optional("transcribe", default=False): cv.boolean,
            vol.Optional("transcribe_callback", default=False): cv.boolean,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE,
        async_pause_call,
        schema=vol.Schema({
            vol.Required(ATTR_CALL_SID): cv.string,
            vol.Optional("length", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
        }),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Unregister webhook
        webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])

        # Unregister services
        hass.services.async_remove(DOMAIN, SERVICE_MAKE_CALL)
        hass.services.async_remove(DOMAIN, SERVICE_SEND_DTMF)
        hass.services.async_remove(DOMAIN, SERVICE_START_RECORDING)
        hass.services.async_remove(DOMAIN, SERVICE_PAUSE)

        # Remove data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async_remove_entry = config_entry_flow.webhook_async_remove_entry
