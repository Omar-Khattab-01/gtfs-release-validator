/* Local build workflow. No feed bytes are sent through the browser. */
const buildForm = document.querySelector('#build-form');
const buildState = {selected: null, active: null, timer: null, picking: false, submitting: false, refreshing: false, resultKey: ''};
const buildStorageKey = 'gtfs.merge-builder.form.v1';
const buildStages = [['sources','Read sources'], ['matching','Match trips'], ['building','Build GTFS'], ['verifying','Verify'], ['comparing','Compare'], ['ready','Ready']];

function setWorkflow(mode) {
  document.querySelector('#inspect-workflow').classList.toggle('hidden', mode !== 'inspect');
  document.querySelector('#build-workflow').classList.toggle('hidden', mode !== 'build');
  document.querySelectorAll('[data-workflow]').forEach(button => {
    button.classList.toggle('active', button.dataset.workflow === mode);
    button.setAttribute('aria-pressed', String(button.dataset.workflow === mode));
  });
  if (mode === 'build') refreshBuilds();
}
document.querySelectorAll('[data-workflow]').forEach(button => button.addEventListener('click', () => setWorkflow(button.dataset.workflow)));

function buildError(message = '') {
  const target = document.querySelector('#build-error');
  target.textContent = message;
  target.classList.toggle('hidden', !message);
}

async function buildRequest(url, payload) {
  const response = await fetch(url, payload === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-GTFS-Validator':'1'}, body:JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The local build request could not finish.');
  return data;
}

function saveBuildForm() {
  try { localStorage.setItem(buildStorageKey, JSON.stringify(Object.fromEntries(new FormData(buildForm)))); } catch (_) { /* Restricted browser storage is optional. */ }
}
try {
  const saved = JSON.parse(localStorage.getItem(buildStorageKey) || '{}');
  for (const element of buildForm.elements) if (element.name && typeof saved[element.name] === 'string') element.value = saved[element.name];
} catch (_) { /* Manual entry stays available. */ }

function buildDateBounds() { document.querySelector('#build-end').min = document.querySelector('#build-start').value; }
buildDateBounds();
buildForm.addEventListener('input', () => { saveBuildForm(); buildDateBounds(); });
document.querySelector('#build-use-inputs').addEventListener('click', () => {
  for (const [target,source] of [['build-cad','clevercad-path'],['build-hastus','hastus-path'],['build-rail','rail-path']]) {
    document.getElementById(target).value = document.getElementById(source).value;
  }
  saveBuildForm();
});

function buildBusy() {
  document.querySelector('#build-fields').disabled = Boolean(buildState.active) || buildState.submitting;
  document.querySelector('#build-use-inputs').disabled = Boolean(buildState.active);
  document.querySelector('#build-submit').disabled = Boolean(buildState.active) || buildState.picking || buildState.submitting;
  document.querySelector('#build-submit').textContent = buildState.active ? 'Merge in progress…' : 'Build draft GTFS';
}

document.querySelector('#build-workflow').addEventListener('click', async event => {
  const button = event.target.closest('[data-pick]');
  if (!button || buildState.picking) return;
  buildState.picking = true; buildBusy();
  const original = button.textContent;
  button.textContent = 'Choosing…'; button.disabled = true; buildError();
  try {
    const data = await buildRequest('/api/builds/pick', {kind:button.dataset.pick});
    if (data.path) { document.getElementById(button.dataset.target).value = data.path; saveBuildForm(); }
  } catch (error) { buildError(error.message); }
  finally { buildState.picking = false; button.textContent = original; button.disabled = false; buildBusy(); }
});

buildForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (buildState.active || buildState.picking || buildState.submitting) return;
  buildError();
  const payload = Object.fromEntries(new FormData(buildForm));
  saveBuildForm();
  buildState.submitting = true; buildState.active = 'starting'; buildBusy();
  try {
    const job = await buildRequest('/api/builds', payload);
    buildState.selected = job.id; buildState.active = job.id;
    renderBuild(job);
    document.querySelector('#build-progress-panel').scrollIntoView({behavior:'smooth',block:'start'});
  } catch (error) { buildState.active = null; buildError(error.message); }
  finally { buildState.submitting = false; buildBusy(); refreshBuilds(); }
});

function buildPolicyHtml(policy, title = 'Default publication policy') {
  const rules = (policy.direction_rules || []).map(rule => `${rule.route_min}–${rule.route_max}: direction ${rule.keep.join(' / ')}`).join('; ') || 'No direction exclusions';
  return `<p><strong>${escapeHtml(title)}</strong></p><ul><li>Excluded routes: ${escapeHtml((policy.exclude_routes || []).join(', ') || 'None')}</li><li>${escapeHtml(rules)}</li><li>${policy.clear_block_ids?.length ? 'Cleared block IDs: '+escapeHtml(policy.clear_block_ids.join(', ')) : 'Preserve CAD block IDs'}</li></ul>`;
}

