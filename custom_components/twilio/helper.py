"""Helper functions for Twilio call management."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from homeassistant.core import HomeAssistant

from .const import (
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_FROM,
    ATTR_TO,
    EVENT_TWILIO_CALL_INITIATED,
)

_LOGGER = logging.getLogger(__name__)


def get_twilio_client(hass: HomeAssistant) -> Client | None:
    """Get Twilio client from hass.data."""
    from .const import DATA_TWILIO, DOMAIN
    
    # Try global data first (for legacy YAML config)
    if DATA_TWILIO in hass.data:
        return hass.data[DATA_TWILIO]
    
    # Try config entry data
    if DOMAIN in hass.data:
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and DATA_TWILIO in entry_data:
                return entry_data[DATA_TWILIO]
    
    _LOGGER.error("Twilio client not found in hass.data")
    return None


def get_webhook_url(hass: HomeAssistant) -> str | None:
    """Get webhook URL from hass.data."""
    from .const import DOMAIN
    
    if DOMAIN in hass.data:
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and "webhook_url" in entry_data:
                return entry_data["webhook_url"]
    
    return None


def generate_simple_twiml_url(message: str) -> str:
    """Generate a simple TwiML URL for text-to-speech.
    
    Note: This method uses Twimlets, which is a legacy Twilio service.
    For production use, consider hosting your own TwiML endpoints.
    """
    if message.startswith(("http://", "https://")):
        return message
    
    twimlet_url = "https://twimlets.com/message?Message="
    twimlet_url += urllib.parse.quote(message, safe="")
    return twimlet_url


def fire_call_initiated_event(
    hass: HomeAssistant,
    call_sid: str,
    to_number: str,
    from_number: str,
    call_status: str,
) -> None:
    """Fire a call initiated event."""
    hass.bus.fire(
        EVENT_TWILIO_CALL_INITIATED,
        {
            ATTR_CALL_SID: call_sid,
            ATTR_TO: to_number,
            ATTR_FROM: from_number,
            ATTR_CALL_STATUS: call_status,
            "direction": "outbound-api",
        },
    )
    _LOGGER.debug("Fired call initiated event for SID %s", call_sid)


def make_call(
    client: Client,
    to_number: str,
    from_number: str,
    twiml_url: str,
    hass: HomeAssistant | None = None,
    status_callback: str | None = None,
    status_callback_method: str = "POST",
) -> dict[str, Any] | None:
    """Make a Twilio call with the given parameters.
    
    Args:
        client: Twilio client instance
        to_number: Destination phone number
        from_number: Source phone number (must be a Twilio number)
        twiml_url: URL that returns TwiML instructions
        hass: Home Assistant instance (for firing events)
        status_callback: Optional webhook URL for status callbacks
        status_callback_method: HTTP method for status callback (POST, GET, PUT)
    
    Returns:
        Dictionary with call information (call_sid, status) or None on error
    """
    call_args = {
        "to": to_number,
        "from_": from_number,
        "url": twiml_url,
    }
    
    # Add status callback if provided
    if status_callback:
        call_args["status_callback"] = status_callback
        method = status_callback_method.upper()
        if method in ["POST", "GET", "PUT"]:
            call_args["status_callback_method"] = method
        else:
            _LOGGER.warning("Invalid status_callback_method: %s, using POST", method)
            call_args["status_callback_method"] = "POST"
    
    try:
        call = client.calls.create(**call_args)
        
        # Fire event if hass is available
        if hass:
            fire_call_initiated_event(
                hass, call.sid, to_number, from_number, call.status
            )
        
        _LOGGER.info("Call initiated to %s with SID %s", to_number, call.sid)
        
        return {
            "call_sid": call.sid,
            "status": call.status,
            "to": to_number,
            "from": from_number,
        }
    
    except TwilioRestException as exc:
        _LOGGER.error("Failed to initiate call to %s: %s", to_number, exc)
        return None


def make_simple_call(
    client: Client,
    to_number: str,
    from_number: str,
    message: str,
    hass: HomeAssistant | None = None,
    status_callback: str | None = None,
    status_callback_method: str = "POST",
) -> dict[str, Any] | None:
    """Make a simple text-to-speech call.
    
    This is a convenience function that generates a TwiML URL and makes the call.
    
    Args:
        client: Twilio client instance
        to_number: Destination phone number
        from_number: Source phone number (must be a Twilio number)
        message: Message to speak or URL to TwiML
        hass: Home Assistant instance (for firing events)
        status_callback: Optional webhook URL for status callbacks
        status_callback_method: HTTP method for status callback (POST, GET, PUT)
    
    Returns:
        Dictionary with call information (call_sid, status) or None on error
    """
    twiml_url = generate_simple_twiml_url(message)
    
    return make_call(
        client=client,
        to_number=to_number,
        from_number=from_number,
        twiml_url=twiml_url,
        hass=hass,
        status_callback=status_callback,
        status_callback_method=status_callback_method,
    )
