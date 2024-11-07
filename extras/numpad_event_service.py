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


def on_key_event(e):
    """Handle key events"""
    event_data = {
        "key": e.name,
        "scan_code": e.scan_code,
        "event_type": e.event_type,
        "time": e.time
    }
    logger.info(f"Key event detected: {event_data}")
    send_to_moonraker(event_data)


def main():
    logger.info("Numpad Listener Service started")

    keyboard.hook(on_key_event)

    logger.info("Listening for all key events...")
    keyboard.wait()


if __name__ == "__main__":
    main()
