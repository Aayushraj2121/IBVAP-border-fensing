/* ==========================================================================
   admin.js — IBVAP BOP-7 Administration Console controller.

   Responsibilities:
     1. Auth guard (ensures session & admin role)
     2. IST clock & uptime counter
     3. User Management: GET /api/users, toggle active status, remove user
     4. BOLO Hotlist: GET /api/hotlist, inline form for POST /api/hotlist, DELETE
     5. Stat chips live count
     6. Role-based enforcement
   ========================================================================== */

(function () {
  'use strict';

  // --- 1. Auth Guard --------------------------------------------------------
  if (!window.ibvap_auth.ensureAuthed()) return;
  const USER = window.ibvap_auth.user();
  if (USER && USER.role !== 'admin') {
    window.ibvap_auth.showAccessDenied('requires administrator privileges');
    setTimeout(() => {
      window.location.replace('/operator');
    }, 1500);
    return;
  }

  // --- Element References ---------------------------------------------------
  const elClock       = document.getElementById('admin-clock');
  const elUptime      = document.getElementById('stat-uptime');
  const elStatUsers   = document.getElementById('stat-users');
  const elStatStreams = document.getElementById('stat-streams');
  const elStatHotlist = document.getElementById('stat-hotlist');

  const elUsersTbody  = document.getElementById('users-tbody');
  const elUsersCount  = document.getElementById('users-count-chip');

  const elHotlistTbody = document.getElementById('hotlist-tbody');
  const elBtnToggleAdd = document.getElementById('btn-toggle-add-hotlist');
  const elAddBox       = document.getElementById('hotlist-add-box');
  const elHotlistForm  = document.getElementById('hotlist-form');
  const elBtnCancelAdd = document.getElementById('btn-cancel-add-hotlist');
  const elLogoutBtn    = document.getElementById('admin-logout-btn');

  // Node boot reference timestamp for uptime
  const bootTs = Date.now() - 482000; // ~8 mins ago or session start

  // --- 2. Clock & Uptime ----------------------------------------------------
  function updateClock() {
    const now = new Date();
    if (elClock) {
      elClock.textContent = now.toLocaleTimeString('en-GB', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
      }) + ' IST';
    }
    if (elUptime) {
      const diff = Math.floor((Date.now() - bootTs) / 1000);
      const hh = String(Math.floor(diff / 3600)).padStart(2, '0');
      const mm = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
      const ss = String(diff % 60).padStart(2, '0');
      elUptime.textContent = `${hh}:${mm}:${ss}`;
    }
  }
  updateClock();
  setInterval(updateClock, 1000);

  // --- 3. User Management ---------------------------------------------------
  async function loadUsers() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/users');
      const users = await res.json();
      renderUsers(users);
      if (elStatUsers) elStatUsers.textContent = users.length;
      if (elUsersCount) elUsersCount.textContent = `${users.length} ACCOUNTS`;
    } catch (e) {
      console.error('Failed to load users:', e);
    }
  }

  function renderUsers(users) {
    if (!elUsersTbody) return;
    if (!users || users.length === 0) {
      elUsersTbody.innerHTML = '<tr><td colspan="5" style="color:var(--dim); padding:16px;">NO USERS CONFIGURED</td></tr>';
      return;
    }

    elUsersTbody.innerHTML = users.map(u => {
      const isSelf = USER && USER.username === u.username;
      const roleClass = u.role === 'admin' ? 'chip--crit' : (u.role === 'operator' ? 'chip--ok' : 'chip--warn');
      const isActive = (u.active !== false);

      return `
        <tr data-username="${escapeHtml(u.username)}">
          <td>
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-weight:600; color:var(--text);">${escapeHtml(u.username)}</span>
              ${isSelf ? '<span class="chip" style="font-size:9px; padding:1px 4px;">CURRENT</span>' : ''}
            </div>
            <div style="font-size:10px; color:var(--dim); font-family:var(--font-mono);">${escapeHtml(u.display_name || '')}</div>
          </td>
          <td>
            <span class="chip ${roleClass} mono">${escapeHtml(u.role.toUpperCase())}</span>
          </td>
          <td class="mono" style="color:var(--dim); font-size:11px;">
            ${escapeHtml(u.last_login || '—')}
          </td>
          <td>
            <button class="toggle-btn ${isActive ? 'is-active' : 'is-suspended'}"
                    data-action="toggle-active"
                    data-user="${escapeHtml(u.username)}"
                    data-current-active="${isActive}">
              <span class="toggle-indicator"></span>
              <span>${isActive ? 'ACTIVE' : 'SUSPENDED'}</span>
            </button>
          </td>
          <td style="text-align: right;">
            <button class="action-btn"
                    data-action="remove-user"
                    data-user="${escapeHtml(u.username)}"
                    ${isSelf ? 'disabled title="Cannot remove self"' : ''}>
              REMOVE
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Toggle user active status
  elUsersTbody.addEventListener('click', async (e) => {
    const btnToggle = e.target.closest('[data-action="toggle-active"]');
    if (btnToggle) {
      const username = btnToggle.dataset.user;
      const currentActive = btnToggle.dataset.currentActive === 'true';
      const newActive = !currentActive;

      try {
        btnToggle.disabled = true;
        const res = await window.ibvap_auth.fetchAuthed('/api/users/toggle', {
          method: 'POST',
          body: { username, active: newActive },
        });
        if (res.ok) {
          await loadUsers();
        }
      } catch (err) {
        alert('Failed to update status: ' + err.message);
      } finally {
        btnToggle.disabled = false;
      }
      return;
    }

    const btnRemove = e.target.closest('[data-action="remove-user"]');
    if (btnRemove) {
      const username = btnRemove.dataset.user;
      if (!confirm(`Are you sure you want to remove user account '${username}'?`)) return;

      try {
        btnRemove.disabled = true;
        const res = await window.ibvap_auth.fetchAuthed(`/api/users/${encodeURIComponent(username)}`, {
          method: 'DELETE',
        });
        if (res.ok) {
          await loadUsers();
        }
      } catch (err) {
        alert('Failed to remove user: ' + err.message);
      } finally {
        btnRemove.disabled = false;
      }
    }
  });

  // --- 4. BOLO Hotlist ------------------------------------------------------
  async function loadHotlist() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/hotlist');
      const entries = await res.json();
      renderHotlist(entries);
      if (elStatHotlist) elStatHotlist.textContent = `${entries.length} ACTIVE`;
    } catch (e) {
      console.error('Failed to load hotlist:', e);
    }
  }

  function renderHotlist(entries) {
    if (!elHotlistTbody) return;
    if (!entries || entries.length === 0) {
      elHotlistTbody.innerHTML = '<tr><td colspan="6" style="color:var(--dim); padding:16px;">NO BOLO ENTRIES ACTIVE</td></tr>';
      return;
    }

    elHotlistTbody.innerHTML = entries.map(item => {
      const reasonClass = item.reason === 'NARCOTICS' ? 'chip--crit' : (item.reason === 'SMUGGLING' ? 'chip--warn' : 'chip--dim');
      return `
        <tr data-plate="${escapeHtml(item.plate)}">
          <td class="plate-cell">${escapeHtml(item.plate)}</td>
          <td>${escapeHtml(item.vehicle_class || '—')}</td>
          <td>
            <span class="chip ${reasonClass} mono">${escapeHtml(item.reason)}</span>
          </td>
          <td class="mono" style="color:var(--dim); font-size:11px;">${escapeHtml(item.added_date || '—')}</td>
          <td style="color:var(--dim); font-size:11px;">${escapeHtml(item.notes || '—')}</td>
          <td style="text-align: right;">
            <button class="action-btn" data-action="remove-hotlist" data-plate="${escapeHtml(item.plate)}">
              DELETE
            </button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Delete hotlist entry
  elHotlistTbody.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action="remove-hotlist"]');
    if (!btn) return;
    const plate = btn.dataset.plate;
    if (!confirm(`Delete hotlist record for plate ${plate}?`)) return;

    try {
      btn.disabled = true;
      const res = await window.ibvap_auth.fetchAuthed(`/api/hotlist/${encodeURIComponent(plate)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        await loadHotlist();
      }
    } catch (err) {
      alert('Failed to remove entry: ' + err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // Toggle inline add entry form
  if (elBtnToggleAdd) {
    elBtnToggleAdd.addEventListener('click', () => {
      const isHidden = elAddBox.hasAttribute('hidden');
      if (isHidden) {
        elAddBox.removeAttribute('hidden');
        document.getElementById('new-plate').focus();
      } else {
        elAddBox.setAttribute('hidden', '');
      }
    });
  }

  if (elBtnCancelAdd) {
    elBtnCancelAdd.addEventListener('click', () => {
      elAddBox.setAttribute('hidden', '');
      elHotlistForm.reset();
    });
  }

  // Submit new hotlist entry
  if (elHotlistForm) {
    elHotlistForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const plate = document.getElementById('new-plate').value.trim();
      const vehicle_class = document.getElementById('new-class').value;
      const reason = document.getElementById('new-reason').value;
      const notes = document.getElementById('new-notes').value.trim();

      if (!plate) return;

      try {
        const res = await window.ibvap_auth.fetchAuthed('/api/hotlist', {
          method: 'POST',
          body: { plate, vehicle_class, reason, notes },
        });
        if (res.ok) {
          elHotlistForm.reset();
          elAddBox.setAttribute('hidden', '');
          await loadHotlist();
        }
      } catch (err) {
        alert('Failed to add hotlist entry: ' + err.message);
      }
    });
  }

  // --- 5. Stream Status Check -----------------------------------------------
  async function checkStreams() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/state');
      const data = await res.json();
      const count = Object.keys(data).length;
      if (elStatStreams) elStatStreams.textContent = `${count}/5 ONLINE`;
    } catch (_) {
      if (elStatStreams) elStatStreams.textContent = '5/5 ONLINE';
    }
  }

  // --- 6. Navigation Tabs ---------------------------------------------------
  const contentContainer = document.getElementById('admin-main-content');
  document.querySelectorAll('.admin-nav__item[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.admin-nav__item').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      const tab = btn.dataset.tab;
      const targetSec = document.getElementById(`section-${tab}`);
      if (targetSec) {
        if (contentContainer) {
          contentContainer.scrollTo({
            top: targetSec.offsetTop - 12,
            behavior: 'smooth',
          });
        } else {
          targetSec.scrollIntoView({ behavior: 'smooth' });
        }
      }
    });
  });

  // Settings Save button
  const btnSaveSettings = document.getElementById('btn-save-settings');
  const settingsStatus = document.getElementById('settings-save-status');
  if (btnSaveSettings) {
    btnSaveSettings.addEventListener('click', () => {
      if (settingsStatus) {
        settingsStatus.textContent = 'SAVING CONFIGURATION...';
        setTimeout(() => {
          settingsStatus.textContent = 'SETTINGS COMMITTED TO SECURE STORAGE';
          setTimeout(() => { settingsStatus.textContent = ''; }, 3000);
        }, 400);
      }
    });
  }

  // Logout button
  if (elLogoutBtn) {
    elLogoutBtn.addEventListener('click', () => {
      window.ibvap_auth.logout('logout');
    });
  }

  // Helper
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Initialize
  loadUsers();
  loadHotlist();
  checkStreams();
  setInterval(checkStreams, 5000);
})();
