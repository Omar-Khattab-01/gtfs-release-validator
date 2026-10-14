// Dedicated reports keep their searches and scroll position while evidence is open.
let missingRequest = 0;
let missingOpener = null;
const missingDialog = document.querySelector('#missing-dialog');

function missingRows(routes, missing, search='') {
  const present = missing === 'cad' ? 'hastus' : 'clevercad';
  const absent = missing === 'cad' ? 'clevercad' : 'hastus';
  const rows = [];
  for (const route of routes) {
    const catalog = new Map((route[`${present}_variations`] || []).map(item => [item.variation_id,item]));
    for (const pair of route.variation_pairs || []) {
      if (pair.status !== 'not_comparable' || pair[`${absent}_variation_id`] || !pair[`${present}_variation_id`]) continue;
      const variation = catalog.get(pair[`${present}_variation_id`]);
      if (!variation) continue;
      const searchable=[route.route_short_name,variation.variation_id,variation.headsigns,variation.shape_ids,variation.direction_ids,variation.first_time,variation.last_time,variation.trip_ids,pair.reason];
      if (!JSON.stringify(searchable).toLowerCase().includes(search.toLowerCase())) continue;
      rows.push({route,pair,variation});
    }
  }
  return rows.sort((a,b)=>String(a.route.route_short_name).localeCompare(String(b.route.route_short_name),undefined,{numeric:true,sensitivity:'base'}));
}

function renderMissingReports() {
  for (const missing of ['cad','hastus']) renderMissingReport(missing);
  missingRequest++;
  if (missingDialog.open) missingDialog.close();
}

function renderMissingReport(missing) {
  const search = document.querySelector(`#missing-${missing}-search`).value.trim();
  const params=new URLSearchParams({missing,search});
  document.querySelectorAll(`[data-export-missing="${missing}"]`).forEach(link=>{
    link.href=`/api/runs/${currentRunId}/missing-report.${link.dataset.format}?${params}`;
  });
  const rows = missingRows(routeHealthData,missing,search);
  const groups = new Map();
  for (const row of rows) {
    const number = row.route.route_short_name;
    if (!groups.has(number)) groups.set(number,[]);
    groups.get(number).push(row);
  }
  const source = missing === 'cad' ? 'HASTUS' : 'CleverCAD';
  document.querySelector(`#missing-${missing}-summary`).textContent = `${groups.size} affected routes · ${rows.length} unpaired variations · ${rows.reduce((total,row)=>total+row.variation.trip_count,0)} ${source} trips${search ? ' · Search applied; exports use the same search' : ''}. Exports include every listed variation, not just the open popup.`;
  document.querySelector(`#missing-${missing}-list`).innerHTML = [...groups].map(([number,items]) => `<section class="missing-route-group"><h4>Route ${escapeHtml(number)} <span>${items.length} unpaired variations</span></h4><p>${items[0].route.clevercad_variation_count} CAD / ${items[0].route.hastus_variation_count} HASTUS variations in this route${items[0].route.direction_alignment === 'reversed' ? ' · Direction IDs reversed between exports' : ''}</p><div class="comparison-table"><table><thead><tr><th>Variation / destination</th><th>Direction</th><th>Shapes</th><th>Stops / trips</th><th>Time span</th><th>Why flagged</th><th>Evidence</th></tr></thead><tbody>${items.map(({pair,variation})=>`<tr><td><strong>${escapeHtml(variation.variation_id)}</strong><br>${escapeHtml((variation.headsigns||[]).join(' / '))}</td><td>${escapeHtml((variation.direction_ids||[]).join(', '))}</td><td>${escapeHtml((variation.shape_ids||[]).join(', ') || 'No shape')}</td><td>${variation.stop_count} stops<br>${variation.trip_count} trips</td><td>${escapeHtml(variation.first_time)}–${escapeHtml(variation.last_time)}</td><td>${escapeHtml(pair.reason || 'No suitable counterpart paired')}</td><td><button type="button" data-view-missing="${missing}" data-route="${escapeHtml(number)}" data-variation="${escapeHtml(variation.variation_id)}">View</button></td></tr>`).join('')}</tbody></table></div></section>`).join('') || '<p class="missing-empty">No source-only variations match this report. Paired variations with other mismatches remain in Route variations.</p>';
}

function missingTripTable(detail, times=[]) {
  return `<div class="comparison-table"><table><thead><tr><th>Sequence</th><th>Stop ID / name</th><th>Arrival</th><th>Departure</th><th>Complete evidence</th></tr></thead><tbody>${detail.stops.map((stop,index)=>`<tr><td>${escapeHtml(stop.sequence)}</td><td>${escapeHtml(stop.source_stop_id)}<br><strong>${escapeHtml(stop.stop_name)}</strong></td><td>${escapeHtml(stop.arrival_time || '—')}</td><td>${escapeHtml(stop.departure_time || '—')}</td><td><details><summary>Stop & boarding attributes</summary>${sourceCard('Complete stops.txt record',stop.source_record || {})}${sourceCard('Complete stop_times.txt record',times[index] || stop)}</details></td></tr>`).join('')}</tbody></table></div>`;
}

