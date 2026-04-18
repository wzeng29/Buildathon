#!/bin/bash
# ================================================================
# build.sh — Plan de build paso a paso
#
# CAUSA RAÍZ DEL PROBLEMA ANTERIOR:
#   El builder activo era "flamboyant_dewdney" con driver
#   "docker-container". Este driver exporta en formato OCI y NO
#   carga las imágenes al daemon local → docker images no las veía.
#
#   SOLUCIÓN PERMANENTE: usar siempre el builder "desktop-linux"
#   (driver "docker") que carga las imágenes directo al daemon.
#
# USO:
#   ./scripts/build.sh          → build completo
#   ./scripts/build.sh services → solo microservicios
#   ./scripts/build.sh frontend → solo frontend
#   ./scripts/build.sh clean    → limpia imágenes del proyecto
# ================================================================

set -euo pipefail

# ── Colores ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()   { echo -e "${BLUE}[BUILD]${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()   { echo -e "${RED}  ✗ ERROR:${NC} $*"; exit 1; }
step()  { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

PROJECT="learning-performance-observability-stack"
TARGET=${1:-all}

# ── PASO 0: Verificar y fijar el builder correcto ─────────────
step "PASO 0 — Verificar builder de Docker"

ACTIVE_BUILDER=$(docker buildx inspect 2>/dev/null | grep "^Driver:" | awk '{print $2}')
ACTIVE_NAME=$(docker buildx inspect 2>/dev/null | grep "^Name:" | awk '{print $2}')

if [ "$ACTIVE_BUILDER" != "docker" ]; then
  warn "Builder activo '$ACTIVE_NAME' usa driver '$ACTIVE_BUILDER'"
  warn "Este driver NO carga imágenes al daemon. Cambiando a desktop-linux..."
  docker buildx use desktop-linux 2>/dev/null || docker buildx use default
fi

ACTIVE_NAME=$(docker buildx inspect 2>/dev/null | grep "^Name:" | awk '{print $2}')
ok "Builder activo: $ACTIVE_NAME (driver: docker)"

if [ "$TARGET" = "clean" ]; then
  step "Limpieza de imágenes del proyecto"
  docker images --format "{{.Repository}}:{{.Tag}}" | grep "$PROJECT" | xargs -r docker rmi -f
  docker image prune -f
  ok "Imágenes del proyecto eliminadas"
  exit 0
fi

# ── PASO 1: Limpiar imágenes huérfanas previas ────────────────
step "PASO 1 — Limpiar imágenes huérfanas (dangling)"
DANGLING=$(docker images -f "dangling=true" -q | wc -l | tr -d ' ')
if [ "$DANGLING" -gt "0" ]; then
  docker image prune -f > /dev/null
  ok "Eliminadas $DANGLING imágenes huérfanas"
else
  ok "No hay imágenes huérfanas"
fi

# ── PASO 2: Construir microservicios base (sin dependencias) ──
if [ "$TARGET" = "all" ] || [ "$TARGET" = "services" ]; then

  step "PASO 2 — Servicios base: users-api y products-service"
  log "Construyendo users-api..."
  docker compose build api
  ok "users-api"

  log "Construyendo products-service..."
  docker compose build products-service
  ok "products-service"

  # Limpiar dangling entre builds
  docker image prune -f > /dev/null

  # ── PASO 3: Servicios con dependencia a products ─────────────
  step "PASO 3 — cart-service (depende de products-service)"
  log "Construyendo cart-service..."
  docker compose build cart-service
  ok "cart-service"

  docker image prune -f > /dev/null

  # ── PASO 4: Servicios que dependen de cart ───────────────────
  step "PASO 4 — orders-service (depende de cart-service)"
  log "Construyendo orders-service..."
  docker compose build orders-service
  ok "orders-service"

  docker image prune -f > /dev/null

  # ── PASO 5: payments-service ─────────────────────────────────
  step "PASO 5 — payments-service (depende de orders-service)"
  log "Construyendo payments-service..."
  docker compose build payments-service
  ok "payments-service"

  docker image prune -f > /dev/null

fi

# ── PASO 6: Frontend ─────────────────────────────────────────
if [ "$TARGET" = "all" ] || [ "$TARGET" = "frontend" ]; then

  step "PASO 6 — Frontend (Astro + React + TailwindCSS)"
  log "Construyendo frontend..."
  docker compose build frontend
  ok "frontend"
  docker image prune -f > /dev/null

fi

# ── PASO 7: Verificar imágenes generadas ─────────────────────
step "PASO 7 — Verificación de imágenes"
EXPECTED=("api" "products-service" "cart-service" "orders-service" "payments-service" "frontend")
ALL_OK=true

for svc in "${EXPECTED[@]}"; do
  IMG="${PROJECT}-${svc}:latest"
  if docker image inspect "$IMG" > /dev/null 2>&1; then
    SIZE=$(docker image inspect "$IMG" --format='{{.Size}}' | awk '{printf "%.0fMB", $1/1048576}')
    ok "$svc → $IMG ($SIZE)"
  else
    warn "$svc → imagen no encontrada"
    ALL_OK=false
  fi
done

if [ "$ALL_OK" = false ]; then
  err "Algunas imágenes no se construyeron. Revisa los logs."
fi

# ── Resumen final ─────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✅  Build completo — todas las imágenes OK${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo -e "  Próximo paso:  ${CYAN}docker compose up -d${NC}"
echo ""
