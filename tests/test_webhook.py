"""Tests for webhook.py functions."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.twilio.webhook import handle_webhook
from custom_components.twilio.const import (
    ATTR_BODY,
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_DTMF_DIGITS,
    ATTR_FROM,
    ATTR_TO,
    ATTR_TRANSCRIPTION,
    EVENT_TWILIO_CALL_ENDED,
    EVENT_TWILIO_CALL_RECEIVED,
    EVENT_TWILIO_DTMF,
    EVENT_TWILIO_SMS_RECEIVED,
    EVENT_TWILIO_TRANSCRIPTION,
    EVENT_TWILIO_TRANSCRIPTION_UPDATED,
)


def create_mock_hass():
    """Create a properly mocked HomeAssistant instance."""
    mock_hass = MagicMock()
    mock_hass.data = {}
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_fire = MagicMock()
    return mock_hass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_sms():
    """Test handling SMS webhook."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "MessageSid": "SM123",
        "From": "+1234567890",
        "To": "+0987654321",
        "Body": "Test message",
        "NumMedia": "0",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    assert response.content_type == "text/xml"
    
    # Verify event was fired
    assert hass.bus.async_fire.called
    # Find the SMS event
    sms_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_SMS_RECEIVED:
            sms_event_fired = True
            event_data = call[0][1]
            assert event_data["message_sid"] == "SM123"
            assert event_data[ATTR_FROM] == "+1234567890"
            assert event_data[ATTR_TO] == "+0987654321"
            assert event_data[ATTR_BODY] == "Test message"
    
    assert sms_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_sms_with_media():
    """Test handling SMS webhook with media."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "MessageSid": "SM123",
        "From": "+1234567890",
        "To": "+0987654321",
        "Body": "Test message",
        "NumMedia": "2",
        "MediaUrl0": "https://example.com/image1.jpg",
        "MediaUrl1": "https://example.com/image2.jpg",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    
    # Verify event includes media URLs
    sms_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_SMS_RECEIVED:
            sms_event_fired = True
            event_data = call[0][1]
            assert "media_urls" in event_data
            assert len(event_data["media_urls"]) == 2
            assert "image1.jpg" in event_data["media_urls"][0]
    
    assert sms_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_call_received():
    """Test handling call received webhook."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "CallStatus": "ringing",
        "From": "+1234567890",
        "To": "+0987654321",
        "Direction": "inbound",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    
    # Verify event was fired
    call_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_CALL_RECEIVED:
            call_event_fired = True
            event_data = call[0][1]
            assert event_data[ATTR_CALL_SID] == "CA123"
            assert event_data[ATTR_CALL_STATUS] == "ringing"
            assert event_data[ATTR_FROM] == "+1234567890"
            assert event_data[ATTR_TO] == "+0987654321"
    
    assert call_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_call_ended():
    """Test handling call ended webhook."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "CallStatus": "completed",
        "From": "+1234567890",
        "To": "+0987654321",
        "Direction": "outbound",
        "CallDuration": "45",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    
    # Verify event was fired
    call_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_CALL_ENDED:
            call_event_fired = True
            event_data = call[0][1]
            assert event_data[ATTR_CALL_SID] == "CA123"
            assert event_data[ATTR_CALL_STATUS] == "completed"
            assert event_data["duration"] == "45"
    
    assert call_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_dtmf():
    """Test handling DTMF webhook."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "Digits": "1234",
        "From": "+1234567890",
        "To": "+0987654321",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    
    # Verify event was fired
    dtmf_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_DTMF:
            dtmf_event_fired = True
            event_data = call[0][1]
            assert event_data[ATTR_CALL_SID] == "CA123"
            assert event_data[ATTR_DTMF_DIGITS] == "1234"
    
    assert dtmf_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_transcription():
    """Test handling transcription webhook."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request
    request = MagicMock()
    request.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "TranscriptionSid": "TR123",
        "TranscriptionText": "Hello world",
        "TranscriptionStatus": "completed",
    })
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 200
    
    # Verify event was fired
    transcription_event_fired = False
    for call in hass.bus.async_fire.call_args_list:
        if call[0][0] == EVENT_TWILIO_TRANSCRIPTION:
            transcription_event_fired = True
            event_data = call[0][1]
            assert event_data[ATTR_CALL_SID] == "CA123"
            assert event_data[ATTR_TRANSCRIPTION] == "Hello world"
            assert event_data["transcription_sid"] == "TR123"
    
    assert transcription_event_fired


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_transcription_event_updates():
    """Test handling TranscriptionEvent webhook and cumulative updates."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"

    request1 = MagicMock()
    request1.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "TranscriptionSid": "GT123",
        "TranscriptionEvent": "transcription-content",
        "SequenceId": "1",
        "Track": "outbound_track",
        "Timestamp": "2024-06-25T16:30:21.600697Z",
        "LanguageCode": "en-US",
        "Stability": "0.9",
        "Final": "false",
        "TranscriptionData": "{\"transcript\":\"Hello there\"}",
    })
    response1 = await handle_webhook(hass, webhook_id, request1)
    assert response1.status == 200

    request2 = MagicMock()
    request2.post = AsyncMock(return_value={
        "CallSid": "CA123",
        "TranscriptionSid": "GT123",
        "TranscriptionEvent": "transcription-content",
        "SequenceId": "2",
        "Track": "outbound_track",
        "Timestamp": "2024-06-25T16:30:22.600697Z",
        "LanguageCode": "en-US",
        "Stability": "0.9",
        "Final": "true",
        "TranscriptionData": "{\"transcript\":\"there from Twilio\"}",
    })
    response2 = await handle_webhook(hass, webhook_id, request2)
    assert response2.status == 200

    updated_events = [
        call for call in hass.bus.async_fire.call_args_list
        if call[0][0] == EVENT_TWILIO_TRANSCRIPTION_UPDATED
    ]
    assert len(updated_events) == 2

    first_event = updated_events[0][0][1]
    assert first_event[ATTR_CALL_SID] == "CA123"
    assert first_event[ATTR_TRANSCRIPTION] == "Hello there"
    assert first_event["segment_text"] == "Hello there"
    assert first_event["parts_count"] == 1

    second_event = updated_events[1][0][1]
    assert second_event[ATTR_CALL_SID] == "CA123"
    assert second_event[ATTR_TRANSCRIPTION] == "Hello there from Twilio"
    assert second_event["segment_text"] == "there from Twilio"
    assert second_event["sequence_id"] == "2"
    assert second_event["final"] is True
    assert second_event["parts_count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_transcription_event_sequence_update():
    """Test updated content for an existing sequence replaces prior segment."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"

    request1 = MagicMock()
    request1.post = AsyncMock(return_value={
        "CallSid": "CA999",
        "TranscriptionSid": "GT999",
        "TranscriptionEvent": "transcription-content",
        "SequenceId": "10",
        "Track": "inbound_track",
        "Timestamp": "2024-06-25T16:30:30.600697Z",
        "TranscriptionData": "{\"transcript\":\"hello wor\"}",
    })
    await handle_webhook(hass, webhook_id, request1)

    request2 = MagicMock()
    request2.post = AsyncMock(return_value={
        "CallSid": "CA999",
        "TranscriptionSid": "GT999",
        "TranscriptionEvent": "transcription-content",
        "SequenceId": "10",
        "Track": "inbound_track",
        "Timestamp": "2024-06-25T16:30:31.600697Z",
        "TranscriptionData": "{\"transcript\":\"hello world\"}",
    })
    await handle_webhook(hass, webhook_id, request2)

    updated_events = [
        call for call in hass.bus.async_fire.call_args_list
        if call[0][0] == EVENT_TWILIO_TRANSCRIPTION_UPDATED
    ]
    assert len(updated_events) == 2

    latest = updated_events[-1][0][1]
    assert latest[ATTR_CALL_SID] == "CA999"
    assert latest[ATTR_TRANSCRIPTION] == "hello world"
    assert latest["parts_count"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_webhook_error():
    """Test handling webhook with error."""
    hass = create_mock_hass()
    webhook_id = "test_webhook"
    
    # Mock request that raises an error
    request = MagicMock()
    request.post = AsyncMock(side_effect=Exception("Test error"))
    
    response = await handle_webhook(hass, webhook_id, request)
    
    assert response.status == 500
    assert "Error processing webhook" in response.text
