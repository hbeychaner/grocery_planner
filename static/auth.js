document.addEventListener("DOMContentLoaded", () => {
  const authBtn = document.getElementById("btn-auth-modal");
  const authModal = document.getElementById("auth-modal");
  const authClose = document.getElementById("auth-modal-close");
  const authForm = document.getElementById("auth-form");
  const authTitle = document.getElementById("auth-modal-title");
  const authNameGroup = document.getElementById("auth-name-group");
  const authSubmitBtn = document.getElementById("auth-submit-btn");
  const authToggleMode = document.getElementById("auth-toggle-mode");
  const authError = document.getElementById("auth-error");
  const authGoogleBtn = document.getElementById("auth-google-btn");
  const authLogoutBtn = document.getElementById("auth-logout-btn");

  if (!authBtn) return;

  let isRegisterMode = false;
  let currentUser = null;
  let googleEnabled = false;

  async function refreshAuthStatus() {
    try {
      const resp = await fetch("/api/v1/auth/me");
      if (!resp.ok) return;
      const data = await resp.json();
      currentUser = data.authenticated ? data.user : null;
      googleEnabled = Boolean(data.google_oauth_enabled);

      if (currentUser) {
        authBtn.textContent = currentUser.display_name || currentUser.email;
        if (authLogoutBtn) authLogoutBtn.classList.remove("hidden");
      } else {
        authBtn.textContent = "Sign In";
        if (authLogoutBtn) authLogoutBtn.classList.add("hidden");
      }
      if (authGoogleBtn) {
        authGoogleBtn.classList.toggle("hidden", !googleEnabled);
      }
    } catch (_) {}
  }

  function renderMode() {
    if (!authTitle) return;
    authTitle.textContent = isRegisterMode ? "Create Account" : "Sign In";
    authSubmitBtn.textContent = isRegisterMode ? "Create Account" : "Sign In";
    authToggleMode.textContent = isRegisterMode
      ? "Already have an account? Sign in"
      : "Need an account? Register";
    if (authNameGroup) authNameGroup.classList.toggle("hidden", !isRegisterMode);
    if (authError) authError.textContent = "";
  }

  authBtn.addEventListener("click", () => {
    if (authModal) {
      renderMode();
      authModal.classList.remove("hidden");
    }
  });

  if (authClose && authModal) {
    authClose.addEventListener("click", () => authModal.classList.add("hidden"));
  }

  if (authToggleMode) {
    authToggleMode.addEventListener("click", () => {
      isRegisterMode = !isRegisterMode;
      renderMode();
    });
  }

  if (authLogoutBtn) {
    authLogoutBtn.addEventListener("click", async () => {
      await fetch("/api/v1/auth/logout", { method: "POST" });
      if (authModal) authModal.classList.add("hidden");
      await refreshAuthStatus();
    });
  }

  if (authForm) {
    authForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (authError) authError.textContent = "";
      const email = document.getElementById("auth-email").value.trim();
      const password = document.getElementById("auth-password").value;
      const displayName = document.getElementById("auth-display-name")?.value.trim();
      const endpoint = isRegisterMode ? "/api/v1/auth/register" : "/api/v1/auth/login";
      const body = isRegisterMode ? { email, password, display_name: displayName || null } : { email, password };

      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const res = await resp.json();
      if (!resp.ok) {
        if (authError) authError.textContent = res.detail || "Authentication failed";
        return;
      }
      if (authModal) authModal.classList.add("hidden");
      authForm.reset();
      await refreshAuthStatus();
    });
  }

  refreshAuthStatus();
});
