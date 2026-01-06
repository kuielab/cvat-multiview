#!/bin/bash
# CVAT Multiview - Linux/Mac Quick Start Script
# This script automates the entire setup process

set -e

echo "========================================"
echo "CVAT Multiview - Quick Start"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# Check for Docker
echo "[1/8] Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed!"
    echo ""
    echo "Please install Docker from:"
    echo "  Linux: https://docs.docker.com/engine/install/"
    echo "  Mac: https://www.docker.com/products/docker-desktop/"
    exit 1
fi
print_success "Docker is installed"

echo ""
echo "[2/8] Checking if Docker is running..."
if ! docker ps &> /dev/null; then
    print_error "Docker is not running!"
    echo ""
    echo "Please start Docker and run this script again"
    echo "  Linux: sudo systemctl start docker"
    echo "  Mac: Start Docker Desktop application"
    exit 1
fi
print_success "Docker is running"

# Check for Docker Compose
echo ""
echo "[3/8] Checking Docker Compose..."
if ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not available!"
    echo ""
    echo "Please install Docker Compose:"
    echo "https://docs.docker.com/compose/install/"
    exit 1
fi
print_success "Docker Compose is available"

echo ""
echo "[4/8] Stopping any existing CVAT containers..."
docker compose down 2>/dev/null || true
print_success "Containers stopped"

echo ""
echo "[5/8] Starting CVAT (this may take 5-10 minutes on first run)..."
docker compose up -d
print_success "Containers started"

echo ""
echo "[6/8] Waiting for server to be ready..."
sleep 20

# Wait for server to be fully ready
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if docker compose exec -T cvat_server python -c "import django" 2>/dev/null; then
        break
    fi
    echo "Waiting for server... ($((attempt+1))/$max_attempts)"
    sleep 5
    ((attempt++))
done

if [ $attempt -eq $max_attempts ]; then
    print_error "Server failed to start within timeout"
    exit 1
fi
print_success "Server is ready"

echo ""
echo "[7/8] Running database migrations..."
docker compose exec -T cvat_server python manage.py makemigrations engine 2>/dev/null || true
docker compose exec -T cvat_server python manage.py migrate engine
print_success "Migrations complete"

echo ""
echo "[8/8] Creating admin account..."
# Check if admin already exists
admin_check=$(docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; print('exists' if User.objects.filter(username='admin').exists() else 'not_exists')" 2>/dev/null | tr -d '\r')

if [[ "$admin_check" == *"exists"* ]]; then
    print_success "Admin account already exists"
else
    docker compose exec -T cvat_server python manage.py createsuperuser --noinput --username admin --email admin@localhost 2>/dev/null || true
    docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; u=User.objects.get(username='admin'); u.set_password('admin123'); u.save(); print('Admin password set')" 2>/dev/null
    print_success "Admin account created"
    echo "     Username: admin"
    echo "     Password: admin123"
fi

echo ""
echo "[9/9] Getting API token..."
API_TOKEN=$(docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)" 2>/dev/null | tr -d '\r\n' | tail -1)
print_success "API Token: $API_TOKEN"

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "CVAT is now running at: http://localhost:8080"
echo ""
echo "Login credentials:"
echo "  Username: admin"
echo "  Password: admin123"
echo ""
echo "API Token: $API_TOKEN"
echo ""
echo "To create a multiview task, see QUICKSTART.md"
echo ""
echo "To stop CVAT: docker compose down"
echo "To restart: docker compose up -d"
echo ""
