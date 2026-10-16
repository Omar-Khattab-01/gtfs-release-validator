let inspectionData={};
let inspectionComparisons={};
let inspectionSource='hastus';
let inspectionEvidenceRequest=0;
let inspectionFindingLimit=100;
let inspectionOpener=null;
const inspectionDialog=document.querySelector('#inspection-dialog');
const inspectionLabels={cad:'CleverCAD',hastus:'HASTUS bus',rail:'HASTUS rail',final:'Final merged GTFS'};

function renderIndividualFeeds(report) {
  inspectionData=report.stats?.individual_feeds || {};
  inspectionComparisons=report.stats?.source_final || {};
  const workflow=report.stats?.workflow || {};
  const paired=workflow.bus_comparison==='complete';
  const both=inspectionData.cad && inspectionData.hastus;
  document.querySelector('#inspection-workflow').textContent=`${Object.keys(inspectionData).length} exports supplied · Bus comparison: ${paired ? 'available' : both ? 'Unavailable — check source findings' : 'Not available — supply CAD and HASTUS bus'} · Final merged GTFS: ${workflow.final==='supplied' ? 'supplied' : 'Not supplied'}. Individual inspection does not require another export.`;
  for (const view of ['routes','stops','missing-cad','missing-hastus']) document.querySelector(`.workspace-tab[data-view="${view}"]`).disabled=!paired;
  document.querySelector('.workspace-tab[data-view="rail"]').disabled=!inspectionData.rail;
  if (!inspectionData[inspectionSource])inspectionSource=['hastus','rail','cad','final'].find(source=>inspectionData[source]) || 'hastus';
  inspectionEvidenceRequest++;
  if (inspectionDialog.open)inspectionDialog.close();
  renderInspection();
  const active=document.querySelector('.workspace-tab.active');
  if (!paired || active?.disabled)document.querySelector('.workspace-tab[data-view="inspection"]').click();
}

function inspectionSearch(value) {
  return JSON.stringify(value).toLowerCase().includes(document.querySelector('#inspection-search').value.trim().toLowerCase());
}