function buildResultHtml(job) {
  const result = job.result;
  if (!result) return '';
  const summary = result.summary, counts = summary.counts, validation = summary.validation.counts;
  const number = value => Number(value || 0).toLocaleString();
  const groups = summary.review_groups || [], reviewCount = groups.reduce((sum,g) => sum+g.count,0);
  const url = kind => `/api/builds/${encodeURIComponent(job.id)}/download/${kind}`;
  const metric = (value,label) => `<div class="metric"><strong>${number(value)}</strong><span>${label}</span></div>`;
  const example = item => {
    const parts = Object.fromEntries(Object.entries(item).filter(([key]) => !['kind','message'].includes(key)));
    return `<li><p>${escapeHtml(item.message)}</p>${Object.keys(parts).length ? `<pre>${escapeHtml(JSON.stringify(parts,null,2))}</pre>` : ''}</li>`;
  };
  const comparison = result.comparison || {status:'not_requested'};
  let compareHtml = '<p>No reference final supplied. The draft was generated from its source exports.</p>';
  if (comparison.status === 'complete') {
    const different = Object.entries(comparison.tables).filter(([,table]) => table.byte_equal === false || table.counts?.changed_rows || table.counts?.candidate_only_rows || table.counts?.reference_only_rows);
    compareHtml = `<h4>${comparison.equivalent ? 'Reference data match' : 'Reference differences found'}</h4><p>Comparison normalizes surrounding whitespace and numeric formatting. It does not require identical ZIP bytes.</p>`;
    if (different.length) compareHtml += `<div class="table-wrap"><table class="build-comparison"><thead><tr><th>Table</th><th>Changed records</th><th>Only in draft</th><th>Only in reference</th></tr></thead><tbody>${different.map(([name,t])=>`<tr><td>${escapeHtml(name)}</td><td>${number(t.counts?.changed_rows)}</td><td>${number(t.counts?.candidate_only_rows)}</td><td>${number(t.counts?.reference_only_rows)}</td></tr>`).join('')}</tbody></table></div>`;
    for (const [key,label] of [['candidate_only_members','Files only in draft'],['reference_only_members','Files only in reference']]) if (comparison[key]?.length) compareHtml += `<p>${label}: ${escapeHtml(comparison[key].join(', '))}</p>`;
    compareHtml += `<a class="button secondary" download href="${url('comparison')}">Download comparison JSON</a>`;
  } else if (['pending','running'].includes(comparison.status)) compareHtml = '<p>The reference comparison is in progress. The draft and receipt are already saved.</p>';
  else if (comparison.status !== 'not_requested') compareHtml = `<p class="build-error">Reference comparison ${escapeHtml(comparison.status)}: ${escapeHtml(comparison.message || 'It did not finish. The draft and receipt remain available.')}</p>`;
  const findings = summary.validation.findings || [];
  return `<div class="build-ready"><div><p class="kicker">Draft output · not approved for publication</p><h3>Your merged GTFS is saved.</h3><p class="build-output-path">${escapeHtml(result.output)}</p></div><a class="button" href="${url('zip')}" download>Download GTFS ZIP</a></div>
    <div class="metric-grid">${metric(counts.routes,'Routes')}${metric((counts.bus_trips||0)+(counts.rail_trips||0),'Trip records')}${metric(counts.stops,'Stops')}${metric((counts.bus_stop_times||0)+(counts.rail_stop_times||0),'Stop-time records')}</div>
    <section class="panel build-note"><div class="build-downloads"><a class="button secondary" href="${url('receipt')}" download>Full receipt &amp; crosswalk</a><a class="button secondary" href="${url('reviews')}" download>Review items CSV</a><button type="button" id="build-open-inspector" class="button secondary">Use in inspector</button></div><p class="quiet">${number(counts.bus_trips)} bus trips · ${number(counts.rail_trips)} rail trips · ${number(summary.excluded_trip_count)} trip records excluded by policy. “Use in inspector” fills the inspection form so you can choose your validation checks.</p><details><summary>Applied publication policy</summary>${buildPolicyHtml(summary.policy,'Policy used for this build')}</details></section>
    <div class="build-review-layout"><section class="panel build-note"><h3>${number(reviewCount)} review items</h3><p>Review uncertain matches and omitted content before publication. The receipt contains every item; the groups below show up to five examples each.</p>${groups.length ? groups.map(g=>`<details class="build-review-group"><summary><strong>${escapeHtml(g.title)}</strong><span>${number(g.count)}</span></summary><ul>${g.examples.map(example).join('')}</ul></details>`).join('') : '<p>No source-matching or policy review items were recorded.</p>'}</section>
    <section class="panel build-note"><h3>Technical checks</h3><p>${number(validation.blocker)} blockers · ${number(validation.error)} errors · ${number(validation.warning)} warnings</p><p>ZIP integrity passed. All members are stored at root as regular files with mode <code>0644</code>.</p><p class="quiet">${escapeHtml(summary.archive_verification.windows_note || 'Temporary extraction verified every file as 0644.')}</p><p class="quiet">These are core checks. MobilityData can be run through the inspector.</p>${findings.length ? `<details><summary>Core validation findings</summary><pre>${escapeHtml(JSON.stringify(findings.slice(0,20),null,2))}</pre></details>` : ''}<details><summary>Output SHA-256</summary><code class="build-output-path">${escapeHtml(summary.sha256)}</code></details><h3 class="build-section-title">Reference comparison</h3>${compareHtml}</section></div>`;
}

