## Twilio Integration for Home Assistant

A comprehensive Home Assistant integration for Twilio, providing SMS, MMS, and advanced voice call capabilities with interactive features.

### Key Features

- 📱 **SMS Notifications** - Send text messages to any phone number
- 🖼️ **MMS Support** - Send multimedia messages with images
- 📞 **Voice Calls** - Make automated phone calls
- 🎙️ **Interactive Voice Response (IVR)**
  - Gather DTMF input (key presses) during calls
  - Live transcription of recorded messages
  - Phrase-to-key mapping for automated responses
- 🔔 **Event System** - Fire Home Assistant events for:
  - Incoming SMS/MMS messages
  - Incoming phone calls
  - Call status updates
  - DTMF key presses
  - Voice transcriptions
- 🌐 **Webhook Support** - Receive real-time updates from Twilio

### Quick Start

1. Get your Twilio credentials from the [Twilio Console](https://console.twilio.com/)
   - Account SID
   - Auth Token
   - A Twilio phone number

2. Add the integration:
   - Go to Settings → Devices & Services
   - Click "+ Add Integration"
   - Search for "Twilio"
   - Enter your credentials

3. Configure your Twilio phone number:
   - Set the webhook URL provided during setup
   - Configure for both SMS and Voice

### Example Usage

#### Send SMS
```yaml
service: notify.twilio_sms
data:
  message: "Hello from Home Assistant!"
  target:
    - "+1234567890"
```

#### Send MMS with Image
```yaml
service: notify.twilio_sms
data:
  message: "Check this out!"
  target:
    - "+1234567890"
  data:
    media_url:
      - "https://example.com/image.jpg"
```

#### Make Interactive Voice Call
```yaml
service: notify.twilio_call
data:
  message: "Press 1 for emergency, 2 for info"
  target:
    - "+1234567890"
  data:
    call_type: "interactive"
    gather_enabled: true
    gather_config:
      num_digits: 1
      timeout: 10
```

#### Handle Incoming SMS
```yaml
automation:
  - alias: "SMS Received"
    trigger:
      - platform: event
        event_type: twilio_sms_received
    action:
      - service: notify.persistent_notification
        data:
          message: "SMS from {{ trigger.event.data.from }}: {{ trigger.event.data.body }}"
```

### Events

The integration fires the following events:

- `twilio_sms_received` - When an SMS is received
- `twilio_call_received` - When a call is received
- `twilio_call_ended` - When a call ends
- `twilio_dtmf_received` - When DTMF keys are pressed during a call
- `twilio_transcription_received` - When a voice transcription is ready

### Blueprints Included

- **Emergency Alert** - Send SMS and call alerts when sensors trigger
- **Interactive Phone Menu** - Create phone menus that respond to key presses
- **SMS Command Handler** - Control Home Assistant via SMS commands

### Requirements

- Home Assistant 2023.1.0 or newer
- Twilio account with phone number
- Home Assistant accessible from the internet (for webhooks)

### Support

For issues and questions:
- [GitHub Issues](https://github.com/constructorfleet/hacs-twilio/issues)
- [Home Assistant Community](https://community.home-assistant.io/)

### Credits

Based on the Home Assistant Core Twilio Integration with enhanced features for HACS distribution.
