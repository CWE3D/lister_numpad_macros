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
        self.device_path = config.get('device_path', '/dev/input/by-id/usb-SIGMACHIP_USB_Keyboard-event-kbd')

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

    def handle_moonraker_connected(self):
        """Called when Moonraker connects"""
        logging.info("NumpadMacros: Moonraker connected")
        # Send initial configuration to Moonraker
        self.send_status_to_moonraker()

    def send_status_to_moonraker(self):
        """Send current status to Moonraker"""
        try:
            status = {
                'command_mapping': self.command_mapping,
                'connected': hasattr(self, 'device'),
                'device_name': self.device.name if hasattr(self, 'device') else None
            }
            self.printer.send_event("numpad:status_update", json.dumps(status))
        except Exception as e:
            logging.error(f"NumpadMacros: Error sending status to Moonraker: {str(e)}")

    def handle_connect(self):
        """Called when printer connects"""
        try:
            self.device = InputDevice(self.device_path)
            logging.info(f"NumpadMacros: Connected to device {self.device.name}")

            # Start monitoring thread
            self.input_thread = threading.Thread(target=self._monitor_input)
            self.input_thread.daemon = True
            self.input_thread.start()

            # Send initial status to Moonraker
            self.send_status_to_moonraker()

        except Exception as e:
            logging.error(f"NumpadMacros: Failed to initialize device: {str(e)}")
            raise self.printer.config_error(f"Failed to initialize numpad device: {str(e)}")

    def handle_shutdown(self):
        """Called when printer shuts down"""
        self.shutdown = True
        if hasattr(self, 'device'):
            self.device.close()

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

        except Exception as e:
            logging.error(f"NumpadMacros: Error in input monitoring: {str(e)}")

    def _handle_key_press(self, key):
        """Handle a key press event"""
        try:
            # Notify Moonraker of key press
            self.printer.send_event("numpad:keypress", json.dumps({
                'key': key,
                'command': self.command_mapping.get(key, "Unknown")
            }))

            # Execute mapped command if available
            command = self.command_mapping.get(key)
            if command:
                self.gcode.run_script_from_command(command)
            else:
                self.gcode.respond_info(f"No command mapped for key: {key}")

        except Exception as e:
            logging.error(f"NumpadMacros: Error handling key press: {str(e)}")

    def cmd_NUMPAD_TEST(self, gcmd):
        """G-code command to test numpad functionality"""
        gcmd.respond_info("NumpadMacros test command received")
        if hasattr(self, 'device'):
            gcmd.respond_info(f"Connected to: {self.device.name}")
            gcmd.respond_info(f"Current command mapping: {json.dumps(self.command_mapping, indent=2)}")
        else:
            gcmd.respond_info("No numpad device connected")

    def get_status(self, eventtime=None):
        """Return status for Moonraker"""
        return {
            'command_mapping': self.command_mapping,
            'connected': hasattr(self, 'device'),
            'device_name': self.device.name if hasattr(self, 'device') else None
        }


def load_config(config):
    return NumpadMacros(config)