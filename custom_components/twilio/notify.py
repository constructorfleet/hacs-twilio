"""Twilio notification platforms for SMS, MMS, and Voice Calls."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, cast
import urllib.parse

from twilio.base.exceptions import TwilioRestException
from twilio.twiml.voice_response import Start, VoiceResponse, Gather
import voluptuous as vol

from homeassistant.components.notify import (
    PLATFORM_SCHEMA as NOTIFY_PLATFORM_SCHEMA,
    NotifyEntity,
)
from homeassistant.components.notify.const import (
    ATTR_DATA,
    ATTR_TARGET,
)
from homeassistant.components.notify.legacy import BaseNotificationService
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_FROM_NUMBER,
    CONF_VOICE,
    CONF_LANGUAGE,
    CONF_PHRASE_MAPPINGS,
    CONF_TIMEOUT,
    CONF_NUM_DIGITS,
    CONF_FINISH_ON_KEY,
    CONF_TRANSCRIBE_LANGUAGE,
    CONF_PROFANITY_FILTER,
    CONF_PARTIAL_RESULTS,
    CONF_AUTOMATIC_PUNCTUATION,
    DATA_TWILIO,
    DOMAIN,
    ATTR_MEDIAURL,
    DEFAULT_TIMEOUT,
    DEFAULT_NUM_DIGITS,
    DEFAULT_FINISH_ON_KEY,
    DEFAULT_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_TRANSCRIBE_LANGUAGE,
)
from .helper import make_call, make_simple_call

_LOGGER = logging.getLogger(__name__)
MAX_MMS_MEDIA_SIZE_BYTES = 5 * 1024 * 1024

# Platform types
PLATFORM_SMS = "sms"
PLATFORM_CALL = "call"

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
CONF_SMS_TARGET = "sms_target"
CONF_CALL_TARGET = "call_target"

# Call types
CALL_TYPE_SIMPLE = "simple"
CALL_TYPE_TWIML = "twiml"
CALL_TYPE_INTERACTIVE = "interactive"

PLATFORM_SCHEMA = NOTIFY_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_FROM_NUMBER): vol.All(
            cv.string,
            vol.Match(
                r"^\+?[1-9]\d{1,14}$|"
                r"^(?=.{1,11}$)[a-zA-Z0-9\s]*"
                r"[a-zA-Z][a-zA-Z0-9\s]*$"
            ),
        ),
        vol.Optional(CONF_VOICE, default=DEFAULT_VOICE): cv.string,
        vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): cv.string,
        vol.Optional(CONF_PHRASE_MAPPINGS, default={}): dict,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Twilio notify entities for a config entry."""
    domain_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not domain_data or DATA_TWILIO not in domain_data:
        _LOGGER.error("Twilio client not found for entry %s", entry.entry_id)
        return

    twilio_client = domain_data[DATA_TWILIO]
    webhook_url = domain_data.get("webhook_url")
    from_number = entry.options.get(CONF_FROM_NUMBER, "")

    sms_target = entry.options.get(CONF_SMS_TARGET, from_number)
    call_target = entry.options.get(CONF_CALL_TARGET, from_number)

    sms_service = TwilioSMSNotificationService(
        twilio_client, from_number, hass, webhook_url
    )
    call_service = TwilioCallNotificationService(
        twilio_client, from_number, hass=hass, webhook_url=webhook_url
    )

    async_add_entities(
        [
            TwilioNotifyEntity(
                unique_id=f"{entry.entry_id}_sms",
                name="Twilio SMS",
                notification_service=sms_service,
                target=sms_target,
            ),
            TwilioNotifyEntity(
                unique_id=f"{entry.entry_id}_call",
                name="Twilio Call",
                notification_service=call_service,
                target=call_target,
            ),
        ]
    )