function renderInspection() {
  document.querySelector('#inspection-sources').innerHTML=Object.entries(inspectionLabels).map(([source,label])=>{
    const data=inspectionData[source];const counts=data?.validation?.counts || {};
    const issues=(counts.blocker||0)+(counts.error||0)+(counts.warning||0);
    return `<button type="button" class="route-card ${data ? issues || data.status!=='complete' ? 'issues' : 'healthy' : 'not_comparable'} ${source===inspectionSource ? 'active' : ''}" data-inspection-source="${source}" ${data ? '' : 'disabled'}><strong>${escapeHtml(label)}</strong><span>${!data ? 'Not supplied' : `${data.inventory?.routes || 0} routes · ${data.inventory?.trips || 0} trips · ${issues} findings${data.status!=='complete' ? ' · Inspection incomplete' : ''}`}</span></button>`;
  }).join('');
  const data=inspectionData[inspectionSource];const target=document.querySelector('#inspection-content');
  if (!data) {target.innerHTML='<p>No export supplied for inspection.</p>';return;}
  const view=document.querySelector('#inspection-section').value;
  const validation=data.validation || {counts:{},findings:[]};
  const counts=Object.entries(validation.counts || {}).map(([key,value])=>`${value} ${key}`).join(' · ');
  const heading=`<h4>${escapeHtml(inspectionLabels[inspectionSource])}</h4><p>${escapeHtml(data.path)}</p><p>${escapeHtml(counts)}${data.status!=='complete' ? ' · '+escapeHtml(data.message || data.status) : ''}</p><a href="/api/runs/${currentRunId}/inspection-report.json?source=${inspectionSource}" download>Download this feed’s inspection (JSON)</a>`;
  if (view==='overview') {
    const inventory=data.inventory || {};
    const categories={};
    for (const finding of validation.findings || [])categories[finding.category]=(categories[finding.category] || 0)+1;
    target.innerHTML=heading+`<div class="metric-grid">${Object.entries(inventory).map(([name,value])=>`<div class="metric"><strong>${value}</strong><span>${escapeHtml(name.replaceAll('_',' '))}</span></div>`).join('')}</div><p>Inspection status: ${escapeHtml(data.status)} · ${data.files.filter(file=>file.present!==false).length} archive members</p><p>${Object.entries(categories).map(([name,value])=>`${value} ${escapeHtml(name)}`).join(' · ')}</p><p>Technical findings, agency review items and content-scope checks are listed separately by category. Optional destination and shape fields are review items, not GTFS required-field errors.</p><p>${validation.suppressed_findings ? `${validation.suppressed_findings} additional findings were suppressed by the evidence limit.` : ''}</p><button type="button" data-inspection-section="files">Inspect all files</button> <button type="button" data-inspection-section="routes">Inspect routes and variations</button> <button type="button" data-inspection-section="findings">Review findings</button><p>Use an approved expected-service list or prior export to establish whether entire routes or variations were omitted.</p>`;
  } else if (view==='files') {
    const files=data.files.filter(file=>inspectionSearch(file.name));
    target.innerHTML=heading+`<div class="comparison-table"><table><thead><tr><th>File</th><th>Records</th><th>Columns</th><th>Bytes</th><th>Checks</th><th>Findings</th><th>Inspect</th></tr></thead><tbody>${files.map(file=>`<tr><td>${escapeHtml(file.name)}${file.present===false ? '<br><strong>Not supplied</strong>' : ''}</td><td>${file.rows ?? 'Unavailable'}</td><td><details><summary>${file.columns.length} columns</summary>${escapeHtml(file.columns.join(', '))}</details></td><td>${file.bytes}</td><td>${escapeHtml(file.check_coverage)}</td><td>${file.finding_indices.length}</td><td>${file.columns.length ? `<button type="button" data-inspection-file="${escapeHtml(file.name)}">Open table</button>` : 'No parsed table'}</td></tr>`).join('')}</tbody></table></div>`;
  } else if (view==='routes') {
    const routes=data.routes.filter(item=>inspectionSearch(item.route)).sort((a,b)=>String(a.route.route_short_name || a.route.route_id).localeCompare(String(b.route.route_short_name || b.route.route_id),undefined,{numeric:true}));
    target.innerHTML=heading+`<p>${data.unassigned_findings || 0} feed-level findings are not assigned to a route. Route status covers route-specific findings; check File health and Findings too.</p><div class="comparison-table"><table><thead><tr><th>Route</th><th>Type</th><th>Trips / shapes</th><th>Direction</th><th>Route checks</th><th>Inspect</th></tr></thead><tbody>${routes.map(item=>`<tr><td><strong>${escapeHtml(item.route.route_short_name || item.route.route_id)}</strong><br>${escapeHtml(item.route.route_long_name || '')}</td><td>${escapeHtml(item.route.route_type)}</td><td>${item.trip_count} trips · ${item.shape_count} shapes</td><td>${escapeHtml(item.direction_ids.join(', '))}</td><td>${item.status==='needs_review' ? 'Needs review' : 'No route-specific findings'} · ${item.finding_indices.length} findings</td><td><button type="button" data-inspection-route="${escapeHtml(item.route.route_id)}">Variations & trips</button> <button type="button" data-inspection-route-findings="${escapeHtml(item.route.route_id)}">Findings</button></td></tr>`).join('')}</tbody></table></div>`;
  } else if (view==='findings') {
    const level=document.querySelector('#inspection-level').value;
    const findings=(validation.findings || []).map((finding,index)=>({finding,index})).filter(({finding})=>(!level || finding.severity===level) && inspectionSearch(finding));
    target.innerHTML=heading+`<p>${findings.length} matching findings${validation.suppressed_findings ? ` · ${validation.suppressed_findings} further findings suppressed` : ''}</p>${findings.slice(0,inspectionFindingLimit).map(({finding,index})=>`<article class="validation-file"><span class="pill ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span> ${escapeHtml(finding.category)} · ${escapeHtml(finding.rule_id)}<h4>${escapeHtml(finding.title)}</h4><p>${escapeHtml(finding.message)}</p><p>${escapeHtml(finding.file || '')}${finding.row ? ' · CSV record '+finding.row : ''} · ${escapeHtml(finding.key || '')}</p><button type="button" data-inspection-finding="${index}">View evidence</button></article>`).join('') || '<p>No findings match these filters.</p>'}${findings.length>inspectionFindingLimit ? '<button type="button" data-inspection-more>Show more findings</button>' : ''}`;
  } else if (view==='comparison') {
    const comparison=inspectionComparisons[inspectionSource];
    if (!inspectionData.final)target.innerHTML=heading+'<p>Final merged GTFS: Not supplied. Individual checks are available now.</p>';
    else if (inspectionSource==='final')target.innerHTML=heading+'<p>This is the final feed. Select a source to review its final comparison, or open Final GTFS validation.</p>';
    else if (inspectionSource==='rail')target.innerHTML=heading+'<button type="button" data-inspection-open-tab="rail">Open rail → final comparison</button>';
    else if (!comparison)target.innerHTML=heading+'<button type="button" data-inspection-open-tab="routes">Open CAD / HASTUS / final variation comparison</button>';
    else if (comparison.status!=='complete')target.innerHTML=heading+`<p>Comparison ${escapeHtml(comparison.status)}: ${escapeHtml(comparison.message)}</p>`;
    else target.innerHTML=heading+`<p>Final coverage: ${escapeHtml(comparison.coverage_window?.join(' to ') || 'Unverifiable')} · ${escapeHtml(JSON.stringify(comparison.counts))}</p>`+comparison.routes.filter(route=>inspectionSearch(route)).map(route=>`<section class="validation-file"><h4>Route ${escapeHtml(route.route_short_name)} · ${escapeHtml(route.status.replaceAll('_',' '))}</h4><p>${escapeHtml(JSON.stringify(route.counts))}</p><p>Route attribute changes: ${escapeHtml((route.route_attribute_changes || []).map(item=>item.fields.join(', ')).join('; ') || 'None')} · ${route.stop_difference_count || 0} stops with missing or changed attributes</p><details><summary>Stop attribute evidence (up to 200)</summary>${(route.stop_difference_examples || []).map(item=>`<h5>${escapeHtml(item.source_stop_id)} · ${escapeHtml(item.fields.join(', '))}</h5><div class="source-grid">${sourceCard(inspectionLabels[inspectionSource],item.source)}${sourceCard('Final merged GTFS',item.final || {})}</div>`).join('')}</details>${route.route_ids.map(id=>`<button type="button" data-inspection-route="${escapeHtml(id)}">Inspect source route</button>`).join('')} ${route.final_route_ids.map(id=>`<button type="button" data-inspection-final-route="${escapeHtml(id)}">Inspect final route</button>`).join('')}<details><summary>Trip evidence (${route.examples.length} shown; up to ${route.example_limit})</summary>${route.examples.map(item=>`<p>${escapeHtml(item.trip_id)} · ${escapeHtml(item.status)} · ${escapeHtml(item.issues.join('; '))}</p><button type="button" data-inspection-trip="${escapeHtml(item.trip_id)}">Open source trip</button>${item.final_trip_ids.map(id=>`<button type="button" data-inspection-final-trip="${escapeHtml(id)}">Open final trip ${escapeHtml(id)}</button>`).join('')}`).join('')}</details></section>`).join('');
  }
}

