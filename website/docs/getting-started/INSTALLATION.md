# Installation Guide - Learning-Performance-Observability-Stack

Complete step-by-step guide to install and run the Learning-Performance-Observability-Stack educational platform on your computer.

## Table of Contents

- [System Requirements](#system-requirements)
- [Prerequisites Installation](#prerequisites-installation)
  - [Windows](#windows)
  - [macOS](#macos)
  - [Linux](#linux)
- [Project Installation](#project-installation)
- [First-Time Setup](#first-time-setup)
- [Verifying Installation](#verifying-installation)
- [Accessing Services](#accessing-services)
- [Common Issues](#common-issues)
- [Next Steps](#next-steps)

---

## System Requirements

### Minimum Hardware Requirements

- **RAM:** 4 GB minimum, 8 GB recommended
- **Disk Space:** 5 GB free space for Docker images and volumes
- **CPU:** 2 cores minimum, 4 cores recommended
- **Internet:** Required for initial Docker image downloads

### Software Requirements

- **Docker:** Version 20.10 or higher
- **Docker Compose:** Version 2.0 or higher
- **Git:** Any recent version
- **Web Browser:** Chrome, Firefox, Safari, or Edge (latest versions)

### Port Availability

The following ports must be available on your system:

| Port | Service | Description |
|------|---------|-------------|
| 3000 | Grafana | Visualization dashboard |
| 3001 | Users API | Main REST API |
| 3100 | Loki | Log aggregation |
| 3200 | Tempo | Distributed tracing |
| 4000 | Frontend | Web interface |
| 4317 | OTLP gRPC | OpenTelemetry protocol |
| 4318 | OTLP HTTP | OpenTelemetry protocol |
| 5434 | PostgreSQL | Database |
| 9090 | Prometheus | Metrics collection |

---

## Prerequisites Installation

### Windows

#### 1. Install Docker Desktop for Windows

1. Download Docker Desktop from: https://www.docker.com/products/docker-desktop/
2. Run the installer
3. Follow the installation wizard
4. **Important:** Enable WSL 2 during installation (recommended)
5. Restart your computer when prompted
6. Launch Docker Desktop
7. Wait for Docker Engine to start (check the system tray icon)

**Verify installation:**
```powershell
docker --version
docker-compose --version
```

Expected output:
```
Docker version 24.0.0 or higher
Docker Compose version v2.0.0 or higher
```

#### 2. Install Git for Windows

1. Download Git from: https://git-scm.com/download/win
2. Run the installer
3. Use default settings (or customize as needed)
4. Open Command Prompt or PowerShell

**Verify installation:**
```powershell
git --version
```

---

### macOS

#### 1. Install Docker Desktop for Mac

1. Download Docker Desktop from: https://www.docker.com/products/docker-desktop/
2. Open the `.dmg` file
3. Drag Docker icon to Applications folder
4. Launch Docker from Applications
5. Grant permissions when requested
6. Wait for Docker Engine to start (menu bar icon)

**Verify installation:**
```bash
docker --version
docker-compose --version
```

#### 2. Install Git (if not already installed)

macOS usually comes with Git pre-installed. Verify with:
```bash
git --version
```

If not installed, download from: https://git-scm.com/download/mac

Or install via Homebrew:
```bash
brew install git
```

---

### Linux

#### 1. Install Docker Engine

**Ubuntu/Debian:**

```bash
# Update package index
sudo apt-get update

# Install prerequisites
sudo apt-get install ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to docker group (avoid using sudo)
sudo usermod -aG docker $USER

# Log out and log back in for group changes to take effect
```

**Fedora/RHEL/CentOS:**

```bash
# Install Docker
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group
sudo usermod -aG docker $USER
```

**Verify installation:**
```bash
docker --version
docker compose version
```

#### 2. Install Git

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install git
```

**Fedora/RHEL/CentOS:**
```bash
sudo dnf install git
```

**Verify installation:**
```bash
git --version
```

---

## Project Installation

### Step 1: Clone the Repository

Open your terminal (Command Prompt, PowerShell, Terminal, etc.) and run:

```bash
# Clone the repository (replace with actual repository URL)
git clone https://github.com/your-username/api-example-node-js.git

# Navigate to project directory
cd api-example-node-js
```

### Step 2: Review Project Structure

After cloning, you should see this structure:

```
api-example-node-js/
├── docker-compose.yml       # Docker orchestration configuration
├── Dockerfile               # API container configuration
├── .env.example             # Environment variables template
├── package.json             # Node.js dependencies
├── README.md                # Main documentation
├── INSTALLATION.md          # This file
├── db/
│   └── init.sql            # Database initialization script
├── observability/
│   ├── prometheus.yml      # Prometheus configuration
│   ├── tempo.yaml          # Tempo configuration
│   ├── loki.yaml           # Loki configuration
│   ├── promtail.yaml       # Promtail configuration
│   ├── alert-rules.yml     # Alert rules
│   └── slo-rules.yml       # SLO rules
├── src/
│   ├── server.js           # Main API server
│   ├── tracing.js          # OpenTelemetry configuration
│   ├── logger.js           # Structured logging
│   └── db.js               # Database connection
└── users-front/            # Frontend application
    ├── Dockerfile
    ├── package.json
    └── src/
```

### Step 3: Configure Environment Variables (Optional)

The project uses sensible defaults from `docker-compose.yml`, but you can customize settings:

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env file with your preferred text editor
# Example: nano .env, vim .env, or code .env
```

**Default configuration works out-of-the-box**, so this step is optional for most users.

---

## First-Time Setup

### Step 1: Start All Services

From the project root directory, run:

```bash
docker-compose up -d
```

**What happens:**
- Docker downloads required images (first time only, ~2-5 minutes)
- Creates 8 containers:
  - `users-api` - REST API
  - `users-front` - Web frontend
  - `users-db` - PostgreSQL database
  - `grafana` - Visualization platform
  - `tempo` - Distributed tracing
  - `loki` - Log aggregation
  - `promtail` - Log collector
  - `prometheus` - Metrics collection
- Creates Docker volumes for data persistence
- Creates a Docker network for inter-service communication

**Expected output:**
```
[+] Running 9/9
 ✔ Network api-example-node-js_observability  Created
 ✔ Volume "api-example-node-js_postgres_data" Created
 ✔ Volume "api-example-node-js_tempo_data"    Created
 ✔ Volume "api-example-node-js_loki_data"     Created
 ✔ Volume "api-example-node-js_prometheus_data" Created
 ✔ Volume "api-example-node-js_grafana_data"  Created
 ✔ Container tempo         Started
 ✔ Container loki          Started
 ✔ Container promtail      Started
 ✔ Container users-db      Started
 ✔ Container prometheus    Started
 ✔ Container users-api     Started
 ✔ Container users-front   Started
 ✔ Container grafana       Started
```

### Step 2: Wait for Services to Initialize

Give the services 30-60 seconds to fully start. You can monitor progress with:

```bash
docker-compose ps
```

**Healthy output (all services "running"):**
```
NAME          IMAGE                    STATUS         PORTS
grafana       grafana/grafana:latest   Up 30 seconds  0.0.0.0:3000->3000/tcp
loki          grafana/loki:latest      Up 30 seconds  0.0.0.0:3100->3100/tcp
prometheus    prom/prometheus:latest   Up 30 seconds  0.0.0.0:9090->9090/tcp
promtail      grafana/promtail:latest  Up 30 seconds
tempo         grafana/tempo:latest     Up 30 seconds  0.0.0.0:3200->3200/tcp
users-api     api-example-node-js-api  Up 30 seconds  0.0.0.0:3001->3001/tcp
users-db      postgres:15-alpine       Up 30 seconds  0.0.0.0:5434->5432/tcp
users-front   users-front              Up 30 seconds  0.0.0.0:4000->80/tcp
```

### Step 3: Check Service Health

**Test API health:**
```bash
curl http://localhost:3001/health
```

**Expected response:**
```json
{
  "status": "OK",
  "timestamp": "2025-12-03T12:00:00.000Z"
}
```

**Test API readiness (includes database check):**
```bash
curl http://localhost:3001/health/ready
```

**Expected response:**
```json
{
  "status": "OK",
  "timestamp": "2025-12-03T12:00:00.000Z",
  "checks": {
    "database": "connected",
    "dbConnections": {
      "total": 1,
      "idle": 1,
      "waiting": 0
    }
  }
}
```

---

## Verifying Installation

### Test 1: Create Sample Users

Generate 5 random users:

```bash
# Linux/macOS
for i in {1..5}; do
  curl -s -X POST http://localhost:3001/api/users
  sleep 1
done

# Windows PowerShell
for ($i=1; $i -le 5; $i++) {
  Invoke-RestMethod -Method POST -Uri http://localhost:3001/api/users
  Start-Sleep -Seconds 1
}
```

### Test 2: Retrieve Users

```bash
curl http://localhost:3001/api/users
```

**Expected response:**
```json
{
  "status": "OK",
  "code": 200,
  "total": 5,
  "data": [
    {
      "id": 1,
      "firstname": "John",
      "lastname": "Doe",
      "email": "john.doe@example.com",
      ...
    }
  ]
}
```

### Test 3: Check Metrics

```bash
curl http://localhost:3001/metrics
```

**Expected:** Prometheus-format metrics output with `http_requests_total`, `users_created_total`, etc.

---

## Accessing Services

### 1. Frontend Web Interface

**URL:** http://localhost:4000

**Features:**
- Interactive API documentation
- API playground for testing endpoints
- Observability dashboard links
- Architecture diagrams

### 2. Grafana Dashboard

**URL:** http://localhost:3000

**Default Credentials:**
- Username: `admin`
- Password: `admin`

**First login:**
1. Open http://localhost:3000
2. Enter credentials
3. Skip password change prompt (or change it)
4. Navigate to dashboard via "Dashboards" menu

**Pre-configured dashboards:**
- Users API Monitoring (Basic): http://localhost:3000/d/users-api-obs
- Users API Monitoring (Enhanced): http://localhost:3000/d/users-api-obs-v2

### 3. Prometheus

**URL:** http://localhost:9090

**Useful pages:**
- Targets: http://localhost:9090/targets (verify API is being scraped)
- Alerts: http://localhost:9090/alerts (view active alerts)
- Graph: http://localhost:9090/graph (query metrics manually)

**Example query:**
```
rate(http_requests_total[1m])
```

### 4. Explore Logs (Loki)

1. Open Grafana: http://localhost:3000
2. Go to "Explore" (compass icon in left sidebar)
3. Select datasource: **Loki**
4. Run query:
```
{container="users-api"} | json
```

### 5. Explore Traces (Tempo)

1. Open Grafana: http://localhost:3000
2. Go to "Explore"
3. Select datasource: **Tempo**
4. Search for traces:
```
{resource.service.name="users-api-microservice"}
```

---

## Common Issues

### Issue 1: Port Already in Use

**Error:**
```
Error: bind: address already in use
```

**Solution:**

**Find and stop conflicting process:**

```bash
# Linux/macOS
lsof -i :3000  # Replace 3000 with the conflicting port
kill -9 <PID>

# Windows
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

**Or change ports in `docker-compose.yml`:**
```yaml
services:
  grafana:
    ports:
      - "3030:3000"  # Change 3000 to 3030
```

### Issue 2: Docker Daemon Not Running

**Error:**
```
Cannot connect to the Docker daemon
```

**Solution:**
- **Windows/macOS:** Launch Docker Desktop application
- **Linux:** Start Docker service:
  ```bash
  sudo systemctl start docker
  ```

### Issue 3: Permission Denied (Linux)

**Error:**
```
permission denied while trying to connect to Docker daemon
```

**Solution:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and log back in
# Or run: newgrp docker
```

### Issue 4: Database Connection Failed

**Error in API logs:**
```
Error: connect ECONNREFUSED
```

**Solution:**
```bash
# Check if database is healthy
docker-compose ps users-db

# Restart database
docker-compose restart users-db

# Wait 10 seconds and restart API
docker-compose restart users-api
```

### Issue 5: Cannot Access Grafana

**Problem:** Browser shows "Connection refused" or "Cannot reach"

**Solution:**
```bash
# Check Grafana status
docker-compose logs grafana

# Restart Grafana
docker-compose restart grafana

# Wait 10 seconds and try again
```

### Issue 6: Slow Performance

**Symptoms:** Services take too long to start or respond slowly

**Solutions:**
- Increase Docker Desktop resources:
  - **Windows/macOS:** Docker Desktop → Settings → Resources
  - Recommended: 4 GB RAM, 2 CPUs minimum
- Close other resource-intensive applications
- Check disk space: `df -h` (Linux/macOS) or `Get-PSDrive` (Windows)

### Issue 7: Services Keep Restarting

**Check logs:**
```bash
docker-compose logs <service-name>
```

**Common causes:**
- Out of memory: Increase Docker memory limit
- Port conflicts: Check if ports are available
- Configuration error: Verify `docker-compose.yml` syntax

---

## Next Steps

### 1. Explore the API

Read the [README.md](./README.md) for complete API documentation including:
- All available endpoints
- Request/response examples
- Business metrics
- Observability features

### 2. Learn Observability

Follow the observability guides:
- [Logs with Loki](./README.md#1-logs-loki--promtail)
- [Traces with Tempo](./README.md#2-trazas-tempo--opentelemetry)
- [Metrics with Prometheus](./README.md#3-métricas-prometheus--prom-client)

### 3. Experiment with Load Testing

Generate traffic and observe metrics:

```bash
# Generate 100 requests
for i in {1..100}; do
  curl -s http://localhost:3001/api/users > /dev/null
  echo "Request $i completed"
done
```

Then check:
- Grafana dashboards for metrics visualization
- Loki for request logs
- Tempo for distributed traces

### 4. Understand the Architecture

Read [ARCHITECTURE.md](./ARCHITECTURE.md) to understand:
- System design
- Component interactions
- Data flow
- Best practices

### 5. Customize and Extend

Modify the code to learn:
- Add new API endpoints
- Create custom metrics
- Add business logic
- Implement new observability features

---

## Stopping and Cleaning Up

### Stop All Services (Keep Data)

```bash
docker-compose stop
```

Restart later with:
```bash
docker-compose start
```

### Stop and Remove Containers (Keep Data)

```bash
docker-compose down
```

Data persists in Docker volumes. Restart with:
```bash
docker-compose up -d
```

### Complete Cleanup (Remove Everything)

```bash
# Stop and remove containers, networks, and volumes
docker-compose down -v

# Remove Docker images (optional, saves disk space)
docker rmi $(docker images 'api-example-node-js*' -q)
```

**Warning:** This deletes all data including database records, metrics, logs, and traces.

---

## Getting Help

### Check Logs

Always check logs first when troubleshooting:

```bash
# All services
docker-compose logs

# Specific service
docker-compose logs users-api
docker-compose logs postgres
docker-compose logs grafana

# Follow logs in real-time
docker-compose logs -f users-api
```

### Verify Service Health

```bash
# Check all containers
docker-compose ps

# Check specific service
docker inspect users-api
```

### Common Log Locations

- **API logs:** `docker logs users-api`
- **Database logs:** `docker logs users-db`
- **Grafana logs:** `docker logs grafana`
- **Prometheus logs:** `docker logs prometheus`

### Documentation Resources

- [README.md](./README.md) - Complete project documentation
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Technical architecture
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Detailed troubleshooting guide
- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)

---

## Success Checklist

Use this checklist to verify your installation:

- [ ] Docker and Docker Compose installed
- [ ] Project cloned successfully
- [ ] `docker-compose up -d` completed without errors
- [ ] All 8 containers running (`docker-compose ps`)
- [ ] API health check returns OK (`curl http://localhost:3001/health`)
- [ ] Can create users (`curl -X POST http://localhost:3001/api/users`)
- [ ] Can retrieve users (`curl http://localhost:3001/api/users`)
- [ ] Grafana accessible at http://localhost:3000
- [ ] Frontend accessible at http://localhost:4000
- [ ] Prometheus accessible at http://localhost:9090
- [ ] Can see metrics (`curl http://localhost:3001/metrics`)
- [ ] Can see logs in Grafana (Explore → Loki)
- [ ] Can see traces in Grafana (Explore → Tempo)

**If all items are checked, your installation is complete and working!** 🎉

---

## What's Next?

Now that your installation is complete, you're ready to:

1. **Learn by doing** - Use the API playground and observe the results
2. **Explore dashboards** - See real-time metrics and traces
3. **Understand observability** - Learn the three pillars (logs, metrics, traces)
4. **Experiment** - Modify the code and see the impact
5. **Practice** - Simulate real-world scenarios and learn to debug

**Welcome to API-USERS-TEST!** This platform is designed to help you master performance and observability through hands-on experience. Happy learning! 🚀
