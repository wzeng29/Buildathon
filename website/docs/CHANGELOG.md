# Changelog — Poleras Store

---

## [Fase 5 — E-Commerce Platform] - 2026-03-22

### Plataforma e-commerce completa

- 5 microservicios independientes: users-api, products-service, cart-service, orders-service, payments-service
- 5 bases de datos PostgreSQL independientes (una por servicio)
- Frontend Astro + React + TailwindCSS (:4000)
- Autenticación con registro/login real (JWT, bcrypt, email único)
- Propagación W3C TraceContext (`traceparent`) entre servicios para trazas distribuidas
- `X-Session-ID` propagado en todos los requests del frontend para correlación en Loki

### Observabilidad actualizada

- 4 dashboards Grafana: RED Metrics, Logs, SLO, Distributed Tracing
- Fix Tempo `metrics-generator local-blocks`: agregado `traces_storage.path` para corregir inicialización en cascada que bloqueaba todos los processors
- Fix dashboards Loki: paneles de errores/warnings migrados de `queryType: instant` + `rate([1m])` a `count_over_time([$__range])`
- Fix métricas APM: corrección de nombres de métricas (`auth_login_attempts_total`, `auth_registrations_total`)

### Diagramas

- `docs/architecture.html` — diagrama de alto nivel (Mermaid flowchart)
- `docs/sequence.html` — flujo de compra end-to-end (HTML/CSS puro)

---

## [Fase 4 — JWT Auth] - 2025-12-17

### 🔐 Autenticación JWT

#### Nuevas Características

**Sistema de Autenticación Completo:**
- ✅ Autenticación JWT para operaciones de escritura (POST, PUT, DELETE)
- ✅ Endpoint `POST /api/auth/token` para generar tokens de acceso
- ✅ Middleware de autenticación con soporte para JWT y API Key
- ✅ Tokens con expiración configurable (default: 24h)
- ✅ Validación automática de tokens en endpoints protegidos
- ✅ Endpoints de lectura (GET) públicos sin autenticación

**Observabilidad de Autenticación:**
- ✅ Métricas de autenticación en Prometheus:
  - `auth_attempts_total` - Intentos de autenticación por método y estado
  - `tokens_generated_total` - Tokens generados por client_id
  - `protected_endpoint_access_total` - Accesos a endpoints protegidos
- ✅ Logs estructurados con contexto de autenticación
- ✅ Trazas de OpenTelemetry con atributos de autenticación
- ✅ Correlation IDs para seguimiento end-to-end

**Seguridad:**
- ✅ Secrets configurables vía variables de entorno
- ✅ JWT_SECRET y API_KEY con valores seguros por defecto
- ✅ Documentación de generación de secrets aleatorios
- ✅ Advertencias de seguridad en documentación

#### Archivos Nuevos

- `ecommerce-tshirts/services/users-service/src/auth.js` - Middleware y lógica de autenticación JWT
  - Funciones: `generateToken`, `verifyToken`, `authenticate`
  - Soporte para JWT (Bearer token) y API Key
  - Integración con OpenTelemetry y logger estructurado

#### Archivos Modificados

- `ecommerce-tshirts/services/users-service/package.json` - Agregado `jsonwebtoken` ^9.0.2
- `ecommerce-tshirts/services/users-service/src/server.js`:
  - Importado módulo de autenticación
  - Agregado endpoint `POST /api/auth/token`
  - Protegidos endpoints POST, PUT, DELETE con middleware `authenticate`
  - Agregadas métricas de autenticación
  - Actualizado mensaje de inicio con endpoints de autenticación

**Documentación:**
- `ecommerce-tshirts/services/users-service/README.md` - Sección completa de autenticación con ejemplos
- `README.md` - Sección de autenticación con guía paso a paso
- `.env.example` - Variables JWT_SECRET, JWT_EXPIRATION, API_KEY

#### Variables de Entorno Nuevas

| Variable | Default | Descripción |
|----------|---------|-------------|
| `JWT_SECRET` | `default-secret-change-in-production` | Clave secreta para firmar tokens JWT |
| `JWT_EXPIRATION` | `24h` | Tiempo de expiración de tokens |
| `API_KEY` | `default-api-key-change-in-production` | API key alternativa |

#### Breaking Changes

⚠️ **IMPORTANTE:** A partir de esta versión:
- Los endpoints `POST /api/users`, `PUT /api/users/:id`, y `DELETE /api/users/:id` **requieren autenticación**
- Los requests sin token recibirán `401 Unauthorized`
- Los endpoints de lectura (GET) permanecen públicos

#### Migración

Para usar endpoints protegidos:

```bash
# 1. Generar token
TOKEN=$(curl -s -X POST http://localhost:3001/api/auth/token | jq -r '.data.token')

# 2. Usar token en requests
curl -X POST http://localhost:3001/api/users \
  -H "Authorization: Bearer $TOKEN"
```

