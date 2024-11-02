#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Define paths
SCRIPT_DIR="$HOME/lister_numpad_macros"
KLIPPER_DIR="$HOME/klipper"
KLIPPY_ENV="$HOME/klippy-env"
PLUGIN_NAME="numpad_macros.py"

echo -e "${GREEN}Starting installation of Numpad Macros plugin...${NC}"

# Check if directories exist
if [ ! -d "$SCRIPT_DIR" ]; then
    echo -e "${RED}Error: Directory $SCRIPT_DIR does not exist${NC}"
    exit 1
fi

if [ ! -d "$KLIPPER_DIR" ]; then
    echo -e "${RED}Error: Klipper directory $KLIPPER_DIR does not exist${NC}"
    exit 1
fi

if [ ! -d "$KLIPPY_ENV" ]; then
    echo -e "${RED}Error: Klippy virtual environment $KLIPPY_ENV does not exist${NC}"
    exit 1
fi

# Install system dependencies
echo -e "${YELLOW}Installing system dependencies...${NC}"
sudo apt-get update
if ! sudo apt-get install -y python3-evdev; then
    echo -e "${RED}Error: Failed to install system dependencies${NC}"
    exit 1
fi

# Add user to input group
echo -e "${YELLOW}Adding user to input group...${NC}"
if ! sudo usermod -a -G input $USER; then
    echo -e "${RED}Error: Failed to add user to input group${NC}"
    exit 1
fi

# Install Python dependencies in klippy-env
echo -e "${YELLOW}Installing Python dependencies in klippy-env...${NC}"
source $KLIPPY_ENV/bin/activate
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    if ! pip install -r "$SCRIPT_DIR/requirements.txt"; then
        echo -e "${RED}Error: Failed to install Python dependencies${NC}"
        deactivate
        exit 1
    fi
else
    echo -e "${RED}Warning: requirements.txt not found, installing evdev directly${NC}"
    if ! pip install evdev; then
        echo -e "${RED}Error: Failed to install evdev${NC}"
        deactivate
        exit 1
    fi
fi
deactivate

# Create symbolic link for the plugin
echo -e "${YELLOW}Creating symbolic link for plugin...${NC}"
EXTRAS_DIR="$SCRIPT_DIR/extras"
KLIPPER_EXTRAS_DIR="$KLIPPER_DIR/klippy/extras"

if [ ! -d "$KLIPPER_EXTRAS_DIR" ]; then
    echo -e "${RED}Error: Klipper extras directory does not exist${NC}"
    exit 1
fi

if [ -f "$EXTRAS_DIR/$PLUGIN_NAME" ]; then
    # Remove existing symlink if it exists
    if [ -L "$KLIPPER_EXTRAS_DIR/$PLUGIN_NAME" ]; then
        rm "$KLIPPER_EXTRAS_DIR/$PLUGIN_NAME"
    fi

    # Create new symlink
    if ! ln -s "$EXTRAS_DIR/$PLUGIN_NAME" "$KLIPPER_EXTRAS_DIR/$PLUGIN_NAME"; then
        echo -e "${RED}Error: Failed to create symbolic link${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: Plugin file not found in $EXTRAS_DIR${NC}"
    exit 1
fi

# Restart Klipper service
echo -e "${YELLOW}Restarting Klipper service...${NC}"
if ! sudo service klipper restart; then
    echo -e "${RED}Error: Failed to restart Klipper service${NC}"
    exit 1
fi

echo -e "${GREEN}Installation completed successfully!${NC}"
echo -e "${YELLOW}Note: You may need to log out and back in for the input group changes to take effect${NC}"
echo -e "${YELLOW}You can check the installation by running:${NC}"
echo -e "  ${GREEN}1. ls -l $KLIPPER_EXTRAS_DIR/$PLUGIN_NAME${NC}"
echo -e "  ${GREEN}2. grep input /etc/group${NC}"
echo -e "  ${GREEN}3. systemctl status klipper${NC}"