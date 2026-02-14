"""Tests for Twilio notify entities."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.notify.const import ATTR_DATA

from custom_components.twilio.const import (
    ATTR_MEDIAURL,
    CONF_CALL_TARGETS,
    CONF_FROM_NUMBER,
    CONF_PHONE_NUMBERS,
    CONF_SMS_TARGETS,
    DATA_TWILIO,
    DOMAIN,
)
from custom_components.twilio.notify import (
    ATTR_CAMERA_ENTITY,
    ATTR_IMAGE_ENTITY,
    ATTR_IMAGE_PATH,
    TwilioCallNotificationEntity,
    TwilioSMSNotificationEntity,
    async_setup_entry,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_setup_entry_creates_entities_for_selected_numbers(
    hass, mock_twilio_client
):
    """Setup creates SMS and Call notify entities per configured phone number."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {
        CONF_PHONE_NUMBERS: ["+1234567890", "+1098765432"],
        CONF_SMS_TARGETS: ["+14155550123"],
        CONF_CALL_TARGETS: ["+14155550124"],
        CONF_FROM_NUMBER: "+1234567890",
    }

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_TWILIO: mock_twilio_client,
        "webhook_url": "https://example.com/webhook",
    }

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 4
    assert (
        sum(isinstance(entity, TwilioSMSNotificationEntity) for entity in entities) == 2
    )
    assert (
        sum(isinstance(entity, TwilioCallNotificationEntity) for entity in entities)
        == 2
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_setup_entry_uses_legacy_from_number_fallback(
    hass, mock_twilio_client
):
    """Setup keeps working when only legacy from_number is stored."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {
        CONF_FROM_NUMBER: "+1234567890",
        CONF_SMS_TARGETS: ["+14155550123"],
        CONF_CALL_TARGETS: ["+14155550124"],
    }

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_TWILIO: mock_twilio_client,
        "webhook_url": "https://example.com/webhook",
    }

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_setup_entry_creates_fallback_entities_without_targets(
    hass, mock_twilio_client
):
    """Setup should still create generic entities when no targets are mapped."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {
        CONF_PHONE_NUMBERS: ["+1234567890"],
        CONF_FROM_NUMBER: "+1234567890",
        CONF_SMS_TARGETS: [],
        CONF_CALL_TARGETS: [],
    }

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_TWILIO: mock_twilio_client,
        "webhook_url": "https://example.com/webhook",
    }

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]
    assert len(entities) == 2
    assert isinstance(entities[0], TwilioSMSNotificationEntity)
    assert isinstance(entities[1], TwilioCallNotificationEntity)


