#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Define paths
REPO_DIR="/home/pi/lister_numpad_macros"
MOONRAKER_DIR="/home/pi/moonraker"
LOG_DIR="/home/pi/printer_data/logs"
INSTALL_LOG="$LOG_DIR/numpad_macros_install.log"
MOONRAKER_CONF="/home/pi/printer_data/config/moonraker.conf"
UPDATE_SCRIPT="${REPO_DIR}/refresh.sh"

# Update manager configuration block
read -r -d '' UPDATE_MANAGER_CONFIG << 'EOL'

[update_manager lister_numpad_macros]
type: git_repo
path: ~/lister_numpad_macros
origin: https://github.com/CWE3D/lister_numpad_macros.git
is_system_service: False
primary_branch: main
managed_services: moonraker
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

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Please run as root (sudo)"
        exit 1
    fi
}

# Check if required directories exist
check_directories() {
    local missing_dirs=0
    local dirs=("$REPO_DIR" "$MOONRAKER_DIR")

    for dir in "${dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            log_error "Error: Directory $dir does not exist"
            missing_dirs=1
        fi
    done

    if [ $missing_dirs -eq 1 ]; then
        exit 1
    fi
}

# Install system dependencies
install_system_deps() {
    log_message "Installing system dependencies..."
    apt-get update
    apt-get install -y python3-pip
}

# Setup user permissions
setup_user_permissions() {
    log_message "Adding user pi to input group..."
    usermod -a -G input pi

    # Set correct ownership for repository
    chown -R pi:pi "$REPO_DIR"
}

# Install Python dependencies
install_python_deps() {
    log_message "Installing Python dependencies..."
    pip3 install -r "$REPO_DIR/requirements.txt"
}

# Create update script
create_update_script() {
    log_message "Creating update script..."

    # Create the update script
    cat > "$UPDATE_SCRIPT" << 'EOL'
#!/bin/bash

# Define colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Define paths
REPO_DIR="/home/pi/lister_numpad_macros"
LOG_DIR="/home/pi/printer_data/logs"
UPDATE_LOG="$LOG_DIR/numpad_update.log"

# Function to log messages
log_message() {
    echo -e "${GREEN}$(date): $1${NC}" | tee -a "$UPDATE_LOG"
}

log_error() {
    echo -e "${RED}$(date): $1${NC}" | tee -a "$UPDATE_LOG"
}

log_warning() {
    echo -e "${YELLOW}$(date): $1${NC}" | tee -a "$UPDATE_LOG"
}

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Please run as root (sudo)"
        exit 1
    fi
}

# Function to update repository
update_repo() {
    log_message "Updating numpad macros repository..."

    if [ ! -d "$REPO_DIR" ]; then
        log_message "Repository not found. Cloning..."
        git clone https://github.com/CWE3D/lister_numpad_macros.git "$REPO_DIR"
    else
        cd "$REPO_DIR" || exit 1
        git fetch

        LOCAL=$(git rev-parse @)
        REMOTE=$(git rev-parse @{u})

        if [ "$LOCAL" != "$REMOTE" ]; then
            log_message "Updates found. Pulling changes..."
            git pull
            return 0
        else
            log_message "Already up to date"
            return 1
        fi
    fi
}

# Function to restart services
restart_services() {
    log_message "Restarting services..."

    # Stop services in reverse dependency order
    log_message "Stopping numpad event service..."
    systemctl stop numpad_event_service

    log_message "Stopping Moonraker..."
    systemctl stop moonraker

    log_message "Stopping Klipper..."
    systemctl stop klipper

    # Small delay to ensure clean shutdown
    sleep 2

    # Start services in dependency order
    log_message "Starting Klipper..."
    systemctl start klipper
    sleep 2

    log_message "Starting Moonraker..."
    systemctl start moonraker
    sleep 2

    log_message "Starting numpad event service..."
    systemctl start numpad_event_service
}

