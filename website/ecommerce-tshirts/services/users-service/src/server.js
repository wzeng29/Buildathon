require('./tracing');
require('dotenv').config();
const express = require('express');
const pool = require('./db');
const { runMigrations } = require('./migrate');
const { generateRandomUser } = require('./userGenerator');
const promClient = require('prom-client');
const { trace, context, propagation, baggage, SpanStatusCode } = require('@opentelemetry/api');
const { randomUUID } = require('crypto');
const logger = require('./logger');
const { generateToken, authenticate } = require('./auth');
const bcrypt = require('bcrypt');
const BCRYPT_ROUNDS = 12;

const app = express();
const PORT = process.env.PORT || 3000;

// Configurar Prometheus
const register = new promClient.Registry();
promClient.collectDefaultMetrics({ register });

// Métricas HTTP personalizadas
const httpRequestDuration = new promClient.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

const httpRequestTotal = new promClient.Counter({
  name: 'http_requests_total',
  help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'],
  registers: [register]
});

// Métricas de negocio
const usersCreatedTotal = new promClient.Counter({
  name: 'users_created_total',
  help: 'Total number of users created',
  labelNames: ['gender'],
  registers: [register]
});

const usersDeletedTotal = new promClient.Counter({
  name: 'users_deleted_total',
  help: 'Total number of users deleted',
  registers: [register]
});

const usersUpdatedTotal = new promClient.Counter({
  name: 'users_updated_total',
  help: 'Total number of users updated',
  registers: [register]
});

// Métricas de errores
const apiErrorsTotal = new promClient.Counter({
  name: 'api_errors_total',
  help: 'Total API errors',
  labelNames: ['error_type', 'endpoint', 'status_code'],
  registers: [register]
});

// Métricas de base de datos
const dbConnectionsActive = new promClient.Gauge({
  name: 'db_connections_active',
  help: 'Active database connections',
  registers: [register]
});

const dbConnectionsIdle = new promClient.Gauge({
  name: 'db_connections_idle',
  help: 'Idle database connections in the pool',
  registers: [register]
});

const dbConnectionsTotal = new promClient.Gauge({
  name: 'db_connections_total',
  help: 'Total database connections in the pool',
  registers: [register]
});

const dbConnectionsWaiting = new promClient.Gauge({
  name: 'db_connections_waiting',
  help: 'Number of queued requests waiting for a database connection',
  registers: [register]
});

const dbQueryDuration = new promClient.Histogram({
  name: 'db_query_duration_seconds',
  help: 'Database query duration in seconds',
  labelNames: ['query_type', 'table', 'status'],
  buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
  registers: [register]
});

const dbQueriesTotal = new promClient.Counter({
  name: 'db_queries_total',
  help: 'Total number of database queries',
  labelNames: ['query_type', 'table', 'status'],
  registers: [register]
});

// Métricas de autenticación
const authAttemptsTotal = new promClient.Counter({
  name: 'auth_attempts_total',
  help: 'Total number of authentication attempts',
  labelNames: ['method', 'status', 'error_type'],
  registers: [register]
});

const tokensGeneratedTotal = new promClient.Counter({
  name: 'tokens_generated_total',
  help: 'Total number of tokens generated',
  labelNames: ['client_id'],
  registers: [register]
});

const protectedEndpointAccessTotal = new promClient.Counter({
  name: 'protected_endpoint_access_total',
  help: 'Total number of protected endpoint accesses',
  labelNames: ['endpoint', 'method', 'auth_status'],
  registers: [register]
});

// Métricas de autenticación de clientes
const authRegistrationsTotal = new promClient.Counter({
  name: 'auth_registrations_total',
  help: 'Total number of customer registrations',
  registers: [register]
});

const authLoginAttemptsTotal = new promClient.Counter({
  name: 'auth_login_attempts_total',
  help: 'Total number of login attempts',
  labelNames: ['status'],
  registers: [register]
});

// Función para actualizar métricas del pool de PostgreSQL
function updatePoolMetrics() {
  dbConnectionsTotal.set(pool.totalCount);
  dbConnectionsIdle.set(pool.idleCount);
  dbConnectionsWaiting.set(pool.waitingCount);
  // Conexiones activas = total - idle
  dbConnectionsActive.set(pool.totalCount - pool.idleCount);
}

