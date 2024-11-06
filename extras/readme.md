# Numpad Listener Service for Moonraker

## Overview

The Numpad Listener Service is a Python-based service designed to capture keyboard events and forward them to Moonraker, the API server for Klipper 3D printer firmware. This service runs independently of Klipper and Moonraker, allowing for improved performance and simplified event handling.

## Features

- Captures all keyboard events
- Runs as a system service (systemd)
- Forwards event data to Moonraker via HTTP POST requests
- Logging with rotation to prevent excessive disk usage

## Requirements

- Raspberry Pi or similar Linux-based system
- Python 3.7 or higher
- Root access for installation and execution

## Installation

### Automatic Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/numpad-listener.git
   cd numpad-listener
