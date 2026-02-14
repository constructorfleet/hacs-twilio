"""Common fixtures for Twilio integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.const import CONF_WEBHOOK_ID

from custom_components.twilio.const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    DATA_TWILIO,
    DOMAIN,
)


@pytest.fixture
def mock_twilio_client():
    """Mock Twilio client."""
    client = MagicMock()
    
    # Mock calls resource
    client.calls = MagicMock()
    client.calls.create_async = AsyncMock()
    
    # Mock call instance
    mock_call = MagicMock()
    mock_call.sid = "CA1234567890abcdef1234567890abcdef"
    mock_call.status = "queued"
    client.calls.create_async.return_value = mock_call
    
    # Mock call update
    def mock_calls_getter(call_sid):
        call_resource = MagicMock()
        call_resource.update_async = AsyncMock()
        return call_resource
    
    client.calls.side_effect = mock_calls_getter
    
    # Mock messages resource
    client.messages = MagicMock()
    client.messages.create = MagicMock()
    
    # Mock message instance
    mock_message = MagicMock()
    mock_message.sid = "SM1234567890abcdef1234567890abcdef"
    mock_message.status = "queued"
    client.messages.create.return_value = mock_message
    
    return client


@pytest.fixture
def mock_config_entry():
    """Mock config entry."""
    return {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook_id",
    }


@pytest.fixture
async def hass_with_twilio(hass: HomeAssistant, mock_twilio_client, mock_config_entry):
    """Set up Home Assistant with Twilio integration."""
    # Store mock client in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["test_entry"] = {
        DATA_TWILIO: mock_twilio_client,
        "webhook_id": mock_config_entry[CONF_WEBHOOK_ID],
        "webhook_url": "https://example.com/api/webhook/test_webhook_id",
    }
    
    return hass


@pytest.fixture
def mock_async_http_client():
    """Mock AsyncTwilioHttpClient."""
    with patch("custom_components.twilio.AsyncTwilioHttpClient") as mock:
        yield mock.return_value
