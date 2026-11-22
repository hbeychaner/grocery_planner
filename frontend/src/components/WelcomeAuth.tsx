import { useState, type FormEvent } from "react";
import { ArrowRight, BarChart3, Bot, ShoppingCart } from "lucide-react";
import { loginLocal, registerLocal, type AuthStatus } from "../api";

interface WelcomeAuthProps {
  googleOAuthEnabled: boolean;
  onAuthenticated: (status: AuthStatus) => void;
}

export function WelcomeAuth({ googleOAuthEnabled, onAuthenticated }: WelcomeAuthProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const status = isRegister
        ? await registerLocal(email.trim(), password, displayName.trim())
        : await loginLocal(email.trim(), password);
      onAuthenticated(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col justify-center px-6 py-12">
      <div className="max-w-5xl w-full mx-auto grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
        {/* Left Hero */}
        <div className="lg:col-span-7 space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-600 shadow-xs">
            Prague Grocery Intelligence
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 leading-tight">
            Compare Czech supermarkets and track real food inflation.
          </h1>
          <p className="text-base text-slate-600 leading-relaxed max-w-xl">
            Live normalized unit-price matching across Rohlík.cz and Košík.cz, 24-month ČSÚ vs. US BLS
            benchmarks normalized by median income, and an A2A Gemini assistant.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
              <ShoppingCart className="w-4 h-4 text-indigo-600 mb-2" />
              <div className="text-xl font-bold text-slate-900">219+</div>
              <div className="text-xs text-slate-500">Tracked groceries</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
              <BarChart3 className="w-4 h-4 text-indigo-600 mb-2" />
              <div className="text-xl font-bold text-slate-900">24 mo</div>
              <div className="text-xs text-slate-500">ČSÚ &amp; US BLS data</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
              <Bot className="w-4 h-4 text-indigo-600 mb-2" />
              <div className="text-xl font-bold text-slate-900">A2A + MCP</div>
              <div className="text-xs text-slate-500">Gemini 3.5 Flash</div>
            </div>
          </div>
        </div>

        {/* Right Auth Card */}
        <div className="lg:col-span-5">
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                {isRegister ? "Create your account" : "Sign in to Grocery Planner"}
              </h2>
              <p className="text-xs text-slate-500 mt-1">
                {isRegister
                  ? "Register a local account to access live comparisons and trends."
                  : "Authenticate to access price comparisons, trends, and the AI assistant."}
              </p>
            </div>

            {googleOAuthEnabled && (
              <>
                <a
                  href="/auth/google/login"
                  className="w-full inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg border border-slate-300 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
                >
                  Continue with Google
                </a>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <div className="h-px flex-1 bg-slate-200" />
                  <span>or email</span>
                  <div className="h-px flex-1 bg-slate-200" />
                </div>
              </>
            )}

            <form onSubmit={handleSubmit} className="space-y-3.5">
              {isRegister && (
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Display Name</label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Your name"
                    className="w-full px-3 py-2 rounded-lg border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Email</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {error && (
                <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition cursor-pointer"
              >
                <span>{loading ? "Please wait..." : isRegister ? "Create Account" : "Sign In"}</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>

            <div className="pt-2 border-t border-slate-100 text-center space-y-2">
              <button
                type="button"
                onClick={() => {
                  setIsRegister(!isRegister);
                  setError(null);
                }}
                className="text-xs text-indigo-600 hover:underline font-medium cursor-pointer"
              >
                {isRegister ? "Already have an account? Sign in" : "Need an account? Create one"}
              </button>
              <div className="flex items-center justify-center gap-3 text-[11px] text-slate-400">
                <a href="/privacy" className="hover:text-slate-700 underline">
                  Privacy Policy
                </a>
                <span>&bull;</span>
                <a href="/terms" className="hover:text-slate-700 underline">
                  Terms of Use
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
