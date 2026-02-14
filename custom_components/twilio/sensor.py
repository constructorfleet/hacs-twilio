"""Support for Twilio voice call status sensors."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .const import (
    DOMAIN,
    EVENT_TWILIO_CALL_RECEIVED,
    EVENT_TWILIO_CALL_INITIATED,
    EVENT_TWILIO_CALL_ENDED,
    EVENT_TWILIO_TRANSCRIPTION,
    ATTR_CALL_SID,
    ATTR_CALL_STATUS,
    ATTR_FROM,
    ATTR_TO,
    ATTR_TRANSCRIPTION,
    ATTR_CURRENT_TRANSCRIPTION,
    ATTR_FULL_TRANSCRIPTION,
    ATTR_PHONE_NUMBER,
    CONF_SENSOR_CLEANUP_HOURS,
    DEFAULT_SENSOR_CLEANUP_HOURS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Twilio voice call sensors from a config entry."""
    # Get cleanup hours from options or use default
    cleanup_hours = config_entry.options.get(
        CONF_SENSOR_CLEANUP_HOURS, DEFAULT_SENSOR_CLEANUP_HOURS
    )
    
    # Store reference to async_add_entities for dynamic entity creation
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("sensor_manager", {})
    hass.data[DOMAIN]["sensor_manager"]["async_add_entities"] = async_add_entities
    hass.data[DOMAIN]["sensor_manager"]["entities"] = {}
    hass.data[DOMAIN]["sensor_manager"]["cleanup_timers"] = {}
    
    async def async_cleanup_sensor(call_sid: str):
        """Clean up a sensor entity."""
        entities_dict = hass.data[DOMAIN]["sensor_manager"]["entities"]
        cleanup_timers = hass.data[DOMAIN]["sensor_manager"]["cleanup_timers"]
        
        if call_sid in entities_dict:
            sensor = entities_dict.pop(call_sid)
            
            # Remove the entity from the registry
            entity_reg = er.async_get(hass)
            if entity_id := entity_reg.async_get_entity_id("sensor", DOMAIN, sensor.unique_id):
                entity_reg.async_remove(entity_id)
                _LOGGER.debug("Cleaned up sensor for call %s", call_sid)
        
        # Remove cleanup timer reference
        cleanup_timers.pop(call_sid, None)
    
    @callback
    def handle_call_event(event):
        """Handle call received event and create sensor."""
        call_sid = event.data.get(ATTR_CALL_SID)
        if not call_sid:
            return
        
        # Check if sensor already exists
        entities_dict = hass.data[DOMAIN]["sensor_manager"]["entities"]
        if call_sid in entities_dict:
            # Update existing sensor
            sensor = entities_dict[call_sid]
            sensor.update_from_event(event.data)
        else:
            # Create new sensor for this call
            sensor = TwilioCallSensor(hass, call_sid, event.data)
            entities_dict[call_sid] = sensor
            async_add_entities([sensor], True)
    
    @callback
    def handle_call_ended(event):
        """Handle call ended event."""
        call_sid = event.data.get(ATTR_CALL_SID)
        if not call_sid:
            return
        
        entities_dict = hass.data[DOMAIN]["sensor_manager"]["entities"]
        cleanup_timers = hass.data[DOMAIN]["sensor_manager"]["cleanup_timers"]
        
        if call_sid in entities_dict:
            sensor = entities_dict[call_sid]
            sensor.update_from_event(event.data)
            # Mark as ended but keep entity for historical reference
            sensor.mark_ended()
            
            # Schedule cleanup after configured time
            if call_sid not in cleanup_timers:
                cleanup_delay = timedelta(hours=cleanup_hours)
                cleanup_timers[call_sid] = async_call_later(
                    hass, cleanup_delay.total_seconds(), 
                    lambda _: hass.async_create_task(async_cleanup_sensor(call_sid))
                )
                _LOGGER.debug(
                    "Scheduled cleanup for call %s in %s hours", 
                    call_sid, cleanup_hours
                )
    
    @callback
    def handle_transcription(event):
        """Handle transcription event."""
        call_sid = event.data.get(ATTR_CALL_SID)
        if not call_sid:
            return
        
        entities_dict = hass.data[DOMAIN]["sensor_manager"]["entities"]
        if call_sid in entities_dict:
            sensor = entities_dict[call_sid]
            sensor.add_transcription(event.data.get(ATTR_TRANSCRIPTION, ""))
    
    # Register event listeners
    hass.bus.async_listen(EVENT_TWILIO_CALL_RECEIVED, handle_call_event)
    hass.bus.async_listen(EVENT_TWILIO_CALL_INITIATED, handle_call_event)
    hass.bus.async_listen(EVENT_TWILIO_CALL_ENDED, handle_call_ended)
    hass.bus.async_listen(EVENT_TWILIO_TRANSCRIPTION, handle_transcription)


class TwilioCallSensor(SensorEntity):
    """Representation of a Twilio voice call sensor."""

    def __init__(self, hass: HomeAssistant, call_sid: str, call_data: dict[str, Any]) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._call_sid = call_sid
        self._call_status = call_data.get(ATTR_CALL_STATUS, "unknown")
        self._from = call_data.get(ATTR_FROM, "")
        self._to = call_data.get(ATTR_TO, "")
        self._direction = call_data.get("direction", "")
        self._current_transcription = ""
        self._full_transcription = []
        self._ended = False
        
    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"twilio_call_{self._call_sid}"
    
    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"Twilio Call {self._call_sid[:8]}"
    
    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        return self._call_status
    
    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        if self._call_status in ["in-progress", "ringing", "queued"]:
            return "mdi:phone-in-talk"
        elif self._call_status in ["completed", "busy", "no-answer", "failed", "canceled"]:
            return "mdi:phone-hangup"
        return "mdi:phone"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            ATTR_CALL_SID: self._call_sid,
            ATTR_PHONE_NUMBER: self._to if self._direction == "outbound-api" else self._from,
            ATTR_FROM: self._from,
            ATTR_TO: self._to,
            "direction": self._direction,
            ATTR_CURRENT_TRANSCRIPTION: self._current_transcription,
            ATTR_FULL_TRANSCRIPTION: "\n".join(self._full_transcription),
        }
    
    @callback
    def update_from_event(self, event_data: dict[str, Any]) -> None:
        """Update sensor from event data."""
        self._call_status = event_data.get(ATTR_CALL_STATUS, self._call_status)
        if ATTR_FROM in event_data:
            self._from = event_data[ATTR_FROM]
        if ATTR_TO in event_data:
            self._to = event_data[ATTR_TO]
        if "direction" in event_data:
            self._direction = event_data["direction"]
        self.async_write_ha_state()
    
    @callback
    def add_transcription(self, transcription_text: str) -> None:
        """Add transcription segment."""
        if transcription_text:
            self._current_transcription = transcription_text
            self._full_transcription.append(transcription_text)
            self.async_write_ha_state()
    
    @callback
    def mark_ended(self) -> None:
        """Mark the call as ended."""
        self._ended = True
        self.async_write_ha_state()
    
    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False
