# Poleras Store

Poleras Store es una plataforma e-commerce de aprendizaje con:

- 5 microservicios Node.js
- 5 bases de datos PostgreSQL
- un frontend en el puerto `4000`
- un stack completo de observabilidad: Grafana, Prometheus, Loki y Tempo

Este directorio es el punto de entrada Docker para levantar la web y todos sus servicios.

## Levantar la Web con Docker

Desde el directorio `website/`:

```bash
docker compose up -d
docker compose ps
```

En el primer arranque, espera aproximadamente 60 segundos para que las bases de datos, los servicios y Grafana queden listos.

Para detener todo:

```bash
docker compose down
```

Para borrar volumnes y reiniciar desde cero:

```bash
docker compose down -v
docker compose up -d
```

## URLs Principales

### Aplicacion

| Servicio | URL | Uso |
|---|---|---|
| Frontend | http://localhost:4000 | Interfaz de la tienda |
| users-api | http://localhost:3001 | Registro, login, JWT |
| products-service | http://localhost:3002 | Catalogo y stock |
| cart-service | http://localhost:3003 | Carrito |
| orders-service | http://localhost:3004 | Creacion y estado de pedidos |
| payments-service | http://localhost:3005 | Procesamiento de pagos |

### Observabilidad

| Servicio | URL | Uso |
|---|---|---|
| Grafana | http://localhost:3000 | Dashboards y exploracion |
| Prometheus | http://localhost:9090 | Metricas |
| Loki | http://localhost:3100 | Logs |
| Tempo | http://localhost:3200 | Trazas distribuidas |

Login por defecto de Grafana:

```text
admin / admin
```

## Verificacion Rapida

```bash
docker compose ps
docker compose logs api products-service cart-service orders-service payments-service --tail 20
```

Tambien puedes usar los scripts incluidos:

```bash
./scripts/health-check.sh
./scripts/test-ecommerce-flow.sh
```

## Flujo de Compra de Ejemplo

```bash
# 1. Registrar usuario
curl -s -X POST http://localhost:3001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"firstname":"Ana","lastname":"Lopez","email":"ana@test.com","password":"12345678"}'

# 2. Login y capturar JWT
TOKEN=$(curl -s -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@test.com","password":"12345678"}' | jq -r '.data.token')

# 3. Ver productos
curl http://localhost:3002/api/products | jq '.data[].slug'

# 4. Agregar producto al carrito
curl -s -X POST http://localhost:3003/api/cart/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variant_id":1,"quantity":2}'

# 5. Crear pedido
ORDER=$(curl -s -X POST http://localhost:3004/api/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shippingAddress":"123 Main St, Santiago"}' | jq -r '.data.id')

# 6. Procesar pago
curl -s -X POST http://localhost:3005/api/payments/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"order_id\":$ORDER,\"payment_method\":\"credit_card\",\"card_number\":\"4111 1111 1111 1234\"}" | jq
```

## Documentacion

- [docs/README.md](docs/README.md)
- [docs/architecture.html](docs/architecture.html)
- [docs/sequence.html](docs/sequence.html)
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
- [observability/README.md](observability/README.md)
