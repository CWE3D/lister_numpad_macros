#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Define paths
SCRIPT_DIR="/home/pi/lister_numpad_macros"
KLIPPER_DIR="/home/pi/klipper"
MOONRAKER_DIR="/home/pi/moonraker"
KLIPPY_ENV="/home/pi/klippy-env"
LOG_DIR="/home/pi/printer_data/logs"
INSTALL_LOG="$LOG_DIR/numpad_macros_install.log"
MOONRAKER_CONF="/home/pi/printer_data/config/moonraker.conf"

# Update manager configuration block
read -r -d '' UPDATE_MANAGER_CONFIG << 'EOL'

[update_manager numpad_macros_service]
type: git_repo
path: ~/numpad_macros_service
origin: https://github.com/CWE3D/numpad_macros_service.git
is_system_service: False
primary_branch: main
managed_services: klipper moonraker
install_script: install.sh
EOL

# Function to log messages
log_message() {
    echo -e "${GREEN}$(date): $1${NC}" | tee -a "$INSTALL_LOG"
}

log_error() {
    echo -e "${RED}$(date): $1${NC}" | tee -a "$INSTALL_LOG"
}

log_warning() {
    echo -e "${YELLOW}$(date): $1${NC}" | tee -a "$INSTALL_LOG"
}

# Function to backup moonraker.conf
backup_moonraker_conf() {
    local backup_file="${MOONRAKER_CONF}.$(date +%Y%m%d_%H%M%S).backup"
    if cp "$MOONRAKER_CONF" "$backup_file"; then
        log_message "Created backup of moonraker.conf at $backup_file"
        return 0
    else
        log_error "Failed to create backup of moonraker.conf"
        return 1
    fi
}

# Function to check if update_manager section exists
section_exists() {
    if grep -q "^\[update_manager lister_numpad_macros\]" "$MOONRAKER_CONF"; then
        return 0
    else
        return 1
    fi
}

# Function to update moonraker.conf
update_moonraker_conf() {
    log_message "Checking moonraker.conf configuration..."

    # Check if moonraker.conf exists
    if [ ! -f "$MOONRAKER_CONF" ]; then
        log_error "moonraker.conf not found at $MOONRAKER_CONF"
        return 1
    fi

    # Create backup before making changes
    backup_moonraker_conf || return 1

    # Check and add update_manager section if needed
    if ! section_exists; then
        log_message "Adding [update_manager lister_numpad_macros] configuration..."
        echo "$UPDATE_MANAGER_CONFIG" >> "$MOONRAKER_CONF"
        log_message "moonraker.conf updated successfully"
    else
        log_warning "[update_manager lister_numpad_macros] section already exists in moonraker.conf"
    fi
}

# Check if required directories exist
check_directories() {
    local missing_dirs=0

    if [ ! -d "$SCRIPT_DIR" ]; then
        log_error "Error: Directory $SCRIPT_DIR does not exist"
        missing_dirs=1
    fi

    if [ ! -d "$KLIPPER_DIR" ]; then
        log_error "Error: Klipper directory $KLIPPER_DIR does not exist"
        missing_dirs=1
    fi

    if [ ! -d "$MOONRAKER_DIR" ]; then
        log_error "Error: Moonraker directory $MOONRAKER_DIR does not exist"
        missing_dirs=1
    fi

    if [ ! -d "$KLIPPY_ENV" ]; then
        log_error "Error: Klippy virtual environment $KLIPPY_ENV does not exist"
        missing_dirs=1
    fi

    if [ $missing_dirs -eq 1 ]; then
        exit 1
    fi
}

# Install system dependencies
install_system_deps() {
    log_message "Installing system dependencies..."
    sudo apt-get update
    if ! sudo apt-get install -y python3-evdev; then
        log_error "Error: Failed to install system dependencies"
        exit 1
    fi
}

# Add user to input group
setup_user_permissions() {
    log_message "Adding user to input group..."
    if ! sudo usermod -a -G input $USER; then
        log_error "Error: Failed to add user to input group"
        exit 1
    fi
}

