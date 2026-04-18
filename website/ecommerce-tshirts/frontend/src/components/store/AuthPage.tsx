import { useState, useEffect } from "react";
import { getUser } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";
import LoginForm from "./LoginForm";
import RegisterForm from "./RegisterForm";

export default function AuthPage() {
  const [view, setView] = useState<"login" | "register">("login");
  const [redirect, setRedirect] = useState("/");
  const { t, localePath } = useI18n();

  useEffect(() => {
    const defaultRedirect = localePath("/");
    const r = new URLSearchParams(window.location.search).get("redirect") ?? defaultRedirect;
    setRedirect(r);
    if (getUser()) {
      window.location.href = r;
    }
  }, []);

  return (
    <div className="min-h-[70vh] flex items-center justify-center py-10">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <a href={localePath("/")} className="inline-flex items-center gap-2 font-bold text-2xl text-indigo-600">
            <svg className="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
              <path d="M16.5 6.75A4.5 4.5 0 0 0 12 2.25a4.5 4.5 0 0 0-4.5 4.5H3l1.5 14.25h15L21 6.75h-4.5Z" />
            </svg>
            Poleras Store
          </a>
          <p className="text-gray-500 mt-2 text-sm">
            {view === "login" ? t("auth.welcome") : t("auth.createAccount")}
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-gray-100 rounded-xl p-1 mb-6">
          <button
            onClick={() => setView("login")}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
              view === "login" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t("auth.login")}
          </button>
          <button
            onClick={() => setView("register")}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition-colors ${
              view === "register" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {t("auth.register")}
          </button>
        </div>

        {/* Form card */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
          {view === "login" ? (
            <LoginForm redirect={redirect} onSwitchToRegister={() => setView("register")} />
          ) : (
            <RegisterForm redirect={redirect} onSwitchToLogin={() => setView("login")} />
          )}
        </div>
      </div>
    </div>
  );
}
