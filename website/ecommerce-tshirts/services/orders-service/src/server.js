require('./tracing');
require('dotenv').config();
const express = require('express');
const pool = require('./db');
const { runMigrations } = require('./migrate');
const promClient = require('prom-client');
const { trace, context, propagation, SpanStatusCode } = require('@opentelemetry/api');
const { randomUUID } = require('crypto');
const logger = require('./logger');
const jwt = require('jsonwebtoken');
const fetch = require('node-fetch');

const app = express();
const PORT = process.env.PORT || 3004;
const JWT_SECRET = process.env.JWT_SECRET || 'ecommerce-jwt-secret-2026';
const CART_SERVICE_URL = process.env.CART_SERVICE_URL || 'http://cart-service:3003';
const PRODUCTS_SERVICE_URL = process.env.PRODUCTS_SERVICE_URL || 'http://products-service:3002';

// ==================== PROMETHEUS METRICS ====================
const register = new promClient.Registry();
promClient.collectDefaultMetrics({ register });

const httpRequestDuration = new promClient.Histogram({
  name: 'http_request_duration_seconds', help: 'Duration of HTTP requests in seconds',
  labelNames: ['method', 'route', 'status_code'], registers: [register]
});
const httpRequestTotal = new promClient.Counter({
  name: 'http_requests_total', help: 'Total number of HTTP requests',
  labelNames: ['method', 'route', 'status_code'], registers: [register]
});
const ordersCreatedTotal = new promClient.Counter({
  name: 'orders_created_total', help: 'Total orders created', registers: [register]
});
const ordersByStatusGauge = new promClient.Gauge({
  name: 'orders_by_status', help: 'Orders count by status',
  labelNames: ['status'], registers: [register]
});
const orderValueHistogram = new promClient.Histogram({
  name: 'order_value_clp', help: 'Order value in CLP',
  buckets: [5000, 10000, 20000, 50000, 100000, 200000], registers: [register]
});
const dbQueryDuration = new promClient.Histogram({
  name: 'db_query_duration_seconds', help: 'Database query duration in seconds',
  labelNames: ['query_type', 'table', 'status'],
  buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
  registers: [register]
});
const dbQueriesTotal = new promClient.Counter({
  name: 'db_queries_total', help: 'Total number of database queries',
  labelNames: ['query_type', 'table', 'status'], registers: [register]
});
const apiErrorsTotal = new promClient.Counter({
  name: 'api_errors_total', help: 'Total API errors',
  labelNames: ['error_type', 'endpoint', 'status_code'], registers: [register]
});
const dbConnectionsActive = new promClient.Gauge({ name: 'db_connections_active', help: 'Active DB connections', registers: [register] });
const dbConnectionsIdle = new promClient.Gauge({ name: 'db_connections_idle', help: 'Idle DB connections', registers: [register] });
const dbConnectionsTotal = new promClient.Gauge({ name: 'db_connections_total', help: 'Total DB connections', registers: [register] });

function updatePoolMetrics() {
  dbConnectionsTotal.set(pool.totalCount);
  dbConnectionsIdle.set(pool.idleCount);
  dbConnectionsActive.set(pool.totalCount - pool.idleCount);
}

async function queryWithMetrics(sql, params, queryType, table) {
  const end = dbQueryDuration.startTimer({ query_type: queryType, table });
  try {
    const result = await pool.query(sql, params);
    updatePoolMetrics();
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'success' });
    end({ status: 'success' });
    return result;
  } catch (error) {
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'error' });
    end({ status: 'error' });
    logger.error('Database query error', { queryType, table, error: error.message });
    throw error;
  }
}

async function clientQueryWithMetrics(client, sql, params, queryType, table) {
  const end = dbQueryDuration.startTimer({ query_type: queryType, table });
  try {
    const result = await client.query(sql, params);
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'success' });
    end({ status: 'success' });
    return result;
  } catch (error) {
    dbQueriesTotal.inc({ query_type: queryType, table, status: 'error' });
    end({ status: 'error' });
    throw error;
  }
}

// ==================== MIDDLEWARE ====================
app.use(express.json());

app.use((req, res, next) => {
  req.id = req.headers['x-request-id'] || randomUUID();
  req.correlationId = req.headers['x-correlation-id'] || req.id;
  req.sessionId = req.headers['x-session-id'] || '';
  res.setHeader('x-request-id', req.id);
  res.setHeader('x-correlation-id', req.correlationId);
  next();
});

app.use((req, res, next) => {
  const span = trace.getActiveSpan();
  if (span) {
    span.setAttribute('request.id', req.id);
    span.setAttribute('correlation.id', req.correlationId);
    span.setAttribute('service.name', 'orders-service');
  }
  next();
});

app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    const route = req.route ? req.route.path : req.path;
    httpRequestDuration.labels(req.method, route, res.statusCode).observe(duration / 1000);
    httpRequestTotal.labels(req.method, route, res.statusCode).inc();
    logger.child({ requestId: req.id, correlationId: req.correlationId, sessionId: req.sessionId }).logRequest(req, res, duration);
  });
  next();
});

