/**
 * DEV-20 — Script de catálogo de productos
 * Endpoints: GET /api/products?limit=12 · GET /api/products/:slug
 *
 * SLAs (DEV-13): P95 < 300ms · error rate < 0.5%
 *
 * Escenarios:
 *   - Listado de productos → valida status 200 y estructura de respuesta
 *   - Detalle de producto  → valida status 200, variantes y precio
 *
 * Consideraciones:
 *   - Tag { service: 'products' } alimenta thresholds diferenciados (DEV-13)
 *   - Mayor volumen de tráfico esperado: 70% del total (Black Friday)
 *   - Navegación realista: listado → detalle con slugs del dataset
 *
 * Ejecutar:
 *   k6 run tests/products/products.test.js
 *   k6 run --env PRODUCTS_URL=http://127.0.0.1:3002 tests/products/products.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    products_load: {
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
    // SLAs definidos en DEV-13: P95 < 300ms, error rate < 0.5%
    'http_req_duration{service:products}': [
      { threshold: 'p(95)<300', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed{service:products}': ['rate<0.005'],
    checks:                              ['rate>0.99'],
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const PRODUCTS_URL = __ENV.PRODUCTS_URL || 'http://127.0.0.1:3002';

const products = new SharedArray('products', () =>
  JSON.parse(open('../../data/products.json'))
);

// ─── Block 4: Default function (VU workload) ─────────────────────────────────

export default function () {
  const sessionId = generateSessionId();
  const product   = products[(__VU - 1) % products.length];
  const tags      = { service: 'products' };

  // ── Escenario 1: Listado de productos ──────────────────────────────────────
  group('Listado de productos', () => {
    const res = http.get(
      `${PRODUCTS_URL}/api/products?limit=12`,
      { headers: buildHeaders(sessionId), tags }
    );

    check(res, {
      'status 200':     (r) => r.status === 200,
      'lista no vacía': (r) => {
        const data = r.json('data');
        return Array.isArray(data) && data.length > 0;
      },
      'contiene precio': (r) => {
        const data = r.json('data');
        return Array.isArray(data) && data.length > 0 && data[0].price !== undefined;
      },
    });

    sleep(Math.random() * 2 + 1); // think time: 1–3s
  });

  // ── Escenario 2: Detalle de producto ───────────────────────────────────────
  group('Detalle de producto', () => {
    const res = http.get(
      `${PRODUCTS_URL}/api/products/${product.slug}`,
      { headers: buildHeaders(sessionId), tags }
    );

    check(res, {
      'status 200':         (r) => r.status === 200,
      'contiene variantes': (r) => r.json('data.variants') !== undefined,
      'contiene precio':    (r) => r.json('data.price') !== undefined,
      'slug correcto':      (r) => r.json('data.slug') === product.slug,
    });

    sleep(Math.random() * 2 + 1); // think time: 1–3s
  });
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/products-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
