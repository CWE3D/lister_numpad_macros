import evdev
from evdev import InputDevice, categorize, ecodes
import logging
import sys
from select import select
import time

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    filename='evdev_test.log'
)

# Also print to console
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

def list_devices():
    """List all input devices"""
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    logging.info("Available input devices:")
    for device in devices:
        logging.info(f"  {device.path}: {device.name} (phys = {device.phys})")
    return devices

def monitor_device(device):
    """Monitor a single input device"""
    logging.info(f"Monitoring device: {device.name}")
    logging.info("Press keys to see events (Ctrl+C to exit)")

    while True:
        r, w, x = select([device], [], [], 0.1)
        if r:
            for event in device.read():
                if event.type == evdev.ecodes.EV_KEY:
                    key_event = categorize(event)
                    if key_event.keystate == key_event.key_down:
                        logging.info(f'Key pressed - Code: {key_event.scancode}, Key: {key_event.keycode}')

def main():
    try:
        devices = list_devices()
        if not devices:
            logging.error("No input devices found!")
            return

        # Monitor all keyboard-like devices
        keyboard_devices = [d for d in devices if d.name.lower().find('keyboard') != -1]
        if not keyboard_devices:
            logging.warning("No keyboard devices found! Showing all devices instead.")
            keyboard_devices = devices

        for device in keyboard_devices:
            try:
                device.grab()
                logging.info(f"Successfully grabbed device: {device.name}")
                monitor_device(device)
            except IOError as e:
                logging.error(f"Could not grab device {device.name}: {e}")
            finally:
                device.ungrab()

    except Exception as e:
        logging.error(f"Error: {e}")
    except KeyboardInterrupt:
        logging.info("Shutting down...")

if __name__ == "__main__":
    main()