"""Service handlers for Twilio integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import cast
import time
import urllib.parse

from twilio.twiml.voice_response import Start, VoiceResponse

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError

from .const import (
    ATTR_BODY,
    ATTR_CALL_SID,
    ATTR_DTMF_DIGITS,
    ATTR_MEDIA_URL,
    ATTR_TO,
)
from .helper import (
    fire_call_initiated_event,
    generate_simple_twiml_url,
    get_twilio_client,
    get_webhook_url,
)

_LOGGER = logging.getLogger(__name__)
MAX_MMS_MEDIA_SIZE_BYTES = 5 * 1024 * 1024
ATTR_CAMERA_ENTITY = "camera_entity"
ATTR_IMAGE_ENTITY = "image_entity"
ATTR_IMAGE_PATH = "image_path"


async def _async_create_call(client, **kwargs):
    """Create a call with async client when available, else use sync API in a thread."""
    create_async = getattr(client.calls, "create_async", None)
    if create_async and inspect.iscoroutinefunction(create_async):
        return await create_async(**kwargs)
    return await asyncio.to_thread(lambda: client.calls.create(**kwargs))


async def _async_create_message(client, **kwargs):
    """Create a message with async client when available, else use sync API in a thread."""
    create_async = getattr(client.messages, "create_async", None)
    if create_async and inspect.iscoroutinefunction(create_async):
        return await create_async(**kwargs)
    return await asyncio.to_thread(lambda: client.messages.create(**kwargs))


def _get_external_base_url(hass: HomeAssistant) -> str | None:
    """Return configured Home Assistant external URL, if available."""
    external_url = getattr(hass.config, "external_url", None)
    if not external_url:
        _LOGGER.warning(
            "Cannot attach entity/file images to MMS: Home Assistant external_url is not configured"
        )
        return None
    return external_url.rstrip("/")


async def _async_get_entity_snapshot(
    hass: HomeAssistant, entity_id: str
) -> tuple[str, bytes] | None:
    """Fetch snapshot bytes for a camera/image entity."""
    domain = entity_id.split(".", maxsplit=1)[0]
    if domain == "camera":
        from homeassistant.components.camera import async_get_image as camera_get_image

        snapshot = await camera_get_image(hass, entity_id)
        return snapshot.content_type, snapshot.content

    if domain == "image":
        from homeassistant.components.image import async_get_image as image_get_image

        snapshot = await image_get_image(hass, entity_id)
        return snapshot.content_type, snapshot.content

    _LOGGER.warning("Unsupported entity domain for MMS attachment: %s", entity_id)
    return None


async def _build_entity_media_url(hass: HomeAssistant, entity_id: str) -> str | None:
    """Create snapshot file for entity and return external /local URL."""
    external_base = _get_external_base_url(hass)
    if not external_base:
        return None

    try:
        snapshot_data = await _async_get_entity_snapshot(hass, entity_id)
        if snapshot_data is None:
            return None
        content_type, content = snapshot_data
    except HomeAssistantError as err:
        _LOGGER.error("Failed to get snapshot from %s: %s", entity_id, err)
        return None

    if len(content) > MAX_MMS_MEDIA_SIZE_BYTES:
        _LOGGER.warning("Entity snapshot is too large for MMS (max 5MB): %s", entity_id)
        return None

    extension = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }.get(content_type.lower(), "jpg")

    snapshot_dir = Path(hass.config.config_dir) / "www" / "twilio_snapshots"
    await hass.async_add_executor_job(lambda: snapshot_dir.mkdir(parents=True, exist_ok=True))
    safe_entity_id = entity_id.replace(".", "_")
    filename = f"{safe_entity_id}_{int(time.time() * 1000)}.{extension}"
    snapshot_path = snapshot_dir / filename
    await hass.async_add_executor_job(snapshot_path.write_bytes, content)
    return f"{external_base}/local/twilio_snapshots/{filename}"


def _build_file_media_url(hass: HomeAssistant, image_path: str) -> str | None:
    """Build a publicly reachable media URL for a local image file."""
    external_base = _get_external_base_url(hass)
    if not external_base:
        return None

    path = Path(image_path)
    if not path.exists():
        _LOGGER.error("Image file not found: %s", image_path)
        return None
    if path.stat().st_size > MAX_MMS_MEDIA_SIZE_BYTES:
        _LOGGER.warning("Image file is too large for MMS (max 5MB): %s", image_path)
        return None

    www_dir = Path(hass.config.config_dir) / "www"
    try:
        relative_path = path.resolve().relative_to(www_dir.resolve())
    except ValueError:
        _LOGGER.warning(
            "Image file path must be under %s to be externally accessible: %s",
            www_dir,
            image_path,
        )
        return None

    return f"{external_base}/local/{relative_path.as_posix()}"


async def async_make_call(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Make a voice call and return call information."""
    to_number = call.data.get("to")
    message = call.data.get("message", "")
    from_number = call.data.get("from_number")
    transcription_enabled = call.data.get("transcription", False)

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
        _LOGGER.warning(
            "No from_number provided, call may fail without configured number"
        )
        return None

    try:
        if transcription_enabled:
            webhook_url = get_webhook_url(hass)
            if not webhook_url:
                _LOGGER.error(
                    "Transcription requested for make_call but no webhook URL is configured"
                )
                return None

            webhook_method = call.data.get("webhook_method", "POST").upper()
            if webhook_method not in ["POST", "GET", "PUT"]:
                _LOGGER.warning(
                    "Invalid webhook_method '%s'; defaulting to POST", webhook_method
                )
                webhook_method = "POST"

            language_code = call.data.get("language_code", "en-US")
            profanity_filter = call.data.get("profanity_filter", False)
            automatic_punctuation = call.data.get("automatic_punctuation", False)
            transcription_pause = call.data.get("transcription_pause", 10)

            twiml = VoiceResponse()
            cast(Start, twiml.start()).transcription(
                status_callback_url=webhook_url,
                status_callback_method=webhook_method,
                language_code=language_code,
                profanity_filter=profanity_filter,
                enable_automatic_punctuation=automatic_punctuation,
                partial_results=True,
            )
            twiml.pause(length=transcription_pause)

            twilio_call = await _async_create_call(
                client,
                to=to_number,
                from_=from_number,
                twiml=twiml.to_xml(),
            )
        else:
            # Create simple TwiML for the message
            twiml_url = generate_simple_twiml_url(message)

            # Make the call using async Twilio client
            twilio_call = await _async_create_call(
                client,
                to=to_number,
                from_=from_number,
                url=twiml_url,
            )

        call_sid = twilio_call.sid
        call_status = twilio_call.status

        if not call_sid or not call_status:
            return {}

        # Fire event for call initiated
        fire_call_initiated_event(
            hass, call_sid, to_number, from_number, str(call_status)
        )

        # Wait a moment for sensor to be created
        await asyncio.sleep(0.5)

        # Get the entity_id of the sensor
        entity_id = f"sensor.twilio_call_{call_sid}".lower()

        _LOGGER.info("Call initiated to %s with SID %s", to_number, call_sid)

        return {
            "call_sid": call_sid,
            "entity_id": entity_id,
            "status": str(call_status),
            "to": to_number,
            "from": from_number,
        }

    except Exception as err:
        _LOGGER.error("Failed to make call to %s: %s", to_number, err)
        return None


