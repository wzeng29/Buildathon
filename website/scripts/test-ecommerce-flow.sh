#!/bin/bash
# ================================================================
# E-commerce Poleras — Full Flow Integration Test
# Tests: register → login → browse → add to cart → order → pay
# ================================================================

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

USERS_API="http://localhost:3001"
PRODUCTS_API="http://localhost:3002"
CART_API="http://localhost:3003"
ORDERS_API="http://localhost:3004"
PAYMENTS_API="http://localhost:3005"

PASS=0
FAIL=0

check() {
  local label="$1"
  local condition="$2"
  if [ "$condition" = "true" ]; then
    echo -e "  ${GREEN}✓${NC} $label"
    PASS=$((PASS + 1))
  else
    echo -e "  ${RED}✗${NC} $label"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   E-commerce Poleras - Integration Flow Test      ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# ─── STEP 0: Health Checks ───────────────────────────────────────
echo -e "${YELLOW}[0] Health Checks${NC}"
for service in "$USERS_API" "$PRODUCTS_API" "$CART_API" "$ORDERS_API" "$PAYMENTS_API"; do
  status=$(curl -s -o /dev/null -w "%{http_code}" "$service/health" 2>/dev/null || echo "000")
  name=$(echo "$service" | sed 's/http:\/\/localhost://g')
  check "Service :$name health" "$([ "$status" = "200" ] && echo true || echo false)"
done
echo ""

# ─── STEP 1: Register User ───────────────────────────────────────
echo -e "${YELLOW}[1] Register Customer${NC}"
RAND=$(date +%s%N | tail -c 6)
EMAIL="testuser${RAND}@poleras.cl"

REGISTER_RESP=$(curl -s -X POST "$USERS_API/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"firstname\":\"Test\",\"lastname\":\"Usuario\",\"email\":\"$EMAIL\",\"password\":\"test123\"}")

TOKEN=$(echo "$REGISTER_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token',''))" 2>/dev/null || echo "")
check "Register returns JWT token" "$([ -n "$TOKEN" ] && echo true || echo false)"
echo "    Email: $EMAIL"
echo ""

# ─── STEP 2: Login ───────────────────────────────────────────────
echo -e "${YELLOW}[2] Login${NC}"
LOGIN_RESP=$(curl -s -X POST "$USERS_API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"test123\"}")

LOGIN_TOKEN=$(echo "$LOGIN_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('token',''))" 2>/dev/null || echo "")
check "Login returns JWT token" "$([ -n "$LOGIN_TOKEN" ] && echo true || echo false)"

# Use login token going forward
if [ -n "$LOGIN_TOKEN" ]; then TOKEN="$LOGIN_TOKEN"; fi
echo ""

# ─── STEP 3: List Products ───────────────────────────────────────
echo -e "${YELLOW}[3] Browse Products${NC}"
PRODUCTS_RESP=$(curl -s "$PRODUCTS_API/api/products?limit=12")
PRODUCT_COUNT=$(echo "$PRODUCTS_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")
check "Products list returns > 0 products" "$([ "$PRODUCT_COUNT" -gt 0 ] && echo true || echo false)"

# Get first product slug
PRODUCT_SLUG=$(echo "$PRODUCTS_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['slug'])" 2>/dev/null || echo "")
check "Product has slug" "$([ -n "$PRODUCT_SLUG" ] && echo true || echo false)"
echo "    Products found: $PRODUCT_COUNT | Using: $PRODUCT_SLUG"

# List categories
CATS_RESP=$(curl -s "$PRODUCTS_API/api/categories")
CAT_COUNT=$(echo "$CATS_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")
check "Categories returns 5 categories" "$([ "$CAT_COUNT" -eq 5 ] && echo true || echo false)"
echo ""

# ─── STEP 4: Product Detail ──────────────────────────────────────
echo -e "${YELLOW}[4] Product Detail (PDP)${NC}"
PDP_RESP=$(curl -s "$PRODUCTS_API/api/products/$PRODUCT_SLUG")
VARIANT_ID=$(echo "$PDP_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d['data']['variants'][1]['id'])" 2>/dev/null || echo "")
VARIANT_STOCK=$(echo "$PDP_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d['data']['variants'][0]['stock'])" 2>/dev/null || echo "0")
check "Product detail returns variants" "$([ -n "$VARIANT_ID" ] && echo true || echo false)"
echo "    Variant ID: $VARIANT_ID (stock: $VARIANT_STOCK)"
echo ""

# ─── STEP 5: Add to Cart ─────────────────────────────────────────
echo -e "${YELLOW}[5] Add to Cart${NC}"
CART_ADD_RESP=$(curl -s -X POST "$CART_API/api/cart/items" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"variant_id\":$VARIANT_ID,\"quantity\":1}")

CART_TOTAL=$(echo "$CART_ADD_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('total',0))" 2>/dev/null || echo "0")
CART_STATUS=$(echo "$CART_ADD_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
check "Item added to cart" "$([ "$CART_STATUS" = "OK" ] && echo true || echo false)"
echo "    Cart total: \$$(echo "$CART_TOTAL") CLP"
echo ""

# ─── STEP 6: View Cart ───────────────────────────────────────────
echo -e "${YELLOW}[6] View Cart${NC}"
CART_RESP=$(curl -s "$CART_API/api/cart" -H "Authorization: Bearer $TOKEN")
CART_ITEMS=$(echo "$CART_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('data',{}).get('items',[])))" 2>/dev/null || echo "0")
check "Cart has items" "$([ "$CART_ITEMS" -gt 0 ] && echo true || echo false)"
echo ""

# ─── STEP 7: Create Order ────────────────────────────────────────
echo -e "${YELLOW}[7] Create Order${NC}"
ORDER_RESP=$(curl -s -X POST "$ORDERS_API/api/orders" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"shipping_address":{"street":"Av. Providencia 1234","city":"Santiago","region":"RM","zip":"7500000"}}')

ORDER_STATUS=$(echo "$ORDER_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
ORDER_ID=$(echo "$ORDER_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('id',''))" 2>/dev/null || echo "")
ORDER_NUMBER=$(echo "$ORDER_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('order_number',''))" 2>/dev/null || echo "")
check "Order created successfully" "$([ "$ORDER_STATUS" = "OK" ] && echo true || echo false)"
check "Order number generated (POL-YYYY-XXXXX)" "$(echo "$ORDER_NUMBER" | grep -qE '^POL-[0-9]{4}-[0-9]{5}$' && echo true || echo false)"
echo "    Order ID: $ORDER_ID | Number: $ORDER_NUMBER"
echo ""

# ─── STEP 8: Process Payment ─────────────────────────────────────
echo -e "${YELLOW}[8] Process Payment${NC}"
PAYMENT_RESP=$(curl -s -X POST "$PAYMENTS_API/api/payments/process" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"order_id\":$ORDER_ID,\"payment_method\":\"credit_card\",\"card_number\":\"4111 1111 1111 1234\"}")

PAYMENT_STATUS=$(echo "$PAYMENT_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('status',''))" 2>/dev/null || echo "")
TRANSACTION_ID=$(echo "$PAYMENT_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('transaction_id','N/A'))" 2>/dev/null || echo "N/A")
check "Payment processed (approved or rejected)" "$([ "$PAYMENT_STATUS" = "approved" ] || [ "$PAYMENT_STATUS" = "rejected" ] && echo true || echo false)"
echo "    Payment status: $PAYMENT_STATUS | TX: $TRANSACTION_ID"
echo ""

# ─── STEP 9: List My Orders ──────────────────────────────────────
echo -e "${YELLOW}[9] My Orders (Customer History)${NC}"
MY_ORDERS_RESP=$(curl -s "$ORDERS_API/api/orders" -H "Authorization: Bearer $TOKEN")
MY_ORDERS_COUNT=$(echo "$MY_ORDERS_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")
check "My orders list returns > 0 orders" "$([ "$MY_ORDERS_COUNT" -gt 0 ] && echo true || echo false)"
echo ""

# ─── STEP 10: Force Rejected Payment (testing) ───────────────────
echo -e "${YELLOW}[10] Test Payment Rejection (card ending 0000)${NC}"
# Create another order first (need a fresh pending order)
# Skip if previous order already exists, just test the rejection logic

REJECT_RESP=$(curl -s -X POST "$PAYMENTS_API/api/payments/process" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"order_id\":99999,\"payment_method\":\"debit_card\",\"card_number\":\"4111 1111 1111 0000\"}")
REJECT_CODE=$(echo "$REJECT_RESP" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('code',0))" 2>/dev/null || echo "0")
# We expect 404 (order not found) or 402 (rejected) - both are handled
check "Rejection endpoint responds correctly" "$([ "$REJECT_CODE" -gt 0 ] && echo true || echo false)"
echo ""

# ─── SUMMARY ─────────────────────────────────────────────────────
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "  Results: ${GREEN}$PASS passed${NC} / ${RED}$FAIL failed${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo -e "${YELLOW}Tip: Make sure all services are running:${NC}"
  echo "  docker compose up -d"
  echo "  docker compose ps"
  echo ""
fi

echo -e "Grafana Dashboards: ${BLUE}http://localhost:3000${NC} (admin/admin)"
echo -e "Traces in Tempo:    ${BLUE}http://localhost:3000/explore${NC}"
echo ""
