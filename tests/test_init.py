"""Tests for __init__.py setup functions."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID

from custom_components.twilio import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.twilio.const import (
    CONF_ACCOUNT_SID,
    CONF_AUTH_TOKEN,
    DATA_TWILIO,
    DOMAIN,
    SERVICE_MAKE_CALL,
    SERVICE_PAUSE,
    SERVICE_SEND_DTMF,
    SERVICE_START_RECORDING,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_setup_no_config(hass):
    """Test setup without configuration."""
    result = await async_setup(hass, {})
    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.AsyncTwilioHttpClient")
@patch("custom_components.twilio.Client")
async def test_async_setup_with_config(mock_client_class, mock_http_client_class, hass):
    """Test setup with configuration."""
    config = {
        DOMAIN: {
            CONF_ACCOUNT_SID: "ACtest123",
            CONF_AUTH_TOKEN: "test_token",
        }
    }
    
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_http_client = MagicMock()
    mock_http_client_class.return_value = mock_http_client
    
    result = await async_setup(hass, config)
    
    assert result is True
    assert DATA_TWILIO in hass.data
    assert hass.data[DATA_TWILIO] == mock_client
    
    # Verify Client was created with async HTTP client
    mock_client_class.assert_called_once()
    call_args = mock_client_class.call_args
    assert call_args[1]["http_client"] == mock_http_client


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
@patch("custom_components.twilio.AsyncTwilioHttpClient")
@patch("custom_components.twilio.Client")
async def test_async_setup_entry(
    mock_client_class, mock_http_client_class, mock_webhook, hass
):
    """Test config entry setup."""
    entry_data = {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook",
    }
    
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.data = entry_data
    mock_entry.entry_id = "test_entry"
    
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_http_client = MagicMock()
    mock_http_client_class.return_value = mock_http_client
    
    mock_webhook.async_generate_url.return_value = "https://example.com/webhook"
    
    # Mock platform setup
    with patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()):
        result = await async_setup_entry(hass, mock_entry)
    
    assert result is True
    assert DOMAIN in hass.data
    assert mock_entry.entry_id in hass.data[DOMAIN]
    assert DATA_TWILIO in hass.data[DOMAIN][mock_entry.entry_id]
    
    # Verify webhook was registered
    mock_webhook.async_register.assert_called_once()
    
    # Verify services were registered
    assert hass.services.async_register.called
    service_calls = hass.services.async_register.call_args_list
    service_names = [call[0][1] for call in service_calls]
    assert SERVICE_MAKE_CALL in service_names
    assert SERVICE_SEND_DTMF in service_names
    assert SERVICE_START_RECORDING in service_names
    assert SERVICE_PAUSE in service_names


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
async def test_async_unload_entry(mock_webhook, hass):
    """Test config entry unload."""
    entry_data = {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook",
    }
    
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.data = entry_data
    mock_entry.entry_id = "test_entry"
    
    # Setup data
    hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            DATA_TWILIO: MagicMock(),
            "webhook_id": "test_webhook",
        },
        "_services_registered": True,
    }
    
    # Mock platform unload
    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ):
        result = await async_unload_entry(hass, mock_entry)
    
    assert result is True
    
    # Verify webhook was unregistered
    mock_webhook.async_unregister.assert_called_once_with(hass, "test_webhook")
    
    # Verify data was removed
    assert mock_entry.entry_id not in hass.data[DOMAIN]
    
    # Verify services were unregistered (when it's the last entry)
    assert hass.services.async_remove.called


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
async def test_async_unload_entry_with_remaining_entries(mock_webhook, hass):
    """Test config entry unload with other entries remaining."""
    entry_data = {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook",
    }
    
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.data = entry_data
    mock_entry.entry_id = "test_entry"
    
    # Setup data with multiple entries
    hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            DATA_TWILIO: MagicMock(),
            "webhook_id": "test_webhook",
        },
        "another_entry": {
            DATA_TWILIO: MagicMock(),
            "webhook_id": "another_webhook",
        },
        "_services_registered": True,
    }
    
    # Mock platform unload
    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ):
        result = await async_unload_entry(hass, mock_entry)
    
    assert result is True
    
    # Verify webhook was unregistered
    mock_webhook.async_unregister.assert_called_once()
    
    # Verify only the specific entry was removed
    assert mock_entry.entry_id not in hass.data[DOMAIN]
    assert "another_entry" in hass.data[DOMAIN]
    
    # Verify services were NOT unregistered (other entries remain)
    assert not hass.services.async_remove.called
