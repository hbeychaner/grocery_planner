import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { fetchAuthStatus, logoutUser, type AuthStatus } from "./api";
import { ChatSidebar } from "./components/ChatSidebar";
import { CompareView } from "./components/CompareView";
import { DiscountsView } from "./components/DiscountsView";
import { TrendsView } from "./components/TrendsView";
import { WelcomeAuth } from "./components/WelcomeAuth";
import { LanguageProvider, useLang } from "./i18n";

type AppTab = "compare" | "discounts" | "trends";

export function App() {
  return (
    <LanguageProvider>
      <AppShell />
    </LanguageProvider>
  );
}

function AppShell() {
  const { lang, setLang, t } = useLang();
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [tab, setTab] = useState<AppTab>(() => {
    if (window.location.pathname === "/trends") return "trends";
    if (window.location.pathname === "/discounts") return "discounts";
    return "compare";
  });

  useEffect(() => {
    fetchAuthStatus().then(setAuth);
  }, []);

  function switchTab(next: AppTab) {
    setTab(next);
    const path = next === "trends" ? "/trends" : next === "discounts" ? "/discounts" : "/";
    window.history.pushState({}, "", path);
  }

  async function handleLogout() {
    await logoutUser();
    setAuth((prev) =>
      prev ? { ...prev, authenticated: false, user: null } : { authenticated: false, user: null, google_oauth_enabled: false }
    );
  }

  if (auth === null) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-slate-500">
        Loading Grocery Planner...
      </div>
    );
  }

  if (!auth.authenticated) {
    return (
      <WelcomeAuth
        googleOAuthEnabled={auth.google_oauth_enabled}
        onAuthenticated={(status) => setAuth(status)}
      />
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Top Navigation */}
      <header className="bg-white border-b border-slate-200 px-6 py-3">
        <div className="max-w-[1440px] mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <div>
              <span className="text-base font-bold text-slate-900">Grocery Planner</span>
              <span className="ml-2 text-xs text-slate-500">
                {t("Prague (Rohlík vs. Košík)", "Praha (Rohlík vs. Košík)")}
              </span>
            </div>
            <nav className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50 text-xs">
              <button
                type="button"
                onClick={() => switchTab("compare")}
                className={`px-3 py-1.5 rounded-md font-medium cursor-pointer ${
                  tab === "compare" ? "bg-indigo-600 text-white" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("Compare", "Porovnat")}
              </button>
              <button
                type="button"
                onClick={() => switchTab("discounts")}
                className={`px-3 py-1.5 rounded-md font-medium cursor-pointer ${
                  tab === "discounts" ? "bg-indigo-600 text-white" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("Discounts", "Slevy a akce")}
              </button>
              <button
                type="button"
                onClick={() => switchTab("trends")}
                className={`px-3 py-1.5 rounded-md font-medium cursor-pointer ${
                  tab === "trends" ? "bg-indigo-600 text-white" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("Price Trends", "Vývoj cen")}
              </button>
            </nav>
          </div>

          <div className="flex items-center gap-3 text-xs">
            <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50" role="group" aria-label="Language">
              <button
                type="button"
                onClick={() => setLang("en")}
                className={`px-2 py-1 rounded-md font-semibold cursor-pointer ${
                  lang === "en" ? "bg-white text-slate-900 shadow-2xs" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                EN
              </button>
              <button
                type="button"
                onClick={() => setLang("cs")}
                className={`px-2 py-1 rounded-md font-semibold cursor-pointer ${
                  lang === "cs" ? "bg-white text-slate-900 shadow-2xs" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                CS
              </button>
            </div>
            <a
              href="/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
            >
              API Docs
            </a>
            <span className="text-slate-600 font-medium">
              {auth.user?.display_name || auth.user?.email}
            </span>
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>{t("Sign Out", "Odhlásit se")}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Workspace + Right AI Assistant */}
      <div className="flex-1 max-w-[1440px] w-full mx-auto px-6 py-6 flex flex-col lg:flex-row gap-6 items-start">
        <main className="flex-1 min-w-0 w-full">
          {tab === "compare" ? (
            <CompareView />
          ) : tab === "discounts" ? (
            <DiscountsView />
          ) : (
            <TrendsView />
          )}
        </main>
        <ChatSidebar />
      </div>
    </div>
  );
}
