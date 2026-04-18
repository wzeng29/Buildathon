# Users API Service

RESTful API microservice for managing user data with automatic data generation.

## Overview

This service provides a complete CRUD API for user management, built with Node.js and Express, featuring:

- **RESTful endpoints** for user operations (Create, Read, Update, Delete)
- **JWT-based authentication** for write operations
- **Automatic data generation** with Faker.js
- **PostgreSQL database** integration
- **OpenTelemetry instrumentation** for distributed tracing
- **Prometheus metrics** for monitoring
- **Structured logging** with correlation IDs
- **Health check endpoints** (liveness and readiness probes)

## Technology Stack

- **Runtime:** Node.js 22.x
- **Framework:** Express.js
- **Database Client:** pg (PostgreSQL)
- **Authentication:** jsonwebtoken (JWT)
- **Observability:**
  - OpenTelemetry SDK for tracing
  - prom-client for Prometheus metrics
  - Custom structured logger
- **Data Generation:** @faker-js/faker

## Project Structure

```
ecommerce-tshirts/services/users-service/
├── README.md           # This file
├── Dockerfile          # Container image definition
├── package.json        # Dependencies and scripts
└── src/
    ├── server.js       # Main application entry point
    ├── auth.js         # Authentication middleware and JWT logic
    ├── tracing.js      # OpenTelemetry configuration
    ├── logger.js       # Structured logging implementation
    ├── db.js           # Database connection and pool
    └── userGenerator.js # Faker data generation logic
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3001` | API server port |
| `DB_HOST` | `postgres` | PostgreSQL hostname |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `usersdb` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | `postgres` | Database password |
| `JWT_SECRET` | `default-secret...` | Secret key for signing JWT tokens ⚠️ Change in production! |
| `JWT_EXPIRATION` | `24h` | Token expiration time (1h, 24h, 7d, etc.) |
| `API_KEY` | `default-api-key...` | Alternative authentication via x-api-key header |
| `OTEL_SERVICE_NAME` | `users-api-microservice` | Service name in traces |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://tempo:4318` | Tempo endpoint |
| `TRACE_SAMPLING_RATE` | `1.0` | Trace sampling rate (0.0-1.0) |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |

## API Endpoints

### Authentication

- `POST /api/auth/token` - Generate access token
  - **Body:** `{ "client_id": "optional", "description": "optional" }`
  - **Response:** JWT token with expiration info
  - **Public endpoint** - No authentication required

### Health Checks

- `GET /health` - Basic health check
- `GET /health/live` - Liveness probe
- `GET /health/ready` - Readiness probe (includes DB check)

### Metrics

- `GET /metrics` - Prometheus metrics endpoint

### Users CRUD

**Public endpoints (no authentication required):**
- `GET /api/users` - List users (with pagination)
- `GET /api/users/:id` - Get user by ID

**Protected endpoints (authentication required):**
- `POST /api/users` - Create new user (auto-generated data) 🔒
- `PUT /api/users/:id` - Update user (auto-generated data) 🔒
- `DELETE /api/users/:id` - Delete user 🔒

### Debug/Profiling

- `GET /debug/memory` - Memory usage statistics
- `GET /debug/heapsnapshot` - Generate heap snapshot
- `GET /debug/profile/start` - Start CPU profiler
- `GET /debug/profile/stop` - Stop CPU profiler
- `GET /debug/eventloop` - Event loop statistics

## Authentication

### Generating a Token

To access protected endpoints, you must first generate an access token:

```bash
curl -X POST http://localhost:3001/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "my-app",
    "description": "Token for testing"
  }'
```

Response:
```json
{
  "status": "OK",
  "code": 201,
  "message": "Token generated successfully",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": "24h",
    "client_id": "my-app",
    "usage": "Include in Authorization header as: Bearer <token>"
  }
}
```

### Using the Token

Include the token in the `Authorization` header for protected endpoints:

```bash
# Create a new user
curl -X POST http://localhost:3001/api/users \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

# Update a user
curl -X PUT http://localhost:3001/api/users/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json"

# Delete a user
curl -X DELETE http://localhost:3001/api/users/1 \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

### Alternative: API Key Authentication

You can also use an API key for authentication:

```bash
curl -X POST http://localhost:3001/api/users \
  -H "x-api-key: YOUR_API_KEY_HERE" \
  -H "Content-Type: application/json"
```

### Authentication Errors

- **401 Unauthorized** - No token provided or invalid/expired token
- **403 Forbidden** - Valid token but insufficient permissions (future feature)

Example error response:
```json
{
  "status": "ERROR",
  "code": 401,
  "message": "Authentication required",
  "error": "No token provided",
  "requestId": "uuid-here"
}
```

## Development

### Local Development (without Docker)

```bash
# Install dependencies
npm install

# Start PostgreSQL locally (or use Docker)
# Configure .env file with local database credentials

# Run in development mode
npm run dev
```

### Running with Docker

```bash
# From project root
docker-compose up -d api
```

### Running Tests

```bash
# Unit tests
npm test

# Integration tests
npm run test:integration
```

## Observability Features

### Distributed Tracing

- Automatic HTTP request instrumentation
- Database query tracing
- Custom spans for business operations
- W3C Trace Context propagation

### Metrics

**HTTP Metrics:**
- `http_requests_total` - Total requests by method, route, status
- `http_request_duration_seconds` - Request latency histogram

**Business Metrics:**
- `users_created_total` - Users created by gender
- `users_updated_total` - Users updated
- `users_deleted_total` - Users deleted

**Authentication Metrics:**
- `auth_attempts_total` - Authentication attempts by method and status
- `tokens_generated_total` - Tokens generated by client_id
- `protected_endpoint_access_total` - Protected endpoint accesses

**Database Metrics:**
- `db_queries_total` - DB queries by type, table, status
- `db_query_duration_seconds` - Query latency histogram
- `db_connections_active` - Active database connections

**System Metrics:**
- Node.js memory, CPU, event loop metrics (via prom-client)

### Logging

Structured JSON logs with:
- Request ID and Correlation ID
- Trace ID and Span ID
- Log levels (debug, info, warn, error, fatal)
- Automatic context propagation

## Production Considerations

### Security

⚠️ **Important security considerations:**

**Authentication:**
- **CRITICAL:** Change `JWT_SECRET` and `API_KEY` in production!
  - Generate secure random values: `node -e "console.log(require('crypto').randomBytes(64).toString('hex'))"`
  - Never commit secrets to version control
  - Use environment variables or secrets management (e.g., AWS Secrets Manager, HashiCorp Vault)
- Consider shorter token expiration times for production (e.g., 1h instead of 24h)
- Implement token refresh mechanism for better UX
- Monitor authentication metrics for suspicious activity

**Debug Endpoints:**
- Remove or protect `/debug/*` endpoints in production
- Use environment-based feature flags
- Implement IP whitelisting for debug endpoints

**General:**
- Use HTTPS in production
- Implement rate limiting
- Add request validation and sanitization
- Monitor for security vulnerabilities in dependencies

### Performance

- Configure connection pooling in `db.js`
- Adjust `TRACE_SAMPLING_RATE` for high traffic (e.g., 0.1 = 10%)
- Monitor memory usage and set appropriate limits

### Deployment

Ready for deployment to:
- Docker/Docker Compose
- Kubernetes (see k8s examples in docs)
- Cloud platforms (AWS ECS, Google Cloud Run, etc.)

## Contributing

See the main [CONTRIBUTING.md](../../docs/CONTRIBUTING.md) for guidelines.

## License

Part of the Learning-Performance-Observability-Stack educational project.
