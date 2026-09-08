/* ==========================================================================
   auth.js — shared auth helpers used on every IBVAP page.

   - Stores JWT in localStorage['ibvap.token']
   - Exposes ibvap_auth.fetch() — a fetch wrapper that:
       * attaches Authorization: Bearer <token>
       * on 401 → clears token, redirects to /login
       * on 403 → shows the global ACCESS DENIED bar for 4s
   - Exposes ibvap_auth.token(), ibvap_auth.user(), ibvap_auth.logout(),
     ibvap_auth.requireAuth() (redirects to /login if not authed)
   ========================================================================== */

(function () {
  const TOKEN_KEY = 'ibvap.token';
  const USER_KEY  = 'ibvap.user';

  function token() {
    let t = localStorage.getItem(TOKEN_KEY) || null;
    if (!t) {
      const match = document.cookie.match(/(?:^|;\s*)ibvap\.token=([^;]+)/);
      if (match) {
        t = decodeURIComponent(match[1]);
        try { localStorage.setItem(TOKEN_KEY, t); } catch (_) {}
      }
    }
    return t;
  }

  function user() {
    try {
      const u = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
      if (u) return u;
      const t = token();
      if (t) {
        const parts = t.split('.');
        if (parts.length === 3) {
          const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
          const derived = {
            username: payload.sub || payload.username,
            role: payload.role,
            display_name: payload.display_name || payload.sub,
          };
          try { localStorage.setItem(USER_KEY, JSON.stringify(derived)); } catch (_) {}
          return derived;
        }
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  function storeSession(payload) {
    if (!payload || !payload.token) {
      throw new Error('storeSession: missing token');
    }
    localStorage.setItem(TOKEN_KEY, payload.token);
    localStorage.setItem(USER_KEY, JSON.stringify({
      username:      payload.username,
      role:           payload.role,
      display_name:   payload.display_name,
      expires_at:     Date.now() + (payload.expires_in || 8 * 3600) * 1000,
    }));
  }

  function logout(reason) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    // Clear the navigation cookie too (best-effort; HttpOnly would prevent this
    // but we deliberately set httponly=false so we can clear it client-side).
    document.cookie = 'ibvap.token=; Max-Age=0; path=/; SameSite=Lax';
    const q = reason ? ('?reason=' + encodeURIComponent(reason)) : '';
    window.location.replace('/login' + q);
  }

  function ensureAuthed() {
    const t = token();
    if (!t) {
      window.location.replace('/login?reason=unauth');
      return false;
    }
    // Client-side expiry check (server is source of truth).
    const u = user();
    if (u && u.expires_at && Date.now() > u.expires_at) {
      logout('expired');
      return false;
    }
    return true;
  }

  function showAccessDenied(detail) {
    let bar = document.getElementById('access-denied-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'access-denied-bar';
      bar.setAttribute('role', 'alert');
      document.body.prepend(bar);
    }
    const who = (user() && user().display_name) || (user() && user().username) || 'UNKNOWN';
    bar.textContent = 'ACCESS DENIED — ' + (detail || 'insufficient role') + ' / ' + who.toUpperCase();
    bar.classList.add('is-visible');
    clearTimeout(bar._t);
    bar._t = setTimeout(() => bar.classList.remove('is-visible'), 4000);
  }

  /**
   * Authenticated fetch — adds Authorization, handles 401/403 globally.
   */
  async function fetchAuthed(url, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    const t = token();
    if (t) headers['Authorization'] = 'Bearer ' + t;
    if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(url, Object.assign({}, opts, { headers }));
    if (res.status === 401) {
      logout('unauth');
      throw new Error('unauthorized — session ended');
    }
    if (res.status === 403) {
      // Try to extract detail message.
      let detail = 'insufficient role';
      try {
        const j = await res.clone().json();
        if (j && j.detail) detail = j.detail;
      } catch (_) {}
      showAccessDenied(detail);
      throw new Error('forbidden — ' + detail);
    }
    return res;
  }

  // Expose globally.
  window.ibvap_auth = {
    TOKEN_KEY,
    USER_KEY,
    token,
    user,
    storeSession,
    logout,
    ensureAuthed,
    fetchAuthed,
    showAccessDenied,
  };
})();
