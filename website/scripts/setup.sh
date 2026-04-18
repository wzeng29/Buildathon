#!/bin/bash
# =============================================================================
# Poleras Store — Setup Script
# Levanta el stack completo desde cero
# Uso: ./scripts/setup.sh
# =============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  Poleras Store — Setup${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# ── 1. Docker ──────────────────────────────────────────────
echo -e "${YELLOW}[1/5]${NC} Verificando Docker..."
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker no está corriendo. Inicia Docker Desktop e intenta de nuevo.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker corriendo${NC}"
echo ""

# ── 2. Docker Compose ─────────────────────────────────────
echo -e "${YELLOW}[2/5]${NC} Verificando Docker Compose..."
if ! docker compose version > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker Compose no está disponible.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose disponible${NC}"
echo ""

# ── 3. Limpieza opcional ───────────────────────────────────
echo -e "${YELLOW}[3/5]${NC} Limpieza previa..."
read -p "¿Limpiar contenedores y volúmenes previos? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose down -v --remove-orphans
    echo -e "${GREEN}✓ Limpieza completada${NC}"
else
    echo -e "${BLUE}Omitiendo limpieza${NC}"
fi
echo ""

# ── 4. Levantar servicios ──────────────────────────────────
echo -e "${YELLOW}[4/5]${NC} Levantando servicios..."
echo -e "${BLUE}Esto puede tomar varios minutos la primera vez...${NC}"
docker compose up -d
echo -e "${GREEN}✓ Servicios iniciados${NC}"
echo ""

# ── 5. Esperar que estén listos ───────────────────────────
echo -e "${YELLOW}[5/5]${NC} Esperando que los servicios estén listos..."

max_attempts=30
attempt=0

echo -n -e "${BLUE}  users-db...${NC} "
until docker exec users-db pg_isready -U postgres > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ $attempt -ge $max_attempts ] && echo -e "${RED}timeout${NC}" && exit 1
    sleep 2
done
echo -e "${GREEN}✓${NC}"

attempt=0
echo -n -e "${BLUE}  users-api...${NC} "
until curl -s http://localhost:3001/health > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ $attempt -ge $max_attempts ] && echo -e "${RED}timeout${NC}" && exit 1
    sleep 2
done
echo -e "${GREEN}✓${NC}"

attempt=0
echo -n -e "${BLUE}  products-service...${NC} "
until curl -s http://localhost:3002/health > /dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ $attempt -ge $max_attempts ] && echo -e "${RED}timeout${NC}" && exit 1
    sleep 2
done
echo -e "${GREEN}✓${NC}"

echo ""

# ── Resumen ────────────────────────────────────────────────
echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}  ✅ Setup completo!${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""
echo -e "${BLUE}Accesos:${NC}"
echo ""
echo -e "  ${YELLOW}Frontend:${NC}          http://localhost:4000"
echo -e "  ${YELLOW}users-api:${NC}         http://localhost:3001"
echo -e "  ${YELLOW}products-service:${NC}  http://localhost:3002"
echo -e "  ${YELLOW}cart-service:${NC}      http://localhost:3003"
echo -e "  ${YELLOW}orders-service:${NC}    http://localhost:3004"
echo -e "  ${YELLOW}payments-service:${NC}  http://localhost:3005"
echo -e "  ${YELLOW}Grafana:${NC}           http://localhost:3000  (admin/admin)"
echo -e "  ${YELLOW}Prometheus:${NC}        http://localhost:9090"
echo ""
echo -e "${BLUE}Comandos útiles:${NC}"
echo ""
echo -e "  Health check:   ${YELLOW}./scripts/health-check.sh${NC}"
echo -e "  Integration test: ${YELLOW}./scripts/test-ecommerce-flow.sh${NC}"
echo -e "  Teardown:       ${YELLOW}./scripts/teardown.sh${NC}"
echo ""
