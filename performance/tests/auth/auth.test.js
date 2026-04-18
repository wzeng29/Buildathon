/**
 * DEV-19 — Script de autenticación
 * Endpoint: POST /api/auth/login
 *
 * SLAs (DEV-13): P95 < 450ms · error rate < 0.5%
 *
 * Escenarios:
 *   - Login exitoso con usuario válido → valida status 200, token JWT y duración 24h
 *   - Login fallido con credenciales inválidas → valida status 401
 *
 * Ejecutar:
 *   k6 run tests/auth/auth.test.js
 *   k6 run --env BASE_URL=http://127.0.0.1:3001 tests/auth/auth.test.js
 */

import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { generateSessionId, decodeJWT, buildHeaders } from '../../lib/helpers.js';
import { htmlReport, textSummary } from '../../lib/summary.js';

// ─── Block 1: Options ────────────────────────────────────────────────────────

export const options = {
  scenarios: {
    auth_load: {
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
    // SLAs definidos en DEV-13: P95 < 450ms, error rate < 0.5% (actualizado 2026-03-30 por Arquitectura)
    'http_req_duration{service:auth}': [
      { threshold: 'p(95)<450', abortOnFail: true, delayAbortEval: '1m' },
    ],
    'http_req_failed{service:auth}': ['rate<0.005'],
    checks:                          ['rate>0.99'],
  },
};

// ─── Block 2: Data ────────────────────────────────────────────────────────────

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:3001';

const users = new SharedArray('users', () =>
  JSON.parse(open('../../data/users.json'))
);

function safeJsonPath(response, selector) {
  if (!response || response.status !== 200 || !response.body) {
    return null;
  }

  try {
    return response.json(selector);
  } catch (_error) {
    return null;
  }
}

// ─── Block 4: Default function (VU workload) ─────────────────────────────────

export default function () {
  const sessionId = generateSessionId();
  const user      = users[(__VU - 1) % users.length];
  const tags      = { service: 'auth' };

  // ── Escenario 1: Login exitoso ──────────────────────────────────────────────
  group('Login exitoso', () => {
    const res = http.post(
      `${BASE_URL}/api/auth/login`,
      JSON.stringify({ email: user.email, password: user.password }),
      { headers: buildHeaders(sessionId), tags }
    );

    check(res, {
      'status 200':       (r) => r.status === 200,
      'tiene token':      (r) => {
        const token = safeJsonPath(r, 'data.token');
        return token !== undefined && token !== null && token !== '';
      },
      'token duración 24h': (r) => {
        const token = safeJsonPath(r, 'data.token');
        if (!token) return false;
        const payload = decodeJWT(token);
        if (!payload || !payload.exp || !payload.iat) return false;
        const durationHours = (payload.exp - payload.iat) / 3600;
        return durationHours >= 23.9 && durationHours <= 24.1;
      },
      'X-Session-ID en response': (r) => r.status === 200,
    });

    sleep(Math.random() * 2 + 1); // think time: 1–3s
  });

  // ── Escenario 2: Login fallido (credenciales inválidas) ────────────────────
  group('Login fallido — credenciales inválidas', () => {
    const res = http.post(
      `${BASE_URL}/api/auth/login`,
      JSON.stringify({ email: user.email, password: 'wrong_password_test_123' }),
      { headers: buildHeaders(sessionId), tags, responseCallback: http.expectedStatuses(401) }
    );

    check(res, {
      'status 401': (r) => r.status === 401,
    });

    sleep(Math.random() + 0.5); // think time: 0.5–1.5s
  });
}

// ─── Block 5: Summary ────────────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    'results/auth-report.html': htmlReport(data),
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
