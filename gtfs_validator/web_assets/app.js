const form = document.querySelector('#run-form');
const clevercadInput = document.querySelector('#clevercad-path');
const hastusInput = document.querySelector('#hastus-path');
const finalInput = document.querySelector('#final-path');
const runButton = document.querySelector('#run-button');
const runningPanel = document.querySelector('#running-panel');
const results = document.querySelector('#results');
const body = document.querySelector('#findings-body');
const search = document.querySelector('#search');
const severityFilter = document.querySelector('#severity-filter');
const categoryFilter = document.querySelector('#category-filter');
let activeFindings = [];

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const formatBytes = (bytes) => bytes == null ? '—' : new Intl.NumberFormat().format(bytes) + ' B';

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  runButton.disabled = true;
  runningPanel.classList.remove('hidden');
  results.classList.add('hidden');
  try {
    const response = await fetch('/api/runs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-GTFS-Validator': '1'},
      body: JSON.stringify({
        clevercad_path: clevercadInput.value.trim(),
        hastus_path: hastusInput.value.trim(),
        final_path: finalInput.value.trim()
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Could not start validation');
    await poll(payload.id);
  } catch (error) {
    alert(error.message);
    runningPanel.classList.add('hidden');
  } finally {
    runButton.disabled = false;
  }
});

async function poll(id) {
  while (true) {
    const response = await fetch(`/api/runs/${id}`, {cache: 'no-store'});
    const payload = await response.json();
    if (payload.status === 'complete') {
      runningPanel.classList.add('hidden');
      renderReport(payload.report, id);
      return;
    }
    if (payload.status === 'failed') throw new Error(payload.error || 'Validation failed');
    await new Promise(resolve => setTimeout(resolve, 700));
  }
}

function renderReport(report, id) {
  results.classList.remove('hidden');
  const strip = document.querySelector('#decision-strip');
  strip.className = 'decision-strip ' + (report.decision === 'BLOCKED' ? 'blocked' : report.decision.startsWith('ELIGIBLE') ? 'approved' : '');
  document.querySelector('#decision').textContent = report.decision;
  document.querySelector('#source-name').textContent = report.source_path;
  document.querySelector('#hash').textContent = `SHA-256 ${report.sha256 || 'not available'}`;
  document.querySelector('#csv-link').href = `/api/runs/${id}/findings.csv`;
  document.querySelector('#json-link').href = `/api/runs/${id}/report.json`;
  const counts = report.counts;
  document.querySelector('#metrics').innerHTML = ['blocker','error','warning','info'].map(level => `<div class="metric ${level}"><strong>${counts[level] || 0}</strong><span>${level}${(counts[level] || 0) === 1 ? '' : 's'}</span></div>`).join('');
  activeFindings = report.findings;
  const categories = [...new Set(activeFindings.map(f => f.category))].sort();
  categoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option>${escapeHtml(c)}</option>`).join('');
  renderFindings();
  const inventoryRows = [];
  for (const [key, value] of Object.entries(report.stats)) {
    if (key === 'extracted_permissions') continue;
    if (key === 'inputs' && value && typeof value === 'object') {
      inventoryRows.push(['input archives', Object.keys(value).length]);
      continue;
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [childKey, childValue] of Object.entries(value)) {
        if (childValue == null || typeof childValue === 'object') continue;
        inventoryRows.push([`${key} · ${childKey}`, childValue]);
      }
      continue;
    }
    inventoryRows.push([key, value]);
  }
  document.querySelector('#inventory').innerHTML = inventoryRows.map(([key,value]) => `<div class="inventory-row"><span>${escapeHtml(key.replaceAll('_',' '))}</span><strong>${escapeHtml(value)}</strong></div>`).join('') || '<p class="quiet">No feed statistics available.</p>';
  const files = Object.entries(report.files);
  document.querySelector('#packaging').innerHTML = `<div class="package-row"><span>Archive size</span><strong>${formatBytes(report.archive_size)}</strong></div><div class="package-row"><span>Members inspected</span><strong>${files.length}</strong></div><div class="package-row"><span>Members stored as 0644</span><strong>${files.filter(([,v]) => v.stored_mode === '644').length} / ${files.length}</strong></div><div class="package-row"><span>System extraction tested</span><strong>${report.stats.extracted_permissions ? 'Yes' : 'Unavailable'}</strong></div>`;
  results.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function renderFindings() {
  const needle = search.value.trim().toLowerCase();
  const severity = severityFilter.value;
  const category = categoryFilter.value;
  const filtered = activeFindings.filter(f => {
    const haystack = [f.rule_id, f.category, f.title, f.message, f.file, f.key, f.observed, f.expected].join(' ').toLowerCase();
    return (!needle || haystack.includes(needle)) && (!severity || f.severity === severity) && (!category || f.category === category);
  });
  document.querySelector('#result-count').textContent = `${filtered.length} of ${activeFindings.length}`;
  document.querySelector('#empty-state').classList.toggle('hidden', filtered.length !== 0);
  body.innerHTML = filtered.map(f => {
    const location = [f.file, f.row ? `row ${f.row}` : '', f.key ? `key ${f.key}` : ''].filter(Boolean).map(escapeHtml).join('<br>');
    const evidence = [f.observed != null ? `Observed: ${f.observed}` : '', f.expected != null ? `Expected: ${f.expected}` : ''].filter(Boolean).map(escapeHtml).join('<br>');
    return `<tr><td><span class="pill ${escapeHtml(f.severity)}">${escapeHtml(f.severity)}</span></td><td><span class="rule">${escapeHtml(f.rule_id)}</span><div class="finding-message">${escapeHtml(f.category)}</div></td><td><strong class="finding-title">${escapeHtml(f.title)}</strong><div class="finding-message">${escapeHtml(f.message)}</div></td><td class="location"><code>${location || '—'}</code></td><td class="evidence">${evidence || '—'}</td></tr>`;
  }).join('');
}

[search, severityFilter, categoryFilter].forEach(control => control.addEventListener('input', renderFindings));
