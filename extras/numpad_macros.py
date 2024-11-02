import evdev
from evdev import InputDevice, categorize, ecodes
import threading
import logging
import json


class NumpadMacros:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.shutdown = False

        # Get configuration
        self.device_path = config.get('device_path', '/dev/input/by-id/usb-INSTANT_USB_Keyboard-event-kbd')
        self.debug_log = config.getboolean('debug_log', False)  # Add debug logging configuration

        # Register event handlers
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:shutdown", self.handle_shutdown)

        # Register commands
        self.gcode.register_command(
            'NUMPAD_TEST',
            self.cmd_NUMPAD_TEST,
            desc="Test numpad functionality"
        )

        # Key mapping for numpad (adjust these based on your device)
        self.key_mapping = {
            # Numpad key codes to their corresponding values
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

        # Default command mapping
        self.command_mapping = {
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

        # Start the input monitoring thread
        self.input_thread = None

        # Register for Moonraker component initialization
        self.printer.register_event_handler(
            'moonraker:connected',
            self.handle_moonraker_connected
        )

        # Log initialization if debug is enabled
        self._debug_log("NumpadMacros initialized with debug logging enabled")

    def _debug_log(self, message):
        """Helper method for debug logging"""
        if self.debug_log:
            logging.info(f"NumpadMacros Debug: {message}")
            # Also echo to console for visibility in Mainsail
            self.gcode.respond_info(f"NumpadMacros Debug: {message}")

    def handle_moonraker_connected(self):
        """Called when Moonraker connects"""
        self._debug_log("Moonraker connected")
        # Send initial configuration to Moonraker
        self.send_status_to_moonraker()

    def send_status_to_moonraker(self):
        """Send current status to Moonraker"""
        try:
            status = {
                'command_mapping': self.command_mapping,
                'connected': hasattr(self, 'device'),
                'device_name': self.device.name if hasattr(self, 'device') else None,
                'debug_enabled': self.debug_log
            }
            self.printer.send_event("numpad:status_update", json.dumps(status))
            self._debug_log(f"Status sent to Moonraker: {json.dumps(status)}")
        except Exception as e:
            error_msg = f"Error sending status to Moonraker: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")

    def handle_connect(self):
        """Called when printer connects"""
        try:
            self.device = InputDevice(self.device_path)
            connect_msg = f"Connected to device {self.device.name}"
            logging.info(f"NumpadMacros: {connect_msg}")
            self._debug_log(connect_msg)

            # Start monitoring thread
            self.input_thread = threading.Thread(target=self._monitor_input)
            self.input_thread.daemon = True
            self.input_thread.start()

            # Send initial status to Moonraker
            self.send_status_to_moonraker()

        except Exception as e:
            error_msg = f"Failed to initialize device: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")
            raise self.printer.config_error(f"Failed to initialize numpad device: {str(e)}")

    def handle_shutdown(self):
        """Called when printer shuts down"""
        self.shutdown = True
        if hasattr(self, 'device'):
            self.device.close()
        self._debug_log("NumpadMacros shutdown")

    def _monitor_input(self):
        """Monitor numpad input in a separate thread"""
        try:
            for event in self.device.read_loop():
                if self.shutdown:
                    break

                if event.type == evdev.ecodes.EV_KEY:
                    key_event = categorize(event)

                    # Only process key press events (not releases)
                    if key_event.keystate == key_event.key_down:
                        key_code = key_event.scancode

                        if key_code in self.key_mapping:
                            key_value = self.key_mapping[key_code]
                            # Schedule the key handling in the main thread
                            self.reactor.register_callback(
                                lambda e, k=key_value: self._handle_key_press(k))
                            self._debug_log(f"Key pressed: {key_value} (scancode: {key_code})")

        except Exception as e:
            error_msg = f"Error in input monitoring: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")

    def _handle_key_press(self, key):
        """Handle a key press event"""
        try:
            # Notify Moonraker of key press
            press_data = {
                'key': key,
                'command': self.command_mapping.get(key, "Unknown")
            }
            self.printer.send_event("numpad:keypress", json.dumps(press_data))

            # Always show key press in console for user feedback
            self.gcode.respond_info(f"NumpadMacros: Key '{key}' pressed")

            # Execute mapped command if available
            command = self.command_mapping.get(key)
            if command:
                self._debug_log(f"Executing command: {command}")
                self.gcode.run_script_from_command(command)
            else:
                self._debug_log(f"No command mapped for key: {key}")

        except Exception as e:
            error_msg = f"Error handling key press: {str(e)}"
            logging.error(f"NumpadMacros: {error_msg}")
            if self.debug_log:
                self.gcode.respond_info(f"NumpadMacros Error: {error_msg}")

    def cmd_NUMPAD_TEST(self, gcmd):
        """G-code command to test numpad functionality"""
        self._debug_log("Running NUMPAD_TEST command")
        gcmd.respond_info("NumpadMacros test command received")
        if hasattr(self, 'device'):
            gcmd.respond_info(f"Connected to: {self.device.name}")
            gcmd.respond_info(f"Current command mapping: {json.dumps(self.command_mapping, indent=2)}")
            gcmd.respond_info(f"Debug logging: {'enabled' if self.debug_log else 'disabled'}")
        else:
            gcmd.respond_info("No numpad device connected")

    def get_status(self, eventtime=None):
        """Return status for Moonraker"""
        return {
            'command_mapping': self.command_mapping,
            'connected': hasattr(self, 'device'),
            'device_name': self.device.name if hasattr(self, 'device') else None,
            'debug_enabled': self.debug_log
        }


def load_config(config):
    return NumpadMacros(config)