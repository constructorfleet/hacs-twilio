"""Tests for services.py functions."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import ServiceCall

from custom_components.twilio.services import (
    async_make_call,
    async_pause_call,
    async_send_mms,
    async_send_dtmf,
    async_start_recording,
)
from custom_components.twilio.const import DATA_TWILIO, DOMAIN


def create_mock_hass_with_client(mock_twilio_client):
    """Create a mock HomeAssistant instance with Twilio client."""
    mock_hass = MagicMock()
    mock_hass.data = {
        DOMAIN: {
            "test_entry": {
                DATA_TWILIO: mock_twilio_client,
                "webhook_url": "https://example.com/webhook",
            }
        }
    }
    mock_hass.bus = MagicMock()
    mock_hass.bus.fire = MagicMock()
    mock_hass.config = MagicMock()
    mock_hass.config.external_url = "https://ha.example.com"
    mock_hass.config.config_dir = "/tmp"
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    return mock_hass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_success(mock_twilio_client):
    """Test making a call via service."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "message": "Hello world",
    }
    service_call = ServiceCall(hass, "twilio", "make_call", call_data)
    
    result = await async_make_call(hass, service_call)
    
    assert result is not None
    assert "call_sid" in result
    assert result["call_sid"] == "CA1234567890abcdef1234567890abcdef"
    assert result["status"] == "queued"
    assert result["to"] == "+1234567890"
    assert result["from"] == "+0987654321"
    
    # Verify Twilio client was called
    mock_twilio_client.calls.create_async.assert_called_once()
    call_kwargs = mock_twilio_client.calls.create_async.call_args.kwargs
    assert "url" in call_kwargs
    assert "twimlets.com/message" in call_kwargs["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_with_transcription(mock_twilio_client):
    """Test making a call with streaming transcription enabled."""
    hass = create_mock_hass_with_client(mock_twilio_client)

    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "transcription": True,
        "language_code": "en-US",
        "profanity_filter": False,
        "automatic_punctuation": False,
        "transcription_pause": 10,
        "webhook_method": "POST",
    }
    service_call = ServiceCall(hass, "twilio", "make_call", call_data)

    result = await async_make_call(hass, service_call)

    assert result is not None
    call_kwargs = mock_twilio_client.calls.create_async.call_args.kwargs
    assert call_kwargs["to"] == "+1234567890"
    assert call_kwargs["from_"] == "+0987654321"
    assert "twiml" in call_kwargs
    assert "Start" in call_kwargs["twiml"]
    assert "Transcription" in call_kwargs["twiml"]
    assert "statusCallbackUrl=\"https://example.com/webhook\"" in call_kwargs["twiml"]
    assert "languageCode=\"en-US\"" in call_kwargs["twiml"]
    assert "partialResults=\"true\"" in call_kwargs["twiml"]
    assert "url" not in call_kwargs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_missing_to(mock_twilio_client):
    """Test making a call without 'to' number."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "from_number": "+0987654321",
        "message": "Hello world",
    }
    service_call = ServiceCall(hass, "twilio", "make_call", call_data)
    
    result = await async_make_call(hass, service_call)
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_missing_from(mock_twilio_client):
    """Test making a call without 'from_number'."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "to": "+1234567890",
        "message": "Hello world",
    }
    service_call = ServiceCall(hass, "twilio", "make_call", call_data)
    
    result = await async_make_call(hass, service_call)
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_mms_success(mock_twilio_client):
    """Test sending MMS via service."""
    hass = create_mock_hass_with_client(mock_twilio_client)

    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "media_url": "https://example.com/image.jpg",
        "body": "Photo attached",
    }
    service_call = ServiceCall(hass, "twilio", "send_mms", call_data)

    result = await async_send_mms(hass, service_call)

    assert result is not None
    assert result["message_sid"] == "SM1234567890abcdef1234567890abcdef"
    assert result["status"] == "queued"
    assert result["to"] == "+1234567890"
    assert result["from"] == "+0987654321"

    mock_twilio_client.messages.create.assert_called_once()
    message_kwargs = mock_twilio_client.messages.create.call_args.kwargs
    assert message_kwargs["to"] == "+1234567890"
    assert message_kwargs["from_"] == "+0987654321"
    assert message_kwargs["media_url"] == ["https://example.com/image.jpg"]
    assert message_kwargs["body"] == "Photo attached"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_mms_missing_media_url(mock_twilio_client):
    """Test sending MMS without any media source."""
    hass = create_mock_hass_with_client(mock_twilio_client)

    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
    }
    service_call = ServiceCall(hass, "twilio", "send_mms", call_data)

    result = await async_send_mms(hass, service_call)

    assert result is None
    mock_twilio_client.messages.create.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_mms_with_camera_entity(mock_twilio_client):
    """Test sending MMS using camera entity media source."""
    hass = create_mock_hass_with_client(mock_twilio_client)

    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "camera_entity": "camera.front_door",
    }
    service_call = ServiceCall(hass, "twilio", "send_mms", call_data)

    with patch(
        "custom_components.twilio.services._build_entity_media_url",
        new=AsyncMock(return_value="https://ha.example.com/local/twilio_snapshots/camera_front_door_1.jpg"),
    ):
        result = await async_send_mms(hass, service_call)

    assert result is not None
    message_kwargs = mock_twilio_client.messages.create.call_args.kwargs
    assert message_kwargs["media_url"] == [
        "https://ha.example.com/local/twilio_snapshots/camera_front_door_1.jpg"
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_mms_with_image_path(mock_twilio_client, tmp_path):
    """Test sending MMS using local image path media source."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    hass.config.config_dir = str(tmp_path)
    image_file = Path(tmp_path) / "www" / "snapshots" / "front.jpg"
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(b"test-image")

    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "image_path": str(image_file),
    }
    service_call = ServiceCall(hass, "twilio", "send_mms", call_data)

    result = await async_send_mms(hass, service_call)

    assert result is not None
    message_kwargs = mock_twilio_client.messages.create.call_args.kwargs
    assert message_kwargs["media_url"] == [
        "https://ha.example.com/local/snapshots/front.jpg"
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_dtmf_success(mock_twilio_client):
    """Test sending DTMF digits via service."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "call_sid": "CA123",
        "digits": "1234#",
    }
    service_call = ServiceCall(hass, "twilio", "send_dtmf", call_data)
    
    await async_send_dtmf(hass, service_call)
    
    # Verify calls() was called with the call_sid
    mock_twilio_client.calls.assert_called_once_with("CA123")
    
    # Verify update_async was called on the returned call resource
    call_resource = mock_twilio_client.calls.return_value
    call_resource.update_async.assert_called_once()
    call_args = call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_dtmf_missing_call_sid(mock_twilio_client):
    """Test sending DTMF without call_sid."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "digits": "1234#",
    }
    service_call = ServiceCall(hass, "twilio", "send_dtmf", call_data)
    
    # Should return without error
    await async_send_dtmf(hass, service_call)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_start_recording_success(mock_twilio_client):
    """Test starting recording via service."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "call_sid": "CA123",
        "max_length": 3600,
        "transcribe": True,
    }
    service_call = ServiceCall(hass, "twilio", "start_recording", call_data)
    
    await async_start_recording(hass, service_call)
    
    # Verify calls() was called with the call_sid
    mock_twilio_client.calls.assert_called_once_with("CA123")
    
    # Verify update_async was called on the returned call resource
    call_resource = mock_twilio_client.calls.return_value
    call_resource.update_async.assert_called_once()
    call_args = call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_start_recording_with_callbacks(mock_twilio_client):
    """Test starting recording with callbacks enabled."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "call_sid": "CA123",
        "recording_status_callback": True,
        "transcribe": True,
        "transcribe_callback": True,
    }
    service_call = ServiceCall(hass, "twilio", "start_recording", call_data)
    
    await async_start_recording(hass, service_call)
    
    # Verify calls() was called
    mock_twilio_client.calls.assert_called_once_with("CA123")
    
    # Verify update_async was called
    call_resource = mock_twilio_client.calls.return_value
    call_resource.update_async.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_pause_call_success(mock_twilio_client):
    """Test pausing a call via service."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "call_sid": "CA123",
        "length": 5,
    }
    service_call = ServiceCall(hass, "twilio", "pause", call_data)
    
    await async_pause_call(hass, service_call)
    
    # Verify calls() was called with the call_sid
    mock_twilio_client.calls.assert_called_once_with("CA123")
    
    # Verify update_async was called on the returned call resource
    call_resource = mock_twilio_client.calls.return_value
    call_resource.update_async.assert_called_once()
    call_args = call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_pause_call_missing_call_sid(mock_twilio_client):
    """Test pausing a call without call_sid."""
    hass = create_mock_hass_with_client(mock_twilio_client)
    
    call_data = {
        "length": 5,
    }
    service_call = ServiceCall(hass, "twilio", "pause", call_data)
    
    # Should return without error
    await async_pause_call(hass, service_call)