// Wrapper para queries con observabilidad
async function queryWithMetrics(sql, params, queryType, table) {
  const end = dbQueryDuration.startTimer({ query_type: queryType, table });
  const start = Date.now();

  try {
    const result = await pool.query(sql, params);
    const duration = Date.now() - start;

    // Actualizar métricas del pool después de cada query
    updatePoolMetrics();

    // Registrar métrica exitosa
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'success' });
    end({ status: 'success' });

    // Log de query (solo en desarrollo o si es lenta)
    if (duration > 100) {
      console.log(JSON.stringify({
        level: 'warn',
        message: 'Slow database query',
        queryType,
        table,
        duration: `${duration}ms`,
        rowCount: result.rowCount,
        timestamp: new Date().toISOString()
      }));
    }

    return result;
  } catch (error) {
    // Registrar métrica de error
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'error' });
    end({ status: 'error' });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Database query error',
      queryType,
      table,
      error: error.message,
      timestamp: new Date().toISOString()
    }));

    throw error;
  }
}

// Wrapper para queries de cliente (transacciones) con observabilidad
async function clientQueryWithMetrics(client, sql, params, queryType, table) {
  const end = dbQueryDuration.startTimer({ query_type: queryType, table });
  const start = Date.now();

  try {
    const result = await client.query(sql, params);
    const duration = Date.now() - start;

    // Actualizar métricas del pool después de cada query
    updatePoolMetrics();

    dbQueriesTotal.inc({ query_type: queryType, table, status: 'success' });
    end({ status: 'success' });

    if (duration > 100) {
      logger.warn('Slow database query', {
        queryType,
        table,
        duration: `${duration}ms`,
        rowCount: result.rowCount
      });
    }

    return result;
  } catch (error) {
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'error' });
    end({ status: 'error' });

    logger.error('Database query error', {
      queryType,
      table,
      error: error.message
    });

    throw error;
  }
}

app.use(express.json());

// Middleware: Request ID y Correlation ID
app.use((req, res, next) => {
  // Request ID único por request
  req.id = req.headers['x-request-id'] || randomUUID();

  // Correlation ID para flujos relacionados
  req.correlationId = req.headers['x-correlation-id'] || req.id;
  req.sessionId = req.headers['x-session-id'] || '';

  // Agregar a response headers
  res.setHeader('x-request-id', req.id);
  res.setHeader('x-correlation-id', req.correlationId);

  next();
});

// Middleware: Distributed Context Propagation (Span Attributes)
app.use((req, res, next) => {
  // Agregar context info al span actual para correlación
  const span = trace.getActiveSpan();
  if (span) {
    span.setAttribute('request.id', req.id);
    span.setAttribute('correlation.id', req.correlationId);

    // Agregar tenant/user info si viene en headers (preparación para multi-tenancy)
    if (req.headers['x-tenant-id']) {
      span.setAttribute('tenant.id', req.headers['x-tenant-id']);
    }
    if (req.headers['x-user-id']) {
      span.setAttribute('user.id', req.headers['x-user-id']);
    }

    // Agregar deployment info
    span.setAttribute('deployment.environment', process.env.NODE_ENV || 'development');
  }

  next();
});

// Middleware combinado: métricas + logging con trace correlation
app.use((req, res, next) => {
  const start = Date.now();

  res.on('finish', () => {
    const duration = Date.now() - start;
    const durationInSeconds = duration / 1000;
    const route = req.route ? req.route.path : req.path;

    // 1. Actualizar métricas de Prometheus
    httpRequestDuration.labels(req.method, route, res.statusCode).observe(durationInSeconds);
    httpRequestTotal.labels(req.method, route, res.statusCode).inc();

    // 2. Generar log estructurado con trace correlation
    const span = trace.getActiveSpan();
    const spanContext = span?.spanContext();

    // Usar logger estructurado
    const requestLogger = logger.child({
      requestId: req.id,
      correlationId: req.correlationId,
      sessionId: req.sessionId
    });

    requestLogger.logRequest(req, res, duration);
  });

  next();
});

async function buildResponse(data, total = null) {
  return {
    status: "OK",
    code: 200,
    locale: "en_US",
    seed: null,
    total: total !== null ? total : (Array.isArray(data) ? data.length : 1),
    data: Array.isArray(data) ? data : [data]
  };
}

// ==================== AUTHENTICATION ENDPOINTS ====================

/**
 * POST /api/auth/token
 * Genera un nuevo token de acceso JWT
 * Body: { client_id?: string, description?: string }
 */
