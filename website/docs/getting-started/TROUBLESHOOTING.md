# Troubleshooting Guide - Learning-Performance-Observability-Stack

Comprehensive guide to diagnose and fix common issues with the Learning-Performance-Observability-Stack platform.

## Table of Contents

- [General Diagnostics](#general-diagnostics)
- [Docker Issues](#docker-issues)
- [API Issues](#api-issues)
- [Database Issues](#database-issues)
- [Observability Stack Issues](#observability-stack-issues)
- [Frontend Issues](#frontend-issues)
- [Network and Port Issues](#network-and-port-issues)
- [Performance Issues](#performance-issues)
- [Data Issues](#data-issues)
- [Advanced Debugging](#advanced-debugging)

---

## General Diagnostics

### Quick Health Check

Run this comprehensive health check to identify issues:

```bash
# Check if Docker is running
docker ps

# Check all services status
docker-compose ps

# Check API health
curl http://localhost:3001/health

# Check API readiness (includes DB)
curl http://localhost:3001/health/ready

# Check if all ports are accessible
curl -I http://localhost:3000  # Grafana
curl -I http://localhost:3001  # API
curl -I http://localhost:4000  # Frontend
curl -I http://localhost:9090  # Prometheus
```

### View All Logs

```bash
# All services (last 100 lines)
docker-compose logs --tail=100

# Specific service with timestamps
docker-compose logs --timestamps users-api

# Follow logs in real-time
docker-compose logs -f

# Filter logs for errors
docker-compose logs | grep -i error
```

### Check Resource Usage

```bash
# Linux/macOS
docker stats

# Check disk space
df -h

# Check Docker disk usage
docker system df
```

---

## Docker Issues

### Issue: Docker Daemon Not Running

**Symptoms:**
```
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Solutions:**

**Windows/macOS:**
1. Launch Docker Desktop application
2. Wait for Docker icon in system tray to show "Docker Desktop is running"
3. Try command again

**Linux:**
```bash
# Start Docker service
sudo systemctl start docker

# Enable Docker to start on boot
sudo systemctl enable docker

# Check status
sudo systemctl status docker
```

---

### Issue: Permission Denied (Linux)

**Symptoms:**
```
Got permission denied while trying to connect to the Docker daemon socket
```

**Solutions:**

```bash
# Add your user to docker group
sudo usermod -aG docker $USER

# Apply changes (choose one):
# Option 1: Log out and log back in
# Option 2: Run this command
newgrp docker

# Option 3: Reboot system
sudo reboot

# Verify
docker ps
```

---

### Issue: Docker Compose Command Not Found

**Symptoms:**
```
docker-compose: command not found
```

**Solutions:**

**Docker Compose V2 (Built-in to Docker):**
```bash
# Use 'docker compose' instead of 'docker-compose'
docker compose up -d
docker compose ps
docker compose logs
```

**Install Docker Compose V1 (Legacy):**
```bash
# Linux
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify
docker-compose --version
```

---

### Issue: Out of Disk Space

**Symptoms:**
```
no space left on device
```

**Solutions:**

```bash
# Check Docker disk usage
docker system df

# Remove unused containers, images, and volumes
docker system prune -a --volumes

# Remove only stopped containers and unused images
docker system prune

# Remove specific old images
docker images
docker rmi <image-id>

# Remove unused volumes
docker volume ls
docker volume rm <volume-name>
```

---

### Issue: Container Exits Immediately

**Symptoms:**
- `docker-compose ps` shows service as "Exited"
- Service keeps restarting

**Diagnosis:**
```bash
# Check exit code and error
docker-compose ps
docker-compose logs <service-name>

# Check last 50 lines
docker-compose logs --tail=50 <service-name>

# Inspect container
docker inspect <container-name>
```

**Common Causes:**

1. **Configuration Error**
   ```bash
   # Validate docker-compose.yml syntax
   docker-compose config
   ```

2. **Port Conflict**
   ```bash
   # Check if port is in use
   lsof -i :3001  # Linux/macOS
   netstat -ano | findstr :3001  # Windows
   ```

3. **Missing Environment Variables**
   ```bash
   # Check environment variables
   docker-compose config | grep environment
   ```

4. **Out of Memory**
   - Increase Docker Desktop memory limit
   - Settings → Resources → Memory (4 GB minimum)

---

## API Issues

### Issue: API Not Starting

**Symptoms:**
```
users-api container exits with code 1
```

**Diagnosis:**
```bash
# Check API logs
docker-compose logs users-api

# Check if database is ready
docker-compose logs users-db | grep "ready to accept connections"

# Test database connection
docker exec users-db pg_isready -U postgres
```

**Solutions:**

1. **Database Not Ready**
   ```bash
   # Wait for database to be healthy
   docker-compose ps users-db
   # Should show "healthy" status

   # Restart API after database is ready
   docker-compose restart users-api
   ```

2. **Environment Variables Missing**
   ```bash
   # Check environment in docker-compose.yml
   docker-compose config

   # Verify database connection settings
   docker-compose exec users-api env | grep DB_
   ```

3. **Node Modules Issue**
   ```bash
   # Rebuild API container
   docker-compose build --no-cache users-api
   docker-compose up -d users-api
   ```

---

### Issue: API Returns 500 Internal Server Error

**Diagnosis:**
```bash
# Check API logs for stack traces
docker-compose logs users-api | grep -A 20 "Error"

# Test specific endpoint
curl -v http://localhost:3001/api/users

# Check database connection
curl http://localhost:3001/health/ready
```

**Common Causes:**

1. **Database Connection Failed**
   ```json
   {
     "status": "ERROR",
     "checks": {
       "database": "disconnected"
     }
   }
   ```

   **Solution:**
   ```bash
   # Restart database
   docker-compose restart users-db

   # Wait 10 seconds
   sleep 10

   # Restart API
   docker-compose restart users-api
   ```

2. **Database Schema Not Initialized**
   ```bash
   # Check if tables exist
   docker exec -it users-db psql -U postgres -d usersdb -c "\dt"

   # If empty, reinitialize
   docker-compose down -v
   docker-compose up -d
   ```

---

### Issue: API Responds Slowly

**Diagnosis:**
```bash
# Test response time
time curl http://localhost:3001/api/users

# Check event loop lag
curl http://localhost:3001/debug/eventloop

# Check memory usage
curl http://localhost:3001/debug/memory

# Check Docker stats
docker stats users-api
```

**Solutions:**

1. **High Memory Usage**
   ```bash
   # Check memory
   curl http://localhost:3001/debug/memory

   # Restart API to clear memory
   docker-compose restart users-api
   ```

2. **Database Slow Queries**
   ```bash
   # Check Prometheus for slow queries
   # Open: http://localhost:9090
   # Query: histogram_quantile(0.95, rate(db_query_duration_seconds_bucket[5m]))

   # Check database connections
   docker exec users-db psql -U postgres -d usersdb -c "SELECT count(*) FROM pg_stat_activity;"
   ```

3. **Insufficient Docker Resources**
   - Increase Docker Desktop CPU/Memory allocation
   - Settings → Resources → Advanced

---

## Database Issues

### Issue: Database Connection Refused

**Symptoms:**
```
Error: connect ECONNREFUSED
```

**Diagnosis:**
```bash
# Check if database is running
docker-compose ps users-db

# Check database logs
docker-compose logs users-db

# Test database connectivity
docker exec users-db pg_isready -U postgres
```

**Solutions:**

1. **Database Not Running**
   ```bash
   docker-compose start users-db
   docker-compose ps users-db
   ```

2. **Database Starting**
   ```bash
   # Wait for healthy status
   watch -n 1 'docker-compose ps users-db'
   # Wait until STATUS shows "healthy"
   ```

3. **Port Conflict**
   ```bash
   # Check if port 5434 is available
   lsof -i :5434  # Linux/macOS
   netstat -ano | findstr :5434  # Windows
   ```

---

### Issue: Database Authentication Failed

**Symptoms:**
```
FATAL: password authentication failed for user "postgres"
```

**Solution:**
```bash
# Verify credentials in docker-compose.yml
cat docker-compose.yml | grep -A 5 postgres:

# Expected:
# POSTGRES_USER: postgres
# POSTGRES_PASSWORD: postgres
# POSTGRES_DB: usersdb

# Recreate database with correct credentials
docker-compose down -v
docker-compose up -d
```

---

### Issue: Tables Not Found

**Symptoms:**
```
ERROR: relation "users" does not exist
```

**Diagnosis:**
```bash
# Check if init script ran
docker-compose logs users-db | grep "init.sql"

# List tables
docker exec -it users-db psql -U postgres -d usersdb -c "\dt"
```

**Solutions:**

1. **Init Script Didn't Run**
   ```bash
   # Recreate database
   docker-compose down -v
   docker-compose up -d

   # Verify tables exist
   docker exec -it users-db psql -U postgres -d usersdb -c "\dt"
   # Should show: users, addresses
   ```

2. **Manual Schema Creation**
   ```bash
   # Connect to database
   docker exec -it users-db psql -U postgres -d usersdb

   # Run init script manually
   \i /docker-entrypoint-initdb.d/init.sql

   # Verify
   \dt
   \q
   ```

---

## Observability Stack Issues

### Issue: No Logs in Loki

**Symptoms:**
- Grafana Explore → Loki shows "No data"

**Diagnosis:**
```bash
# Check Promtail is running
docker-compose ps promtail

# Check Promtail logs
docker-compose logs promtail | grep -i error

# Check Loki is running
docker-compose ps loki

# Test Loki API
curl http://localhost:3100/ready
```

**Solutions:**

1. **Promtail Not Running**
   ```bash
   docker-compose restart promtail
   docker-compose logs -f promtail
   ```

2. **No Traffic to Generate Logs**
   ```bash
   # Generate API traffic
   for i in {1..10}; do
     curl http://localhost:3001/api/users
   done

   # Wait 10 seconds for logs to appear
   ```

3. **Incorrect Time Range in Grafana**
   - Change time range to "Last 5 minutes"
   - Click "Run query" button

4. **Docker Socket Permission Issue**
   ```bash
   # Check Promtail has access to Docker socket
   docker-compose logs promtail | grep "permission denied"

   # Fix (Linux only):
   sudo chmod 666 /var/run/docker.sock
   ```

---

### Issue: No Traces in Tempo

**Symptoms:**
- Grafana Explore → Tempo shows no traces

**Diagnosis:**
```bash
# Check Tempo is running
docker-compose ps tempo

# Check Tempo logs
docker-compose logs tempo | grep -i error

# Test Tempo API
curl http://localhost:3200/ready

# Check if API is sending traces
docker-compose logs users-api | grep -i "trace\|otlp"
```

**Solutions:**

1. **Tempo Not Ready**
   ```bash
   # Restart Tempo
   docker-compose restart tempo

   # Wait for ready
   curl http://localhost:3200/ready
   # Should return: {"status":"ready"}
   ```

2. **API Not Sending Traces**
   ```bash
   # Check OpenTelemetry environment variables
   docker-compose exec users-api env | grep OTEL

   # Verify endpoint is correct:
   # OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318

   # Restart API
   docker-compose restart users-api
   ```

3. **Sampling Rate Too Low**
   ```bash
   # Check sampling rate
   docker-compose exec users-api env | grep TRACE_SAMPLING_RATE

   # Temporarily increase to 100%
   # Edit docker-compose.yml:
   # TRACE_SAMPLING_RATE: "1.0"

   docker-compose up -d users-api
   ```

---

### Issue: No Metrics in Prometheus

**Symptoms:**
- Prometheus shows no data
- Grafana dashboards are empty

**Diagnosis:**
```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Check if API exposes metrics
curl http://localhost:3001/metrics

# Check Prometheus logs
docker-compose logs prometheus | grep -i error
```

**Solutions:**

1. **API Target Down**
   ```bash
   # Open Prometheus targets page
   # http://localhost:9090/targets

   # If "users-api" is DOWN:
   docker-compose restart users-api

   # Wait 30 seconds and refresh
   ```

2. **Scrape Configuration Issue**
   ```bash
   # Verify prometheus.yml
   cat observability/prometheus.yml

   # Check job configuration:
   # - job_name: 'users-api'
   #   static_configs:
   #   - targets: ['users-api:3001']

   # Reload configuration
   docker-compose restart prometheus
   ```

3. **Metrics Endpoint Not Responding**
   ```bash
   # Test from within Docker network
   docker-compose exec prometheus wget -O- http://users-api:3001/metrics
   ```

---

### Issue: Grafana Datasources Not Working

**Symptoms:**
- "Data source not found" error
- Cannot query Loki/Tempo/Prometheus

**Solutions:**

1. **Datasources Not Provisioned**
   ```bash
   # Check datasources file
   cat observability/grafana-datasources.yml

   # Restart Grafana
   docker-compose restart grafana

   # Check logs
   docker-compose logs grafana | grep -i "provisioning"
   ```

2. **Datasource URL Incorrect**
   ```bash
   # In Grafana: Configuration → Data Sources
   # Verify URLs:
   # - Loki: http://loki:3100
   # - Tempo: http://tempo:3200
   # - Prometheus: http://prometheus:9090

   # Test connection for each datasource
   ```

3. **Services Not Reachable from Grafana**
   ```bash
   # Test connectivity from Grafana container
   docker-compose exec grafana wget -O- http://loki:3100/ready
   docker-compose exec grafana wget -O- http://tempo:3200/ready
   docker-compose exec grafana wget -O- http://prometheus:9090/-/healthy
   ```

---

## Frontend Issues

### Issue: Frontend Not Accessible

**Symptoms:**
```
ERR_CONNECTION_REFUSED when accessing http://localhost:4000
```

**Diagnosis:**
```bash
# Check if frontend container is running
docker-compose ps users-front

# Check frontend logs
docker-compose logs users-front

# Check if port is bound
lsof -i :4000  # Linux/macOS
netstat -ano | findstr :4000  # Windows
```

**Solutions:**

1. **Container Not Running**
   ```bash
   docker-compose start users-front
   docker-compose ps users-front
   ```

2. **Build Failed**
   ```bash
   # Rebuild frontend
   docker-compose build --no-cache users-front
   docker-compose up -d users-front

   # Check build logs
   docker-compose logs users-front
   ```

3. **Port Conflict**
   ```bash
   # Change port in docker-compose.yml
   # users-front:
   #   ports:
   #     - "4001:80"  # Changed from 4000 to 4001

   docker-compose up -d users-front
   ```

---

### Issue: Frontend Shows API Connection Error

**Symptoms:**
- Frontend loads but cannot fetch data
- Console shows CORS or network errors

**Solutions:**

1. **API Not Running**
   ```bash
   # Verify API is accessible
   curl http://localhost:3001/health

   # If not, restart API
   docker-compose restart users-api
   ```

2. **CORS Issue**
   ```bash
   # Check API logs for CORS errors
   docker-compose logs users-api | grep -i cors

   # Verify API allows frontend origin
   ```

3. **Wrong API URL in Frontend**
   ```bash
   # Check frontend environment
   docker-compose exec users-front env | grep API
   ```

---

## Network and Port Issues

### Issue: Port Already in Use

**Symptoms:**
```
Bind for 0.0.0.0:3000 failed: port is already allocated
```

**Diagnosis:**

**Linux/macOS:**
```bash
# Find process using port
lsof -i :3000

# Output example:
# COMMAND   PID   USER   FD   TYPE  DEVICE  SIZE/OFF  NODE  NAME
# node    12345  user   23u  IPv4  123456  0t0       TCP   *:3000 (LISTEN)
```

**Windows:**
```powershell
# Find process using port
netstat -ano | findstr :3000

# Output example:
# TCP    0.0.0.0:3000    0.0.0.0:0    LISTENING    12345
```

**Solutions:**

1. **Kill Conflicting Process**
   ```bash
   # Linux/macOS
   kill -9 <PID>

   # Windows
   taskkill /PID <PID> /F
   ```

2. **Change Port in docker-compose.yml**
   ```yaml
   services:
     grafana:
       ports:
         - "3030:3000"  # Changed external port to 3030
   ```

   Then access Grafana at http://localhost:3030

3. **Stop Other Docker Containers**
   ```bash
   # List all running containers
   docker ps

   # Stop conflicting container
   docker stop <container-name>
   ```

---

### Issue: Cannot Access Services from Host

**Symptoms:**
- Services work within Docker but not from host machine
- `curl localhost:3001` fails but `docker exec` works

**Diagnosis:**
```bash
# Check port mappings
docker-compose ps

# Test from inside Docker network
docker-compose exec users-api wget -O- http://localhost:3001/health

# Check firewall rules (Linux)
sudo iptables -L
```

**Solutions:**

1. **Port Not Mapped**
   ```bash
   # Verify ports in docker-compose.yml
   cat docker-compose.yml | grep -A 2 "ports:"

   # Should see: "3001:3001" for API

   # Recreate containers if ports were changed
   docker-compose down
   docker-compose up -d
   ```

2. **Firewall Blocking**
   ```bash
   # Linux - Allow port
   sudo ufw allow 3001/tcp

   # Windows - Check Windows Firewall settings
   # macOS - Check System Preferences → Security
   ```

3. **Docker Network Issue**
   ```bash
   # Recreate network
   docker-compose down
   docker network prune
   docker-compose up -d
   ```

---

## Performance Issues

### Issue: High Memory Usage

**Diagnosis:**
```bash
# Check container memory usage
docker stats --no-stream

# Check Node.js memory
curl http://localhost:3001/debug/memory
```

**Solutions:**

1. **Increase Docker Memory Limit**
   - Docker Desktop → Settings → Resources
   - Set memory to at least 4 GB

2. **Restart API to Clear Memory**
   ```bash
   docker-compose restart users-api
   ```

3. **Check for Memory Leaks**
   ```bash
   # Take heap snapshot
   curl http://localhost:3001/debug/heapsnapshot

   # Analyze in Chrome DevTools
   ```

---

### Issue: High CPU Usage

**Diagnosis:**
```bash
# Check CPU usage
docker stats

# Check event loop lag
curl http://localhost:3001/debug/eventloop
```

**Solutions:**

1. **Increase Docker CPU Allocation**
   - Docker Desktop → Settings → Resources
   - Set CPUs to 2 or more

2. **Profile CPU Usage**
   ```bash
   # Start CPU profiler
   curl http://localhost:3001/debug/profile/start

   # Generate load for 30 seconds
   for i in {1..100}; do curl http://localhost:3001/api/users; done

   # Stop profiler
   curl http://localhost:3001/debug/profile/stop

   # Analyze .cpuprofile in Chrome DevTools
   ```

---

## Data Issues

### Issue: No Data in Database

**Diagnosis:**
```bash
# Check user count
curl http://localhost:3001/api/users

# Connect to database
docker exec -it users-db psql -U postgres -d usersdb

# Query tables
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM addresses;
```

**Solutions:**

1. **Create Sample Data**
   ```bash
   # Create 10 users
   for i in {1..10}; do
     curl -X POST http://localhost:3001/api/users
   done

   # Verify
   curl http://localhost:3001/api/users
   ```

2. **Reinitialize Database**
   ```bash
   # This will delete all data!
   docker-compose down -v
   docker-compose up -d

   # Recreate sample data
   for i in {1..10}; do
     curl -X POST http://localhost:3001/api/users
   done
   ```

---

### Issue: Database Data Corrupted

**Symptoms:**
- Queries return unexpected results
- Foreign key violations

**Solution:**
```bash
# Complete reset (WARNING: Deletes all data)
docker-compose down -v

# Remove PostgreSQL volume
docker volume rm api-example-node-js_postgres_data

# Start fresh
docker-compose up -d

# Wait for initialization
sleep 30

# Verify tables
docker exec -it users-db psql -U postgres -d usersdb -c "\dt"

# Create sample data
for i in {1..10}; do
  curl -X POST http://localhost:3001/api/users
done
```

---

## Advanced Debugging

### Debugging Inside Containers

```bash
# Execute shell inside container
docker-compose exec users-api sh

# Inside container:
# - Check environment: env
# - Check processes: ps aux
# - Check network: netstat -tlnp
# - Check files: ls -la
# - Test endpoints: wget http://localhost:3001/health
```

### Network Debugging

```bash
# Test connectivity between containers
docker-compose exec users-api ping postgres
docker-compose exec users-api wget -O- http://tempo:4318

# Inspect Docker network
docker network ls
docker network inspect api-example-node-js_observability

# Check DNS resolution
docker-compose exec users-api nslookup postgres
```

### Log Analysis

```bash
# Search logs for specific errors
docker-compose logs | grep -i "error\|exception\|failed"

# Export logs to file
docker-compose logs > logs.txt

# Filter logs by time
docker-compose logs --since 10m

# Count errors
docker-compose logs | grep -i error | wc -l
```

### Complete System Reset

If all else fails, perform a complete reset:

```bash
# Stop all containers
docker-compose down -v

# Remove all project containers
docker ps -a | grep "api-example-node-js" | awk '{print $1}' | xargs docker rm

# Remove all project images
docker images | grep "api-example-node-js" | awk '{print $3}' | xargs docker rmi

# Remove all project volumes
docker volume ls | grep "api-example-node-js" | awk '{print $2}' | xargs docker volume rm

# Clean Docker system
docker system prune -a --volumes

# Start fresh
docker-compose up -d

# Wait for initialization
sleep 60

# Verify
docker-compose ps
curl http://localhost:3001/health
```

---

## Getting More Help

### Before Asking for Help

Collect this information:

1. **System Information:**
   ```bash
   docker --version
   docker-compose --version
   uname -a  # Linux/macOS
   systeminfo  # Windows
   ```

2. **Service Status:**
   ```bash
   docker-compose ps
   ```

3. **Recent Logs:**
   ```bash
   docker-compose logs --tail=100 > all-logs.txt
   ```

4. **Error Messages:**
   - Copy exact error message
   - Include stack trace if available

### Support Resources

- [Installation Guide](./INSTALLATION.md)
- [Quick Start Guide](./QUICK_START.md)
- [Main Documentation](./README.md)
- [Architecture Guide](./ARCHITECTURE.md)
- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)

---

## Troubleshooting Checklist

Use this checklist when diagnosing issues:

- [ ] Docker is running
- [ ] Docker Compose is available
- [ ] All containers are running (`docker-compose ps`)
- [ ] No port conflicts
- [ ] Sufficient disk space (> 2 GB free)
- [ ] Sufficient RAM allocated to Docker (> 4 GB)
- [ ] Database is healthy
- [ ] API responds to `/health`
- [ ] API responds to `/health/ready`
- [ ] Can create users (`POST /api/users`)
- [ ] Can retrieve users (`GET /api/users`)
- [ ] Grafana is accessible
- [ ] Prometheus shows API target as UP
- [ ] Logs appear in Loki
- [ ] Traces appear in Tempo

If all items check out, your system should be working correctly!
