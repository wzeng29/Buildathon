const pool = require('./db');

async function runMigrations() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        currency VARCHAR(3) NOT NULL DEFAULT 'CLP',
        status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'approved', 'rejected', 'refunded')),
        payment_method VARCHAR(30) NOT NULL CHECK (payment_method IN ('credit_card', 'debit_card', 'bank_transfer')),
        transaction_id VARCHAR(100) UNIQUE,
        gateway_response JSONB,
        processed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

      CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id);
      CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
      CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
      CREATE INDEX IF NOT EXISTS idx_payments_transaction ON payments(transaction_id);
    `);
    console.log('[migrate] payments-service: tablas verificadas/creadas correctamente');
  } finally {
    client.release();
  }
}

module.exports = { runMigrations };