# Install Python dependencies
install_python_deps() {
    log_message "Installing Python dependencies in klippy-env..."
    source $KLIPPY_ENV/bin/activate
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        if ! pip install -r "$SCRIPT_DIR/requirements.txt"; then
            log_error "Error: Failed to install Python dependencies"
            deactivate
            exit 1
        fi
    else
        log_warning "Warning: requirements.txt not found, installing evdev directly"
        if ! pip install evdev; then
            log_error "Error: Failed to install evdev"
            deactivate
            exit 1
        fi
    fi
    deactivate
}

# Setup Klipper plugin symlink
setup_klipper_plugin() {
    log_message "Setting up Klipper plugin symlink..."
    EXTRAS_DIR="$SCRIPT_DIR/extras"
    KLIPPER_EXTRAS_DIR="$KLIPPER_DIR/klippy/extras"

    if [ ! -d "$KLIPPER_EXTRAS_DIR" ]; then
        log_error "Error: Klipper extras directory does not exist"
        exit 1
    fi

    if [ -f "$EXTRAS_DIR/numpad_macros.py" ]; then
        # Remove existing symlink if it exists
        if [ -L "$KLIPPER_EXTRAS_DIR/numpad_macros.py" ]; then
            rm "$KLIPPER_EXTRAS_DIR/numpad_macros.py"
        fi

        # Create new symlink
        if ! ln -s "$EXTRAS_DIR/numpad_macros.py" "$KLIPPER_EXTRAS_DIR/numpad_macros.py"; then
            log_error "Error: Failed to create Klipper plugin symlink"
            exit 1
        fi
    else
        log_error "Error: Klipper plugin file not found in $EXTRAS_DIR"
        exit 1
    fi
}

# Setup Moonraker component symlink
setup_moonraker_component() {
    log_message "Setting up Moonraker component symlink..."
    COMPONENTS_DIR="$SCRIPT_DIR/components"
    MOONRAKER_COMPONENTS_DIR="$MOONRAKER_DIR/moonraker/components"

    if [ ! -d "$MOONRAKER_COMPONENTS_DIR" ]; then
        log_error "Error: Moonraker components directory does not exist"
        exit 1
    fi

    if [ -f "$COMPONENTS_DIR/numpad_macros_service.py" ]; then  # Updated filename
        # Remove existing symlink if it exists
        if [ -L "$MOONRAKER_COMPONENTS_DIR/numpad_macros_service.py" ]; then  # Updated filename
            rm "$MOONRAKER_COMPONENTS_DIR/numpad_macros_service.py"
        fi

        # Create new symlink
        if ! ln -s "$COMPONENTS_DIR/numpad_macros_service.py" "$MOONRAKER_COMPONENTS_DIR/numpad_macros_service.py"; then  # Updated filename
            log_error "Error: Failed to create Moonraker component symlink"
            exit 1
        fi
    else
        log_error "Error: Moonraker component file not found in $COMPONENTS_DIR"
        exit 1
    fi
}

# Restart services
restart_services() {
    log_message "Restarting Klipper and Moonraker services..."
    sudo systemctl restart klipper
    sudo systemctl restart moonraker
}

# Main installation process
main() {
    log_message "Starting Numpad Macros installation..."

    check_directories
    install_system_deps
    setup_user_permissions
    install_python_deps
    setup_klipper_plugin
    setup_moonraker_component
    update_moonraker_conf
    restart_services

    log_message "Installation completed successfully!"
    log_warning "Note: You may need to log out and back in for the input group changes to take effect"
    log_warning "Remember to add [numpad_macros] configuration to your printer.cfg to enable and configure the plugin"

    # Print verification steps
    echo -e "\n${GREEN}You can verify the installation by running:${NC}"
    echo -e "  ${YELLOW}1. ls -l $KLIPPER_DIR/klippy/extras/numpad_macros.py${NC}"
    echo -e "  ${YELLOW}2. ls -l $MOONRAKER_DIR/moonraker/components/numpad_macros.py${NC}"
    echo -e "  ${YELLOW}3. grep input /etc/group${NC}"
    echo -e "  ${YELLOW}4. systemctl status klipper${NC}"
    echo -e "  ${YELLOW}5. systemctl status moonraker${NC}"
    echo -e "  ${YELLOW}6. cat $MOONRAKER_CONF${NC} (to verify update_manager configuration)"
}

# Run the installation
main