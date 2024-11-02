from __future__ import annotations
import evdev
from evdev import InputDevice, categorize, ecodes
import threading
import logging
import json
import time
import select
from typing import Dict, Optional, Any, Union, List

# Constants
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_READ_TIMEOUT = 0.1
DEFAULT_DEVICE_PATH = '/dev/input/by-id/usb-INSTANT_USB_Keyboard-event-kbd, /dev/input/by-id/usb-INSTANT_USB_Keyboard-event-if01'

class NumpadMacros:
    """
    Klipper plugin for handling multiple input devices and executing mapped commands.
    Supports multiple devices, configurable key mapping, and debug logging.
    """

    def __init__(self, config) -> None:
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')

        # Configuration
        device_paths = config.get('device_paths', DEFAULT_DEVICE_PATH).split(',')
        self.device_paths = [path.strip() for path in device_paths]
        self.debug_log = config.getboolean('debug_log', False)

        # State management
        self._is_shutdown = False
        self._thread_exit = threading.Event()
        self.devices: Dict[str, InputDevice] = {}
        self.input_threads: Dict[str, threading.Thread] = {}

        # Initialize key mappings
        self.key_mapping = self._initialize_key_mapping()

        # Initialize default commands
        self.command_mapping = self._initialize_command_mapping()

        # Register valid config options
        valid_keys = list(self.command_mapping.keys()) + ['device_paths', 'debug_log']
        config.get_prefix_options(valid_keys)

        # Override commands from config
        for key in self.command_mapping.keys():
            if config.get(key, None) is not None:
                self.command_mapping[key] = config.get(key)

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

        self._debug_log("NumpadMacrosClient initialized")

    def _initialize_key_mapping(self) -> Dict[int, str]:
        """Initialize the key code to key name mapping"""
        return {
            # Regular number keys based on observed codes
            2: "key_1",  # KEY_1
            3: "2",  # KEY_2
            4: "3",  # KEY_3
            5: "4",  # KEY_4
            6: "5",  # KEY_5
            7: "6",  # KEY_6
            8: "7",  # KEY_7
            9: "8",  # KEY_8
            10: "9",  # KEY_9
            11: "0",  # KEY_0
            96: "ENTER",  # KEY_KPENTER
            # Volume knob mappings
            114: "DOWN",  # KEY_VOLUMEDOWN
            115: "UP",  # KEY_VOLUMEUP

            # Also include evdev constants for compatibility
            evdev.ecodes.KEY_1: "key_1",
            evdev.ecodes.KEY_2: "2",
            evdev.ecodes.KEY_3: "3",
            evdev.ecodes.KEY_4: "4",
            evdev.ecodes.KEY_5: "5",
            evdev.ecodes.KEY_6: "6",
            evdev.ecodes.KEY_7: "7",
            evdev.ecodes.KEY_8: "8",
            evdev.ecodes.KEY_9: "9",
            evdev.ecodes.KEY_0: "0",
            evdev.ecodes.KEY_KPENTER: "ENTER",
            evdev.ecodes.KEY_DOT: "DOT",
            evdev.ecodes.KEY_KPDOT: "DOT",
            evdev.ecodes.KEY_VOLUMEDOWN: "DOWN",
            evdev.ecodes.KEY_VOLUMEUP: "UP"
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
            "ENTER": "RESUME",
            "UP": "SET_GCODE_OFFSET Z_ADJUST=0.025 MOVE=1",  # Raise nozzle
            "DOWN": "SET_GCODE_OFFSET Z_ADJUST=-0.025 MOVE=1"  # Lower nozzle
        }

    def _debug_log(self, message: str) -> None:
        """Log debug messages to both system log and console if debug is enabled"""
        if self.debug_log:
            logging.info(f"NumpadMacrosClient Debug: {message}")
            self.gcode.respond_info(f"NumpadMacrosClient Debug: {message}")

    def handle_connect(self) -> None:
        """Initialize all configured devices with retry mechanism"""
        for device_path in self.device_paths:
            retry_count = 0
            while retry_count < DEFAULT_RETRY_COUNT and not self._is_shutdown:
                try:
                    device = InputDevice(device_path)
                    self.devices[device_path] = device
                    self._debug_log(f"Connected to device: {device.name}")

                    # Print device capabilities if debug is enabled
                    if self.debug_log:
                        self._log_device_capabilities(device)

                    # Start monitoring thread for this device
                    thread = threading.Thread(
                        target=self._monitor_input,
                        args=(device_path,)
                    )
                    thread.daemon = True
                    thread.start()
                    self.input_threads[device_path] = thread
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count == DEFAULT_RETRY_COUNT:
                        error_msg = f"Failed to initialize device {device_path} after {DEFAULT_RETRY_COUNT} attempts: {str(e)}"
                        self._debug_log(error_msg)
                    else:
                        self._debug_log(f"Connection attempt {retry_count} failed for {device_path}, retrying...")
                        time.sleep(DEFAULT_RETRY_DELAY)

    def _log_device_capabilities(self, device: InputDevice) -> None:
        """Log device capabilities for debugging"""
        self._debug_log(f"Device capabilities for {device.name}:")
        self._debug_log(f"Device info: {device.info}")
        self._debug_log(f"Supported events: {device.capabilities(verbose=True)}")

    def handle_shutdown(self) -> None:
        """Clean up resources during shutdown"""
        self._is_shutdown = True
        self._thread_exit.set()

        for device_path, device in self.devices.items():
            try:
                device.close()
            except Exception as e:
                self._debug_log(f"Error closing device {device_path}: {str(e)}")

        for thread in self.input_threads.values():
            if thread.is_alive():
                thread.join(timeout=1.0)

    def handle_moonraker_connected(self) -> None:
        """Handle Moonraker connection event"""
        self._debug_log("Moonraker connected")
        self.send_status_to_moonraker()

    def _monitor_input(self, device_path: str) -> None:
        """Monitor input device with error recovery"""
        device = self.devices.get(device_path)
        if not device:
            return

        while not self._thread_exit.is_set():
            try:
                r, w, x = select.select([device.fileno()], [], [], DEFAULT_READ_TIMEOUT)
                if not r:
                    continue

                for event in device.read():
                    if event.type == evdev.ecodes.EV_KEY:
                        key_event = categorize(event)

                        # Enhanced debug logging for all key events
                        if self.debug_log:
                            self._debug_log(
                                f"Key event from {device.name} - "
                                f"code: {key_event.scancode}, "
                                f"name: {key_event.keycode}, "
                                f"type: {event.type}, "
                                f"value: {event.value}"
                            )

                        if key_event.keystate == key_event.key_down:
                            # Try both the scancode and the raw code
                            key_value = self.key_mapping.get(key_event.scancode)
                            if key_value is None:
                                key_value = self.key_mapping.get(event.code)

                            if key_value is not None:
                                self.reactor.register_callback(
                                    lambda e, k=key_value: self._handle_key_press(k, device.name))
                                self._debug_log(f"Key mapped and processed: {key_value}")
                            else:
                                self._debug_log(
                                    f"Unhandled key from {device.name}: {key_event.keycode} "
                                    f"(scancode: {key_event.scancode}, "
                                    f"code: {event.code})"
                                )

            except (OSError, IOError) as e:
                if not self._thread_exit.is_set():
                    self._debug_log(f"Device read error on {device_path}: {str(e)}, attempting recovery...")
                    time.sleep(DEFAULT_RETRY_DELAY)
                    try:
                        device = InputDevice(device_path)
                        self.devices[device_path] = device
                    except Exception:
                        continue
            except Exception as e:
                if not self._thread_exit.is_set():
                    self._debug_log(f"Error in input monitoring for {device_path}: {str(e)}")
                    time.sleep(DEFAULT_RETRY_DELAY)

    def _handle_key_press(self, key: str, device_name: str) -> None:
        """Handle key press events and execute mapped commands"""
        try:
            # Always show key press in console
            self.gcode.respond_info(f"NumpadMacros: Key '{key}' pressed on {device_name}")

            command = self.command_mapping.get(key)
            if command:
                self._debug_log(f"Executing command: {command}")
                self.gcode.run_script_from_command(command)
            else:
                self._debug_log(f"No command mapped for key: {key}")

            # Notify Moonraker
            self.printer.send_event("numpad:keypress", json.dumps({
                'key': key,
                'command': command or "Unknown",
                'device': device_name
            }))
        except Exception as e:
            error_msg = f"Error handling key press: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacrosClient Error: {error_msg}")

    def send_status_to_moonraker(self) -> None:
        """Send current status to Moonraker"""
        try:
            status = {
                'command_mapping': self.command_mapping,
                'connected_devices': {
                    path: device.name for path, device in self.devices.items()
                },
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
            "NumpadMacrosClient test command received",
            f"Debug logging: {'enabled' if self.debug_log else 'disabled'}"
        ]

        if self.devices:
            for path, device in self.devices.items():
                responses.extend([
                    f"Connected device: {device.name}",
                    f"Path: {path}"
                ])
            responses.extend([
                "Current command mapping:",
                json.dumps(self.command_mapping, indent=2)
            ])
        else:
            responses.append("No input devices connected")

        for response in responses:
            gcmd.respond_info(response)

    def get_status(self, eventtime: float = None) -> Dict[str, Any]:
        """Return current status"""
        return {
            'command_mapping': self.command_mapping,
            'connected_devices': {
                path: device.name for path, device in self.devices.items()
            },
            'debug_enabled': self.debug_log
        }


def load_config(config):
    return NumpadMacros(config)