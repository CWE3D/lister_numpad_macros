#!/bin/bash

# Installation script for Numpad Listener Service
# Must be run as root/sudo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
}

# Check if numpad_listener_service.py exists in current directory
if [ ! -f "numpad_listener_service.py" ]; then
    echo -e "${RED}Error: numpad_listener_service.py not found in current directory${NC}"
    exit 1
}

echo -e "${GREEN}Starting Numpad Listener Service Installation...${NC}"

# Create installation directory
INSTALL_DIR="/opt/numpad-listener"
echo -e "${YELLOW}Creating installation directory...${NC}"
mkdir -p $INSTALL_DIR

# Copy service file to installation directory
echo -e "${YELLOW}Copying service file...${NC}"
cp numpad_listener_service.py $INSTALL_DIR/
chmod +x $INSTALL_DIR/numpad_listener_service.py

# Create the systemd service file
echo -e "${YELLOW}Creating systemd service file...${NC}"
cat > /etc/systemd/system/numpad-listener.service << 'EOL'
[Unit]
Description=Numpad Listener Service for Moonraker
After=moonraker.service
StartLimitIntervalSec=5
StartLimitBurst=5

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /opt/numpad-listener/numpad_listener_service.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

# Install required packages
echo -e "${YELLOW}Installing required packages...${NC}"
apt-get update
apt-get install -y python3-pip

echo -e "${YELLOW}Installing Python dependencies...${NC}"
pip3 install keyboard requests

# Enable and start the service
echo -e "${YELLOW}Enabling and starting the service...${NC}"
systemctl daemon-reload
systemctl enable numpad-listener
systemctl start numpad-listener

# Check service status
if systemctl is-active --quiet numpad-listener; then
    echo -e "${GREEN}Numpad Listener Service has been successfully installed and started!${NC}"
    echo -e "${GREEN}Service is running as root user${NC}"
    echo -e "${GREEN}Installation completed successfully!${NC}"
    echo -e "\nYou can check the service status with: ${YELLOW}systemctl status numpad-listener${NC}"
    echo -e "View logs with: ${YELLOW}journalctl -u numpad-listener -f${NC}"
else
    echo -e "${RED}Service installation completed but service is not running.${NC}"
    echo -e "${RED}Please check the logs with: journalctl -u numpad-listener -f${NC}"
    exit 1
fi
