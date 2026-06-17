// Simple SSE client that listens for `/events` endpoint.
const eventSource = new EventSource('/events');

eventSource.onmessage = (e) => {
  const data = JSON.parse(e.data);
  const container = document.getElementById('incidents');
  const el = document.createElement('div');
  el.className = 'incident-card';
  el.innerHTML = `
    <h3>${data.incident_type.toUpperCase()} – ${data.severity}</h3>
    <p><strong>ID:</strong> ${data.incident_id}</p>
    <p><strong>Source:</strong> ${data.source || 'N/A'}</p>
    <p><strong>Started:</strong> ${new Date(data.started_at).toLocaleString()}</p>
  `;
  container.prepend(el);
};