app.post('/api/auth/token', (req, res) => {
  try {
    const { client_id, description } = req.body;

    // Validar client_id si se proporciona
    const clientId = client_id || `client_${randomUUID().substring(0, 8)}`;

    // Generar token
    const token = generateToken({
      client_id: clientId,
      description: description || 'API access token'
    });

    // Incrementar métrica
    tokensGeneratedTotal.inc({ client_id: clientId });

    logger.info('Token generated successfully', {
      requestId: req.id,
      correlationId: req.correlationId,
      sessionId: req.sessionId,
      clientId
    });

    res.status(201).json({
      status: 'OK',
      code: 201,
      message: 'Token generated successfully',
      data: {
        token,
        token_type: 'Bearer',
        expires_in: process.env.JWT_EXPIRATION || '24h',
        client_id: clientId,
        usage: 'Include in Authorization header as: Bearer <token>'
      },
      requestId: req.id
    });
  } catch (error) {
    logger.error('Error generating token', {
      requestId: req.id,
      correlationId: req.correlationId,
      sessionId: req.sessionId,
      error: error.message
    });

    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/auth/token',
      status_code: '500'
    });

    res.status(500).json({
      status: 'ERROR',
      code: 500,
      message: 'Internal server error',
      requestId: req.id
    });
  }
});

// ==================== USER ENDPOINTS ====================

app.get('/api/users', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 10;
    const offset = parseInt(req.query.offset) || 0;

    const countResult = await queryWithMetrics('SELECT COUNT(*) FROM users', [], 'SELECT', 'users');
    const total = parseInt(countResult.rows[0].count);

    const usersResult = await queryWithMetrics(
      `SELECT u.*,
        json_build_object(
          'id', a.id,
          'street', a.street,
          'streetName', a.street_name,
          'buildingNumber', a.building_number,
          'city', a.city,
          'zipcode', a.zipcode,
          'country', a.country,
          'country_code', a.country_code,
          'latitude', a.latitude,
          'longitude', a.longitude
        ) as address
      FROM users u
      LEFT JOIN addresses a ON u.address_id = a.id
      ORDER BY u.id
      LIMIT $1 OFFSET $2`,
      [limit, offset],
      'SELECT',
      'users'
    );

    if (usersResult.rows.length === 0) {
      return res.json(await buildResponse([], 0));
    }

    const users = usersResult.rows.map(row => ({
      id: row.id,
      firstname: row.firstname,
      lastname: row.lastname,
      email: row.email,
      phone: row.phone,
      birthday: row.birthday.toISOString().split('T')[0],
      gender: row.gender,
      address: row.address,
      website: row.website,
      image: row.image
    }));

    res.json(await buildResponse(users, total));
  } catch (error) {
    // Registrar error con métricas
    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/users',
      status_code: '500'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Error fetching users',
      error: error.message,
      errorStack: error.stack,
      endpoint: '/api/users',
      method: 'GET',
      requestId: req.id,
      correlationId: req.correlationId,
      timestamp: new Date().toISOString()
    }));

    res.status(500).json({
      status: "ERROR",
      code: 500,
      message: "Internal server error",
      requestId: req.id
    });
  }
});

app.get('/api/users/:id', async (req, res) => {
  try {
    const userId = parseInt(req.params.id);

    if (isNaN(userId)) {
      return res.status(400).json({
        status: "ERROR",
        code: 400,
        message: "Invalid user ID"
      });
    }

    const result = await queryWithMetrics(
      `SELECT u.*,
        json_build_object(
          'id', a.id,
          'street', a.street,
          'streetName', a.street_name,
          'buildingNumber', a.building_number,
          'city', a.city,
          'zipcode', a.zipcode,
          'country', a.country,
          'country_code', a.country_code,
          'latitude', a.latitude,
          'longitude', a.longitude
        ) as address
      FROM users u
      LEFT JOIN addresses a ON u.address_id = a.id
      WHERE u.id = $1`,
      [userId],
      'SELECT',
      'users'
    );

    if (result.rows.length === 0) {
      return res.status(404).json({
        status: "ERROR",
        code: 404,
        message: "User not found"
      });
    }

    const row = result.rows[0];
    const user = {
      id: row.id,
      firstname: row.firstname,
      lastname: row.lastname,
      email: row.email,
      phone: row.phone,
      birthday: row.birthday.toISOString().split('T')[0],
      gender: row.gender,
      address: row.address,
      website: row.website,
      image: row.image
    };

    res.json(await buildResponse(user));
  } catch (error) {
    // Registrar error con métricas
    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/users/:id',
      status_code: '500'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Error fetching user',
      error: error.message,
      errorStack: error.stack,
      endpoint: '/api/users/:id',
      method: 'GET',
      userId: req.params.id,
      requestId: req.id,
      correlationId: req.correlationId,
      timestamp: new Date().toISOString()
    }));

    res.status(500).json({
      status: "ERROR",
      code: 500,
      message: "Internal server error",
      requestId: req.id
    });
  }
});

