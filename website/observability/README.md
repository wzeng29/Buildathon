# Stack de Observabilidad - Users API

Documentación completa del sistema de observabilidad enterprise-grade basado en Grafana Stack (LGTM).

> **Nota:** Este stack ha evolucionado a través de 3 fases. Ver [../OBSERVABILITY-EVOLUTION.md](../OBSERVABILITY-EVOLUTION.md) para detalles de la evolución.

## Tabla de Contenidos

- [Visión General](#visión-general)
- [Archivos de Configuración](#archivos-de-configuración)
- [Componentes del Stack](#componentes-del-stack)
- [Los 3 Pilares de Observabilidad](#los-3-pilares-de-observabilidad)
- [Características Avanzadas](#características-avanzadas)
- [Queries Útiles](#queries-útiles)
- [Dashboard de Monitoreo](#dashboard-de-monitoreo)
- [Alerting y SLO](#alerting-y-slo)
- [Troubleshooting](#troubleshooting)
- [URLs de Acceso](#urls-de-acceso)

---

## Visión General

### Stack Completo (Grafana LGTM)

```
┌──────────────────────────────────────────────────────────┐
│                    Users API                              │
│  - OpenTelemetry (Traces)                                │
│  - Structured Logging (Logs)                             │
│  - prom-client (Metrics)                                 │
│  - SLI/SLO Tracking                                      │
└────────────┬──────────────┬──────────────┬───────────────┘
             │              │              │
     OTLP    │      /metrics│      stdout  │
             │              │              │
        ┌────▼────┐    ┌────▼────┐    ┌───▼──────┐
        │  Tempo  │    │Prometheus│   │ Promtail │
        │ (Traces)│    │(Metrics) │   │  (Logs)  │
        └────┬────┘    └────┬─────┘   └────┬─────┘
             │              │               │
             │              │               ▼
             │              │          ┌────────┐
             │              │          │  Loki  │
             │              │          │ (Logs) │
             │              │          └────┬───┘
             │              │               │
             └──────────────┼───────────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │   Grafana   │
                     │Visualización│
                     └─────────────┘
```

### Capacidades Implementadas

#### Fase 1 - Foundation
- ✅ Request ID y Correlation ID
- ✅ Health Checks (Liveness/Readiness)
- ✅ Métricas de negocio
- ✅ Error tracking estructurado

#### Fase 2 - Advanced
- ✅ Database Query Observability
- ✅ Custom Spans (OpenTelemetry)
- ✅ Structured Logging (5 niveles)
- ✅ Sistema de alerting (10 reglas)

#### Fase 3 - Enterprise
- ✅ SLI/SLO con error budgets (4 SLIs)
- ✅ Trace sampling inteligente (10% configurable)
- ✅ Context propagation mejorado
- ✅ Continuous profiling (5 endpoints)

---

## Archivos de Configuración

### Dashboards
- **`dashboard-users-api-monitoring.json`** - Dashboard de Grafana con visualizaciones en tiempo real

### Datasources
- **`grafana-datasources.yml`** - Configuración automática de datasources
  - Tempo (trazas)
  - Loki (logs) con correlación automática
  - Prometheus (métricas) como default

### Servicios Backend
- **`tempo.yaml`** - Grafana Tempo (almacenamiento de trazas)
- **`loki.yaml`** - Grafana Loki (almacenamiento de logs)
- **`prometheus.yml`** - Prometheus (scraping de métricas)
- **`promtail.yaml`** - Promtail (recolección de logs desde Docker)

### Alerting y SLO
- **`alert-rules.yml`** - 10 reglas de alerting básicas (Fase 2)
- **`slo-rules.yml`** - 14 recording rules + 6 alerting rules SLO (Fase 3)

---

## Componentes del Stack

### 1. OpenTelemetry (Instrumentación)

**Ubicación:** `../src/tracing.js`

**Funciones:**
- Auto-instrumentación de HTTP requests (Express)
- Auto-instrumentación de queries PostgreSQL
- Exportación OTLP a Tempo
- Trace sampling inteligente (10% default)
- Resource attributes (service.name, version, environment)

**Configuración:**
```javascript
// Sampling configurable
TRACE_SAMPLING_RATE=0.1  // 10% de traces

// Resource attributes
service.name: "users-api-microservice"
service.version: "1.0.0"
deployment.environment: "production"
```

**Características Fase 3:**
- ParentBasedSampler para distributed tracing
- Errores 5xx marcados con `force.sampling`
- Response hooks para sampling prioritario

---

### 2. Grafana Tempo (Trazas)

**Puertos:**
- 3200 - API de Tempo
- 4317 - OTLP gRPC
- 4318 - OTLP HTTP (usado por la API)

**Función:** Almacenamiento de trazas distribuidas

**Backend:** Local filesystem (producción: S3, GCS)

**URL:** http://localhost:3200

**Anatomía de una Traza:**
```
Trace ID: a1b2c3d4e5f6g7h8 (duración: 25ms)
│
├─ Span: POST /api/users (25ms)
│  ├─ Span: INSERT addresses (3ms)
│  ├─ Span: INSERT users (2ms)
│  └─ Span: SELECT user (1ms)
```

---

### 3. Grafana Loki (Logs)

**Puerto:** 3100

**Función:** Agregación y almacenamiento de logs estructurados

**Schema:** v13 con TSDB

**URL:** http://localhost:3100

**Formato de logs:**
```json
{
  "level": "info",
  "timestamp": "2025-11-26T12:00:00.000Z",
  "method": "POST",
  "path": "/api/users",
  "statusCode": 201,
  "duration": "25ms",
  "traceId": "a1b2c3d4e5f6g7h8",
  "spanId": "1234567890abcdef",
  "requestId": "uuid-v4",
  "correlationId": "uuid-v4",
  "tenant.id": "tenant-123",      // Fase 3
  "user.id": "user-456"            // Fase 3
}
```

---

### 4. Prometheus (Métricas)

**Puerto:** 9090

**Función:** Scraping y almacenamiento de métricas

**Scrape interval:** 15 segundos

**Targets:** API en http://api:3001/metrics

**URL:** http://localhost:9090

**Métricas Implementadas:**

#### HTTP Metrics
```promql
http_requests_total{method, route, status_code}
http_request_duration_seconds{method, route, status_code}
```

#### Business Metrics (Fase 1)
```promql
users_created_total{gender}
users_updated_total
users_deleted_total
db_connections_active
api_errors_total{error_type, endpoint, status_code}
```

#### Database Metrics (Fase 2)
```promql
db_queries_total{query_type, table, status}
db_query_duration_seconds{query_type, table, status}
```

#### SLI/SLO Metrics (Fase 3)
```promql
# SLIs
sli:availability:ratio_rate5m
sli:latency:ratio_rate5m
sli:database:success_ratio_rate5m

# Error Budgets
slo:availability:error_budget_remaining
slo:latency:error_budget_remaining

# Burn Rates
slo:availability:burn_rate_1h
slo:latency:burn_rate_1h

# Compliance
slo:availability:compliance
slo:latency:compliance
```

#### Node.js Default Metrics
```promql
process_resident_memory_bytes
nodejs_heap_size_total_bytes
nodejs_eventloop_lag_seconds
process_cpu_user_seconds_total
```

**Total:** 30+ métricas activas

---

### 5. Promtail (Recolector de Logs)

**Puerto:** 9080

**Función:** Recolecta logs de contenedores Docker y los envía a Loki

**Descubrimiento:** Automático vía Docker socket (`/var/run/docker.sock`)

**Targets:** Lee logs desde `/var/lib/docker/containers`

---

### 6. Grafana (Visualización)

**Puerto:** 3000

**Credenciales:**
- Usuario: `admin`
- Contraseña: `admin`

**URL:** http://localhost:3000

**Datasources Configurados:**
- **Tempo** - Trazas distribuidas
- **Loki** - Logs con derivedFields para correlación
- **Prometheus** - Métricas (default)

**Dashboards:**
- Users API Monitoring - 5 paneles con auto-refresh

---

## Los 3 Pilares de Observabilidad

### 1. Logs (Structured JSON)

**Implementación:** `../src/logger.js` (Fase 2), `../src/server.js`

**Características:**
- 5 niveles jerárquicos: DEBUG, INFO, WARN, ERROR, FATAL
- Filtrado por nivel via `LOG_LEVEL`
- Contexto automático (traceId, spanId, requestId)
- Child loggers con propagación de contexto
- Helper `logRequest()` con nivel automático

**Ejemplo de uso:**
```javascript
const logger = require('./logger');

logger.info('User created', { userId: 123 });
logger.error('Database error', { error: err.message });

// Child logger con contexto
const requestLogger = logger.child({
  requestId: req.id,
  correlationId: req.correlationId
});
```

**Queries en Loki:**
```logql
# Todos los logs
{container="users-api"}

# Solo errores
{container="users-api"} | json | level="error"

# Por request ID
{container="users-api"} | json | requestId="abc-123"

# Slow queries
{container="users-api"} | json | message=~"Slow.*query"
```

---

### 2. Traces (OpenTelemetry)

**Implementación:** `../src/tracing.js`

**Auto-instrumentation:**
- Express HTTP server
- PostgreSQL client
- HTTP client (fetch, axios)

**Custom Spans (Fase 2):**
```javascript
const tracer = require('./tracing').tracer;

const span = tracer.startSpan('transaction.create_user');
span.setAttribute('user.gender', 'female');
span.setAttribute('user.country', 'Brazil');
// ... business logic ...
span.end();
```

**Queries en Tempo:**
```
# Todas las trazas del servicio
{resource.service.name="users-api-microservice"}

# Por endpoint
{resource.service.name="users-api-microservice" && name=~"POST /api/users"}

# Por duración
{resource.service.name="users-api-microservice" && duration > 100ms}

# Por Trace ID
{trace.id="a1b2c3d4e5f6g7h8"}
```

---

### 3. Metrics (Prometheus)

**Implementación:** `../src/server.js`

**Tipos de métricas:**

**Counter** - Eventos acumulativos:
```javascript
usersCreatedTotal.inc({ gender: 'female' });
```

**Histogram** - Distribución de valores:
```javascript
httpRequestDuration.observe({ method, route }, duration);
```

**Gauge** - Valores instantáneos:
```javascript
dbConnectionsActive.set(pool.totalCount);
```

**Queries en Prometheus:**
```promql
# Request rate
rate(http_requests_total[5m])

# Latency P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Error rate
rate(api_errors_total[5m]) / rate(http_requests_total[5m])

# SLI Availability
sli:availability:ratio_rate5m

# Error Budget
slo:availability:error_budget_remaining
```

---

## Características Avanzadas

### Correlación Logs ↔ Traces

**Configuración en Grafana** (`grafana-datasources.yml`):
```yaml
derivedFields:
  - datasourceUid: tempo
    matcherRegex: "traceId\":\"([a-f0-9]+)\""
    name: TraceID
    url: "${__value.raw}"
```

**Flujo de correlación:**
1. Usuario ve log en Loki
2. Click en log → Grafana extrae traceId vía regex
3. Genera link automático a Tempo
4. Usuario ve traza completa con timeline

**Navegación bidireccional:**
- Log → Trace (click en link "Tempo")
- Trace → Log (copiar traceId y buscar en Loki)

---

### Database Query Observability (Fase 2)

**Implementación:** `../src/db-wrapper.js`

**Características:**
- Wrapper automático de todas las queries
- Métricas por tipo (SELECT, INSERT, UPDATE, DELETE)
- Métricas por tabla (users, addresses)
- Histogram de latencia
- Detección de slow queries (> 100ms)

**Queries instrumentadas:**
```sql
-- Automáticamente instrumentado
SELECT * FROM users WHERE id = $1;
-- Genera métrica: db_queries_total{query_type="SELECT", table="users"}
-- Genera métrica: db_query_duration_seconds{query_type="SELECT", table="users"}
```

**Queries en Prometheus:**
```promql
# Queries por segundo por tipo
rate(db_queries_total{query_type="SELECT"}[5m])

# Latencia P95 de SELECTs
histogram_quantile(0.95, rate(db_query_duration_seconds_bucket{query_type="SELECT"}[5m]))

# Tasa de errores de DB
rate(db_queries_total{status="error"}[5m])
```

---

### Context Propagation (Fase 3)

**Implementación:** Middleware en `../src/server.js`

**Atributos propagados:**
- `request.id` - UUID único del request
- `correlation.id` - Para correlación cross-service
- `tenant.id` - Multi-tenancy (desde header `x-tenant-id`)
- `user.id` - User tracking (desde header `x-user-id`)
- `deployment.environment` - Ambiente (NODE_ENV)

**Uso:**
```bash
curl -H "x-tenant-id: tenant-123" \
     -H "x-user-id: user-456" \
     http://localhost:3001/api/users
```

**Visualización:**
Los atributos aparecen en:
- Spans de Tempo
- Logs de Loki
- Facilita debugging por tenant/usuario

---

### Continuous Profiling (Fase 3)

**Endpoints disponibles:**

1. **GET /debug/memory** - Estadísticas de memoria
```bash
curl http://localhost:3001/debug/memory
```

2. **GET /debug/heapsnapshot** - Genera heap snapshot
```bash
curl http://localhost:3001/debug/heapsnapshot
# Analizar en Chrome DevTools → Memory
```

3. **GET /debug/profile/start** - Inicia CPU profiler
4. **GET /debug/profile/stop** - Detiene y genera .cpuprofile
```bash
curl http://localhost:3001/debug/profile/start
# ... generar tráfico ...
curl http://localhost:3001/debug/profile/stop
# Analizar en Chrome DevTools → Performance
```

5. **GET /debug/eventloop** - Event loop utilization
```bash
curl http://localhost:3001/debug/eventloop
```

⚠️ **Seguridad:** En producción, proteger con autenticación o deshabilitar.

---

## Queries Útiles

### Loki (Logs)

```logql
# Ver todos los logs de la API
{container="users-api"}

# Solo requests a endpoints de API
{container="users-api"} | json | path=~"/api/.*"

# Solo errores (4xx/5xx)
{container="users-api"} | json | statusCode >= 400

# Requests por método
{container="users-api"} | json | method="POST"

# Requests lentos (>100ms)
{container="users-api"} | json | duration=~".*[1-9][0-9]{2,}ms"

# Por Trace ID
{container="users-api"} | json | traceId="<TRACE_ID>"

# Por Request ID
{container="users-api"} | json | requestId="<REQUEST_ID>"

# Por Tenant
{container="users-api"} | json | tenant_id="tenant-123"

# Slow database queries
{container="users-api"} | json | message=~"Slow database query"
```

---

### Tempo (Traces)

```
# Todas las trazas del servicio
{resource.service.name="users-api-microservice"}

# Por endpoint específico
{resource.service.name="users-api-microservice" && name=~"GET /api/users"}

# Por duración (>100ms)
{resource.service.name="users-api-microservice" && duration > 100ms}

# Por Trace ID
{trace.id="<TRACE_ID>"}

# Por tenant (Fase 3)
{resource.service.name="users-api-microservice" && tenant.id="tenant-123"}
```

---

### Prometheus (Metrics)

#### HTTP Metrics
```promql
# Request rate por segundo
rate(http_requests_total[1m])

# Latencia promedio
rate(http_request_duration_seconds_sum[1m]) / rate(http_request_duration_seconds_count[1m])

# Latencia P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))

# Total por endpoint
sum by (route) (http_requests_total)

# Error rate
sum(rate(http_requests_total{status_code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
```

#### Business Metrics
```promql
# Tasa de creación de usuarios
rate(users_created_total[5m])

# Total por género
sum by (gender) (users_created_total)

# Proporción por género
sum by (gender) (users_created_total) / sum(users_created_total)
```

#### Database Metrics
```promql
# Queries por segundo
rate(db_queries_total[5m])

# Latencia promedio de SELECTs
rate(db_query_duration_seconds_sum{query_type="SELECT"}[5m]) / rate(db_query_duration_seconds_count{query_type="SELECT"}[5m])

# P95 de queries
histogram_quantile(0.95, rate(db_query_duration_seconds_bucket[5m]))
```

#### SLI/SLO Metrics
```promql
# SLI de Availability
sli:availability:ratio_rate5m

# Error Budget restante
slo:availability:error_budget_remaining

# Burn Rate
slo:availability:burn_rate_1h

# Compliance con SLO
slo:availability:compliance
```

---

## Dashboard de Monitoreo

**URL:** http://localhost:3000/d/users-api-obs/users-api-monitoring

### Paneles Incluidos

1. **HTTP Request Rate (req/s)**
   ```promql
   rate(http_requests_total[1m])
   ```

2. **Memory Usage (MB)**
   ```promql
   process_resident_memory_bytes / 1024 / 1024
   ```

3. **DB Query Rate (queries/s)**
   ```promql
   rate(db_queries_total[1m])
   ```

4. **DB Query Latency P95**
   ```promql
   histogram_quantile(0.95, rate(db_query_duration_seconds_bucket[1m]))
   ```

5. **Request Latency P95 (seconds)**
   ```promql
   histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))
   ```

6. **Business Metrics**
   - Users created/updated/deleted

7. **API Error Rate**
   ```promql
   rate(api_errors_total[1m])
   ```

8. **Event Loop Lag**
   ```promql
   nodejs_eventloop_lag_seconds
   ```

9. **Database Connections**
   ```promql
   db_connections_active
   ```

10. **Total HTTP Requests**
    ```promql
    http_requests_total
    ```

### Restaurar Dashboard

**Opción 1: Importar manualmente**
1. Grafana → Dashboards → New → Import
2. Upload: `dashboard-users-api-monitoring.json`
3. Click "Load" → "Import"

**Opción 2: Via API**
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d @observability/dashboard-users-api-monitoring.json \
  http://admin:admin@localhost:3000/api/dashboards/db
```

---

## Alerting y SLO

### Alertas Básicas (Fase 2)

**Archivo:** `alert-rules.yml`

**10 Reglas configuradas:**

| Alerta | Severidad | Condición |
|--------|-----------|-----------|
| HighErrorRate | warning | Error rate > 0.1/s |
| DatabaseErrorRate | critical | DB error rate > 0.05/s |
| SlowDatabaseQueries | warning | P95 > 1s |
| EventLoopLagHigh | warning | Lag > 0.1s |
| HighMemoryUsage | warning | Memory > 500MB |
| APINotResponding | critical | 0 requests por 5min |
| High5xxRate | critical | 5xx rate > 5% |
| HighHTTPLatency | warning | P95 > 2s |
| LowDatabaseConnections | warning | Connections < 1 |
| AbnormalUserCreationRate | info | Creation > 10/s |

### Alertas SLO (Fase 3)

**Archivo:** `slo-rules.yml`

**SLOs Definidos:**
- Availability: 99.9%
- Latency: 95% bajo 500ms
- Database Success: 99.9%

**6 Reglas de alerting:**

| Alerta | Severidad | Condición |
|--------|-----------|-----------|
| HighErrorBudgetBurnRate | critical | Burn rate > 14.4x |
| ErrorBudgetExhausted | critical | Error budget < 0% |
| AvailabilitySLOViolation | warning | SLI < 99.9% |
| LatencySLOViolation | warning | SLI < 95% |
| DatabaseSLOViolation | warning | DB SLI < 99.9% |
| LowErrorBudget | info | Error budget < 10% |

**Ver alertas activas:**
```bash
# En Prometheus UI
http://localhost:9090/alerts

# Via API
curl -s http://localhost:9090/api/v1/alerts | jq
```

---

## Troubleshooting

### No veo trazas en Tempo

**Diagnóstico:**
```bash
# Verificar API corriendo
docker logs users-api

# Generar tráfico
curl http://localhost:3001/api/users

# Verificar Tempo
docker logs tempo
curl http://localhost:3200/ready
```

---

### No veo logs en Loki

**Diagnóstico:**
```bash
# Verificar Promtail
docker logs promtail

# Verificar logs del contenedor
docker logs users-api

# Verificar conectividad Promtail → Loki
docker exec promtail wget -O- http://loki:3100/ready
```

**Soluciones comunes:**
- Cambiar rango de tiempo en Grafana a "Last 5 minutes"
- Generar tráfico a la API
- Verificar que el contenedor tenga logs

---

### No veo métricas en Prometheus

**Diagnóstico:**
```bash
# Verificar endpoint de métricas
curl http://localhost:3001/metrics

# Verificar targets en Prometheus
# http://localhost:9090/targets
# users-api debe estar UP

# Revisar logs
docker logs prometheus
```

---

### Dashboard no muestra datos

**Soluciones:**
1. Verificar rango de tiempo (cambiar a "Last 5 minutes")
2. Generar tráfico a la API
3. Verificar que datasources estén configurados
4. Refrescar dashboard (Ctrl+R)

---

### Alertas no se disparan

**Diagnóstico:**
```bash
# Verificar reglas cargadas
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].name'

# Ver estado de alertas
curl -s http://localhost:9090/api/v1/alerts | jq
```

---

## URLs de Acceso

| Servicio | URL | Credenciales | Descripción |
|----------|-----|--------------|-------------|
| **Grafana** | http://localhost:3000 | admin/admin | Interfaz principal |
| **Dashboard** | http://localhost:3000/d/users-api-obs | - | Dashboard de monitoreo |
| **Prometheus** | http://localhost:9090 | - | Interfaz de Prometheus |
| **Prometheus Targets** | http://localhost:9090/targets | - | Estado de targets |
| **Prometheus Alerts** | http://localhost:9090/alerts | - | Alertas activas |
| **Tempo** | http://localhost:3200 | - | API de Tempo |
| **Loki** | http://localhost:3100 | - | API de Loki |
| **API** | http://localhost:3001/api/users | - | API de usuarios |
| **API Metrics** | http://localhost:3001/metrics | - | Métricas Prometheus |
| **API Health** | http://localhost:3001/health/live | - | Liveness probe |
| **API Readiness** | http://localhost:3001/health/ready | - | Readiness probe |
| **API Profiling** | http://localhost:3001/debug/memory | - | Memory stats |

---

## Recursos Adicionales

### Documentación del Proyecto
- [../README.md](../README.md) - Documentación principal
- [../ARCHITECTURE.md](../ARCHITECTURE.md) - Arquitectura del sistema
- [../CHANGELOG.md](../CHANGELOG.md) - Changelog de las 3 fases
- [../OBSERVABILITY-EVOLUTION.md](../OBSERVABILITY-EVOLUTION.md) - Evolución técnica

### Documentación Externa
- [Grafana Tempo Docs](https://grafana.com/docs/tempo/)
- [Grafana Loki Docs](https://grafana.com/docs/loki/)
- [Prometheus Docs](https://prometheus.io/docs/)
- [OpenTelemetry Docs](https://opentelemetry.io/docs/)
- [Grafana Dashboards](https://grafana.com/docs/grafana/latest/dashboards/)
- [Google SRE Book - SLI/SLO](https://sre.google/sre-book/service-level-objectives/)

---

## Stack Completo Implementado

- ✅ OpenTelemetry auto-instrumentación + manual spans
- ✅ Trace sampling inteligente (configurable)
- ✅ Trazas distribuidas (Tempo)
- ✅ Logs estructurados JSON (Loki) con 5 niveles
- ✅ Métricas Prometheus (30+ métricas)
- ✅ Recolección automática de logs (Promtail)
- ✅ Dashboard de monitoreo (Grafana)
- ✅ Correlación completa Logs ↔ Traces
- ✅ Database Query Observability
- ✅ SLI/SLO con error budgets
- ✅ 16 alertas (10 básicas + 6 SLO)
- ✅ Context propagation (tenant, user, request IDs)
- ✅ Continuous profiling (5 endpoints)
- ✅ Todo en docker-compose

---

**Fecha de actualización**: 2025-11-26
**Versión**: 3.0 (Enterprise-Grade)
**Estado**: ✅ Production-Ready
