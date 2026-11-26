const cacheDialog = document.querySelector('#cache-dialog');
const cacheManagerStatus = document.querySelector('#cache-manager-status');
const cacheFeedList = document.querySelector('#cache-feed-list');
const savedPathFields = ['clevercad-path','hastus-path','final-path','rail-path'];
const pathStorageKey = 'gtfs.validator.paths.v1';
let cacheManagerData = null;
let cacheOffloading = false;

for (const id of savedPathFields) document.getElementById(id).value = '';
try { localStorage.removeItem(pathStorageKey); } catch (_) {}

function cacheSize(bytes) {
  if (bytes >= 1024**3) return `${(bytes/1024**3).toFixed(2)} GB`;
  return `${(bytes/1024**2).toFixed(1)} MB`;
}

function renderCacheManager(data) {
  cacheManagerData = data;
  const indexes = data.entries.filter(entry => entry.name.startsWith('index-'));
  const audits = data.entries.filter(entry => entry.name.startsWith('audit-'));
  cacheManagerStatus.textContent = `${indexes.length} saved exports · ${audits.length} saved audits · ${cacheSize(data.bytes)} · ${data.directory}`;
  cacheFeedList.innerHTML = indexes.map(entry => `<article class="cache-feed"><h3>${escapeHtml(entry.paths[0]?.split(/[\\/]/).pop() || 'Older saved index')}</h3>
    ${entry.paths.map(path => `<p class="cache-path">${escapeHtml(path)}</p>`).join('') || '<p>Reopen the original export once to associate its path with this index.</p>'}
    <p>${cacheSize(entry.bytes)} · Last used ${escapeHtml(new Date(entry.last_used * 1000).toLocaleString())}</p>
    ${entry.paths.length ? `<div class="cache-use-path"><label>Load saved path as<select data-cache-role="${entry.name}"><option value="final-path">Final merged GTFS</option><option value="rail-path">HASTUS rail</option><option value="hastus-path">HASTUS bus</option><option value="clevercad-path">CleverCAD</option></select></label><button type="button" class="button secondary" data-cache-use="${entry.name}">Use saved path</button></div>` : ''}
    <button type="button" class="button secondary" data-cache-offload="${entry.name}">Offload cached data (${cacheSize(entry.bytes)})</button></article>`).join('') || '<p>No saved feed indexes.</p>';
  document.querySelector('#cache-offload-all').disabled = !data.entries.length || cacheOffloading;
}

async function loadCacheManager() {
  cacheManagerStatus.textContent = 'Loading saved exports…';
  try {
    const response = await fetch('/api/cache', {cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not read saved data');
    renderCacheManager(data);
  } catch (error) { cacheManagerStatus.textContent = error.message; }
}

async function offloadSavedCache(name = '') {
  if (cacheOffloading) return;
  cacheOffloading = true;
  cacheDialog.querySelectorAll('button[data-cache-offload], #cache-offload-all').forEach(button => { button.disabled = true; });
  cacheManagerStatus.textContent = 'Offloading saved data…';
  try {
    const response = await fetch('/api/cache/offload', {method:'POST', headers:{'Content-Type':'application/json','X-GTFS-Validator':'1'}, body:JSON.stringify({name})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not offload cached data');
    renderCacheManager(data);
    cacheManagerStatus.textContent += ` · Offloaded ${data.cleanup.removed.length} saved files${data.cleanup.skipped.length ? ` · ${data.cleanup.skipped.length} files still in use, retry after browsing finishes` : ''}`;
    refreshCache();
  } catch (error) { cacheManagerStatus.textContent = error.message; }
  finally {
    cacheOffloading = false;
    cacheDialog.querySelectorAll('button[data-cache-offload]').forEach(button => { button.disabled = false; });
    document.querySelector('#cache-offload-all').disabled = !cacheManagerData?.entries.length;
  }
}

document.querySelector('#cache-manage').addEventListener('click', () => { cacheDialog.showModal(); loadCacheManager(); });
document.querySelector('#cache-dialog-close').addEventListener('click', () => cacheDialog.close());
document.querySelector('#cache-offload-all').addEventListener('click', () => offloadSavedCache());
cacheFeedList.addEventListener('click', event => {
  const offload = event.target.closest('[data-cache-offload]');
  if (offload) { offloadSavedCache(offload.dataset.cacheOffload); return; }
  const use = event.target.closest('[data-cache-use]');
  if (!use) return;
  const entry = cacheManagerData.entries.find(item => item.name === use.dataset.cacheUse);
  const role = cacheFeedList.querySelector(`[data-cache-role="${use.dataset.cacheUse}"]`).value;
  document.getElementById(role).value = entry.paths[0];
  cacheDialog.close();
  document.getElementById(role).focus();
});
