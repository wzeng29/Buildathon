# Poleras Store

Poleras Store is a learning e-commerce platform with:

- 5 Node.js microservices
- 5 PostgreSQL databases
- a frontend served on port `4000`
- a full observability stack: Grafana, Prometheus, Loki, and Tempo

This directory is the Docker entrypoint for the website and all supporting services.

## Start the Website with Docker

From the `website/` directory:

```bash
docker compose up -d
docker compose ps
```

On first startup, wait about 60 seconds for the databases, services, and Grafana stack to become healthy.

To stop everything:

```bash
docker compose down
```

To remove volumes and start fresh:

```bash
docker compose down -v
docker compose up -d
```

## Main URLs

### Application

| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:4000 | Store UI |
| users-api | http://localhost:3001 | Registration, login, JWT |
| products-service | http://localhost:3002 | Catalog and stock |
| cart-service | http://localhost:3003 | Shopping cart |
| orders-service | http://localhost:3004 | Order creation and status |
| payments-service | http://localhost:3005 | Payment processing |

### Observability

| Service | URL | Purpose |
|---|---|---|
| Grafana | http://localhost:3000 | Dashboards and exploration |
| Prometheus | http://localhost:9090 | Metrics |
| Loki | http://localhost:3100 | Logs |
| Tempo | http://localhost:3200 | Distributed traces |

Grafana default login:

```text
admin / admin
```

## Quick Health Check

```bash
docker compose ps
docker compose logs api products-service cart-service orders-service payments-service --tail 20
```

You can also run the included helper scripts:

```bash
./scripts/health-check.sh
./scripts/test-ecommerce-flow.sh
```

## Example Purchase Flow

```bash
# 1. Register a user
curl -s -X POST http://localhost:3001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"firstname":"Ana","lastname":"Lopez","email":"ana@test.com","password":"12345678"}'

# 2. Login and capture the JWT
TOKEN=$(curl -s -X POST http://localhost:3001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ana@test.com","password":"12345678"}' | jq -r '.data.token')

# 3. Browse products
curl http://localhost:3002/api/products | jq '.data[].slug'

# 4. Add one item to cart
curl -s -X POST http://localhost:3003/api/cart/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variant_id":1,"quantity":2}'

# 5. Create an order
ORDER=$(curl -s -X POST http://localhost:3004/api/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shippingAddress":"123 Main St, Santiago"}' | jq -r '.data.id')

# 6. Process payment
curl -s -X POST http://localhost:3005/api/payments/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"order_id\":$ORDER,\"payment_method\":\"credit_card\",\"card_number\":\"4111 1111 1111 1234\"}" | jq
```

## Documentation

- [docs/README.md](docs/README.md)
- [docs/architecture.html](docs/architecture.html)
- [docs/sequence.html](docs/sequence.html)
- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)
- [observability/README.md](observability/README.md)

## Project Structure

```text
website/
|-- docker-compose.yml
|-- docs/
|-- observability/
|-- scripts/
`-- ecommerce-tshirts/
    |-- frontend/
    |-- infrastructure/database/
    `-- services/
        |-- users-service/
        |-- products-service/
        |-- cart-service/
        |-- orders-service/
        `-- payments-service/
```
