# Numpad Macros Plugin Documentation

## Overview
The Numpad Macros plugin enables you to use USB input devices (numpads, knobs, etc.) as control interfaces for your Lister 3D printer. This plugin provides customizable key mappings to execute common printer commands, making printer control more convenient and efficient.

## Installation

### Prerequisites
- Klipper installed and configured
- Moonraker installed and configured
- USB input devices (numpad, volume knob, etc.)
- Python 3.7 or higher
- python3-evdev package installed

### Automatic Installation
1. Clone the repository:
```bash
cd ~
git clone https://github.com/CWE3D/lister_numpad_macros.git
```

2. Run the installation script:
```bash
cd ~/lister_numpad_macros
chmod +x install.sh
./install.sh
```

### Configuration

#### 1. Moonraker Configuration
The installation script automatically adds the following to your `moonraker.conf`:
```ini
[update_manager lister_numpad_macros]
type: git_repo
path: ~/lister_numpad_macros
origin: https://github.com/CWE3D/lister_numpad_macros.git
is_system_service: False
primary_branch: main
managed_services: klipper moonraker
install_script: install.sh
```

#### 2. Printer Configuration
Add the following to your `printer.cfg`:
```ini
[numpad_macros]
# Multiple device support (comma-separated)
device_paths: /dev/input/by-id/device1, /dev/input/by-id/device2

# Enable debug logging for troubleshooting
debug_log: True

# Optional: Key mappings
key_1: HOME                    # G28
key_2: PROBE_BED_MESH         # Generate bed mesh
key_3: Z_TILT_ADJUST          # Adjust Z tilt
key_4: BED_PROBE_MANUAL_ADJUST # Manual bed adjustment
key_5: TURN_ON_LIGHT          # Turn on printer light
key_6: TURN_OFF_LIGHT         # Turn off printer light
key_7: DISABLE_X_Y_STEPPERS   # Disable X/Y steppers
key_8: DISABLE_EXTRUDER_STEPPER # Disable extruder
key_9: COLD_CHANGE_FILAMENT   # Change filament
key_0: TOGGLE_FILAMENT_SENSOR # Toggle filament sensor
key_DOT: PROBE_NOZZLE_DISTANCE # Probe calibration
key_ENTER: RESUME             # Resume print

# Volume knob mappings
key_UP: SET_GCODE_OFFSET Z_ADJUST=0.025 MOVE=1    # Raise nozzle
key_DOWN: SET_GCODE_OFFSET Z_ADJUST=-0.025 MOVE=1  # Lower nozzle
```

## Finding Your Device Paths

1. List available input devices:
```bash
ls -l /dev/input/by-id/
```

2. To see detailed device information and supported events:
```bash
evtest
```

3. Update the `device_paths` in your `printer.cfg` with your device paths

## Testing the Installation

### 1. Verify Components
```bash
# Check Klipper plugin installation
ls -l ~/klipper/klippy/extras/numpad_macros.py

# Check Moonraker component installation
ls -l ~/moonraker/moonraker/components/numpad_macros.py

# Check input group membership
groups | grep input
```

### 2. Test Basic Functionality
1. Enable debug logging and send a test command:
```bash
NUMPAD_TEST
```
This will show:
- Connected devices
- Current key mappings
- Debug status

2. Press keys or use input devices:
- Each input should generate a message in the console
- Debug logging will show detailed event information
- You should see command execution confirmations

## Advanced Features

### Device Support
The plugin now supports multiple input devices:
- Standard numpads
- Volume knobs (sends UP/DOWN events)
- Other USB input devices that send key events

### Debug Logging
Enable detailed logging to troubleshoot issues:
```ini
[numpad_macros]
debug_log: True
```
This will show:
- Device connection details
- Key event information
- Command execution details
- Error messages

### Custom Key Mappings
Map any key event to any Klipper command:
```ini
[numpad_macros]
# Z-offset adjustment examples
key_UP: SET_GCODE_OFFSET Z_ADJUST=0.1 MOVE=1     # Larger increment
key_DOWN: SET_GCODE_OFFSET Z_ADJUST=-0.1 MOVE=1  # Larger decrement

# Custom command examples
key_1: G28                  # Home all axes
key_2: G1 Z10              # Move Z up 10mm
key_3: M104 S200           # Set hotend temperature
```

## Default Key Mappings Reference

| Key    | Default Command           | Description                    |
|--------|--------------------------|--------------------------------|
| 1-9, 0 | Various printer commands | Standard numpad keys           |
| .      | PROBE_NOZZLE_DISTANCE   | Probe calibration              |
| ENTER  | RESUME                  | Resume print                   |
| UP     | Z offset +0.025         | Raise nozzle (volume knob)     |
| DOWN   | Z offset -0.025         | Lower nozzle (volume knob)     |

## Troubleshooting

### Common Issues

1. **Device Not Found**
   - Check USB connections
   - Verify device paths with `ls -l /dev/input/by-id/`
   - Check device events with `evtest`
   - Verify user permissions with `groups | grep input`

2. **Keys Not Responding**
   - Enable debug logging
   - Check Klipper logs: `tail -f /tmp/klippy.log`
   - Verify device detection: `NUMPAD_TEST`
   - Try reconnecting the device

3. **Commands Not Executing**
   - Check command mapping in `printer.cfg`
   - Verify command exists in Klipper
   - Check debug logs for errors

## Support and Contributing
- Report issues on GitHub
- Submit pull requests for improvements
- Check documentation for updates