function renderBuild(job) {
  const panel = document.querySelector('#build-progress-panel');
  panel.classList.remove('hidden');
  const running = ['queued','running','comparing'].includes(job.status);
  const stopped = ['failed','interrupted'].includes(job.status);
  document.querySelector('#build-spinner').classList.toggle('hidden', !running);
  document.querySelector('#build-status-label').textContent = stopped ? 'Build needs attention' : running ? 'Build in progress' : 'Build complete';
  document.querySelector('#build-progress-title').textContent = job.request.output_path.split(/[\\/]/).pop();
  document.querySelector('#build-progress-message').textContent = job.error || job.progress;
  document.querySelector('#build-progress-message').classList.toggle('build-error', stopped);
  const stages = buildStages.filter(([key]) => key !== 'comparing' || job.request.reference_path);
  const current = stages.findIndex(([key]) => key === job.stage);
  document.querySelector('#build-stages').innerHTML = stages.map(([key,label],i) => `<li class="${i < current ? 'done' : i === current ? 'current' : ''}" ${i === current ? 'aria-current="step"' : ''}>${label}</li>`).join('');
  const until = running ? Date.now() : Date.parse(job.updated_at);
  const seconds = Math.max(0,Math.floor((until-Date.parse(job.created_at))/1000));
  document.querySelector('#build-elapsed').textContent = `${Math.floor(seconds/60)}m ${seconds%60}s elapsed${running ? ' · Keep this server window open; large feeds take several minutes.' : ''}`;
  document.querySelector('#build-log').textContent = job.log.map(entry=>`${entry.time}  ${entry.message}`).join('\n');
  const key = `${job.id}:${job.status}:${job.result?.comparison?.status || ''}`;
  if (key !== buildState.resultKey) {
    buildState.resultKey = key;
    document.querySelector('#build-result').innerHTML = buildResultHtml(job);
    document.querySelector('#build-result').classList.toggle('hidden', !job.result);
    document.querySelector('#build-open-inspector')?.addEventListener('click', () => {
      const pairs = [['clevercad-path','cad_path'],['hastus-path','hastus_path'],['rail-path','rail_path']];
      for (const [id,name] of pairs) document.getElementById(id).value = job.request[name] || '';
      document.querySelector('#final-path').value = job.result.output;
      setWorkflow('inspect');
      document.querySelector('#setup-panel').scrollIntoView({behavior:'smooth',block:'start'});
      document.querySelector('#run-button').focus({preventScroll:true});
    });
  }
}

async function refreshBuilds() {
  if (buildState.refreshing) return;
  clearTimeout(buildState.timer); buildState.refreshing = true;
  try {
    const data = await buildRequest('/api/builds');
    if (!document.querySelector('#build-directory').value) document.querySelector('#build-directory').value = data.defaults.output_directory;
    document.querySelector('#build-policy-summary').innerHTML = buildPolicyHtml(data.defaults.policy);
    buildState.active = data.active_id;
    document.querySelector('#build-history').innerHTML = data.builds.length ? data.builds.map(job => `<button type="button" class="build-history-item ${job.id === buildState.selected ? 'active' : ''}" data-build-id="${escapeHtml(job.id)}"><strong>${escapeHtml(job.request.output_path.split(/[\\/]/).pop())}</strong><span>${escapeHtml(new Date(job.created_at).toLocaleString())} · ${escapeHtml(job.status)}</span></button>`).join('') : '<p class="quiet">Your first build will appear here.</p>';
    if (!buildState.selected) buildState.selected = data.active_id || data.builds[0]?.id;
    if (buildState.selected) renderBuild(await buildRequest(`/api/builds/${encodeURIComponent(buildState.selected)}`));
  } catch (error) {
    buildError(`Could not reconnect to the local builder: ${error.message} Keep the server window open and use Refresh to retry.`);
  } finally {
    buildState.refreshing = false; buildBusy();
    if (buildState.active) buildState.timer = setTimeout(refreshBuilds, 2000);
  }
}
document.querySelector('#build-refresh').addEventListener('click', () => { buildError(); refreshBuilds(); });
document.querySelector('#build-history').addEventListener('click', event => {
  const button = event.target.closest('[data-build-id]');
  if (button) { buildState.selected = button.dataset.buildId; refreshBuilds(); }
});
if (new URLSearchParams(window.location.search).get('workflow') === 'build') setWorkflow('build');
