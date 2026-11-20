const headwaySource = document.querySelector('#headway-source');
const headwayRoute = document.querySelector('#headway-route');
const headwayDate = document.querySelector('#headway-date');
const headwayDirection = document.querySelector('#headway-direction');
const headwayStop = document.querySelector('#headway-stop');
const headwayThreshold = document.querySelector('#headway-threshold');
const headwayStatus = document.querySelector('#headway-status');
const headwayContent = document.querySelector('#headway-content');
let headwayRequest = 0;
let headwayData = null;
let headwayLimit = 60;
let headwayOpening = false;

function headwayBusy(busy) {
  for (const field of [headwayRoute, headwayDate, headwayDirection, headwayStop, headwayThreshold]) field.disabled = busy;
}

function headwayDuration(seconds) {
  if (seconds == null) return '—';
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round((seconds % 60) * 10) / 10;
  return minutes ? `${minutes}m${remainder ? ` ${remainder}s` : ''}` : `${remainder}s`;
}

function setupHeadways(feeds) {
  headwayRequest++;
  headwayData = null;
  headwaySource.innerHTML = ['final','rail','hastus','cad'].filter(source => feeds[source])
    .map(source => `<option value="${source}">${escapeHtml(inspectionLabels[source])}</option>`).join('');
  headwayRoute.replaceChildren();
  headwayDate.value = '';
  headwayDirection.replaceChildren();
  headwayStop.replaceChildren();
  headwayContent.replaceChildren();
}

