from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Dict, Any, Optional, Set as SetType

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from ..common import WebRequest
    from .klippy_apis import KlippyAPI
    from .job_state import JobState

class NumpadMacros:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        self.event_loop = self.server.get_event_loop()
        self.name = config.get_name()

        # Initialize component logger
        self.debug_log = config.getboolean('debug_log', False)
        self.logger = logging.getLogger(f"moonraker.{self.name}")
        if self.debug_log:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        # Get keys that don't require confirmation
        no_confirm_default = ['key_up', 'key_down', 'key_enter', 'key_enter_alt']
        no_confirm_str = config.get('no_confirmation_keys', ','.join(no_confirm_default))
        self.no_confirm_keys: SetType[str] = set(key.strip() for key in no_confirm_str.split(','))

        if self.debug_log:
            self.logger.debug(f"Keys without confirmation requirement: {self.no_confirm_keys}")

        # Get command mappings from config
        self.command_mapping: Dict[str, str] = {}
        self.query_mapping: Dict[str, str] = {}
        self._load_command_mapping(config)

        # Get configuration values
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

        # Get command mappings from config
        self.command_mapping: Dict[str, str] = {}
        self.query_mapping: Dict[str, str] = {}
        self._load_command_mapping(config)

        # State tracking
        self.pending_key: Optional[str] = None
        self.is_probing: bool = False
        self._is_printing: bool = False

        # Register endpoints
        self.server.register_endpoint(
            "/server/numpad/event", ['POST'], self._handle_numpad_event
        )
        self.server.register_endpoint(
            "/server/numpad/status", ['GET'], self._handle_status_request
        )

        # Register notifications
        self.server.register_notification('numpad_macros:status_update')
        self.server.register_notification('numpad_macros:command_queued')
        self.server.register_notification('numpad_macros:command_executed')

        # Register event handlers
        self.server.register_event_handler(
            "server:klippy_ready", self._handle_ready
        )
        self.server.register_event_handler(
            "server:klippy_shutdown", self._handle_shutdown
        )

        if self.debug_log:
            self.logger.debug(f"{self.name}: Component Initialized")

    def _load_command_mapping(self, config: ConfigHelper) -> None:
        """Load command mappings from config"""
        key_options = [
            'key_1', 'key_2', 'key_3', 'key_4', 'key_5',
            'key_6', 'key_7', 'key_8', 'key_9', 'key_0',
            'key_dot', 'key_enter', 'key_up', 'key_down',
            'key_1_alt', 'key_2_alt', 'key_3_alt', 'key_4_alt',
            'key_5_alt', 'key_6_alt', 'key_7_alt', 'key_8_alt',
            'key_9_alt', 'key_0_alt', 'key_dot_alt', 'key_enter_alt'
        ]
        for key in key_options:
            cmd = config.get(key, f"RESPOND MSG=\"{key} not assigned\"")
            self.command_mapping[key] = cmd
            # Create query version of command
            if not cmd.startswith("_"):
                self.query_mapping[key] = f"_QUERY_{cmd}"
            else:
                self.query_mapping[key] = cmd

    async def _handle_ready(self) -> None:
        """Handle Klippy ready event"""
        await self._check_klippy_state()

    async def _handle_shutdown(self) -> None:
        """Handle Klippy shutdown event"""
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset all state variables"""
        self.pending_key = None
        self._is_printing = False
        self.is_probing = False
        self._notify_status_update()

    async def _check_klippy_state(self) -> None:
        """Update internal state based on Klippy status"""
        kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
        try:
            result = await kapis.query_objects({
                'print_stats': None,
                'probe': None
            })
            self._is_printing = result.get('print_stats', {}).get('state', '') == 'printing'
            self.is_probing = result.get('probe', {}).get('last_query', False)
            self._notify_status_update()
        except Exception:
            msg = f"{self.name}: Error fetching Klippy state"
            self.logger.exception(msg)
            self._reset_state()
            raise self.server.error(msg, 503)

    async def _handle_numpad_event(
            self, web_request: WebRequest
    ) -> Dict[str, Any]:
        """Handle incoming numpad events"""
        klippy_conn = self.server.lookup_component('klippy_connection')
        if not klippy_conn.is_connected():
            raise self.server.error("Klippy not connected", 503)

        try:
            event = web_request.get_args()
            if self.debug_log:
                self.logger.debug(f"Received event: {event}")

            key: str = event.get('key', '')
            event_type: str = event.get('event_type', '')
            value: Optional[float] = event.get('value', None)

            if not key or not event_type or event_type not in ['down', 'up']:
                raise self.server.error(
                    f"Invalid event data: {event}", 400
                )

            # Only process key down events
            if event_type != 'down':
                return {'status': 'ignored'}

            if key in ['up', 'down'] and value is not None:
                # Handle direct adjustment values from event service
                await self._handle_adjustment(key, value)
            elif key == 'enter':
                await self._handle_enter_key()
            else:
                await self._handle_command_key(key)

            return {'status': 'ok'}

        except Exception as e:
            msg = f"Error processing numpad event: {str(e)}"
            self.logger.exception(msg)
            raise self.server.error(msg, 500)

    async def _handle_adjustment(self, key: str, value: float) -> None:
        """Handle adjustment with direct value"""
        try:
            # Update Klippy state
            await self._check_klippy_state()
            kapis: KlippyAPI = self.server.lookup_component('klippy_apis')

            if self.is_probing:
                # Handle probe adjustment
                cmd = f"TESTZ Z={value}"
                await kapis.run_gcode(cmd)
            elif self._is_printing:
                # Get Z height to determine mode
                toolhead = await self._get_toolhead_position()
                if toolhead['z'] < 1.0:
                    # Z offset adjustment
                    cmd = f"SET_GCODE_OFFSET Z_ADJUST={value} MOVE=1"
                else:
                    # Speed adjustment
                    cmd = f"SET_VELOCITY_LIMIT VELOCITY_FACTOR={value}"
                await kapis.run_gcode(cmd)

        except Exception as e:
            msg = f"Error handling adjustment: {str(e)}"
            self.logger.exception(msg)
            raise self.server.error(msg, 500)

    async def _handle_command_key(self, key: str) -> None:
        """Handle regular command keys"""
        if key not in self.command_mapping:
            if self.debug_log:
                self.logger.debug(f"No command mapped for key: {key}")
            return

        if key in self.no_confirm_keys:
            # Direct execution without confirmation for specified keys
            try:
                cmd = self.command_mapping[key]
                await self._execute_gcode(cmd)
                self.server.send_event(
                    "numpad_macros:command_executed",
                    {'command': cmd}
                )
            except Exception as e:
                self.logger.exception(f"Error executing command for key {key}: {str(e)}")
            return

        # Store pending command for keys that need confirmation
        self.pending_key = key

        # Execute query version if available
        query_cmd = self.query_mapping.get(key)
        if query_cmd:
            await self._execute_gcode(query_cmd)

        self._notify_status_update()
        self.server.send_event(
            "numpad_macros:command_queued",
            {'command': self.command_mapping[key]}
        )

    async def _handle_enter_key(self) -> None:
        """Handle enter key press"""
        if not self.pending_key:
            return

        try:
            cmd = self.command_mapping[self.pending_key]
            await self._execute_gcode(cmd)
            self.server.send_event(
                "numpad_macros:command_executed",
                {'command': cmd}
            )
        finally:
            self.pending_key = None
            self._notify_status_update()

    async def _get_toolhead_position(self) -> Dict[str, float]:
        """Get current toolhead position"""
        kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
        result = await kapis.query_objects({'toolhead': None})
        pos = result.get('toolhead', {}).get('position', [0., 0., 0., 0.])
        return {
            'x': pos[0], 'y': pos[1], 'z': pos[2], 'e': pos[3]
        }

    async def _execute_gcode(self, command: str) -> None:
        """Execute a gcode command"""
        kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
        await kapis.run_gcode(command)

    async def _handle_status_request(
            self, web_request: WebRequest
    ) -> Dict[str, Any]:
        """Handle status request endpoint"""
        return {'status': self.get_status()}

    def get_status(self) -> Dict[str, Any]:
        """Return component status"""
        return {
            'command_mapping': self.command_mapping,
            'query_mapping': self.query_mapping,
            'pending_key': self.pending_key,
            'is_printing': self._is_printing,
            'is_probing': self.is_probing,
            'no_confirm_keys': list(self.no_confirm_keys),
            'config': {
                'debug_log': self.debug_log,
                'z_adjust_increment': self.z_adjust_increment,
                'speed_adjust_increment': self.speed_adjust_increment,
                'min_speed_factor': self.min_speed_factor,
                'max_speed_factor': self.max_speed_factor
            }
        }

    def _notify_status_update(self) -> None:
        """Notify clients of status changes"""
        self.server.send_event(
            "numpad_macros:status_update",
            self.get_status()
        )


def load_component(config: ConfigHelper) -> NumpadMacros:
    return NumpadMacros(config)