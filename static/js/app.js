/* ============================================================
   StadiumSaathi — Application JavaScript
   Handles all 3 personas: Fan, Volunteer, Command Center.
   ============================================================ */

// ── State ───────────────────────────────────────────────────────────────────
let fanSessionId = null;
let volunteerSessionId = null;
let selectedIncidentType = 'medical';
let commandRefreshTimer = null;

const ZONES = ["Zone A", "Zone B", "Zone C", "Zone D", "Zone E - Family", "Zone VIP"];

const QUICK_ASKS = [
  "Where is my seat?",
  "Nearest accessible restroom?",
  "Is my zone crowded right now?",
  "Where can I get food nearby?",
];

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  populateZoneSelects();
  buildQuickAsks();

  document.getElementById('fan-input')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendFanMessage();
  });

  // Persona selections
  document.getElementById('btn-persona-fan')?.addEventListener('click', () => enterPersona('fan'));
  document.getElementById('btn-persona-volunteer')?.addEventListener('click', () => enterPersona('volunteer'));
  document.getElementById('btn-persona-command')?.addEventListener('click', () => enterPersona('command'));

  // Back buttons
  document.querySelectorAll('.back-btn').forEach(btn => {
    btn.addEventListener('click', goHome);
  });

  // Check In and Action buttons
  document.getElementById('btn-checkin-fan')?.addEventListener('click', startFanSession);
  document.getElementById('btn-send-fan')?.addEventListener('click', () => sendFanMessage());
  document.getElementById('btn-signin-volunteer')?.addEventListener('click', startVolunteerSession);
  document.getElementById('btn-report-incident')?.addEventListener('click', reportIncident);
  document.getElementById('btn-refresh-recs')?.addEventListener('click', refreshRecommendations);

  // Incident type buttons
  document.querySelectorAll('.incident-btn').forEach(btn => {
    btn.addEventListener('click', () => selectIncidentType(btn.dataset.type));
  });
});


function populateZoneSelects() {
  ['fan-zone', 'vol-zone'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    ZONES.forEach(zone => {
      const opt = document.createElement('option');
      opt.value = zone;
      opt.textContent = zone;
      select.appendChild(opt);
    });
  });
}

function buildQuickAsks() {
  const wrap = document.getElementById('fan-quick-asks');
  if (!wrap) return;
  QUICK_ASKS.forEach(q => {
    const btn = document.createElement('button');
    btn.className = 'quick-ask-btn';
    btn.textContent = q;
    btn.addEventListener('click', () => sendFanMessage(q));
    wrap.appendChild(btn);
  });
}

// ── Navigation ────────────────────────────────────────────────────────────────
function enterPersona(persona) {
  document.getElementById('landing').style.display = 'none';
  document.getElementById(`${persona}-view`).style.display = 'block';

  if (persona === 'command') {
    initCommandCenter();
  }
}

function goHome() {
  document.querySelectorAll('.persona-view').forEach(v => v.style.display = 'none');
  document.getElementById('landing').style.display = 'flex';
  if (commandRefreshTimer) {
    clearInterval(commandRefreshTimer);
    commandRefreshTimer = null;
  }
}

// ══════════════════════════════════════════════════════════════════════════
// FAN PERSONA
// ══════════════════════════════════════════════════════════════════════════

async function startFanSession() {
  const name = document.getElementById('fan-name').value.trim();
  if (!name) {
    document.getElementById('fan-name').focus();
    return;
  }
  const seatZone = document.getElementById('fan-zone').value;
  const language = document.getElementById('fan-lang').value;

  const res = await postJSON('/api/fan/session', { name, seat_zone: seatZone, language });
  fanSessionId = res.session_id;

  document.getElementById('fan-setup').style.display = 'none';
  document.getElementById('fan-chat').style.display = 'block';
  document.getElementById('fan-zone-banner').textContent =
    `Checked in — ${name}, seated in ${seatZone}. Ask Saathi anything about the stadium.`;

  addFanMessage('saathi', `Welcome, ${escapeHtml(name)}! I'm Saathi, your match-day assistant. Ask me about directions, facilities, or crowd conditions.`);
}

async function sendFanMessage(preset) {
  const input = document.getElementById('fan-input');
  const message = preset || input.value.trim();
  if (!message) return;

  input.value = '';
  addFanMessage('fan', message);

  const res = await postJSON('/api/fan/ask', { session_id: fanSessionId, message });
  addFanMessage('saathi', res.response);

  if (res.crowd_warning) {
    addFanWarning(res.crowd_warning);
  }
}

