require('./tracing');
require('dotenv').config();
const express = require('express');
const pool = require('./db');
const { runMigrations } = require('./migrate');
const promClient = require('prom-client');
const { trace } = require('@opentelemetry/api');
const { randomUUID } = require('crypto');
const logger = require('./logger');
const jwt = require('jsonwebtoken');

const app = express();
const PORT = process.env.PORT || 3002;
const JWT_SECRET = process.env.JWT_SECRET || 'ecommerce-jwt-secret-2026';

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
const productsViewedTotal = new promClient.Counter({
  name: 'products_viewed_total', help: 'Total product detail views',
  labelNames: ['category'], registers: [register]
});
const productsListedTotal = new promClient.Counter({
  name: 'products_listed_total', help: 'Total product list requests', registers: [register]
});
const stockCheckTotal = new promClient.Counter({
  name: 'stock_check_total', help: 'Total stock check requests',
  labelNames: ['result'], registers: [register]
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
const dbConnectionsActive = new promClient.Gauge({ name: 'db_connections_active', help: 'Active database connections', registers: [register] });
const dbConnectionsIdle = new promClient.Gauge({ name: 'db_connections_idle', help: 'Idle database connections', registers: [register] });
const dbConnectionsTotal = new promClient.Gauge({ name: 'db_connections_total', help: 'Total database connections', registers: [register] });

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
    span.setAttribute('deployment.environment', process.env.NODE_ENV || 'development');
    span.setAttribute('service.name', 'products-service');
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

// ==================== ENDPOINTS ====================

// GET /api/categories
app.get('/api/categories', async (req, res) => {
  try {
    const result = await queryWithMetrics('SELECT * FROM categories ORDER BY name', [], 'SELECT', 'categories');
    res.json({ status: 'OK', code: 200, data: result.rows, total: result.rows.length, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/categories', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/products?category=basica&size=M&min_price=5000&max_price=30000&limit=12&offset=0
app.get('/api/products', async (req, res) => {
  try {
    const { category, search, size, color, min_price, max_price, limit = 12, offset = 0 } = req.query;
    let whereConditions = ['p.is_active = true'];
    let params = [];
    let i = 0;

    if (category) { whereConditions.push(`c.slug = $${++i}`); params.push(category); }
    if (search) { ++i; whereConditions.push(`(p.name ILIKE $${i} OR p.description ILIKE $${i})`); params.push(`%${search}%`); }
    if (size) { whereConditions.push(`EXISTS (SELECT 1 FROM product_variants pv2 WHERE pv2.product_id = p.id AND pv2.size = $${++i} AND pv2.stock > 0)`); params.push(size); }
    if (color) { whereConditions.push(`EXISTS (SELECT 1 FROM product_variants pv3 WHERE pv3.product_id = p.id AND pv3.color ILIKE $${++i} AND pv3.stock > 0)`); params.push(`%${color}%`); }
    if (min_price) { whereConditions.push(`p.base_price >= $${++i}`); params.push(parseFloat(min_price)); }
    if (max_price) { whereConditions.push(`p.base_price <= $${++i}`); params.push(parseFloat(max_price)); }

    const where = 'WHERE ' + whereConditions.join(' AND ');
    const countResult = await queryWithMetrics(
      `SELECT COUNT(DISTINCT p.id) FROM products p LEFT JOIN categories c ON p.category_id = c.id ${where}`,
      params, 'SELECT', 'products'
    );
    const total = parseInt(countResult.rows[0].count);

    params.push(parseInt(limit)); const limitIdx = ++i;
    params.push(parseInt(offset)); const offsetIdx = ++i;

    const result = await queryWithMetrics(
      `SELECT p.id, p.name, p.slug, p.description, p.base_price, p.image_url, p.created_at,
        c.id as category_id, c.name as category_name, c.slug as category_slug,
        (SELECT COUNT(*) FROM product_variants pv WHERE pv.product_id = p.id AND pv.stock > 0) as variants_in_stock,
        (SELECT json_agg(DISTINCT pv.color) FROM product_variants pv WHERE pv.product_id = p.id AND pv.stock > 0) as available_colors,
        (SELECT json_agg(s.size) FROM (SELECT DISTINCT pv.size, CASE pv.size WHEN 'XS' THEN 1 WHEN 'S' THEN 2 WHEN 'M' THEN 3 WHEN 'L' THEN 4 WHEN 'XL' THEN 5 WHEN 'XXL' THEN 6 ELSE 99 END as sort_order FROM product_variants pv WHERE pv.product_id = p.id AND pv.stock > 0 ORDER BY sort_order) s) as available_sizes
       FROM products p LEFT JOIN categories c ON p.category_id = c.id
       ${where} GROUP BY p.id, c.id ORDER BY p.id
       LIMIT $${limitIdx} OFFSET $${offsetIdx}`,
      params, 'SELECT', 'products'
    );

    productsListedTotal.inc();
    res.json({ status: 'OK', code: 200, data: result.rows, total, limit: parseInt(limit), offset: parseInt(offset), requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/products', status_code: '500' });
    logger.error('Error listing products', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/products/variant/:variantId  — MUST be before /:slug
app.get('/api/products/variant/:variantId', async (req, res) => {
  try {
    const variantId = parseInt(req.params.variantId);
    if (isNaN(variantId)) return res.status(400).json({ status: 'ERROR', code: 400, message: 'Invalid variant ID', requestId: req.id });

    const result = await queryWithMetrics(
      `SELECT pv.id, pv.product_id, pv.size, pv.color, pv.color_hex, pv.sku, pv.stock,
        COALESCE(pv.price_override, p.base_price) as price, p.name as product_name, p.slug as product_slug, p.image_url
       FROM product_variants pv JOIN products p ON pv.product_id = p.id WHERE pv.id = $1`,
      [variantId], 'SELECT', 'product_variants'
    );

    if (result.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Variant not found', requestId: req.id });

    const variant = result.rows[0];
    stockCheckTotal.inc({ result: variant.stock > 0 ? 'in_stock' : 'out_of_stock' });
    res.json({ status: 'OK', code: 200, data: variant, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/products/variant/:variantId', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// PATCH /api/products/variant/:variantId/stock — decrement stock (internal use by orders-service)
app.patch('/api/products/variant/:variantId/stock', authenticate, async (req, res) => {
  try {
    const variantId = parseInt(req.params.variantId);
    const { quantity } = req.body;
    if (isNaN(variantId) || !quantity || quantity <= 0) return res.status(400).json({ status: 'ERROR', code: 400, message: 'Invalid variantId or quantity', requestId: req.id });

    const result = await queryWithMetrics(
      `UPDATE product_variants SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING id, sku, stock`,
      [quantity, variantId], 'UPDATE', 'product_variants'
    );

    if (result.rows.length === 0) return res.status(409).json({ status: 'ERROR', code: 409, message: 'Insufficient stock', requestId: req.id });

    const variant = result.rows[0];
    res.json({ status: 'OK', code: 200, data: { variantId: variant.id, sku: variant.sku, newStock: variant.stock }, requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/products/variant/:variantId/stock', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/products/:slug
app.get('/api/products/:slug', async (req, res) => {
  try {
    const { slug } = req.params;
    const productResult = await queryWithMetrics(
      `SELECT p.*, c.id as category_id, c.name as category_name, c.slug as category_slug
       FROM products p LEFT JOIN categories c ON p.category_id = c.id
       WHERE p.slug = $1 AND p.is_active = true`,
      [slug], 'SELECT', 'products'
    );

    if (productResult.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Product not found', requestId: req.id });

    const product = productResult.rows[0];
    const variantsResult = await queryWithMetrics(
      `SELECT id, size, color, color_hex, sku, stock, price_override
       FROM product_variants WHERE product_id = $1
       ORDER BY CASE size WHEN 'XS' THEN 1 WHEN 'S' THEN 2 WHEN 'M' THEN 3 WHEN 'L' THEN 4 WHEN 'XL' THEN 5 WHEN 'XXL' THEN 6 END, color`,
      [product.id], 'SELECT', 'product_variants'
    );

    productsViewedTotal.inc({ category: product.category_slug || 'unknown' });

    const span = trace.getActiveSpan();
    if (span) {
      span.setAttribute('product.id', product.id);
      span.setAttribute('product.slug', slug);
      span.setAttribute('product.category', product.category_slug || 'unknown');
    }

    res.json({
      status: 'OK', code: 200,
      data: {
        id: product.id, name: product.name, slug: product.slug,
        description: product.description, base_price: product.base_price,
        image_url: product.image_url, is_active: product.is_active, created_at: product.created_at,
        category: { id: product.category_id, name: product.category_name, slug: product.category_slug },
        variants: variantsResult.rows
      },
      requestId: req.id
    });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/products/:slug', status_code: '500' });
    logger.error('Error fetching product', { error: error.message, slug: req.params.slug, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// ==================== HEALTH + METRICS ====================

app.get('/metrics', async (req, res) => { res.set('Content-Type', register.contentType); res.end(await register.metrics()); });
app.get('/health/live', (req, res) => res.json({ status: 'OK', timestamp: new Date().toISOString(), uptime: process.uptime(), service: 'products-service' }));
app.get('/health/ready', async (req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({ status: 'OK', timestamp: new Date().toISOString(), checks: { database: 'connected' } });
  } catch (error) {
    res.status(503).json({ status: 'ERROR', timestamp: new Date().toISOString(), checks: { database: 'disconnected', error: error.message } });
  }
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
    console.log(`Products Service running on port ${PORT}`);
    console.log('  GET  /api/products           - List products (with filters)');
    console.log('  GET  /api/products/:slug      - Product detail + variants');
    console.log('  GET  /api/categories          - List categories');
    console.log('  GET  /api/products/variant/:id - Variant info + stock');
    console.log('  PATCH /api/products/variant/:id/stock - Decrement stock');
  });
}

startServer().catch(err => { console.error('Failed to start:', err); process.exit(1); });
