/* ==========================================================================
   operator.js — IBVAP BOP-7 Operator Console controller.

   Responsibilities:
     1. Auth guard (redirect to /login if no token)
     2. Render 6-tile grid (5 cameras + 1 STANDBY) with MJPEG <img> src
     3. Poll /api/state every 2s → draw bounding boxes on canvas overlays
     4. Poll /api/events every 2s → render right-side live event feed
     5. Update IST clock every 1s, uptime every 1s, stat chips every 2s
     6. Bottom ticker: latest critical alerts, scroll horizontally
     7. Per-tile hover controls: DRAW ZONE / SNAPSHOT / FULLSCREEN
     8. Zone draw mode: click to add points → POST /api/zones
     9. ACK button per event row → POST /api/alerts/ack
    10. Role-based UI: auditor sees controls but cannot ACK / draw zone
   ========================================================================== */

(function () {
  'use strict';

  // --- Auth guard ----------------------------------------------------------
  if (!window.ibvap_auth.ensureAuthed()) return;
  const TOKEN = window.ibvap_auth.token();
  const USER  = window.ibvap_auth.user();
  const ROLE  = USER ? USER.role : '';
  const CAN_ACK  = (ROLE === 'admin' || ROLE === 'operator');
  const CAN_ZONE = (ROLE === 'admin' || ROLE === 'operator');

  // --- 6 tiles: 5 cameras + 1 standby ------------------------------------
  // `streamId` is the URL param that hits /api/stream/{cam_id}; null = standby.
  const TILES = [
    { camId: 'CAM-01', camName: 'CAM-01 (People)',            label: 'CAM-01 — GATE'        },
    { camId: 'CAM-02', camName: 'CAM-02 (Vehicles & ANPR)',   label: 'CAM-02 — PERIMETER'   },
    { camId: 'CAM-03', camName: 'CAM-03 (Night CCTV)',        label: 'CAM-03 — NORTH WALL'  },
    { camId: 'CAM-04', camName: 'CAM-04 (Thermal FLIR)',      label: 'CAM-04 — ROOFTOP'    },
    { camId: 'CAM-05', camName: 'CAM-05 (Face Recognition)',  label: 'CAM-05 — ENTRY'       },
    { camId: 'GRID',   camName: 'Tactical Grid',               label: 'TACTICAL C2 MASTER HUD' },
  ];

  // --- Element refs -------------------------------------------------------
  const elGrid        = document.getElementById('op-grid');
  const elMasterSection = document.getElementById('op-master-stream');
  const elMasterImg   = document.getElementById('master-stream-img');
  const elBtnTiles    = document.getElementById('btn-mode-tiles');
  const elBtnMaster   = document.getElementById('btn-mode-master');
  const elEventFeed  = document.getElementById('event-feed');
  const elFeedCount   = document.getElementById('feed-count');
  const elStatStreams  = document.getElementById('stat-streams');
  const elStatAlerts   = document.getElementById('stat-alerts');
  const elStatFiltered = document.getElementById('stat-filtered');
  const elStatUptime   = document.getElementById('stat-uptime');
  const elClock        = document.getElementById('ist-clock');
  const elStatusChip   = document.getElementById('op-status-chip');
  const elStatusText   = document.getElementById('op-status-text');
  const elTickerTrack  = document.getElementById('ticker-track');
  const elZoneHint     = document.getElementById('zone-hint');
  const elZoneHintCount = document.getElementById('zone-hint-count');

  // --- State -------------------------------------------------------------
  let latestState = {};          // last /api/state payload
  let latestEvents = [];         // last /api/events payload
  let ackedSeqs = new Set();     // acked alert seqs (client-side)
  let zonesByCam = {};           // zones from /api/zones, keyed by cam name
  const tileElementsByCam = {};  // cam name → tile DOM element
  const PAGE_LOAD_TS = Date.now();

  // --- Render the 6-tile grid --------------------------------------------
  function renderTiles() {
    elGrid.innerHTML = '';
    TILES.forEach((t, idx) => {
      const tile = document.createElement('div');
      tile.className = 'tile';
      tile.dataset.camId  = t.camId || '';
      tile.dataset.camName = t.camName || '';
      tile.dataset.idx = String(idx);
      tile.dataset.streamId = t.camId || '';

      const isGridTile = (t.camId === 'GRID');
      tile.innerHTML = `
        <div class="tile__label">
          <span class="tile__name">
            <span class="dot dot--ok"></span>
            <span>${t.label}</span>
          </span>
          <span class="tile__chips">
            <span class="tile__chip tile__chip--live">LIVE</span>
          </span>
        </div>
        <div class="tile__frame">
          <img class="tile__img" alt="${t.label}" src="" />
          <canvas class="tile__overlay"></canvas>
          <canvas class="tile__zone-canvas"></canvas>
          <div class="tile__controls">
            ${isGridTile ? '' : '<button class="tile__ctrl tile__ctrl--zone" data-action="zone">DRAW ZONE</button>'}
            <button class="tile__ctrl tile__ctrl--snap" data-action="snap">SNAPSHOT</button>
            <button class="tile__ctrl" data-action="fs">FULLSCREEN</button>
          </div>
        </div>
      `;
      tileElementsByCam[t.camName] = tile;

      const img = tile.querySelector('.tile__img');
      if (img) {
        if (isGridTile) {
          img.src = `/api/stream/GRID?token=${encodeURIComponent(TOKEN)}`;
          img.onerror = () => {
            setTimeout(() => {
              const currentTok = window.ibvap_auth.token() || TOKEN;
              if (currentTok) {
                img.src = `/api/stream/GRID?token=${encodeURIComponent(currentTok)}&_retry=${Date.now()}`;
              }
            }, 1500);
          };
        } else {
          // Fast non-blocking snapshot loop: releases TCP socket immediately after each frame
          tile._running = true;
          const refreshSnapshot = () => {
            if (!tile._running) return;
            const temp = new Image();
            const curTok = window.ibvap_auth.token() || TOKEN;
            temp.onload = () => {
              img.src = temp.src;
              if (tile._running) setTimeout(refreshSnapshot, 250);
            };
            temp.onerror = () => {
              if (tile._running) setTimeout(refreshSnapshot, 1500);
            };
            temp.src = `/api/snapshot/${t.camId}?token=${encodeURIComponent(curTok)}&_t=${Date.now()}`;
          };
          refreshSnapshot();
        }
      }

      // Wire up the canvas to the cam's native resolution (set on first draw)
      const overlay = tile.querySelector('.tile__overlay');
      const zoneCv = tile.querySelector('.tile__zone-canvas');
      overlay._nativeW = isGridTile ? 1440 : 640;
      overlay._nativeH = isGridTile ? 720 : 360;
      zoneCv._nativeW = overlay._nativeW;
      zoneCv._nativeH = overlay._nativeH;

      // Hover control handlers
      const zoneBtn = tile.querySelector('[data-action="zone"]');
      if (zoneBtn) {
        zoneBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (!CAN_ZONE) {
            window.ibvap_auth.showAccessDenied('zone draw requires operator/admin role');
            return;
          }
          enterZoneMode(tile);
        });
      }
      tile.querySelector('[data-action="snap"]').addEventListener('click', (e) => {
        e.stopPropagation();
        const a = document.createElement('a');
        a.href = `/api/snapshot/${t.camId}?token=${encodeURIComponent(TOKEN)}`;
        a.download = `${t.camId}_${Date.now()}.jpg`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      });
      tile.querySelector('[data-action="fs"]').addEventListener('click', (e) => {
        e.stopPropagation();
        const frame = tile.querySelector('.tile__frame');
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else if (frame.requestFullscreen) {
          frame.requestFullscreen();
        }
      });

      elGrid.appendChild(tile);
    });
  }

  // --- View mode switching (Camera Tiles vs Master C2 Stream) ---
  function setViewMode(mode) {
    if (mode === 'master') {
      elGrid.style.display = 'none';
      if (elMasterSection) elMasterSection.classList.add('is-visible');
      if (elBtnMaster) elBtnMaster.classList.add('is-active');
      if (elBtnTiles) elBtnTiles.classList.remove('is-active');
      if (elMasterImg) {
        const curTok = window.ibvap_auth.token() || TOKEN;
        elMasterImg.src = `/api/stream/GRID?token=${encodeURIComponent(curTok)}`;
        elMasterImg.onerror = () => {
          setTimeout(() => {
            const reTok = window.ibvap_auth.token() || TOKEN;
            if (reTok) elMasterImg.src = `/api/stream/GRID?token=${encodeURIComponent(reTok)}&_retry=${Date.now()}`;
          }, 1500);
        };
      }
    } else {
      elGrid.style.display = 'grid';
      if (elMasterSection) elMasterSection.classList.remove('is-visible');
      if (elBtnTiles) elBtnTiles.classList.add('is-active');
      if (elBtnMaster) elBtnMaster.classList.remove('is-active');
      if (elMasterImg) {
        elMasterImg.src = '';
      }
    }
  }

  if (elBtnTiles && elBtnMaster) {
    elBtnTiles.addEventListener('click', () => setViewMode('tiles'));
    elBtnMaster.addEventListener('click', () => setViewMode('master'));
  }

  // --- Bounding-box overlay drawing -------------------------------------
  function drawOverlay(tile, camState) {
    const canvas = tile.querySelector('.tile__overlay');
    if (!canvas || !camState) return;
    const ctx = canvas.getContext('2d');

    // Determine native resolution from motion boxes (best heuristic).
    // Fallback to 640x360.
    let maxW = 0, maxH = 0;
    const motions = camState.motion || [];
    for (const m of motions) {
      if (m[2] > maxW) maxW = m[2];
      if (m[3] > maxH) maxH = m[3];
    }
    const tracks = camState.tracks || [];
    for (const t of tracks) {
      if (t.box[2] > maxW) maxW = t.box[2];
      if (t.box[3] > maxH) maxH = t.box[3];
    }
    if (maxW > 0 && maxH > 0) {
      // round up to a sane boundary
      canvas._nativeW = Math.ceil(maxW);
      canvas._nativeH = Math.ceil(maxH);
    }
    if (canvas.width !== canvas._nativeW) canvas.width = canvas._nativeW;
    if (canvas.height !== canvas._nativeH) canvas.height = canvas._nativeH;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 1. Motion boxes (subtle, amber)
    ctx.strokeStyle = 'rgba(201,138,43,0.35)';
    ctx.lineWidth = 1;
    for (const m of motions) {
      ctx.strokeRect(m[0], m[1], m[2] - m[0], m[3] - m[1]);
    }

    // 2. Persisted zone polygons (dashed red)
    const zones = zonesByCam[tile.dataset.camName] || [];
    if (zones.length) {
      ctx.strokeStyle = 'rgba(201,58,58,0.55)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      for (const z of zones) {
        const pts = z.pts || [];
        if (pts.length < 2) continue;
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.closePath();
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // 3. Track bounding boxes (accent blue)
    for (const t of tracks) {
      const [x1, y1, x2, y2] = t.box;
      ctx.strokeStyle = '#2E7DD1';
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      // Label
      const label = `#${t.tid} ${t.cls} ${Math.round((t.conf || 0) * 100)}%`;
      ctx.font = '11px "JetBrains Mono", monospace';
      const tw = ctx.measureText(label).width + 8;
      ctx.fillStyle = 'rgba(46,125,209,0.92)';
      ctx.fillRect(x1, Math.max(0, y1 - 14), tw, 14);
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(label, x1 + 4, Math.max(10, y1 - 3));
    }

    // 4. Faces (red border, BOLO label)
    const faces = camState.faces || [];
    for (const f of faces) {
      const [x, y, w, h] = f.box;
      ctx.strokeStyle = '#C93A3A';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      if (f.bolo) {
        // BOLO tag above the box
        ctx.fillStyle = '#C93A3A';
        ctx.fillRect(x, Math.max(0, y - 16), 50, 16);
        ctx.fillStyle = '#FFFFFF';
        ctx.font = 'bold 10px "JetBrains Mono", monospace';
        ctx.fillText('BOLO', x + 6, Math.max(11, y - 4));
      }
    }

    // 5. Plates (blue tag, mono text)
    const plates = camState.plates || [];
    for (const p of plates) {
      if (p.box) {
        const [x, y, w, h] = p.box;
        ctx.strokeStyle = '#2E7DD1';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, w, h);
      }
      if (p.text) {
        // Find a free spot — top-right of canvas
        const text = p.text;
        ctx.font = 'bold 12px "JetBrains Mono", monospace';
        const tw = ctx.measureText(text).width + 10;
        ctx.fillStyle = 'rgba(46,125,209,0.92)';
        ctx.fillRect(canvas.width - tw - 4, 4, tw, 18);
        ctx.fillStyle = '#FFFFFF';
        ctx.fillText(text, canvas.width - tw + 1, 17);
      }
    }
  }

  // --- Stat chips -------------------------------------------------------
  function updateStats() {
    const cams = Object.keys(latestState);
    const total = cams.length;
    const alive = cams.filter(c => latestState[c] && latestState[c].fps > 0).length;
    elStatStreams.textContent = `${alive}/${total}`;

    // Active alerts: count zone_events + bolo faces + tampered cams in latest state
    let activeAlerts = 0;
    for (const c of cams) {
      const s = latestState[c];
      activeAlerts += (s.zone_events || []).length;
      activeAlerts += (s.faces || []).filter(f => f.bolo).length;
      if (s.tamper && s.tamper.tampered) activeAlerts++;
    }
    elStatAlerts.textContent = String(activeAlerts);
    elStatAlerts.classList.toggle('is-crit', activeAlerts > 0);

    // Filtered today: count ALERT events in the ledger with today's date
    const todayStr = new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD
    const filteredToday = latestEvents.filter(r => {
      if (!r.event || r.event.type !== 'ALERT') return false;
      const d = new Date((r.ts || 0) * 1000);
      return d.toLocaleDateString('en-CA') === todayStr;
    }).length;
    elStatFiltered.textContent = String(filteredToday);

    // Uptime
    const elapsed = Math.floor((Date.now() - PAGE_LOAD_TS) / 1000);
    const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
    const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    elStatUptime.textContent = `${h}:${m}:${s}`;

    // Status chip
    const critCams = cams.filter(c => latestState[c] && latestState[c].threat_level === 'CRITICAL');
    if (critCams.length > 0) {
      elStatusChip.className = 'op-status-chip is-crit';
      elStatusText.textContent = `${critCams.length} CAM${critCams.length>1?'S':''} CRITICAL`;
    } else if (activeAlerts > 0) {
      elStatusChip.className = 'op-status-chip is-warn';
      elStatusText.textContent = 'ELEVATED';
    } else {
      elStatusChip.className = 'op-status-chip';
      elStatusText.textContent = 'SYSTEM NOMINAL';
    }
  }

  // --- IST clock --------------------------------------------------------
  function updateClock() {
    const now = new Date();
    // Convert to IST (UTC+5:30) regardless of viewer timezone
    const utcMs = now.getTime() + now.getTimezoneOffset() * 60000;
    const ist = new Date(utcMs + 5.5 * 3600000);
    const h = String(ist.getHours()).padStart(2, '0');
    const m = String(ist.getMinutes()).padStart(2, '0');
    const s = String(ist.getSeconds()).padStart(2, '0');
    elClock.textContent = `${h}:${m}:${s} IST`;
  }

  // --- Event feed -------------------------------------------------------
  function severityChipClass(event) {
    const sub = event.subtype || event.type || '';
    if (sub === 'PERIMETER_BREACH') return 'event-row__chip--breach';
    if (sub === 'VEHICLE')          return 'event-row__chip--vehicle';
    if (sub === 'FACE_MATCH')       return 'event-row__chip--face';
    if (sub === 'TAMPER')           return 'event-row__chip--tamper';
    if (sub === 'AUTH_SUCCESS')     return 'event-row__chip--auth';
    if (sub === 'AUTH_FAILURE')     return 'event-row__chip--tamper';
    if (sub === 'ALERT_ACK')        return 'event-row__chip--ack';
    if (sub === 'ZONES_UPDATED')    return 'event-row__chip--zones';
    return '';
  }

  function severityLabel(event) {
    const sub = event.subtype || '';
    if (sub) return sub.replace(/_/g, ' ');
    return (event.type || 'EVENT').replace(/_/g, ' ');
  }

  function formatTs(ts) {
    if (!ts) return '--:--:--';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-GB', { hour12: false });
  }

  function renderEventFeed() {
    // Show newest last; we want newest at top.
    const rows = [...latestEvents].reverse();
    if (rows.length === 0) {
      elEventFeed.innerHTML = `<div class="event-row--empty">NO EVENTS YET</div>`;
      elFeedCount.textContent = '0';
      return;
    }
    elFeedCount.textContent = String(rows.length);

    // Only render ALERT + ALERT_ACK + ZONES_UPDATED + AUTH events (skip genesis/test)
    const visible = rows.filter(r => {
      const t = r.event && r.event.type;
      return t && ['ALERT', 'ALERT_ACK', 'ZONES_UPDATED', 'AUTH_SUCCESS', 'AUTH_FAILURE'].includes(t);
    });

    if (visible.length === 0) {
      elEventFeed.innerHTML = `<div class="event-row--empty">NO ALERTS YET</div>`;
      return;
    }

    const html = visible.map(r => {
      const ev = r.event || {};
      const isCrit = ev.severity === 'CRITICAL' || ev.subtype === 'PERIMETER_BREACH' || ev.subtype === 'FACE_MATCH' || ev.subtype === 'TAMPER';
      const isAcked = ackedSeqs.has(r.seq) || ev.type === 'ALERT_ACK';
      const chipCls = severityChipClass(ev);
      const cam = ev.cam || '';
      const msg = ev.message || ev.subtype || ev.type || '';
      const ackDisabled = !CAN_ACK || isAcked || ev.type === 'ALERT_ACK' || ev.type === 'AUTH_SUCCESS' || ev.type === 'AUTH_FAILURE' || ev.type === 'ZONES_UPDATED';
      const ackLabel = isAcked ? 'ACKED' : 'ACK';
      return `
        <div class="event-row ${isCrit ? 'is-crit' : ''} ${isAcked ? 'is-acked' : ''}" data-seq="${r.seq}">
          <span class="event-row__ts">${formatTs(r.ts)}</span>
          <span class="event-row__chip ${chipCls}">${severityLabel(ev)}</span>
          <span class="event-row__msg"><span class="cam">${cam}</span>${msg}</span>
          <button class="event-row__ack" ${ackDisabled ? 'disabled' : ''} data-seq="${r.seq}" data-cam="${cam}">${ackLabel}</button>
        </div>
      `;
    }).join('');
    elEventFeed.innerHTML = html;

    // Wire up ACK buttons
    elEventFeed.querySelectorAll('.event-row__ack:not([disabled])').forEach(btn => {
      btn.addEventListener('click', async () => {
        const seq = parseInt(btn.dataset.seq, 10);
        const cam = btn.dataset.cam;
        btn.disabled = true;
        btn.textContent = 'ACKING...';
        try {
          await window.ibvap_auth.fetchAuthed('/api/alerts/ack', {
            method: 'POST',
            body: { seq, cam },
          });
          ackedSeqs.add(seq);
          btn.textContent = 'ACKED';
          btn.disabled = true;
          btn.closest('.event-row').classList.add('is-acked');
        } catch (e) {
          btn.disabled = false;
          btn.textContent = 'ACK';
          // Access-denied bar already shown by fetchAuthed.
        }
      });
    });
  }

  // --- Bottom ticker ---------------------------------------------------
  function updateTicker() {
    const critical = latestEvents.filter(r => {
      const ev = r.event || {};
      return ev.type === 'ALERT' && (ev.severity === 'CRITICAL' || ev.subtype === 'PERIMETER_BREACH' || ev.subtype === 'FACE_MATCH' || ev.subtype === 'TAMPER');
    }).reverse().slice(0, 12);

    if (critical.length === 0) {
      elTickerTrack.innerHTML = `<span class="op-ticker__item op-ticker__item--empty">NO CRITICAL ALERTS</span>`;
      return;
    }

    const items = critical.map(r => {
      const ev = r.event || {};
      return `<span class="op-ticker__item">
        <span class="seq">#${r.seq}</span>
        <span class="ts">${formatTs(r.ts)}</span>
        <span class="msg">${ev.message || ev.subtype || 'ALERT'}</span>
        <span class="sep">/</span>
      </span>`;
    }).join('');
    // Duplicate for seamless loop
    elTickerTrack.innerHTML = items + items;
  }

  // --- Pollers ---------------------------------------------------------
  async function pollState() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/state');
      latestState = await res.json();
      // Draw overlays for each camera tile
      for (const camName of Object.keys(latestState)) {
        const tile = tileElementsByCam[camName];
        if (tile) {
          drawOverlay(tile, latestState[camName]);
          // Update tile chip (LIVE / NIGHT / CRIT)
          const chipHost = tile.querySelector('.tile__chips');
          const s = latestState[camName];
          if (chipHost) {
            let chips = `<span class="tile__chip tile__chip--live">LIVE</span>`;
            if (s.night) chips += `<span class="tile__chip tile__chip--night">NIGHT</span>`;
            if (s.threat_level === 'CRITICAL') chips += `<span class="tile__chip tile__chip--crit">CRIT</span>`;
            if (s.tamper && s.tamper.tampered) chips += `<span class="tile__chip tile__chip--crit">TAMP</span>`;
            chipHost.innerHTML = chips;
          }
          // Highlight critical tiles
          if (s.threat_level === 'CRITICAL') tile.classList.add('is-crit');
          else tile.classList.remove('is-crit');
        }
      }
    } catch (e) {
      // fetchAuthed already handles 401/403 globally; just log others.
      if (!String(e.message).includes('forbidden') && !String(e.message).includes('unauthorized')) {
        console.warn('[ibvap] state poll failed:', e);
      }
    }
  }

  async function pollEvents() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/events?n=50');
      latestEvents = await res.json();
      // Also fetch acked set
      try {
        const ackedRes = await window.ibvap_auth.fetchAuthed('/api/alerts/acked');
        const ackedData = await ackedRes.json();
        if (Array.isArray(ackedData.acked)) {
          ackedData.acked.forEach(s => ackedSeqs.add(s));
        }
      } catch (_) { /* ignore */ }
      renderEventFeed();
      updateTicker();
    } catch (e) {
      if (!String(e.message).includes('forbidden') && !String(e.message).includes('unauthorized')) {
        console.warn('[ibvap] events poll failed:', e);
      }
    }
  }

  async function pollZones() {
    try {
      const res = await window.ibvap_auth.fetchAuthed('/api/zones');
      zonesByCam = await res.json();
    } catch (e) {
      // ignore — overlays will just skip zones
    }
  }

  // --- Zone draw mode --------------------------------------------------
  let zoneMode = false;
  let zoneTile = null;
  let zonePoints = [];

  function enterZoneMode(tile) {
    if (zoneMode) exitZoneMode(true);
    zoneMode = true;
    zoneTile = tile;
    zonePoints = [];
    tile.classList.add('is-zone-mode');
    elZoneHint.hidden = false;
    elZoneHintCount.textContent = '0 PTS';
    // Wire up the zone canvas
    const zc = tile.querySelector('.tile__zone-canvas');
    // Match the overlay's native dims
    const overlay = tile.querySelector('.tile__overlay');
    zc.width = overlay.width || 640;
    zc.height = overlay.height || 360;
    zc._nativeW = zc.width;
    zc._nativeH = zc.height;
    drawZoneInProgress();
  }

  function exitZoneMode(cancelled) {
    if (zoneTile) zoneTile.classList.remove('is-zone-mode');
    zoneMode = false;
    zoneTile = null;
    zonePoints = [];
    elZoneHint.hidden = true;
    if (cancelled) {
      // clear the canvas
    }
  }

  function drawZoneInProgress() {
    if (!zoneTile) return;
    const zc = zoneTile.querySelector('.tile__zone-canvas');
    const ctx = zc.getContext('2d');
    ctx.clearRect(0, 0, zc.width, zc.height);
    if (zonePoints.length === 0) return;
    ctx.strokeStyle = '#2E7DD1';
    ctx.lineWidth = 2;
    ctx.fillStyle = 'rgba(46,125,209,0.18)';
    ctx.beginPath();
    ctx.moveTo(zonePoints[0][0], zonePoints[0][1]);
    for (let i = 1; i < zonePoints.length; i++) ctx.lineTo(zonePoints[i][0], zonePoints[i][1]);
    if (zonePoints.length >= 3) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
    // Points
    ctx.fillStyle = '#2E7DD1';
    for (const p of zonePoints) {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 3, 0, Math.PI * 2);
      ctx.fill();
    }
    elZoneHintCount.textContent = `${zonePoints.length} PTS`;
  }

  async function finishZone() {
    if (!zoneTile || zonePoints.length < 3) {
      exitZoneMode(true);
      return;
    }
    const camName = zoneTile.dataset.camName;
    const camId = zoneTile.dataset.camId;
    const newZone = {
      zone_id: `Z-${camId}-${Date.now()}`,
      zone_name: `Operator Drawn ${new Date().toISOString().slice(11,19)}`,
      zone_type: 'EXCLUSION_ZONE',
      pts: zonePoints,
    };
    // Build full payload (POST replaces entire zones.json)
    const updated = { ...zonesByCam };
    if (!Array.isArray(updated[camName])) updated[camName] = [];
    updated[camName] = [...updated[camName], newZone];

    try {
      await window.ibvap_auth.fetchAuthed('/api/zones', {
        method: 'POST',
        body: updated,
      });
      zonesByCam = updated;
      exitZoneMode(false);
    } catch (e) {
      // Access denied or network — abort zone mode.
      exitZoneMode(true);
    }
  }

  // Delegate click events on zone canvases
  document.addEventListener('click', (e) => {
    if (!zoneMode || !zoneTile) return;
    const zc = zoneTile.querySelector('.tile__zone-canvas');
    if (e.target !== zc) return;
    const rect = zc.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * zc._nativeW;
    const y = ((e.clientY - rect.top) / rect.height) * zc._nativeH;
    zonePoints.push([Math.round(x), Math.round(y)]);
    drawZoneInProgress();
  });
  document.addEventListener('dblclick', (e) => {
    if (!zoneMode || !zoneTile) return;
    finishZone();
  });
  document.addEventListener('keydown', (e) => {
    if (!zoneMode) return;
    if (e.key === 'Escape') exitZoneMode(true);
    else if (e.key === 'Enter') finishZone();
  });

  // --- Rail buttons ---------------------------------------------------
  const btnRailGrid = document.getElementById('rail-grid');
  const btnRailZones = document.getElementById('rail-zones');
  const btnRailEvents = document.getElementById('rail-events');
  const btnRailSettings = document.getElementById('rail-settings');

  if (btnRailGrid) {
    btnRailGrid.addEventListener('click', () => {
      document.querySelectorAll('.rail-btn').forEach(b => b.classList.remove('is-active'));
      btnRailGrid.classList.add('is-active');
      setViewMode('tiles');
    });
  }

  if (btnRailZones) {
    btnRailZones.addEventListener('click', () => {
      if (!CAN_ZONE) {
        window.ibvap_auth.showAccessDenied('zone draw requires operator/admin role');
        return;
      }
      const firstTile = elGrid.querySelector('.tile');
      if (firstTile) {
        enterZoneMode(firstTile);
      }
    });
  }

  if (btnRailEvents) {
    btnRailEvents.addEventListener('click', () => {
      if (elEventFeed) {
        elEventFeed.scrollIntoView({ behavior: 'smooth' });
        elEventFeed.style.outline = '1px solid var(--accent)';
        setTimeout(() => { elEventFeed.style.outline = 'none'; }, 1500);
      }
    });
  }

  if (btnRailSettings) {
    btnRailSettings.addEventListener('click', () => {
      // Toggle between Master C2 Stream and Multi-Camera Tiles
      const isMaster = elMasterSection && elMasterSection.classList.contains('is-visible');
      setViewMode(isMaster ? 'tiles' : 'master');
    });
  }

  document.getElementById('rail-logout').addEventListener('click', () => {
    window.ibvap_auth.logout('logout');
  });
  document.getElementById('rail-export').addEventListener('click', async () => {
    // Open Section 65B export in a new tab using token query param
    window.open(`/api/export65b?token=${encodeURIComponent(TOKEN)}`, '_blank');
  });

  // --- Init -----------------------------------------------------------
  renderTiles();
  updateClock();
  setInterval(updateClock, 1000);
  updateStats();
  setInterval(updateStats, 1000);  // uptime ticks every second
  pollZones();
  pollState();
  setInterval(pollState, 2000);
  pollEvents();
  setInterval(pollEvents, 2000);

  console.log('[ibvap] operator console ready — role=' + ROLE);
})();
