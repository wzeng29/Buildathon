# Database Service

PostgreSQL database setup and initialization for the Users API.

## Overview

PostgreSQL 15 database with:
- Users table
- Addresses table  
- Foreign key relationships
- Auto-incrementing primary keys
- Optimized indexes

## Schema

### Tables

**users**
- `id` - Serial primary key
- `firstname` - VARCHAR(100)
- `lastname` - VARCHAR(100)
- `email` - VARCHAR(255) UNIQUE
- `phone` - VARCHAR(50)
- `birthday` - DATE
- `gender` - VARCHAR(20)
- `website` - VARCHAR(255)
- `image` - VARCHAR(255)
- `address_id` - INTEGER (FK to addresses)

**addresses**
- `id` - Serial primary key
- `street` - VARCHAR(255)
- `streetName` - VARCHAR(255)
- `buildingNumber` - VARCHAR(50)
- `city` - VARCHAR(100)
- `zipcode` - VARCHAR(20)
- `country` - VARCHAR(100)
- `country_code` - VARCHAR(10)
- `latitude` - DECIMAL(10, 7)
- `longitude` - DECIMAL(10, 7)

## Initialization

The `init.sql` script runs automatically when the container starts for the first time.

## Connection

Default credentials (configured in docker-compose.yml):
- Host: `postgres` (Docker network) or `localhost` (external)
- Port: `5434` (external) / `5432` (internal)
- Database: `usersdb`
- User: `postgres`
- Password: `postgres`

⚠️ **Change credentials for production use**

## Access Database

```bash
# Via docker exec
docker exec -it users-db psql -U postgres -d usersdb

# Via psql client
psql -h localhost -p 5434 -U postgres -d usersdb
```

## Backup & Restore

```bash
# Backup
docker exec users-db pg_dump -U postgres usersdb > backup.sql

# Restore
docker exec -i users-db psql -U postgres -d usersdb < backup.sql
```

## License

Part of the Learning-Performance-Observability-Stack educational project.
