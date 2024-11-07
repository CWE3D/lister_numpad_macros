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

        # Define keys that don't require confirmation (direct execution)
        self.no_confirm_keys: SetType[str] = {'key_up', 'key_down'}

        # Define confirmation keys
        self.confirmation_keys: SetType[str] = {'key_enter', 'key_enter_alt'}

        # Get command mappings from config
        self.command_mapping: Dict[str, str] = {}
        self.query_mapping: Dict[str, str] = {}
        self._load_command_mapping(config)

        # State tracking
        self.pending_key: Optional[str] = None
        self.pending_command: Optional[str] = None
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
            # Create query version of command if it starts with uppercase letter
            # (indicating it's a regular command and not a special _QUERY_ command)
            if not cmd.startswith('_'):
                self.query_mapping[key] = f"_QUERY_{cmd}"
            else:
                self.query_mapping[key] = cmd

    async def _handle_numpad_event(
        self, web_request: WebRequest
    ) -> Dict[str, Any]:
        """Handle incoming numpad events"""
        klippy_conn = self.server.lookup_component('klippy_connection')
        if not klippy_conn.is_connected():
            await self._execute_gcode('RESPOND TYPE=error MSG="Numpad macros: Klippy not connected"')
            raise self.server.error("Klippy not connected", 503)

        try:
            event = web_request.get_args()
            if self.debug_log:
                self.logger.debug(f"Received event: {event}")
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: Received {event.get("key", "unknown")} key event"')

            key: str = event.get('key', '')
            event_type: str = event.get('event_type', '')
            value: Optional[float] = event.get('value', None)

            if not key or not event_type or event_type not in ['down', 'up']:
                await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: Invalid event data - {event}"')
                raise self.server.error(f"Invalid event data: {event}", 400)

            # Only process key down events
            if event_type != 'down':
                return {'status': 'ignored'}

            # Process the key event based on its type
            if key in self.no_confirm_keys:
                # Direct execution for up/down keys
                if value is not None:
                    await self._execute_gcode(f'RESPOND MSG="Numpad macros: Direct execution of {key} with value {value}"')
                    await self._handle_adjustment(key, value)
            elif key in self.confirmation_keys:
                # Handle confirmation key press
                if self.pending_command:
                    await self._execute_gcode(f'RESPOND MSG="Numpad macros: Confirming command {self.pending_command}"')
                else:
                    await self._execute_gcode('RESPOND MSG="Numpad macros: No command pending for confirmation"')
                await self._handle_confirmation()
            else:
                # Handle regular command key
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: Processing command key {key}"')
                await self._handle_command_key(key)

            return {'status': 'ok'}

        except Exception as e:
            msg = f"Error processing numpad event: {str(e)}"
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: {msg}"')
            self.logger.exception(msg)
            raise self.server.error(msg, 500)

    async def _handle_command_key(self, key: str) -> None:
        """Handle regular command keys"""
        if key not in self.command_mapping:
            if self.debug_log:
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: No command mapped for key {key}"')
            return

        # Store as pending command (replaces any existing pending command)
        if self.pending_key and self.pending_key != key:
            await self._execute_gcode(
                f'RESPOND MSG="Numpad macros: Replacing pending command {self.pending_command} with new key {key}"'
            )

        self.pending_key = key
        self.pending_command = self.command_mapping[key]

        # Execute query version if available
        query_cmd = self.query_mapping.get(key)
        if query_cmd:
            try:
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: Executing query command {query_cmd}"')
                await self._execute_gcode(query_cmd)
            except Exception as e:
                await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: Error executing query command: {str(e)}"')
                self.logger.exception(f"Error executing query command: {str(e)}")

        await self._execute_gcode(
            f'RESPOND MSG="Numpad macros: Command {self.pending_command} is pending. Press ENTER to execute"'
        )
        self._notify_status_update()
        self.server.send_event(
            "numpad_macros:command_queued",
            {'command': self.pending_command}
        )

    async def _handle_confirmation(self) -> None:
        """Handle confirmation key press"""
        if not self.pending_key or not self.pending_command:
            await self._execute_gcode('RESPOND MSG="Numpad macros: No command pending for confirmation"')
            return

        try:
            # Execute the pending command
            await self._execute_gcode(f'RESPOND MSG="Numpad macros: Executing confirmed command {self.pending_command}"')
            await self._execute_gcode(self.pending_command)
            self.server.send_event(
                "numpad_macros:command_executed",
                {'command': self.pending_command}
            )
        except Exception as e:
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: Error executing command: {str(e)}"')
            self.logger.exception(f"Error executing command: {str(e)}")
        finally:
            # Clear pending command state
            await self._execute_gcode('RESPOND MSG="Numpad macros: Command execution complete, clearing pending state"')
            self.pending_key = None
            self.pending_command = None
            self._notify_status_update()

    async def _handle_adjustment(self, key: str, value: float) -> None:
        """Handle immediate adjustment commands (up/down keys)"""
        try:
            # Update Klippy state
            await self._check_klippy_state()
            kapis: KlippyAPI = self.server.lookup_component('klippy_apis')

            if self.is_probing:
                # Handle probe adjustment
                cmd = f"TESTZ Z={value}"
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: Probe adjustment Z={value}"')
                await kapis.run_gcode(cmd)
            elif self._is_printing:
                # Get Z height to determine mode
                toolhead = await self._get_toolhead_position()
                if toolhead['z'] < 1.0:
                    # Z offset adjustment
                    cmd = f"SET_GCODE_OFFSET Z_ADJUST={value} MOVE=1"
                    await self._execute_gcode(f'RESPOND MSG="Numpad macros: Z offset adjustment {value}"')
                else:
                    # Speed adjustment
                    cmd = f"SET_VELOCITY_LIMIT VELOCITY_FACTOR={value}"
                    await self._execute_gcode(f'RESPOND MSG="Numpad macros: Speed adjustment factor={value}"')
                await kapis.run_gcode(cmd)

        except Exception as e:
            msg = f"Error handling adjustment: {str(e)}"
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: {msg}"')
            self.logger.exception(msg)
            raise self.server.error(msg, 500)

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
            if self.debug_log:
                await self._execute_gcode(
                    f'RESPOND MSG="Numpad macros: State update - Printing: {self._is_printing}, Probing: {self.is_probing}"'
                )
            self._notify_status_update()
        except Exception:
            msg = f"{self.name}: Error fetching Klippy state"
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: {msg}"')
            self.logger.exception(msg)
            self._reset_state()
            raise self.server.error(msg, 503)

    def get_status(self) -> Dict[str, Any]:
        """Return component status"""
        return {
            'command_mapping': self.command_mapping,
            'query_mapping': self.query_mapping,
            'pending_key': self.pending_key,
            'pending_command': self.pending_command,
            'is_printing': self._is_printing,
            'is_probing': self.is_probing,
            'no_confirm_keys': list(self.no_confirm_keys),
            'confirmation_keys': list(self.confirmation_keys)
        }

    def _notify_status_update(self) -> None:
        """Notify clients of status changes"""
        self.server.send_event(
            "numpad_macros:status_update",
            self.get_status()
        )

    async def _handle_ready(self) -> None:
        """Handle Klippy ready event"""
        await self._check_klippy_state()

    async def _handle_shutdown(self) -> None:
        """Handle Klippy shutdown event"""
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset all state variables"""
        self.pending_key = None
        self.pending_command = None  # This was missing
        self._is_printing = False
        self.is_probing = False
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

def load_component(config: ConfigHelper) -> NumpadMacros:
    return NumpadMacros(config)