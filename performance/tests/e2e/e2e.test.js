/**
 * DEV-24 — Script E2E: flujo completo de compra (happy path Black Friday)
 *
 * Flujo: Login → Catálogo → Detalle → Carrito → Pedido → Pago
 *
 * SLAs por servicio (DEV-13):
 *   users-api        P95 < 450ms · error rate < 0.5%
 *   products-service P95 < 300ms · error rate < 0.5%
 *   cart-service     P95 < 300ms · error rate < 1%
 *   orders-service   P95 < 500ms · error rate < 0.5%
 *   payments-service P95 < 800ms · error rate < 0.1%
 *
 * Usado en: Smoke Test · Spike Test · Soak Test
 *
 * Ejecutar:
 *   k6 run tests/e2e/e2e.test.js
 *   k6 run \
 *     --env AUTH_URL=http://127.0.0.1:3001 \
 *     --env PRODUCTS_URL=http://127.0.0.1:3002 \
 *     --env CART_URL=http://127.0.0.1:3003 \
 *     --env ORDERS_URL=http://127.0.0.1:3004 \
 *     --env PAYMENTS_URL=http://127.0.0.1:3005 \
 *     tests/e2e/e2e.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    e2e_load: {
      executor:         'ramping-vus',
      startVUs:         0,
      stages: [
        { duration: '30s', target: 10 },  // ramp-up
        { duration: '9m',  target: 10 },  // carga sostenida
        { duration: '30s', target: 0  },  // ramp-down
      ],
      gracefulRampDown: '30s',
      gracefulStop:     '60s',            // más alto por latencia acumulada del flujo completo
    },
  },
  thresholds: {
    // SLAs por servicio — definidos en DEV-13
    'http_req_duration{service:auth}': [
      { threshold: 'p(95)<450', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_duration{service:products}': [
      { threshold: 'p(95)<300', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_duration{service:cart}': [
      { threshold: 'p(95)<300', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_duration{service:orders}': [
      { threshold: 'p(95)<500', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_duration{service:payments}': [
      { threshold: 'p(95)<800', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed': ['rate<0.005'],
    checks:            ['rate>0.95'],     // tasa de compras exitosas > 95%
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const AUTH_URL     = __ENV.AUTH_URL     || 'http://127.0.0.1:3001';
const PRODUCTS_URL = __ENV.PRODUCTS_URL || 'http://127.0.0.1:3002';
const CART_URL     = __ENV.CART_URL     || 'http://127.0.0.1:3003';
const ORDERS_URL   = __ENV.ORDERS_URL   || 'http://127.0.0.1:3004';
const PAYMENTS_URL = __ENV.PAYMENTS_URL || 'http://127.0.0.1:3005';

const users = new SharedArray('users', () =>
  JSON.parse(open('../../data/users.json'))
);

const products = new SharedArray('products', () =>
  JSON.parse(open('../../data/products.json'))
);

const cards = new SharedArray('cards', () =>
  JSON.parse(open('../../data/cards.json'))
);

// ─── Block 4: Default function (VU workload) ─────────────────────────────────

export default function () {
  const sessionId = generateSessionId();
  const user      = users[(__VU - 1) % users.length];
  const product   = products[(__VU - 1) % products.length];
  const card      = cards[(__VU - 1) % cards.length];

  let token;
  let orderId;

  // ── Paso 1: Login ───────────────────────────────────────────────────────────
  group('1 · Login', () => {
    const res = http.post(
      `${AUTH_URL}/api/auth/login`,
      JSON.stringify({ email: user.email, password: user.password }),
      {
        headers:          buildHeaders(sessionId),
        tags:             { service: 'auth' },
        responseCallback: http.expectedStatuses(200),
      }
    );

    check(res, {
      'auth: status 200':  (r) => r.status === 200,
      'auth: tiene token': (r) => {
        const t = r.json('data.token');
        return t !== undefined && t !== null && t !== '';
      },
    });

    token = res.json('data.token');
  });

  if (!token) { sleep(1); return; }

  sleep(Math.random() * 2 + 1); // think time

  // ── Paso 2: Explorar catálogo ───────────────────────────────────────────────
  group('2 · Catálogo de productos', () => {
    const res = http.get(
      `${PRODUCTS_URL}/api/products?limit=12`,
      { headers: buildHeaders(sessionId, token), tags: { service: 'products' } }
    );

    check(res, {
      'products: status 200':    (r) => r.status === 200,
      'products: lista no vacía':(r) => {
        const data = r.json('data');
        return Array.isArray(data) && data.length > 0;
      },
    });

    sleep(Math.random() * 2 + 1);
  });

  // ── Paso 3: Detalle de producto ─────────────────────────────────────────────
  group('3 · Detalle de producto', () => {
    const res = http.get(
      `${PRODUCTS_URL}/api/products/${product.slug}`,
      { headers: buildHeaders(sessionId, token), tags: { service: 'products' } }
    );

    check(res, {
      'product detail: status 200':   (r) => r.status === 200,
      'product detail: tiene precio': (r) => r.json('data.price') !== undefined,
    });

    sleep(Math.random() * 2 + 1);
  });

  // ── Paso 4: Agregar al carrito ──────────────────────────────────────────────
  group('4 · Agregar al carrito', () => {
    const res = http.post(
      `${CART_URL}/api/cart/items`,
      JSON.stringify({
        product_id: product.product_id,
        variant_id: product.variant_id,
        qty:        1,
      }),
      { headers: buildHeaders(sessionId, token), tags: { service: 'cart' } }
    );

    check(res, {
      'cart: status 201':      (r) => r.status === 201,
      'cart: item confirmado': (r) => r.json('data.product_id') !== undefined,
    });

    sleep(Math.random() + 0.5);
  });

  // ── Paso 5: Revisar carrito ─────────────────────────────────────────────────
  group('5 · Revisar carrito', () => {
    const res = http.get(
      `${CART_URL}/api/cart`,
      { headers: buildHeaders(sessionId, token), tags: { service: 'cart' } }
    );

    check(res, {
      'cart review: status 200':     (r) => r.status === 200,
      'cart review: contiene items': (r) => {
        const items = r.json('data.items');
        return Array.isArray(items) && items.length > 0;
      },
    });

    sleep(Math.random() + 0.5);
  });

  // ── Paso 6: Crear pedido ────────────────────────────────────────────────────
  group('6 · Crear pedido', () => {
    const res = http.post(
      `${ORDERS_URL}/api/orders`,
      JSON.stringify({
        items: [
          {
            product_id: product.product_id,
            variant_id: product.variant_id,
            qty:        1,
            price:      product.price,
          },
        ],
        shipping_address: {
          street: 'Av. Test 123',
          city:   'Santiago',
          region: 'Metropolitana',
          zip:    '8320000',
        },
      }),
      { headers: buildHeaders(sessionId, token), tags: { service: 'orders' } }
    );

    check(res, {
      'orders: status 201':    (r) => r.status === 201,
      'orders: tiene order_id':(r) => r.json('data.order_id') !== undefined,
    });

    orderId = res.json('data.order_id');
    sleep(Math.random() + 0.5);
  });

  // ── Paso 7: Procesar pago ───────────────────────────────────────────────────
  group('7 · Procesar pago', () => {
    const res = http.post(
      `${PAYMENTS_URL}/api/payments/process`,
      JSON.stringify({
        order_id:    orderId,
        card_number: card.card_number,
        card_expiry: card.card_expiry,
        card_cvv:    card.card_cvv,
        card_holder: card.card_holder,
        amount:      product.price,
      }),
      { headers: buildHeaders(sessionId, token), tags: { service: 'payments' } }
    );

    check(res, {
      'payments: status 200':   (r) => r.status === 200,
      'payments: aprobado':     (r) => r.json('data.status') === 'approved',
      'payments: tiene tx_id':  (r) => r.json('data.transaction_id') !== undefined,
    });

    sleep(Math.random() * 2 + 1);
  });
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/e2e-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
