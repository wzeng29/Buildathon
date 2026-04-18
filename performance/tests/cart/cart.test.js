/**
 * DEV-21 — Script de gestión de carrito
 * Endpoints: POST /api/cart/items · GET /api/cart
 *
 * SLAs (DEV-13): P95 < 300ms · error rate < 1%
 * Requiere: JWT válido — login por VU en cada iteración
 *
 * Escenarios:
 *   - Agregar item al carrito  → valida 201 y item confirmado
 *   - Consultar carrito        → valida 200, items, subtotal y total
 *
 * Ejecutar:
 *   k6 run tests/cart/cart.test.js
 *   k6 run --env AUTH_URL=http://127.0.0.1:3001 --env CART_URL=http://127.0.0.1:3003 tests/cart/cart.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    cart_load: {
      executor:         'ramping-vus',
      startVUs:         0,
      stages: [
        { duration: '30s', target: 10 },  // ramp-up
        { duration: '9m',  target: 10 },  // carga sostenida
        { duration: '30s', target: 0  },  // ramp-down
      ],
      gracefulRampDown: '30s',
      gracefulStop:     '30s',
    },
  },
  thresholds: {
    // SLAs definidos en DEV-13: P95 < 300ms, error rate < 1%
    'http_req_duration{service:cart}': [
      { threshold: 'p(95)<300', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed{service:cart}': ['rate<0.01'],
    checks:                          ['rate>0.99'],
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const AUTH_URL = __ENV.AUTH_URL || 'http://127.0.0.1:3001';
const CART_URL = __ENV.CART_URL || 'http://127.0.0.1:3003';

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

  // ── Login por VU para obtener JWT ──────────────────────────────────────────
  let token;

  group('Login para JWT', () => {
    const res = http.post(
      `${AUTH_URL}/api/auth/login`,
      JSON.stringify({ email: user.email, password: user.password }),
      {
        headers: buildHeaders(sessionId),
        tags:    { service: 'auth' },
        responseCallback: http.expectedStatuses(200),
      }
    );

    check(res, { 'login 200': (r) => r.status === 200 });
    token = res.json('data.token');
  });

  // Abortar iteración si no hay token válido
  if (!token) {
    sleep(1);
    return;
  }

  sleep(Math.random() + 0.5); // think time: 0.5–1.5s

  // ── Escenario 1: Agregar item al carrito ───────────────────────────────────
  group('Agregar item al carrito', () => {
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
      'status 201':      (r) => r.status === 201,
      'item confirmado': (r) => r.json('data.product_id') !== undefined,
      'qty correcta':    (r) => r.json('data.qty') === 1,
    });

    sleep(Math.random() * 2 + 1); // think time: 1–3s
  });

  // ── Escenario 2: Consultar carrito ─────────────────────────────────────────
  group('Consultar carrito', () => {
    const res = http.get(
      `${CART_URL}/api/cart`,
      { headers: buildHeaders(sessionId, token), tags: { service: 'cart' } }
    );

    check(res, {
      'status 200':     (r) => r.status === 200,
      'contiene items': (r) => {
        const items = r.json('data.items');
        return Array.isArray(items) && items.length > 0;
      },
      'contiene total': (r) => r.json('data.total') !== undefined,
    });

    sleep(Math.random() * 2 + 1); // think time: 1–3s
  });
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/cart-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
