import logging


class NumpadMacros:
    def __init__(self, config):
        self.server = config.get_server()
        self.printer = self.server.lookup_component('printer')
        self.keymap_config = {}

        # Initialize default config
        self._init_keymap_config(config)

        # Register endpoints
        self.server.register_endpoint(
            "/machine/numpad/keymap",
            ['GET', 'POST'],
            self._handle_keymap_request
        )
        self.server.register_endpoint(
            "/machine/numpad/status",
            ['GET'],
            self._handle_status_request
        )

        # Register notification methods
        self.server.register_notification("numpad:keypress")

        # Register printer event handlers
        self.server.register_event_handler(
            "server:klippy_ready",
            self._handle_ready
        )

    def _init_keymap_config(self, config):
        """Initialize keymap configuration with defaults"""
        default_keymap = {
            "1": "HOME",  # G28
            "2": "PROBE_BED_MESH",  # Generate bed mesh
            "3": "Z_TILT_ADJUST",  # Adjust Z tilt
            "4": "BED_PROBE_MANUAL_ADJUST",  # Manual bed adjustment
            "5": "TURN_ON_LIGHT",  # Turn on printer light
            "6": "TURN_OFF_LIGHT",  # Turn off printer light
            "7": "DISABLE_X_Y_STEPPERS",  # Disable X/Y steppers
            "8": "DISABLE_EXTRUDER_STEPPER",  # Disable extruder
            "9": "COLD_CHANGE_FILAMENT",  # Change filament
            "0": "TOGGLE_FILAMENT_SENSOR",  # Toggle filament sensor
            "DOT": "PROBE_NOZZLE_DISTANCE",  # Probe calibration
            "ENTER": "RESUME"  # Resume print
        }

        # Load config from moonraker.conf
        for key in default_keymap:
            config_key = f"key_{key}"
            self.keymap_config[key] = config.get(config_key, default_keymap[key])

    async def _handle_ready(self):
        """Handle Klippy ready event"""
        logging.info("Numpad Macros Plugin Ready")
        # Additional initialization if needed

    async def _handle_keypress(self, key):
        """Handle keypress events from Klipper"""
        # Send notification to connected clients
        await self.server.send_event("numpad:keypress", {
            'key': key,
            'command': self.keymap_config.get(key, "Unknown")
        })

    async def _handle_keymap_request(self, web_request):
        """Handle keymap GET/POST requests"""
        if web_request.get_method() == 'GET':
            return {'keymap': self.keymap_config}

        # Handle POST - update keymap
        data = web_request.get_json_body()
        new_keymap = data.get('keymap', {})

        # Validate and update keymap
        for key, command in new_keymap.items():
            if key in self.keymap_config:
                self.keymap_config[key] = command

        # Save to disk
        await self._save_keymap()
        return {'keymap': self.keymap_config}

    async def _handle_status_request(self, web_request):
        """Return current numpad status"""
        return {
            'enabled': True,  # You might want to track this state
            'connected': True,  # You might want to track device connection
            'last_keypress': None  # You might want to track last key press
        }

    async def _save_keymap(self):
        """Save current keymap configuration to disk"""
        # Implementation for saving config
        pass

    async def close(self):
        """Clean up resources on exit"""
        logging.info("Closing Numpad Macros Plugin")


def load_component(config):
    return NumpadMacros(config)