#!/bin/bash
#
# CVAT Backup Setup Script
#
# This script helps set up the automated backup system for CVAT PostgreSQL.
# It will:
#   1. Install rclone if not present
#   2. Guide you through rclone Google Drive configuration
#   3. Set up cron jobs for automated backups
#
# Usage: sudo ./setup_backup.sh
#

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup_to_gdrive.sh"

# Backup schedule (KST 06:00 = UTC 21:00, KST 18:00 = UTC 09:00)
CRON_SCHEDULE_1="0 21 * * *"  # KST 06:00
CRON_SCHEDULE_2="0 9 * * *"   # KST 18:00

# Directories
BACKUP_DIR="/tmp/cvat-backup"
LOG_DIR="/var/log/cvat-backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Functions
# =============================================================================

print_header() {
    echo -e "${BLUE}"
    echo "=============================================="
    echo "  CVAT PostgreSQL Backup Setup"
    echo "=============================================="
    echo -e "${NC}"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_warning "This script should be run as root for system-wide setup."
        print_info "Some features may require sudo access."
        echo ""
    fi
}

install_rclone() {
    echo ""
    echo -e "${BLUE}Step 1: Installing rclone${NC}"
    echo "----------------------------------------"

    if command -v rclone &> /dev/null; then
        local version
        version=$(rclone version | head -n1)
        print_success "rclone is already installed: ${version}"
    else
        print_info "Installing rclone..."
        if curl https://rclone.org/install.sh | sudo bash; then
            print_success "rclone installed successfully."
        else
            print_error "Failed to install rclone."
            exit 1
        fi
    fi
}

install_mailutils() {
    echo ""
    echo -e "${BLUE}Step 2: Installing mailutils (optional, for email alerts)${NC}"
    echo "----------------------------------------"

    if command -v mail &> /dev/null; then
        print_success "mailutils is already installed."
    else
        read -p "Install mailutils for email notifications? (y/n): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if apt-get update && apt-get install -y mailutils; then
                print_success "mailutils installed successfully."
            else
                print_warning "Failed to install mailutils. Email notifications will not work."
            fi
        else
            print_info "Skipping mailutils installation."
        fi
    fi
}

configure_rclone() {
    echo ""
    echo -e "${BLUE}Step 3: Configuring rclone for Google Drive${NC}"
    echo "----------------------------------------"

    # Check if gdrive remote already exists
    if rclone listremotes 2>/dev/null | grep -q "^gdrive:$"; then
        print_success "rclone 'gdrive' remote is already configured."
        read -p "Do you want to reconfigure it? (y/n): " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            return
        fi
    fi

    echo ""
    echo "Please follow the interactive rclone configuration."
    echo ""
    echo -e "${YELLOW}Configuration steps:${NC}"
    echo "  1. Choose 'n' for New remote"
    echo "  2. Name: gdrive"
    echo "  3. Storage type: Choose the number for 'Google Drive'"
    echo "  4. client_id: Press Enter (use default)"
    echo "  5. client_secret: Press Enter (use default)"
    echo "  6. scope: Choose '1' for Full access"
    echo "  7. root_folder_id: Press Enter (or enter specific folder ID)"
    echo "  8. service_account_file: Press Enter"
    echo "  9. Edit advanced config: n"
    echo "  10. Use auto config: n (since this is a headless server)"
    echo "  11. Follow the URL and paste the verification code"
    echo "  12. Configure as team drive: n (unless you're using team drive)"
    echo "  13. Confirm with 'y'"
    echo "  14. Quit with 'q'"
    echo ""

    read -p "Press Enter to start rclone configuration..."

    rclone config

    # Verify configuration
    if rclone listremotes | grep -q "^gdrive:$"; then
        print_success "rclone 'gdrive' remote configured successfully."

        echo ""
        print_info "Testing connection to Google Drive..."
        if rclone lsd gdrive: &>/dev/null; then
            print_success "Successfully connected to Google Drive."

            # Create backup folder if it doesn't exist
            if ! rclone lsd gdrive: 2>/dev/null | grep -q "cvat-backup"; then
                print_info "Creating 'cvat-backup' folder on Google Drive..."
                rclone mkdir gdrive:cvat-backup
                print_success "Created 'cvat-backup' folder."
            else
                print_success "'cvat-backup' folder already exists on Google Drive."
            fi
        else
            print_warning "Could not connect to Google Drive. Please verify your configuration."
        fi
    else
        print_error "rclone configuration failed. Please try again."
        exit 1
    fi
}

