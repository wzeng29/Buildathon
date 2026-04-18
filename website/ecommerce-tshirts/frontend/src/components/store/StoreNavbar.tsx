import { useState, useEffect } from "react";
import { getUser, clearAuth, getCartCount } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

export default function StoreNavbar() {
  const [user, setUser] = useState<any>(null);
  const [cartCount, setCartCount] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const { t, localePath, switchLangUrl } = useI18n();

  useEffect(() => {
    setUser(getUser());
    setCartCount(getCartCount());

    const onAuth = () => setUser(getUser());
    const onCart = () => setCartCount(getCartCount());

    window.addEventListener("auth_change", onAuth);
    window.addEventListener("cart_change", onCart);
    return () => {
      window.removeEventListener("auth_change", onAuth);
      window.removeEventListener("cart_change", onCart);
    };
  }, []);

  const handleLogout = () => {
    clearAuth();
    window.location.href = localePath("/");
  };

  return (
    <nav className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <a href={localePath("/")} className="flex items-center gap-2 font-bold text-xl text-indigo-600">
            <svg className="w-7 h-7" fill="currentColor" viewBox="0 0 24 24">
              <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
            </svg>
            Poleras Store
          </a>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-6 text-sm font-medium">
            <a href={localePath("/productos")} className="text-gray-600 hover:text-indigo-600 transition-colors">
              {t("nav.products")}
            </a>
            <a href={localePath("/productos") + "?categoria=basica"} className="text-gray-600 hover:text-indigo-600 transition-colors">
              {t("nav.basics")}
            </a>
            <a href={localePath("/productos") + "?categoria=oversize"} className="text-gray-600 hover:text-indigo-600 transition-colors">
              {t("nav.oversize")}
            </a>
            <a href={localePath("/productos") + "?categoria=estampada"} className="text-gray-600 hover:text-indigo-600 transition-colors">
              {t("nav.printed")}
            </a>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-3">
            {/* Language switcher */}
            <button
              onClick={() => { window.location.href = switchLangUrl(); }}
              className="text-xs font-semibold px-2 py-1 rounded-md border border-gray-300 text-gray-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
            >
              {t("lang.switch")}
            </button>

            {/* Cart */}
            <a href={localePath("/carrito")} className="relative p-2 text-gray-600 hover:text-indigo-600 transition-colors">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm-8 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4z" />
              </svg>
              {cartCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-indigo-600 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center font-bold">
                  {cartCount > 9 ? "9+" : cartCount}
                </span>
              )}
            </a>

            {/* Auth */}
            {user ? (
              <div className="relative">
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2 text-sm text-gray-700 hover:text-indigo-600 transition-colors"
                >
                  <div className="w-8 h-8 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center font-semibold text-xs">
                    {user.firstname?.[0]?.toUpperCase() ?? "U"}
                  </div>
                  <span className="hidden md:block">{user.firstname}</span>
                </button>
                {menuOpen && (
                  <div className="absolute right-0 mt-2 w-48 bg-white border border-gray-200 rounded-lg shadow-lg py-1 text-sm">
                    <a href={localePath("/mi-cuenta/pedidos")} className="block px-4 py-2 text-gray-700 hover:bg-gray-50">
                      {t("nav.myOrders")}
                    </a>
                    <button
                      onClick={handleLogout}
                      className="block w-full text-left px-4 py-2 text-red-600 hover:bg-gray-50"
                    >
                      {t("nav.logout")}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <a
                href={localePath("/mi-cuenta")}
                className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                {t("nav.login")}
              </a>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