app.post('/api/users', authenticate, async (req, res) => {
  // Registrar acceso a endpoint protegido
  protectedEndpointAccessTotal.inc({
    endpoint: '/api/users',
    method: 'POST',
    auth_status: 'authenticated'
  });

  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    const randomUser = generateRandomUser();

    // Crear span custom para la transacción
    const span = trace.getActiveSpan();
    const tracer = trace.getTracer('users-api');
    const txSpan = tracer.startSpan('transaction.create_user', {}, trace.setSpan(context.active(), span));
    txSpan.setAttribute('user.gender', randomUser.gender);
    txSpan.setAttribute('user.country', randomUser.address.country);

    const addressResult = await clientQueryWithMetrics(
      client,
      `INSERT INTO addresses (street, street_name, building_number, city, zipcode, country, country_code, latitude, longitude)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING id`,
      [
        randomUser.address.street,
        randomUser.address.streetName,
        randomUser.address.buildingNumber,
        randomUser.address.city,
        randomUser.address.zipcode,
        randomUser.address.country,
        randomUser.address.country_code,
        randomUser.address.latitude,
        randomUser.address.longitude
      ],
      'INSERT',
      'addresses'
    );

    const addressId = addressResult.rows[0].id;

    const userResult = await clientQueryWithMetrics(
      client,
      `INSERT INTO users (firstname, lastname, email, phone, birthday, gender, address_id, website, image)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING id`,
      [
        randomUser.firstname,
        randomUser.lastname,
        randomUser.email,
        randomUser.phone,
        randomUser.birthday,
        randomUser.gender,
        addressId,
        randomUser.website,
        randomUser.image
      ],
      'INSERT',
      'users'
    );

    const userId = userResult.rows[0].id;

    await client.query('COMMIT');

    // Finalizar span custom
    txSpan.setStatus({ code: 0 }); // OK
    txSpan.end();

    const result = await queryWithMetrics(
      `SELECT u.*,
        json_build_object(
          'id', a.id,
          'street', a.street,
          'streetName', a.street_name,
          'buildingNumber', a.building_number,
          'city', a.city,
          'zipcode', a.zipcode,
          'country', a.country,
          'country_code', a.country_code,
          'latitude', a.latitude,
          'longitude', a.longitude
        ) as address
      FROM users u
      LEFT JOIN addresses a ON u.address_id = a.id
      WHERE u.id = $1`,
      [userId],
      'SELECT',
      'users'
    );

    const row = result.rows[0];
    const user = {
      id: row.id,
      firstname: row.firstname,
      lastname: row.lastname,
      email: row.email,
      phone: row.phone,
      birthday: row.birthday.toISOString().split('T')[0],
      gender: row.gender,
      address: row.address,
      website: row.website,
      image: row.image
    };

    // Incrementar métrica de negocio
    usersCreatedTotal.inc({ gender: user.gender });

    res.status(201).json(await buildResponse(user));
  } catch (error) {
    await client.query('ROLLBACK');

    // Finalizar span custom con error
    if (typeof txSpan !== 'undefined') {
      txSpan.setStatus({ code: 2, message: error.message }); // ERROR
      txSpan.recordException(error);
      txSpan.end();
    }

    // Registrar error con métricas
    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/users',
      status_code: '500'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Error creating user',
      error: error.message,
      errorStack: error.stack,
      endpoint: '/api/users',
      method: 'POST',
      requestId: req.id,
      correlationId: req.correlationId,
      timestamp: new Date().toISOString()
    }));

    res.status(500).json({
      status: "ERROR",
      code: 500,
      message: "Internal server error",
      requestId: req.id
    });
  } finally {
    client.release();
  }
});