# Function to verify services
verify_services() {
    local all_good=true

    # Check each service
    for service in klipper moonraker numpad_event_service; do
        if ! systemctl is-active --quiet "$service"; then
            log_error "$service failed to start"
            all_good=false
        else
            log_message "$service is running"
        fi
    done

    if [ "$all_good" = false ]; then
        log_error "Some services failed to start. Check the logs for details:"
        log_error "- Klipper log: ${LOG_DIR}/klippy.log"
        log_error "- Moonraker log: ${LOG_DIR}/moonraker.log"
        log_error "- Numpad service log: ${LOG_DIR}/numpad_event_service.log"
        return 1
    fi

    return 0
}

# Main update process
main() {
    log_message "Starting numpad macros update process..."

    check_root

    # Update repository
    if update_repo; then
        # Only restart services if there were updates
        restart_services
        verify_services
    else
        log_message "No updates found. Skipping service restart."
    fi

    log_message "Update process completed!"

    # Print verification steps
    echo -e "\n${GREEN}Verify the services:${NC}"
    echo -e "1. Check Klipper status: ${YELLOW}systemctl status klipper${NC}"
    echo -e "2. Check Moonraker status: ${YELLOW}systemctl status moonraker${NC}"
    echo -e "3. Check numpad service status: ${YELLOW}systemctl status numpad_event_service${NC}"
    echo -e "4. View logs: ${YELLOW}tail -f ${LOG_DIR}/{klippy,moonraker,numpad_event_service}.log${NC}"
}

# Run the update
main
EOL

    # Make update script executable
    chmod +x "$UPDATE_SCRIPT"
    chown pi:pi "$UPDATE_SCRIPT"

    log_message "Update script created at $UPDATE_SCRIPT"
}

# Setup event service
setup_event_service() {
    log_message "Setting up numpad event service..."

    # Create the systemd service file
    cat > /etc/systemd/system/numpad_event_service.service << EOL
[Unit]
Description=Numpad Listener Service for Moonraker
After=network.target moonraker.service
Wants=moonraker.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 ${REPO_DIR}/extras/numpad_event_service.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

    # Make service file executable
    chmod +x "${REPO_DIR}/extras/numpad_event_service.py"

    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable numpad_event_service.service
}

# Setup Moonraker component symlink
setup_moonraker_component() {
    log_message "Setting up Moonraker component symlink..."

    local moonraker_comp_dir="${MOONRAKER_DIR}/moonraker/components"
    if [ -L "${moonraker_comp_dir}/numpad_macros.py" ]; then
        rm "${moonraker_comp_dir}/numpad_macros.py"
    fi
    ln -s "${REPO_DIR}/components/numpad_macros.py" "${moonraker_comp_dir}/numpad_macros.py"
    chown -h pi:pi "${moonraker_comp_dir}/numpad_macros.py"
}

# Update moonraker.conf
update_moonraker_conf() {
    log_message "Updating moonraker.conf..."

    # Backup existing config
    cp "$MOONRAKER_CONF" "${MOONRAKER_CONF}.backup"

    # Add update_manager section if it doesn't exist
    if ! grep -q "^\[update_manager lister_numpad_macros\]" "$MOONRAKER_CONF"; then
        echo "$UPDATE_MANAGER_CONFIG" >> "$MOONRAKER_CONF"
    fi
}

# Restart services
restart_services() {
    log_message "Restarting services..."
    systemctl restart numpad_event_service
    systemctl restart moonraker
}

# Main installation process
main() {
    log_message "Starting Numpad Macros installation..."

    check_root
    check_directories
    install_system_deps
    setup_user_permissions
    install_python_deps
    setup_event_service
    setup_moonraker_component
    update_moonraker_conf
    create_update_script
    restart_services

    log_message "Installation completed successfully!"

    # Print verification steps
    echo -e "\n${GREEN}Verify the installation:${NC}"
    echo -e "1. Check event service status: ${YELLOW}systemctl status numpad_event_service${NC}"
    echo -e "2. View event service logs: ${YELLOW}journalctl -u numpad_event_service -f${NC}"
    echo -e "3. Check Moonraker logs: ${YELLOW}tail -f ${LOG_DIR}/moonraker.log${NC}"
    echo -e "4. Update script created at: ${YELLOW}${UPDATE_SCRIPT}${NC}"

    log_warning "Note: You may need to log out and back in for the input group changes to take effect"
}

# Run the installation
main