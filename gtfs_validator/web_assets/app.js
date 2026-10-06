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
const routeSort = document.querySelector('#route-sort');
const stopMappingSearch = document.querySelector('#stop-mapping-search');
const stopMappingFilter = document.querySelector('#stop-mapping-filter');
const drawer = document.querySelector('#drawer-backdrop');
let activeFindings = [];
let filteredFindings = [];
let activeRule = '';
let activeRoute = '';
let activeVariation = '';
let activeVariationFilters = [];
let routeHealthData = [];
let stopMappingData = [];
let stopMappingLimit = 80;
let currentRunId = '';
let pageLimit = 60;
const selected = new Set();

const ruleGuidance = {
  STP005: 'Review rider-facing names side by side. Open an item to inspect every source field.',
  STP006: 'Review stops whose mapped coordinates are far apart. Open an item for a local coordinate map.',
  TRP102: 'Compare equivalent journeys with different stop patterns. Open an item for aligned stop sequences.',
  TRP103: 'Review route variations paired by direction and stop-sequence similarity.',
  STP010: 'Review mapped stops whose accessibility, platform, station, zone, or descriptive attributes differ.',
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
  activeVariation = '';
  activeVariationFilters = [];
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
  renderStopMapping(report.stats?.stop_crosswalk || {});
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
  const ambiguousRoutes = routes.filter(route => route.status === 'ambiguous').length;
  const healthyRoutes = routes.filter(route => route.status === 'healthy').length;
  const unpairedRoutes = routes.filter(route => route.status === 'not_comparable').length;
  document.querySelector('#route-summary').textContent = `${issueRoutes} with mismatches · ${ambiguousRoutes} ambiguous · ${healthyRoutes} matching · ${unpairedRoutes} source-only`;
  const routeNumberOrder = (a, b) => String(a.route_short_name).localeCompare(String(b.route_short_name), undefined, {numeric:true, sensitivity:'base'});
  const statusOrder = {issues: 0, ambiguous: 1, healthy: 2, not_comparable: 3};
  const orderedRoutes = [...routes].sort((a, b) => {
    if (routeSort.value === 'attention') return (statusOrder[a.status] - statusOrder[b.status]) || (b.mismatch_variation_count || 0) - (a.mismatch_variation_count || 0) || routeNumberOrder(a, b);
    if (routeSort.value === 'variations') return Math.max(b.clevercad_variation_count || 0, b.hastus_variation_count || 0) - Math.max(a.clevercad_variation_count || 0, a.hastus_variation_count || 0) || routeNumberOrder(a, b);
    return routeNumberOrder(a, b);
  });
  routeGrid.innerHTML = orderedRoutes.map(route => {
    const variationCounts = `${route.clevercad_variation_count || 0} CAD / ${route.hastus_variation_count || 0} HASTUS variations`;
    const issueParts = [];
    if (route.mismatch_variation_count) {
      issueParts.push(`${route.mismatch_variation_count} pattern mismatch${route.mismatch_variation_count === 1 ? '' : 'es'}`);
    }
    if (route.unpaired_variation_count) {
      issueParts.push(`${route.unpaired_variation_count} source-only pattern${route.unpaired_variation_count === 1 ? '' : 's'}`);
    }
    const detail = route.status === 'issues'
      ? issueParts.join(' · ')
      : route.status === 'ambiguous' ? `${route.ambiguous_variation_count || 0} pairing${route.ambiguous_variation_count === 1 ? '' : 's'} need review`
      : route.status === 'healthy' ? `${variationCounts} · all matching` : `${variationCounts} · no counterpart`;
    return `<button type="button" class="route-card ${escapeHtml(route.status)} ${activeRoute === route.route_short_name ? 'active' : ''}" data-route="${escapeHtml(route.route_short_name)}"><strong>${escapeHtml(route.route_short_name || 'Unnamed')}</strong><span>${escapeHtml(detail)}</span></button>`;
  }).join('');
  routeGrid.querySelectorAll('.route-card').forEach(card => card.addEventListener('click', () => {
    activeRoute = card.dataset.route;
    activeVariation = '';
    activeVariationFilters = [];
    activeRule = '';
    pageLimit = 60;
    renderRouteHealth(routes);
    renderIssueGroups();
    renderFindings();
  }));
  const active = document.querySelector('#active-route');
  active.classList.toggle('hidden', !activeRoute);
  document.querySelector('#active-route-label').textContent = activeRoute ? `Showing evidence for route ${activeRoute}` : '';
  renderVariationPanel(routes.find(route => route.route_short_name === activeRoute));
}

