/* ==========================================================================
   login.js — page logic for /login.

   Flow:
     1. If a valid session exists in localStorage → redirect to /dashboard.
     2. On submit, POST form-encoded credentials to /login.
     3. On 200 → store JWT, redirect to /dashboard.
     4. On 401 → inline AUTHENTICATION FAILED message.
     5. On network error → inline NODE UNREACHABLE message.
   ========================================================================== */

(function () {
  // If already authed, bounce to dashboard.
  (function quickRedirect() {
    const t = window.ibvap_auth.token();
    if (!t) return;
    const u = window.ibvap_auth.user();
    if (u && u.expires_at && Date.now() < u.expires_at) {
      const target = {
        admin:    '/admin',
        operator: '/operator',
        auditor:  '/auditor',
      }[u.role] || '/operator';
      window.location.replace(target);
    } else {
      window.ibvap_auth.logout('expired');
    }
  })();

  const form     = document.getElementById('login-form');
  const username = document.getElementById('username');
  const password = document.getElementById('password');
  const submit   = document.getElementById('login-submit');
  const status   = document.getElementById('login-status');

  // Show ?reason=... hint if redirected here.
  (function showReasonHint() {
    const p = new URLSearchParams(window.location.search);
    const r = p.get('reason');
    if (!r) return;
    const map = {
      unauth:    'SESSION TERMINATED — REAUTHENTICATE',
      expired:   'SESSION EXPIRED — REAUTHENTICATE',
      logout:    'SESSION CLOSED',
    };
    setStatus(map[r] || ('SESSION: ' + r.toUpperCase()), 'warn');
  })();

  function setStatus(text, kind) {
    status.textContent = text;
    status.className = 'login-status';
    if (kind) status.classList.add('is-' + kind);
  }

  function clearStatus() {
    status.textContent = '';
    status.className = 'login-status';
  }

  function setLoading(loading) {
    if (loading) {
      submit.classList.add('is-loading');
      submit.disabled = true;
      setStatus('AUTHENTICATING...', 'loading');
    } else {
      submit.classList.remove('is-loading');
      submit.disabled = false;
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearStatus();

    const u = (username.value || '').trim();
    const p = password.value || '';
    if (!u || !p) {
      setStatus('OPERATOR ID AND PASSPHRASE REQUIRED', 'error');
      return;
    }

    setLoading(true);
    try {
      // /login accepts form-encoded (per FastAPI Form(...)).
      const body = new URLSearchParams();
      body.set('username', u);
      body.set('password', p);

      const res = await fetch('/login', {
        method: 'POST',
        body: body,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      if (res.status === 401) {
        setLoading(false);
        setStatus('AUTHENTICATION FAILED — INVALID CREDENTIALS', 'error');
        password.value = '';
        password.focus();
        return;
      }
      if (!res.ok) {
        setLoading(false);
        setStatus('NODE ERROR — HTTP ' + res.status, 'error');
        return;
      }

      const payload = await res.json();
      window.ibvap_auth.storeSession(payload);
      setStatus('AUTHENTICATED — REDIRECTING', 'ok');
      // Brief delay so the user sees the success state.
      setTimeout(() => {
        // Role-aware redirect: strictly route each role to its dedicated console.
        const target = {
          admin:    '/admin',
          operator: '/operator',
          auditor:  '/auditor',
        }[payload.role] || '/operator';
        window.location.replace(target);
      }, 240);
    } catch (err) {
      setLoading(false);
      setStatus('NODE UNREACHABLE — CHECK UPLINK', 'error');
      // eslint-disable-next-line no-console
      console.error('[ibvap.login] submit failed:', err);
    }
  });

  // Focus username on load.
  username.focus();
})();
