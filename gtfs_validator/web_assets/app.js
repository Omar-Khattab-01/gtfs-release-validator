const form = document.querySelector('#run-form');
const clevercadInput = document.querySelector('#clevercad-path');
const hastusInput = document.querySelector('#hastus-path');
const finalInput = document.querySelector('#final-path');
const runButton = document.querySelector('#run-button');
const runningPanel = document.querySelector('#running-panel');
const results = document.querySelector('#results');
const list = document.querySelector('#findings-list');
const search = document.querySelector('#search');
const severityFilter = document.querySelector('#severity-filter');
const categoryFilter = document.querySelector('#category-filter');
const drawer = document.querySelector('#drawer-backdrop');
let activeFindings = [];
let filteredFindings = [];
let activeRule = '';
let activeRoute = '';
let routeHealthData = [];
let currentRunId = '';
let pageLimit = 60;
const selected = new Set();

const ruleGuidance = {
  STP005: 'Review rider-facing names side by side. Open an item to inspect every source field.',
  STP006: 'Review stops whose mapped coordinates are far apart. Open an item for a local coordinate map.',
  TRP102: 'Compare equivalent journeys with different stop patterns. Open an item for aligned stop sequences.',
  TRP100: 'The final ordered stops differ from the source export.',
  TRP101: 'Stops match, but times or pickup/drop-off rules changed in the final feed.'
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const formatBytes = (bytes) => bytes == null ? '—' : new Intl.NumberFormat().format(bytes) + ' B';

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  runButton.disabled = true;
  runningPanel.classList.remove('hidden');
  results.classList.add('hidden');
  selected.clear();
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
  currentRunId = id;
  activeRule = '';
  activeRoute = '';
  pageLimit = 60;
  results.classList.remove('hidden');
  const strip = document.querySelector('#decision-strip');
  strip.className = 'decision-strip ' + (report.decision === 'BLOCKED' ? 'blocked' : report.decision.startsWith('ELIGIBLE') ? 'approved' : '');
  document.querySelector('#decision').textContent = report.decision;
  document.querySelector('#source-name').textContent = report.source_path;
  document.querySelector('#hash').textContent = report.sha256 ? `Final SHA-256 ${report.sha256}` : 'Source archive hashes recorded in the exported report';
  document.querySelector('#csv-link').href = `/api/runs/${id}/findings.csv`;
  document.querySelector('#json-link').href = `/api/runs/${id}/report.json`;
  const counts = report.counts;
  document.querySelector('#metrics').innerHTML = ['blocker','error','warning','info'].map(level => `<div class="metric ${level}"><strong>${counts[level] || 0}</strong><span>${level}${(counts[level] || 0) === 1 ? '' : 's'}</span></div>`).join('');
  activeFindings = report.findings.map((finding, index) => ({...finding, _index: index}));
  const categories = [...new Set(activeFindings.map(f => f.category))].sort();
  categoryFilter.innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option>${escapeHtml(c)}</option>`).join('');
  renderRouteHealth(report.stats?.trip_reconciliation?.route_health || []);
  renderIssueGroups();
  renderFindings();
  renderInventory(report);
  renderPackaging(report);
  results.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function renderRouteHealth(routes) {
  routeHealthData = routes;
  const routeGrid = document.querySelector('#route-grid');
  const issueRoutes = routes.filter(route => route.status === 'issues').length;
  const healthyRoutes = routes.filter(route => route.status === 'healthy').length;
  const unpairedRoutes = routes.filter(route => route.status === 'not_comparable').length;
  document.querySelector('#route-summary').textContent = `${issueRoutes} with mismatches · ${healthyRoutes} matching · ${unpairedRoutes} not compared`;
  const statusOrder = {issues: 0, healthy: 1, not_comparable: 2};
  const orderedRoutes = [...routes].sort((a, b) => (statusOrder[a.status] - statusOrder[b.status]) || b.mismatch_journeys - a.mismatch_journeys || String(a.route_short_name).localeCompare(String(b.route_short_name), undefined, {numeric:true}));
  routeGrid.innerHTML = orderedRoutes.map(route => {
    const detail = route.status === 'issues'
      ? `${route.mismatch_journeys} mismatch${route.mismatch_journeys === 1 ? '' : 'es'}`
      : route.status === 'healthy' ? `${route.compared_journeys} compared · ${route.match_percent}%` : 'No comparable trips';
    return `<button type="button" class="route-card ${escapeHtml(route.status)} ${activeRoute === route.route_short_name ? 'active' : ''}" data-route="${escapeHtml(route.route_short_name)}"><strong>${escapeHtml(route.route_short_name || 'Unnamed')}</strong><span>${escapeHtml(detail)}</span></button>`;
  }).join('');
  routeGrid.querySelectorAll('.route-card').forEach(card => card.addEventListener('click', () => {
    activeRoute = card.dataset.route;
    activeRule = '';
    pageLimit = 60;
    renderRouteHealth(routes);
    renderIssueGroups();
    renderFindings();
  }));
  const active = document.querySelector('#active-route');
  active.classList.toggle('hidden', !activeRoute);
  document.querySelector('#active-route-label').textContent = activeRoute ? `Showing evidence for route ${activeRoute}` : '';
}

function renderIssueGroups() {
  const groups = new Map();
  for (const finding of activeFindings) {
    const current = groups.get(finding.rule_id) || {rule: finding.rule_id, title: finding.title, count: 0, severity: finding.severity};
    current.count += 1;
    groups.set(finding.rule_id, current);
  }
  const cards = [...groups.values()].sort((a,b) => b.count - a.count).slice(0, 6);
  document.querySelector('#issue-groups').innerHTML = cards.map(group => `<button type="button" class="issue-group ${activeRule === group.rule ? 'active' : ''}" data-rule="${escapeHtml(group.rule)}"><span class="group-top"><strong>${escapeHtml(group.title)}</strong><span class="group-count">${group.count}</span></span><p>${escapeHtml(ruleGuidance[group.rule] || 'Open an item to review source evidence and affected records.')}</p><span class="rule">${escapeHtml(group.rule)}</span></button>`).join('');
  document.querySelectorAll('.issue-group').forEach(card => card.addEventListener('click', () => {
    activeRule = activeRule === card.dataset.rule ? '' : card.dataset.rule;
    pageLimit = 60;
    renderIssueGroups();
    renderFindings();
  }));
}

function getFilteredFindings() {
  const needle = search.value.trim().toLowerCase();
  const severity = severityFilter.value;
  const category = categoryFilter.value;
  return activeFindings.filter(f => {
    const route = String(f.context?.route_short_name || '');
    const haystack = [f.rule_id, f.category, f.title, f.message, f.file, f.key, f.observed, f.expected, route].join(' ').toLowerCase();
    return (!needle || haystack.includes(needle)) && (!severity || f.severity === severity) && (!category || f.category === category) && (!activeRule || f.rule_id === activeRule) && (!activeRoute || route === activeRoute);
  });
}

function previewValues(finding) {
  if (finding.rule_id === 'STP005') {
    const parts = String(finding.observed || '').split(' | ');
    return [parts[0]?.replace(/^CAD:\s*/, '') || '—', parts[1]?.replace(/^HASTUS:\s*/, '') || '—'];
  }
  if (finding.rule_id === 'STP006') return [finding.observed || '—', finding.expected || 'Review on map'];
  return [finding.observed || 'CleverCAD evidence', finding.expected || 'HASTUS evidence'];
}

function renderFindings() {
  filteredFindings = getFilteredFindings();
  const visible = filteredFindings.slice(0, pageLimit);
  document.querySelector('#result-count').textContent = `${Math.min(pageLimit, filteredFindings.length)} shown · ${filteredFindings.length} matching · ${activeFindings.length} total`;
  document.querySelector('#empty-state').classList.toggle('hidden', filteredFindings.length !== 0);
  const loadMore = document.querySelector('#load-more');
  loadMore.classList.toggle('hidden', visible.length >= filteredFindings.length);
  loadMore.textContent = `Show ${Math.min(100, filteredFindings.length - visible.length)} more`;
  list.innerHTML = visible.map(f => {
    const [left, right] = previewValues(f);
    return `<article class="finding-card"><input class="finding-select" type="checkbox" aria-label="Select finding ${escapeHtml(f.rule_id)}" data-index="${f._index}" ${selected.has(f._index) ? 'checked' : ''}><button type="button" class="finding-open" data-index="${f._index}"><span class="finding-meta"><span class="pill ${escapeHtml(f.severity)}">${escapeHtml(f.severity)}</span><span class="rule">${escapeHtml(f.rule_id)}</span><span class="finding-key">${escapeHtml(f.key || f.file || '')}</span></span><h4>${escapeHtml(f.title)}</h4><div class="finding-preview"><span class="preview-value"><strong>CleverCAD / observed</strong><br>${escapeHtml(left)}</span><span class="preview-value hastus"><strong>HASTUS / expected</strong><br>${escapeHtml(right)}</span></div></button><span class="view-evidence">View evidence →</span></article>`;
  }).join('');
  document.querySelectorAll('.finding-select').forEach(box => box.addEventListener('change', () => {
    const index = Number(box.dataset.index);
    box.checked ? selected.add(index) : selected.delete(index);
    updateSelection();
  }));
  document.querySelectorAll('.finding-open').forEach(button => button.addEventListener('click', () => openDetail(Number(button.dataset.index))));
  updateSelection();
}

function updateSelection() {
  document.querySelector('#selected-count').textContent = selected.size;
  document.querySelector('#export-selected').disabled = selected.size === 0;
  document.querySelector('#export-stops').disabled = !filteredFindings.some(f => f.rule_id.startsWith('STP'));
}

function renderInventory(report) {
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
}

function renderPackaging(report) {
  const files = Object.entries(report.files);
  document.querySelector('#packaging').innerHTML = report.profile === 'oc-transpo-source-preflight'
    ? '<div class="package-row"><span>Final merged GTFS</span><strong>Not supplied</strong></div><p class="field-help">Final artifact and permission checks were skipped. Add the merged ZIP after the vendor produces it.</p>'
    : `<div class="package-row"><span>Final archive size</span><strong>${formatBytes(report.archive_size)}</strong></div><div class="package-row"><span>Members inspected</span><strong>${files.length}</strong></div><div class="package-row"><span>Members stored as 0644</span><strong>${files.filter(([,v]) => v.stored_mode === '644').length} / ${files.length}</strong></div><div class="package-row"><span>System extraction tested</span><strong>${report.stats.extracted_permissions ? 'Yes' : 'Unavailable'}</strong></div>`;
}

async function openDetail(index) {
  const finding = activeFindings.find(item => item._index === index);
  if (!finding) return;
  document.querySelector('#detail-title').textContent = finding.title;
  document.querySelector('#drawer-body').innerHTML = '<div class="loading-detail"><div class="spinner"></div><p>Loading source evidence…</p></div>';
  drawer.classList.remove('hidden');
  try {
    const response = await fetch(`/api/runs/${currentRunId}/details/${index}`, {cache: 'no-store'});
    const detail = await response.json();
    if (!response.ok) throw new Error(detail.error || 'Evidence could not be loaded');
    renderDetail(finding, detail);
  } catch (error) {
    document.querySelector('#drawer-body').innerHTML = `<div class="detail-intro"><strong>Evidence unavailable</strong><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderDetail(finding, detail) {
  const intro = `<div class="detail-intro"><span class="pill ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span> <span class="rule">${escapeHtml(finding.rule_id)}</span><p>${escapeHtml(finding.message)}</p></div>`;
  if (detail.type === 'stop') {
    document.querySelector('#drawer-body').innerHTML = intro + renderStopDetail(detail);
  } else if (detail.type === 'trip') {
    document.querySelector('#drawer-body').innerHTML = intro + renderTripDetail(detail);
  } else {
    document.querySelector('#drawer-body').innerHTML = intro + `<pre>${escapeHtml(JSON.stringify(detail, null, 2))}</pre>`;
  }
}

function sourceCard(label, data, cssClass='') {
  const preferred = ['stop_id','stop_code','stop_name','stop_desc','stop_lat','stop_lon','zone_id','stop_url','location_type','parent_station','stop_timezone','wheelchair_boarding','level_id','platform_code'];
  const remaining = Object.keys(data || {}).filter(key => !preferred.includes(key));
  const fields = [...preferred.filter(key => Object.hasOwn(data || {}, key)), ...remaining];
  return `<section class="source-card ${cssClass}"><h3>${escapeHtml(label)}</h3><dl class="field-list">${fields.map(key => `<div><dt>${escapeHtml(key.replaceAll('_',' '))}</dt><dd>${escapeHtml(data[key] || '—')}</dd></div>`).join('')}</dl></section>`;
}

function renderStopDetail(detail) {
  const map = renderCoordinateMap(detail.clevercad, detail.hastus, detail.distance_m);
  return `<div class="source-grid">${sourceCard('CleverCAD', detail.clevercad)}${sourceCard('HASTUS', detail.hastus, 'hastus')}</div>${map}`;
}

function renderCoordinateMap(cad, hastus, distance) {
  const points = [
    {label:'CleverCAD', lat:Number(cad.stop_lat), lon:Number(cad.stop_lon), color:'#183446'},
    {label:'HASTUS', lat:Number(hastus.stop_lat), lon:Number(hastus.stop_lon), color:'#c5202f'}
  ];
  if (points.some(point => !Number.isFinite(point.lat) || !Number.isFinite(point.lon))) return '';
  const minLat=Math.min(...points.map(p=>p.lat)), maxLat=Math.max(...points.map(p=>p.lat));
  const minLon=Math.min(...points.map(p=>p.lon)), maxLon=Math.max(...points.map(p=>p.lon));
  const latSpan=Math.max(maxLat-minLat,.00015), lonSpan=Math.max(maxLon-minLon,.00015);
  const plotted=points.map(point => ({...point,x:70+((point.lon-minLon)/lonSpan)*560,y:250-((point.lat-minLat)/latSpan)*190}));
  const grid=[100,200,300,400,500,600].map(x=>`<line x1="${x}" y1="35" x2="${x}" y2="270" stroke="#d6ddda"/>`).join('') + [70,120,170,220,270].map(y=>`<line x1="45" y1="${y}" x2="655" y2="${y}" stroke="#d6ddda"/>`).join('');
  return `<section class="map-card"><h3>Coordinate comparison · ${distance == null ? 'distance unavailable' : `${escapeHtml(distance)} metres apart`}</h3><svg class="mini-map" viewBox="0 0 700 300" role="img" aria-label="Relative positions of CleverCAD and HASTUS stop coordinates">${grid}<line x1="${plotted[0].x}" y1="${plotted[0].y}" x2="${plotted[1].x}" y2="${plotted[1].y}" stroke="#7a858b" stroke-width="2" stroke-dasharray="6 5"/>${plotted.map(point=>`<circle cx="${point.x}" cy="${point.y}" r="10" fill="${point.color}" stroke="white" stroke-width="4"/><text x="${point.x+15}" y="${point.y-10}" font-size="13" font-weight="700" fill="#101820">${point.label}</text><text x="${point.x+15}" y="${point.y+8}" font-size="10" fill="#5d6871">${point.lat.toFixed(6)}, ${point.lon.toFixed(6)}</text>`).join('')}</svg><div class="map-legend"><span><i class="legend-dot"></i>CleverCAD</span><span><i class="legend-dot hastus"></i>HASTUS</span><span>North ↑</span></div></section>`;
}

function renderTripDetail(detail) {
  const differences = detail.differences || [];
  const context = [detail.route_short_name && `Route ${detail.route_short_name}`, detail.headsign && `To ${detail.headsign}`, detail.first_time && `${detail.first_time}–${detail.last_time}`, `${differences.length} explained differences`].filter(Boolean);
  const statusLabels = {match:'Match', different_stop:'Different stops', clevercad_only:'Only in CleverCAD', hastus_only:'Only in HASTUS', schedule_difference:'Time / boarding rules'};
  const rows = (detail.alignment || []).map((row, index) => {
    const cad = row.clevercad || {};
    const hastus = row.hastus || {};
    const changedFields = row.fields?.length ? `<br><small>${escapeHtml(row.fields.join(', ').replaceAll('_',' '))}</small>` : '';
    return `<tr class="${escapeHtml(row.status.replaceAll('_','-'))}"><td>${index + 1}</td><td class="status-cell"><span class="diff-badge ${escapeHtml(row.status.replaceAll('_','-'))}">${escapeHtml(statusLabels[row.status] || row.status)}</span>${changedFields}</td><td>${escapeHtml(cad.sequence || '—')}</td><td>${escapeHtml(cad.departure_time || cad.arrival_time || '—')}</td><td><strong>${escapeHtml(cad.stop_name || '—')}</strong><br><small>source ${escapeHtml(cad.source_stop_id || '—')} · mapped ${escapeHtml(cad.canonical_stop_id || '—')}</small></td><td>${escapeHtml(hastus.sequence || '—')}</td><td>${escapeHtml(hastus.departure_time || hastus.arrival_time || '—')}</td><td><strong>${escapeHtml(hastus.stop_name || '—')}</strong><br><small>source ${escapeHtml(hastus.source_stop_id || '—')} · mapped ${escapeHtml(hastus.canonical_stop_id || '—')}</small></td></tr>`;
  }).join('');
  const evidence = differences.map((row, index) => {
    const cad = row.clevercad;
    const hastus = row.hastus;
    const cadName = cad?.stop_name || 'No CleverCAD stop';
    const hastusName = hastus?.stop_name || 'No HASTUS stop';
    return `<details class="mismatch-evidence"><summary>${index + 1}. ${escapeHtml(statusLabels[row.status] || row.status)} · ${escapeHtml(cadName)} ↔ ${escapeHtml(hastusName)}</summary><div class="source-grid">${sourceCard('CleverCAD complete stop record', cad?.source_record || {}, '')}${sourceCard('HASTUS complete stop record', hastus?.source_record || {}, 'hastus')}</div></details>`;
  }).join('');
  return `<div class="trip-context">${context.map(value=>`<span>${escapeHtml(value)}</span>`).join('')}</div><div class="comparison-table"><table><thead><tr><th>Aligned row</th><th>Result</th><th>CAD #</th><th>CAD time</th><th>CleverCAD stop</th><th>HASTUS #</th><th>HASTUS time</th><th>HASTUS stop</th></tr></thead><tbody>${rows}</tbody></table></div><div class="mismatch-stack"><h3>Mismatch evidence</h3><p class="quiet">Open any difference to see every available stops.txt field from both exports.</p>${evidence || '<p>No sequence differences were found.</p>'}</div>`;
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replaceAll('"','""')}"`;
}