async function headwayFetch(params = {}) {
  const query = new URLSearchParams({source:headwaySource.value, ...params});
  const response = await fetch(`/api/runs/${currentRunId}/headways?${query}`, {cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not read route headways');
  return data;
}

async function loadHeadwayCatalog(route = '', day = '') {
  const request = ++headwayRequest;
  headwayBusy(true);
  headwayData = null;
  headwayContent.replaceChildren();
  headwayStatus.textContent = 'Loading routes and service dates…';
  try {
    const catalog = await headwayFetch();
    if (request !== headwayRequest) return;
    const railTypes = new Set(['0','1','2','12']);
    const rail = catalog.routes.filter(item => railTypes.has(item.route_type));
    const other = catalog.routes.filter(item => !railTypes.has(item.route_type));
    const options = items => items.map(item => `<option value="${escapeHtml(item.route_id)}">${escapeHtml(item.route_short_name || item.route_id)} · ${escapeHtml(item.route_long_name || '')}</option>`).join('');
    headwayRoute.innerHTML = `${rail.length ? `<optgroup label="Rail">${options(rail)}</optgroup>` : ''}${other.length ? `<optgroup label="Bus and other routes">${options(other)}</optgroup>` : ''}`;
    if (route && catalog.routes.some(item => item.route_id === route)) headwayRoute.value = route;
    headwayDate.min = catalog.first_date;
    headwayDate.max = catalog.last_date;
    headwayDate.value = day || catalog.date;
    if (!headwayRoute.value) {
      headwayStatus.textContent = 'This export has no routes to inspect.';
      return;
    }
    await loadHeadways(true, true);
  } catch (error) {
    if (request === headwayRequest) headwayStatus.textContent = error.message;
  } finally {
    if (request === headwayRequest) headwayBusy(false);
  }
}

async function loadHeadways(resetStop = false, resetDirection = false) {
  const request = ++headwayRequest;
  if (!headwayRoute.value || !headwayDate.value || !headwayDate.checkValidity() || !headwayThreshold.checkValidity()) return;
  headwayBusy(true);
  headwayData = null;
  const params = {date:headwayDate.value, route_id:headwayRoute.value, threshold:headwayThreshold.value};
  if (!resetDirection && headwayDirection.options.length) params.direction = headwayDirection.value;
  if (!resetStop && headwayStop.value) params.stop_id = headwayStop.value;
  headwayStatus.textContent = 'Loading trip schedules, departure gaps and blocks…';
  headwayContent.replaceChildren();
  try {
    const data = await headwayFetch(params);
    if (request !== headwayRequest) return;
    headwayData = data;
    headwayLimit = 60;
    headwayDirection.innerHTML = data.directions.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value === '' ? 'Unspecified direction' : 'Direction ' + value)}</option>`).join('') + '<option value="all">All directions</option>';
    headwayDirection.value = data.direction;
    headwayStop.innerHTML = data.stops.map(stop => `<option value="${escapeHtml(stop.stop_id)}">${escapeHtml(stop.stop_name)} · ${escapeHtml(stop.stop_id)} · ${stop.trip_count} trips</option>`).join('');
    headwayStop.value = data.stop_id;
    headwayStatus.textContent = `${data.route.route_short_name || data.route.route_id} · ${data.date} · ${data.trips.length} trip records · ${data.departures.length} boarding departures at the selected stop`;
    renderHeadways();
  } catch (error) {
    if (request === headwayRequest) headwayStatus.textContent = error.message;
  } finally {
    if (request === headwayRequest) headwayBusy(false);
  }
}

function renderHeadwayTrips() {
  const search = document.querySelector('#headway-trip-search').value.toLowerCase().trim();
  const rows = headwayData.trips.filter(trip => [trip.trip_id,trip.block_id,trip.trip_headsign,trip.service_id,trip.shape_id].some(value => String(value || '').toLowerCase().includes(search)));
  document.querySelector('#headway-trip-count').textContent = `${rows.length} matching trip records`;
  document.querySelector('#headway-trip-rows').innerHTML = rows.slice(0,headwayLimit).map(trip => {
    const departures = trip.departures.map(call => `<div>${escapeHtml(call.time)} <small>Seq ${escapeHtml(call.sequence)}</small></div>`).join('');
    const gaps = trip.departures.map(call => `<div>${headwayDuration(call.headway_seconds)}${call.previous_trip_id ? `<small>After ${escapeHtml(call.previous_trip_id)}</small>` : ''}</div>`).join('');
    return `<tr><td>${departures || 'No boarding departure'}</td>
      <td>${gaps || '—'}</td><td><button type="button" class="text-button headway-trip-link" data-trip="${escapeHtml(trip.trip_id)}">${escapeHtml(trip.trip_id)}</button><div>${escapeHtml(trip.trip_headsign || '')}</div></td>
      <td><strong>${escapeHtml(trip.block_id || 'Unassigned')}</strong><div>Direction ${escapeHtml(trip.direction_id || 'Unspecified')}</div></td>
      <td>${escapeHtml(trip.service_id)}<small>Shape ${escapeHtml(trip.shape_id || 'Unspecified')}</small></td>
      <td>${escapeHtml(trip.first_time || '—')} – ${escapeHtml(trip.last_time || '—')}<small>${escapeHtml(trip.first_stop)} → ${escapeHtml(trip.last_stop)}</small></td></tr>`;
  }).join('');
  document.querySelector('#headway-more').hidden = rows.length <= headwayLimit;
}

function renderHeadways() {
  const data = headwayData;
  const card = (value,label) => `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`;
  const issueGroups = {};
  for (const issue of data.issues) (issueGroups[issue.kind] ||= []).push(issue);
  const issues = Object.values(issueGroups).map(group => `<details class="headway-review"><summary>${escapeHtml(group[0].message)} <strong>${group.length}</strong></summary>${group.map(issue => `<pre>${escapeHtml(JSON.stringify(issue,null,2))}</pre>`).join('')}</details>`).join('');
  headwayContent.innerHTML = `<div class="metric-grid">${card(headwayDuration(data.headways.minimum),'Shortest headway')}${card(headwayDuration(data.headways.median),'Median headway')}${card(headwayDuration(data.headways.maximum),'Longest headway')}${card(data.block_count,'Assigned blocks')}</div>
    <p class="field-help">${data.unassigned_blocks} trip records have an empty block ID. ${data.not_at_stop} scheduled records have no timed boarding departure at this stop. ${data.excluded_no_pickup_calls} drop-off-only calls and ${data.missing_departure_times} calls without departure times are excluded from the gaps.</p>
    <details class="headway-section" ${data.issues.length ? 'open' : ''}><summary>Review checks · ${data.issues.length} items</summary><p>Block overlaps are checked across this route’s active directions. Gap alerts use your selected threshold.</p>${issues || '<p>No review items found by these checks.</p>'}</details>
    <details class="headway-section" open><summary>Hourly departure frequency and headways</summary><div class="table-wrap"><table class="headway-hourly"><thead><tr><th>GTFS hour</th><th>Direction</th><th>Departures in hour</th><th>Shortest gap</th><th>Median gap</th><th>Longest gap</th></tr></thead><tbody>${data.hourly.map(hour => `<tr><td>${String(hour.hour).padStart(2,'0')}:00</td><td>${escapeHtml(hour.direction_id || 'Unspecified')}</td><td>${hour.departures}</td><td>${headwayDuration(hour.minimum)}</td><td>${headwayDuration(hour.median)}</td><td>${headwayDuration(hour.maximum)}</td></tr>`).join('')}</tbody></table></div></details>
    <h4>Trips and blocks</h4><p class="field-help">Open a trip ID for its full exported attributes, stops and shape. Service times such as 25:00 retain their GTFS hour.</p>
    <div class="headway-table-tools"><label>Find a trip, block, destination or shape<input id="headway-trip-search" type="search"></label><span id="headway-trip-count"></span></div>
    <div class="table-wrap"><table class="headway-trip-table"><thead><tr><th>Departure at selected stop</th><th>Gap from previous departure</th><th>Trip / destination</th><th>Block / direction</th><th>Service / shape</th><th>Trip times / endpoints</th></tr></thead><tbody id="headway-trip-rows"></tbody></table></div><button type="button" class="button secondary" id="headway-more">Show more trips</button>`;
  renderHeadwayTrips();
  document.querySelector('#headway-trip-search').addEventListener('input', () => { headwayLimit = 60; renderHeadwayTrips(); });
  document.querySelector('#headway-more').addEventListener('click', () => { headwayLimit += 60; renderHeadwayTrips(); });
}

async function openHeadways(source, day, route) {
  scheduleDialog.close();
  headwaySource.value = source;
  headwayOpening = true;
  document.querySelector('[data-view="headways"]').click();
  try { await loadHeadwayCatalog(route, day); }
  finally { headwayOpening = false; }
}

document.querySelector('[data-view="headways"]').addEventListener('click', () => { if (!headwayData && !headwayOpening) loadHeadwayCatalog(); });
headwaySource.addEventListener('change', () => loadHeadwayCatalog());
headwayRoute.addEventListener('change', () => loadHeadways(true, true));
headwayDate.addEventListener('change', () => loadHeadways(true, true));
headwayDirection.addEventListener('change', () => loadHeadways(true));
headwayStop.addEventListener('change', () => loadHeadways());
headwayThreshold.addEventListener('change', () => loadHeadways());
headwayContent.addEventListener('click', event => {
  const button = event.target.closest('[data-trip]');
  if (button) inspectionOpenViewer(headwaySource.value, {trip:button.dataset.trip});
});