@pytest.mark.unit
def test_notify_entities_include_device_info(mock_twilio_client):
    """SMS/Call entities should share per-number device info identifiers."""
    sms = TwilioSMSNotificationEntity(
        twilio_client=mock_twilio_client,
        from_number="+1234567890",
        target_number="+14155550123",
        webhook_url=None,
        entry_id="entry-1",
    )
    call = TwilioCallNotificationEntity(
        twilio_client=mock_twilio_client,
        from_number="+1234567890",
        target_number="+14155550124",
        webhook_url=None,
        entry_id="entry-1",
    )

    assert sms.device_info is not None
    assert call.device_info is not None
    assert sms.device_info.get("identifiers") == call.device_info.get("identifiers")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_message(hass, mock_twilio_client):
    """Test sending SMS message."""
    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message("Test message", "Test title")

    mock_twilio_client.messages.create.assert_called_once()
    call_args = mock_twilio_client.messages.create.call_args[1]
    assert call_args["to"] == "+14155550123"
    assert call_args["from_"] == "+1234567890"
    assert call_args["body"] == "Test message"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_mms(hass, mock_twilio_client):
    """Test sending MMS message with media."""
    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message(
        "Test message",
        "Test title",
        **{
            ATTR_DATA: {ATTR_MEDIAURL: ["https://example.com/image.jpg"]},
        },
    )

    mock_twilio_client.messages.create.assert_called_once()
    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    assert "https://example.com/image.jpg" in call_args[ATTR_MEDIAURL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_to_fixed_target(hass, mock_twilio_client):
    """Entity sends SMS only to its configured target."""
    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550124",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message("Test message", "Another test message")

    mock_twilio_client.messages.create.assert_called_once()
    assert mock_twilio_client.messages.create.call_args.kwargs["to"] == "+14155550124"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_skips_invalid_entity_target(hass, mock_twilio_client):
    """Invalid configured entity target is ignored."""
    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "invalid",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message("Test message")

    mock_twilio_client.messages.create.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_mms_camera_entity(hass, mock_twilio_client, tmp_path):
    """Test sending MMS using camera snapshot exported under /local."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)

    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    with patch(
        "custom_components.twilio.notify.TwilioSMSNotificationEntity._async_get_entity_snapshot",
        new=AsyncMock(return_value=("image/jpeg", b"jpeg-data")),
    ):
        await entity.async_send_message(
            "Camera snapshot",
            "Message Title",
            **{
                ATTR_DATA: {
                    ATTR_CAMERA_ENTITY: "camera.front_door",
                },
            },
        )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    media_url = call_args[ATTR_MEDIAURL][0]
    assert media_url.startswith(
        "https://ha.example.com/local/twilio_snapshots/camera_front_door_"
    )
    assert (
        len(
            list(
                (Path(tmp_path) / "www" / "twilio_snapshots").glob(
                    "camera_front_door_*.jpg"
                )
            )
        )
        == 1
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_mms_image_entity(hass, mock_twilio_client, tmp_path):
    """Test sending MMS using image snapshot exported under /local."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)

    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    with patch(
        "custom_components.twilio.notify.TwilioSMSNotificationEntity._async_get_entity_snapshot",
        new=AsyncMock(return_value=("image/png", b"png-data")),
    ):
        await entity.async_send_message(
            "Image snapshot",
            "Message Title",
            **{
                ATTR_DATA: {
                    ATTR_IMAGE_ENTITY: "image.front_door",
                },
            },
        )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    media_url = call_args[ATTR_MEDIAURL][0]
    assert media_url.startswith(
        "https://ha.example.com/local/twilio_snapshots/image_front_door_"
    )
    assert (
        len(
            list(
                (Path(tmp_path) / "www" / "twilio_snapshots").glob(
                    "image_front_door_*.png"
                )
            )
        )
        == 1
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_mms_image_path_from_www(
    hass, mock_twilio_client, tmp_path
):
    """Test sending MMS using local file path under <config>/www."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)
    image_file = Path(tmp_path) / "www" / "snapshots" / "front.jpg"
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"test-image")

    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message(
        "File snapshot",
        "Message Title",
        **{
            ATTR_DATA: {
                ATTR_IMAGE_PATH: str(image_file),
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    assert (
        "https://ha.example.com/local/snapshots/front.jpg" in call_args[ATTR_MEDIAURL]
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_send_mms_image_path_too_large(
    hass, mock_twilio_client, tmp_path
):
    """Test oversized MMS file is skipped."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)
    image_file = Path(tmp_path) / "www" / "snapshots" / "large.jpg"
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"x" * (5 * 1024 * 1024 + 1))

    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message(
        "Oversized file",
        "Message Title",
        **{
            ATTR_DATA: {
                ATTR_IMAGE_PATH: str(image_file),
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL not in call_args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_entity_attachment_without_external_url_logs_warning(
    hass, mock_twilio_client, caplog
):
    """Test camera/image attachment is skipped when external_url is missing."""
    entity = TwilioSMSNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        None,
        "entry-1",
    )
    entity.hass = hass

    await entity.async_send_message(
        "No external URL",
        "Message Title",
        **{
            ATTR_DATA: {
                ATTR_CAMERA_ENTITY: "camera.front_door",
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL not in call_args
    assert "external_url is not configured" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_entity_async_make_call_simple(hass, mock_twilio_client):
    """Test making a simple call async."""
    entity = TwilioCallNotificationEntity(
        mock_twilio_client, "+1234567890", "+14155550123"
    )
    entity.hass = hass

    await entity._async_make_call("+14155550123", "Hello world", "simple", {})

    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["to"] == "+14155550123"
    assert call_args["from_"] == "+1234567890"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_entity_async_make_call_twiml(hass, mock_twilio_client):
    """Test making a call with custom TwiML URL."""
    entity = TwilioCallNotificationEntity(
        mock_twilio_client, "+1234567890", "+14155550123"
    )
    entity.hass = hass

    await entity._async_make_call(
        "+14155550123", "", "twiml", {"twiml_url": "https://example.com/twiml"}
    )

    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["url"] == "https://example.com/twiml"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_entity_async_make_call_interactive(hass, mock_twilio_client):
    """Test making an interactive call."""
    entity = TwilioCallNotificationEntity(
        mock_twilio_client,
        "+1234567890",
        "+14155550123",
        webhook_url="https://example.com/webhook",
    )
    entity.hass = hass

    await entity._async_make_call(
        "+14155550123",
        "Hello world",
        "interactive",
        {
            "gather_enabled": True,
            "record_enabled": True,
            "transcribe_enabled": True,
        },
    )

    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_entity_skips_invalid_entity_target(hass, mock_twilio_client):
    """Invalid configured call target is ignored."""
    entity = TwilioCallNotificationEntity(mock_twilio_client, "+1234567890", "invalid")
    entity.hass = hass

    await entity.async_send_message("Hello world")
    mock_twilio_client.calls.create_async.assert_not_called()