class TwilioNotifyEntity(NotifyEntity):
    """Notify entity that proxies to a Twilio notification service."""

    _attr_should_poll = False

    def __init__(
        self,
        unique_id: str,
        name: str,
        notification_service: BaseNotificationService,
        target: str,
    ) -> None:
        """Initialize Twilio notify entity."""
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._service = notification_service
        self._target = target

    @property
    def available(self) -> bool:
        """Return whether the entity can send notifications."""
        return bool(
            getattr(self._service, "from_number", "")
            and self._target
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message through the wrapped Twilio service."""
        if not self.available:
            _LOGGER.error(
                "%s is unavailable: configure from_number and target in options",
                self.name,
            )
            return

        data: dict[str, Any] = {}
        if title:
            data["title"] = title

        await self._service.async_send_message(
            message,
            **{
                ATTR_TARGET: [self._target],
                ATTR_DATA: data,
            },
        )


def get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> BaseNotificationService | None:
    """Get the notification service."""
    # Determine platform type from config or discovery_info
    platform_type = PLATFORM_SMS
    if discovery_info:
        platform_type = discovery_info.get("platform_type", PLATFORM_SMS)

    # Get Twilio client and webhook info from hass.data
    twilio_client = None
    webhook_url = None
    if DATA_TWILIO in hass.data:
        twilio_client = hass.data[DATA_TWILIO]
    elif DOMAIN in hass.data:
        # Try to get from config entry
        for entry_id, entry_data in hass.data[DOMAIN].items():
            if DATA_TWILIO in entry_data:
                twilio_client = entry_data[DATA_TWILIO]
                webhook_url = entry_data.get("webhook_url")
                break

    if not twilio_client:
        _LOGGER.error("Twilio client not found in hass.data")
        return None

    if platform_type == PLATFORM_CALL:
        return TwilioCallNotificationService(
            twilio_client,
            config[CONF_FROM_NUMBER],
            config.get(CONF_VOICE, DEFAULT_VOICE),
            config.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            config.get(CONF_PHRASE_MAPPINGS, {}),
            hass,
            webhook_url,
        )
    else:
        return TwilioSMSNotificationService(
            twilio_client,
            config[CONF_FROM_NUMBER],
            hass,
            webhook_url,
        )


class TwilioSMSNotificationService(BaseNotificationService):
    """Implement the notification service for Twilio SMS/MMS."""

    def __init__(self, twilio_client, from_number, hass, webhook_url=None):
        """Initialize the service."""
        self.client = twilio_client
        self.from_number = from_number
        self.hass = hass
        self.webhook_url = webhook_url

    def _get_external_base_url(self) -> str | None:
        """Return configured Home Assistant external URL, if available."""
        if not self.hass:
            return None

        external_url = getattr(self.hass.config, "external_url", None)
        if not external_url:
            _LOGGER.warning(
                "Cannot attach entity/file images to MMS: Home Assistant external_url is not configured"
            )
            return None

        return external_url.rstrip("/")

    async def _async_get_entity_snapshot(self, entity_id: str) -> tuple[str, bytes] | None:
        """Fetch snapshot bytes for a camera/image entity."""
        domain = entity_id.split(".", maxsplit=1)[0]
        if domain == "camera":
            from homeassistant.components.camera import async_get_image as camera_get_image

            snapshot = await camera_get_image(self.hass, entity_id)
            return snapshot.content_type, snapshot.content

        if domain == "image":
            from homeassistant.components.image import async_get_image as image_get_image

            snapshot = await image_get_image(self.hass, entity_id)
            return snapshot.content_type, snapshot.content

        _LOGGER.warning("Unsupported entity domain for MMS attachment: %s", entity_id)
        return None

    async def _build_entity_media_url(self, entity_id: str) -> str | None:
        """Create snapshot file for entity and return external /local URL."""
        if not self.hass:
            return None

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

    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Send SMS/MMS to specified target user."""
        targets = kwargs.get(ATTR_TARGET)
        data = kwargs.get(ATTR_DATA) or {}
        twilio_args = {"body": message, "from_": self.from_number}

        # Handle media URLs for MMS
        media_urls = []

        # Support direct media_url parameter (existing functionality)
        if ATTR_MEDIAURL in data:
            urls = data[ATTR_MEDIAURL]
            if isinstance(urls, str):
                media_urls.append(urls)
            elif isinstance(urls, list):
                media_urls.extend(urls)

        # Support camera entity
        if ATTR_CAMERA_ENTITY in data:
            if camera_url := await self._build_entity_media_url(data[ATTR_CAMERA_ENTITY]):
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

        for target in targets:
            try:
                self.client.messages.create(to=target, **twilio_args)
                _LOGGER.debug("SMS/MMS sent to %s", target)
            except TwilioRestException as exc:
                _LOGGER.error("Failed to send SMS/MMS to %s: %s", target, exc)

    def send_message(self, message: str = "", **kwargs: Any) -> None:
        """Send message (sync wrapper)."""
        # Use hass to schedule the async task properly
        if self.hass:
            self.hass.async_create_task(self.async_send_message(message, **kwargs))
        else:
            _LOGGER.error("Cannot send message: HomeAssistant instance not available")


class TwilioCallNotificationService(BaseNotificationService):
    """Implement the notification service for Twilio Voice Calls with interactive features."""

    def __init__(
        self,
        twilio_client,
        from_number,
        voice=DEFAULT_VOICE,
        language=DEFAULT_LANGUAGE,
        phrase_mappings=None,
        hass: HomeAssistant | None = None,
        webhook_url=None,
    ):
        """Initialize the service."""
        self.client = twilio_client
        self.from_number = from_number
        self.voice = voice
        self.language = language
        self.phrase_mappings = phrase_mappings or {}
        self.webhook_url = webhook_url
        if hass:
            self.hass = hass

    def send_message(self, message: str = "", **kwargs: Any) -> None:
        """Make voice call to specified target users."""
        if not (targets := kwargs.get(ATTR_TARGET)):
            _LOGGER.warning("At least 1 target is required")
            return

        data = kwargs.get(ATTR_DATA) or {}
        call_type = data.get(ATTR_CALL_TYPE, CALL_TYPE_SIMPLE)

        # Schedule async calls for each target
        if self.hass:
            for target in targets:
                self.hass.async_create_task(
                    self._async_make_call(target, message, call_type, data)
                )
        else:
            _LOGGER.error("Cannot make calls: HomeAssistant instance not available")

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
