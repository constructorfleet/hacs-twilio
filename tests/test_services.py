"""Tests for services.py functions."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import ServiceCall

from custom_components.twilio.services import (
    async_make_call,
    async_pause_call,
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
