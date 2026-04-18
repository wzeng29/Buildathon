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
const PORT = process.env.PORT || 3005;
const JWT_SECRET = process.env.JWT_SECRET || 'ecommerce-jwt-secret-2026';
const ORDERS_SERVICE_URL = process.env.ORDERS_SERVICE_URL || 'http://orders-service:3004';

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
const paymentsProcessedTotal = new promClient.Counter({
  name: 'payments_processed_total', help: 'Total payments processed',
  labelNames: ['status', 'method'], registers: [register]
});
const paymentAmountHistogram = new promClient.Histogram({
  name: 'payment_amount_clp', help: 'Payment amount in CLP',
  buckets: [5000, 10000, 20000, 50000, 100000, 200000], registers: [register]
});
const paymentGatewayLatency = new promClient.Histogram({
  name: 'payment_gateway_latency_seconds', help: 'Simulated payment gateway latency',
  buckets: [0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0], registers: [register]
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
    span.setAttribute('service.name', 'payments-service');
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

// Simulate payment gateway (mock)
async function simulateGateway(paymentMethod, cardNumber) {
  const gatewayStart = Date.now();
  // Simulate latency: 200-800ms
  const latency = Math.floor(Math.random() * 600) + 200;
  await new Promise(r => setTimeout(r, latency));

  const elapsed = (Date.now() - gatewayStart) / 1000;
  paymentGatewayLatency.observe(elapsed);

  // Force reject if card ends in 0000
  if (cardNumber && cardNumber.replace(/\s/g, '').endsWith('0000')) {
    return { approved: false, reason: 'Card declined by issuer', transaction_id: null };
  }

  // 90% approval rate
  const approved = Math.random() < 0.90;
  return {
    approved,
    reason: approved ? 'Approved' : 'Insufficient funds',
    transaction_id: approved ? `TXN-${randomUUID().toUpperCase().substring(0, 12)}` : null
  };
}

// ==================== ENDPOINTS ====================

// POST /api/payments/process — process payment for an order
app.post('/api/payments/process', authenticate, async (req, res) => {
  const tracer = trace.getTracer('payments-service');
  const span = tracer.startSpan('ecommerce.process_payment', {}, context.active());

  try {
    const userId = req.auth.tokenPayload.id;
    const { order_id, payment_method, card_number } = req.body;

    const validMethods = ['credit_card', 'debit_card', 'bank_transfer'];
    if (!order_id || !payment_method || !validMethods.includes(payment_method)) {
      return res.status(400).json({ status: 'ERROR', code: 400, message: `order_id and payment_method (${validMethods.join(', ')}) required`, requestId: req.id });
    }

    span.setAttribute('payment.order_id', order_id);
    span.setAttribute('payment.method', payment_method);
    span.setAttribute('payment.user_id', userId);
    span.setAttribute('session.id', req.sessionId || '');

    // Fetch order from orders-service
    const orderRes = await fetch(`${ORDERS_SERVICE_URL}/api/orders/${order_id}`, { headers: getTraceHeaders(req) });
    if (!orderRes.ok) {
      return res.status(404).json({ status: 'ERROR', code: 404, message: 'Order not found', requestId: req.id });
    }
    const orderData = await orderRes.json();
    const order = orderData.data;

    if (order.user_id !== userId) {
      return res.status(403).json({ status: 'ERROR', code: 403, message: 'Forbidden: order does not belong to you', requestId: req.id });
    }
    if (order.status !== 'pending') {
      return res.status(409).json({ status: 'ERROR', code: 409, message: `Order cannot be paid. Current status: ${order.status}`, requestId: req.id });
    }

    span.setAttribute('payment.amount', parseFloat(order.total));

    // Create pending payment record
    const pendingResult = await queryWithMetrics(
      `INSERT INTO payments (order_id, user_id, amount, currency, status, payment_method)
       VALUES ($1, $2, $3, 'CLP', 'processing', $4) RETURNING id`,
      [order_id, userId, parseFloat(order.total), payment_method],
      'INSERT', 'payments'
    );
    const paymentId = pendingResult.rows[0].id;

    // Call mock gateway
    const gatewayResult = await simulateGateway(payment_method, card_number);

    const finalStatus = gatewayResult.approved ? 'approved' : 'rejected';
    const gatewayResponse = {
      approved: gatewayResult.approved,
      reason: gatewayResult.reason,
      timestamp: new Date().toISOString()
    };

    // Update payment record
    await queryWithMetrics(
      `UPDATE payments SET status = $1, transaction_id = $2, gateway_response = $3, processed_at = NOW() WHERE id = $4`,
      [finalStatus, gatewayResult.transaction_id, JSON.stringify(gatewayResponse), paymentId],
      'UPDATE', 'payments'
    );

    // Update order status
    const newOrderStatus = gatewayResult.approved ? 'paid' : 'cancelled';
    try {
      await fetch(`${ORDERS_SERVICE_URL}/api/orders/${order_id}/status`, {
        method: 'PATCH',
        headers: getTraceHeaders(req),
        body: JSON.stringify({ status: newOrderStatus })
      });
    } catch (orderErr) {
      logger.warn('Failed to update order status', { orderId: order_id, error: orderErr.message });
    }

    // Metrics
    paymentsProcessedTotal.inc({ status: finalStatus, method: payment_method });
    if (gatewayResult.approved) paymentAmountHistogram.observe(parseFloat(order.total));

    span.setAttribute('payment.status', finalStatus);
    span.setAttribute('payment.transaction_id', gatewayResult.transaction_id || 'none');
    span.setStatus({ code: SpanStatusCode.OK });
    span.end();

    logger.info('Payment processed', {
      paymentId, orderId: order_id, status: finalStatus,
      amount: order.total, method: payment_method, requestId: req.id, sessionId: req.sessionId
    });

    if (gatewayResult.approved) {
      res.status(201).json({
        status: 'OK', code: 201, message: 'Payment approved',
        data: {
          payment_id: paymentId,
          transaction_id: gatewayResult.transaction_id,
          order_id,
          order_number: order.order_number,
          amount: parseFloat(order.total),
          currency: 'CLP',
          status: 'approved',
          payment_method,
          processed_at: new Date().toISOString()
        },
        requestId: req.id
      });
    } else {
      res.status(402).json({
        status: 'ERROR', code: 402, message: `Payment rejected: ${gatewayResult.reason}`,
        data: { payment_id: paymentId, order_id, status: 'rejected', reason: gatewayResult.reason },
        requestId: req.id
      });
    }
  } catch (error) {
    span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
    span.recordException(error);
    span.end();
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/payments/process', status_code: '500' });
    logger.error('Error processing payment', { error: error.message, requestId: req.id, sessionId: req.sessionId });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/payments/:id — payment detail
app.get('/api/payments/:id', authenticate, async (req, res) => {
  try {
    const paymentId = parseInt(req.params.id);
    const userId = req.auth.tokenPayload.id;

    const result = await queryWithMetrics(
      'SELECT * FROM payments WHERE id = $1 AND user_id = $2',
      [paymentId, userId], 'SELECT', 'payments'
    );

    if (result.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Payment not found', requestId: req.id });

    res.json({ status: 'OK', code: 200, data: result.rows[0], requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/payments/:id', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// GET /api/payments/order/:orderId — payment for an order
app.get('/api/payments/order/:orderId', authenticate, async (req, res) => {
  try {
    const orderId = parseInt(req.params.orderId);
    const userId = req.auth.tokenPayload.id;

    const result = await queryWithMetrics(
      'SELECT * FROM payments WHERE order_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT 1',
      [orderId, userId], 'SELECT', 'payments'
    );

    if (result.rows.length === 0) return res.status(404).json({ status: 'ERROR', code: 404, message: 'Payment not found for this order', requestId: req.id });

    res.json({ status: 'OK', code: 200, data: result.rows[0], requestId: req.id });
  } catch (error) {
    apiErrorsTotal.inc({ error_type: error.name, endpoint: '/api/payments/order/:orderId', status_code: '500' });
    res.status(500).json({ status: 'ERROR', code: 500, message: 'Internal server error', requestId: req.id });
  }
});

// ==================== HEALTH + METRICS ====================
app.get('/metrics', async (req, res) => { res.set('Content-Type', register.contentType); res.end(await register.metrics()); });
app.get('/health/live', (req, res) => res.json({ status: 'OK', timestamp: new Date().toISOString(), uptime: process.uptime(), service: 'payments-service' }));
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
    console.log(`Payments Service running on port ${PORT}`);
    console.log('  POST /api/payments/process          - Process payment');
    console.log('  GET  /api/payments/:id              - Payment detail');
    console.log('  GET  /api/payments/order/:orderId   - Payment by order');
    console.log('  NOTE: Card ending in 0000 = forced rejection (for testing)');
  });
}

startServer().catch(err => { console.error('Failed to start:', err); process.exit(1); });