app.put('/api/users/:id', authenticate, async (req, res) => {
  // Registrar acceso a endpoint protegido
  protectedEndpointAccessTotal.inc({
    endpoint: '/api/users/:id',
    method: 'PUT',
    auth_status: 'authenticated'
  });

  const client = await pool.connect();

  try {
    const userId = parseInt(req.params.id);

    if (isNaN(userId)) {
      return res.status(400).json({
        status: "ERROR",
        code: 400,
        message: "Invalid user ID"
      });
    }

    const checkUser = await queryWithMetrics('SELECT address_id FROM users WHERE id = $1', [userId], 'SELECT', 'users');

    if (checkUser.rows.length === 0) {
      return res.status(404).json({
        status: "ERROR",
        code: 404,
        message: "User not found"
      });
    }

    await client.query('BEGIN');

    const randomUser = generateRandomUser(userId);
    const addressId = checkUser.rows[0].address_id;

    if (addressId) {
      await clientQueryWithMetrics(
        client,
        `UPDATE addresses
         SET street = $1, street_name = $2, building_number = $3, city = $4,
             zipcode = $5, country = $6, country_code = $7, latitude = $8, longitude = $9
         WHERE id = $10`,
        [
          randomUser.address.street,
          randomUser.address.streetName,
          randomUser.address.buildingNumber,
          randomUser.address.city,
          randomUser.address.zipcode,
          randomUser.address.country,
          randomUser.address.country_code,
          randomUser.address.latitude,
          randomUser.address.longitude,
          addressId
        ],
        'UPDATE',
        'addresses'
      );
    }

    await clientQueryWithMetrics(
      client,
      `UPDATE users
       SET firstname = $1, lastname = $2, email = $3, phone = $4,
           birthday = $5, gender = $6, website = $7, image = $8
       WHERE id = $9`,
      [
        randomUser.firstname,
        randomUser.lastname,
        randomUser.email,
        randomUser.phone,
        randomUser.birthday,
        randomUser.gender,
        randomUser.website,
        randomUser.image,
        userId
      ],
      'UPDATE',
      'users'
    );

    await client.query('COMMIT');

    const result = await queryWithMetrics(
      `SELECT u.*,
        json_build_object(
          'id', a.id,
          'street', a.street,
          'streetName', a.street_name,
          'buildingNumber', a.building_number,
          'city', a.city,
          'zipcode', a.zipcode,
          'country', a.country,
          'country_code', a.country_code,
          'latitude', a.latitude,
          'longitude', a.longitude
        ) as address
      FROM users u
      LEFT JOIN addresses a ON u.address_id = a.id
      WHERE u.id = $1`,
      [userId],
      'SELECT',
      'users'
    );

    const row = result.rows[0];
    const user = {
      id: row.id,
      firstname: row.firstname,
      lastname: row.lastname,
      email: row.email,
      phone: row.phone,
      birthday: row.birthday.toISOString().split('T')[0],
      gender: row.gender,
      address: row.address,
      website: row.website,
      image: row.image
    };

    // Incrementar métrica de negocio
    usersUpdatedTotal.inc();

    res.json(await buildResponse(user));
  } catch (error) {
    await client.query('ROLLBACK');

    // Registrar error con métricas
    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/users/:id',
      status_code: '500'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Error updating user',
      error: error.message,
      errorStack: error.stack,
      endpoint: '/api/users/:id',
      method: 'PUT',
      userId: req.params.id,
      requestId: req.id,
      correlationId: req.correlationId,
      timestamp: new Date().toISOString()
    }));

    res.status(500).json({
      status: "ERROR",
      code: 500,
      message: "Internal server error",
      requestId: req.id
    });
  } finally {
    client.release();
  }
});

app.delete('/api/users/:id', authenticate, async (req, res) => {
  // Registrar acceso a endpoint protegido
  protectedEndpointAccessTotal.inc({
    endpoint: '/api/users/:id',
    method: 'DELETE',
    auth_status: 'authenticated'
  });

  try {
    const userId = parseInt(req.params.id);

    if (isNaN(userId)) {
      return res.status(400).json({
        status: "ERROR",
        code: 400,
        message: "Invalid user ID"
      });
    }

    const result = await queryWithMetrics('DELETE FROM users WHERE id = $1 RETURNING id', [userId], 'DELETE', 'users');

    if (result.rows.length === 0) {
      return res.status(404).json({
        status: "ERROR",
        code: 404,
        message: "User not found",
        requestId: req.id
      });
    }

    // Incrementar métrica de negocio
    usersDeletedTotal.inc();

    res.json({
      status: "OK",
      code: 200,
      message: "User deleted successfully",
      requestId: req.id
    });
  } catch (error) {
    // Registrar error con métricas
    apiErrorsTotal.inc({
      error_type: error.name || 'UnknownError',
      endpoint: '/api/users/:id',
      status_code: '500'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Error deleting user',
      error: error.message,
      errorStack: error.stack,
      endpoint: '/api/users/:id',
      method: 'DELETE',
      userId: req.params.id,
      requestId: req.id,
      correlationId: req.correlationId,
      timestamp: new Date().toISOString()
    }));

    res.status(500).json({
      status: "ERROR",
      code: 500,
      message: "Internal server error",
      requestId: req.id
    });
  }
});

