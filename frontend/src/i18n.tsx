import { createContext, useContext, useState, type ReactNode } from "react";

export type AppLang = "en" | "cs";

interface LanguageContextValue {
  lang: AppLang;
  setLang: (next: AppLang) => void;
  t: (en: string, cs: string) => string;
}

const LanguageContext = createContext<LanguageContextValue>({
  lang: "en",
  setLang: () => {},
  t: (en) => en,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<AppLang>(() => {
    try {
      const saved = localStorage.getItem("gp_lang");
      return saved === "cs" ? "cs" : "en";
    } catch {
      return "en";
    }
  });

  function setLang(next: AppLang) {
    setLangState(next);
    try {
      localStorage.setItem("gp_lang", next);
    } catch {
      // ignore storage errors
    }
  }

  function t(en: string, cs: string): string {
    return lang === "cs" ? cs : en;
  }

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLang() {
  return useContext(LanguageContext);
}
