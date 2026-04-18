const pool = require('./db');

async function runMigrations() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS addresses (
        id SERIAL PRIMARY KEY,
        street VARCHAR(255) NOT NULL,
        street_name VARCHAR(255) NOT NULL,
        building_number VARCHAR(50) NOT NULL,
        city VARCHAR(100) NOT NULL,
        zipcode VARCHAR(20) NOT NULL,
        country VARCHAR(100) NOT NULL,
        country_code VARCHAR(2) NOT NULL,
        latitude DECIMAL(10, 6) NOT NULL,
        longitude DECIMAL(10, 6) NOT NULL
      );

      CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        firstname VARCHAR(100) NOT NULL,
        lastname VARCHAR(100) NOT NULL,
        email VARCHAR(255) NOT NULL UNIQUE,
        phone VARCHAR(50) NOT NULL,
        birthday DATE NOT NULL,
        gender VARCHAR(10) NOT NULL,
        address_id INTEGER REFERENCES addresses(id) ON DELETE CASCADE,
        website VARCHAR(255),
        image VARCHAR(255),
        password_hash VARCHAR(255),
        role VARCHAR(20) DEFAULT 'customer' NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

      CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
      CREATE INDEX IF NOT EXISTS idx_users_address_id ON users(address_id);
      CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
    `);
    console.log('[migrate] users-service: tablas verificadas/creadas correctamente');
  } finally {
    client.release();
  }
}

module.exports = { runMigrations };
