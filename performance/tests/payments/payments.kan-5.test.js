import http                        from 'k6/http';
import { check, group, sleep }     from 'k6';
import { SharedArray }             from 'k6/data';
import { htmlReport, textSummary } from '../../lib/summary.js';

// Block 1: Options
export const options = {
  scenarios: {
    payments_load: {
      executor: 'constant-vus',
      vus: __ENV.VUS ? Number(__ENV.VUS) : 2,
      duration: __ENV.DURATION || '30s',
      gracefulStop: '30s',
    },
  },
  thresholds: {
    'http_req_failed{service:payments}': ['rate<0.001000'],
    'http_req_duration{service:payments}': ['p(95)<800'],
    checks: ['rate>0.99'],
  },
};

// Block 2: Data
const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:3005';
const testUsers = new SharedArray('ticket-users', () => JSON.parse(open('../../data/users.json')));

// Block 3: Setup
export function setup() {
  return { baseUrl: BASE_URL };
}

// Block 4: Default function
export default function (context) {
  const user = testUsers[(__VU - 1) % testUsers.length] || {};
  const payload = JSON.stringify({ issueKey: __ENV.TICKET_KEY || 'KAN-5', userId: user.id || __VU });

  group('KAN-5 Develop payment script — POST /api/payments/process (approved + rejected)', () => {
    const request = http.post(`${context.baseUrl}/api/payments/process`, payload, { headers: { 'Content-Type': 'application/json' }, tags: { service: 'payments', jira: 'KAN-5' } });
    check(request, {
      'status is expected': (r) => r.status >= 200 && r.status < 300,
      'response time within hard ceiling': (r) => r.timings.duration < 1600,
    });
    sleep(Math.random() + 1);
  });
}

// Block 5: Summary
export function handleSummary(data) {
  return {
    stdout: textSummary(data, { indent: ' ' }),
    'results/kan-5-payments-report.html': htmlReport(data),
  };
}