function buildVariationPairs(route) {
  const cadItems = route.clevercad_variations || [];
  const hastusItems = route.hastus_variations || [];
  const cadById = new Map(cadItems.map(item => [item.variation_id, item]));
  const hastusById = new Map(hastusItems.map(item => [item.variation_id, item]));
  return (route.variation_pairs || []).map(pair => ({
    ...pair,
    id: pair.pair_id,
    cad: cadById.get(pair.clevercad_variation_id) || null,
    hastus: hastusById.get(pair.hastus_variation_id) || null
  }));
}

function variationSummary(item, label) {
  if (!item) return `<section class="variation-source empty-source"><h5>${escapeHtml(label)}</h5><p>No paired variation.</p></section>`;
  const shapes = item.shape_ids?.length ? item.shape_ids.join(', ') : 'No shape_id';
  const descriptors = [...(item.direction_ids || []).map(value => `direction ${value}`), ...(item.headsigns || []).map(value => `to ${value}`)].join(' · ') || 'No direction/headsign';
  return `<section class="variation-source"><h5>${escapeHtml(label)} · ${escapeHtml(item.variation_id)}</h5><strong>${escapeHtml(item.stop_count)} stops · ${escapeHtml(item.trip_count)} trips</strong><span>${escapeHtml(descriptors)}</span><code>shape: ${escapeHtml(shapes)}</code></section>`;
}

function renderVariationPanel(route) {
  const panel = document.querySelector('#variation-panel');
  panel.classList.toggle('hidden', !route);
  if (!route) return;
  const scopeLabels = {
    all_comparable_variations: 'Every comparable route variation is affected.',
    specific_variations: 'The problem is limited to specific route variations.',
    none: route.status === 'not_comparable' ? 'No sufficiently similar pattern exists in the other source.' : 'All confidently paired route variations match.'
  };
  document.querySelector('#variation-title').textContent = `Route ${route.route_short_name} · ${route.clevercad_variation_count} CleverCAD and ${route.hastus_variation_count} HASTUS variations`;
  document.querySelector('#variation-scope').textContent = scopeLabels[route.variation_scope] || '';
  const pairs = buildVariationPairs(route);
  const groups = [
    ['issues', 'Needs attention'],
    ['ambiguous', 'Pairing needs review'],
    ['matching', 'Matching'],
    ['not_comparable', 'Source-only']
  ];
  document.querySelector('#variation-tabs').innerHTML = groups.map(([status, label]) => {
    const items = pairs.filter(pair => pair.status === status);
    if (!items.length) return '';
    return `<section class="variation-tab-group"><h5>${escapeHtml(label)} <span>${items.length}</span></h5><div class="variation-tabs">${items.map(pair => {
      const pairLabel = pair.cad && pair.hastus ? `${pair.cad.variation_id} ↔ ${pair.hastus.variation_id}` : pair.cad?.variation_id || pair.hastus?.variation_id;
      const sublabel = pair.status === 'issues' ? `${pair.difference_count} stop difference${pair.difference_count === 1 ? '' : 's'} · ${pair.similarity_percent}% similar` : pair.status === 'ambiguous' ? `${pair.similarity_percent}% similar · review pairing` : pair.status === 'matching' ? `${pair.cad.stop_count} stops match` : pair.reason;
      return `<button type="button" role="tab" aria-selected="${activeVariation === pair.id}" class="variation-tab ${escapeHtml(pair.status)} ${activeVariation === pair.id ? 'active' : ''}" data-pair-id="${escapeHtml(pair.id)}"><strong>${escapeHtml(pairLabel)}</strong><span>${escapeHtml(sublabel)}</span></button>`;
    }).join('')}</div></section>`;
  }).join('');
  panel.querySelectorAll('.variation-tab').forEach(tab => tab.addEventListener('click', () => selectVariation(route, pairs.find(pair => pair.id === tab.dataset.pairId))));
  document.querySelector('#clear-variation').classList.toggle('hidden', !activeVariation);
}

