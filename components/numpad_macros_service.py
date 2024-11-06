import logging


class NumpadMacrosService:
    def __init__(self, config):
        self.logger = logging.getLogger("moonraker.NumpadMacrosService")
        self.logger.info("Initializing NumpadMacrosService")

        self.server = config.get_server()
        self.printer = self.server.lookup_component('printer')

        # Register endpoint to receive events from the listener service
        self.server.register_endpoint(
            "/server/numpad_event", ['POST'],
            self._handle_numpad_event
        )
        self.logger.info("Registered /server/numpad_event endpoint")

        # Configuration
        self.z_adjust_increment = config.getfloat('z_adjust_increment', 0.01)
        self.speed_adjust_increment = config.getfloat('speed_adjust_increment', 0.05)
        self.min_speed_factor = config.getfloat('min_speed_factor', 0.2)
        self.max_speed_factor = config.getfloat('max_speed_factor', 2.0)
        self.debug_log = config.getboolean('debug_log', False)
        self.logger.info(f"Configuration loaded: z_adjust={self.z_adjust_increment}, "
                         f"speed_adjust={self.speed_adjust_increment}, "
                         f"min_speed={self.min_speed_factor}, max_speed={self.max_speed_factor}")

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
        self.logger.info(f"Key mapping configured: {self.key_mapping}")

        # Special handling for up/down keys
        self.special_keys = {'key_up', 'key_down'}

        self.logger.info("NumpadMacrosService initialization complete")

    def _log_debug(self, message):
        if self.debug_log:
            self.logger.debug(f"NumpadMacros: {message}")

    async def _handle_numpad_event(self, web_request):
        event = web_request.get_json_body()
        key = f"key_{event.get('key')}"
        self.logger.info(f"Received key event: {key}")

        if key in self.key_mapping:
            if key in self.special_keys:
                await self._handle_special_key(key)
            else:
                await self._execute_macro(self.key_mapping[key])
        else:
            self.logger.warning(f"Unrecognized key event: {key}")
        return {'status': "ok"}

    async def _handle_special_key(self, key):
        await self._update_printer_state()
        self.logger.info(f"Handling special key: {key}")
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
        self.logger.info(f"Printer state updated: printing={self.is_printing}, "
                         f"probing={self.is_probing}, current_z={self.current_z}")

    async def _handle_up(self):
        self.logger.info("Handling up key")
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
        self.logger.info("Handling down key")
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
        self.logger.info(f"Executing macro: {macro_name}")
        await self.printer.run_method("gcode.script", script=macro_name)

    # ... (other methods remain the same, but you can add logging as needed)


def load_component(config):
    return NumpadMacrosService(config)


# Add this line at the end of the file
logging.getLogger("moonraker.NumpadMacrosService").info("NumpadMacrosService module loaded")