function authenticate(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.startsWith('Bearer ') ? authHeader.substring(7) : null;
  if (!token) return res.status(401).json({ status: 'ERROR', code: 401, message: 'Authentication required', requestId: req.id });
  try {
    req.auth = { tokenPayload: jwt.verify(token, JWT_SECRET), authenticated: true };
    next();
  } catch {
    return res.status(401).json({ status: 'ERROR', code: 401, message: 'Invalid or expired token', requestId: req.id });
  }
}

function getTraceHeaders(req) {
  const headers = { 'x-request-id': req.id, 'x-correlation-id': req.correlationId, 'Content-Type': 'application/json' };
  propagation.inject(context.active(), headers);
  if (req.headers['authorization']) headers['authorization'] = req.headers['authorization'];
  return headers;
}

function generateOrderNumber(id) {
  return `POL-${new Date().getFullYear()}-${String(id).padStart(5, '0')}`;
}

// ==================== ENDPOINTS ====================

// POST /api/orders — create order from active cart
app.post('/api/orders', authenticate, async (req, res) => {
  const tracer = trace.getTracer('orders-service');
  const span = tracer.startSpan('ecommerce.create_order', {}, context.active());

  const client = await pool.connect();
  try {
    const userId = req.auth.tokenPayload.id;
    const { shipping_address } = req.body;

    // 1. Fetch active cart from cart-service
    span.setAttribute('order.user_id', userId);
    span.setAttribute('session.id', req.sessionId || '');
    const cartRes = await fetch(`${CART_SERVICE_URL}/api/cart`, { headers: getTraceHeaders(req) });
    if (!cartRes.ok) {
      span.setAttribute('error', true);
      return res.status(400).json({ status: 'ERROR', code: 400, message: 'Could not fetch cart', requestId: req.id });
    }
    const cartData = await cartRes.json();
    const cart = cartData.data;

    if (!cart.items || cart.items.length === 0) {
      return res.status(400).json({ status: 'ERROR', code: 400, message: 'Cart is empty', requestId: req.id });
    }

    span.setAttribute('order.items_count', cart.items.length);
    span.setAttribute('order.total', cart.total);

    // 2. Create order in DB (transaction)
    await client.query('BEGIN');

    // Get next ID for order number generation
    const seqResult = await clientQueryWithMetrics(client, 'SELECT nextval(\'orders_id_seq\')', [], 'SELECT', 'orders');
    const orderId = parseInt(seqResult.rows[0].nextval);
    const orderNumber = generateOrderNumber(orderId);

    const subtotal = cart.subtotal;
    const tax = cart.tax;
    const shippingCost = subtotal >= 50000 ? 0 : 3990; // Free shipping over 50k CLP
    const total = subtotal + tax + shippingCost;

    const orderResult = await clientQueryWithMetrics(
      client,
      `INSERT INTO orders (id, order_number, user_id, status, subtotal, tax, shipping_cost, total, shipping_address)
       VALUES ($1, $2, $3, 'pending', $4, $5, $6, $7, $8) RETURNING *`,
      [orderId, orderNumber, userId, subtotal, tax, shippingCost, total, JSON.stringify(shipping_address || {})],
      'INSERT', 'orders'
    );

    // 3. Insert order items
    for (const item of cart.items) {
      await clientQueryWithMetrics(
        client,
        `INSERT INTO order_items (order_id, product_id, variant_id, product_name, variant_description, quantity, unit_price, subtotal)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
        [orderId, item.product_id, item.variant_id, item.product_name, item.variant_description, item.quantity, item.unit_price, item.unit_price * item.quantity],
        'INSERT', 'order_items'
      );
    }

    await client.query('COMMIT');

    // 4. Decrement stock in products-service (best effort)
    for (const item of cart.items) {
      try {
        await fetch(`${PRODUCTS_SERVICE_URL}/api/products/variant/${item.variant_id}/stock`, {
          method: 'PATCH',
          headers: getTraceHeaders(req),
          body: JSON.stringify({ quantity: item.quantity })
        });
      } catch (stockErr) {
        logger.warn('Failed to decrement stock', { variantId: item.variant_id, error: stockErr.message });
      }
    }

    // 5. Convert cart to order (mark as converted)
    try {
      await fetch(`${CART_SERVICE_URL}/api/cart/convert`, { method: 'POST', headers: getTraceHeaders(req) });
    } catch (cartErr) {
      logger.warn('Failed to convert cart', { error: cartErr.message });
    }

    // Metrics
    ordersCreatedTotal.inc();
    orderValueHistogram.observe(total);

    // Update status gauges
    const statusCounts = await queryWithMetrics('SELECT status, COUNT(*) FROM orders GROUP BY status', [], 'SELECT', 'orders');
    statusCounts.rows.forEach(row => ordersByStatusGauge.set({ status: row.status }, parseInt(row.count)));

    span.setAttribute('order.id', orderId);
    span.setAttribute('order.number', orderNumber);
    span.setAttribute('order.status', 'pending');
    span.setStatus({ code: SpanStatusCode.OK });
    span.end();

    logger.info('Order created', { orderId, orderNumber, userId, total, requestId: req.id, sessionId: req.sessionId });

    const order = orderResult.rows[0];
    const itemsResult = await queryWithMetrics('SELECT * FROM order_items WHERE order_id = $1', [orderId], 'SELECT', 'order_items');

    res.status(201).json({
      status: 'OK', code: 201, message: 'Order created successfully',
      data: { ...order, items: itemsResult.rows },
      requestId: req.id
    });
  } catch (error) {
    await client.query('ROLLBACK');
    span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
    span.recordException(error);
    span.end();
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/orders', status_code: '500' });
    logger.error('Error creating order', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  } finally {
    client.release();
  }
});

// GET /api/orders — list user's orders
app.get('/api/orders', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const limit = parseInt(req.query.limit) || 10;
    const offset = parseInt(req.query.offset) || 0;

    const countResult = await queryWithMetrics('SELECT COUNT(*) FROM orders WHERE user_id = $1', [userId], 'SELECT', 'orders');
    const total = parseInt(countResult.rows[0].count);

    const result = await queryWithMetrics(
      'SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',
      [userId, limit, offset], 'SELECT', 'orders'
    );

    res.json({ status: 'OK', code: 200, data: result.rows, total, limit, offset, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/orders', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/orders/:id — order detail
app.get('/api/orders/:id', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const orderId = parseInt(req.params.id);

    const orderResult = await queryWithMetrics(
      'SELECT * FROM orders WHERE id = $1 AND user_id = $2',
      [orderId, userId], 'SELECT', 'orders'
    );

    if (orderResult.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Order not found', requestId: req.id });

    const itemsResult = await queryWithMetrics('SELECT * FROM order_items WHERE order_id = $1', [orderId], 'SELECT', 'order_items');

    res.json({ status: 'OK', code: 200, data: { ...orderResult.rows[0], items: itemsResult.rows }, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/orders/:id', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// PATCH /api/orders/:id/status — update order status (called by payments-service)
app.patch('/api/orders/:id/status', authenticate, async (req, res) => {
  try {
    const orderId = parseInt(req.params.id);
    const { status } = req.body;
    const validStatuses = ['pending', 'paid', 'processing', 'shipped', 'delivered', 'cancelled'];

    if (!status || !validStatuses.includes(status)) {
      return res.status(400).json({ status: 'ERROR', code: 400, message: `Invalid status. Valid: ${validStatuses.join(', ')}`, requestId: req.id });
    }

    const result = await queryWithMetrics(
      'UPDATE orders SET status = $1, updated_at = NOW() WHERE id = $2 RETURNING *',
      [status, orderId], 'UPDATE', 'orders'
    );

    if (result.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Order not found', requestId: req.id });

    const span = trace.getActiveSpan();
    if (span) span.setAttribute('order.new_status', status);

    // Update status gauges
    const statusCounts = await queryWithMetrics('SELECT status, COUNT(*) FROM orders GROUP BY status', [], 'SELECT', 'orders');
    statusCounts.rows.forEach(row => ordersByStatusGauge.set({ status: row.status }, parseInt(row.count)));

    res.json({ status: 'OK', code: 200, message: `Order status updated to ${status}`, data: result.rows[0], requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/orders/:id/status', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// ==================== HEALTH + METRICS ====================
app.get('/metrics', async (req, res) => { res.set('Content-Type', register.contentType); res.end(await register.metrics()); });
app.get('/health/live', (req, res) => res.json({ status: 'OK', timestamp: new Date().toISOString(), uptime: process.uptime(), service: 'orders-service' }));
app.get('/health/ready', async (req, res) => {
  try { await pool.query('SELECT 1'); res.json({ status: 'OK', timestamp: new Date().toISOString(), checks: { database: 'connected' } }); }
  catch (error) { res.status(503).json({ status: 'ERROR', timestamp: new Date().toISOString(), checks: { database: 'disconnected', error: error.message } }); }
});
app.get('/health', (req, res) => res.json({ status: 'OK', timestamp: new Date().toISOString() }));

// ==================== SERVER START ====================
async function waitForDatabase() {
  for (let i = 0; i < 30; i++) {
    try { await pool.query('SELECT 1'); console.log('Database connected'); return; }
    catch { console.log(`Waiting for database... (${i + 1}/30)`); await new Promise(r => setTimeout(r, 2000)); }
  }
  throw new Error('Could not connect to database');
}

async function startServer() {
  await waitForDatabase();
  await runMigrations();
  setInterval(updatePoolMetrics, 5000);
  updatePoolMetrics();
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Orders Service running on port ${PORT}`);
    console.log('  POST  /api/orders           - Create order from cart');
    console.log('  GET   /api/orders           - List user orders');
    console.log('  GET   /api/orders/:id       - Order detail');
    console.log('  PATCH /api/orders/:id/status - Update order status');
  });
}

startServer().catch(err => { console.error('Failed to start:', err); process.exit(1); });
