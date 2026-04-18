/**
 * DEV-22 — Script de creación de pedido (cross-service)
 * Flujo: Auth → Cart → POST /api/orders · GET /api/orders/:id
 *
 * SLAs (DEV-13):
 *   orders-service   P95 < 500ms · error rate < 0.5%
 *   auth (prep)      P95 < 450ms
 *   cart (prep)      P95 < 300ms
 *
 * Escenarios:
 *   - Crear pedido con items válidos  → valida 201 y order_id
 *   - Consultar pedido creado         → valida 200 y estado
 *   - Crear pedido sin autenticación  → valida 401
 *
 * Ejecutar:
 *   k6 run tests/orders/orders.test.js
 *   k6 run \
 *     --env AUTH_URL=http://127.0.0.1:3001 \
 *     --env CART_URL=http://127.0.0.1:3003 \
 *     --env ORDERS_URL=http://127.0.0.1:3004 \
 *     tests/orders/orders.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    orders_load: {
      executor:         'ramping-vus',
      startVUs:         0,
      stages: [
        { duration: '30s', target: 10 },  // ramp-up
        { duration: '9m',  target: 10 },  // carga sostenida
        { duration: '30s', target: 0  },  // ramp-down
      ],
      gracefulRampDown: '30s',
      gracefulStop:     '60s',
    },
  },
  thresholds: {
    // SLAs definidos en DEV-13: P95 < 500ms, error rate < 0.5%
    'http_req_duration{service:orders}': [
      { threshold: 'p(95)<500', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed{service:orders}': ['rate<0.005'],
    checks:                            ['rate>0.99'],
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const AUTH_URL   = __ENV.AUTH_URL   || 'http://127.0.0.1:3001';
const CART_URL   = __ENV.CART_URL   || 'http://127.0.0.1:3003';
const ORDERS_URL = __ENV.ORDERS_URL || 'http://127.0.0.1:3004';

const users = new SharedArray('users', () =>
  JSON.parse(open('../../data/users.json'))
);

const products = new SharedArray('products', () =>
  JSON.parse(open('../../data/products.json'))
);

// ─── Block 4: Default function (VU workload) ─────────────────────────────────

export default function () {
  const sessionId = generateSessionId();
  const user      = users[(__VU - 1) % users.length];
  const product   = products[(__VU - 1) % products.length];

  let token;
  let orderId;

  // ── Prep: Login por VU ─────────────────────────────────────────────────────
  group('Login para JWT', () => {
    const res = http.post(
      `${AUTH_URL}/api/auth/login`,
      JSON.stringify({ email: user.email, password: user.password }),
      {
        headers:          buildHeaders(sessionId),
        tags:             { service: 'auth' },
        responseCallback: http.expectedStatuses(200),
      }
    );
    check(res, { 'login 200': (r) => r.status === 200 });
    token = res.json('data.token');
  });

  if (!token) { sleep(1); return; }

  sleep(Math.random() + 0.5);

  // ── Prep: Agregar item al carrito y obtener cart_id ───────────────────────
  let cartId;

  group('Agregar item al carrito (prep)', () => {
    const res = http.post(
      `${CART_URL}/api/cart/items`,
      JSON.stringify({
        product_id: product.product_id,
        variant_id: product.variant_id,
        qty:        1,
      }),
      {
        headers:          buildHeaders(sessionId, token),
        tags:             { service: 'cart' },
        responseCallback: http.expectedStatuses(201),
      }
    );
    check(res, { 'cart 201': (r) => r.status === 201 });

    // Obtener cart_id del carrito activo
    const cartRes = http.get(
      `${CART_URL}/api/cart`,
      { headers: buildHeaders(sessionId, token), tags: { service: 'cart' } }
    );
    check(cartRes, { 'cart get 200': (r) => r.status === 200 });
    cartId = cartRes.json('data.cart_id');
  });

  if (!cartId) { sleep(1); return; }

  sleep(Math.random() + 0.5);

  // ── Escenario 1: Crear pedido con cart_id ──────────────────────────────────
  group('Crear pedido', () => {
    const res = http.post(
      `${ORDERS_URL}/api/orders`,
      JSON.stringify({
        cart_id:          cartId,
        shipping_address: {
          street: 'Av. Test 123',
          city:   'Santiago',
          zip:    '8320000',
        },
      }),
      { headers: buildHeaders(sessionId, token), tags: { service: 'orders' } }
    );

    check(res, {
      'orders: status 201':     (r) => r.status === 201,
      'orders: tiene order_id': (r) => r.json('data.order_id') !== undefined,
      'orders: estado pending': (r) => {
        const status = r.json('data.status');
        return status === 'pending' || status === 'created';
      },
    });

    orderId = res.json('data.order_id');
    sleep(Math.random() * 2 + 1);
  });

  // ── Escenario 2: Consultar pedido creado ───────────────────────────────────
  if (orderId) {
    group('Consultar pedido', () => {
      const res = http.get(
        `${ORDERS_URL}/api/orders/${orderId}`,
        { headers: buildHeaders(sessionId, token), tags: { service: 'orders' } }
      );

      check(res, {
        'orders get: status 200':    (r) => r.status === 200,
        'orders get: order_id match':(r) => r.json('data.order_id') === orderId,
        'orders get: tiene items':   (r) => {
          const items = r.json('data.items');
          return Array.isArray(items) && items.length > 0;
        },
      });

      sleep(Math.random() + 0.5);
    });
  }

  // ── Escenario 3: Crear pedido sin autenticación ────────────────────────────
  group('Crear pedido sin auth — debe rechazar', () => {
    const res = http.post(
      `${ORDERS_URL}/api/orders`,
      JSON.stringify({ cart_id: cartId, shipping_address: { street: 'Test', city: 'Santiago', zip: '8320000' } }),
      {
        headers:          buildHeaders(sessionId),  // sin token
        tags:             { service: 'orders' },
        responseCallback: http.expectedStatuses(401),
      }
    );

    check(res, { 'orders no-auth: status 401': (r) => r.status === 401 });
    sleep(Math.random() + 0.5);
  });
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/orders-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
