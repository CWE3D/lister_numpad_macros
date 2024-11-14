from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING, Dict, Any, Optional, Set as SetType
import re

import asyncio


def strip_comments(code):
    # This regex removes everything after a '#' unless it's inside a string
    return code

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

        # Define default no-confirm and confirmation keys
        default_no_confirm = "key_up,key_down"
        default_confirm = "key_enter,key_enter_alt"

        # Get configuration for no-confirm and confirmation keys
        no_confirm_str = config.get('no_confirmation_keys', default_no_confirm)
        confirm_str = config.get('confirmation_keys', default_confirm)

        # Convert comma-separated strings to sets
        self.no_confirm_keys: SetType[str] = set(k.strip() for k in no_confirm_str.split(','))
        self.confirmation_keys: SetType[str] = set(k.strip() for k in confirm_str.split(','))

        if self.debug_log:
            self.logger.debug(f"No confirmation required for keys: {self.no_confirm_keys}")
            self.logger.debug(f"Confirmation keys: {self.confirmation_keys}")

        # Get command mappings from config
        self.command_mapping: Dict[str,str] = {}
        self.initial_query_command_mapping: Dict[str, str] = {}
        self._load_command_mapping(config)

        # State tracking
        self.pending_key: Optional[str] = None
        self.pending_command: Optional[str] = None
        self.is_probing: bool = False
        self._is_printing: bool = False
        self.z_offset_save_delay = config.getfloat(
            'z_offset_save_delay', 3.0, above=0.
        )
        self._pending_z_offset_save = False
        self._last_z_adjust_time = 0.0
        self._accumulated_z_adjust = 0.0

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
            # Check if the option exists in config
            if config.has_option(key):
                # Get the command value, strip whitespace
                cmd = config.get(key)
                if cmd:  # If command is not empty after stripping
                    self.command_mapping[key] = cmd
                    # Create QUERY version by adding prefix
                    self.initial_query_command_mapping[key] = f"_QUERY{cmd}" if cmd.startswith('_') else f"_QUERY_{cmd}"

                    if self.debug_log:
                        self.logger.debug(
                            f"Loaded mapping for {key} -> Command: {self.command_mapping[key]}, "
                            f"Query: {self.initial_query_command_mapping[key]}"
                        )
            else:
                # Option not in config - add to both mappings
                self.command_mapping[key] = f'_NO_ASSIGNED_MACRO KEY={key}'
                self.initial_query_command_mapping[key] = f'_NO_ASSIGNED_MACRO KEY={key}'

    async def _handle_numpad_event(self, web_request: WebRequest) -> Dict[str, Any]:
        try:
            event = web_request.get_args()
            key: str = event.get('key', '')
            event_type: str = event.get('event_type', '')

            if self.debug_log:
                self.logger.debug(f"Received event - Key: {key}, Type: {event_type}")
                self.logger.debug(f"Current state - pending_key: {self.pending_key}, "
                                  f"pending_command: {self.pending_command}")

            # THE MOST 1ST ORDER IMPORTANT KEY
            # First, check if it's a confirmation key
            if key in self.confirmation_keys:
                if self.debug_log:
                    self.logger.debug("Processing confirmation key")
                await self._handle_confirmation()
                return {'status': 'confirmed'}

            # THESE COMMAND RUN DIRECTLY AND 2ND ORDER
            # Then check if it's a no-confirmation key
            if key in self.no_confirm_keys:
                if self.debug_log:
                    self.logger.debug(f"Processing no-confirmation key: {key}")

                # Handle adjustment keys specially
                # Check if we are dealing with up and down, they are special 3RD ORDER
                if key in ['key_up', 'key_down']:
                    await self._handle_knob_adjustment(key)
                else:
                    # Now we can run the query command directly because
                    # we are dealing with real command as is no confirmation key.
                    # Execute command directly without query prefix
                    command = self.command_mapping[key]
                    if self.debug_log:
                        self.logger.debug(f"Executing no-confirmation command: {command}")

                    await self._execute_gcode(f'RESPOND MSG="Numpad macros: Executing {command}"')
                    await self._execute_gcode(command)

                    # Maintain status updates and notifications
                    await self.server.send_event(
                        "numpad_macros:command_executed",
                        {'command': command}
                    )
                    self._notify_status_update()

                return {'status': 'executed'}

            # Finally, handle regular command keys that need confirmation
            if self.debug_log:
                self.logger.debug("Processing regular command key")

            await self._handle_command_key(key)
            return {'status': 'queued'}

        except Exception as e:
            self.logger.exception("Error processing numpad event")
            raise

    async def _handle_command_key(self, key: str) -> None:
        """Handle regular command keys that require confirmation"""
        if self.debug_log:
            self.logger.debug(f"Processing command key: {key}")

        # Store as pending command (replaces any existing pending command)
        if self.pending_key and self.pending_key != key:
            await self._execute_gcode(
                f'RESPOND MSG="Numpad macros: Replacing pending command '
                f'{self.command_mapping[self.pending_key]} with {self.command_mapping[key]}"'
            )

        # Store the pending command
        self.pending_key = key
        self.pending_command = self.command_mapping[key]

        # Run the QUERY version for confirmation-required commands
        query_cmd = self.initial_query_command_mapping[key]
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

    # The updated _handle_adjustment method:
    async def _handle_knob_adjustment(self, key: str) -> None:
        """Handle immediate adjustment commands (up/down keys)"""
        try:
            if self.debug_log:
                self.logger.debug(f"Starting adjustment handling - Key: {key}")

            await self._check_klippy_state()
            if self.debug_log:
                self.logger.debug(
                    f"Klippy state checked - is_probing: {self.is_probing}, is_printing: {self._is_printing}")

            # Initialize cmd as None
            cmd = None

            if self.is_probing:
                # Get current Z position
                toolhead = await self._get_toolhead_position()
                current_z = toolhead['z']

                if self.debug_log:
                    self.logger.debug(f"Probe adjustment - Current Z: {current_z}")

                # Determine step size based on height
                # PLEASE DO NOT SIMPLIFY, TESTZ Z+/- string is intentional
                if current_z < 0.1:
                    cmd = f"TESTZ Z={'+' if key == 'key_up' else '-'}"
                    if self.debug_log:
                        self.logger.debug(f"Using fine adjustment mode: {cmd}")
                else:
                    step_size = max(current_z * self.probe_coarse_multiplier, self.probe_min_step)

                    cmd = f"TESTZ Z={'+' if key == 'key_up' else '-'}{step_size:.3f}"
                    if self.debug_log:
                        self.logger.debug(f"Using coarse adjustment with step size: {step_size:.3f}")

            elif self._is_printing:
                # Get Z height to determine mode
                toolhead = await self._get_toolhead_position()
                current_z = toolhead['z']

                if self.debug_log:
                    self.logger.debug(f"Print adjustment - Current Z: {current_z}")

                if current_z <= 1.0:
                    # Z offset adjustment
                    ## NOTE LOGIC CANNOT BE SIMPLIFIED
                    ## This is intentionally two separate strings as one cannot pass a negative
                    ## value to Z_ADJUST={-5} (the negative is a string), string is "Z_ADJUST=-"
                    if key == 'key_up':
                        cmd = f"SET_GCODE_OFFSET Z_ADJUST={self.z_adjust_increment} MOVE=1"
                        adjustment = self.z_adjust_increment
                    else:
                        cmd = f"SET_GCODE_OFFSET Z_ADJUST=-{self.z_adjust_increment} MOVE=1"
                        adjustment = -self.z_adjust_increment

                    # Track the adjustment
                    self._accumulated_z_adjust += adjustment
                    self._last_z_adjust_time = time.time()
                    self._pending_z_offset_save = True

                    # Schedule the save after delay
                    self.event_loop.create_task(self._delayed_save_z_offset())

                    if self.debug_log:
                        self.logger.debug(f"First layer Z adjustment: {cmd}")
                else:
                    # Speed adjustment using M220
                    # Get current speed factor
                    kapis: KlippyAPI = self.server.lookup_component('klippy_apis')
                    result = await kapis.query_objects({'gcode_move': None})
                    current_speed = result.get('gcode_move', {}).get('speed_factor', 1.0) * 100

                    increment = self.speed_settings["increment"]
                    max_speed = self.speed_settings["max"]
                    min_speed = self.speed_settings["min"]

                    # Calculate new speed value
                    if key == 'key_up':
                        new_speed = min(current_speed + increment, max_speed)
                    else:
                        new_speed = max(current_speed - increment, min_speed)

                    # Set the absolute speed value
                    cmd = f"M220 S{int(new_speed)}"

                    if self.debug_log:
                        self.logger.debug(
                            f"Speed adjustment: {cmd} (previous: {current_speed}%, new: {new_speed}%, "
                            f"limits: {min_speed}%-{max_speed}%, step: {increment}%)"
                        )
            else:
                '''Standby mode: WE can now handle the volume knobs'''
                if key == 'key_up':
                    await self._execute_gcode('RESPOND MSG="Volume up"')
                    await self._execute_gcode('VOLUME_UP')
                else:
                    await self._execute_gcode('RESPOND MSG="Volume down"')
                    await self._execute_gcode('VOLUME_DOWN')

                if self.debug_log:
                    self.logger.debug("No adjustment command was generated")

            # Execute the command only if one was set
            if cmd is not None:
                if self.debug_log:
                    self.logger.debug(f"Executing adjustment command: {cmd}")
                await self._execute_gcode(f'RESPOND MSG="Numpad macros: {cmd}"')
                await self._execute_gcode(cmd)
            else:
                if self.debug_log:
                    self.logger.debug("No adjustment command was generated")

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
                self.logger.debug(f'Klippy state query result: {result}')
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
            'query_mapping': self.initial_query_command_mapping,
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

    async def _delayed_save_z_offset(self) -> None:
        """Save the accumulated Z offset after a delay"""
        try:
            await asyncio.sleep(self.z_offset_save_delay)

            # Check if this is the most recent adjustment
            if time.time() - self._last_z_adjust_time >= self.z_offset_save_delay:
                if self._pending_z_offset_save:
                    # Simply save the accumulated adjustment
                    await self._execute_gcode(
                        f'SAVE_VARIABLE VARIABLE=real_z_offset VALUE={self._accumulated_z_adjust}'
                    )

                    if self.debug_log:
                        self.logger.debug(
                            f"Saved Z offset adjustment: {self._accumulated_z_adjust}"
                        )

                    # Reset tracking variables
                    self._accumulated_z_adjust = 0.0
                    self._pending_z_offset_save = False

        except Exception as e:
            self.logger.exception("Error saving Z offset")
            await self._execute_gcode(
                f'RESPOND TYPE=error MSG="Error saving Z offset: {str(e)}"'
            )

    def _reset_state(self) -> None:
        """Reset all state variables"""
        self.pending_key = None
        self.pending_command = None
        self._is_printing = False
        self.is_probing = False
        self._accumulated_z_adjust = 0.0
        self._pending_z_offset_save = False
        self._last_z_adjust_time = 0.0
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