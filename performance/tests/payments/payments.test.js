/**
 * DEV-23 — Script de procesamiento de pagos
 * Flujo: Auth → Orders (prep) → POST /api/payments/process
 *
 * SLAs (DEV-13):
 *   payments-service P95 < 800ms · error rate < 0.1%
 *   orders (prep)    P95 < 500ms
 *   auth (prep)      P95 < 450ms
 *
 * Escenarios:
 *   - Pago aprobado   (tarjeta válida)    → valida 200 + status "approved"
 *   - Pago rechazado  (tarjeta declinada) → valida 200 + status "rejected"
 *
 * Tarjetas de prueba:
 *   Aprobada:  4111 1111 1111 1111
 *   Rechazada: 4000 0000 0000 0002
 *
 * Ejecutar:
 *   k6 run tests/payments/payments.test.js
 *   k6 run \
 *     --env AUTH_URL=http://127.0.0.1:3001 \
 *     --env ORDERS_URL=http://127.0.0.1:3004 \
 *     --env PAYMENTS_URL=http://127.0.0.1:3005 \
 *     tests/payments/payments.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    payments_load: {
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
    // SLAs definidos en DEV-13: P95 < 800ms, error rate < 0.1%
    'http_req_duration{service:payments}': [
      { threshold: 'p(95)<800', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed{service:payments}': ['rate<0.001'],
    checks:                              ['rate>0.99'],
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const AUTH_URL     = __ENV.AUTH_URL     || 'http://127.0.0.1:3001';
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

// Tarjeta de prueba para escenario de rechazo (no requiere dataset externo)
const DECLINED_CARD = {
  card_number: '4000000000000002',
  card_expiry: '12/28',
  card_cvv:    '123',
  card_holder: 'Declined Test Card',
};

// ─── Block 4: Default function (VU workload) ─────────────────────────────────

export default function () {
  const sessionId = generateSessionId();
  const user      = users[(__VU - 1) % users.length];
  const product   = products[(__VU - 1) % products.length];
  const card      = cards[(__VU - 1) % cards.length];

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

  // ── Prep: Crear pedido para tener order_id ─────────────────────────────────
  group('Crear pedido (prep)', () => {
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
      {
        headers:          buildHeaders(sessionId, token),
        tags:             { service: 'orders' },
        responseCallback: http.expectedStatuses(201),
      }
    );
    check(res, { 'order 201': (r) => r.status === 201 });
    orderId = res.json('data.order_id');
  });

  if (!orderId) { sleep(1); return; }

  sleep(Math.random() + 0.5);

  // ── Escenarios: 80% aprobado / 20% rechazado ──────────────────────────────
  // Distribución definida en DEV-23: simula tráfico real de pagos Black Friday
  const isApproved = Math.random() < 0.8;

  if (isApproved) {
    // ── Escenario 1: Pago aprobado (80%) ─────────────────────────────────────
    group('Pago aprobado — tarjeta válida', () => {
      const res = http.post(
        `${PAYMENTS_URL}/api/payments/process`,
        JSON.stringify({
          order_id:       orderId,
          payment_method: 'credit_card',
          card_number:    card.card_number,
          card_expiry:    card.card_expiry,
          card_cvv:       card.card_cvv,
          card_holder:    card.card_holder,
        }),
        {
          headers:          buildHeaders(sessionId, token),
          tags:             { service: 'payments' },
          responseCallback: http.expectedStatuses(201),
        }
      );

      check(res, {
        'payments: status 201':          (r) => r.status === 201,
        'payments: status approved':     (r) => r.json('data.status') === 'approved',
        'payments: tiene transaction_id':(r) => r.json('data.transaction_id') !== undefined,
      });

      sleep(Math.random() * 2 + 1);
    });
  } else {
    // ── Escenario 2: Pago rechazado (20%) ────────────────────────────────────
    group('Pago rechazado — tarjeta declinada', () => {
      const res = http.post(
        `${PAYMENTS_URL}/api/payments/process`,
        JSON.stringify({
          order_id:       orderId,
          payment_method: 'credit_card',
          card_number:    DECLINED_CARD.card_number,
          card_expiry:    DECLINED_CARD.card_expiry,
          card_cvv:       DECLINED_CARD.card_cvv,
          card_holder:    DECLINED_CARD.card_holder,
        }),
        {
          headers:          buildHeaders(sessionId, token),
          tags:             { service: 'payments' },
          responseCallback: http.expectedStatuses(201),
        }
      );

      check(res, {
        'payments rejected: status 201':    (r) => r.status === 201,
        'payments rejected: status rejected':(r) => r.json('data.status') === 'rejected',
        'payments rejected: tiene reason':  (r) => r.json('data.reason') !== undefined,
      });

      sleep(Math.random() * 2 + 1);
    });
  }
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/payments-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
