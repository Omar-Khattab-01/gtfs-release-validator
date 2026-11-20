const scheduleView = document.querySelector('#schedule-view');
const scheduleSource = document.querySelector('#schedule-source');
const scheduleSearch = document.querySelector('#schedule-search');
const scheduleDate = document.querySelector('#schedule-date');
const scheduleGrid = document.querySelector('#schedule-grid');
const scheduleStatus = document.querySelector('#schedule-status');
const schedulePrev = document.querySelector('#schedule-prev');
const scheduleNext = document.querySelector('#schedule-next');
const scheduleDialog = document.querySelector('#schedule-dialog');
const scheduleBody = document.querySelector('#schedule-dialog-body');
const scheduleLabels = {bus:'Bus', line1:'Line 1', lines24:'Lines 2 & 4', other:'Other service'};
const scheduleNumber = new Intl.NumberFormat();
let scheduleMonth = '';
let scheduleRequest = 0;
let scheduleDayRequest = 0;
let scheduleSearchTimer;

function scheduleFormat(day, options) {
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, options);
}

function setupSchedule(feeds) {
  clearTimeout(scheduleSearchTimer);
  scheduleRequest++;
  scheduleDayRequest++;
  if (scheduleDialog.open) scheduleDialog.close();
  scheduleSource.innerHTML = ['final','cad','hastus','rail'].filter(source => feeds[source])
    .map(source => `<option value="${source}">${escapeHtml(inspectionLabels[source])}</option>`).join('');
  scheduleMonth = '';
  scheduleSearch.value = '';
  scheduleDate.value = '';
  scheduleGrid.replaceChildren();
  if (!scheduleView.classList.contains('hidden')) loadSchedule();
}

async function scheduleFetch(params) {
  const query = new URLSearchParams({source:scheduleSource.value, ...params});
  const response = await fetch(`/api/runs/${currentRunId}/calendar?${query}`, {cache:'no-store'});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not load the schedule');
  return data;
}

function scheduleGroups(groups) {
  return Object.keys(scheduleLabels).filter(key => key !== 'other' || groups.other.route_count || groups.other.removed.length);
}

function scheduleCount(group) {
  return `${scheduleNumber.format(group.route_count)} ${group.route_count === 1 ? 'route' : 'routes'} · ${scheduleNumber.format(group.trip_count)} trips`;
}

function renderScheduleMonth(data) {
  const weekdays = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  const blanks = new Date(`${data.month}-01T12:00:00`).getDay();
  const today = new Date().toLocaleDateString('sv-SE');
  const days = data.days.map(day => {
    const number = Number(day.date.slice(-2));
    const dateLabel = scheduleFormat(day.date, {weekday:'long',month:'long',day:'numeric',year:'numeric'});
    if (day.date < data.first_date || day.date > data.last_date) {
      return `<div class="schedule-day schedule-outside"><strong>${number}</strong><small>Outside feed dates</small></div>`;
    }
    const groups = scheduleGroups(day.groups).map(key => {
      const group = day.groups[key];
      const services = group.service_ids.join(', ');
      const changes = `${group.added.length ? ' + ' : ''}${group.removed.length ? ' − ' : ''}`;
      const description = `${scheduleLabels[key]}, ${dateLabel}, ${scheduleCount(group)}`;
      return `<button type="button" class="schedule-service ${key}" data-day="${day.date}" data-group="${key}" aria-label="${escapeHtml(description)}" title="${escapeHtml(services || 'No active service IDs')}">
        <span><strong>${escapeHtml(scheduleLabels[key])}</strong><small>${group.route_count || '–'}${changes}</small></span>
        <span class="schedule-service-ids">${escapeHtml(services || (scheduleSearch.value.trim() ? 'No matches' : 'No service'))}</span>
      </button>`;
    }).join('');
    return `<div class="schedule-day${day.date === today ? ' schedule-today' : ''}"><button type="button" class="schedule-day-number" data-day="${day.date}" aria-label="View service on ${escapeHtml(dateLabel)}">${number}</button>${day.date === today ? '<span class="schedule-today-label">Today</span>' : ''}${groups}</div>`;
  });
  scheduleGrid.innerHTML = weekdays.map(day => `<div class="schedule-weekday">${day}</div>`).join('')
    + '<div class="schedule-blank" aria-hidden="true"></div>'.repeat(blanks) + days.join('');
}

