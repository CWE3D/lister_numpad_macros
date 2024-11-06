#!/usr/bin/env python3
from __future__ import annotations
import keyboard
import threading
import logging
import json
import time
import requests
import argparse
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class KeyEvent:
    key: str
    timestamp: float
    pending: bool = False


class NumpadListenerService:
    def __init__(self, moonraker_url: str, debug: bool = False) -> None:
        self.moonraker_url = moonraker_url.rstrip('/')
        self.debug = debug

        # Initialize logging
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )

        # State management
        self._state = {
            'is_printing': False,
            'last_event_time': 0,
            'last_event_key': None,
            'pending_key': None
        }
        self._state_lock = threading.Lock()
        self._is_shutdown = False

        # Key mappings (same as your original plugin)
        self.key_mapping = {
            'num_1': 'key_1',
            'num_2': 'key_2',
            'num_3': 'key_3',
            'num_4': 'key_4',
            'num_5': 'key_5',
            'num_6': 'key_6',
            'num_7': 'key_7',
            'num_8': 'key_8',
            'num_9': 'key_9',
            'num_0': 'key_0',
            'num_decimal': 'key_dot',
            'num_enter': 'key_enter',
            'volume up': 'key_up',
            'volume down': 'key_down'
        }

        # Fetch initial configuration from Moonraker
        self._fetch_config()

    def _fetch_config(self) -> None:
        """Fetch configuration from Moonraker"""
        try:
            response = requests.get(f"{self.moonraker_url}/machine/numpad/keymap")
            if response.status_code == 200:
                self.command_mapping = response.json().get('keymap', {})
                logging.info("Configuration loaded from Moonraker")
            else:
                logging.error("Failed to fetch configuration from Moonraker")
        except Exception as e:
            logging.error(f"Error fetching configuration: {str(e)}")

    def _send_event_to_moonraker(self, event: KeyEvent) -> None:
        """Send key event to Moonraker"""
        try:
            data = {
                'key': event.key,
                'timestamp': event.timestamp,
                'pending': event.pending
            }

            response = requests.post(
                f"{self.moonraker_url}/machine/numpad/keypress",
                json=data,
                timeout=1.0
            )

            if response.status_code != 200:
                logging.error(f"Failed to send event to Moonraker: {response.text}")

        except Exception as e:
            logging.error(f"Error sending event to Moonraker: {str(e)}")

    def _on_key_event(self, event) -> None:
        """Handle keyboard events with debouncing"""
        try:
            current_time = time.time()

            with self._state_lock:
                # Debounce check
                if (current_time - self._state['last_event_time'] < 0.3 and
                        event.name == self._state['last_event_key']):
                    return

                self._state['last_event_time'] = current_time
                self._state['last_event_key'] = event.name

            # Map key to internal representation
            mapped_key = self.key_mapping.get(event.name)
            if not mapped_key:
                return

            # Create key event
            key_event = KeyEvent(
                key=mapped_key,
                timestamp=current_time,
                pending=mapped_key not in {'key_up', 'key_down', 'key_enter'}
            )

            # Send to Moonraker
            self._send_event_to_moonraker(key_event)

            if self.debug:
                logging.debug(f"Key event processed: {mapped_key}")

        except Exception as e:
            logging.error(f"Error in key event handler: {str(e)}")

    def start(self) -> None:
        """Start the keyboard listener service"""
        try:
            # Set up keyboard hooks
            for kb_key in self.key_mapping.keys():
                keyboard.on_press_key(kb_key, self._on_key_event, suppress=True)

            logging.info("Numpad listener service started")

            # Keep the main thread alive
            while not self._is_shutdown:
                time.sleep(1)

        except Exception as e:
            logging.error(f"Error in listener service: {str(e)}")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Cleanup and shutdown the service"""
        self._is_shutdown = True
        keyboard.unhook_all()
        logging.info("Numpad listener service stopped")


def main():
    parser = argparse.ArgumentParser(description="Numpad Listener Service for Moonraker")
    parser.add_argument(
        '--moonraker-url',
        default='http://localhost:7125',
        help='Moonraker API URL'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    service = NumpadListenerService(args.moonraker_url, args.debug)

    try:
        service.start()
    except KeyboardInterrupt:
        service.shutdown()


if __name__ == "__main__":
    main()
