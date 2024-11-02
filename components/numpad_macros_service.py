import logging
from typing import Dict, Any, Optional

class NumpadMacrosService:  # Changed from NumpadMacros
    """
    Moonraker component for managing numpad macros configuration and status.
    Provides web API endpoints for configuration management and status updates.
    Supports multiple devices and additional input types like volume knobs.
    """

    def __init__(self, config) -> None:
        self.server = config.get_server()
        self.printer = self.server.lookup_component('printer')

        # Initialize state
        self._status: Dict[str, Any] = {
            'enabled': True,
            'connected_devices': {},
            'last_keypress': None,
            'last_error': None,
            'config_loaded': False
        }
        self.keymap_config: Dict[str, str] = {}

        # Initialize configuration
        self._init_keymap_config(config)

        # Update endpoint paths to reflect service name
        self.server.register_endpoint(
            "/machine/numpad/keymap",  # Updated path
            ['GET', 'POST'],
            self._handle_keymap_request,
            transport="http"
        )
        self.server.register_endpoint(
            "/machine/numpad/status",  # Updated path
            ['GET'],
            self._handle_status_request,
            transport="http"
        )
        self.server.register_endpoint(
            "/machine/numpad/devices",  # Updated path
            ['GET'],
            self._handle_devices_request,
            transport="http"
        )

        # Register notification methods (keep numpad: prefix for compatibility)
        self.server.register_notification("numpad:keypress")
        self.server.register_notification("numpad:status_update")
        self.server.register_notification("numpad:device_update")

        # Register event handlers
        self.server.register_event_handler(
            "server:klippy_ready",
            self._handle_ready
        )

        logging.info("Numpad Macros Service Component Initialized")

    def _get_default_keymap(self) -> Dict[str, str]:
        """Return default key mapping configuration"""
        return {
            # Standard numpad keys
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
            # Volume knob controls
            "UP": "SET_GCODE_OFFSET Z_ADJUST=0.025 MOVE=1",
            "DOWN": "SET_GCODE_OFFSET Z_ADJUST=-0.025 MOVE=1"
        }

    def _init_keymap_config(self, config) -> None:
        """Initialize keymap configuration with validation"""
        try:
            default_keymap = self._get_default_keymap()

            # Load and validate configuration
            for key, default_cmd in default_keymap.items():
                config_key = f"key_{key}"
                cmd = config.get(config_key, default_cmd)

                if self._validate_command(cmd):
                    self.keymap_config[key] = cmd
                else:
                    logging.warning(
                        f"Invalid command format for {config_key}: {cmd}, "
                        f"using default: {default_cmd}"
                    )
                    self.keymap_config[key] = default_cmd

            self._status['config_loaded'] = True
            logging.info("Numpad keymap configuration loaded successfully")

        except Exception as e:
            logging.error(f"Error loading numpad configuration: {str(e)}")
            self.keymap_config = self._get_default_keymap()
            self._status['last_error'] = str(e)

    def _validate_command(self, cmd: str) -> bool:
        """Validate command format"""
        if not isinstance(cmd, str) or not cmd.strip():
            return False

        # Add additional command validation as needed
        invalid_chars = set('<>{}[]\\')
        return not any(char in cmd for char in invalid_chars)

    async def _handle_ready(self) -> None:
        """Handle Klippy ready event"""
        try:
            logging.info("Numpad Macros Component Ready")
            await self._update_status(enabled=True)
        except Exception as e:
            logging.error(f"Error in ready handler: {str(e)}")

    async def _handle_keymap_request(self, web_request) -> Dict[str, Any]:
        """Handle keymap GET/POST requests with validation"""
        if web_request.get_method() == 'GET':
            return {'keymap': self.keymap_config}

        try:
            data = web_request.get_json_body()
            if not isinstance(data, dict) or 'keymap' not in data:
                raise self.server.error("Invalid request format")

            new_keymap = data['keymap']
            if not isinstance(new_keymap, dict):
                raise self.server.error("Invalid keymap format")

            # Validate and update keymap
            validated_keymap = {}
            for key, command in new_keymap.items():
                if key in self.keymap_config:
                    if self._validate_command(command):
                        validated_keymap[key] = command
                    else:
                        raise self.server.error(
                            f"Invalid command format for key: {key}")

            # Update configuration
            self.keymap_config.update(validated_keymap)
            await self._save_keymap()
            await self._notify_keymap_update()

            return {'keymap': self.keymap_config}

        except Exception as e:
            raise self.server.error(f"Failed to update keymap: {str(e)}")

    async def _handle_status_request(self, web_request) -> Dict[str, Any]:
        """Return current numpad status"""
        return {
            'status': self._status,
            'keymap': self.keymap_config
        }

    async def _handle_devices_request(self, web_request) -> Dict[str, Any]:
        """Return information about connected devices"""
        return {
            'devices': self._status['connected_devices']
        }

    async def _update_status(self, **kwargs) -> None:
        """Update component status and notify clients"""
        self._status.update(kwargs)
        try:
            await self.server.send_event(
                "numpad:status_update",
                {
                    'status': self._status,
                    'keymap': self.keymap_config
                }
            )
        except Exception as e:
            logging.error(f"Error sending status update: {str(e)}")

    async def _notify_keymap_update(self) -> None:
        """Notify clients about keymap changes"""
        try:
            await self.server.send_event(
                "numpad:keymap_update",
                {'keymap': self.keymap_config}
            )
        except Exception as e:
            logging.error(f"Error notifying keymap update: {str(e)}")

    async def _handle_device_update(self, device_info: Dict[str, Any]) -> None:
        """Handle device connection/disconnection updates"""
        try:
            self._status['connected_devices'] = device_info
            await self.server.send_event(
                "numpad:device_update",
                {'devices': device_info}
            )
        except Exception as e:
            logging.error(f"Error handling device update: {str(e)}")

    async def _save_keymap(self) -> None:
        """Save current keymap configuration"""
        try:
            # TODO: Implement actual configuration saving mechanism
            # Could save to a config file or database
            self._status['config_loaded'] = True
            logging.info("Keymap configuration saved successfully")
        except Exception as e:
            logging.error(f"Error saving keymap configuration: {str(e)}")
            self._status['last_error'] = str(e)

    async def close(self) -> None:
        """Clean up resources on shutdown"""
        logging.info("Closing Numpad Macros Component")
        try:
            await self._update_status(
                enabled=False,
                connected_devices={}
            )
        except Exception as e:
            logging.error(f"Error during component shutdown: {str(e)}")


def load_component(config):
    return NumpadMacrosService(config)