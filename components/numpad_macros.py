# Numpad Macros Component for Moonraker
#
# Copyright (C) 2024
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Dict, Any, Optional

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from ..common import WebRequest
    from .klippy_apis import KlippyAPI
    from .job_state import JobState
    from .klippy_connection import KlippyConnection

class NumpadMacros:
    def __init__(self, config: ConfigHelper) -> None:
        # Core initialization
        self.server = config.get_server()
        self.event_loop = self.server.get_event_loop()
        self.name = config.get_name()

        # Get configuration options with validation
        self.debug_log = config.getboolean('debug_log', False)
        self.z_adjust_increment = config.getfloat(
            'z_adjust_increment', 0.01, above=0., below=1.
        )
        self.speed_adjust_increment = config.getfloat(
            'speed_adjust_increment', 0.05, above=0., below=1.
        )
        self.min_speed_factor = config.getfloat(
            'min_speed_factor', 0.2, above=0., below=1.
        )
        self.max_speed_factor = config.getfloat(
            'max_speed_factor', 2.0, above=1.
        )

        # Component references
        self.kapis: KlippyAPI = self.server.lookup_component('klippy_apis')

        # State tracking with typing
        self.is_printing: bool = False
        self.is_probing: bool = False
        self.current_z: float = 0.0
        self._cached_speed_factor: float = 1.0

        # Register endpoints
        self.server.register_endpoint(
            "/server/numpad/event",
            ['POST'],
            self._handle_numpad_event
        )
        self.server.register_endpoint(
            "/server/numpad/status",
            ['GET'],
            self._handle_status_request
        )

        # Register notifications
        self.server.register_notification('numpad_macros:status_update')

        # Register event handlers
        self.server.register_event_handler(
            "server:klippy_ready", self._handle_ready
        )
        self.server.register_event_handler(
            "server:klippy_shutdown", self._handle_shutdown
        )
        self.server.register_event_handler(
            "server:klippy_disconnect", self._handle_disconnect
        )

        if self.debug_log:
            logging.debug(f"{self.name}: Component Initialized")

    async def _handle_ready(self) -> None:
        """Called when Klippy reports ready"""
        await self._fetch_initial_state()
        if self.debug_log:
            logging.debug("Numpad ready with initial state")

    async def _handle_shutdown(self) -> None:
        """Called when Klippy enters shutdown state"""
        self.is_printing = False
        self._notify_status_update()

    async def _handle_disconnect(self) -> None:
        """Called when Klippy disconnects"""
        self.is_printing = False
        self._notify_status_update()

    async def _fetch_initial_state(self) -> None:
        """Fetch initial state from Klippy"""
        try:
            status = await self.kapis.query_objects({
                'print_stats': None,
                'toolhead': None,
                'gcode_move': None
            })
            self.is_printing = status.get('print_stats', {}).get('state', '') == 'printing'
            position = status.get('toolhead', {}).get('position', [0, 0, 0, 0])
            self.current_z = position[2]
            self._cached_speed_factor = status.get('gcode_move', {}).get(
                'speed_factor', 1.0
            )
            self._notify_status_update()
        except Exception:
            msg = f"{self.name}: Error fetching initial state"
            logging.exception(msg)
            self.server.add_warning(msg)

    def _notify_status_update(self) -> None:
        """Notify clients of a status change"""
        self.server.send_event(
            "numpad_macros:status_update",
            self.get_status()
        )

    async def _handle_status_request(
        self, web_request: WebRequest
    ) -> Dict[str, Any]:
        """Handle status request endpoint"""
        return {'status': self.get_status()}

    async def _handle_numpad_event(
        self, web_request: WebRequest
    ) -> Dict[str, Any]:
        """Process incoming numpad events"""
        if not await self._check_klippy_ready():
            raise self.server.error("Klippy not ready", 503)

        try:
            event = web_request.get_args()
            if self.debug_log:
                logging.debug(f"{self.name}: Received event: {event}")

            key: str = event.get('key', '')
            event_type: str = event.get('event_type', '')

            if not key or not event_type:
                raise self.server.error(
                    "Missing required fields 'key' or 'event_type'", 400
                )

            if event_type == 'down':
                if key in ['up', 'down']:
                    await self._handle_special_key(f"key_{key}")
                else:
                    await self._execute_gcode(f"_{key.upper()}")
                self._notify_status_update()

            return {'status': "ok"}

        except Exception as e:
            msg = f"Error processing numpad event: {str(e)}"
            logging.exception(msg)
            raise self.server.error(msg, 500) from e

    async def _check_klippy_ready(self) -> bool:
        """Verify Klippy is ready to process commands"""
        klippy_conn: KlippyConnection = self.server.lookup_component('klippy_connection')
        return (
                klippy_conn.is_connected() and
                klippy_conn.is_ready()
        )

    async def _handle_special_key(self, key: str) -> None:
        """Handle special key events (up/down)"""
        try:
            # Update current state
            status = await self.kapis.query_objects({
                'print_stats': None,
                'toolhead': None,
                'gcode_move': None
            })
            self.is_printing = status.get('print_stats', {}).get('state', '') == 'printing'
            position = status.get('toolhead', {}).get('position', [0, 0, 0, 0])
            self.current_z = position[2]
            self._cached_speed_factor = status.get('gcode_move', {}).get(
                'speed_factor', self._cached_speed_factor
            )

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

        except Exception:
            msg = f"{self.name}: Error handling special key: {key}"
            logging.exception(msg)
            self.server.add_warning(msg)

    async def _execute_gcode(self, command: str) -> None:
        """Execute a GCode command with error handling"""
        try:
            await self.kapis.run_gcode(command)
        except Exception:
            msg = f"{self.name}: Error executing gcode {command}"
            logging.exception(msg)
            self.server.add_warning(msg)

    async def _adjust_z(self, adjustment: float) -> None:
        """Adjust Z offset with bounds checking"""
        try:
            cmd = f"SET_GCODE_OFFSET Z_ADJUST={adjustment} MOVE=1"
            await self.kapis.run_gcode(cmd)
            self.current_z += adjustment
        except Exception:
            msg = f"{self.name}: Error adjusting Z by {adjustment}"
            logging.exception(msg)
            self.server.add_warning(msg)

    async def _adjust_speed(self, adjustment: float) -> None:
        """Adjust speed factor with bounds checking"""
        try:
            new_factor = max(
                self.min_speed_factor,
                min(self._cached_speed_factor + adjustment, self.max_speed_factor)
            )
            cmd = f"SET_VELOCITY_FACTOR FACTOR={new_factor}"
            await self.kapis.run_gcode(cmd)
            self._cached_speed_factor = new_factor
        except Exception:
            msg = f"{self.name}: Error adjusting speed by {adjustment}"
            logging.exception(msg)
            self.server.add_warning(msg)

    def get_status(self) -> Dict[str, Any]:
        """Return component status"""
        return {
            'is_printing': self.is_printing,
            'current_z': round(self.current_z, 6),
            'speed_factor': round(self._cached_speed_factor, 2),
            'debug_enabled': self.debug_log,
            'config': {
                'z_adjust_increment': self.z_adjust_increment,
                'speed_adjust_increment': self.speed_adjust_increment,
                'min_speed_factor': self.min_speed_factor,
                'max_speed_factor': self.max_speed_factor
            }
        }

def load_component(config: ConfigHelper) -> NumpadMacros:
    return NumpadMacros(config)