// ==================== CUSTOMER AUTH ENDPOINTS ====================

/**
 * POST /api/auth/register
 * Registro de nuevo cliente con email + password
 */
app.post('/api/auth/register', async (req, res) => {
  try {
    const { firstname, lastname, email, password } = req.body;

    if (!firstname || !lastname || !email || !password) {
      return res.status(400).json({
        status: 'ERROR', code: 400,
        message: 'firstname, lastname, email and password are required',
        requestId: req.id
      });
    }

    if (password.length < 6) {
      return res.status(400).json({
        status: 'ERROR', code: 400,
        message: 'Password must be at least 6 characters',
        requestId: req.id
      });
    }

    const existing = await queryWithMetrics(
      'SELECT id FROM users WHERE email = $1', [email], 'SELECT', 'users'
    );

    if (existing.rows.length > 0) {
      return res.status(409).json({
        status: 'ERROR', code: 409,
        message: 'Email already registered',
        requestId: req.id
      });
    }

    const password_hash = await bcrypt.hash(password, BCRYPT_ROUNDS);
    const avatarUrl = `https://ui-avatars.com/api/?name=${encodeURIComponent(firstname + '+' + lastname)}&background=random`;

    const result = await queryWithMetrics(
      `INSERT INTO users (firstname, lastname, email, phone, birthday, gender, website, image, password_hash, role)
       VALUES ($1, $2, $3, '+56900000000', '1990-01-01', 'other', '', $4, $5, 'customer')
       RETURNING id, firstname, lastname, email, role`,
      [firstname, lastname, email, avatarUrl, password_hash],
      'INSERT', 'users'
    );

    const user = result.rows[0];
    const token = generateToken({ id: user.id, email: user.email, role: user.role });

    const tracer = trace.getTracer('users-api');
    const span = tracer.startSpan('ecommerce.user_register', {}, context.active());
    span.setAttribute('user.email', email);
    span.setAttribute('user.role', 'customer');
    span.setAttribute('session.id', req.sessionId || '');
    span.end();

    authRegistrationsTotal.inc();
    logger.info('Customer registered', { requestId: req.id, sessionId: req.sessionId, userId: user.id, email });

    res.status(201).json({
      status: 'OK', code: 201,
      message: 'Registration successful',
      data: {
        token, token_type: 'Bearer',
        expires_in: process.env.JWT_EXPIRATION || '24h',
        user: { id: user.id, firstname: user.firstname, lastname: user.lastname, email: user.email, role: user.role }
      },
      requestId: req.id
    });
  } catch (error) {
    logger.error('Error in registration', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

/**
 * POST /api/auth/login
 * Login de cliente con email + password
 */
app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      authLoginAttemptsTotal.inc({ status: 'missing_credentials' });
      return res.status(400).json({
        status: 'ERROR', code: 400,
        message: 'email and password are required',
        requestId: req.id
      });
    }

    const result = await queryWithMetrics(
      'SELECT id, firstname, lastname, email, password_hash, role FROM users WHERE email = $1',
      [email], 'SELECT', 'users'
    );

    if (result.rows.length === 0) {
      authLoginAttemptsTotal.inc({ status: 'user_not_found' });
      return res.status(401).json({
        status: 'ERROR', code: 401,
        message: 'Invalid email or password',
        requestId: req.id
      });
    }

    const user = result.rows[0];

    if (!user.password_hash) {
      authLoginAttemptsTotal.inc({ status: 'no_password' });
      return res.status(401).json({
        status: 'ERROR', code: 401,
        message: 'Invalid email or password',
        requestId: req.id
      });
    }

    const valid = await bcrypt.compare(password, user.password_hash);

    if (!valid) {
      authLoginAttemptsTotal.inc({ status: 'wrong_password' });
      return res.status(401).json({
        status: 'ERROR', code: 401,
        message: 'Invalid email or password',
        requestId: req.id
      });
    }

    const token = generateToken({ id: user.id, email: user.email, role: user.role });

    const loginTracer = trace.getTracer('users-api');
    const loginSpan = loginTracer.startSpan('ecommerce.user_login', {}, context.active());
    loginSpan.setAttribute('user.id', String(user.id));
    loginSpan.setAttribute('user.email', user.email);
    loginSpan.setAttribute('session.id', req.sessionId || '');
    loginSpan.end();

    authLoginAttemptsTotal.inc({ status: 'success' });
    logger.info('Customer login successful', { requestId: req.id, sessionId: req.sessionId, userId: user.id });

    res.json({
      status: 'OK', code: 200,
      message: 'Login successful',
      data: {
        token, token_type: 'Bearer',
        expires_in: process.env.JWT_EXPIRATION || '24h',
        user: { id: user.id, firstname: user.firstname, lastname: user.lastname, email: user.email, role: user.role }
      },
      requestId: req.id
    });
  } catch (error) {
    logger.error('Error in login', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

/**
 * GET /api/auth/me
 * Perfil del usuario autenticado
 */
app.get('/api/auth/me', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;

    if (!userId) {
      return res.status(400).json({
        status: 'ERROR', code: 400,
        message: 'Token does not contain user ID',
        requestId: req.id
      });
    }

    const result = await queryWithMetrics(
      `SELECT u.id, u.firstname, u.lastname, u.email, u.phone, u.birthday, u.gender, u.role, u.image, u.created_at,
        json_build_object('id', a.id, 'street', a.street, 'city', a.city, 'country', a.country) as address
       FROM users u LEFT JOIN addresses a ON u.address_id = a.id
       WHERE u.id = $1`,
      [userId], 'SELECT', 'users'
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ status: 'ERROR', code: 404, message: 'User not found', requestId: req.id });
    }

    const row = result.rows[0];
    res.json({
      status: 'OK', code: 200,
      data: {
        id: row.id, firstname: row.firstname, lastname: row.lastname,
        email: row.email, phone: row.phone, birthday: row.birthday,
        gender: row.gender, role: row.role, image: row.image,
        address: row.address, created_at: row.created_at
      },
      requestId: req.id
    });
  } catch (error) {
    logger.error('Error fetching profile', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// Endpoint de métricas para Prometheus
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});

// Health check - Liveness probe (proceso vivo)
app.get('/health/live', (req, res) => {
  res.json({
    status: 'OK',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    service: 'users-api'
  });
});

// Health check - Readiness probe (listo para recibir tráfico)
app.get('/health/ready', async (req, res) => {
  try {
    // Verificar conexión a base de datos
    await pool.query('SELECT 1');

    // Actualizar métrica de conexiones activas
    dbConnectionsActive.set(pool.totalCount);

    res.json({
      status: 'OK',
      timestamp: new Date().toISOString(),
      checks: {
        database: 'connected',
        dbConnections: {
          total: pool.totalCount,
          idle: pool.idleCount,
          waiting: pool.waitingCount
        }
      }
    });
  } catch (error) {
    // Registrar error
    apiErrorsTotal.inc({
      error_type: 'DatabaseConnectionError',
      endpoint: '/health/ready',
      status_code: '503'
    });

    console.error(JSON.stringify({
      level: 'error',
      message: 'Health check failed',
      error: error.message,
      timestamp: new Date().toISOString()
    }));

    res.status(503).json({
      status: 'ERROR',
      timestamp: new Date().toISOString(),
      checks: {
        database: 'disconnected',
        error: error.message
      }
    });
  }
});

// Health check - Backward compatibility
app.get('/health', (req, res) => {
  res.json({ status: 'OK', timestamp: new Date().toISOString() });
});

// ==================== PROFILING ENDPOINTS ====================

// Endpoint: Heap Snapshot (memoria)
app.get('/debug/heapsnapshot', (req, res) => {
  const v8 = require('v8');
  const fs = require('fs');
  const path = require('path');

  try {
    const filename = `heapsnapshot-${Date.now()}.heapsnapshot`;
    const filepath = path.join('/tmp', filename);

    // Generar heap snapshot
    const snapshotStream = v8.writeHeapSnapshot(filepath);

    logger.info('Heap snapshot generated', { filepath, filename });

    res.json({
      status: 'OK',
      message: 'Heap snapshot generated',
      filepath,
      filename,
      note: 'Use Chrome DevTools to analyze the snapshot'
    });
  } catch (error) {
    logger.error('Error generating heap snapshot', { error: error.message });
    res.status(500).json({
      status: 'ERROR',
      error: error.message
    });
  }
});

// Endpoint: Memory stats
app.get('/debug/memory', (req, res) => {
  const usage = process.memoryUsage();

  res.json({
    status: 'OK',
    timestamp: new Date().toISOString(),
    memory: {
      rss: `${Math.round(usage.rss / 1024 / 1024)} MB`,
      heapTotal: `${Math.round(usage.heapTotal / 1024 / 1024)} MB`,
      heapUsed: `${Math.round(usage.heapUsed / 1024 / 1024)} MB`,
      external: `${Math.round(usage.external / 1024 / 1024)} MB`,
      arrayBuffers: `${Math.round(usage.arrayBuffers / 1024 / 1024)} MB`
    },
    raw: usage
  });
});

// Endpoint: CPU profile (requiere --inspect flag)
app.get('/debug/profile/start', (req, res) => {
  try {
    const inspector = require('inspector');
    const session = new inspector.Session();
    session.connect();

    session.post('Profiler.enable', () => {
      session.post('Profiler.start', () => {
        // Guardar la sesión en el objeto global para poder detenerla después
        global.__profilerSession = session;

        logger.info('CPU profiler started');

        res.json({
          status: 'OK',
          message: 'CPU profiler started',
          note: 'Call /debug/profile/stop to stop and get the profile'
        });
      });
    });
  } catch (error) {
    logger.error('Error starting CPU profiler', { error: error.message });
    res.status(500).json({
      status: 'ERROR',
      error: error.message,
      note: 'Node.js might not have been started with --inspect flag'
    });
  }
});

app.get('/debug/profile/stop', (req, res) => {
  try {
    const session = global.__profilerSession;

    if (!session) {
      return res.status(400).json({
        status: 'ERROR',
        message: 'Profiler not running. Start it first with /debug/profile/start'
      });
    }

    session.post('Profiler.stop', (err, { profile }) => {
      session.disconnect();
      global.__profilerSession = null;

      if (err) {
        logger.error('Error stopping CPU profiler', { error: err.message });
        return res.status(500).json({
          status: 'ERROR',
          error: err.message
        });
      }

      const fs = require('fs');
      const filename = `cpuprofile-${Date.now()}.cpuprofile`;
      const filepath = `/tmp/${filename}`;

      fs.writeFileSync(filepath, JSON.stringify(profile));

      logger.info('CPU profile generated', { filepath, filename });

      res.json({
        status: 'OK',
        message: 'CPU profiler stopped',
        filepath,
        filename,
        duration: profile.endTime - profile.startTime,
        note: 'Use Chrome DevTools to analyze the profile'
      });
    });
  } catch (error) {
    logger.error('Error stopping CPU profiler', { error: error.message });
    res.status(500).json({
      status: 'ERROR',
      error: error.message
    });
  }
});

// Endpoint: Event Loop stats
app.get('/debug/eventloop', (req, res) => {
  const perf = require('perf_hooks').performance;

  res.json({
    status: 'OK',
    timestamp: new Date().toISOString(),
    eventLoop: {
      utilizationSince1m: perf.eventLoopUtilization(),
      lag: process.hrtime.bigint() // Aproximación simple
    },
    uptime: `${Math.round(process.uptime())} seconds`
  });
});

async function waitForDatabase() {
  const maxRetries = 30;
  let retries = 0;

  while (retries < maxRetries) {
    try {
      await pool.query('SELECT 1');
      console.log('Database connection established');
      return;
    } catch (error) {
      retries++;
      console.log(`Waiting for database... (${retries}/${maxRetries})`);
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }

  throw new Error('Could not connect to database');
}

async function startServer() {
  try {
    await waitForDatabase();
    await runMigrations();

    // Actualizar métricas del pool cada 5 segundos
    setInterval(() => {
      updatePoolMetrics();
    }, 5000);

    // Actualizar métricas iniciales
    updatePoolMetrics();

    app.listen(PORT, '0.0.0.0', () => {
      console.log(`Server running on port ${PORT}`);
      console.log(`Health check: http://localhost:${PORT}/health`);
      console.log(`\nAPI endpoints:`);
      console.log(`  Authentication:`);
      console.log(`    POST   /api/auth/token          - Generate access token`);
      console.log(`\n  Users (read - public):`);
      console.log(`    GET    /api/users               - List users`);
      console.log(`    GET    /api/users/:id           - Get user by ID`);
      console.log(`\n  Users (write - requires authentication):`);
      console.log(`    POST   /api/users               - Create user`);
      console.log(`    PUT    /api/users/:id           - Update user`);
      console.log(`    DELETE /api/users/:id           - Delete user`);
      console.log(`\nAuthentication: Include "Authorization: Bearer <token>" header`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

startServer();