async function loadSchedule(month = scheduleMonth) {
  const request = ++scheduleRequest;
  schedulePrev.disabled = scheduleNext.disabled = true;
  scheduleStatus.textContent = 'Loading service dates…';
  scheduleGrid.replaceChildren();
  if (!scheduleSource.value) {
    scheduleStatus.textContent = 'Supply an export to view its schedule.';
    return;
  }
  try {
    const data = await scheduleFetch({month, search:scheduleSearch.value.trim()});
    if (request !== scheduleRequest) return;
    scheduleMonth = data.month;
    scheduleDate.min = data.first_date;
    scheduleDate.max = data.last_date;
    schedulePrev.disabled = data.month <= data.first_date.slice(0,7);
    scheduleNext.disabled = data.month >= data.last_date.slice(0,7);
    document.querySelector('#schedule-month').textContent = scheduleFormat(`${data.month}-01`, {month:'long',year:'numeric'});
    document.querySelector('#schedule-coverage').textContent = `Service calendar dates: ${data.first_date} to ${data.last_date}. Counts are scheduled trip records.`;
    const activeDays = data.days.filter(day => Object.values(day.groups).some(group => group.trip_count)).length;
    scheduleStatus.textContent = scheduleSearch.value.trim() ? `${activeDays} days with matching service this month` : '';
    renderScheduleMonth(data);
  } catch (error) {
    if (request !== scheduleRequest) return;
    scheduleStatus.textContent = error.message;
    document.querySelector('#schedule-coverage').textContent = '';
    document.querySelector('#schedule-month').textContent = '';
  }
}

function moveScheduleMonth(delta) {
  const month = new Date(`${scheduleMonth}-01T12:00:00`);
  month.setMonth(month.getMonth() + delta);
  loadSchedule(`${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, '0')}`);
}

function scheduleTripTable(target, trips) {
  const rows = document.createElement('tbody');
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'button secondary';
  more.textContent = 'Show more trips';
  let shown = 0;
  const addPage = () => {
    const page = trips.slice(shown, shown + 50);
    rows.insertAdjacentHTML('beforeend', page.map(trip => `<tr>
      <td><strong>${escapeHtml(trip.trip_id)}</strong><br>${escapeHtml(trip.trip_headsign || '—')}<br><small>Service ${escapeHtml(trip.service_id)}</small></td>
      <td>${escapeHtml(trip.block_id || '—')}<br><small>Direction ${escapeHtml(trip.direction_id || '—')}</small></td>
      <td>${escapeHtml(trip.first_time || '—')} to ${escapeHtml(trip.last_time || '—')}</td>
      <td>${escapeHtml(trip.first_stop_name || trip.first_stop_id || '—')}<br>${escapeHtml(trip.last_stop_name || trip.last_stop_id || '—')}</td>
    </tr>`).join(''));
    shown += page.length;
    more.hidden = shown >= trips.length;
  };
  target.innerHTML = '<div class="table-wrap"><table class="schedule-trip-table"><thead><tr><th>Trip / destination</th><th>Block / direction</th><th>Departure / arrival</th><th>First / last stop</th></tr></thead></table></div>';
  target.querySelector('table').append(rows);
  target.append(more);
  more.addEventListener('click', addPage);
  addPage();
}