async function selectVariation(route, pair) {
  if (!pair) return;
  activeVariation = pair.id;
  activeVariationFilters = [pair.cad && `CAD|${pair.cad.variation_id}`, pair.hastus && `HASTUS|${pair.hastus.variation_id}`].filter(Boolean);
  pageLimit = 60;
  renderVariationPanel(route);
  renderFindings();
  const detailPanel = document.querySelector('#variation-detail');
  detailPanel.innerHTML = `<div class="variation-source-grid">${variationSummary(pair.cad, 'CleverCAD')}${variationSummary(pair.hastus, 'HASTUS')}</div>`;
  if (!pair.cad || !pair.hastus) {
    detailPanel.innerHTML += `<p class="variation-prompt">${escapeHtml(pair.reason || 'This source-only variation has no paired pattern to display side by side.')}</p>`;
    return;
  }
  detailPanel.innerHTML += '<div class="loading-detail"><div class="spinner"></div><p>Loading representative stop patterns…</p></div>';
  try {
    const query = new URLSearchParams({cad_trip_id: pair.cad.example_trip_id, hastus_trip_id: pair.hastus.example_trip_id});
    const response = await fetch(`/api/runs/${currentRunId}/variation-detail?${query}`, {cache:'no-store'});
    const detail = await response.json();
    if (!response.ok) throw new Error(detail.error || 'Variation evidence could not be loaded');
    if (activeVariation !== pair.id) return;
    detail.clevercad_variation_id = pair.cad.variation_id;
    detail.hastus_variation_id = pair.hastus.variation_id;
    detail.clevercad_shape_id = (pair.cad.shape_ids || []).join(', ');
    detail.hastus_shape_id = (pair.hastus.shape_ids || []).join(', ');
    detail.route_short_name = route.route_short_name;
    const resultLabel = pair.status === 'matching' ? 'Patterns match' : pair.status === 'ambiguous' ? 'Pairing needs review' : 'Pattern mismatch';
    const reason = pair.reason ? ` · ${pair.reason}` : '';
    detailPanel.innerHTML = `<div class="variation-source-grid">${variationSummary(pair.cad, 'CleverCAD')}${variationSummary(pair.hastus, 'HASTUS')}</div><div class="variation-result ${pair.status}"><strong>${escapeHtml(resultLabel)}</strong><span>${detail.differences.length ? `${detail.differences.length} stop-sequence differences` : 'The translated ordered stops are identical.'}${escapeHtml(reason)}</span></div>${renderTripDetail(detail)}`;
  } catch (error) {
    detailPanel.innerHTML += `<p class="variation-error">${escapeHtml(error.message)}</p>`;
  }
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
    const variationKeys = [
      ...(f.context?.clevercad_variation_ids || [f.context?.clevercad_variation_id]).filter(Boolean).map(value => `CAD|${value}`),
      ...(f.context?.hastus_variation_ids || [f.context?.hastus_variation_id]).filter(Boolean).map(value => `HASTUS|${value}`)
    ];
    const haystack = [f.rule_id, f.category, f.title, f.message, f.file, f.key, f.observed, f.expected, route, ...variationKeys, f.context?.clevercad_shape_id, f.context?.hastus_shape_id].join(' ').toLowerCase();
    return (!needle || haystack.includes(needle)) && (!severity || f.severity === severity) && (!category || f.category === category) && (!activeRule || f.rule_id === activeRule) && (!activeRoute || route === activeRoute) && (!activeVariationFilters.length || variationKeys.some(key => activeVariationFilters.includes(key)));
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
    const cadVariations = (f.context?.clevercad_variation_ids || [f.context?.clevercad_variation_id]).filter(Boolean).join(', ');
    const hastusVariations = (f.context?.hastus_variation_ids || [f.context?.hastus_variation_id]).filter(Boolean).join(', ');
    const cadShapes = (f.context?.clevercad_shape_ids || [f.context?.clevercad_shape_id]).filter(Boolean).join(', ');
    const hastusShapes = (f.context?.hastus_shape_ids || [f.context?.hastus_shape_id]).filter(Boolean).join(', ');
    const variationEvidence = f.context?.clevercad_variation_id || f.context?.hastus_variation_id
      ? `<div class="finding-variation"><span>${escapeHtml(cadVariations || 'CAD variation unavailable')} · shape ${escapeHtml(cadShapes || '—')}</span><span>${escapeHtml(hastusVariations || 'HASTUS variation unavailable')} · shape ${escapeHtml(hastusShapes || '—')}</span></div>` : '';
    return `<article class="finding-card"><input class="finding-select" type="checkbox" aria-label="Select finding ${escapeHtml(f.rule_id)}" data-index="${f._index}" ${selected.has(f._index) ? 'checked' : ''}><button type="button" class="finding-open" data-index="${f._index}"><span class="finding-meta"><span class="pill ${escapeHtml(f.severity)}">${escapeHtml(f.severity)}</span><span class="rule">${escapeHtml(f.rule_id)}</span><span class="finding-key">${escapeHtml(f.key || f.file || '')}</span></span><h4>${escapeHtml(f.title)}</h4>${variationEvidence}<div class="finding-preview"><span class="preview-value"><strong>CleverCAD / observed</strong><br>${escapeHtml(left)}</span><span class="preview-value hastus"><strong>HASTUS / expected</strong><br>${escapeHtml(right)}</span></div></button><span class="view-evidence">View evidence →</span></article>`;
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

function filteredStopMappings() {
  const needle = stopMappingSearch.value.trim().toLowerCase();
  const field = stopMappingFilter.value;
  return stopMappingData.filter(item => {
    const haystack = [item.clevercad_stop_id, item.hastus_stop_id, item.clevercad_stop_name, item.hastus_stop_name, ...(item.difference_fields || [])].join(' ').toLowerCase();
    return (!needle || haystack.includes(needle)) && (!field || (item.difference_fields || []).includes(field));
  });
}

function renderStopMapping(stats) {
  stopMappingData = stats.mapping_issues || [];
  stopMappingLimit = 80;
  document.querySelector('#stop-mapping-summary').textContent = `${stats.source_stop_mappings || 0} mapped pairs · ${stats.mapped_stop_mismatches || 0} with differences`;
  renderStopMappingRows();
}

function renderStopMappingRows() {
  const filtered = filteredStopMappings();
  const visible = filtered.slice(0, stopMappingLimit);
  const listElement = document.querySelector('#stop-mapping-list');
  listElement.innerHTML = visible.map((item, index) => {
    const badges = (item.difference_fields || []).map(field => `<span>${escapeHtml(field.replaceAll('_', ' '))}</span>`).join('');
    const distance = item.distance_m == null ? 'Distance unavailable' : `${item.distance_m} m apart`;
    return `<article class="stop-mapping-row"><div class="stop-pair"><section><small>CleverCAD ${escapeHtml(item.clevercad_stop_id)}</small><strong>${escapeHtml(item.clevercad_stop_name || 'Unnamed stop')}</strong></section><span aria-hidden="true">↔</span><section><small>HASTUS ${escapeHtml(item.hastus_stop_id)}</small><strong>${escapeHtml(item.hastus_stop_name || 'Unnamed stop')}</strong></section></div><div class="stop-difference-badges">${badges}</div><span class="quiet">${escapeHtml(distance)}</span><button type="button" class="button secondary stop-mapping-open" data-stop-index="${stopMappingData.indexOf(item)}">Compare fields</button></article>`;
  }).join('');
  document.querySelector('#stop-mapping-empty').classList.toggle('hidden', filtered.length !== 0);
  const more = document.querySelector('#stop-mapping-more');
  more.classList.toggle('hidden', visible.length >= filtered.length);
  more.textContent = `Show ${Math.min(100, filtered.length - visible.length)} more stops`;
  listElement.querySelectorAll('.stop-mapping-open').forEach(button => button.addEventListener('click', () => openStopMapping(Number(button.dataset.stopIndex))));
}

function openStopMapping(index) {
  const item = stopMappingData[index];
  if (!item) return;
  document.querySelector('#detail-title').textContent = `${item.clevercad_stop_id} ↔ ${item.hastus_stop_id}`;
  const differences = (item.differences || []).map(difference => `<tr><td>${escapeHtml(String(difference.field).replaceAll('_', ' '))}</td><td>${escapeHtml(difference.clevercad || '—')}</td><td>${escapeHtml(difference.hastus || '—')}</td></tr>`).join('');
  const summary = `<div class="detail-intro"><span class="pill warning">Mapped stop mismatch</span><p>These records map to one another, but the highlighted attributes differ.</p></div><div class="comparison-table compact-table"><table><thead><tr><th>Attribute</th><th>CleverCAD</th><th>HASTUS</th></tr></thead><tbody>${differences}</tbody></table></div>`;
  document.querySelector('#drawer-body').innerHTML = summary + renderStopDetail({clevercad:item.clevercad || {}, hastus:item.hastus || {}, distance_m:item.distance_m});
  drawer.classList.remove('hidden');
}

function exportStopMappings() {
  const rows = filteredStopMappings();
  if (!rows.length) return;
  const columns = ['clevercad_stop_id','hastus_stop_id','clevercad_stop_name','hastus_stop_name','distance_m','difference_fields'];
  const csv = [columns.join(','), ...rows.map(row => columns.map(column => csvCell(column === 'difference_fields' ? (row.difference_fields || []).join('|') : row[column])).join(','))].join('\r\n');
  const blob = new Blob(['\ufeff', csv], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'mapped-stop-mismatches.csv'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  const context = [detail.route_short_name && `Route ${detail.route_short_name}`, detail.headsign && `To ${detail.headsign}`, detail.first_time && `${detail.first_time}–${detail.last_time}`, detail.clevercad_variation_id && `${detail.clevercad_variation_id} · shape ${detail.clevercad_shape_id || '—'}`, detail.hastus_variation_id && `${detail.hastus_variation_id} · shape ${detail.hastus_shape_id || '—'}`, `${differences.length} explained differences`].filter(Boolean);
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
document.querySelector('#clear-route').addEventListener('click', () => { activeRoute = ''; activeVariation = ''; activeVariationFilters = []; renderRouteHealth(routeHealthData); renderFindings(); });
document.querySelector('#clear-variation').addEventListener('click', () => { activeVariation = ''; activeVariationFilters = []; document.querySelector('#variation-detail').innerHTML = '<p class="variation-prompt">Choose a variation tab to compare its representative CleverCAD and HASTUS stop patterns.</p>'; renderRouteHealth(routeHealthData); renderFindings(); });
routeSort.addEventListener('change', () => renderRouteHealth(routeHealthData));
document.querySelectorAll('.workspace-tab').forEach(tab => tab.addEventListener('click', () => {
  document.querySelectorAll('.workspace-tab').forEach(item => { item.classList.toggle('active', item === tab); item.setAttribute('aria-selected', String(item === tab)); });
  document.querySelector('#route-view').classList.toggle('hidden', tab.dataset.view !== 'routes');
  document.querySelector('#stop-view').classList.toggle('hidden', tab.dataset.view !== 'stops');
}));
stopMappingSearch.addEventListener('input', () => { stopMappingLimit = 80; renderStopMappingRows(); });
stopMappingFilter.addEventListener('change', () => { stopMappingLimit = 80; renderStopMappingRows(); });
document.querySelector('#stop-mapping-more').addEventListener('click', () => { stopMappingLimit += 100; renderStopMappingRows(); });
document.querySelector('#export-stop-mapping').addEventListener('click', exportStopMappings);
document.querySelector('#export-selected').addEventListener('click', () => downloadRows(activeFindings.filter(f => selected.has(f._index)), 'selected-gtfs-findings.csv'));
document.querySelector('#export-stops').addEventListener('click', () => downloadStopRows(filteredFindings.filter(f => f.rule_id.startsWith('STP'))));
document.querySelector('#close-drawer').addEventListener('click', () => drawer.classList.add('hidden'));
drawer.addEventListener('click', event => { if (event.target === drawer) drawer.classList.add('hidden'); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') drawer.classList.add('hidden'); });
[search, severityFilter, categoryFilter].forEach(control => control.addEventListener('input', () => { pageLimit = 60; renderFindings(); }));