function downloadRows(rows, filename) {
  if (!rows.length) return;
  const columns = ['rule_id','severity','category','title','key','observed','expected','file','row'];
  const csv = [columns.join(','), ...rows.map(row => columns.map(column => csvCell(row[column])).join(','))].join('\r\n');
  const blob = new Blob(['\ufeff', csv], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadStopRows(rows) {
  if (!rows.length) return;
  const columns = ['rule_id','severity','clevercad_stop_id','hastus_stop_id','clevercad_stop_name','hastus_stop_name','distance_m','message'];
  const exportRows = rows.map(row => {
    const context = row.context || {};
    const keyParts = String(row.key || '').split('↔').map(value => value.trim());
    const nameParts = String(row.observed || '').split(' | ');
    return {
      rule_id: row.rule_id,
      severity: row.severity,
      clevercad_stop_id: context.clevercad_stop_id || keyParts[0] || '',
      hastus_stop_id: context.hastus_stop_id || keyParts[1] || '',
      clevercad_stop_name: row.rule_id === 'STP005' ? (nameParts[0] || '').replace(/^CAD:\s*/, '') : '',
      hastus_stop_name: row.rule_id === 'STP005' ? (nameParts[1] || '').replace(/^HASTUS:\s*/, '') : '',
      distance_m: context.distance_m ?? (row.rule_id === 'STP006' ? String(row.observed || '').replace(/\s*m$/, '') : ''),
      message: row.message
    };
  });
  const csv = [columns.join(','), ...exportRows.map(row => columns.map(column => csvCell(row[column])).join(','))].join('\r\n');
  const blob = new Blob(['\ufeff', csv], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'affected-stops.csv'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.querySelector('#load-more').addEventListener('click', () => { pageLimit += 100; renderFindings(); });
document.querySelector('#clear-selection').addEventListener('click', () => { selected.clear(); renderFindings(); });
document.querySelector('#clear-route').addEventListener('click', () => { activeRoute = ''; renderRouteHealth(routeHealthData); renderFindings(); });
document.querySelector('#export-selected').addEventListener('click', () => downloadRows(activeFindings.filter(f => selected.has(f._index)), 'selected-gtfs-findings.csv'));
document.querySelector('#export-stops').addEventListener('click', () => downloadStopRows(filteredFindings.filter(f => f.rule_id.startsWith('STP'))));
document.querySelector('#close-drawer').addEventListener('click', () => drawer.classList.add('hidden'));
drawer.addEventListener('click', event => { if (event.target === drawer) drawer.classList.add('hidden'); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') drawer.classList.add('hidden'); });
[search, severityFilter, categoryFilter].forEach(control => control.addEventListener('input', () => { pageLimit = 60; renderFindings(); }));