async def async_send_mms(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Send an MMS message and return message information."""
    to_number = call.data.get(ATTR_TO)
    from_number = call.data.get("from_number")
    message = call.data.get(ATTR_BODY, "")
    media_url = call.data.get(ATTR_MEDIA_URL)
    camera_entity = call.data.get(ATTR_CAMERA_ENTITY)
    image_entity = call.data.get(ATTR_IMAGE_ENTITY)
    image_path = call.data.get(ATTR_IMAGE_PATH)

    if not to_number:
        _LOGGER.error("'to' number is required for send_mms service")
        return None
    if not from_number:
        _LOGGER.error("'from_number' is required for send_mms service")
        return None
    # Get the Twilio client
    client = get_twilio_client(hass)
    if not client:
        _LOGGER.error("Twilio client not found")
        return None

    media_urls: list[str] = []
    if isinstance(media_url, str) and media_url.strip():
        media_urls.append(media_url.strip())
    elif isinstance(media_url, list):
        media_urls.extend(
            [str(url).strip() for url in media_url if isinstance(url, str) and url.strip()]
        )

    if isinstance(camera_entity, str) and camera_entity.strip():
        if camera_url := await _build_entity_media_url(hass, camera_entity.strip()):
            media_urls.append(camera_url)
    if isinstance(image_entity, str) and image_entity.strip():
        if image_url := await _build_entity_media_url(hass, image_entity.strip()):
            media_urls.append(image_url)
    if isinstance(image_path, str) and image_path.strip():
        if image_url := _build_file_media_url(hass, image_path.strip()):
            media_urls.append(image_url)

    if not media_urls:
        _LOGGER.error(
            "send_mms requires at least one media source: media_url, camera_entity, image_entity, or image_path"
        )
        return None

    twilio_args: dict[str, object] = {
        "to": to_number,
        "from_": from_number,
        "media_url": media_urls,
    }
    if message:
        twilio_args[ATTR_BODY] = message

    try:
        twilio_message = await _async_create_message(client, **twilio_args)
        _LOGGER.info("MMS queued to %s with SID %s", to_number, twilio_message.sid)
        return {
            "message_sid": twilio_message.sid,
            "status": str(twilio_message.status),
            "to": to_number,
            "from": from_number,
        }
    except Exception as err:
        _LOGGER.error("Failed to send MMS to %s: %s", to_number, err)
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
        formatted_digits = "w" + "w".join(digits)
        twiml.play(digits=formatted_digits)

        # Convert TwiML to URL-encoded string
        twiml_str = str(twiml)
        twiml_url = f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

        # Update the call with the new TwiML using async client
        await client.calls(call_sid).update_async(url=twiml_url, method="POST")
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
            record_params["recording_status_callback_event"] = [
                "in-progress",
                "completed",
                "absent",
            ]

        # Add transcription if requested
        if transcribe:
            record_params["transcribe"] = True
            if transcribe_callback and webhook_url:
                record_params["transcribe_callback"] = webhook_url

        twiml.record(**record_params)

        # Convert TwiML to URL-encoded string
        twiml_str = str(twiml)
        twiml_url = f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

        # Update the call with the new TwiML using async client
        await client.calls(call_sid).update_async(url=twiml_url, method="POST")
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

        # Update the call with the new TwiML using async client
        await client.calls(call_sid).update_async(url=twiml_url, method="POST")
        _LOGGER.info("Paused call %s for %s seconds", call_sid, length)
    except Exception as err:
        _LOGGER.error("Failed to pause call %s: %s", call_sid, err)
