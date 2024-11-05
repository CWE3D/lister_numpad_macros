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
    def __init__(self, config) -> None:
        # Initialize basic objects
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.query_prefix = config.get('query_prefix', '_QUERY')

        self.last_global_event_time = 0
        self.last_global_event_code = None
        self.global_debounce_time = 0.3  # 300ms global debounce

        # Get configuration values
        device_paths = config.get('device_paths', DEFAULT_DEVICE_PATH).split(',')
        self.device_paths = [path.strip() for path in device_paths]
        self.debug_log = config.getboolean('debug_log', False)

        # Add configuration for keys that don't require confirmation
        default_no_confirm = "key_up,key_down"  # Default keys that don't need confirmation
        no_confirm_str = config.get('no_confirm_keys', default_no_confirm)
        self.no_confirm_keys = [key.strip() for key in no_confirm_str.split(',') if key.strip()]

        # Define key options
        self.key_options = [
            'key_1',
            'key_2',
            'key_3',
            'key_4',
            'key_5',
            'key_6',
            'key_7',
            'key_8',
            'key_9',
            'key_0',
            'key_dot',
            'key_enter',
            'key_grave',
            'key_1_alt',
            'key_2_alt',
            'key_3_alt',
            'key_4_alt',
            'key_5_alt',
            'key_6_alt',
            'key_7_alt',
            'key_8_alt',
            'key_9_alt',
            'key_0_alt',
            'key_dot_alt',
            'key_enter_alt',
            'key_up',
            'key_down',
        ]

        # Add debounce tracking
        self.last_knob_event_time: Dict[str, float] = {
            'key_up': 0.0,
            'key_down': 0.0
        }
        self.knob_debounce_delay = config.getfloat('knob_debounce_delay', 0.3)  # 100ms default

        # Initialize command mapping
        self.command_mapping = {}
        for key in self.key_options:
            self.command_mapping[key] = config.get(key, f"RESPOND MSG=\"{key} not assigned yet\"")

        # Initialize key mapping
        self.key_mapping = self._initialize_key_mapping()

        # Add pending key tracking
        self.pending_key: Optional[str] = None

        # State management
        self._is_shutdown = False
        self._thread_exit = threading.Event()
        self.devices: Dict[str, InputDevice] = {}
        self.input_threads: Dict[str, threading.Thread] = {}

        # Register event handlers
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:shutdown", self.handle_shutdown)
        self.printer.register_event_handler('moonraker:connected', self.handle_moonraker_connected)

        # Register commands
        self.gcode.register_command(
            'NUMPAD_TEST',
            self.cmd_NUMPAD_TEST,
            desc="Test numpad functionality and display current configuration"
        )

    def _debug_log(self, message: str) -> None:
        """Log debug messages to both system log and console if debug is enabled"""
        if self.debug_log:
            logging.info(f"NumpadMacrosClient Debug: {message}")
            self.gcode.respond_info(f"NumpadMacrosClient Debug: {message}")

    @staticmethod
    def _initialize_key_mapping() -> Dict[int, str]:
        """Initialize the key code to key name mapping"""
        mapping = {
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
            114: "key_down",
            115: "key_up",

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
        return mapping

    def _should_process_event(self, event_code: int, device_name: str) -> bool:
        """
        Determine if an event should be processed based on global event history
        """
        current_time = time.time()
        time_since_last = current_time - self.last_global_event_time

        # If this is the same event code within debounce period, skip it
        if (time_since_last < self.global_debounce_time and
                event_code == self.last_global_event_code):
            self._debug_log(f"Debouncing duplicate event from {device_name} "
                            f"(code: {event_code}, time since last: {time_since_last:.3f}s)")
            return False

        # Update global tracking
        self.last_global_event_time = current_time
        self.last_global_event_code = event_code
        return True

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

                        # Debug logging for all events if enabled
                        if self.debug_log:
                            self._debug_log(
                                f"Raw key event from {device.name} - "
                                f"code: {key_event.scancode}, "
                                f"name: {key_event.keycode}, "
                                f"type: {event.type}, "
                                f"value: {event.value}, "
                                f"device: {device_path}"
                            )

                        # Only process press events (value == 1) for ALL keys
                        if event.value == 1:
                            # Check global event history before processing
                            if not self._should_process_event(key_event.scancode, device.name):
                                continue

                            key_value = self.key_mapping.get(key_event.scancode)
                            if key_value is None:
                                key_value = self.key_mapping.get(event.code)

                            if key_value is not None:
                                self.reactor.register_callback(
                                    lambda e, k=key_value: self._handle_key_press(k, device.name))
                                self._debug_log(f"Processing key press for: {key_value} from {device_path}")
                        else:
                            # Debug log for ignored events
                            event_type = "release" if event.value == 0 else "hold"
                            self._debug_log(f"Ignoring key {event_type} event for {key_event.keycode} "
                                          f"from {device_path}")

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
        """Handle key press events with enhanced debugging"""
        try:
            # Special handling for knob inputs
            if key in ['key_up', 'key_down']:
                current_time = time.time()
                last_event_time = self.last_knob_event_time[key]

                # Strict 300ms debounce for knob events
                if (current_time - last_event_time) < 0.3:
                    self._debug_log(f"Strict debouncing {key} event, skipping")
                    return

                # Update last event time before processing
                self.last_knob_event_time[key] = current_time

                # Get command mapping once
                command = self.command_mapping.get(key)
                if command:
                    try:
                        self._debug_log(f"Executing knob command: {command}")
                        self.gcode.run_script_from_command(command)
                    except Exception as cmd_error:
                        error_msg = f"Error executing command '{command}': {str(cmd_error)}"
                        self._debug_log(error_msg)
                        self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")
                return

            # Show key press in console
            self.gcode.respond_info(f"NumpadMacros: Key '{key}' pressed on {device_name}")

            # Check if this key needs confirmation
            if key in self.no_confirm_keys:
                # Execute immediately without waiting for ENTER
                command = self.command_mapping.get(key)
                self._debug_log(f"No confirm key detected, command: {command}")
                if command:
                    self._debug_log(f"Executing command without confirmation: {command}")
                    try:
                        self.gcode.run_script_from_command(command)
                    except Exception as cmd_error:
                        error_msg = f"Error executing command '{command}': {str(cmd_error)}"
                        self._debug_log(error_msg)
                        self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")
                return

            if key in ["key_enter", "key_enter_alt"]:
                # Execute pending command if there is one
                if self.pending_key:
                    command = self.command_mapping.get(self.pending_key)
                    if command:
                        self._debug_log(f"Executing command: {command}")
                        try:
                            self.gcode.run_script_from_command(command)
                        except Exception as cmd_error:
                            error_msg = f"Error executing command '{command}': {str(cmd_error)}"
                            self._debug_log(error_msg)
                            self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")
                    else:
                        self._debug_log(f"No command mapped for key: {self.pending_key}")

                    # Clear pending key after execution or error
                    self.pending_key = None
                else:
                    self._debug_log("No pending key to execute")
            else:
                # Store new pending key, overwriting any existing one
                self.pending_key = key

                # Execute query version of the command if it exists
                command = self.command_mapping.get(key)
                if command and command.startswith('_'):
                    # Simply prepend _QUERY to the actual command name
                    query_command = f"_QUERY{command}"
                    self._debug_log(f"Attempting to execute query command: {query_command}")
                    try:
                        self.gcode.run_script_from_command(query_command)
                    except Exception as query_error:
                        # Only log debug message if query fails - don't interrupt normal flow
                        self._debug_log(f"Query command failed with error: {str(query_error)}")

                self._debug_log(f"Stored pending key: {key} (press ENTER to execute)")

            # Notify Moonraker of the keypress
            self.printer.send_event("numpad:keypress", json.dumps({
                'key': key,
                'pending_key': self.pending_key,
                'device': device_name
            }))

        except Exception as e:
            error_msg = f"Error handling key press: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")

    def handle_connect(self) -> None:
        """Initialize all configured devices with retry mechanism"""
        for device_path in self.device_paths:
            retry_count = 0
            while retry_count < DEFAULT_RETRY_COUNT and not self._is_shutdown:
                try:
                    device = InputDevice(device_path)
                    self.devices[device_path] = device
                    self._debug_log(f"Connected to device: {device.name}")

                    if self.debug_log:
                        self._log_device_capabilities(device)

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

    def send_status_to_moonraker(self) -> None:
        """Send current status to Moonraker"""
        try:
            status = {
                'command_mapping': self.command_mapping,
                'connected_devices': {
                    path: device.name for path, device in self.devices.items()
                },
                'debug_enabled': self.debug_log,
                'pending_key': self.pending_key
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
            f"Debug logging: {'enabled' if self.debug_log else 'disabled'}",
            f"Pending key: {self.pending_key or 'None'}"
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
            'debug_enabled': self.debug_log,
            'pending_key': self.pending_key
        }


def load_config(config):
    return NumpadMacros(config)