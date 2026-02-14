"""Webhook handling for Twilio integration."""

from __future__ import annotations

import json
import logging
import re

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
    EVENT_TWILIO_TRANSCRIPTION_UPDATED,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _extract_transcription_text(data: dict) -> str:
    """Extract transcription text from Twilio TranscriptionData payload."""
    transcription_data = data.get("TranscriptionData")
    if not transcription_data:
        return data.get("TranscriptionText", "")

    payload = transcription_data
    if isinstance(transcription_data, str):
        try:
            payload = json.loads(transcription_data)
        except json.JSONDecodeError:
            _LOGGER.debug("Invalid TranscriptionData JSON: %s", transcription_data)
            return data.get("TranscriptionText", "")

    if isinstance(payload, dict):
        if isinstance(payload.get("transcript"), str):
            return payload["transcript"]
        if isinstance(payload.get("text"), str):
            return payload["text"]

    return data.get("TranscriptionText", "")


def _build_transcription_from_parts(parts: dict[str, dict]) -> str:
    """Build cumulative transcription text from sorted parts."""
    ordered = sorted(
        parts.values(),
        key=lambda part: (
            part.get("sequence_id", 0),
            part.get("timestamp", ""),
            part.get("track", ""),
        ),
    )
    full_transcription = ""

    for part in ordered:
        segment = part.get("text", "").strip()
        if not segment:
            continue
        if not full_transcription:
            full_transcription = segment
            continue
        full_transcription = _merge_with_word_overlap(full_transcription, segment)

    return full_transcription.strip()


def _normalize_token(token: str) -> str:
    """Normalize token for overlap comparison."""
    return re.sub(r"[^\w']", "", token).lower()


def _merge_with_word_overlap(base: str, segment: str) -> str:
    """Merge two segments while removing suffix/prefix word overlap."""
    base_words = base.split()
    segment_words = segment.split()

    if not base_words:
        return segment
    if not segment_words:
        return base

    normalized_base = [_normalize_token(word) for word in base_words]
    normalized_segment = [_normalize_token(word) for word in segment_words]

    max_overlap = min(len(normalized_base), len(normalized_segment))
    overlap_count = 0
    for overlap in range(max_overlap, 0, -1):
        if normalized_base[-overlap:] == normalized_segment[:overlap]:
            overlap_count = overlap
            break

    if overlap_count == len(segment_words):
        return base

    suffix = " ".join(segment_words[overlap_count:])
    if not suffix:
        return base
    return f"{base} {suffix}".strip()


async def handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle incoming webhook from Twilio for inbound messages and calls."""
    try:
        data = dict(await request.post())
        data["webhook_id"] = webhook_id

        # Determine the type of webhook and fire appropriate event
        message_sid = str(data.get("MessageSid"))
        call_sid = str(data.get("CallSid"))
        transcription_sid = str(data.get("TranscriptionSid"))
        transcription_event = str(data.get("TranscriptionEvent"))
        digits = str(data.get("Digits"))

        if transcription_event:
            if not call_sid:
                _LOGGER.warning("TranscriptionEvent received without CallSid: %s", data)
                hass.bus.async_fire(f"{DOMAIN}_data_received", dict(data))
                return web.Response(text="", content_type="text/xml")

            sequence_id = str(data.get("SequenceId", "0"))
            track = str(data.get("Track", ""))
            timestamp = str(data.get("Timestamp", ""))
            is_final = str(data.get("Final", "false")).lower() == "true"
            segment_text = _extract_transcription_text(data)

            domain_data = hass.data.setdefault(DOMAIN, {})
            transcription_store = domain_data.setdefault("transcription_parts", {})
            call_store = transcription_store.setdefault(
                call_sid,
                {
                    "transcription_sid": transcription_sid,
                    "language_code": str(data.get("LanguageCode", "")),
                    "parts": {},
                },
            )

            if transcription_sid:
                call_store["transcription_sid"] = transcription_sid
            if data.get("LanguageCode"):
                call_store["language_code"] = data.get("LanguageCode")

            try:
                sequence_number = int(sequence_id)
            except (TypeError, ValueError):
                sequence_number = 0

            part_key = f"{track}:{sequence_id}"
            call_store["parts"][part_key] = {
                "sequence_id": sequence_number,
                "track": track,
                "timestamp": timestamp,
                "text": segment_text,
                "final": is_final,
            }

            full_transcription = _build_transcription_from_parts(call_store["parts"])

            event_data: dict[str, str | int | bool | list[str]] = {
                ATTR_CALL_SID: call_sid,
                ATTR_TRANSCRIPTION: full_transcription,
                "transcription_sid": call_store.get("transcription_sid", ""),
                "transcription_event": transcription_event,
                "sequence_id": sequence_id,
                "track": track,
                "final": is_final,
                "language_code": call_store.get("language_code", ""),
                "stability": str(data.get("Stability", "")),
                "timestamp": timestamp,
                "segment_text": segment_text,
                "parts_count": len(call_store["parts"]),
            }

            hass.bus.async_fire(EVENT_TWILIO_TRANSCRIPTION_UPDATED, event_data)
            _LOGGER.debug("Transcription updated: %s", event_data)

        elif transcription_sid:
            # Transcription event
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_TRANSCRIPTION: str(data.get("TranscriptionText", "")),
                "transcription_sid": transcription_sid,
                "transcription_status": str(data.get("TranscriptionStatus", "")),
            }
            hass.bus.async_fire(EVENT_TWILIO_TRANSCRIPTION, event_data)
            _LOGGER.debug("Transcription received: %s", event_data)

        elif digits:
            # DTMF input event
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_DTMF_DIGITS: digits,
                ATTR_FROM: str(data.get("From", "")),
                ATTR_TO: str(data.get("To", "")),
            }
            hass.bus.async_fire(EVENT_TWILIO_DTMF, event_data)
            _LOGGER.debug("DTMF digits received: %s", event_data)

        elif message_sid:
            # SMS/MMS event
            event_data = {
                "message_sid": message_sid,
                ATTR_FROM: str(data.get("From", "")),
                ATTR_TO: str(data.get("To", "")),
                ATTR_BODY: str(data.get("Body", "")),
                "num_media": str(data.get("NumMedia", "0")),
            }
            # Add media URLs if present
            num_media = int(str(data.get("NumMedia", "0")))
            if num_media > 0:
                media_urls: list[str] = []
                for i in range(num_media):
                    media_url = data.get(f"MediaUrl{i}")
                    if media_url:
                        media_urls.append(str(media_url))
                if media_urls:
                    event_data["media_urls"] = media_urls

            hass.bus.async_fire(EVENT_TWILIO_SMS_RECEIVED, event_data)
            _LOGGER.debug("SMS received: %s", event_data)

        elif call_sid:
            # Call event
            call_status = data.get("CallStatus", "")
            event_data = {
                ATTR_CALL_SID: call_sid,
                ATTR_CALL_STATUS: str(call_status),
                ATTR_FROM: str(data.get("From", "")),
                ATTR_TO: str(data.get("To", "")),
                "direction": str(data.get("Direction", "")),
            }

            if call_status in ["completed", "busy", "no-answer", "failed", "canceled"]:
                # Call ended
                event_data["duration"] = str(data.get("CallDuration", "0"))
                if DOMAIN in hass.data and "transcription_parts" in hass.data[DOMAIN]:
                    hass.data[DOMAIN]["transcription_parts"].pop(call_sid, None)
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
