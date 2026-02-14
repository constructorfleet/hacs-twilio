"""Service handlers for Twilio integration."""

from __future__ import annotations

import logging
import urllib.parse

from twilio.twiml.voice_response import VoiceResponse

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

from .const import (
    ATTR_CALL_SID,
    ATTR_DTMF_DIGITS,
    ATTR_FROM,
    ATTR_TO,
)
from .helper import (
    fire_call_initiated_event,
    generate_simple_twiml_url,
    get_twilio_client,
    get_webhook_url,
)

_LOGGER = logging.getLogger(__name__)


async def async_make_call(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Make a voice call and return call information."""
    to_number = call.data.get("to")
    message = call.data.get("message", "")
    from_number = call.data.get("from_number")

    if not to_number:
        _LOGGER.error("'to' number is required for make_call service")
        return None

    # Get the Twilio client
    client = get_twilio_client(hass)
    if not client:
        _LOGGER.error("Twilio client not found")
        return None

    # Use provided from_number
    if not from_number:
        _LOGGER.warning("No from_number provided, call may fail without configured number")
        return None

    try:
        # Create simple TwiML for the message
        twiml_url = generate_simple_twiml_url(message)

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
        fire_call_initiated_event(hass, call_sid, to_number, from_number, call_status)

        # Wait a moment for sensor to be created
        import asyncio
        await asyncio.sleep(0.5)

        # Get the entity_id of the sensor
        entity_id = f"sensor.twilio_call_{call_sid}".lower()

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


async def async_send_dtmf(hass: HomeAssistant, call: ServiceCall) -> None:
    """Send DTMF digits to an active call."""
    call_sid = call.data.get(ATTR_CALL_SID)
    digits = call.data.get(ATTR_DTMF_DIGITS)

    if not call_sid or not digits:
        _LOGGER.error("call_sid and digits are required for send_dtmf service")
        return

    # Get the Twilio client
    client = get_twilio_client(hass)
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


async def async_start_recording(hass: HomeAssistant, call: ServiceCall) -> None:
    """Start recording an active call."""
    call_sid = call.data.get(ATTR_CALL_SID)

    if not call_sid:
        _LOGGER.error("call_sid is required for start_recording service")
        return

    # Get the Twilio client and webhook URL
    client = get_twilio_client(hass)
    if not client:
        _LOGGER.error("Twilio client not found")
        return

    webhook_url = get_webhook_url(hass)

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


async def async_pause_call(hass: HomeAssistant, call: ServiceCall) -> None:
    """Pause an active call for a specified duration."""
    call_sid = call.data.get(ATTR_CALL_SID)
    length = call.data.get("length", 1)

    if not call_sid:
        _LOGGER.error("call_sid is required for pause service")
        return

    # Get the Twilio client
    client = get_twilio_client(hass)
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
