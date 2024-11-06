# Numpad Macros Component for Moonraker
#
# Copyright (C) 2024
from __future__ import annotations
import logging

class NumpadMacros:
    def __init__(self, config):
        # Core initialization
        self.server = config.get_server()
        self.name = config.get_name()
        # Get root logger
        self.logger = logging.getLogger(self.name)

        # Get configuration options
        self.debug_log = config.getboolean('debug_log', False)
        self.z_adjust_increment = config.getfloat('z_adjust_increment', 0.01)
        self.speed_adjust_increment = config.getfloat('speed_adjust_increment', 0.05)
        self.min_speed_factor = config.getfloat('min_speed_factor', 0.2)
        self.max_speed_factor = config.getfloat('max_speed_factor', 2.0)

        # State tracking
        self.printer = None
        self.klippy_apis = None
        self.is_printing = False
        self.is_probing = False
        self.current_z = 0.0

        # Register endpoint for numpad events
        self.server.register_endpoint(
            "/server/numpad_event",
            ['POST'],
            self._handle_numpad_event
        )

        # Register notification for status updates
        self.server.register_notification('numpad_macros:status_update')

        if self.debug_log:
            self.logger.debug("NumpadMacros component initialized")

    async def component_init(self):
        # Get printer APIs - these are only available after initialization
        self.printer = self.server.lookup_component('printer')
        self.klippy_apis = self.server.lookup_component('klippy_apis')
        self.logger.info("NumpadMacros component initialization complete")

    async def _handle_numpad_event(self, web_request):
        event = web_request.get_json_body()
        if self.debug_log:
            self.logger.debug(f"Received numpad event: {event}")

        try:
            key = event.get('key', '')
            event_type = event.get('event_type', '')

            if event_type == 'down':  # Only process key down events
                if key in ['up', 'down']:
                    await self._handle_special_key(f"key_{key}")
                else:
                    # Execute the corresponding macro
                    await self._execute_gcode(f"_{key.upper()}")

            return {'status': "ok"}

        except Exception as e:
            self.logger.exception(f"Error processing numpad event: {str(e)}")
            return {'status': "error", 'message': str(e)}

    async def _handle_special_key(self, key):
        # Get printer status
        try:
            status = await self.klippy_apis.query_objects(
                {'print_stats': None, 'toolhead': None}
            )

            self.is_printing = status.get('print_stats', {}).get('state', '') == 'printing'
            self.current_z = status.get('toolhead', {}).get('position', [0, 0, 0, 0])[2]

            if key == 'key_up':
                if self.current_z < 1.0 and self.is_printing:
                    await self._adjust_z(self.z_adjust_increment)
                else:
                    await self._adjust_speed(self.speed_adjust_increment)
            elif key == 'key_down':
                if self.current_z < 1.0 and self.is_printing:
                    await self._adjust_z(-self.z_adjust_increment)
                else:
                    await self._adjust_speed(-self.speed_adjust_increment)

        except Exception as e:
            self.logger.exception(f"Error handling special key: {str(e)}")

    async def _execute_gcode(self, command):
        try:
            await self.klippy_apis.run_gcode(command)
        except Exception as e:
            self.logger.exception(f"Error executing gcode {command}: {str(e)}")

    async def _adjust_z(self, adjustment):
        try:
            cmd = f"SET_GCODE_OFFSET Z_ADJUST={adjustment} MOVE=1"
            await self.klippy_apis.run_gcode(cmd)
        except Exception as e:
            self.logger.exception(f"Error adjusting Z: {str(e)}")

    async def _adjust_speed(self, adjustment):
        try:
            current = await self.klippy_apis.query_objects({'gcode_move': None})
            current_factor = current.get('gcode_move', {}).get('speed_factor', 1.0)
            new_factor = max(self.min_speed_factor,
                             min(current_factor + adjustment, self.max_speed_factor))

            cmd = f"SET_VELOCITY_FACTOR FACTOR={new_factor}"
            await self.klippy_apis.run_gcode(cmd)
        except Exception as e:
            self.logger.exception(f"Error adjusting speed: {str(e)}")

    def get_status(self, eventtime=None):
        return {
            'is_printing': self.is_printing,
            'current_z': self.current_z,
            'debug_enabled': self.debug_log
        }

def load_component(config):
    return NumpadMacros(config)