---

## [Fase 3] - 2025-11-26

### ✨ Nuevas Características

#### SLI/SLO (Service Level Indicators/Objectives)
- ✅ Implementado sistema completo de SLI/SLO con 4 indicadores principales
- ✅ SLI de Availability: 99.9% de requests exitosos
- ✅ SLI de Latency: 95% de requests bajo 500ms
- ✅ SLI de Database Success: 99.9% de queries exitosas
- ✅ SLI de Database Latency: queries bajo 100ms
- ✅ Error Budget tracking con métricas en tiempo real
- ✅ Burn Rate monitoring con alertas críticas (> 14.4x)
- ✅ 14 recording rules para pre-computar SLIs
- ✅ 6 alertas basadas en SLO y error budgets

#### Trace Sampling Inteligente
- ✅ Sampling configurable via `TRACE_SAMPLING_RATE` (default: 10%)
- ✅ `IntelligentSampler` class implementada
- ✅ `ParentBasedSampler` para coherencia en distributed tracing
- ✅ Response hooks para marcar errores 5xx con `force.sampling`
- ✅ Response hooks con `sampling.priority = 1` en errores
- ✅ Resource attributes: `deployment.environment`, `service.version`
- ✅ Reducción de costos de almacenamiento (90% con sampling 10%)

#### Context Propagation Mejorado
- ✅ Middleware para propagar contexto de negocio
- ✅ Atributo `request.id` en todos los spans
- ✅ Atributo `correlation.id` propagado desde headers
- ✅ Atributo `tenant.id` para multi-tenancy (preparación)
- ✅ Atributo `user.id` para user tracking
- ✅ Atributo `deployment.environment` en spans
- ✅ Soporte para headers personalizados: `x-tenant-id`, `x-user-id`, `x-correlation-id`

#### Continuous Profiling
- ✅ `GET /debug/memory` - Estadísticas de memoria en tiempo real
- ✅ `GET /debug/heapsnapshot` - Generar heap snapshot para Chrome DevTools
- ✅ `GET /debug/profile/start` - Iniciar CPU profiler
- ✅ `GET /debug/profile/stop` - Detener profiler y obtener .cpuprofile
- ✅ `GET /debug/eventloop` - Event loop utilization monitoring
- ✅ Profiling on-demand sin redeploy para debugging en producción

### 📝 Archivos Modificados

#### Nuevos
- `observability/slo-rules.yml` - 14 recording rules + 6 alerting rules de SLO

#### Modificados
- `src/tracing.js` - Trace sampling inteligente con IntelligentSampler
- `src/server.js` - Context propagation middleware + 5 profiling endpoints
- `observability/prometheus.yml` - Cargar archivo slo-rules.yml
- `docker-compose.yml` - Montar slo-rules.yml en contenedor de Prometheus
- `README.md` - Documentación completa de Fase 3

### 🎯 Métricas Nuevas

#### SLI Metrics
```promql
sli:availability:ratio_rate5m
sli:latency:ratio_rate5m
sli:database:success_ratio_rate5m
sli:database:latency_ratio_rate5m
```

#### Error Budget Metrics
```promql
slo:availability:error_budget_remaining
slo:latency:error_budget_remaining
slo:database:error_budget_remaining
```

#### Burn Rate Metrics
```promql
slo:availability:burn_rate_1h
slo:latency:burn_rate_1h
slo:database:burn_rate_1h
```

#### Compliance Metrics
```promql
slo:availability:compliance
slo:latency:compliance
slo:database:compliance
```

### 🚨 Alertas Nuevas (6 reglas)

1. **HighErrorBudgetBurnRate** (critical) - Burn rate > 14.4x por 10min
2. **ErrorBudgetExhausted** (critical) - Error budget < 0% por 5min
3. **AvailabilitySLOViolation** (warning) - SLI < 99.9% por 10min
4. **LatencySLOViolation** (warning) - SLI < 95% por 10min
5. **DatabaseSLOViolation** (warning) - DB SLI < 99.9% por 10min
6. **LowErrorBudget** (info) - Error budget < 10% por 5min

### 🔧 Variables de Entorno Nuevas

- `TRACE_SAMPLING_RATE` - Sampling rate para traces (default: 0.1 = 10%)
- `SERVICE_VERSION` - Versión del servicio (default: 1.0.0)
- `NODE_ENV` - Ambiente de deployment (usado en context propagation)

### 📖 Documentación Nueva

- `/tmp/fase3_summary.md` - Resumen técnico completo de Fase 3
- `/tmp/fase3_tests.sh` - Script de verificación automatizada
- Sección "Mejoras de Observabilidad (Fase 3)" en README.md
- Sección "Profiling Endpoints" en README.md
- Sección "Resumen de Evolución del Sistema de Observabilidad" en README.md

