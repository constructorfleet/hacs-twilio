"""Webhook handling for Twilio integration."""

from __future__ import annotations

import logging

from aiohttp import web

from homeassistant.core import HomeAssistant

from .const import (
    ATTR_BODY,
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_DTMF_DIGITS,
    ATTR_FROM,
    ATTR_TO,
    ATTR_TRANSCRIPTION,
    EVENT_TWILIO_CALL_ENDED,
    EVENT_TWILIO_CALL_RECEIVED,
    EVENT_TWILIO_DTMF,
    EVENT_TWILIO_SMS_RECEIVED,
    EVENT_TWILIO_TRANSCRIPTION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


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
