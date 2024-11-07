from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Dict, Any, Optional, Set as SetType

if TYPE_CHECKING:
    from moonraker.common import WebRequest
    from moonraker.components.klippy_apis import KlippyAPI
    from moonraker.confighelper import ConfigHelper

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

        self.pending_key: Optional[str] = None
        self.pending_command: Optional[str] = None
        if self.debug_log:
            self.logger.debug("Initial state - pending_key: None, pending_command: None")

        # Get configuration values
        self.z_adjust_increment = config.getfloat(
            'z_adjust_increment', 0.01, above=0., below=1.
        )

        # Get speed settings from config with defaults
        default_speed_settings = {
            "increment": 10,
            "max": 300,
            "min": 20
        }
        self.speed_settings = config.getdict('speed_settings', default=default_speed_settings)

        if self.debug_log:
            self.logger.debug(f"Loaded speed settings: {self.speed_settings}")

        # Add configuration for probe adjustments
        self.probe_min_step = config.getfloat(
            'probe_min_step', 0.01, above=0., below=1.
        )
        self.probe_coarse_multiplier = config.getfloat(
            'probe_coarse_multiplier', 0.5, above=0., below=1.
        )

        # Define keys that don't require confirmation (direct execution)
        self.no_confirm_keys: SetType[str] = {'key_up', 'key_down'}
        # Define confirmation keys first
        self.confirmation_keys: SetType[str] = {'key_enter', 'key_enter_alt'}

        # Define keys that don't require confirmation (direct execution)
        # Include both direct execution keys and confirmation keys
        self.no_confirm_keys: SetType[str] = {
            'key_up',
            'key_down'
        }.union(self.confirmation_keys)  # Add confirmation keys to no_confirm set

        if self.debug_log:
            self.logger.debug(f"No confirmation required for keys: {self.no_confirm_keys}")
            self.logger.debug(f"Confirmation keys: {self.confirmation_keys}")

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
            # Store the command exactly as configured
            self.command_mapping[key] = config.get(key, f"RESPOND MSG=\"{key} not assigned\"")
            # Create QUERY version by adding prefix
            self.query_mapping[key] = f"_QUERY{self.command_mapping[key]}"

            if self.debug_log:
                self.logger.debug(
                    f"Loaded mapping for {key} -> Command: {self.command_mapping[key]}, "
                    f"Query: {self.query_mapping[key]}"
                )

    async def _handle_command_key(self, key: str) -> None:
        """Handle regular command keys"""
        if self.debug_log:
            self.logger.debug(f"State before command key - pending_key: {self.pending_key}, "
                              f"pending_command: {self.pending_command}")

        # Only process if key is not a no-confirm key
        if key not in self.no_confirm_keys:
            # Store as pending command (replaces any existing pending command)
            if self.pending_key and self.pending_key != key:
                await self._execute_gcode(
                    f'RESPOND MSG="Numpad macros: Replacing pending command {self.command_mapping[key]}"'
                )

            # Store the pending command
            self.pending_key = key
            self.pending_command = self.command_mapping[key]

            # Always run the QUERY version first
            query_cmd = self.query_mapping[key]
            await self._execute_gcode(f'RESPOND MSG="Numpad macros: Running query {query_cmd}"')
            await self._execute_gcode(query_cmd)

            await self._execute_gcode(
                f'RESPOND MSG="Numpad macros: Command {self.pending_command} is ready. Press ENTER to execute"'
            )

            self._notify_status_update()
            await self.server.send_event(
                "numpad_macros:command_queued",
                {'command': self.pending_command}
            )
        else:
            # Direct execution for no-confirm keys
            await self._execute_gcode(self.command_mapping[key])

        if self.debug_log:
            self.logger.debug(f"State after command key - pending_key: {self.pending_key}, "
                              f"pending_command: {self.pending_command}")

    async def _handle_numpad_event(self, web_request: WebRequest) -> Dict[str, Any]:
        try:
            event = web_request.get_args()
            key: str = event.get('key', '')
            event_type: str = event.get('event_type', '')

            if self.debug_log:
                self.logger.debug(f"Current state - pending_key: {self.pending_key}, "
                                  f"pending_command: {self.pending_command}")
                self.logger.debug(f"Received event: {event}")

            # Only process key down events
            if event_type != 'down':
                if self.debug_log:
                    self.logger.debug("Ignoring non-down event")
                return {'status': 'ignored'}

            # Process confirmation keys first
            if key in self.confirmation_keys:
                if self.debug_log:
                    self.logger.debug("Processing confirmation key")
                await self._handle_confirmation()
                return {'status': 'confirmed'}

            # Then process no-confirm keys (up/down)
            if key in self.no_confirm_keys:
                if self.debug_log:
                    self.logger.debug("Processing no-confirm key")
                # For up/down keys, use a default adjustment value
                if key in ['key_up', 'key_down']:
                    adjustment = self.z_adjust_increment if key == 'key_up' else -self.z_adjust_increment
                    if self.debug_log:
                        self.logger.debug(f"Using adjustment value: {adjustment}")
                    await self._handle_adjustment(key, adjustment)
                    return {'status': 'executed'}

            # Finally process regular command keys
            if self.debug_log:
                self.logger.debug("Processing regular command key")
            await self._handle_command_key(key)
            return {'status': 'queued'}

        except Exception as e:
            self.logger.exception("Error processing numpad event")
            raise

    async def _handle_confirmation(self) -> None:
        """Handle confirmation key press"""
        if self.debug_log:
            self.logger.debug(f"Handling confirmation with state - pending_key: {self.pending_key}, "
                            f"pending_command: {self.pending_command}")

        if not self.pending_key or not self.pending_command:
            if self.debug_log:
                self.logger.debug("No pending command to confirm")
            await self._execute_gcode('RESPOND MSG="Numpad macros: No command pending for confirmation"')
            return

        try:
            # Store command locally before clearing state
            cmd = self.pending_command
            if self.debug_log:
                self.logger.debug(f"Executing confirmed command: {cmd}")

            # Execute the command
            await self._execute_gcode(f'RESPOND MSG="Numpad macros: Executing confirmed command {cmd}"')
            await self._execute_gcode(cmd)

            # Notify of execution
            await self.server.send_event(
                "numpad_macros:command_executed",
                {'command': cmd}
            )

        except Exception as e:
            self.logger.exception(f"Error executing command: {str(e)}")
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: Error executing command: {str(e)}"')
        finally:
            # Clear pending command state
            self.pending_key = None
            self.pending_command = None
            if self.debug_log:
                self.logger.debug("Cleared pending command state")
            self._notify_status_update()

    async def _handle_adjustment(self, key: str, value: float) -> None:
        """Handle immediate adjustment commands (up/down keys)"""
        try:
            if self.debug_log:
                self.logger.debug(f"Starting adjustment handling - Key: {key}, Value: {value}")

            await self._check_klippy_state()
            if self.debug_log:
                self.logger.debug(
                    f"Klippy state checked - is_probing: {self.is_probing}, is_printing: {self._is_printing}")

            kapis: KlippyAPI = self.server.lookup_component('klippy_apis')

            if self.is_probing:
                # Get current Z position
                toolhead = await self._get_toolhead_position()
                current_z = toolhead['z']

                if self.debug_log:
                    self.logger.debug(f"Probe adjustment - Current Z: {current_z}")

                # Determine step size based on height
                if current_z < 0.1:
                    cmd = f"TESTZ Z={'+' if key == 'key_up' else '-'}"
                    if self.debug_log:
                        self.logger.debug(f"Using fine adjustment mode: {cmd}")
                else:
                    step_size = max(current_z * self.probe_coarse_multiplier, self.probe_min_step)
                    cmd = f"TESTZ Z={'+' if key == 'key_up' else '-'}{step_size:.3f}"
                    if self.debug_log:
                        self.logger.debug(f"Using coarse adjustment with step size: {step_size:.3f}")

                await self._execute_gcode(f'RESPOND MSG="Numpad macros: {cmd}"')
                await kapis.run_gcode(cmd)

            elif self._is_printing:
                # Get Z height to determine mode
                toolhead = await self._get_toolhead_position()
                current_z = toolhead['z']

                if self.debug_log:
                    self.logger.debug(f"Print adjustment - Current Z: {current_z}")

                if current_z < 1.0:
                    # Z offset adjustment
                    if key == 'key_up':
                        cmd = f"SET_GCODE_OFFSET Z_ADJUST={self.z_adjust_increment} MOVE=1"
                    else:
                        cmd = f"SET_GCODE_OFFSET Z_ADJUST=-{self.z_adjust_increment} MOVE=1"

                    if self.debug_log:
                        self.logger.debug(f"First layer Z adjustment: {cmd}")
                        # Then in the adjustment handler:
                else:
                    # Speed adjustment using M220
                    increment = self.speed_settings["increment"]
                    max_speed = self.speed_settings["max"]
                    min_speed = self.speed_settings["min"]

                    if key == 'key_up':
                        # Increase speed
                        if value + increment > max_speed:
                            cmd = f"M220 S{max_speed}"
                        else:
                            cmd = f"M220 S+{increment}"
                    else:
                        # Decrease speed
                        if value - increment < min_speed:
                            cmd = f"M220 S{min_speed}"
                        else:
                            cmd = f"M220 S-{increment}"

                    if self.debug_log:
                        self.logger.debug(
                            f"Speed adjustment: {cmd} (current: {value}%, "
                            f"limits: {min_speed}%-{max_speed}%, step: {increment}%)"
                        )

                # Execute the command
                if self.debug_log:
                    self.logger.debug(f"Executing adjustment command: {cmd}")

                await self._execute_gcode(f'RESPOND MSG="Numpad macros: {cmd}"')
                await kapis.run_gcode(cmd)

        except Exception as e:
            msg = f"Error handling adjustment: {str(e)}"
            self.logger.exception(msg)
            await self._execute_gcode(f'RESPOND TYPE=error MSG="Numpad macros: {msg}"')
            raise

    async def _check_klippy_state(self) -> None:
        """Update internal state based on Klippy status"""
        kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
        try:
            result = await kapis.query_objects({
                'print_stats': None,
                'gcode_macro CHECK_PROBE_STATUS': None  # Query our macro
            })

            if self.debug_log:
                self.logger.debug(f"Klippy state query result: {result}")
                self.logger.debug(f"CHECK_PROBE_STATUS result: {result.get('gcode_macro CHECK_PROBE_STATUS', {})}")

            probe_status = result.get('gcode_macro CHECK_PROBE_STATUS', {})
            previous_probing = self.is_probing
            self.is_probing = probe_status.get('monitor_active', False)

            if self.debug_log:
                self.logger.debug(f"Probe status change: {previous_probing} -> {self.is_probing}")

            self._is_printing = result.get('print_stats', {}).get('state', '') == 'printing'

            # Get probe status from the macro's variables
            probe_status = result.get('gcode_macro CHECK_PROBE_STATUS', {})
            self.is_probing = probe_status.get('monitor_active', False)

            if self.debug_log:
                await self._execute_gcode(
                    f'RESPOND MSG="Numpad macros: State update - '
                    f'Printing: {self._is_printing}, '
                    f'Probing: {self.is_probing}, '
                    f'Probe Status: {probe_status}"'
                )

            self._notify_status_update()

        except Exception as e:
            msg = f"{self.name}: Error fetching Klippy state: {str(e)}"
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