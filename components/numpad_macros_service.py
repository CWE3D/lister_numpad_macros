import logging

class NumpadMacros:
    def __init__(self, config):
        self.server = config.get_server()
        self.printer = self.server.lookup_component('printer')

        # Register endpoint to receive events from the listener service
        self.server.register_endpoint(
            "/server/numpad_event", ['POST'],
            self._handle_numpad_event
        )

        # Configuration
        self.z_adjust_increment = config.getfloat('z_adjust_increment', 0.01)
        self.speed_adjust_increment = config.getfloat('speed_adjust_increment', 0.05)
        self.min_speed_factor = config.getfloat('min_speed_factor', 0.2)
        self.max_speed_factor = config.getfloat('max_speed_factor', 2.0)
        self.debug_log = config.getboolean('debug_log', False)

        # State tracking
        self.is_printing = False
        self.is_probing = False
        self.current_z = 0

        # User-configurable key mapping
        self.key_mapping = {
            'key_1': config.get('key_1', '_HOME_ALL'),
            'key_2': config.get('key_2', '_SAFE_PARK_OFF'),
            'key_3': config.get('key_3', '_CANCEL_PRINT'),
            'key_4': config.get('key_4', '_PRE_HEAT_BED'),
            'key_5': config.get('key_5', '_PRE_HEAT_NOZZLE'),
            'key_6': config.get('key_6', '_BED_PROBE_MANUAL_ADJUST'),
            'key_7': config.get('key_7', '_DISABLE_X_Y_STEPPERS'),
            'key_8': config.get('key_8', '_CALIBRATE_NOZZLE_OFFSET_PROBE'),
            'key_9': config.get('key_9', '_REPEAT_LAST_PRINT'),
            'key_0': config.get('key_0', '_TOGGLE_PAUSE_RESUME'),
            'key_dot': config.get('key_dot', '_EMERGENCY_STOP'),
            'key_up': config.get('key_up', '_KNOB_UP'),
            'key_down': config.get('key_down', '_KNOB_DOWN'),
        }

        # Special handling for up/down keys
        self.special_keys = {'key_up', 'key_down'}

    def _log_debug(self, message):
        if self.debug_log:
            logging.debug(f"NumpadMacros: {message}")

    async def _handle_numpad_event(self, web_request):
        event = web_request.get_json_body()
        key = f"key_{event.get('key')}"
        self._log_debug(f"Received key event: {key}")

        if key in self.key_mapping:
            if key in self.special_keys:
                await self._handle_special_key(key)
            else:
                await self._execute_macro(self.key_mapping[key])
        return {'status': "ok"}

    async def _handle_special_key(self, key):
        await self._update_printer_state()
        if key == 'key_up':
            await self._handle_up()
        elif key == 'key_down':
            await self._handle_down()

    async def _update_printer_state(self):
        result = await self.printer.run_method("info")
        self.is_printing = result['state'] == 'printing'
        toolhead = self.printer.lookup_component('toolhead')
        self.current_z = toolhead.get_position()[2]
        self.is_probing = await self.printer.run_method("gcode.check_probe_status")

    async def _handle_up(self):
        if self.is_probing:
            await self._probe_up()
        elif self.is_printing:
            if self.current_z < 1.0:
                await self._z_adjust_up()
            else:
                await self._speed_adjust_up()
        else:
            await self._execute_macro(self.key_mapping['key_up'])

    async def _handle_down(self):
        if self.is_probing:
            await self._probe_down()
        elif self.is_printing:
            if self.current_z < 1.0:
                await self._z_adjust_down()
            else:
                await self._speed_adjust_down()
        else:
            await self._execute_macro(self.key_mapping['key_down'])

    async def _execute_macro(self, macro_name):
        self._log_debug(f"Executing macro: {macro_name}")
        await self.printer.run_method("gcode.script", script=macro_name)

    async def _probe_up(self):
        if self.current_z < 0.1:
            await self._execute_macro("TESTZ Z=+")
        else:
            step_size = max(self.current_z / 2, 0.01)
            await self._execute_macro(f"TESTZ Z=+{step_size}")

    async def _probe_down(self):
        if self.current_z < 0.1:
            await self._execute_macro("TESTZ Z=-")
        else:
            step_size = max(self.current_z / 2, 0.01)
            await self._execute_macro(f"TESTZ Z=-{step_size}")

    async def _z_adjust_up(self):
        await self._execute_macro(f"SET_GCODE_OFFSET Z_ADJUST={self.z_adjust_increment} MOVE=1")

    async def _z_adjust_down(self):
        await self._execute_macro(f"SET_GCODE_OFFSET Z_ADJUST=-{self.z_adjust_increment} MOVE=1")

    async def _speed_adjust_up(self):
        current_factor = await self.printer.run_method("gcode_move.get_status", ["speed_factor"])
        new_factor = min(current_factor + self.speed_adjust_increment, self.max_speed_factor)
        await self._execute_macro(f"SET_VELOCITY_FACTOR FACTOR={new_factor}")

    async def _speed_adjust_down(self):
        current_factor = await self.printer.run_method("gcode_move.get_status", ["speed_factor"])
        new_factor = max(current_factor - self.speed_adjust_increment, self.min_speed_factor)
        await self._execute_macro(f"SET_VELOCITY_FACTOR FACTOR={new_factor}")


def load_component(config):
    return NumpadMacros(config)
