"""Tests for __init__.py setup functions."""
import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.config_entries import ConfigEntry
from homeassistant import config_entries
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
    SERVICE_SEND_MMS,
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
async def test_async_setup_with_config(hass):
    """Test setup imports YAML configuration into config entries."""
    config = {
        DOMAIN: {
            CONF_ACCOUNT_SID: "ACtest123",
            CONF_AUTH_TOKEN: "test_token",
        }
    }

    hass.config_entries.flow.async_init = AsyncMock(return_value={"type": "abort"})

    result = await async_setup(hass, config)

    assert result is True
    hass.config_entries.flow.async_init.assert_awaited_once_with(
        DOMAIN,
        context={"source": config_entries.SOURCE_IMPORT},
        data={
            CONF_ACCOUNT_SID: "ACtest123",
            CONF_AUTH_TOKEN: "test_token",
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
@patch("custom_components.twilio.AsyncTwilioHttpClient")
@patch("custom_components.twilio.Client")
async def test_async_setup_entry(
    mock_client_class, mock_http_client_class, mock_webhook
):
    """Test config entry setup."""
    # Create a proper mock hass
    mock_hass = MagicMock()
    mock_hass.data = {}
    mock_hass.bus = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_register = MagicMock()
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.async_forward_entry_setups = AsyncMock()
    
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
    
    result = await async_setup_entry(mock_hass, mock_entry)
    
    assert result is True
    assert DOMAIN in mock_hass.data
    assert mock_entry.entry_id in mock_hass.data[DOMAIN]
    assert DATA_TWILIO in mock_hass.data[DOMAIN][mock_entry.entry_id]
    
    # Ensure stale webhook handlers are replaced during reload/setup.
    mock_webhook.async_unregister.assert_called_once_with(mock_hass, "test_webhook")

    # Verify webhook was registered
    mock_webhook.async_register.assert_called_once()
    
    # Verify services were registered
    assert mock_hass.services.async_register.called
    service_calls = mock_hass.services.async_register.call_args_list
    service_names = [call[0][1] for call in service_calls]
    assert SERVICE_MAKE_CALL in service_names
    assert SERVICE_SEND_MMS in service_names
    assert SERVICE_SEND_DTMF in service_names
    assert SERVICE_START_RECORDING in service_names
    assert SERVICE_PAUSE in service_names
    for service_call in service_calls:
        assert inspect.iscoroutinefunction(service_call[0][2])


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
async def test_async_unload_entry(mock_webhook):
    """Test config entry unload."""
    # Create a proper mock hass
    mock_hass = MagicMock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.services = MagicMock()
    mock_hass.services.async_remove = MagicMock()
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    entry_data = {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook",
    }
    
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.data = entry_data
    mock_entry.entry_id = "test_entry"
    
    # Setup data
    mock_hass.data[DOMAIN] = {
        mock_entry.entry_id: {
            DATA_TWILIO: MagicMock(),
            "webhook_id": "test_webhook",
        },
        "_services_registered": True,
    }
    
    result = await async_unload_entry(mock_hass, mock_entry)
    
    assert result is True
    
    # Verify webhook was unregistered
    mock_webhook.async_unregister.assert_called_once_with(mock_hass, "test_webhook")
    
    # Verify data was removed
    assert mock_entry.entry_id not in mock_hass.data[DOMAIN]
    
    # Verify services were unregistered (when it's the last entry)
    assert mock_hass.services.async_remove.called
    removed_services = [call.args[1] for call in mock_hass.services.async_remove.call_args_list]
    assert SERVICE_SEND_MMS in removed_services


@pytest.mark.unit
@pytest.mark.asyncio
@patch("custom_components.twilio.webhook_component")
async def test_async_unload_entry_with_remaining_entries(mock_webhook):
    """Test config entry unload with other entries remaining."""
    # Create a proper mock hass
    mock_hass = MagicMock()
    mock_hass.data = {DOMAIN: {}}
    mock_hass.services = MagicMock()
    mock_hass.services.async_remove = MagicMock()
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    entry_data = {
        CONF_ACCOUNT_SID: "ACtest123",
        CONF_AUTH_TOKEN: "test_token",
        CONF_WEBHOOK_ID: "test_webhook",
    }
    
    mock_entry = MagicMock(spec=ConfigEntry)
    mock_entry.data = entry_data
    mock_entry.entry_id = "test_entry"
    
    # Setup data with multiple entries
    mock_hass.data[DOMAIN] = {
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
    
    result = await async_unload_entry(mock_hass, mock_entry)
    
    assert result is True
    
    # Verify webhook was unregistered
    mock_webhook.async_unregister.assert_called_once()
    
    # Verify only the specific entry was removed
    assert mock_entry.entry_id not in mock_hass.data[DOMAIN]
    assert "another_entry" in mock_hass.data[DOMAIN]
    
    # Verify services were NOT unregistered (other entries remain)
    assert not mock_hass.services.async_remove.called
