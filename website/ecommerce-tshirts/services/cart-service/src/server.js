require('./tracing');
require('dotenv').config();
const express = require('express');
const pool = require('./db');
const { runMigrations } = require('./migrate');
const promClient = require('prom-client');
const { trace, context, propagation } = require('@opentelemetry/api');
const { randomUUID } = require('crypto');
const logger = require('./logger');
const jwt = require('jsonwebtoken');
const fetch = require('node-fetch');

const app = express();
const PORT = process.env.PORT || 3003;
const JWT_SECRET = process.env.JWT_SECRET || 'ecommerce-jwt-secret-2026';
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
const cartItemsAddedTotal = new promClient.Counter({
  name: 'cart_items_added_total', help: 'Total items added to carts', registers: [register]
});
const cartItemsRemovedTotal = new promClient.Counter({
  name: 'cart_items_removed_total', help: 'Total items removed from carts', registers: [register]
});
const cartsConvertedTotal = new promClient.Counter({
  name: 'carts_converted_total', help: 'Total carts converted to orders', registers: [register]
});
const activeCartsGauge = new promClient.Gauge({
  name: 'carts_active', help: 'Number of active carts', registers: [register]
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
    span.setAttribute('service.name', 'cart-service');
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

// Helper to propagate trace context headers
function getTraceHeaders(req) {
  const headers = { 'x-request-id': req.id, 'x-correlation-id': req.correlationId, 'Content-Type': 'application/json' };
  propagation.inject(context.active(), headers);
  if (req.headers['authorization']) headers['authorization'] = req.headers['authorization'];
  return headers;
}

// Get or create active cart for user
async function getOrCreateCart(userId) {
  let result = await queryWithMetrics(
    'SELECT id FROM carts WHERE user_id = $1 AND status = $2 LIMIT 1',
    [userId, 'active'], 'SELECT', 'carts'
  );
  if (result.rows.length > 0) return result.rows[0].id;

  result = await queryWithMetrics(
    'INSERT INTO carts (user_id, status) VALUES ($1, $2) RETURNING id',
    [userId, 'active'], 'INSERT', 'carts'
  );
  return result.rows[0].id;
}

async function getCartWithItems(cartId) {
  const cart = await queryWithMetrics('SELECT * FROM carts WHERE id = $1', [cartId], 'SELECT', 'carts');
  const items = await queryWithMetrics(
    'SELECT * FROM cart_items WHERE cart_id = $1 ORDER BY added_at',
    [cartId], 'SELECT', 'cart_items'
  );

  const subtotal = items.rows.reduce((sum, item) => sum + parseFloat(item.unit_price) * item.quantity, 0);
  const tax = subtotal * 0.19;
  const total = subtotal + tax;

  return { ...cart.rows[0], items: items.rows, subtotal: Math.round(subtotal), tax: Math.round(tax), total: Math.round(total) };
}

// ==================== ENDPOINTS ====================

// GET /api/cart — get active cart for authenticated user
app.get('/api/cart', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const cartId = await getOrCreateCart(userId);
    const cart = await getCartWithItems(cartId);

    const activeCount = await queryWithMetrics('SELECT COUNT(*) FROM carts WHERE status = $1', ['active'], 'SELECT', 'carts');
    activeCartsGauge.set(parseInt(activeCount.rows[0].count));

    res.json({ status: 'OK', code: 200, data: cart, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart', status_code: '500' });
    logger.error('Error fetching cart', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// POST /api/cart/items — add item to cart
app.post('/api/cart/items', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const { variant_id, quantity = 1 } = req.body;

    if (!variant_id || quantity <= 0 || quantity > 10) {
      return res.status(400).json({ status: 'ERROR', code: 400, message: 'variant_id required and quantity must be 1-10', requestId: req.id });
    }

    // Fetch variant info from products-service
    const variantRes = await fetch(`${PRODUCTS_SERVICE_URL}/api/products/variant/${variant_id}`, {
      headers: getTraceHeaders(req)
    });

    if (!variantRes.ok) {
      const err = await variantRes.json();
      return res.status(variantRes.status).json({ status: 'ERROR', code: variantRes.status, message: err.message || 'Product variant not found', requestId: req.id });
    }

    const variantData = await variantRes.json();
    const variant = variantData.data;

    if (variant.stock < quantity) {
      return res.status(409).json({ status: 'ERROR', code: 409, message: `Insufficient stock. Available: ${variant.stock}`, requestId: req.id });
    }

    const cartId = await getOrCreateCart(userId);
    const variantDesc = `${variant.size} / ${variant.color}`;

    // Check if this variant is already in the cart
    const existing = await queryWithMetrics(
      'SELECT id, quantity FROM cart_items WHERE cart_id = $1 AND variant_id = $2',
      [cartId, variant_id], 'SELECT', 'cart_items'
    );

    if (existing.rows.length > 0) {
      const newQty = existing.rows[0].quantity + quantity;
      if (newQty > 10) return res.status(409).json({ status: 'ERROR', code: 409, message: 'Max 10 units per item', requestId: req.id });
      if (newQty > variant.stock) return res.status(409).json({ status: 'ERROR', code: 409, message: `Insufficient stock. Available: ${variant.stock}`, requestId: req.id });

      await queryWithMetrics(
        'UPDATE cart_items SET quantity = $1 WHERE id = $2',
        [newQty, existing.rows[0].id], 'UPDATE', 'cart_items'
      );
    } else {
      await queryWithMetrics(
        `INSERT INTO cart_items (cart_id, product_id, variant_id, product_name, variant_description, quantity, unit_price)
         VALUES ($1, $2, $3, $4, $5, $6, $7)`,
        [cartId, variant.product_id, variant_id, variant.product_name, variantDesc, quantity, parseFloat(variant.price)],
        'INSERT', 'cart_items'
      );
    }

    await queryWithMetrics('UPDATE carts SET updated_at = NOW() WHERE id = $1', [cartId], 'UPDATE', 'carts');

    const span = trace.getActiveSpan();
    if (span) {
      span.setAttribute('cart.action', 'add_item');
      span.setAttribute('cart.variant_id', variant_id);
      span.setAttribute('cart.product_name', variant.product_name);
    }

    cartItemsAddedTotal.inc();
    const cart = await getCartWithItems(cartId);
    res.status(201).json({ status: 'OK', code: 201, message: 'Item added to cart', data: cart, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart/items', status_code: '500' });
    logger.error('Error adding item to cart', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// PUT /api/cart/items/:itemId — update quantity
app.put('/api/cart/items/:itemId', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const itemId = parseInt(req.params.itemId);
    const { quantity } = req.body;

    if (isNaN(itemId) || !quantity || quantity <= 0 || quantity > 10) {
      return res.status(400).json({ status: 'ERROR', code: 400, message: 'Valid quantity (1-10) required', requestId: req.id });
    }

    const cartResult = await queryWithMetrics(
      `SELECT ci.id, ci.cart_id, ci.variant_id FROM cart_items ci
       JOIN carts c ON ci.cart_id = c.id
       WHERE ci.id = $1 AND c.user_id = $2 AND c.status = 'active'`,
      [itemId, userId], 'SELECT', 'cart_items'
    );

    if (cartResult.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Cart item not found', requestId: req.id });

    await queryWithMetrics('UPDATE cart_items SET quantity = $1 WHERE id = $2', [quantity, itemId], 'UPDATE', 'cart_items');
    await queryWithMetrics('UPDATE carts SET updated_at = NOW() WHERE id = $1', [cartResult.rows[0].cart_id], 'UPDATE', 'carts');

    const cart = await getCartWithItems(cartResult.rows[0].cart_id);
    res.json({ status: 'OK', code: 200, message: 'Cart item updated', data: cart, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart/items/:itemId', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// DELETE /api/cart/items/:itemId — remove item
app.delete('/api/cart/items/:itemId', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const itemId = parseInt(req.params.itemId);

    const cartResult = await queryWithMetrics(
      `SELECT ci.cart_id FROM cart_items ci JOIN carts c ON ci.cart_id = c.id
       WHERE ci.id = $1 AND c.user_id = $2 AND c.status = 'active'`,
      [itemId, userId], 'SELECT', 'cart_items'
    );

    if (cartResult.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Cart item not found', requestId: req.id });

    const cartId = cartResult.rows[0].cart_id;
    await queryWithMetrics('DELETE FROM cart_items WHERE id = $1', [itemId], 'DELETE', 'cart_items');
    await queryWithMetrics('UPDATE carts SET updated_at = NOW() WHERE id = $1', [cartId], 'UPDATE', 'carts');

    cartItemsRemovedTotal.inc();
    const cart = await getCartWithItems(cartId);
    res.json({ status: 'OK', code: 200, message: 'Item removed from cart', data: cart, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart/items/:itemId', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// DELETE /api/cart — clear entire cart
app.delete('/api/cart', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const cartResult = await queryWithMetrics(
      'SELECT id FROM carts WHERE user_id = $1 AND status = $2 LIMIT 1',
      [userId, 'active'], 'SELECT', 'carts'
    );

    if (cartResult.rows.length === 0) return res.json({ status: 'OK', code: 200, message: 'Cart is already empty', requestId: req.id });

    const cartId = cartResult.rows[0].id;
    await queryWithMetrics('DELETE FROM cart_items WHERE cart_id = $1', [cartId], 'DELETE', 'cart_items');
    await queryWithMetrics('UPDATE carts SET updated_at = NOW() WHERE id = $1', [cartId], 'UPDATE', 'carts');

    res.json({ status: 'OK', code: 200, message: 'Cart cleared', data: { items: [], subtotal: 0, tax: 0, total: 0 }, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// POST /api/cart/convert — mark cart as converted (called by orders-service)
app.post('/api/cart/convert', authenticate, async (req, res) => {
  try {
    const userId = req.auth.tokenPayload.id;
    const result = await queryWithMetrics(
      'UPDATE carts SET status = $1, updated_at = NOW() WHERE user_id = $2 AND status = $3 RETURNING id',
      ['converted', userId, 'active'], 'UPDATE', 'carts'
    );

    if (result.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'No active cart found', requestId: req.id });

    cartsConvertedTotal.inc();
    res.json({ status: 'OK', code: 200, message: 'Cart converted to order', data: { cartId: result.rows[0].id }, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/cart/convert', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// ==================== HEALTH + METRICS ====================
app.get('/metrics', async (req, res) => { res.set('Content-Type', register.contentType); res.end(await register.metrics()); });
app.get('/health/live', (req, res) => res.json({ status: 'OK', timestamp: new Date().toISOString(), uptime: process.uptime(), service: 'cart-service' }));
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
    console.log(`Cart Service running on port ${PORT}`);
    console.log('  GET    /api/cart               - Get active cart');
    console.log('  POST   /api/cart/items         - Add item to cart');
    console.log('  PUT    /api/cart/items/:id     - Update item quantity');
    console.log('  DELETE /api/cart/items/:id     - Remove item');
    console.log('  DELETE /api/cart               - Clear cart');
    console.log('  POST   /api/cart/convert       - Convert cart to order');
  });
}

startServer().catch(err => { console.error('Failed to start:', err); process.exit(1); });
