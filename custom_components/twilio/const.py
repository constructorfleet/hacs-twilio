"""Constants for the Twilio integration."""

DOMAIN = "twilio"

# Configuration constants
CONF_ACCOUNT_SID = "account_sid"
CONF_AUTH_TOKEN = "auth_token"
CONF_FROM_NUMBER = "from_number"

# Data constants
DATA_TWILIO = DOMAIN

# Event types
EVENT_TWILIO_SMS_RECEIVED = f"{DOMAIN}_sms_received"
EVENT_TWILIO_CALL_RECEIVED = f"{DOMAIN}_call_received"
EVENT_TWILIO_CALL_ENDED = f"{DOMAIN}_call_ended"
EVENT_TWILIO_TRANSCRIPTION = f"{DOMAIN}_transcription_received"
EVENT_TWILIO_DTMF = f"{DOMAIN}_dtmf_received"

# Attributes
ATTR_MEDIAURL = "media_url"
ATTR_FROM = "from"
ATTR_TO = "to"
ATTR_BODY = "body"
ATTR_MEDIA_URL = "media_url"
ATTR_CALL_SID = "call_sid"
ATTR_CALL_STATUS = "call_status"
ATTR_TRANSCRIPTION = "transcription_text"
ATTR_DTMF_DIGITS = "digits"
ATTR_CURRENT_TRANSCRIPTION = "current_transcription_segment"
ATTR_FULL_TRANSCRIPTION = "full_transcription"
ATTR_PHONE_NUMBER = "phone_number"

# TwiML response types
TWIML_SAY = "say"
TWIML_PLAY = "play"
TWIML_GATHER = "gather"
TWIML_RECORD = "record"
TWIML_HANGUP = "hangup"

# Voice call configuration
CONF_VOICE = "voice"
CONF_LANGUAGE = "language"
CONF_PHRASE_MAPPINGS = "phrase_mappings"
CONF_TIMEOUT = "timeout"
CONF_NUM_DIGITS = "num_digits"
CONF_FINISH_ON_KEY = "finish_on_key"

# Status callback configuration
CONF_RECEIVE_STATUS_METHOD = "receive_status_method"

# Transcription configuration
CONF_TRANSCRIBE = "transcribe"
CONF_TRANSCRIBE_LANGUAGE = "language_code"
CONF_PROFANITY_FILTER = "profanity_filter"
CONF_PARTIAL_RESULTS = "partial_results"
CONF_AUTOMATIC_PUNCTUATION = "automatic_punctuation"

# Default values
DEFAULT_TIMEOUT = 5
DEFAULT_NUM_DIGITS = 1
DEFAULT_FINISH_ON_KEY = "#"
DEFAULT_VOICE = "alice"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_TRANSCRIBE_LANGUAGE = "en-US"

# Services
SERVICE_SEND_DTMF = "send_dtmf"
SERVICE_START_RECORDING = "start_recording"
