"""Tests for notify.py notification services."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.notify import ATTR_DATA, ATTR_TARGET

from custom_components.twilio.notify import (
    ATTR_CAMERA_ENTITY,
    ATTR_IMAGE_ENTITY,
    ATTR_IMAGE_PATH,
    NOTIFY_SERVICE_CALL,
    NOTIFY_SERVICE_SMS,
    TwilioSMSNotificationService,
    TwilioCallNotificationService,
    async_register_entry_notify_services,
    async_unregister_entry_notify_services,
    get_service,
)
from custom_components.twilio.const import (
    CONF_FROM_NUMBER,
    ATTR_MEDIAURL,
    DATA_TWILIO,
    DOMAIN,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_register_unregister_entry_notify_services(hass, mock_twilio_client):
    """Test config-entry notify services registration lifecycle."""
    services = await async_register_entry_notify_services(
        hass=hass,
        twilio_client=mock_twilio_client,
        webhook_url="https://example.com/webhook",
        from_number="+1234567890",
    )

    assert len(services) == 2
    assert hass.services.has_service("notify", NOTIFY_SERVICE_SMS)
    assert hass.services.has_service("notify", NOTIFY_SERVICE_CALL)

    await async_unregister_entry_notify_services(services)

    assert not hass.services.has_service("notify", NOTIFY_SERVICE_SMS)
    assert not hass.services.has_service("notify", NOTIFY_SERVICE_CALL)


@pytest.mark.unit
def test_get_service_sms(hass, mock_twilio_client):
    """Test getting SMS notification service."""
    hass.data[DATA_TWILIO] = mock_twilio_client
    
    config = {
        "from_number": "+1234567890",
    }
    
    service = get_service(hass, config, {"platform_type": "sms"})
    
    assert service is not None
    assert isinstance(service, TwilioSMSNotificationService)
    assert service.from_number == "+1234567890"


@pytest.mark.unit
def test_get_service_call(hass, mock_twilio_client):
    """Test getting call notification service."""
    hass.data[DATA_TWILIO] = mock_twilio_client
    
    config = {
        "from_number": "+1234567890",
        "voice": "alice",
        "language": "en-US",
    }
    
    service = get_service(hass, config, {"platform_type": "call"})
    
    assert service is not None
    assert isinstance(service, TwilioCallNotificationService)
    assert service.from_number == "+1234567890"
    assert service.voice == "alice"
    assert service.language == "en-US"


@pytest.mark.unit
def test_get_service_no_client(hass):
    """Test getting service with no Twilio client available."""
    config = {
        "from_number": "+1234567890",
    }
    
    service = get_service(hass, config)
    
    assert service is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_message(hass, mock_twilio_client):
    """Test sending SMS message."""
    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )
    
    await service.async_send_message(
        "Test message",
        **{ATTR_TARGET: ["+0987654321"]}
    )
    
    # Verify message was sent
    mock_twilio_client.messages.create.assert_called_once()
    call_args = mock_twilio_client.messages.create.call_args[1]
    assert call_args["to"] == "+0987654321"
    assert call_args["from_"] == "+1234567890"
    assert call_args["body"] == "Test message"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_mms(hass, mock_twilio_client):
    """Test sending MMS message with media."""
    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )
    
    await service.async_send_message(
        "Test message",
        **{
            ATTR_TARGET: ["+0987654321"],
            ATTR_DATA: {
                ATTR_MEDIAURL: ["https://example.com/image.jpg"]
            }
        }
    )
    
    # Verify MMS was sent
    mock_twilio_client.messages.create.assert_called_once()
    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    assert "https://example.com/image.jpg" in call_args[ATTR_MEDIAURL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_to_multiple_targets(hass, mock_twilio_client):
    """Test sending SMS to multiple targets."""
    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )
    
    await service.async_send_message(
        "Test message",
        **{ATTR_TARGET: ["+0987654321", "+1111111111"]}
    )
    
    # Verify message was sent to both targets
    assert mock_twilio_client.messages.create.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_mms_camera_entity(hass, mock_twilio_client, tmp_path):
    """Test sending MMS using camera snapshot exported under /local."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)

    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )

    with patch(
        "custom_components.twilio.notify.TwilioSMSNotificationService._async_get_entity_snapshot",
        new=AsyncMock(return_value=("image/jpeg", b"jpeg-data")),
    ):
        await service.async_send_message(
            "Camera snapshot",
            **{
                ATTR_TARGET: ["+0987654321"],
                ATTR_DATA: {
                    ATTR_CAMERA_ENTITY: "camera.front_door",
                },
            },
        )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    media_url = call_args[ATTR_MEDIAURL][0]
    assert media_url.startswith("https://ha.example.com/local/twilio_snapshots/camera_front_door_")
    assert len(list((Path(tmp_path) / "www" / "twilio_snapshots").glob("camera_front_door_*.jpg"))) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_mms_image_entity(hass, mock_twilio_client, tmp_path):
    """Test sending MMS using image snapshot exported under /local."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)

    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )

    with patch(
        "custom_components.twilio.notify.TwilioSMSNotificationService._async_get_entity_snapshot",
        new=AsyncMock(return_value=("image/png", b"png-data")),
    ):
        await service.async_send_message(
            "Image snapshot",
            **{
                ATTR_TARGET: ["+0987654321"],
                ATTR_DATA: {
                    ATTR_IMAGE_ENTITY: "image.front_door",
                },
            },
        )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    media_url = call_args[ATTR_MEDIAURL][0]
    assert media_url.startswith("https://ha.example.com/local/twilio_snapshots/image_front_door_")
    assert len(list((Path(tmp_path) / "www" / "twilio_snapshots").glob("image_front_door_*.png"))) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_mms_image_path_from_www(hass, mock_twilio_client, tmp_path):
    """Test sending MMS using local file path under <config>/www."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)
    image_file = Path(tmp_path) / "www" / "snapshots" / "front.jpg"
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"test-image")

    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )

    await service.async_send_message(
        "File snapshot",
        **{
            ATTR_TARGET: ["+0987654321"],
            ATTR_DATA: {
                ATTR_IMAGE_PATH: str(image_file),
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL in call_args
    assert "https://ha.example.com/local/snapshots/front.jpg" in call_args[ATTR_MEDIAURL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_send_mms_image_path_too_large(hass, mock_twilio_client, tmp_path):
    """Test oversized MMS file is skipped."""
    hass.config.external_url = "https://ha.example.com"
    hass.config.config_dir = str(tmp_path)
    image_file = Path(tmp_path) / "www" / "snapshots" / "large.jpg"
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"x" * (5 * 1024 * 1024 + 1))

    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )

    await service.async_send_message(
        "Oversized file",
        **{
            ATTR_TARGET: ["+0987654321"],
            ATTR_DATA: {
                ATTR_IMAGE_PATH: str(image_file),
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL not in call_args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_service_entity_attachment_without_external_url_logs_warning(
    hass, mock_twilio_client, caplog
):
    """Test camera/image attachment is skipped when external_url is missing."""
    hass.states.async_set("camera.front_door", "idle", {})

    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )

    await service.async_send_message(
        "No external URL",
        **{
            ATTR_TARGET: ["+0987654321"],
            ATTR_DATA: {
                ATTR_CAMERA_ENTITY: "camera.front_door",
            },
        },
    )

    call_args = mock_twilio_client.messages.create.call_args[1]
    assert ATTR_MEDIAURL not in call_args
    assert "external_url is not configured" in caplog.text


@pytest.mark.unit
def test_call_service_simple_call(hass, mock_twilio_client):
    """Test making a simple call."""
    service = TwilioCallNotificationService(
        mock_twilio_client, "+1234567890", hass=hass
    )
    
    # Mock async_create_task to consume the coroutine without awaiting
    def mock_create_task_impl(coro):
        # Close the coroutine to prevent warning
        coro.close()
        return MagicMock()
    
    with patch.object(hass, "async_create_task", side_effect=mock_create_task_impl) as mock_create_task:
        service.send_message(
            "Hello world",
            **{ATTR_TARGET: ["+0987654321"]}
        )
        
        # Verify async task was created
        assert mock_create_task.called


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_service_async_make_call_simple(hass, mock_twilio_client):
    """Test making a simple call async."""
    service = TwilioCallNotificationService(
        mock_twilio_client, "+1234567890", hass=hass
    )
    
    await service._async_make_call(
        "+0987654321",
        "Hello world",
        "simple",
        {}
    )
    
    # Verify call was made
    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["to"] == "+0987654321"
    assert call_args["from_"] == "+1234567890"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_service_async_make_call_twiml(hass, mock_twilio_client):
    """Test making a call with custom TwiML URL."""
    service = TwilioCallNotificationService(
        mock_twilio_client, "+1234567890", hass=hass
    )
    
    await service._async_make_call(
        "+0987654321",
        "",
        "twiml",
        {"twiml_url": "https://example.com/twiml"}
    )
    
    # Verify call was made
    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["url"] == "https://example.com/twiml"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_service_async_make_call_interactive(hass, mock_twilio_client):
    """Test making an interactive call."""
    service = TwilioCallNotificationService(
        mock_twilio_client, "+1234567890", hass=hass, webhook_url="https://example.com/webhook"
    )
    
    await service._async_make_call(
        "+0987654321",
        "Hello world",
        "interactive",
        {
            "gather_enabled": True,
            "record_enabled": True,
            "transcribe_enabled": True,
        }
    )
    
    # Verify call was made
    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
def test_call_service_no_targets(hass, mock_twilio_client):
    """Test making a call with no targets."""
    service = TwilioCallNotificationService(
        mock_twilio_client, "+1234567890", hass=hass
    )
    
    # Should not raise error
    service.send_message("Hello world")


@pytest.mark.unit
def test_sms_service_sync_send_message(hass, mock_twilio_client):
    """Test sync send_message wrapper."""
    service = TwilioSMSNotificationService(
        mock_twilio_client, "+1234567890", hass, None
    )
    
    # Mock async_create_task to consume the coroutine without awaiting
    def mock_create_task_impl(coro):
        # Close the coroutine to prevent warning
        coro.close()
        return MagicMock()
    
    with patch.object(hass, "async_create_task", side_effect=mock_create_task_impl) as mock_create_task:
        service.send_message(
            "Test message",
            **{ATTR_TARGET: ["+0987654321"]}
        )
        
        # Verify async task was created
        assert mock_create_task.called
