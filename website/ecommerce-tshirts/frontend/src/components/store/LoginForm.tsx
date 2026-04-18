import { useState } from "react";
import { authApi, saveAuth } from "@/lib/storeApi";
import { useI18n } from "@/i18n/useI18n";

interface Props {
  redirect?: string;
  onSwitchToRegister: () => void;
}

export default function LoginForm({ redirect = "/", onSwitchToRegister }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await authApi.login(email, password);
      saveAuth(res.data.token, res.data.user);
      window.location.href = redirect;
    } catch (e: any) {
      setError(e.message ?? t("auth.errorLogin"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.email")}</label>
        <input
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="tu@email.com"
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">{t("auth.password")}</label>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">{error}</p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors disabled:opacity-60"
      >
        {loading ? t("auth.logging") : t("auth.login")}
      </button>

      <p className="text-center text-sm text-gray-500">
        {t("auth.noAccount")}{" "}
        <button type="button" onClick={onSwitchToRegister} className="text-indigo-600 font-medium hover:underline">
          {t("auth.signUpFree")}
        </button>
      </p>
    </form>
  );
}