function renderScheduleDay(data, key, service = '') {
  const group = data.groups[key];
  const routes = group.routes.filter(route => !service || route.services[service]);
  const visible = service ? {route_count:routes.length, trip_count:routes.reduce((sum, route) => sum + route.services[service], 0)} : group;
  const changes = [['Added',group.added],['Removed',group.removed]].filter(([,ids]) => ids.length)
    .map(([label,ids]) => `<div><strong>${label} service IDs</strong> ${escapeHtml(ids.join(', '))}</div>`).join('');
  const buttons = scheduleGroups(data.groups).map(name => `<button type="button" class="button secondary schedule-group-tab" data-schedule-group="${name}" aria-pressed="${key === name}">${escapeHtml(scheduleLabels[name])} <span>${data.groups[name].route_count}</span></button>`).join('');
  scheduleBody.innerHTML = `<div class="schedule-group-tabs" aria-label="Service groups">${buttons}</div>
    <div class="schedule-day-summary"><p>${escapeHtml(scheduleCount(visible))}</p><label>Service ID<select id="schedule-service-id"><option value="">All active services</option>${group.service_ids.map(id => `<option value="${escapeHtml(id)}" ${id === service ? 'selected' : ''}>${escapeHtml(id)}</option>`).join('')}</select></label></div>
    ${changes ? `<div class="schedule-exceptions">${changes}</div>` : ''}
    ${routes.length ? routes.map((route,i) => {
      const [background, foreground] = [route.route_color, route.route_text_color].map(value => {
        const hex = /^[0-9a-f]{6}$/i.test(value || '') ? `#${value.toUpperCase()}` : '';
        return {hex, label:hex || (value ? `Invalid (${value})` : 'Missing')};
      });
      return `<details class="schedule-route" data-route-index="${i}"><summary>
        <span class="schedule-route-code" style="background-color:${background.hex || '#FFFFFF'};color:${foreground.hex || '#000000'}">${escapeHtml(route.route_short_name || route.route_id)}</span>
        <span class="schedule-route-name">${escapeHtml(route.route_long_name || route.route_id)}<small>Route color ${escapeHtml(background.label)} · Text color ${escapeHtml(foreground.label)}</small></span>
        <span class="schedule-route-count">${scheduleNumber.format(service ? route.services[service] : route.trip_count)} trips${(service ? group.added.includes(service) : route.added_trips) ? ' · Added service' : ''}</span>
      </summary><div class="schedule-route-trips"></div></details>`;
    }).join('') : '<p class="quiet">No scheduled routes match this service group on the selected date.</p>'}`;
  scheduleBody.querySelectorAll('[data-schedule-group]').forEach(button => button.addEventListener('click', () => {
    renderScheduleDay(data, button.dataset.scheduleGroup);
    scheduleBody.querySelector('[aria-pressed="true"]').focus();
  }));
  scheduleBody.querySelector('#schedule-service-id').addEventListener('change', event => {
    renderScheduleDay(data, key, event.target.value);
    scheduleBody.querySelector('#schedule-service-id').focus();
  });
  scheduleBody.querySelectorAll('.schedule-route').forEach(details => details.addEventListener('toggle', async () => {
    if (!details.open || details.dataset.loaded) return;
    details.dataset.loaded = 'yes';
    const target = details.querySelector('.schedule-route-trips');
    target.textContent = 'Loading trip details…';
    try {
      const result = await scheduleFetch({date:data.date, route_id:routes[Number(details.dataset.routeIndex)].route_id, service_id:service});
      if (target.isConnected) {
        scheduleTripTable(target, result.trips);
        const headways = document.createElement('button');
        headways.type = 'button';
        headways.className = 'button secondary';
        headways.textContent = 'Headways & blocks';
        headways.addEventListener('click', () => openHeadways(scheduleSource.value, data.date, routes[Number(details.dataset.routeIndex)].route_id));
        target.prepend(headways);
      }
    } catch (error) {
      target.textContent = error.message;
      delete details.dataset.loaded;
    }
  }));
}

async function openScheduleDay(day, group) {
  const request = ++scheduleDayRequest;
  document.querySelector('#schedule-dialog-title').textContent = scheduleFormat(day, {weekday:'long', month:'long', day:'numeric',year:'numeric'});
  document.querySelector('#schedule-dialog-source').textContent = scheduleSource.selectedOptions[0]?.textContent || '';
  scheduleBody.textContent = 'Loading scheduled routes…';
  if (!scheduleDialog.open) scheduleDialog.showModal();
  try {
    const data = await scheduleFetch({date:day, search:scheduleSearch.value.trim()});
    if (request !== scheduleDayRequest || !scheduleDialog.open) return;
    const firstGroup = scheduleGroups(data.groups).find(key => data.groups[key].route_count) || 'bus';
    renderScheduleDay(data, group || firstGroup);
  } catch (error) {
    if (request === scheduleDayRequest) scheduleBody.textContent = error.message;
  }
}

document.querySelector('[data-view="schedule"]').addEventListener('click', () => loadSchedule());
scheduleSource.addEventListener('change', () => { scheduleDate.value = ''; loadSchedule(''); });
scheduleSearch.addEventListener('input', () => {
  clearTimeout(scheduleSearchTimer);
  scheduleSearchTimer = setTimeout(() => loadSchedule(), 220);
});
schedulePrev.addEventListener('click', () => moveScheduleMonth(-1));
scheduleNext.addEventListener('click', () => moveScheduleMonth(1));
scheduleDate.addEventListener('change', () => {
  if (!scheduleDate.value || !scheduleDate.checkValidity()) return;
  loadSchedule(scheduleDate.value.slice(0,7));
  openScheduleDay(scheduleDate.value);
});
scheduleGrid.addEventListener('click', event => {
  const button = event.target.closest('button[data-day]');
  if (button) openScheduleDay(button.dataset.day, button.dataset.group);
});
document.querySelector('#schedule-dialog-close').addEventListener('click', () => scheduleDialog.close());
scheduleDialog.addEventListener('close', () => { scheduleDayRequest++; scheduleBody.replaceChildren(); });