async function inspectionOpenViewer(source, {file='',row=0,route='',trip=''}={}) {
  inspectionDialog.close();
  document.querySelector('#viewer-source').value=source;
  await loadViewer();
  document.querySelector('.workspace-tab[data-view="viewer"]').click();
  if (trip)await openViewerTrip(trip);
  else if (route)await openViewerRoute(route);
  else if (file) {
    document.querySelector('#viewer-table').value=file;
    const offset=row>=2 ? Math.floor((row-2)/100)*100 : 0;
    await openViewerTable(offset);
    if (row>=2)document.querySelectorAll('#viewer-content tbody tr')[row-2-offset]?.classList.add('evidence-row');
  }
}

async function openInspectionFinding(index,opener=null) {
  const finding=inspectionData[inspectionSource]?.validation?.findings[index];
  if (!finding)return;
  const source=inspectionSource;const request=++inspectionEvidenceRequest;
  inspectionOpener=opener;
  const body=document.querySelector('#inspection-dialog-body');
  document.querySelector('#inspection-dialog-title').textContent=`${inspectionLabels[source]} · ${finding.title}`;
  const hasRow=Number.isInteger(finding.row) && finding.row>=2 && finding.file;
  body.innerHTML=`<p>${escapeHtml(finding.severity)} · ${escapeHtml(finding.category)} · ${escapeHtml(finding.rule_id)}</p><p>${escapeHtml(finding.message)}</p><pre>${escapeHtml(JSON.stringify(finding.context || {},null,2))}</pre>${hasRow ? '<p id="inspection-record-status">Loading affected record…</p>' : ''}`;
  if (!inspectionDialog.open)inspectionDialog.showModal();
  if (hasRow) {
    try {
      const response=await fetch(`/api/runs/${currentRunId}/inspection-row?${new URLSearchParams({source,file:finding.file,row:finding.row})}`);
      const data=await response.json();
      if (!response.ok)throw new Error(data.error);
      if (request!==inspectionEvidenceRequest || !inspectionDialog.open)return;
      body.innerHTML+=sourceCard(`${finding.file} · CSV record ${finding.row}`,data.record);
    } catch(error) {if (request===inspectionEvidenceRequest)body.innerHTML+=`<p>Record unavailable: ${escapeHtml(error.message)}</p>`;}
    finally {if (request===inspectionEvidenceRequest)document.querySelector('#inspection-record-status')?.remove();}
  }
  if (request!==inspectionEvidenceRequest || !inspectionDialog.open)return;
  if (finding.file && inspectionData[source].files.some(file=>file.name===finding.file && file.columns.length))body.innerHTML+=`<button type="button" data-inspection-file="${escapeHtml(finding.file)}" data-row="${finding.row || 0}">Open file table</button>`;
  if (finding.context?.route_id)body.innerHTML+=`<button type="button" data-inspection-route="${escapeHtml(finding.context.route_id)}">Inspect route variations & trips</button>`;
}