create_directories() {
    echo ""
    echo -e "${BLUE}Step 4: Creating directories${NC}"
    echo "----------------------------------------"

    # Create backup directory
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        mkdir -p "${BACKUP_DIR}"
        print_success "Created backup directory: ${BACKUP_DIR}"
    else
        print_success "Backup directory already exists: ${BACKUP_DIR}"
    fi

    # Create log directory
    if [[ ! -d "${LOG_DIR}" ]]; then
        sudo mkdir -p "${LOG_DIR}"
        sudo chmod 755 "${LOG_DIR}"
        print_success "Created log directory: ${LOG_DIR}"
    else
        print_success "Log directory already exists: ${LOG_DIR}"
    fi
}

setup_permissions() {
    echo ""
    echo -e "${BLUE}Step 5: Setting up permissions${NC}"
    echo "----------------------------------------"

    # Make backup script executable
    chmod +x "${BACKUP_SCRIPT}"
    print_success "Made backup script executable: ${BACKUP_SCRIPT}"

    # Secure rclone config
    local rclone_config="${HOME}/.config/rclone/rclone.conf"
    if [[ -f "${rclone_config}" ]]; then
        chmod 600 "${rclone_config}"
        print_success "Secured rclone config: ${rclone_config}"
    fi
}

setup_cron() {
    echo ""
    echo -e "${BLUE}Step 6: Setting up cron jobs${NC}"
    echo "----------------------------------------"

    # Check if cron jobs already exist
    local existing_cron
    existing_cron=$(crontab -l 2>/dev/null || true)

    if echo "${existing_cron}" | grep -q "backup_to_gdrive.sh"; then
        print_warning "Backup cron jobs already exist."
        echo ""
        echo "Current cron entries for backup:"
        echo "${existing_cron}" | grep "backup_to_gdrive.sh"
        echo ""

        read -p "Do you want to replace them? (y/n): " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing cron configuration."
            return
        fi

        # Remove existing backup cron entries
        existing_cron=$(echo "${existing_cron}" | grep -v "backup_to_gdrive.sh" || true)
    fi

    # Add new cron entries
    local new_cron="${existing_cron}
# CVAT PostgreSQL Backup to Google Drive
# KST 06:00 (UTC 21:00)
${CRON_SCHEDULE_1} ${BACKUP_SCRIPT} >> ${LOG_DIR}/backup.log 2>&1
# KST 18:00 (UTC 09:00)
${CRON_SCHEDULE_2} ${BACKUP_SCRIPT} >> ${LOG_DIR}/backup.log 2>&1"

    echo "${new_cron}" | crontab -

    print_success "Cron jobs configured successfully."
    echo ""
    echo "Scheduled backups:"
    echo "  - KST 06:00 (UTC 21:00)"
    echo "  - KST 18:00 (UTC 09:00)"
}

test_backup() {
    echo ""
    echo -e "${BLUE}Step 7: Test backup (optional)${NC}"
    echo "----------------------------------------"

    read -p "Do you want to run a test backup now? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Running test backup..."
        echo ""

        if "${BACKUP_SCRIPT}"; then
            print_success "Test backup completed successfully!"
        else
            print_error "Test backup failed. Please check the logs at ${LOG_DIR}/backup.log"
        fi
    else
        print_info "Skipping test backup."
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}=============================================="
    echo "  Setup Complete!"
    echo "==============================================${NC}"
    echo ""
    echo "Summary:"
    echo "  - Backup script: ${BACKUP_SCRIPT}"
    echo "  - Backup directory: ${BACKUP_DIR}"
    echo "  - Log file: ${LOG_DIR}/backup.log"
    echo "  - Schedule: KST 06:00 and 18:00 (UTC 21:00 and 09:00)"
    echo ""
    echo "Configuration:"
    echo "  - Local backup retention: 7 days"
    echo "  - Google Drive retention: 30 days"
    echo ""
    echo "Commands:"
    echo "  - Manual backup: ${BACKUP_SCRIPT}"
    echo "  - View logs: tail -f ${LOG_DIR}/backup.log"
    echo "  - Edit cron: crontab -e"
    echo "  - List Google Drive backups: rclone ls gdrive:cvat-backup/"
    echo ""
    echo "To configure email alerts, edit ${BACKUP_SCRIPT}"
    echo "and set the ALERT_EMAIL variable."
    echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
    print_header
    check_root

    install_rclone
    install_mailutils
    configure_rclone
    create_directories
    setup_permissions
    setup_cron
    test_backup
    print_summary
}

# Run main function
main "$@"
