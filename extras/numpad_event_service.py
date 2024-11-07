#!/usr/bin/env python3
import keyboard
import requests
import json
import time
import logging
from logging.handlers import RotatingFileHandler

# Configuration
MOONRAKER_URL = "http://localhost:7125"
LOG_FILE = "/home/pi/printer_data/logs/numpad_event_service.log"
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

# Scan code to key name mapping
SCAN_CODE_MAPPING = {
    # Numpad specific keys
    79: "key_1",  # KEY_KP1
    80: "key_2",  # KEY_KP2
    81: "key_3",  # KEY_KP3
    75: "key_4",  # KEY_KP4
    76: "key_5",  # KEY_KP5
    77: "key_6",  # KEY_KP6
    71: "key_7",  # KEY_KP7
    72: "key_8",  # KEY_KP8
    73: "key_9",  # KEY_KP9
    82: "key_0",  # KEY_KP0
    83: "key_dot",  # KEY_KPDOT
    96: "key_enter",  # KEY_KPENTER
    114: "key_down",  # KEY_VOLUMEDOWN
    115: "key_up",  # KEY_VOLUMEUP

    # Regular number keys (for alt mode)
    2: "key_1_alt",  # KEY_1
    3: "key_2_alt",  # KEY_2
    4: "key_3_alt",  # KEY_3
    5: "key_4_alt",  # KEY_4
    6: "key_5_alt",  # KEY_5
    7: "key_6_alt",  # KEY_6
    8: "key_7_alt",  # KEY_7
    9: "key_8_alt",  # KEY_8
    10: "key_9_alt",  # KEY_9
    11: "key_0_alt",  # KEY_0
    28: "key_enter_alt",  # KEY_ENTER
    41: "key_dot_alt",  # KEY_GRAVE
}

# Set up logging
logger = logging.getLogger("NumpadListener")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def send_to_moonraker(event_data):
    """Send key event data to Moonraker"""
    try:
        response = requests.post(f"{MOONRAKER_URL}/server/numpad/event", json=event_data)
        response.raise_for_status()
        logger.info(f"Sent event data to Moonraker: {event_data}")
    except requests.RequestException as e:
        logger.error(f"Error sending event data to Moonraker: {e}")


def get_key_name(scan_code: int, original_name: str) -> str:
    """Get mapped key name from scan code or fallback to original with key_ prefix"""
    # First check if we have a specific mapping for this scan code
    if scan_code in SCAN_CODE_MAPPING:
        return SCAN_CODE_MAPPING[scan_code]

    # If no mapping exists, fallback to adding key_ prefix to original name
    return f"key_{original_name}"


def on_key_event(e):
    """Handle key events - only process key down events"""
    # Only process key down events
    if e.event_type == 'down':
        # Get the appropriate key name based on scan code or fallback
        key_name = get_key_name(e.scan_code, e.name)

        event_data = {
            "key": key_name,
            "scan_code": e.scan_code,
            "event_type": e.event_type,
            "time": e.time
        }

        logger.info(f"Key down event detected: {event_data}")
        send_to_moonraker(event_data)


def main():
    logger.info("Numpad Listener Service started")
    logger.info(f"Using scan code mapping for {len(SCAN_CODE_MAPPING)} special keys")

    keyboard.hook(on_key_event)

    logger.info("Listening for key down events...")
    keyboard.wait()


if __name__ == "__main__":
    main()