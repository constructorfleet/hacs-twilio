"""Tests for helper.py functions."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.twilio.helper import (
    fire_call_initiated_event,
    generate_simple_twiml_url,
    get_twilio_client,
    get_webhook_url,
    make_call,
    make_simple_call,
)
from custom_components.twilio.const import (
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_FROM,
    ATTR_TO,
    DATA_TWILIO,
    DOMAIN,
    EVENT_TWILIO_CALL_INITIATED,
)


@pytest.mark.unit
def test_get_twilio_client_from_global(mock_hass_for_helper):
    """Test getting Twilio client from global data."""
    mock_client = MagicMock()
    mock_hass_for_helper.data[DATA_TWILIO] = mock_client
    
    client = get_twilio_client(mock_hass_for_helper)
    assert client == mock_client


@pytest.mark.unit
def test_get_twilio_client_from_config_entry(mock_hass_for_helper):
    """Test getting Twilio client from config entry data."""
    mock_client = MagicMock()
    mock_hass_for_helper.data[DOMAIN] = {
        "entry1": {
            DATA_TWILIO: mock_client,
        }
    }
    
    client = get_twilio_client(mock_hass_for_helper)
    # The client should be returned directly, not wrapped
    assert client is mock_client


@pytest.mark.unit
def test_get_twilio_client_not_found(mock_hass_for_helper):
    """Test getting Twilio client when not available."""
    client = get_twilio_client(mock_hass_for_helper)
    assert client is None


@pytest.mark.unit
def test_get_webhook_url(mock_hass_for_helper):
    """Test getting webhook URL."""
    mock_hass_for_helper.data[DOMAIN] = {
        "entry1": {
            "webhook_url": "https://example.com/webhook",
        }
    }
    
    url = get_webhook_url(mock_hass_for_helper)
    assert url == "https://example.com/webhook"


@pytest.mark.unit
def test_get_webhook_url_not_found(mock_hass_for_helper):
    """Test getting webhook URL when not available."""
    url = get_webhook_url(mock_hass_for_helper)
    assert url is None


@pytest.mark.unit
def test_generate_simple_twiml_url_with_message():
    """Test generating TwiML URL with a message."""
    message = "Hello world"
    url = generate_simple_twiml_url(message)
    
    assert url.startswith("https://twimlets.com/message?Message=")
    assert "Hello" in url


@pytest.mark.unit
def test_generate_simple_twiml_url_with_url():
    """Test generating TwiML URL when message is already a URL."""
    message = "https://example.com/twiml"
    url = generate_simple_twiml_url(message)
    
    assert url == message


@pytest.mark.unit
def test_fire_call_initiated_event(mock_hass_for_helper):
    """Test firing call initiated event."""
    call_sid = "CA123"
    to_number = "+1234567890"
    from_number = "+0987654321"
    call_status = "queued"
    
    fire_call_initiated_event(mock_hass_for_helper, call_sid, to_number, from_number, call_status)
    
    # Check that event was fired
    assert mock_hass_for_helper.bus.fire.called
    call_args = mock_hass_for_helper.bus.fire.call_args
    assert call_args[0][0] == EVENT_TWILIO_CALL_INITIATED
    assert call_args[0][1][ATTR_CALL_SID] == call_sid
    assert call_args[0][1][ATTR_TO] == to_number
    assert call_args[0][1][ATTR_FROM] == from_number
    assert call_args[0][1][ATTR_CALL_STATUS] == call_status


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_call_success(mock_hass_for_helper, mock_twilio_client):
    """Test making a successful call."""
    to_number = "+1234567890"
    from_number = "+0987654321"
    twiml_url = "https://example.com/twiml"
    
    result = await make_call(
        client=mock_twilio_client,
        to_number=to_number,
        from_number=from_number,
        twiml_url=twiml_url,
        hass=mock_hass_for_helper,
    )
    
    assert result is not None
    assert result["call_sid"] == "CA1234567890abcdef1234567890abcdef"
    assert result["status"] == "queued"
    assert result["to"] == to_number
    assert result["from"] == from_number
    
    # Verify call was made
    mock_twilio_client.calls.create_async.assert_called_once()
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["to"] == to_number
    assert call_args["from_"] == from_number
    assert call_args["url"] == twiml_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_call_with_status_callback(mock_hass_for_helper, mock_twilio_client):
    """Test making a call with status callback."""
    to_number = "+1234567890"
    from_number = "+0987654321"
    twiml_url = "https://example.com/twiml"
    status_callback = "https://example.com/webhook"
    
    result = await make_call(
        client=mock_twilio_client,
        to_number=to_number,
        from_number=from_number,
        twiml_url=twiml_url,
        hass=mock_hass_for_helper,
        status_callback=status_callback,
        status_callback_method="POST",
    )
    
    assert result is not None
    
    # Verify status callback was included
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert call_args["status_callback"] == status_callback
    assert call_args["status_callback_method"] == "POST"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_call_failure(mock_hass_for_helper, mock_twilio_client):
    """Test making a call that fails."""
    from twilio.base.exceptions import TwilioRestException
    
    mock_twilio_client.calls.create_async.side_effect = TwilioRestException(
        status=400,
        uri="/calls",
        msg="Bad request"
    )
    
    result = await make_call(
        client=mock_twilio_client,
        to_number="+1234567890",
        from_number="+0987654321",
        twiml_url="https://example.com/twiml",
        hass=mock_hass_for_helper,
    )
    
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_make_simple_call(mock_hass_for_helper, mock_twilio_client):
    """Test making a simple call with message."""
    to_number = "+1234567890"
    from_number = "+0987654321"
    message = "Hello world"
    
    result = await make_simple_call(
        client=mock_twilio_client,
        to_number=to_number,
        from_number=from_number,
        message=message,
        hass=mock_hass_for_helper,
    )
    
    assert result is not None
    assert result["call_sid"] == "CA1234567890abcdef1234567890abcdef"
    
    # Verify call was made with proper TwiML URL
    call_args = mock_twilio_client.calls.create_async.call_args[1]
    assert "twimlets.com/message" in call_args["url"]
