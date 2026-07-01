// SSE Client for Sentry-Swarm Mobile Responder
let eventSource = null;
const connectionBadge = document.getElementById('connection-status');
const connectionText = document.getElementById('connection-text');
const incidentsContainer = document.getElementById('incidents');
const resolvedList = document.getElementById('resolved-list');

// Track currently active incident IDs to animate transitions
let activeIds = new Set();

function connect() {
  if (eventSource) {
    eventSource.close();
  }

  // Connect to the SSE endpoint
  eventSource = new EventSource('/events');

  connectionBadge.className = 'status-badge';
  connectionText.textContent = 'Connecting...';

  eventSource.onopen = () => {
    connectionBadge.className = 'status-badge connected';
    connectionText.textContent = 'Live Streaming';
    console.log('SSE connection established');
  };

  eventSource.onerror = (err) => {
    connectionBadge.className = 'status-badge';
    connectionText.textContent = 'Disconnected';
    console.error('SSE connection error, retrying...', err);
    // Retry connection after 5 seconds
    setTimeout(connect, 5000);
  };

  eventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      console.log('Received update payload:', payload);

      if (payload.active) {
        renderActiveIncidents(payload.active);
      }
      if (payload.resolved) {
        renderResolvedIncidents(payload.resolved);
      }
    } catch (e) {
      console.error('Error parsing event data:', e);
    }
  };
}

function renderActiveIncidents(activeIncidents) {
  if (activeIncidents.length === 0) {
    incidentsContainer.innerHTML = `
      <div class="card empty-state">
        <div class="empty-icon">🛡️</div>
        <p>No active incidents. System is fully operational.</p>
      </div>
    `;
    activeIds.clear();
    return;
  }

  // Clear container
  incidentsContainer.innerHTML = '';

  activeIncidents.forEach((inc) => {
    activeIds.add(inc.incident_id);

    // Map status/step to index for the progress bar
    // Steps: Sentry (always done to get here), Diagnostician, Fix-Planner, Comms
    const steps = ['sentry', 'diagnostician', 'fix_planner', 'comms'];
    let currentStepIndex = 1; // Default to Diagnostician running

    if (inc.status === 'diagnosed') {
      currentStepIndex = 2; // Diagnostician done, Fix-Planner running
    } else if (inc.status === 'fix_planned') {
      currentStepIndex = 3; // Fix-Planner done, Comms running
    } else if (inc.status === 'resolved' || inc.status === 'error' || inc.status === 'timeout') {
      currentStepIndex = 4; // All done
    }

    const progressPercent = (currentStepIndex / (steps.length - 1)) * 100;

    const card = document.createElement('div');
    card.className = 'card incident-card';

    // Format Start Time
    const startTime = inc.started_at ? new Date(inc.started_at).toLocaleTimeString() : 'N/A';

    // Generate Steps HTML
    const stepsHtml = steps.map((step, idx) => {
      let statusClass = '';
      let markerSymbol = idx + 1;

      if (idx < currentStepIndex) {
        statusClass = 'complete';
        markerSymbol = '✓';
      } else if (idx === currentStepIndex && inc.status !== 'resolved' && inc.status !== 'error') {
        statusClass = 'active';
      }

      const labelMap = {
        sentry: 'Sentry',
        diagnostician: 'Diagnose',
        fix_planner: 'Fix Plan',
        comms: 'Comms'
      };

      return `
        <div class="step-node ${statusClass}">
          <div class="step-circle">${markerSymbol}</div>
          <div class="step-label">${labelMap[step]}</div>
        </div>
      `;
    }).join('');

    // Generate Diagnosis details block
    let detailsHtml = '';
    if (inc.diagnosis) {
      detailsHtml = `
        <div class="incident-details">
          <div class="detail-heading">System Diagnosis</div>
          <div class="detail-body">${escapeHtml(inc.diagnosis)}</div>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="incident-header">
        <div class="incident-type">
          <span>⚠️</span> ${inc.incident_type.toUpperCase()}
        </div>
        <span class="badge badge-${inc.severity.toLowerCase()}">${inc.severity}</span>
      </div>

      <div class="incident-meta">
        <div class="meta-item">
          <strong>Incident ID</strong>
          <span>${inc.incident_id}</span>
        </div>
        <div class="meta-item">
          <strong>Status</strong>
          <span style="font-family: var(--font-mono);">${inc.status}</span>
        </div>
        <div class="meta-item">
          <strong>Started At</strong>
          <span>${startTime}</span>
        </div>
      </div>

      <div class="steps-container">
        <div class="steps-progress-bar">
          <div class="steps-progress-fill" style="width: ${progressPercent}%"></div>
        </div>
        ${stepsHtml}
      </div>

      ${detailsHtml}
    `;

    incidentsContainer.appendChild(card);
  });
}

function renderResolvedIncidents(resolvedIncidents) {
  if (resolvedIncidents.length === 0) {
    resolvedList.innerHTML = `
      <div class="empty-state" style="padding: 2rem 1rem;">
        <p>No recently resolved incidents in this session.</p>
      </div>
    `;
    return;
  }

  // Clear list
  resolvedList.innerHTML = '';

  // Show top 5 recently resolved
  const recent = resolvedIncidents.slice(-5).reverse();

  recent.forEach((inc) => {
    const item = document.createElement('div');
    item.className = 'resolved-item';

    const resolvedTime = inc.resolved_at ? new Date(inc.resolved_at).toLocaleTimeString() : 'N/A';
    const mttdText = inc.mttd_seconds ? `${inc.mttd_seconds.toFixed(1)}s MTTD` : 'N/A MTTD';

    item.innerHTML = `
      <div class="resolved-info">
        <div class="resolved-name">${inc.incident_type.toUpperCase()} (${inc.incident_id})</div>
        <div class="resolved-meta">Resolved at ${resolvedTime} | Services: ${inc.affected_services.join(', ')}</div>
      </div>
      <div class="resolved-mttd">${mttdText}</div>
    `;
    resolvedList.appendChild(item);
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Start SSE connection
connect();