async function inspectMissing(missing, route, variation, trip='', opener=null) {
  const request = ++missingRequest;
  if (opener) missingOpener=opener;
  const body = document.querySelector('#missing-dialog-body');
  document.querySelector('#missing-dialog-title').textContent = `Route ${route} · ${variation} · missing in ${missing === 'cad' ? 'CAD' : 'HASTUS'}`;
  body.innerHTML='<p role="status">Loading full variation evidence…</p>';
  if (!missingDialog.open) missingDialog.showModal();
  try {
    const params=new URLSearchParams({missing,route,variation,trip});
    const response=await fetch(`/api/runs/${currentRunId}/missing-detail?${params}`);
    const data=await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load variation');
    if (request!==missingRequest || !missingDialog.open) return;
    const item=data.summary.variation;
    body.innerHTML=`<p class="variation-error">${escapeHtml(data.disclaimer)}</p><p>${escapeHtml(data.summary.pair.reason)}</p><details><summary>Every available variation attribute</summary>${sourceCard('Source variation',Object.fromEntries(Object.entries(item).filter(([key])=>key!=='trip_ids')))}</details>${sourceCard('Complete route attributes',data.route)}<label>Inspect source trip (${data.trips.length})<select id="missing-trip-choice">${data.trips.map(record=>`<option value="${escapeHtml(record.trip_id)}" ${record.trip_id===data.detail.trip.trip_id ? 'selected' : ''}>${escapeHtml(record.trip_id)} · ${escapeHtml(record.trip_headsign)} · service ${escapeHtml(record.service_id)}</option>`).join('')}</select></label>${sourceCard('Complete trip attributes',data.detail.trip)}<details><summary>Calendar and exceptions for this trip</summary><pre>${escapeHtml(JSON.stringify(data.services,null,2))}</pre></details>${renderShapeMap(data.detail)}<h3>Full source stop sequence — no stops hidden</h3>${missingTripTable(data.detail,data.stop_times)}<details><summary>All trips belonging to this variation (${data.trips.length})</summary><pre>${escapeHtml(JSON.stringify(data.trips,null,2))}</pre></details><div id="missing-final-evidence"></div>`;
    document.querySelector('#missing-trip-choice').addEventListener('change',event=>inspectMissing(missing,route,variation,event.target.value));
    const finalPatterns=data.summary.pair.final_matches || [];
    if (finalPatterns.length) {
      const container=document.querySelector('#missing-final-evidence');
      container.innerHTML=`<h3>Optional final GTFS evidence</h3><p>These final patterns match the source stop pattern; this does not establish timetable equality or vendor intent.</p><label>Final pattern<select id="missing-final-choice"><option value="">Choose final pattern</option>${finalPatterns.map(item=>`<option value="${escapeHtml(item.example_trip_id)}">${escapeHtml(item.variation_id)} · ${item.trip_count} trips · ${escapeHtml(item.matches_source)}</option>`).join('')}</select></label><div id="missing-final-trip"></div>`;
      document.querySelector('#missing-final-choice').addEventListener('change',async event=>{
        const target=document.querySelector('#missing-final-trip');const id=event.target.value;
        target.innerHTML=id ? '<p>Loading final representative trip…</p>' : '';
        if (!id)return;
        try {
          const res=await fetch(`/api/runs/${currentRunId}/viewer?${new URLSearchParams({source:'final',trip_id:id})}`);const detail=await res.json();
          if (!res.ok)throw new Error(detail.error);
          if (request!==missingRequest || !missingDialog.open || event.target.value!==id)return;
          target.innerHTML=sourceCard('Final representative trip — all attributes',detail.trip)+renderShapeMap(detail)+missingTripTable(detail);
        } catch(error) {if (request===missingRequest)target.innerHTML=`<p>${escapeHtml(error.message)}</p>`;}
      });
    }
  } catch(error) {
    if (request===missingRequest && missingDialog.open)body.innerHTML=`<p class="variation-error">${escapeHtml(error.message)}</p>`;
  }
}

for (const missing of ['cad','hastus']) {
  document.querySelector(`#missing-${missing}-search`).addEventListener('input',()=>renderMissingReport(missing));
  document.querySelector(`#missing-${missing}-list`).addEventListener('click',event=>{
    const button=event.target.closest('[data-view-missing]');
    if (button)inspectMissing(missing,button.dataset.route,button.dataset.variation,'',button);
  });
}
document.querySelector('#missing-dialog-close').addEventListener('click',()=>missingDialog.close());
missingDialog.addEventListener('close',()=>{missingRequest++;missingOpener?.focus({preventScroll:true});});
