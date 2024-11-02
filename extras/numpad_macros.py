from __future__ import annotations
import evdev
from evdev import InputDevice, categorize, ecodes
import threading
import logging
import json
import time
import select
from typing import Dict, Optional, Any, Union

# Constants
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_READ_TIMEOUT = 0.1
DEFAULT_DEVICE_PATH = '/dev/input/by-id/usb-INSTANT_USB_Keyboard-event-kbd'


class NumpadMacros:
    """
    Klipper plugin for handling numpad input and executing mapped commands.
    Provides configurable key mapping and debug logging capabilities.
    """

    def __init__(self, config) -> None:
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')

        # Configuration
        self.device_path = config.get('device_path', DEFAULT_DEVICE_PATH)
        self.debug_log = config.getboolean('debug_log', False)

        # State management
        self._is_shutdown = False
        self._thread_exit = threading.Event()
        self.device: Optional[InputDevice] = None
        self.input_thread: Optional[threading.Thread] = None

        # Initialize key mappings
        self.key_mapping = self._initialize_key_mapping()
        self.command_mapping = self._initialize_command_mapping()

        # Register event handlers
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:shutdown", self.handle_shutdown)
        self.printer.register_event_handler('moonraker:connected',
                                            self.handle_moonraker_connected)

        # Register commands
        self.gcode.register_command(
            'NUMPAD_TEST',
            self.cmd_NUMPAD_TEST,
            desc="Test numpad functionality and display current configuration"
        )

        self._debug_log("NumpadMacros initialized")

    def _initialize_key_mapping(self) -> Dict[int, str]:
        """Initialize the key code to key name mapping"""
        return {
            evdev.ecodes.KEY_KP1: "1",
            evdev.ecodes.KEY_KP2: "2",
            evdev.ecodes.KEY_KP3: "3",
            evdev.ecodes.KEY_KP4: "4",
            evdev.ecodes.KEY_KP5: "5",
            evdev.ecodes.KEY_KP6: "6",
            evdev.ecodes.KEY_KP7: "7",
            evdev.ecodes.KEY_KP8: "8",
            evdev.ecodes.KEY_KP9: "9",
            evdev.ecodes.KEY_KP0: "0",
            evdev.ecodes.KEY_KPENTER: "ENTER",
            evdev.ecodes.KEY_KPDOT: "DOT"
        }

    def _initialize_command_mapping(self) -> Dict[str, str]:
        """Initialize the key to command mapping"""
        return {
            "1": "HOME",
            "2": "PROBE_BED_MESH",
            "3": "Z_TILT_ADJUST",
            "4": "BED_PROBE_MANUAL_ADJUST",
            "5": "TURN_ON_LIGHT",
            "6": "TURN_OFF_LIGHT",
            "7": "DISABLE_X_Y_STEPPERS",
            "8": "DISABLE_EXTRUDER_STEPPER",
            "9": "COLD_CHANGE_FILAMENT",
            "0": "TOGGLE_FILAMENT_SENSOR",
            "DOT": "PROBE_NOZZLE_DISTANCE",
            "ENTER": "RESUME"
        }

    def _debug_log(self, message: str) -> None:
        """Log debug messages to both system log and console if debug is enabled"""
        if self.debug_log:
            logging.info(f"NumpadMacros Debug: {message}")
            self.gcode.respond_info(f"NumpadMacros Debug: {message}")

    def handle_connect(self) -> None:
        """Initialize device connection with retry mechanism"""
        retry_count = 0
        while retry_count < DEFAULT_RETRY_COUNT and not self._is_shutdown:
            try:
                self.device = InputDevice(self.device_path)
                self._debug_log(f"Connected to device: {self.device.name}")

                # Start monitoring thread
                self.input_thread = threading.Thread(target=self._monitor_input)
                self.input_thread.daemon = True
                self.input_thread.start()

                return
            except Exception as e:
                retry_count += 1
                if retry_count == DEFAULT_RETRY_COUNT:
                    error_msg = f"Failed to initialize device after {DEFAULT_RETRY_COUNT} attempts: {str(e)}"
                    logging.error(f"NumpadMacros: {error_msg}")
                    raise self.printer.config_error(error_msg)
                self._debug_log(f"Connection attempt {retry_count} failed, retrying...")
                time.sleep(DEFAULT_RETRY_DELAY)

    def handle_shutdown(self) -> None:
        """Clean up resources during shutdown"""
        self._is_shutdown = True
        self._thread_exit.set()

        if self.device is not None:
            try:
                self.device.close()
            except Exception as e:
                self._debug_log(f"Error closing device: {str(e)}")

        if self.input_thread and self.input_thread.is_alive():
            self.input_thread.join(timeout=1.0)

    def handle_moonraker_connected(self) -> None:
        """Handle Moonraker connection event"""
        self._debug_log("Moonraker connected")
        self.send_status_to_moonraker()

    def _monitor_input(self) -> None:
        """Monitor numpad input with error recovery"""
        while not self._thread_exit.is_set() and self.device is not None:
            try:
                r, w, x = select.select([self.device.fileno()], [], [], DEFAULT_READ_TIMEOUT)
                if not r:
                    continue

                for event in self.device.read():
                    if event.type == evdev.ecodes.EV_KEY:
                        key_event = categorize(event)
                        if key_event.keystate == key_event.key_down:
                            if key_event.scancode in self.key_mapping:
                                key_value = self.key_mapping[key_event.scancode]
                                self.reactor.register_callback(
                                    lambda e, k=key_value: self._handle_key_press(k))
                                self._debug_log(f"Key pressed: {key_value}")

            except (OSError, IOError) as e:
                if not self._thread_exit.is_set():
                    self._debug_log(f"Device read error: {str(e)}, attempting recovery...")
                    time.sleep(DEFAULT_RETRY_DELAY)
                    try:
                        self.device = InputDevice(self.device_path)
                    except Exception:
                        continue
            except Exception as e:
                if not self._thread_exit.is_set():
                    self._debug_log(f"Error in input monitoring: {str(e)}")
                    time.sleep(DEFAULT_RETRY_DELAY)

    def _handle_key_press(self, key: str) -> None:
        """Handle key press events and execute mapped commands"""
        try:
            # Always show key press in console
            self.gcode.respond_info(f"NumpadMacros: Key '{key}' pressed")

            command = self.command_mapping.get(key)
            if command:
                self._debug_log(f"Executing command: {command}")
                self.gcode.run_script_from_command(command)
            else:
                self._debug_log(f"No command mapped for key: {key}")

            # Notify Moonraker
            self.printer.send_event("numpad:keypress", json.dumps({
                'key': key,
                'command': command or "Unknown"
            }))
        except Exception as e:
            error_msg = f"Error handling key press: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")

    def send_status_to_moonraker(self) -> None:
        """Send current status to Moonraker"""
        try:
            status = {
                'command_mapping': self.command_mapping,
                'connected': self.device is not None,
                'device_name': self.device.name if self.device else None,
                'debug_enabled': self.debug_log
            }
            self.printer.send_event("numpad:status_update", json.dumps(status))
            self._debug_log(f"Status sent to Moonraker: {json.dumps(status)}")
        except Exception as e:
            self._debug_log(f"Error sending status to Moonraker: {str(e)}")

    def cmd_NUMPAD_TEST(self, gcmd) -> None:
        """Handle NUMPAD_TEST command"""
        self._debug_log("Running NUMPAD_TEST command")

        responses = [
            "NumpadMacros test command received",
            f"Debug logging: {'enabled' if self.debug_log else 'disabled'}"
        ]

        if self.device is not None:
            responses.extend([
                f"Connected to: {self.device.name}",
                f"Current command mapping:",
                json.dumps(self.command_mapping, indent=2)
            ])
        else:
            responses.append("No numpad device connected")

        for response in responses:
            gcmd.respond_info(response)

    def get_status(self, eventtime: float = None) -> Dict[str, Any]:
        """Return current status"""
        return {
            'command_mapping': self.command_mapping,
            'connected': self.device is not None,
            'device_name': self.device.name if self.device else None,
            'debug_enabled': self.debug_log
        }


def load_config(config):
    return NumpadMacros(config)