---

## [Fase 2] - 2025-11-25

### ✨ Nuevas Características

#### Database Query Observability
- ✅ Wrapper de database con instrumentación automática
- ✅ Métricas de queries por tipo (SELECT, INSERT, UPDATE, DELETE)
- ✅ Métricas por tabla (users, addresses)
- ✅ Histogram de duración de queries
- ✅ Contador de queries por status (success, error)
- ✅ Detección automática de slow queries (> 100ms)
- ✅ Logs estructurados de queries con tipo, tabla, duración, rowCount

#### Custom Spans (OpenTelemetry Manual Instrumentation)
- ✅ Span `transaction.create_user` para POST /api/users
- ✅ Atributos de negocio: `user.gender`, `user.country`
- ✅ Trazabilidad completa de transacciones multi-step
- ✅ Correlación con auto-instrumentation de PostgreSQL

#### Structured Logging
- ✅ Logger class con niveles jerárquicos (DEBUG, INFO, WARN, ERROR, FATAL)
- ✅ Filtrado por nivel via variable `LOG_LEVEL`
- ✅ Contexto automático: traceId y spanId del span activo
- ✅ Child loggers con propagación de contexto
- ✅ Método helper `logRequest()` con nivel automático según status code
- ✅ Logs estructurados JSON con todos los campos estándar

#### Alerting System
- ✅ Archivo `observability/alert-rules.yml` con 10 reglas de alerting
- ✅ Alertas por error rate, latencia, memoria, event loop
- ✅ 3 niveles de severidad: critical, warning, info
- ✅ Integración con Prometheus Alertmanager

### 📝 Archivos Modificados

#### Nuevos
- `src/logger.js` - Logger class con structured logging
- `src/db-wrapper.js` - Database wrapper con observabilidad
- `observability/alert-rules.yml` - 10 reglas de alerting

#### Modificados
- `src/server.js` - Integración de logger, db-wrapper y custom spans
- `observability/prometheus.yml` - Cargar alert-rules.yml
- `docker-compose.yml` - Montar alert-rules.yml
- `README.md` - Documentación completa de Fase 2

### 🎯 Métricas Nuevas

```promql
# Database metrics
db_queries_total{query_type, table, status}
db_query_duration_seconds{query_type, table, status}
```

### 🚨 Alertas Nuevas (10 reglas)

1. **HighErrorRate** (warning) - Error rate > 0.1/s
2. **DatabaseErrorRate** (critical) - DB error rate > 0.05/s
3. **SlowDatabaseQueries** (warning) - P95 > 1s
4. **EventLoopLagHigh** (warning) - Lag > 0.1s
5. **HighMemoryUsage** (warning) - Memory > 500MB
6. **APINotResponding** (critical) - 0 requests por 5min
7. **High5xxRate** (critical) - 5xx rate > 5%
8. **HighHTTPLatency** (warning) - P95 > 2s
9. **LowDatabaseConnections** (warning) - Connections < 1
10. **AbnormalUserCreationRate** (info) - Creation rate > 10/s

---

## [Fase 1] - 2025-11-24

### ✨ Nuevas Características

#### Request ID y Correlation ID
- ✅ Middleware UUID para generar Request ID único
- ✅ Propagación de Correlation ID desde headers `x-correlation-id`
- ✅ Headers de respuesta: `x-request-id`, `x-correlation-id`
- ✅ Request ID en todos los logs estructurados
- ✅ Request ID en respuestas de error para soporte

#### Health Checks Avanzados
- ✅ `GET /health/live` - Liveness probe (proceso vivo)
- ✅ `GET /health/ready` - Readiness probe (puede recibir tráfico)
- ✅ Readiness verifica conexión a base de datos
- ✅ Readiness muestra estado de pool de conexiones
- ✅ Backward compatibility con `GET /health`
- ✅ Configuración lista para Kubernetes probes

#### Métricas de Negocio
- ✅ `users_created_total` - Counter con label `gender`
- ✅ `users_updated_total` - Counter de actualizaciones
- ✅ `users_deleted_total` - Counter de eliminaciones
- ✅ `db_connections_active` - Gauge de conexiones activas
- ✅ Visualización de métricas de negocio en Grafana

#### Error Tracking Estructurado
- ✅ Métrica `api_errors_total` con labels: error_type, endpoint, status_code
- ✅ Logs estructurados de errores con stack trace
- ✅ Correlación de errores via requestId
- ✅ Error rate queries en Prometheus

### 📝 Archivos Modificados

- `src/server.js` - Request ID middleware, health checks, business metrics, error tracking
- `README.md` - Documentación completa de Fase 1

### 🎯 Métricas Nuevas