function inspectionAction(event) {
  const button=event.target.closest('button');if (!button)return;
  if (button.dataset.inspectionSource) {inspectionSource=button.dataset.inspectionSource;inspectionFindingLimit=100;renderInspection();}
  else if (button.dataset.inspectionSection) {document.querySelector('#inspection-section').value=button.dataset.inspectionSection;renderInspection();}
  else if (button.dataset.inspectionFinding!==undefined)openInspectionFinding(Number(button.dataset.inspectionFinding),button);
  else if (button.dataset.inspectionMore!==undefined) {inspectionFindingLimit+=100;renderInspection();}
  else if (button.dataset.inspectionFile)inspectionOpenViewer(inspectionSource,{file:button.dataset.inspectionFile,row:Number(button.dataset.row || 0)});
  else if (button.dataset.inspectionRoute)inspectionOpenViewer(inspectionSource,{route:button.dataset.inspectionRoute});
  else if (button.dataset.inspectionFinalRoute)inspectionOpenViewer('final',{route:button.dataset.inspectionFinalRoute});
  else if (button.dataset.inspectionTrip)inspectionOpenViewer(inspectionSource,{trip:button.dataset.inspectionTrip});
  else if (button.dataset.inspectionFinalTrip)inspectionOpenViewer('final',{trip:button.dataset.inspectionFinalTrip});
  else if (button.dataset.inspectionRouteFindings) {document.querySelector('#inspection-section').value='findings';document.querySelector('#inspection-search').value=button.dataset.inspectionRouteFindings;renderInspection();}
  else if (button.dataset.inspectionOpenTab)document.querySelector(`.workspace-tab[data-view="${button.dataset.inspectionOpenTab}"]`).click();
}
document.querySelector('#inspection-view').addEventListener('click',inspectionAction);
document.querySelector('#inspection-dialog-body').addEventListener('click',inspectionAction);
for (const control of ['inspection-section','inspection-level'])document.querySelector('#'+control).addEventListener('change',()=>{inspectionFindingLimit=100;renderInspection();});
document.querySelector('#inspection-search').addEventListener('input',()=>{inspectionFindingLimit=100;renderInspection();});
document.querySelector('#inspection-dialog-close').addEventListener('click',()=>inspectionDialog.close());
inspectionDialog.addEventListener('close',()=>{inspectionEvidenceRequest++;inspectionOpener?.focus({preventScroll:true});});
