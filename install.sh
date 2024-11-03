#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Define paths with variables for easier maintenance
KLIPPER_HOME="${HOME}/klipper"
MOONRAKER_HOME="${HOME}/moonraker"
PLUGIN_HOME="${HOME}/numpad_macros"
CONFIG_HOME="${HOME}/printer_data/config"
LOG_DIR="${HOME}/printer_data/logs"
INSTALL_LOG="${LOG_DIR}/numpad_macros_install.log"

# Update manager configuration block
read -r -d '' UPDATE_MANAGER_CONFIG << 'EOL'

[update_manager numpad_macros]
type: git_repo
path: ~/numpad_macros
origin: https://github.com/your-username/numpad_macros.git
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

# Function to check for required directories
check_directories() {
    local missing_dirs=0
    local dirs=("$KLIPPER_HOME" "$MOONRAKER_HOME" "$CONFIG_HOME")

    for dir in "${dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            log_error "Required directory not found: $dir"
            missing_dirs=1
        fi
    done

    # Create log directory if it doesn't exist
    if [ ! -d "$LOG_DIR" ]; then
        mkdir -p "$LOG_DIR"
    fi

    if [ $missing_dirs -eq 1 ]; then
        return 1
    fi
    return 0
}

# Install system dependencies
install_system_deps() {
    log_message "Installing system dependencies..."
    sudo apt-get update || {
        log_error "Failed to update package list"
        return 1
    }
    sudo apt-get install -y python3-evdev || {
        log_error "Failed to install python3-evdev"
        return 1
    }
    return 0
}

# Setup user permissions
setup_user_permissions() {
    log_message "Adding user to input group..."
    if ! groups | grep -q "\binput\b"; then
        sudo usermod -a -G input "$USER" || {
            log_error "Failed to add user to input group"
            return 1
        }
        log_warning "You will need to log out and back in for the input group changes to take effect"
    else
        log_message "User already in input group"
    fi
    return 0
}

# Setup Klipper plugin
setup_klipper_plugin() {
    log_message "Setting up Klipper plugin..."
    local plugin_src="${PLUGIN_HOME}/numpad_macros.py"
    local plugin_dst="${KLIPPER_HOME}/klippy/extras/numpad_macros.py"

    if [ -f "$plugin_src" ]; then
        ln -sf "$plugin_src" "$plugin_dst" || {
            log_error "Failed to create Klipper plugin symlink"
            return 1
        }
    else
        log_error "Plugin source file not found: $plugin_src"
        return 1
    fi
    return 0
}

# Setup Moonraker component
setup_moonraker_component() {
    log_message "Setting up Moonraker component..."
    local component_src="${PLUGIN_HOME}/numpad_macros_service.py"
    local component_dst="${MOONRAKER_HOME}/moonraker/components/numpad_macros.py"

    if [ -f "$component_src" ]; then
        ln -sf "$component_src" "$component_dst" || {
            log_error "Failed to create Moonraker component symlink"
            return 1
        }
    else
        log_error "Component source file not found: $component_src"
        return 1
    fi
    return 0
}

# Update Moonraker configuration
update_moonraker_conf() {
    local moonraker_conf="${CONFIG_HOME}/moonraker.conf"

    if [ ! -f "$moonraker_conf" ]; then
        log_error "moonraker.conf not found at $moonraker_conf"
        return 1
    fi

    # Check if update_manager section already exists
    if ! grep -q "\[update_manager numpad_macros\]" "$moonraker_conf"; then
        log_message "Adding update_manager configuration..."
        echo "$UPDATE_MANAGER_CONFIG" >> "$moonraker_conf"
    else
        log_warning "Update manager section already exists in moonraker.conf"
    fi
    return 0
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

    # Run installation steps
    check_directories || exit 1
    install_system_deps || exit 1
    setup_user_permissions || exit 1
    setup_klipper_plugin || exit 1
    setup_moonraker_component || exit 1
    update_moonraker_conf || exit 1
    restart_services

    log_message "Installation completed successfully!"

    # Print verification instructions
    cat << EOF

${GREEN}Installation complete! Please verify the installation:${NC}

1. Check Klipper plugin:
   ls -l ${KLIPPER_HOME}/klippy/extras/numpad_macros.py

2. Check Moonraker component:
   ls -l ${MOONRAKER_HOME}/moonraker/components/numpad_macros.py

3. Verify group membership:
   groups | grep input

4. Check service status:
   systemctl status klipper
   systemctl status moonraker

5. Add configuration to your printer.cfg:

[numpad_macros]
device_paths: /dev/input/by-id/your-device-id
debug_log: True

EOF
}

# Run the installation
main