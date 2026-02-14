"""Twilio notification platforms for SMS, MMS, and Voice Calls."""

from __future__ import annotations

import logging
from typing import Any
import urllib.parse

from twilio.base.exceptions import TwilioRestException
from twilio.twiml.voice_response import VoiceResponse, Gather
import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_TARGET,
    PLATFORM_SCHEMA as NOTIFY_PLATFORM_SCHEMA,
    BaseNotificationService,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_FROM_NUMBER,
    CONF_VOICE,
    CONF_LANGUAGE,
    CONF_PHRASE_MAPPINGS,
    CONF_TIMEOUT,
    CONF_NUM_DIGITS,
    CONF_FINISH_ON_KEY,
    DATA_TWILIO,
    DOMAIN,
    ATTR_MEDIAURL,
    DEFAULT_TIMEOUT,
    DEFAULT_NUM_DIGITS,
    DEFAULT_FINISH_ON_KEY,
    DEFAULT_VOICE,
    DEFAULT_LANGUAGE,
)

_LOGGER = logging.getLogger(__name__)

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

    # Get Twilio client from hass.data
    twilio_client = None
    if DATA_TWILIO in hass.data:
        twilio_client = hass.data[DATA_TWILIO]
    elif DOMAIN in hass.data:
        # Try to get from config entry
        for entry_id, entry_data in hass.data[DOMAIN].items():
            if DATA_TWILIO in entry_data:
                twilio_client = entry_data[DATA_TWILIO]
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
        )
    else:
        return TwilioSMSNotificationService(
            twilio_client,
            config[CONF_FROM_NUMBER],
        )


class TwilioSMSNotificationService(BaseNotificationService):
    """Implement the notification service for Twilio SMS/MMS."""

    def __init__(self, twilio_client, from_number):
        """Initialize the service."""
        self.client = twilio_client
        self.from_number = from_number

    def send_message(self, message: str = "", **kwargs: Any) -> None:
        """Send SMS/MMS to specified target user."""
        targets = kwargs.get(ATTR_TARGET)
        data = kwargs.get(ATTR_DATA) or {}
        twilio_args = {"body": message, "from_": self.from_number}

        # Add media URLs for MMS
        if ATTR_MEDIAURL in data:
            media_urls = data[ATTR_MEDIAURL]
            if isinstance(media_urls, str):
                media_urls = [media_urls]
            twilio_args[ATTR_MEDIAURL] = media_urls

        if not targets:
            _LOGGER.warning("At least 1 target is required")
            return

        for target in targets:
            try:
                self.client.messages.create(to=target, **twilio_args)
                _LOGGER.debug("SMS/MMS sent to %s", target)
            except TwilioRestException as exc:
                _LOGGER.error("Failed to send SMS/MMS to %s: %s", target, exc)


class TwilioCallNotificationService(BaseNotificationService):
    """Implement the notification service for Twilio Voice Calls with interactive features."""

    def __init__(
        self,
        twilio_client,
        from_number,
        voice=DEFAULT_VOICE,
        language=DEFAULT_LANGUAGE,
        phrase_mappings=None,
        hass=None,
    ):
        """Initialize the service."""
        self.client = twilio_client
        self.from_number = from_number
        self.voice = voice
        self.language = language
        self.phrase_mappings = phrase_mappings or {}
        self.hass = hass

    def send_message(self, message: str = "", **kwargs: Any) -> None:
        """Make voice call to specified target users."""
        if not (targets := kwargs.get(ATTR_TARGET)):
            _LOGGER.warning("At least 1 target is required")
            return

        data = kwargs.get(ATTR_DATA) or {}
        call_type = data.get(ATTR_CALL_TYPE, CALL_TYPE_SIMPLE)

        for target in targets:
            try:
                if call_type == CALL_TYPE_TWIML:
                    # Use custom TwiML URL
                    twiml_url = data.get(ATTR_TWIML_URL)
                    if not twiml_url:
                        _LOGGER.error("TwiML URL required for twiml call type")
                        continue
                    self._make_twiml_call(target, twiml_url)

                elif call_type == CALL_TYPE_INTERACTIVE:
                    # Generate interactive TwiML with gather, record, transcribe
                    twiml_url = self._generate_interactive_twiml_url(message, data)
                    self._make_twiml_call(target, twiml_url)

                else:
                    # Simple message call using Twimlet
                    self._make_simple_call(target, message)

                _LOGGER.debug("Call initiated to %s", target)

            except TwilioRestException as exc:
                _LOGGER.error("Failed to initiate call to %s: %s", target, exc)

    def _make_simple_call(self, target: str, message: str) -> None:
        """Make a simple call with a message."""
        if message.startswith(("http://", "https://")):
            twimlet_url = message
        else:
            twimlet_url = "http://twimlets.com/message?Message="
            twimlet_url += urllib.parse.quote(message, safe="")

        self.client.calls.create(
            to=target,
            from_=self.from_number,
            url=twimlet_url,
        )

    def _make_twiml_call(self, target: str, twiml_url: str) -> None:
        """Make a call with custom TwiML."""
        self.client.calls.create(
            to=target,
            from_=self.from_number,
            url=twiml_url,
        )

    def _generate_interactive_twiml_url(
        self, message: str, data: dict[str, Any]
    ) -> str:
        """Generate TwiML for interactive call.

        Note: In a production environment, you would host a TwiML endpoint
        that generates the appropriate TwiML response. This is a simplified
        version that uses Twimlet for basic functionality.

        For full interactive features (phrase-to-key mappings, live transcription),
        you need to:
        1. Host a webhook endpoint in your Home Assistant instance
        2. Generate TwiML with <Gather> for DTMF collection
        3. Use <Record> with transcribe=true for transcription
        4. Handle status callbacks for real-time updates
        """
        gather_enabled = data.get(ATTR_GATHER_ENABLED, False)
        record_enabled = data.get(ATTR_RECORD_ENABLED, False)
        transcribe_enabled = data.get(ATTR_TRANSCRIBE_ENABLED, False)

        # For now, create a basic TwiML response
        # In production, this should point to a hosted endpoint
        response = VoiceResponse()

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
            response.record(
                transcribe=transcribe_enabled,
                transcribe_callback="/api/webhook/" + self._get_webhook_id(),
            )

        # Convert TwiML to URL-encoded format for Twimlet
        twiml_str = str(response)
        # Use a Twimlet echo service or host your own endpoint
        return f"http://twimlets.com/echo?Twiml={urllib.parse.quote(twiml_str)}"

    def _get_webhook_id(self) -> str:
        """Get the webhook ID for this integration."""
        if self.hass and DOMAIN in self.hass.data:
            for entry_data in self.hass.data[DOMAIN].values():
                if isinstance(entry_data, dict) and "webhook_id" in entry_data:
                    return entry_data["webhook_id"]
        return "twilio-webhook"
