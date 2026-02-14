"""Twilio notification platforms for SMS, MMS, and Voice Calls."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
import re
import time
from typing import Any, cast
import urllib.parse

from twilio.base.exceptions import TwilioRestException
from twilio.twiml.voice_response import Gather, Start, VoiceResponse

from homeassistant.components.notify import NotifyEntity
from homeassistant.components.notify.const import ATTR_DATA, ATTR_TARGET
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_MEDIAURL,
    CONF_AUTOMATIC_PUNCTUATION,
    CONF_CALL_TARGETS,
    CONF_CALL_TARGETS_BY_NUMBER,
    CONF_FINISH_ON_KEY,
    CONF_FROM_NUMBER,
    CONF_LANGUAGE,
    CONF_NUM_DIGITS,
    CONF_PARTIAL_RESULTS,
    CONF_PHONE_NUMBERS,
    CONF_PHRASE_MAPPINGS,
    CONF_PROFANITY_FILTER,
    CONF_SMS_TARGETS,
    CONF_SMS_TARGETS_BY_NUMBER,
    CONF_TIMEOUT,
    CONF_TRANSCRIBE_LANGUAGE,
    CONF_VOICE,
    DATA_TWILIO,
    DEFAULT_FINISH_ON_KEY,
    DEFAULT_LANGUAGE,
    DEFAULT_NUM_DIGITS,
    DEFAULT_TIMEOUT,
    DEFAULT_TRANSCRIBE_LANGUAGE,
    DEFAULT_VOICE,
    DOMAIN,
)
from .helper import make_call, make_simple_call

_LOGGER = logging.getLogger(__name__)
MAX_MMS_MEDIA_SIZE_BYTES = 5 * 1024 * 1024

# Notify service attributes
ATTR_CALL_TYPE = "call_type"
ATTR_TWIML_URL = "twiml_url"
ATTR_GATHER_ENABLED = "gather_enabled"
ATTR_RECORD_ENABLED = "record_enabled"
ATTR_TRANSCRIBE_ENABLED = "transcribe_enabled"
ATTR_GATHER_CONFIG = "gather_config"
ATTR_TRANSCRIBE_CONFIG = "transcribe"
ATTR_STATUS_CALLBACK = "status_callback"
ATTR_STATUS_CALLBACK_METHOD = "status_callback_method"
ATTR_CAMERA_ENTITY = "camera_entity"
ATTR_IMAGE_ENTITY = "image_entity"
ATTR_IMAGE_PATH = "image_path"

# Call types
CALL_TYPE_SIMPLE = "simple"
CALL_TYPE_TWIML = "twiml"
CALL_TYPE_INTERACTIVE = "interactive"
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
ISSUE_ID_MISSING_TARGET_MAPPING = "missing_target_mapping"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Twilio notify entities for a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    twilio_client = entry_data.get(DATA_TWILIO)
    webhook_url = entry_data.get("webhook_url")

    if not twilio_client:
        _LOGGER.error("Twilio client not found for entry %s", entry.entry_id)
        return

    options = getattr(entry, "options", {}) or {}
    data = getattr(entry, "data", {}) or {}

    def _entry_value(key: str, default: Any) -> Any:
        """Get option from options first, fallback to entry data."""
        if key in options:
            return options.get(key, default)
        return data.get(key, default)

    configured_numbers = _entry_value(CONF_PHONE_NUMBERS, [])
    if not isinstance(configured_numbers, list):
        configured_numbers = []
    configured_numbers = [
        str(number).strip() for number in configured_numbers if str(number).strip()
    ]
    sms_targets = _entry_value(CONF_SMS_TARGETS, [])
    if not isinstance(sms_targets, list):
        sms_targets = []
    sms_targets = [str(target).strip() for target in sms_targets if str(target).strip()]
    call_targets = _entry_value(CONF_CALL_TARGETS, [])
    if not isinstance(call_targets, list):
        call_targets = []
    call_targets = [
        str(target).strip() for target in call_targets if str(target).strip()
    ]
    sms_targets_by_number = _entry_value(CONF_SMS_TARGETS_BY_NUMBER, {})
    if not isinstance(sms_targets_by_number, dict):
        sms_targets_by_number = {}
    call_targets_by_number = _entry_value(CONF_CALL_TARGETS_BY_NUMBER, {})
    if not isinstance(call_targets_by_number, dict):
        call_targets_by_number = {}

    # Backward compatibility for installs that still have single from_number option.
    if not configured_numbers:
        fallback_number = _entry_value(CONF_FROM_NUMBER, "")
        if isinstance(fallback_number, str) and fallback_number:
            configured_numbers = [fallback_number]

    if not configured_numbers:
        _LOGGER.warning("Skipping Twilio notify setup: no phone numbers are configured")
        return

    voice = _entry_value(CONF_VOICE, DEFAULT_VOICE)
    language = _entry_value(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    phrase_mappings = _entry_value(CONF_PHRASE_MAPPINGS, {})
    if not isinstance(phrase_mappings, dict):
        phrase_mappings = {}

    missing_mappings: list[str] = []
    entities: list[NotifyEntity] = []
    for number in configured_numbers:
        number_sms_targets = sms_targets_by_number.get(number, sms_targets)
        if not isinstance(number_sms_targets, list):
            number_sms_targets = sms_targets
        number_sms_targets = [
            str(target).strip() for target in number_sms_targets if str(target).strip()
        ]
        number_call_targets = call_targets_by_number.get(number, call_targets)
        if not isinstance(number_call_targets, list):
            number_call_targets = call_targets
        number_call_targets = [
            str(target).strip() for target in number_call_targets if str(target).strip()
        ]

        if not number_sms_targets and not number_call_targets:
            missing_mappings.append(number)
            # Fallback: create generic per-number entities until explicit mappings exist.
            entities.append(
                TwilioSMSNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=None,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )
            entities.append(
                TwilioCallNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=None,
                    voice=voice,
                    language=language,
                    phrase_mappings=phrase_mappings,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )
            continue

        for target in number_sms_targets:
            entities.append(
                TwilioSMSNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=target,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )
        for target in number_call_targets:
            entities.append(
                TwilioCallNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=target,
                    voice=voice,
                    language=language,
                    phrase_mappings=phrase_mappings,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )

    issue_id = f"{ISSUE_ID_MISSING_TARGET_MAPPING}_{entry.entry_id}"
    if missing_mappings:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ID_MISSING_TARGET_MAPPING,
            translation_placeholders={"numbers": ", ".join(missing_mappings)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    if not entities:
        # Last-resort fallback: create per-number generic entities so notify stays usable.
        for number in configured_numbers:
            entities.append(
                TwilioSMSNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=None,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )
            entities.append(
                TwilioCallNotificationEntity(
                    twilio_client=twilio_client,
                    from_number=number,
                    target_number=None,
                    voice=voice,
                    language=language,
                    phrase_mappings=phrase_mappings,
                    webhook_url=webhook_url,
                    entry_id=entry.entry_id,
                )
            )
        _LOGGER.warning(
            "No target mappings resolved; created generic Twilio notify entities for configured numbers"
        )

    async_add_entities(entities)


def _phone_number_key(phone_number: str) -> str:
    """Normalize phone number for ids."""
    return "".join(char for char in phone_number if char.isalnum())


def _is_valid_target_phone_number(value: str) -> bool:
    """Return True if target looks like a valid E.164 phone number."""
    return bool(PHONE_PATTERN.match(value.strip()))


class TwilioSMSNotificationEntity(NotifyEntity):
    """Twilio notify entity for SMS/MMS."""

    _attr_should_poll = False

    def __init__(
        self,
        twilio_client: Any,
        from_number: str,
        target_number: str | None,
        webhook_url: str | None,
        entry_id: str,
    ) -> None:
        """Initialize the entity."""
        self.client = twilio_client
        self.from_number = from_number
        self.target_number = target_number
        self.webhook_url = webhook_url
        target_key = _phone_number_key(target_number) if target_number else "any"
        self._attr_unique_id = (
            f"{entry_id}_twilio_sms_{_phone_number_key(from_number)}_{target_key}"
        )
        self._attr_name = (
            f"Twilio SMS {from_number} to {target_number}"
            if target_number
            else f"Twilio SMS {from_number}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry_id}_{_phone_number_key(from_number)}")},
            "name": f"Twilio {from_number}",
            "manufacturer": "Twilio",
            "model": "Phone Number",
        }
        self._attr_icon = "mdi:message-text-fast"

    def _get_external_base_url(self) -> str | None:
        """Return configured Home Assistant external URL, if available."""
        external_url = getattr(self.hass.config, "external_url", None)
        if not external_url:
            _LOGGER.warning(
                "Cannot attach entity/file images to MMS: Home Assistant external_url is not configured"
            )
            return None

        return external_url.rstrip("/")

    async def _async_get_entity_snapshot(
        self, entity_id: str
    ) -> tuple[str, bytes] | None:
        """Fetch snapshot bytes for a camera/image entity."""
        domain = entity_id.split(".", maxsplit=1)[0]
        if domain == "camera":
            from homeassistant.components.camera import (
                async_get_image as camera_get_image,
            )

            snapshot = await camera_get_image(self.hass, entity_id)
            return snapshot.content_type, snapshot.content

        if domain == "image":
            from homeassistant.components.image import (
                async_get_image as image_get_image,
            )

            snapshot = await image_get_image(self.hass, entity_id)
            return snapshot.content_type, snapshot.content

        _LOGGER.warning("Unsupported entity domain for MMS attachment: %s", entity_id)
        return None

    async def _build_entity_media_url(self, entity_id: str) -> str | None:
        """Create snapshot file for entity and return external /local URL."""
        external_base = self._get_external_base_url()
        if not external_base:
            return None

        try:
            snapshot_data = await self._async_get_entity_snapshot(entity_id)
            if snapshot_data is None:
                return None
            content_type, content = snapshot_data
        except HomeAssistantError as err:
            _LOGGER.error("Failed to get snapshot from %s: %s", entity_id, err)
            return None

        if len(content) > MAX_MMS_MEDIA_SIZE_BYTES:
            _LOGGER.warning(
                "Entity snapshot is too large for MMS (max 5MB): %s", entity_id
            )
            return None

        extension = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/gif": "gif",
            "image/webp": "webp",
        }.get(content_type.lower(), "jpg")

        snapshot_dir = Path(self.hass.config.config_dir) / "www" / "twilio_snapshots"
        await self.hass.async_add_executor_job(
            lambda: snapshot_dir.mkdir(parents=True, exist_ok=True)
        )
        safe_entity_id = entity_id.replace(".", "_")
        filename = f"{safe_entity_id}_{int(time.time() * 1000)}.{extension}"
        snapshot_path = snapshot_dir / filename
        await self.hass.async_add_executor_job(snapshot_path.write_bytes, content)
        return f"{external_base}/local/twilio_snapshots/{filename}"

    def _build_file_media_url(self, image_path: str) -> str | None:
        """Build a publicly reachable media URL for a local image file."""
        external_base = self._get_external_base_url()
        if not external_base:
            return None

        path = Path(image_path)
        if not path.exists():
            _LOGGER.error("Image file not found: %s", image_path)
            return None
        if path.stat().st_size > MAX_MMS_MEDIA_SIZE_BYTES:
            _LOGGER.warning("Image file is too large for MMS (max 5MB): %s", image_path)
            return None

        # Only files under <config>/www are exposed via /local.
        www_dir = Path(self.hass.config.config_dir) / "www"
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

    async def async_send_message(
        self, message: str = "", title: str | None = None, **kwargs: Any
    ) -> None:
        """Send SMS/MMS to specified target user."""
        del title
        targets = (
            [self.target_number] if self.target_number else kwargs.get(ATTR_TARGET)
        )
        data = kwargs.get(ATTR_DATA) or {}
        twilio_args: dict[str, str | list[str]] = {
            "body": message,
            "from_": self.from_number,
        }

        # Handle media URLs for MMS
        media_urls: list[str] = []

        # Support direct media_url parameter (existing functionality)
        if ATTR_MEDIAURL in data:
            urls = data[ATTR_MEDIAURL]
            if isinstance(urls, str):
                media_urls.append(urls)
            elif isinstance(urls, list):
                media_urls.extend(urls)

        # Support camera entity
        if ATTR_CAMERA_ENTITY in data:
            if camera_url := await self._build_entity_media_url(
                data[ATTR_CAMERA_ENTITY]
            ):
                _LOGGER.debug("Using camera snapshot media URL for MMS attachment.")
                media_urls.append(camera_url)

        # Support image entity
        if ATTR_IMAGE_ENTITY in data:
            if image_url := await self._build_entity_media_url(data[ATTR_IMAGE_ENTITY]):
                _LOGGER.debug("Using image snapshot media URL for MMS attachment.")
                media_urls.append(image_url)

        # Support image file path
        if ATTR_IMAGE_PATH in data:
            if image_url := self._build_file_media_url(data[ATTR_IMAGE_PATH]):
                media_urls.append(image_url)

        # Add media URLs if any were collected
        if media_urls:
            twilio_args[ATTR_MEDIAURL] = media_urls

        # Add status callback if configured
        if (
            ATTR_STATUS_CALLBACK in data
            and data[ATTR_STATUS_CALLBACK]
            and self.webhook_url
        ):
            twilio_args["status_callback"] = self.webhook_url
            # Set status callback method if specified
            method = data.get(ATTR_STATUS_CALLBACK_METHOD, "POST").upper()
            if method in ["POST", "GET", "PUT"]:
                twilio_args["status_callback_method"] = method
            else:
                _LOGGER.warning(
                    "Invalid status_callback_method: %s, using POST", method
                )
                twilio_args["status_callback_method"] = "POST"

        if not targets:
            _LOGGER.warning("At least 1 target is required")
            return

        valid_targets = [
            target
            for target in targets
            if isinstance(target, str) and _is_valid_target_phone_number(target)
        ]
        invalid_targets = [target for target in targets if target not in valid_targets]
        for target in invalid_targets:
            _LOGGER.warning("Skipping invalid target phone number: %s", target)

        if not valid_targets:
            _LOGGER.warning("No valid target phone numbers were provided")
            return

        for target in valid_targets:
            try:
                create_async = getattr(self.client.messages, "create_async", None)
                if create_async and inspect.iscoroutinefunction(create_async):
                    await create_async(to=target, **twilio_args)
                else:
                    await self.hass.async_add_executor_job(
                        lambda: self.client.messages.create(to=target, **twilio_args)
                    )
                _LOGGER.debug("SMS/MMS sent to %s", target)
            except TwilioRestException as exc:
                _LOGGER.error("Failed to send SMS/MMS to %s: %s", target, exc)


class TwilioCallNotificationEntity(NotifyEntity):
    """Twilio notify entity for Voice Calls."""

    _attr_should_poll = False

    def __init__(
        self,
        twilio_client,
        from_number,
        target_number: str | None,
        voice=DEFAULT_VOICE,
        language=DEFAULT_LANGUAGE,
        phrase_mappings=None,
        webhook_url=None,
        entry_id: str = "",
    ):
        """Initialize the entity."""
        self.client = twilio_client
        self.from_number = from_number
        self.target_number = target_number
        self.voice = voice
        self.language = language
        self.phrase_mappings = phrase_mappings or {}
        self.webhook_url = webhook_url
        target_key = _phone_number_key(target_number) if target_number else "any"
        self._attr_unique_id = (
            f"{entry_id}_twilio_call_{_phone_number_key(from_number)}_{target_key}"
        )
        self._attr_name = (
            f"Twilio Call {from_number} to {target_number}"
            if target_number
            else f"Twilio Call {from_number}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{_phone_number_key(from_number)}")},
            name=f"Twilio {from_number}",
            manufacturer="Twilio",
            model="Phone Number",
        )
        self._attr_icon = "mdi:phone-in-talk"

    async def async_send_message(
        self, message: str = "", title: str | None = None, **kwargs: Any
    ) -> None:
        """Make voice call to specified target users."""
        del title
        targets = cast(
            list[str],
            [self.target_number] if self.target_number else kwargs.get(ATTR_TARGET),
        )

        valid_targets = [
            target
            for target in targets
            if isinstance(target, str) and _is_valid_target_phone_number(target)
        ]
        invalid_targets = [target for target in targets if target not in valid_targets]
        for target in invalid_targets:
            _LOGGER.warning("Skipping invalid target phone number: %s", target)

        if not valid_targets:
            _LOGGER.warning("No valid target phone numbers were provided")
            return

        data = kwargs.get(ATTR_DATA) or {}
        call_type = data.get(ATTR_CALL_TYPE, CALL_TYPE_SIMPLE)

        for target in valid_targets:
            await self._async_make_call(target, message, call_type, data)

    async def _async_make_call(
        self, target: str, message: str, call_type: str, data: dict[str, Any]
    ) -> None:
        """Make a call asynchronously."""
        try:
            if call_type == CALL_TYPE_TWIML:
                # Use custom TwiML URL
                twiml_url = data.get(ATTR_TWIML_URL)
                if not twiml_url:
                    _LOGGER.error("TwiML URL required for twiml call type")
                    return
                await self._make_twiml_call(target, twiml_url, data)

            elif call_type == CALL_TYPE_INTERACTIVE:
                # Generate interactive TwiML with gather, record, transcribe
                twiml_url = self._generate_interactive_twiml_url(message, data)
                await self._make_twiml_call(target, twiml_url, data)

            else:
                # Simple message call using Twimlet
                await self._make_simple_call(target, message, data)

            _LOGGER.debug("Call initiated to %s", target)

        except TwilioRestException as exc:
            _LOGGER.error("Failed to initiate call to %s: %s", target, exc)

    async def _make_simple_call(
        self, target: str, message: str, data: dict[str, Any]
    ) -> None:
        """Make a simple call with a message.

        Note: This method uses Twimlets, which is a legacy Twilio service.
        For production use, consider hosting your own TwiML endpoints.
        """
        # Determine status callback settings
        status_callback = None
        status_callback_method = "POST"

        if (
            ATTR_STATUS_CALLBACK in data
            and data[ATTR_STATUS_CALLBACK]
            and self.webhook_url
        ):
            status_callback = self.webhook_url
            status_callback_method = data.get(ATTR_STATUS_CALLBACK_METHOD, "POST")

        # Use helper function to make the call
        await make_simple_call(
            client=self.client,
            to_number=target,
            from_number=self.from_number,
            message=message,
            hass=self.hass,
            status_callback=status_callback,
            status_callback_method=status_callback_method,
        )

    async def _make_twiml_call(
        self, target: str, twiml_url: str, data: dict[str, Any]
    ) -> None:
        """Make a call with custom TwiML."""
        # Determine status callback settings
        status_callback = None
        status_callback_method = "POST"

        if (
            ATTR_STATUS_CALLBACK in data
            and data[ATTR_STATUS_CALLBACK]
            and self.webhook_url
        ):
            status_callback = self.webhook_url
            status_callback_method = data.get(ATTR_STATUS_CALLBACK_METHOD, "POST")

        # Use helper function to make the call
        await make_call(
            client=self.client,
            to_number=target,
            from_number=self.from_number,
            twiml_url=twiml_url,
            hass=self.hass,
            status_callback=status_callback,
            status_callback_method=status_callback_method,
        )

    def _generate_interactive_twiml_url(
        self, message: str, data: dict[str, Any]
    ) -> str:
        """Generate TwiML for interactive call.

        IMPORTANT: This is a simplified implementation using Twimlets for basic functionality.

        For production use with full interactive features (phrase-to-key mappings,
        live transcription, status callbacks), you should:
        1. Host a webhook endpoint in your Home Assistant instance
        2. Generate TwiML with <Gather> for DTMF collection
        3. Use <Start><Stream> with transcription for real-time transcription
        4. Handle status callbacks for real-time updates

        Note: Twimlets is a legacy service and URL-encoded TwiML has length limitations.
        For complex TwiML, consider implementing a dedicated webhook endpoint.
        """
        gather_enabled = data.get(ATTR_GATHER_ENABLED, False)
        record_enabled = data.get(ATTR_RECORD_ENABLED, False)
        transcribe_enabled = data.get(ATTR_TRANSCRIBE_ENABLED, False)

        # Create TwiML response
        response = VoiceResponse()

        # Get transcription configuration
        transcribe_config = data.get(ATTR_TRANSCRIBE_CONFIG, {})

        # Use Stream transcription for real-time transcription with enhanced options
        if transcribe_enabled and transcribe_config and self.webhook_url:
            # Start streaming transcription
            start = cast(Start, response.start())
            transcription_params = {
                "status_callback_url": self.webhook_url,
                "status_callback_method": "POST",
            }

            # Add enhanced transcription options
            if CONF_TRANSCRIBE_LANGUAGE in transcribe_config:
                transcription_params["language_code"] = transcribe_config[
                    CONF_TRANSCRIBE_LANGUAGE
                ]
            else:
                transcription_params["language_code"] = DEFAULT_TRANSCRIBE_LANGUAGE

            if CONF_PROFANITY_FILTER in transcribe_config:
                transcription_params["profanity_filter"] = transcribe_config[
                    CONF_PROFANITY_FILTER
                ]

            if CONF_PARTIAL_RESULTS in transcribe_config:
                transcription_params["partial_results"] = transcribe_config[
                    CONF_PARTIAL_RESULTS
                ]

            if CONF_AUTOMATIC_PUNCTUATION in transcribe_config:
                transcription_params["enable_automatic_punctuation"] = (
                    transcribe_config[CONF_AUTOMATIC_PUNCTUATION]
                )

            start.transcription(**transcription_params)

        if gather_enabled:
            gather_config = data.get(ATTR_GATHER_CONFIG, {})
            timeout = gather_config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            num_digits = gather_config.get(CONF_NUM_DIGITS, DEFAULT_NUM_DIGITS)
            finish_on_key = gather_config.get(CONF_FINISH_ON_KEY, DEFAULT_FINISH_ON_KEY)

            gather = Gather(
                timeout=timeout,
                num_digits=num_digits,
                finish_on_key=finish_on_key,
            )
            gather.say(message, voice=self.voice, language=self.language)
            response.append(gather)
        else:
            response.say(message, voice=self.voice, language=self.language)

        if record_enabled:
            # Use basic recording (not streaming)
            record_params = {
                "transcribe": transcribe_enabled
                and not transcribe_config,  # Use basic transcription only if no advanced config
            }

            # Add transcription callback for basic transcription
            if transcribe_enabled and not transcribe_config and self.webhook_url:
                record_params["transcribe_callback"] = self.webhook_url

            response.record(**record_params)

        # Convert TwiML to URL-encoded format for Twimlet
        twiml_str = str(response)
        # Use a Twimlet echo service or host your own endpoint
        return f"https://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

    def _get_webhook_id(self) -> str:
        """Get the webhook ID for this integration."""
        if self.hass and DOMAIN in self.hass.data:
            for entry_data in self.hass.data[DOMAIN].values():
                if isinstance(entry_data, dict) and "webhook_id" in entry_data:
                    return entry_data["webhook_id"]
        return "twilio-webhook"