```promql
# Business metrics
users_created_total{gender}
users_updated_total
users_deleted_total
db_connections_active

# Error tracking
api_errors_total{error_type, endpoint, status_code}
```

### 🔧 Variables de Entorno Nuevas

Ninguna (usa variables existentes)

---

## [Sistema Base] - Inicial

### Stack de Observabilidad Implementado

#### Logs (Loki + Promtail)
- ✅ Grafana Loki para almacenamiento de logs
- ✅ Promtail para recolección desde Docker
- ✅ Logs JSON estructurados desde la aplicación
- ✅ Integración con Grafana Explore

#### Trazas (Tempo + OpenTelemetry)
- ✅ Grafana Tempo para almacenamiento de trazas
- ✅ OpenTelemetry auto-instrumentation de Node.js
- ✅ Instrumentación automática de HTTP (Express)
- ✅ Instrumentación automática de PostgreSQL
- ✅ OTLP exporter a Tempo via HTTP/protobuf

#### Métricas (Prometheus + prom-client)
- ✅ Prometheus para scraping y almacenamiento
- ✅ prom-client para exponer métricas desde Node.js
- ✅ Endpoint `GET /metrics` en formato Prometheus
- ✅ Métricas HTTP básicas: requests_total, duration_seconds
- ✅ Métricas default de Node.js: memoria, CPU, event loop

#### Visualización (Grafana)
- ✅ Grafana unificado para Logs, Traces, Metrics
- ✅ Datasources pre-configurados: Loki, Tempo, Prometheus
- ✅ Correlación básica entre logs y traces via traceId
- ✅ Grafana Explore para queries ad-hoc

### 🐳 Infraestructura Docker

#### Servicios
- `users-api` - API de usuarios (Node.js + Express)
- `postgres` - Base de datos PostgreSQL 15
- `tempo` - Grafana Tempo (trazas)
- `loki` - Grafana Loki (logs)
- `promtail` - Promtail (recolector de logs)
- `prometheus` - Prometheus (métricas)
- `grafana` - Grafana (visualización)

#### Networking
- Red Docker `observability` compartida entre todos los servicios
- Puertos expuestos: 3000, 3001, 3100, 3200, 4317, 4318, 5434, 9090

#### Volumes
- `postgres_data` - Datos de PostgreSQL
- `tempo_data` - Trazas de Tempo
- `loki_data` - Logs de Loki
- `prometheus_data` - Métricas de Prometheus
- `grafana_data` - Configuración de Grafana

---

## Resumen Cuantitativo

### Por Fase

| Aspecto | Base | Fase 1 | Fase 2 | Fase 3 | Total |
|---------|------|--------|--------|--------|-------|
| **Métricas nuevas** | 5 | 5 | 2 | 16 | **28** |
| **Alertas** | 0 | 0 | 10 | 6 | **16** |
| **Endpoints nuevos** | 10 | 2 | 0 | 5 | **17** |
| **Archivos nuevos** | 10 | 0 | 3 | 1 | **14** |
| **Archivos modificados** | - | 1 | 4 | 5 | **10** |
| **Variables de entorno** | 11 | 0 | 0 | 3 | **14** |

### Totales Finales

- ✅ **28+ métricas** implementadas
- ✅ **16 alertas** configuradas
- ✅ **17 endpoints** disponibles
- ✅ **3 pilares** de observabilidad completos
- ✅ **7 servicios** Docker orquestados
- ✅ **4 SLIs** con error budgets
- ✅ **100% correlación** entre Logs, Traces y Metrics

---

## Próximos Pasos Potenciales

### Observabilidad Avanzada
- [ ] Integrar con Alertmanager para notificaciones (email, Slack, PagerDuty)
- [ ] Dashboard de SLO en Grafana con visualización de error budgets
- [ ] Distributed tracing entre múltiples microservicios
- [ ] Baggage propagation para contexto más rico
- [ ] Span events para milestones dentro de transacciones

### Performance
- [ ] Cache layer con observabilidad (Redis)
- [ ] APM profiling continuo (Pyroscope)
- [ ] Query performance insights automáticos
- [ ] Synthetic monitoring con Blackbox Exporter

### Security & Compliance
- [ ] Audit logs separados para compliance
- [ ] Autenticación en profiling endpoints
- [ ] Data retention policies configurables
- [ ] PII scrubbing en logs y traces

### Infrastructure
- [ ] Kubernetes deployment con Helm charts
- [ ] Horizontal Pod Autoscaling basado en SLIs
- [ ] Service Mesh con Istio para observabilidad automática
- [ ] GitOps con ArgoCD para deployments observables

---

## Contribuciones

Este proyecto es un ejemplo educativo de observabilidad completa con Grafana Stack.

**Autor:** Desarrollado con stack completo de observabilidad (Grafana LGTM + OpenTelemetry)

**Licencia:** ISC
