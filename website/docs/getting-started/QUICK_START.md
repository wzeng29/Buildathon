# Quick Start — Poleras Store

Guía para poner en marcha el stack completo en 5 minutos.

## Requisitos previos

```bash
docker --version          # >= 20.10
docker compose version    # >= 2.0
```

Si no tienes Docker → [INSTALLATION.md](./INSTALLATION.md)

---

## 1. Levantar el stack

```bash
docker compose up -d
```

Espera ~60 segundos. Verifica que todos los servicios estén `running`:

```bash
docker compose ps
```

---

## 2. Puntos de acceso

| Servicio | URL | Credenciales |
|----------|-----|--------------|
| Frontend | http://localhost:4000 | — |
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| users-api | http://localhost:3001 | — |
| products-service | http://localhost:3002 | — |
| cart-service | http://localhost:3003 | — |
| orders-service | http://localhost:3004 | — |
| payments-service | http://localhost:3005 | — |

---

## 3. Generar tráfico de prueba

### Autenticarse

```bash
# Registrar usuario
curl -s -X POST http://localhost:3001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"firstname":"Test","lastname":"User","email":"test@demo.com","password":"12345678"}'

# Login y guardar token
TOKEN=$(curl -s -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@demo.com","password":"12345678"}' | jq -r '.data.token')
```

### Flujo de compra completo

```bash
# Ver productos
curl -s http://localhost:3002/api/products | jq '.data[0]'

# Agregar al carrito
curl -s -X POST http://localhost:3003/api/cart/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variant_id":1,"quantity":1}' | jq

# Crear pedido
ORDER=$(curl -s -X POST http://localhost:3004/api/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shippingAddress":"Calle Test 123"}' | jq -r '.data.id')

# Pagar
curl -s -X POST http://localhost:3005/api/payments/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"order_id\":$ORDER,\"payment_method\":\"credit_card\",\"card_number\":\"4111 1111 1111 1234\"}" | jq
```

---

## 4. Explorar la observabilidad en Grafana

Abre http://localhost:3000 → Dashboards:

| Dashboard | Qué observar |
|-----------|--------------|
| **RED Metrics** | RPS, tasa de errores, latencia P95 por servicio |
| **Logs** | Streams de error, correlación con trazas |
| **SLO** | Error budget, burn rate |
| **Distributed Tracing** | Service map, spans end-to-end |

### Queries de exploración rápida

> **Nota:** Estas queries requieren que hayas generado tráfico primero (sección 3). Sin tráfico, Prometheus y Loki no tendrán datos.

**Loki (logs):**
```
# Todos los logs de todos los servicios
{service=~"api|products-service|cart-service|orders-service|payments-service"} | json

# Solo errores de la users-api
{service="api"} | json | level="error"

# Logs con traceId (para correlación con Tempo)
{service=~"api|products-service|cart-service|orders-service|payments-service"} | json | traceId != ""
```

> El label de `users-api` en Loki es `service="api"`, no `service="users-api"`.

**Tempo (trazas):**
```
# Todos los servicios
{resource.service.name=~"users-api-microservice|products-service|cart-service|orders-service|payments-service"}

# Solo users-api
{resource.service.name="users-api-microservice"}
```

**Prometheus (métricas):**
```promql
# Requests por segundo por servicio (usa label "job", no "service_name")
rate(http_requests_total[1m])

# Por servicio específico
rate(http_requests_total{job="users-api"}[1m])

# Latencia P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

---

## Comandos frecuentes

```bash
# Ver logs de un servicio
docker compose logs -f users-api

# Reiniciar un servicio
docker compose restart orders-service

# Detener todo
docker compose down

# Reset completo (borra datos)
docker compose down -v && docker compose up -d
```

---

**Siguiente paso:** [Arquitectura técnica](../architecture/ARCHITECTURE.md) | [Troubleshooting](./TROUBLESHOOTING.md)
