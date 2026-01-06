@echo off
REM CVAT Multiview - Windows Quick Start Script
REM This script automates the entire setup process

echo ========================================
echo CVAT Multiview - Quick Start
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] This script requires administrator privileges
    echo Right-click and select "Run as Administrator"
    pause
    exit /b 1
)

echo [1/8] Checking Docker installation...
docker --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Docker is not installed!
    echo.
    echo Please install Docker Desktop from:
    echo https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)
echo [OK] Docker is installed

echo.
echo [2/8] Checking if Docker Desktop is running...
docker ps >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Docker Desktop is not running!
    echo.
    echo Please start Docker Desktop and wait for it to fully start
    echo Then run this script again
    pause
    exit /b 1
)
echo [OK] Docker Desktop is running

echo.
echo [3/8] Stopping any existing CVAT containers...
docker compose down 2>nul
echo [OK] Containers stopped

echo.
echo [4/8] Starting CVAT (this may take 5-10 minutes on first run)...
docker compose up -d
if %errorLevel% neq 0 (
    echo [ERROR] Failed to start Docker containers
    pause
    exit /b 1
)

echo.
echo [5/8] Waiting for server to be ready...
timeout /t 20 /nobreak >nul

REM Wait for server to be fully ready
:wait_loop
docker compose exec -T cvat_server python -c "import django" 2>nul
if %errorLevel% neq 0 (
    echo Waiting for server...
    timeout /t 5 /nobreak >nul
    goto wait_loop
)
echo [OK] Server is ready

echo.
echo [6/8] Running database migrations...
docker compose exec -T cvat_server python manage.py makemigrations engine 2>nul
docker compose exec -T cvat_server python manage.py migrate engine
if %errorLevel% neq 0 (
    echo [ERROR] Migration failed
    pause
    exit /b 1
)
echo [OK] Migrations complete

echo.
echo [7/8] Creating admin account...
REM Check if admin already exists
docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; print('exists' if User.objects.filter(username='admin').exists() else 'not_exists')" > temp_admin_check.txt 2>nul
findstr /C:"exists" temp_admin_check.txt >nul
if %errorLevel% equ 0 (
    echo [OK] Admin account already exists
) else (
    docker compose exec -T cvat_server python manage.py createsuperuser --noinput --username admin --email admin@localhost
    docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; u=User.objects.get(username='admin'); u.set_password('admin123'); u.save(); print('Admin password set')"
    echo [OK] Admin account created
    echo      Username: admin
    echo      Password: admin123
)
del temp_admin_check.txt 2>nul

echo.
echo [8/8] Getting API token...
for /f "tokens=2" %%i in ('docker compose exec -T cvat_server python manage.py shell -c "from django.contrib.auth.models import User; from rest_framework.authtoken.models import Token; u=User.objects.get(username='admin'); t,_=Token.objects.get_or_create(user=u); print(t.key)" 2^>nul') do set API_TOKEN=%%i
echo [OK] API Token: %API_TOKEN%

echo.
echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo CVAT is now running at: http://localhost:8080
echo.
echo Login credentials:
echo   Username: admin
echo   Password: admin123
echo.
echo API Token: %API_TOKEN%
echo.
echo To create a multiview task, see QUICKSTART.md
echo.
echo To stop CVAT: docker compose down
echo To restart: docker compose up -d
echo.

pause
