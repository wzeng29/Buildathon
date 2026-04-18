#!/bin/bash
# =============================================================================
# Poleras Store — Teardown Script
# Detiene y elimina todos los contenedores, redes y volúmenes
# Uso: ./scripts/teardown.sh
# =============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}  Poleras Store — Teardown${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""
echo -e "${RED}ADVERTENCIA: Esto detendrá todos los contenedores y eliminará los datos.${NC}"
echo ""
read -p "¿Estás seguro? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Teardown cancelado${NC}"
    exit 0
fi
echo ""

echo -e "${YELLOW}[1/2]${NC} Deteniendo y eliminando contenedores..."
docker compose down --remove-orphans
echo -e "${GREEN}✓ Contenedores detenidos${NC}"
echo ""

echo -e "${YELLOW}[2/2]${NC} ¿Eliminar también los volúmenes (datos de BD, métricas, logs)?"
read -p "(y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose down -v
    echo -e "${GREEN}✓ Volúmenes eliminados${NC}"
else
    echo -e "${BLUE}Volúmenes conservados${NC}"
fi
echo ""

echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}  ✅ Teardown completo${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""
echo -e "Para levantar de nuevo: ${YELLOW}./scripts/setup.sh${NC}  o  ${YELLOW}docker compose up -d${NC}"
echo ""
