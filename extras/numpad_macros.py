from __future__ import annotations
import keyboard
import threading
import logging
import json
import time
from typing import Dict, Optional, Any

# Constants
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_DEBOUNCE_TIME = 0.3

class NumpadMacros:
    def __init__(self, config) -> None:
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.debug_log = config.getboolean('debug_log', False)

        # Initialize state
        self._state = {
            'is_printing': False,
            'last_event_time': 0,
            'last_event_key': None,
            'z_adjust_accumulator': 0.0,
            'pending_z_adjust': False,
            'last_z_adjust_time': 0.0,
            'speed_adjust_accumulator': 0.0,
            'pending_speed_adjust': False,
            'last_speed_adjust_time': 0.0,
            'z_adjust_increment': config.getfloat('z_adjust_increment', 0.01),
            'speed_adjust_increment': config.getfloat('speed_adjust_increment', 0.05),
            'min_speed_factor': config.getfloat('min_speed_factor', 0.2),
            'max_speed_factor': config.getfloat('max_speed_factor', 2.0)
        }

        self._state_lock = threading.Lock()
        self.pending_key: Optional[str] = None
        self._is_shutdown = False

        # Key mappings
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

        # Command mapping (from config)
        self.command_mapping = {}
        for key in self.key_mapping.values():
            self.command_mapping[key] = config.get(key, f"RESPOND MSG=\"{key} not assigned\"")

        # Register events
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:disconnect", self.handle_disconnect)

        # Register commands
        self.gcode.register_command('NUMPAD_TEST', self.cmd_NUMPAD_TEST,
                                    desc="Test numpad functionality")

        # Define keys that don't need confirmation
        self.no_confirm_keys = {'key_up', 'key_down'}

        # Define keys allowed during printing
        self.print_allowed_keys = {'key_dot', 'key_enter', 'key_up', 'key_down'}

    def handle_connect(self) -> None:
        """Initialize keyboard hooks"""
        try:
            # Set up keyboard hooks for all mapped keys
            for kb_key in self.key_mapping.keys():
                keyboard.on_press_key(kb_key, self._on_key_event, suppress=True)

            self._debug_log("Keyboard hooks initialized successfully")
        except Exception as e:
            self._debug_log(f"Error initializing keyboard hooks: {str(e)}")

    def _on_key_event(self, event) -> None:
        """Handle keyboard events with debouncing"""
        try:
            current_time = time.time()
            with self._state_lock:
                # Check debounce
                if (current_time - self._state['last_event_time'] < DEFAULT_DEBOUNCE_TIME and
                        event.name == self._state['last_event_key']):
                    return

                self._state['last_event_time'] = current_time
                self._state['last_event_key'] = event.name

            # Map key to command
            key = self.key_mapping.get(event.name)
            if not key:
                return

            # Schedule processing on main thread
            self.reactor.register_callback(
                lambda e, k=key: self._handle_key_press(k))

        except Exception as e:
            self._debug_log(f"Error in key event handler: {str(e)}")

    def _handle_key_press(self, key: str) -> None:
        """Process key press with proper state handling"""
        try:
            is_printing = self._check_printing_state()

            # Handle printing restrictions
            if is_printing and key not in self.print_allowed_keys:
                return

            # Handle special keys
            if key in self.no_confirm_keys:
                self._handle_special_key(key, is_printing)
                return

            # Handle regular keys
            if key == 'key_enter':
                if self.pending_key:
                    command = self.command_mapping.get(self.pending_key)
                    if command:
                        self._debug_log(f"Executing: {command}")
                        self.gcode.run_script_from_command(command)
                    self.pending_key = None
            else:
                self.pending_key = key
                command = self.command_mapping.get(key)
                if command and command.startswith('_'):
                    self.gcode.run_script_from_command(f"_QUERY{command}")

            # Notify Moonraker
            self._send_status_update(key)

        except Exception as e:
            self._debug_log(f"Error handling key press: {str(e)}")

    def _handle_special_key(self, key: str, is_printing: bool) -> None:
        """Handle up/down keys with state awareness"""
        try:
            # Check probe calibration mode
            probe_active = False
            try:
                probe_active = self.printer.lookup_object('gcode_macro CHECK_PROBE_STATUS').monitor_active
            except Exception:
                pass

            if probe_active:
                self._handle_probe_adjustment(key)
            elif is_printing:
                current_z = self._get_current_z()
                if current_z < 1.0:
                    self._handle_first_layer_adjustment(key)
                else:
                    self._handle_speed_adjustment('up' if key == 'key_up' else 'down')
            else:
                command = self.command_mapping.get(key)
                if command:
                    self.gcode.run_script_from_command(command)

        except Exception as e:
            self._debug_log(f"Error handling special key: {str(e)}")

    def handle_disconnect(self) -> None:
        """Clean up resources"""
        self._is_shutdown = True
        keyboard.unhook_all()
        self._debug_log("Keyboard hooks removed")

    def _debug_log(self, message: str) -> None:
        """Log debug messages if enabled"""
        if self.debug_log:
            logging.info(f"NumpadMacros: {message}")
            self.gcode.respond_info(f"NumpadMacros: {message}")

    def _check_printing_state(self) -> bool:
        """Check if printer is currently printing"""
        try:
            return self.printer.lookup_object('virtual_sdcard').is_active()
        except Exception:
            return False

    def _get_current_z(self) -> float:
        """Get current Z position safely"""
        try:
            return self.printer.lookup_object('toolhead').get_position()[2]
        except Exception:
            return 0.0

    def _send_status_update(self, key: str) -> None:
        """Send status update to Moonraker"""
        try:
            status = {
                'last_key': key,
                'pending_key': self.pending_key,
                'is_printing': self._check_printing_state(),
                'z_adjust_accumulator': self._state['z_adjust_accumulator'],
                'pending_z_adjust': self._state['pending_z_adjust']
            }
            self.printer.send_event("numpad:status_update", json.dumps(status))
        except Exception as e:
            self._debug_log(f"Error sending status update: {str(e)}")

    def cmd_NUMPAD_TEST(self, gcmd) -> None:
        """Handle NUMPAD_TEST command"""
        responses = [
            "NumpadMacros test command",
            f"Debug logging: {'enabled' if self.debug_log else 'disabled'}",
            f"Pending key: {self.pending_key or 'None'}",
            "Current command mapping:",
            json.dumps(self.command_mapping, indent=2)
        ]
        for response in responses:
            gcmd.respond_info(response)


def load_config(config):
    return NumpadMacros(config)