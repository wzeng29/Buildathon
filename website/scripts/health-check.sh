#!/bin/bash
# =============================================================================
# Poleras Store — Health Check
# Verifica el estado de todos los contenedores y endpoints del stack
# Uso: ./scripts/health-check.sh
# =============================================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  Poleras Store — Health Check${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""

# ── Docker running ─────────────────────────────────────────
echo -e "${YELLOW}Docker:${NC}"
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}✗ Docker no está corriendo${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker corriendo${NC}"
echo ""

# ── Función: verificar contenedor ─────────────────────────
check_container() {
    local name=$1
    echo -n -e "${BLUE}  $name...${NC} "
    if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
        health=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "none")
        if [ "$health" = "unhealthy" ]; then
            echo -e "${YELLOW}⚠ Running (unhealthy)${NC}"
        else
            echo -e "${GREEN}✓ Running${NC}"
        fi
        return 0
    else
        echo -e "${RED}✗ No encontrado${NC}"
        return 1
    fi
}

# ── Función: verificar endpoint HTTP ──────────────────────
check_endpoint() {
    local name=$1
    local url=$2
    local expected=${3:-200}
    echo -n -e "${BLUE}  $name ($url)...${NC} "
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$status" -eq "$expected" ] 2>/dev/null; then
        echo -e "${GREEN}✓ HTTP $status${NC}"
        return 0
    else
        echo -e "${RED}✗ HTTP $status (esperado $expected)${NC}"
        return 1
    fi
}

# ── Contenedores ───────────────────────────────────────────
echo -e "${YELLOW}Contenedores:${NC}"
failed=0

containers=(
    "users-api" "products-service" "cart-service" "orders-service" "payments-service"
    "users-front"
    "users-db" "products-db" "cart-db" "orders-db" "payments-db"
    "grafana" "prometheus" "loki" "tempo" "promtail"
)

for c in "${containers[@]}"; do
    check_container "$c" || ((failed++))
done
echo ""

# ── Endpoints de aplicación ────────────────────────────────
echo -e "${YELLOW}Servicios:${NC}"
check_endpoint "Frontend"          "http://localhost:4000"              200 || ((failed++))
check_endpoint "users-api"         "http://localhost:3001/health"       200 || ((failed++))
check_endpoint "products-service"  "http://localhost:3002/health"       200 || ((failed++))
check_endpoint "cart-service"      "http://localhost:3003/health"       200 || ((failed++))
check_endpoint "orders-service"    "http://localhost:3004/health"       200 || ((failed++))
check_endpoint "payments-service"  "http://localhost:3005/health"       200 || ((failed++))
echo ""

# ── Observabilidad ─────────────────────────────────────────
echo -e "${YELLOW}Observabilidad:${NC}"
check_endpoint "Grafana"    "http://localhost:3000/api/health"  200 || ((failed++))
check_endpoint "Prometheus" "http://localhost:9090/-/healthy"   200 || ((failed++))
check_endpoint "Loki"       "http://localhost:3100/ready"       200 || ((failed++))
check_endpoint "Tempo"      "http://localhost:3200/ready"       200 || ((failed++))
echo ""

# ── Base de datos ──────────────────────────────────────────
echo -e "${YELLOW}Bases de datos (PostgreSQL):${NC}"
for db in users-db products-db cart-db orders-db payments-db; do
    echo -n -e "${BLUE}  $db...${NC} "
    if docker exec "$db" pg_isready -U postgres > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Accepting connections${NC}"
    else
        echo -e "${RED}✗ Not ready${NC}"
        ((failed++))
    fi
done
echo ""

# ── Resumen ────────────────────────────────────────────────
echo -e "${BLUE}=================================================${NC}"
if [ "$failed" -eq 0 ]; then
    echo -e "${GREEN}  ✅ All systems operational${NC}"
else
    echo -e "${YELLOW}  ⚠ Issues detected: $failed checks failed${NC}"
    echo ""
    echo -e "  Ver logs:   ${YELLOW}docker compose logs -f <servicio>${NC}"
    echo -e "  Reiniciar:  ${YELLOW}docker compose restart <servicio>${NC}"
fi
echo -e "${BLUE}=================================================${NC}"
echo ""
[ "$failed" -eq 0 ] && exit 0 || exit 1
