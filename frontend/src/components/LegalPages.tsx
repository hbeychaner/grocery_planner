import { ArrowLeft } from "lucide-react";
import { useLang } from "../i18n";

interface LegalPagesProps {
  page: "privacy" | "terms";
  onNavigate?: (path: string) => void;
}

export function LegalPages({ page, onNavigate }: LegalPagesProps) {
  const { t } = useLang();

  function go(path: string) {
    if (onNavigate) {
      onNavigate(path);
    } else {
      window.location.href = path;
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="max-w-3xl mx-auto rounded-2xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              {page === "privacy"
                ? t("Privacy Policy", "Zásady ochrany osobních údajů")
                : t("Terms of Use", "Podmínky použití")}
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              {t("Grocery Planner — Last updated: November 22, 2026", "Grocery Planner — Poslední aktualizace: 22. listopadu 2026")}
            </p>
          </div>
          <button
            type="button"
            onClick={() => go("/")}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>{t("Back to App", "Zpět do aplikace")}</span>
          </button>
        </div>

        {page === "privacy" ? (
          <div className="space-y-4 text-sm text-slate-700 leading-relaxed">
            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("1. Information We Collect", "1. Jaké údaje shromažďujeme")}
              </h2>
              <p>
                {t(
                  "When you create an account or sign in with Google, we store your email address, display name, and authentication identifier (a salted password hash for local accounts or your Google account subject ID for OAuth). We also set an HTTP-only session cookie (gp_session) strictly to keep you signed in.",
                  "Při registraci nebo přihlášení přes Google ukládáme váš e-mail, zobrazované jméno a přihlašovací identifikátor (hash hesla pro lokální účty nebo Google ID pro OAuth). Pro udržení přihlášení používáme výhradně HTTP-only cookie (gp_session)."
                )}
              </p>
            </section>

            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("2. How We Use Your Data", "2. Jak údaje používáme")}
              </h2>
              <p>
                {t(
                  "Your account information is used solely to authenticate access to Grocery Planner, personalize your experience, and protect the service against abuse via basic IP rate limiting. We do not sell, rent, or share your personal information with third-party advertisers.",
                  "Údaje o účtu slouží výhradně k ověření přístupu do aplikace Grocery Planner, personalizaci a ochraně služby před zneužitím. Vaše osobní údaje neprodáváme ani neposkytujeme třetím stranám pro reklamní účely."
                )}
              </p>
            </section>

            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("3. AI Assistant & Third-Party APIs", "3. AI asistent a externí služby")}
              </h2>
              <p>
                {t(
                  "Queries submitted to the Grocery Assistant or search bar are used to look up live product prices from Rohlík.cz, Košík.cz, and Kupi.cz, and may be processed by Google Gemini APIs to translate queries or generate summaries. Please avoid entering sensitive personal information into chat prompts.",
                  "Dotazy zadané do vyhledávání nebo asistenta nákupů slouží k zjištění aktuálních cen na Rohlík.cz, Košík.cz a Kupi.cz a mohou být zpracovány pomocí Google Gemini API pro překlad nebo shrnutí. Do chatu prosím nezadávejte citlivé osobní údaje."
                )}
              </p>
            </section>

            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("4. Data Retention & Deletion", "4. Uchování a smazání údajů")}
              </h2>
              <p>
                {t(
                  "Your account and session records are stored in the application's database only while your account is active. You may sign out at any time or contact the app administrator to request deletion of your account.",
                  "Účet a záznamy relací jsou uloženy v databázi aplikace pouze po dobu aktivního účtu. Kdykoliv se můžete odhlásit nebo požádat správce aplikace o odstranění účtu."
                )}
              </p>
            </section>
          </div>
        ) : (
          <div className="space-y-4 text-sm text-slate-700 leading-relaxed">
            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("1. Informational Purpose Only", "1. Pouze informativní charakter")}
              </h2>
              <p>
                {t(
                  "Grocery Planner aggregates publicly available product listings, promotional discounts, and official statistical benchmarks (ČSÚ and US BLS) for personal price comparison and budgeting. Prices, stock availability, and discount end dates are provided 'as is' and may change on the retailer's website at any time.",
                  "Grocery Planner shromažďuje veřejně dostupné ceny potravin, akční slevy a statistická data (ČSÚ a US BLS) pro osobní porovnání cen. Ceny, dostupnost i platnost slev jsou poskytovány bez záruky a mohou se na stránkách prodejců kdykoliv změnit."
                )}
              </p>
            </section>

            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("2. Acceptable Use", "2. Přijatelné používání")}
              </h2>
              <p>
                {t(
                  "You agree to use this application for personal, non-commercial household grocery planning and not to attempt automated scraping, denial-of-service attacks, or unauthorized access to other users' accounts.",
                  "Zavazujete se používat aplikaci pouze pro osobní, nekomerční plánování nákupů a nepokoušet se o automatizované vytěžování, přetěžování služby ani neoprávněný přístup k cizím účtům."
                )}
              </p>
            </section>

            <section className="space-y-1.5">
              <h2 className="text-base font-semibold text-slate-900">
                {t("3. Limitation of Liability", "3. Omezení odpovědnosti")}
              </h2>
              <p>
                {t(
                  "Grocery Planner is not affiliated with Rohlík.cz, Košík.cz, or Kupi.cz. Always verify final checkout prices and terms directly on the retailer's website before placing an order.",
                  "Aplikace Grocery Planner není spojena se společnostmi Rohlík.cz, Košík.cz ani Kupi.cz. Konečné ceny a podmínky si před objednávkou vždy ověřte přímo na webu příslušného prodejce."
                )}
              </p>
            </section>
          </div>
        )}

        <div className="pt-4 border-t border-slate-200 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
          <div className="flex gap-4">
            <button type="button" onClick={() => go("/privacy")} className="hover:text-slate-900 underline cursor-pointer">
              {t("Privacy Policy", "Zásady ochrany osobních údajů")}
            </button>
            <button type="button" onClick={() => go("/terms")} className="hover:text-slate-900 underline cursor-pointer">
              {t("Terms of Use", "Podmínky použití")}
            </button>
          </div>
          <span>Grocery Planner</span>
        </div>
      </div>
    </div>
  );
}
