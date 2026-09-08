/* ==========================================================================
   auditor.js — IBVAP BOP-7 Forensic Auditor Console controller.

   Responsibilities:
     1. Auth guard (ensures session & auditor/admin role)
     2. IST clock live ticking
     3. Verify ledger integrity: call /api/ledger/verify → update green/red banner
     4. Render vertical ledger timeline: #num, mono timestamp, event chip,
        camera id, snapshot thumb, truncated SHA-256 (a3f9c2...e81b, mono, --dim),
        chain-link icons connecting blocks
     5. Export Section 65B Certificate form → trigger /api/export65b PDF download
     6. STRICTLY NO VIDEO ANYWHERE
   ========================================================================== */

(function () {
  'use strict';

  // --- 1. Auth Guard --------------------------------------------------------
  if (!window.ibvap_auth.ensureAuthed()) return;
  const USER = window.ibvap_auth.user();
  if (USER && USER.role !== 'auditor' && USER.role !== 'admin') {
    window.ibvap_auth.showAccessDenied('requires auditor or administrator role');
    setTimeout(() => {
      window.location.replace('/operator');
    }, 1500);
    return;
  }

  // --- Element References ---------------------------------------------------
  const elClock           = document.getElementById('auditor-clock');
  const elBanner          = document.getElementById('integrity-banner');
  const elStatusText      = document.getElementById('integrity-status-text');
  const elSubText         = document.getElementById('integrity-sub-text');
  const elIconPath        = document.getElementById('integrity-icon-path');
  const elBtnReverify     = document.getElementById('btn-reverify');

  const elTimeline        = document.getElementById('timeline-container');
  const elLedgerCountChip = document.getElementById('ledger-count-chip');

  const elExportForm      = document.getElementById('export65b-form');
  const elExportSeq       = document.getElementById('export-seq');
  const elExportStatus    = document.getElementById('export-status-msg');
  const elBtnPdf          = document.getElementById('btn-generate-pdf');
  const elLogoutBtn       = document.getElementById('auditor-logout-btn');

  let currentRecords = [];

  // --- 2. Clock -------------------------------------------------------------
  function updateClock() {
    if (elClock) {
      const now = new Date();
      elClock.textContent = now.toLocaleTimeString('en-GB', {
        timeZone: 'Asia/Kolkata',
        hour12: false,
      }) + ' IST';
    }
  }
  updateClock();
  setInterval(updateClock, 1000);

  // --- 3. Ledger Integrity Verification -------------------------------------
  async function checkIntegrity() {
    if (!elBanner) return;
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/ledger/verify');
      const data = await res.json();

      if (data.status === 'OK') {
        elBanner.className = 'integrity-banner integrity-banner--ok';
        if (elIconPath) elIconPath.setAttribute('d', 'M13.5 4.5l-7 7L3 8');
        if (elStatusText) elStatusText.textContent = `LEDGER INTEGRITY: VERIFIED — ${data.records} BLOCKS`;
        if (elSubText) elSubText.textContent = 'ALL SHA-256 HASH CHAINS INTACT';
      } else {
        elBanner.className = 'integrity-banner integrity-banner--broken';
        if (elIconPath) elIconPath.setAttribute('d', 'M4 4l8 8M12 4l-8 8');
        if (elStatusText) elStatusText.textContent = 'CHAIN BREAK DETECTED';
        if (elSubText) elSubText.textContent = `BROKEN AT BLOCK #${data.broken_at_seq || '?'}: ${data.detail || 'MISMATCH'}`;
      }
    } catch (err) {
      elBanner.className = 'integrity-banner integrity-banner--broken';
      if (elStatusText) elStatusText.textContent = 'VERIFICATION ERROR';
      if (elSubText) elSubText.textContent = err.message;
    }
  }

  if (elBtnReverify) {
    elBtnReverify.addEventListener('click', async () => {
      if (elStatusText) elStatusText.textContent = 'VERIFYING CHAIN...';
      await checkIntegrity();
      await loadTimeline();
    });
  }

  // --- 4. Vertical Ledger Timeline ------------------------------------------
  async function loadTimeline() {
    if (!elTimeline) return;
    try {
      elTimeline.setAttribute('aria-busy', 'true');
      const res = await window.ibvap_auth.fetchAuthed('/api/events?n=100');
      const records = await res.json();
      currentRecords = Array.isArray(records) ? records : [];

      if (elLedgerCountChip) {
        elLedgerCountChip.textContent = `${currentRecords.length} BLOCKS`;
      }

      renderTimeline(currentRecords);
      populateSeqSelect(currentRecords);
    } catch (err) {
      elTimeline.innerHTML = `<div style="padding:16px; color:var(--crit);">Failed to load ledger: ${escapeHtml(err.message)}</div>`;
    } finally {
      elTimeline.setAttribute('aria-busy', 'false');
    }
  }

  function truncateHash(hash) {
    if (!hash || typeof hash !== 'string') return '000000…0000';
    if (hash.length <= 12) return hash;
    return `${hash.slice(0, 6)}…${hash.slice(-4)}`;
  }

  function formatTs(ts) {
    if (!ts) return '—';
    try {
      const d = new Date(typeof ts === 'number' && ts < 1e11 ? ts * 1000 : ts);
      return d.toLocaleDateString('en-GB') + ' ' + d.toLocaleTimeString('en-GB', { hour12: false }) + ' IST';
    } catch (_) {
      return String(ts);
    }
  }

  function getEventChip(ev) {
    const type = (ev.subtype || ev.type || 'EVENT').toUpperCase();
    if (type.includes('BREACH') || type.includes('CRITICAL') || type.includes('MATCH')) {
      return `<span class="chip chip--crit mono">${escapeHtml(type)}</span>`;
    }
    if (type.includes('AUTH_SUCCESS') || type.includes('SECURE') || type.includes('NOMINAL')) {
      return `<span class="chip chip--ok mono">${escapeHtml(type)}</span>`;
    }
    return `<span class="chip chip--warn mono">${escapeHtml(type)}</span>`;
  }

  function getCamId(rec) {
    const ev = rec.event || {};
    if (ev.cam) {
      // Extract CAM-01, CAM-02, etc.
      const match = ev.cam.match(/CAM-\d+/i);
      return match ? match[0].toUpperCase() : ev.cam;
    }
    return ev.node || 'NODE-BOP7';
  }

  function getSnapshotThumb(rec) {
    const ev = rec.event || {};
    // Only static snapshots or pre-generated thumb placeholders — NO LIVE VIDEO
    if (ev.cam && ev.cam.includes('01')) {
      return `<img src="/snapshots/cam1_live.jpg" alt="Snapshot" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<span class=\\'timeline-block__thumb-placeholder\\'>CAM-01<br/>SNAPPED</span>';"/>`;
    }
    if (ev.cam && ev.cam.includes('05')) {
      return `<img src="/snapshots/cam5_live.jpg" alt="Snapshot" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<span class=\\'timeline-block__thumb-placeholder\\'>CAM-05<br/>SNAPPED</span>';"/>`;
    }
    return `<span class="timeline-block__thumb-placeholder">${escapeHtml(getCamId(rec))}<br/>EVIDENCE</span>`;
  }

  function renderTimeline(records) {
    if (!elTimeline) return;
    if (records.length === 0) {
      elTimeline.innerHTML = '<div style="padding:24px; color:var(--dim); text-align:center;">NO LEDGER RECORDS FOUND</div>';
      return;
    }

    // Newest first for quick inspection
    const reversed = [...records].reverse();

    const itemsHtml = reversed.map((rec, idx) => {
      const ev = rec.event || {};
      const seq = rec.seq || (records.length - idx);
      const timeStr = formatTs(rec.ts || ev.ts);
      const camId = getCamId(rec);
      const chipHtml = getEventChip(ev);
      const thumbHtml = getSnapshotThumb(rec);
      const thisHashTrunc = truncateHash(rec.this_hash);
      const prevHashTrunc = truncateHash(rec.prev_hash);
      const message = ev.message || (ev.type ? `${ev.type} on ${camId}` : 'Chained System Event');

      const blockHtml = `
        <article class="timeline-block" data-seq="${seq}" id="block-seq-${seq}">
          <header class="timeline-block__header">
            <div class="timeline-block__meta">
              <span class="timeline-block__seq">#${seq}</span>
              <span class="timeline-block__time">${timeStr}</span>
              ${chipHtml}
            </div>
            <span class="timeline-block__cam">${escapeHtml(camId)}</span>
          </header>

          <div class="timeline-block__body">
            <div class="timeline-block__thumb">
              ${thumbHtml}
            </div>
            <div class="timeline-block__desc">
              <div style="font-weight:600; margin-bottom: 2px;">${escapeHtml(message)}</div>
              <div style="font-size:11px; color:var(--dim); font-family:var(--font-mono);">
                Target: ${escapeHtml(ev.cls || ev.username || 'System')} &middot; Severity: ${escapeHtml(ev.severity || 'NORMAL')}
              </div>
            </div>
          </div>

          <footer class="timeline-block__footer">
            <div class="timeline-block__hash">
              <span>prev:</span>
              <span class="timeline-block__hash-val">${prevHashTrunc}</span>
              <span style="color:var(--border);">&rarr;</span>
              <span>this:</span>
              <span class="timeline-block__hash-val" style="color:var(--text);">${thisHashTrunc}</span>
            </div>
            <button class="action-btn" data-action="select-seq" data-seq="${seq}" style="font-size:9px; padding:2px 6px;">
              SELECT FOR 65B
            </button>
          </footer>
        </article>
      `;

      // Chain-link icon connector between blocks
      const connectorHtml = (idx < reversed.length - 1) ? `
        <div class="timeline-chain-connector" aria-hidden="true">
          <div class="timeline-chain-line"></div>
          <svg class="timeline-chain-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M7 9a3 3 0 0 1 0-4.2l1.8-1.8a3 3 0 0 1 4.2 4.2L11.5 8.5" />
            <path d="M9 7a3 3 0 0 1 0 4.2l-1.8 1.8a3 3 0 0 1-4.2-4.2L4.5 7.5" />
          </svg>
          <div class="timeline-chain-line"></div>
        </div>
      ` : '';

      return blockHtml + connectorHtml;
    }).join('');

    elTimeline.innerHTML = itemsHtml;
  }

  function populateSeqSelect(records) {
    if (!elExportSeq) return;
    const currentVal = elExportSeq.value;
    let opts = '<option value="">Latest Chained Block (Default)</option>';
    // Newest first in dropdown
    const reversed = [...records].reverse();
    reversed.forEach(r => {
      const ev = r.event || {};
      const desc = ev.message || ev.type || 'Event';
      opts += `<option value="${r.seq}">#${r.seq} &mdash; ${escapeHtml(desc.slice(0, 36))}</option>`;
    });
    elExportSeq.innerHTML = opts;
    if (currentVal) elExportSeq.value = currentVal;
  }

  // Handle clicking "SELECT FOR 65B" or block click
  elTimeline.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-action="select-seq"]');
    const block = e.target.closest('.timeline-block');
    if (btn || block) {
      const seq = (btn && btn.dataset.seq) || (block && block.dataset.seq);
      if (seq && elExportSeq) {
        elExportSeq.value = seq;
        document.querySelectorAll('.timeline-block').forEach(b => b.classList.remove('is-selected'));
        block.classList.add('is-selected');
        if (elExportStatus) {
          elExportStatus.textContent = `Selected Block #${seq} for 65B Certificate`;
          elExportStatus.style.color = 'var(--accent)';
        }
      }
    }
  });

  // --- 5. Export Section 65B Certificate ------------------------------------
  if (elExportForm) {
    elExportForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const seq = elExportSeq.value;
      const caseId = document.getElementById('export-case-id').value.trim();
      const officer = document.getElementById('export-officer').value.trim();
      const fromDate = document.getElementById('export-from').value;
      const toDate = document.getElementById('export-to').value;

      const token = window.ibvap_auth.token();
      if (!token) {
        alert('Authentication required to generate certificates');
        return;
      }

      if (elBtnPdf) {
        elBtnPdf.disabled = true;
        elBtnPdf.textContent = 'GENERATING SIGNED PDF...';
      }
      if (elExportStatus) {
        elExportStatus.textContent = 'Compiling cryptographic ledger chain and reportlab PDF...';
        elExportStatus.style.color = 'var(--accent)';
      }

      try {
        const params = new URLSearchParams();
        if (seq) params.set('seq', seq);
        if (caseId) params.set('case_id', caseId);
        if (officer) params.set('officer_name', officer);
        if (fromDate) params.set('date_from', fromDate);
        if (toDate) params.set('date_to', toDate);
        params.set('token', token);

        const url = `/api/export65b?${params.toString()}`;

        // Fetch the PDF blob
        const res = await window.ibvap_auth.fetchAuthed(url);
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`Server returned ${res.status}: ${errText}`);
        }

        const blob = await res.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `IBVAP_65B_Seq${seq || 'Latest'}_${caseId || 'CERT'}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);

        if (elExportStatus) {
          elExportStatus.textContent = 'CERTIFICATE DOWNLOADED SUCCESSFULLY';
          elExportStatus.style.color = 'var(--ok)';
        }
      } catch (err) {
        console.error('PDF export failed:', err);
        if (elExportStatus) {
          elExportStatus.textContent = 'Export failed: ' + err.message;
          elExportStatus.style.color = 'var(--crit)';
        }
      } finally {
        if (elBtnPdf) {
          elBtnPdf.disabled = false;
          elBtnPdf.textContent = 'GENERATE SIGNED PDF';
        }
      }
    });
  }

  // --- 6. Navigation Tabs ---------------------------------------------------
  const navVault = document.getElementById('nav-vault');
  const navCert = document.getElementById('nav-cert');

  if (navVault) {
    navVault.addEventListener('click', () => {
      navVault.classList.add('is-active');
      navCert?.classList.remove('is-active');
      if (elTimeline) {
        elTimeline.scrollIntoView({ behavior: 'smooth' });
        elTimeline.style.outline = '2px solid var(--ok)';
        setTimeout(() => { elTimeline.style.outline = 'none'; }, 1500);
      }
    });
  }

  if (navCert) {
    navCert.addEventListener('click', () => {
      navCert.classList.add('is-active');
      navVault?.classList.remove('is-active');
      const caseIdInput = document.getElementById('export-case-id');
      if (caseIdInput) {
        caseIdInput.focus();
      }
      if (elExportForm) {
        elExportForm.scrollIntoView({ behavior: 'smooth' });
        elExportForm.style.outline = '2px solid var(--accent)';
        setTimeout(() => { elExportForm.style.outline = 'none'; }, 1500);
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
  checkIntegrity();
  loadTimeline();
  // Poll for new ledger entries every 5 seconds
  setInterval(() => {
    checkIntegrity();
    loadTimeline();
  }, 5000);
})();