function addFanMessage(sender, text) {
  const container = document.getElementById('fan-messages');
  const div = document.createElement('div');
  div.className = `msg msg-${sender}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addFanWarning(text) {
  const container = document.getElementById('fan-messages');
  const div = document.createElement('div');
  div.className = 'msg-warning';
  div.textContent = `⚠️ ${text}`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ══════════════════════════════════════════════════════════════════════════
// VOLUNTEER PERSONA
// ══════════════════════════════════════════════════════════════════════════

async function startVolunteerSession() {
  const name = document.getElementById('vol-name').value.trim();
  if (!name) {
    document.getElementById('vol-name').focus();
    return;
  }
  const role = document.getElementById('vol-role').value;
  const zone = document.getElementById('vol-zone').value;

  const res = await postJSON('/api/volunteer/session', { name, role, zone });
  volunteerSessionId = res.session_id;

  document.getElementById('volunteer-setup').style.display = 'none';
  document.getElementById('volunteer-console').style.display = 'block';
}

function selectIncidentType(type) {
  selectedIncidentType = type;
  document.querySelectorAll('.incident-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.incident-btn[data-type="${type}"]`)?.classList.add('active');
}

async function reportIncident() {
  const description = document.getElementById('incident-desc').value.trim();
  const resultBox = document.getElementById('triage-result');
  resultBox.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Getting AI guidance...</p>';

  const res = await postJSON('/api/volunteer/incident', {
    session_id: volunteerSessionId,
    incident_type: selectedIncidentType,
    description,
  });

  const incident = res.incident;
  resultBox.innerHTML = `
    <div class="triage-card">
      <div class="triage-id">${escapeHtml(incident.incident_id)} · ${escapeHtml(incident.zone)}</div>
      ${escapeHtml(incident.guidance)}
    </div>
  `;
  document.getElementById('incident-desc').value = '';
}

// ══════════════════════════════════════════════════════════════════════════
// COMMAND CENTER PERSONA
// ══════════════════════════════════════════════════════════════════════════

async function initCommandCenter() {
  await refreshHeatmap();
  await refreshRecommendations();
  await refreshIncidentLog();

  commandRefreshTimer = setInterval(async () => {
    await refreshHeatmap();
    await refreshIncidentLog();
  }, 10000);
}

async function refreshHeatmap() {
  const res = await fetch('/api/stadium_state').then(r => r.json());
  const container = document.getElementById('zone-heatmap');
  container.innerHTML = '';

  res.zones.forEach(zone => {
    const pct = Math.round(zone.density * 100);
    const row = document.createElement('div');
    row.className = 'zone-row';
    row.setAttribute('role', 'listitem');
    row.innerHTML = `
      <div class="zone-label">${escapeHtml(zone.name)}</div>
      <div class="zone-bar-track">
        <div class="zone-bar-fill ${zone.status}" style="width:${pct}%"></div>
      </div>
      <div class="zone-pct">${pct}%</div>
    `;
    container.appendChild(row);
  });
}

async function refreshRecommendations() {
  const container = document.getElementById('ai-recommendations');
  container.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">Analysing live conditions...</p>';

  const res = await fetch('/api/command/recommendations').then(r => r.json());
  container.innerHTML = '';

  res.recommendations.forEach(rec => {
    const card = document.createElement('div');
    card.className = 'rec-card';
    card.textContent = rec;
    container.appendChild(card);
  });
}

async function refreshIncidentLog() {
  const res = await fetch('/api/command/incidents').then(r => r.json());
  const container = document.getElementById('incident-log');
  container.innerHTML = '';

  if (res.incidents.length === 0) {
    container.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">No incidents reported yet.</p>';
    return;
  }

  res.incidents.slice(0, 10).forEach(inc => {
    const row = document.createElement('div');
    row.className = 'incident-row';
    row.setAttribute('role', 'listitem');
    row.innerHTML = `
      <div class="i-top">
        <span class="i-id">${escapeHtml(inc.incident_id)} · ${escapeHtml(inc.incident_type)}</span>
        <span class="i-zone">${escapeHtml(inc.zone)}</span>
      </div>
      <div class="i-guidance">${escapeHtml(inc.guidance)}</div>
    `;
    container.appendChild(row);
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
