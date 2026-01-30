#!/bin/bash
#
# CVAT PostgreSQL Backup to Google Drive
#
# This script performs hot backup of CVAT PostgreSQL database
# and uploads it to Google Drive using rclone.
#
# Usage: ./backup_to_gdrive.sh
#
# Requirements:
#   - rclone configured with 'gdrive' remote
#   - Docker running with cvat_db container
#   - mailutils for email notifications (optional)

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

# Database settings
DB_CONTAINER="cvat_db"
DB_USER="root"
DB_NAME="cvat"

# Backup settings
BACKUP_DIR="/tmp/cvat-backup"
LOG_DIR="/var/log/cvat-backup"
LOG_FILE="${LOG_DIR}/backup.log"

# Retention settings (days)
LOCAL_RETENTION_DAYS=7
GDRIVE_RETENTION_DAYS=30

# Google Drive settings
RCLONE_REMOTE="gdrive"
GDRIVE_FOLDER="cvat-backup"

# Email notification settings (leave empty to disable)
ALERT_EMAIL=""
# Example: ALERT_EMAIL="admin@example.com"

# =============================================================================
# Functions
# =============================================================================

log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" | tee -a "${LOG_FILE}"
}

log_info() {
    log "INFO" "$1"
}

log_error() {
    log "ERROR" "$1"
}

log_success() {
    log "SUCCESS" "$1"
}

send_alert() {
    local subject="$1"
    local body="$2"

    if [[ -n "${ALERT_EMAIL}" ]]; then
        if command -v mail &> /dev/null; then
            echo "${body}" | mail -s "${subject}" "${ALERT_EMAIL}"
            log_info "Alert email sent to ${ALERT_EMAIL}"
        else
            log_error "mail command not found. Install mailutils to enable email alerts."
        fi
    fi
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if rclone is installed
    if ! command -v rclone &> /dev/null; then
        log_error "rclone is not installed. Please run setup_backup.sh first."
        exit 1
    fi

    # Check if rclone remote is configured
    if ! rclone listremotes | grep -q "^${RCLONE_REMOTE}:$"; then
        log_error "rclone remote '${RCLONE_REMOTE}' is not configured."
        log_error "Run 'rclone config' to set up Google Drive."
        exit 1
    fi

    # Check if Docker is running
    if ! docker info &> /dev/null; then
        log_error "Docker is not running."
        exit 1
    fi

    # Check if cvat_db container exists and is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
        log_error "Container '${DB_CONTAINER}' is not running."
        exit 1
    fi

    log_info "All prerequisites satisfied."
}

create_directories() {
    mkdir -p "${BACKUP_DIR}"
    mkdir -p "${LOG_DIR}"
}

perform_backup() {
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_filename="cvat_db_${timestamp}.sql.gz"
    local backup_path="${BACKUP_DIR}/${backup_filename}"

    log_info "Starting PostgreSQL backup..."
    log_info "Backup file: ${backup_filename}"

    # Perform pg_dump with gzip compression
    if docker exec "${DB_CONTAINER}" pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip > "${backup_path}"; then
        local size
        size=$(du -h "${backup_path}" | cut -f1)
        log_success "Backup created successfully: ${backup_path} (${size})"
        echo "${backup_path}"
    else
        log_error "Failed to create database backup."
        return 1
    fi
}

upload_to_gdrive() {
    local backup_path="$1"
    local filename
    filename=$(basename "${backup_path}")

    log_info "Uploading to Google Drive: ${GDRIVE_FOLDER}/${filename}"

    if rclone copy "${backup_path}" "${RCLONE_REMOTE}:${GDRIVE_FOLDER}/" --progress; then
        log_success "Upload completed successfully."
        return 0
    else
        log_error "Failed to upload to Google Drive."
        return 1
    fi
}

cleanup_local_backups() {
    log_info "Cleaning up local backups older than ${LOCAL_RETENTION_DAYS} days..."

    local count
    count=$(find "${BACKUP_DIR}" -name "cvat_db_*.sql.gz" -type f -mtime +${LOCAL_RETENTION_DAYS} 2>/dev/null | wc -l)

    if [[ ${count} -gt 0 ]]; then
        find "${BACKUP_DIR}" -name "cvat_db_*.sql.gz" -type f -mtime +${LOCAL_RETENTION_DAYS} -delete
        log_info "Deleted ${count} old local backup(s)."
    else
        log_info "No old local backups to delete."
    fi
}

cleanup_gdrive_backups() {
    log_info "Cleaning up Google Drive backups older than ${GDRIVE_RETENTION_DAYS} days..."

    # rclone delete with min-age filter
    if rclone delete "${RCLONE_REMOTE}:${GDRIVE_FOLDER}/" \
        --min-age "${GDRIVE_RETENTION_DAYS}d" \
        --include "cvat_db_*.sql.gz" \
        --verbose 2>&1 | tee -a "${LOG_FILE}"; then
        log_info "Google Drive cleanup completed."
    else
        log_error "Failed to cleanup Google Drive backups."
    fi
}

# =============================================================================
# Main
# =============================================================================

main() {
    local start_time
    start_time=$(date '+%Y-%m-%d %H:%M:%S')

    log_info "=========================================="
    log_info "CVAT PostgreSQL Backup Started"
    log_info "=========================================="

    # Create necessary directories
    create_directories

    # Check prerequisites
    if ! check_prerequisites; then
        send_alert "[CVAT Backup FAILED] Prerequisites check failed" \
            "Backup failed at: ${start_time}\n\nPrerequisites check failed. Please check the logs at ${LOG_FILE}"
        exit 1
    fi

    # Perform backup
    local backup_path
    if ! backup_path=$(perform_backup); then
        send_alert "[CVAT Backup FAILED] Database backup failed" \
            "Backup failed at: ${start_time}\n\nFailed to create database dump. Please check the logs at ${LOG_FILE}"
        exit 1
    fi

    # Upload to Google Drive
    if ! upload_to_gdrive "${backup_path}"; then
        send_alert "[CVAT Backup FAILED] Upload failed" \
            "Backup failed at: ${start_time}\n\nFailed to upload to Google Drive. Please check the logs at ${LOG_FILE}\n\nLocal backup is still available at: ${backup_path}"
        exit 1
    fi

    # Cleanup old backups
    cleanup_local_backups
    cleanup_gdrive_backups

    local end_time
    end_time=$(date '+%Y-%m-%d %H:%M:%S')

    log_info "=========================================="
    log_success "Backup completed successfully!"
    log_info "Started: ${start_time}"
    log_info "Finished: ${end_time}"
    log_info "=========================================="
}

# Run main function
main "$@"
