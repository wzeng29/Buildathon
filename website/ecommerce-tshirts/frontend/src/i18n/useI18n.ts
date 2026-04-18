import { translations, type Lang } from "./translations";

function getLang(): Lang {
  if (typeof document === "undefined") return "en";
  const lang = document.documentElement.lang;
  return lang === "es" ? "es" : "en";
}

export function useI18n() {
  const lang = getLang();
  const dict = translations[lang];

  /** Translate a key, optionally replacing {placeholder} tokens */
  function t(key: string, params?: Record<string, string | number>): string {
    let value = dict[key];
    if (value === undefined) return key;
    if (!params) return value;
    return Object.entries(params).reduce(
      (s, [k, v]) => s.replace(`{${k}}`, String(v)),
      value,
    );
  }

  /**
   * Prefix a path with /es when the current locale is Spanish.
   * English is the default locale so no prefix is added.
   * e.g. localePath("/productos") → "/es/productos" on Spanish pages
   */
  function localePath(path: string): string {
    if (lang === "es") {
      if (path.startsWith("/es")) return path;
      return "/es" + (path === "/" ? "" : path);
    }
    return path;
  }

  /**
   * Returns the URL for the same page in the other language.
   * Works by adding or removing the /es prefix from window.location.pathname.
   */
  function switchLangUrl(): string {
    if (typeof window === "undefined") return "/";
    const path = window.location.pathname;
    if (lang === "es") {
      // Remove /es prefix → go to English (default)
      return path.replace(/^\/es/, "") || "/";
    } else {
      // Add /es prefix → go to Spanish
      return "/es" + (path === "/" ? "" : path);
    }
  }

  return { t, lang, localePath, switchLangUrl };
}
