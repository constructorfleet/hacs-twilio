# Twilio Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A comprehensive Home Assistant custom component for integrating with Twilio, providing SMS, MMS, and advanced voice call capabilities with interactive features.

## Features

- **SMS Notifications**: Send text messages to any phone number
- **MMS Notifications**: Send multimedia messages with images
- **Voice Call Notifications**: Make automated phone calls
- **Interactive Voice Response (IVR)**: 
  - Gather DTMF input (key presses) during calls
  - Live transcription of recorded messages
  - Phrase-to-key mapping for automated responses
- **Event-Driven**: Fire Home Assistant events for:
  - Incoming SMS/MMS messages
  - Incoming phone calls
  - Call status updates
  - DTMF key presses
  - Voice transcriptions
- **Webhook Support**: Receive real-time updates from Twilio

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/constructorfleet/hacs-twilio`
6. Select category: "Integration"
7. Click "Add"
8. Find "Twilio" in the integration list and click "Download"
9. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/twilio` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### UI Configuration (Recommended)

1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Twilio"
4. Enter your Twilio credentials:
   - **Account SID**: Found in your [Twilio Console](https://console.twilio.com/)
   - **Auth Token**: Found in your [Twilio Console](https://console.twilio.com/)
5. After setup, you'll receive a webhook URL - configure this in your Twilio phone number settings

### YAML Configuration (Legacy)

Add to your `configuration.yaml`:

```yaml
twilio:
  account_sid: YOUR_ACCOUNT_SID
  auth_token: YOUR_AUTH_TOKEN

notify:
  - name: twilio_sms
    platform: twilio
    from_number: "+1234567890"
  
  - name: twilio_call
    platform: twilio
    from_number: "+1234567890"
    voice: "alice"
    language: "en-US"
```

## Usage

### Sending SMS/MMS

#### Simple SMS

```yaml
service: notify.twilio_sms
data:
  message: "Hello from Home Assistant!"
  target:
    - "+1234567890"
```

#### MMS with Image

```yaml
service: notify.twilio_sms
data:
  message: "Check out this image!"
  target:
    - "+1234567890"
  data:
    media_url:
      - "https://example.com/image.jpg"
```

### Making Voice Calls

#### Simple Voice Message

```yaml
service: notify.twilio_call
data:
  message: "Hello! This is an automated call from Home Assistant."
  target:
    - "+1234567890"
```

#### Interactive Call with DTMF Collection

```yaml
service: notify.twilio_call
data:
  message: "Press 1 for emergency, 2 for information, or 3 to speak to someone."
  target:
    - "+1234567890"
  data:
    call_type: "interactive"
    gather_enabled: true
    gather_config:
      num_digits: 1
      timeout: 5
      finish_on_key: "#"
```

#### Call with Recording and Transcription

```yaml
service: notify.twilio_call
data:
  message: "Please leave a message after the beep."
  target:
    - "+1234567890"
  data:
    call_type: "interactive"
    record_enabled: true
    transcribe_enabled: true
```

## Events

The integration fires various events that you can use in automations:

### SMS Received Event

```yaml
automation:
  - alias: "Handle Incoming SMS"
    trigger:
      - platform: event
        event_type: twilio_sms_received
    action:
      - service: notify.persistent_notification
        data:
          message: "SMS from {{ trigger.event.data.from }}: {{ trigger.event.data.body }}"
```

### DTMF Key Press Event

```yaml
automation:
  - alias: "Handle Phone Menu Selection"
    trigger:
      - platform: event
        event_type: twilio_dtmf_received
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.digits == '1' }}"
    action:
      - service: light.turn_on
        target:
          entity_id: light.living_room
```

### Call Received Event

```yaml
automation:
  - alias: "Log Incoming Calls"
    trigger:
      - platform: event
        event_type: twilio_call_received
    action:
      - service: logbook.log
        data:
          name: "Incoming Call"
          message: "Call from {{ trigger.event.data.from }}"
```

### Transcription Received Event

```yaml
automation:
  - alias: "Process Voice Message"
    trigger:
      - platform: event
        event_type: twilio_transcription_received
    action:
      - service: notify.mobile_app
        data:
          message: "Voice message: {{ trigger.event.data.transcription_text }}"
```

## Advanced Configuration

### Phrase-to-Key Mapping

Configure automated responses to voice prompts:

```yaml
notify:
  - name: twilio_call
    platform: twilio
    from_number: "+1234567890"
    phrase_mappings:
      "press 1 for english": "1"
      "press 2 for spanish": "2"
      "enter your code": "1234"
      "pound key to continue": "#"
```

## Webhook Configuration

After setting up the integration, configure your Twilio phone number webhooks:

1. Go to [Twilio Console → Phone Numbers](https://console.twilio.com/us1/develop/phone-numbers/manage/incoming)
2. Select your phone number
3. Under "Messaging", set:
   - **A MESSAGE COMES IN**: Webhook → Your webhook URL → HTTP POST
4. Under "Voice & Fax", set:
   - **A CALL COMES IN**: Webhook → Your webhook URL → HTTP POST
   - **CALL STATUS CHANGES**: Webhook → Your webhook URL → HTTP POST
5. Save your changes

## Blueprints

### Emergency Alert System

```yaml
blueprint:
  name: Emergency Alert via Twilio
  description: Send emergency alerts via SMS and voice call
  domain: automation
  input:
    emergency_sensor:
      name: Emergency Sensor
      selector:
        entity:
          domain: binary_sensor
    phone_number:
      name: Phone Number
      selector:
        text:
    
automation:
  trigger:
    - platform: state
      entity_id: !input emergency_sensor
      to: "on"
  action:
    - service: notify.twilio_sms
      data:
        message: "EMERGENCY ALERT: {{ trigger.to_state.attributes.friendly_name }} triggered!"
        target:
          - !input phone_number
    - service: notify.twilio_call
      data:
        message: "Emergency! {{ trigger.to_state.attributes.friendly_name }} has been triggered. Please check your home immediately."
        target:
          - !input phone_number
```

## Troubleshooting

### Check Logs

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.twilio: debug
    twilio: debug
```

### Common Issues

1. **Authentication Failed**: Double-check your Account SID and Auth Token
2. **Webhook Not Receiving Data**: Ensure your Home Assistant instance is accessible from the internet and the webhook URL is correctly configured in Twilio
3. **SMS Not Sending**: Verify your Twilio account has SMS capabilities and sufficient balance
4. **Voice Calls Failing**: Check that your Twilio phone number has voice capabilities enabled

## Support

For issues, feature requests, or questions:
- Open an issue on [GitHub](https://github.com/constructorfleet/hacs-twilio/issues)
- Check the [Home Assistant Community](https://community.home-assistant.io/)

## License

This project is licensed under the MIT License.

## Credits

Based on the [Home Assistant Core Twilio Integration](https://www.home-assistant.io/integrations/twilio/) with enhanced features for HACS distribution.
