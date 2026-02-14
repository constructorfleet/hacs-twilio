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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_success(hass_with_twilio, mock_twilio_client):
    """Test making a call via service."""
    call_data = {
        "to": "+1234567890",
        "from_number": "+0987654321",
        "message": "Hello world",
    }
    service_call = ServiceCall("twilio", "make_call", call_data)
    
    result = await async_make_call(hass_with_twilio, service_call)
    
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
async def test_async_make_call_missing_to(hass_with_twilio):
    """Test making a call without 'to' number."""
    call_data = {
        "from_number": "+0987654321",
        "message": "Hello world",
    }
    service_call = ServiceCall("twilio", "make_call", call_data)
    
    result = await async_make_call(hass_with_twilio, service_call)
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_make_call_missing_from(hass_with_twilio):
    """Test making a call without 'from_number'."""
    call_data = {
        "to": "+1234567890",
        "message": "Hello world",
    }
    service_call = ServiceCall("twilio", "make_call", call_data)
    
    result = await async_make_call(hass_with_twilio, service_call)
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_dtmf_success(hass_with_twilio, mock_twilio_client):
    """Test sending DTMF digits via service."""
    call_data = {
        "call_sid": "CA123",
        "digits": "1234#",
    }
    service_call = ServiceCall("twilio", "send_dtmf", call_data)
    
    # Mock the calls getter
    mock_call_resource = MagicMock()
    mock_call_resource.update_async = AsyncMock()
    mock_twilio_client.calls.return_value = mock_call_resource
    
    await async_send_dtmf(hass_with_twilio, service_call)
    
    # Verify update was called
    mock_call_resource.update_async.assert_called_once()
    call_args = mock_call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_send_dtmf_missing_call_sid(hass_with_twilio):
    """Test sending DTMF without call_sid."""
    call_data = {
        "digits": "1234#",
    }
    service_call = ServiceCall("twilio", "send_dtmf", call_data)
    
    # Should return without error
    await async_send_dtmf(hass_with_twilio, service_call)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_start_recording_success(hass_with_twilio, mock_twilio_client):
    """Test starting recording via service."""
    call_data = {
        "call_sid": "CA123",
        "max_length": 3600,
        "transcribe": True,
    }
    service_call = ServiceCall("twilio", "start_recording", call_data)
    
    # Mock the calls getter
    mock_call_resource = MagicMock()
    mock_call_resource.update_async = AsyncMock()
    mock_twilio_client.calls.return_value = mock_call_resource
    
    await async_start_recording(hass_with_twilio, service_call)
    
    # Verify update was called
    mock_call_resource.update_async.assert_called_once()
    call_args = mock_call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_start_recording_with_callbacks(hass_with_twilio, mock_twilio_client):
    """Test starting recording with callbacks enabled."""
    call_data = {
        "call_sid": "CA123",
        "recording_status_callback": True,
        "transcribe": True,
        "transcribe_callback": True,
    }
    service_call = ServiceCall("twilio", "start_recording", call_data)
    
    # Mock the calls getter
    mock_call_resource = MagicMock()
    mock_call_resource.update_async = AsyncMock()
    mock_twilio_client.calls.return_value = mock_call_resource
    
    await async_start_recording(hass_with_twilio, service_call)
    
    # Verify update was called
    mock_call_resource.update_async.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_pause_call_success(hass_with_twilio, mock_twilio_client):
    """Test pausing a call via service."""
    call_data = {
        "call_sid": "CA123",
        "length": 5,
    }
    service_call = ServiceCall("twilio", "pause", call_data)
    
    # Mock the calls getter
    mock_call_resource = MagicMock()
    mock_call_resource.update_async = AsyncMock()
    mock_twilio_client.calls.return_value = mock_call_resource
    
    await async_pause_call(hass_with_twilio, service_call)
    
    # Verify update was called
    mock_call_resource.update_async.assert_called_once()
    call_args = mock_call_resource.update_async.call_args[1]
    assert "url" in call_args
    assert "twimlets.com/echo" in call_args["url"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_pause_call_missing_call_sid(hass_with_twilio):
    """Test pausing a call without call_sid."""
    call_data = {
        "length": 5,
    }
    service_call = ServiceCall("twilio", "pause", call_data)
    
    # Should return without error
    await async_pause_call(hass_with_twilio, service_call)
