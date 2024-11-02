# Numpad Macros Plugin Documentation

## Overview
The Numpad Macros plugin enables you to use a USB numpad as a control interface for your Lister 3D printer. This plugin provides customizable key mappings to execute common printer commands, making printer control more convenient and efficient.

## Installation

### Prerequisites
- Klipper installed and configured
- Moonraker installed and configured
- A USB numpad
- Python 3.7 or higher

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
# Optional: Device path (default shown below)
device_path: /dev/input/by-id/usb-SIGMACHIP_USB_Keyboard-event-kbd

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
```

## Finding Your Numpad's Device Path

1. List available input devices:
```bash
ls -l /dev/input/by-id/
```

2. Connect your numpad and run the command again to identify the new device
3. Update the `device_path` in your `printer.cfg` if different from default

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
1. Send a test command:
```bash
NUMPAD_TEST
```
This should show connection status to your numpad device.

2. Press keys on the numpad:
- Each keypress should generate a message in the console
- You should see: "Numpad key pressed: X" (where X is the key number)

### 3. Test Command Execution
1. Press key 1 (should execute HOME command)
2. Check console output for command execution
3. Verify printer response to the command

## Troubleshooting

### 1. Device Not Found
If you see "Failed to initialize numpad device":
1. Check USB connection
2. Verify device path:
```bash
ls -l /dev/input/by-id/
```
3. Update `device_path` in `printer.cfg`
4. Check user permissions:
```bash
groups | grep input
```

### 2. Keys Not Responding
1. Check Klipper logs:
```bash
tail -f /tmp/klippy.log
```
2. Verify numpad is detected:
```bash
NUMPAD_TEST
```
3. Restart Klipper:
```bash
sudo service klipper restart
```

### 3. Commands Not Executing
1. Check command mapping in `printer.cfg`
2. Verify command exists in Klipper
3. Check Klipper logs for errors

## Advanced Usage

### Custom Key Mappings
You can map any valid Klipper G-code command to any key. Example:
```ini
[numpad_macros]
key_1: G28                  # Home all axes
key_2: G1 Z10              # Move Z up 10mm
key_3: M104 S200           # Set hotend temperature
```

### Development and Debugging
Enable debug logging in `printer.cfg`:
```ini
[numpad_macros]
device_paths: /dev/input/by-id/device1, /dev/input/by-id/device2
debug_log: True
```

## Updating the Plugin
The plugin updates automatically through Moonraker's update manager. You can also manually update:
```bash
cd ~/lister_numpad_macros
git pull
./install.sh
```

## Safety Features
- Key commands won't execute during critical operations
- Service restarts are handled safely
- Configuration backups are created during updates

## Support and Contributing
- Report issues on GitHub
- Submit pull requests for improvements
- Check documentation for updates

## Default Key Mappings Reference

| Key    | Default Command           | Description                    |
|--------|--------------------------|--------------------------------|
| 1      | HOME                    | Home all axes                  |
| 2      | PROBE_BED_MESH         | Generate bed mesh              |
| 3      | Z_TILT_ADJUST          | Adjust Z tilt                  |
| 4      | BED_PROBE_MANUAL_ADJUST| Manual bed adjustment          |
| 5      | TURN_ON_LIGHT          | Turn on printer light          |
| 6      | TURN_OFF_LIGHT         | Turn off printer light         |
| 7      | DISABLE_X_Y_STEPPERS   | Disable X/Y steppers           |
| 8      | DISABLE_EXTRUDER_STEPPER| Disable extruder              |
| 9      | COLD_CHANGE_FILAMENT   | Change filament routine        |
| 0      | TOGGLE_FILAMENT_SENSOR | Toggle filament sensor         |
| .      | PROBE_NOZZLE_DISTANCE  | Probe calibration              |
| ENTER  | RESUME                 | Resume print                   |