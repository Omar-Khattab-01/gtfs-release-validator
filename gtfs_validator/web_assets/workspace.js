const settingsDialog = document.querySelector('#settings-dialog');
const settingFields = ['save-indexes','run-agency','run-mobility','mobility-jar','sort-reference'];
try {
  const saved = JSON.parse(localStorage.getItem('gtfs.validator.settings.v1') || '{}');
  for (const id of settingFields) {
    const field = document.getElementById(id);
    if (field.type === 'checkbox' && typeof saved[id] === 'boolean') field.checked = saved[id];
    else if (typeof saved[id] === 'string') field.value = saved[id];
  }
} catch (_) {}
document.querySelector('#open-settings').addEventListener('click', () => settingsDialog.showModal());
document.querySelector('#toggle-files').addEventListener('click', () => {
  const collapsed=document.querySelector('#setup-panel').classList.toggle('collapsed');
  document.querySelector('#toggle-files').textContent=collapsed?'Change files':'Hide files';
});
document.querySelector('#close-settings').addEventListener('click', () => settingsDialog.close());
settingsDialog.addEventListener('change', () => {
  try { localStorage.setItem('gtfs.validator.settings.v1',JSON.stringify(Object.fromEntries(settingFields.map(id => {
    const field = document.getElementById(id); return [id,field.type === 'checkbox' ? field.checked : field.value];
  })))); } catch (_) {}
});
for (const [id,kind] of [['mobility-jar','jar'],['sort-reference','csv']]) {
  const input = document.getElementById(id);
  const button = document.createElement('button');
  button.type='button'; button.className='button secondary';button.textContent='Browse…';
  button.dataset.browse=id;button.dataset.kind=kind;
  const wrapper=document.createElement('span');wrapper.className='file-input';
  input.replaceWith(wrapper);wrapper.append(input,button);
}
let pickingFile = false;
document.addEventListener('click',async event => {
  const button=event.target.closest('[data-browse]');if (!button || pickingFile)return;
  pickingFile=true;button.disabled=true;
  const status=document.querySelector('#file-input-status');status.textContent='Choose a file in the file browser…';
  try {
    const response=await fetch('/api/pick-file',{method:'POST',headers:{'Content-Type':'application/json','X-GTFS-Validator':'1'},body:JSON.stringify({kind:button.dataset.kind})});
    const data=await response.json();if (!response.ok)throw new Error(data.error);
    if (data.path) {
      const input=document.getElementById(button.dataset.browse);input.value=data.path;
      input.dispatchEvent(new Event('change',{bubbles:true}));
    }
    status.textContent='';
  } catch(error) {status.textContent=error.message;document.querySelector('#settings-status').textContent=error.message;}
  finally {pickingFile=false;button.disabled=false;}
});

function updateRunProgress(payload) {
  document.querySelector('#run-progress').textContent=payload.progress || 'Preparing files…';
  const percent=Math.max(0,Math.min(100,Number(payload.progress_percent)||0));
  const bar=document.querySelector('#run-progress-bar');bar.style.width=percent+'%';
  bar.setAttribute('aria-valuenow',String(percent));
  const elapsed=Math.max(0,Math.floor(payload.elapsed_seconds || 0));
  document.querySelector('#run-time').textContent=`${percent}% · ${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,'0')} elapsed`;
}

let packagingRequest=0;
async function loadPackaging(extract=false) {
  const request=++packagingRequest;
  const source=document.querySelector('#packaging-source').value;
  const target=document.querySelector('#packaging');
  if (!source)return;
  target.textContent=extract ? 'Extracting a temporary copy and checking the files…' : 'Reading ZIP metadata…';
  try {
    const response=await fetch(`/api/runs/${currentRunId}/packaging?${new URLSearchParams({source,extract:extract?'1':'0'})}`,{cache:'no-store'});
    const data=await response.json();if (!response.ok)throw new Error(data.error);
    if (request!==packagingRequest)return;
    const archiveIssues=(inspectionData[source]?.validation?.findings||[]).filter(item=>item.rule_id.startsWith('PKG')&&!['PKG009','PKG016','PKG018'].includes(item.rule_id));
    const notices=archiveIssues.length?`<details class="validation-file"><summary>Archive checks · ${archiveIssues.length} items</summary><div class="review-list">${archiveIssues.map(item=>`<article class="review-row"><span class="pill ${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.message)}</p><small>${escapeHtml(item.file||'')}</small></div></article>`).join('')}</div></details>`:'';
    target.innerHTML=`${notices}<p>${data.files.length} members · <strong>${data.flagged_count} stored as 0600</strong></p><p class="field-help">Stored ZIP permissions and extracted permissions are separate. Missing Unix metadata is accepted. Only a stored mode of 0600 is flagged here.</p><button type="button" class="button secondary" id="test-extraction">${data.extraction_tested?'Run extraction again':'Test extraction'}</button>${data.extraction_tested ? `<p role="status">Extraction completed.${data.posix_permissions ? '' : ' Windows uses file attributes; Unix mode 0600 is checked in the ZIP metadata.'}</p>` : ''}<div class="table-wrap"><table><thead><tr><th>File</th><th>Bytes</th><th>Stored ZIP mode</th><th>Extracted mode</th><th>Permission check</th></tr></thead><tbody>${data.files.map(file=>`<tr class="${file.flagged?'evidence-row':''}"><td>${escapeHtml(file.file)}</td><td>${formatBytes(file.bytes)}</td><td>${escapeHtml(file.stored_mode || 'Not stored')}</td><td>${escapeHtml(file.extracted_mode || (data.extraction_tested && !data.posix_permissions ? 'Windows attributes' : 'Not tested'))}</td><td>${file.flagged?'<span class="pill error">0600 — review</span>':'OK'}</td></tr>`).join('')}</tbody></table></div>`;
    document.querySelector('#test-extraction').addEventListener('click',()=>loadPackaging(true));
  } catch(error) {if(request===packagingRequest)target.textContent=error.message;}
}
document.querySelector('#packaging-source').addEventListener('change',()=>loadPackaging());
document.querySelector('#inspection-reset').addEventListener('click',()=>{
  for (const id of ['inspection-search','inspection-level','inspection-rule'])document.getElementById(id).value='';
  inspectionFindingLimit=25;renderInspection();
});

let finalPayload=null;
let finalEngine='mobility';
let finalLevel='';
let finalFile='';
let finalSearch='';
let finalPage=0;
function finalItems(engine,data) {
  if (engine==='mobility')return (data.notices||[]).map(item=>({level:item.severity.toLowerCase(),title:item.code,message:`${item.totalNotices} occurrences`,notice:item,file:(item.sampleNotices||[])[0]?.filename || ''}));
  if (engine==='agency')return (data.files||[]).flatMap(file=>['errors','warnings','info'].flatMap(level=>(file[level]||[]).map(item=>({...item,level:{errors:'error',warnings:'warning',info:'info'}[level],title:file.file,file:file.file}))));
  return (data.findings||[]).filter(item=>!item.rule_id.startsWith('PKG')).map(item=>({...item,level:item.severity,title:item.title || item.rule_id}));
}
function agencyFileState(file) {
  const counts=Object.fromEntries(['errors','warnings','info'].map(level=>[level,Number(file.counts?.[level]??file[level]?.length??0)]));
  const state=counts.errors || file.status==='FAIL' ? 'error' : counts.warnings || file.status==='PASS WITH WARNINGS' ? 'warning' : ['PASS','complete'].includes(file.status) ? 'clear' : 'unchecked';
  const label={error:'Error',warning:'Warning',clear:'Clear',unchecked:'Not checked'}[state];
  return {counts,state,label};
}
function finalNavigation(data) {
  const statuses={complete:'Complete',not_requested:'Not run',unavailable:'Unavailable',failed:'Failed'};
  return `<nav class="inspection-nav" aria-label="Validation engine">${[['mobility','MobilityData'],['agency','OC Transpo'],['technical','GTFS checks']].map(([key,label])=>`<button type="button" class="button secondary ${key===finalEngine?'active':''}" data-final-engine="${key}">${label}</button>`).join('')}</nav><p>${escapeHtml(statuses[data.status]||data.status)}${data.message?' · '+escapeHtml(data.message):''}</p>`;
}
function wireFinalNavigation(target) {
  target.querySelectorAll('[data-final-engine]').forEach(button=>button.addEventListener('click',()=>{
    finalEngine=button.dataset.finalEngine;finalLevel='';finalFile='';finalSearch='';finalPage=0;renderFinalReview();
  }));
}
function openAgencyFile(name) {
  const file=finalPayload?.final_validation?.agency?.files?.find(item=>item.file===name);
  if(!file)return;
  const {state}=agencyFileState(file);
  finalFile=name;finalLevel=state==='error'?'error':state==='warning'?'warning':'';
  finalSearch='';finalPage=0;renderFinalReview();
}
function renderAgencyFiles(target,data) {
  const rank={error:0,warning:1,unchecked:2,clear:3};
  const files=(data.files||[]).filter(file=>!finalSearch||file.file.toLowerCase().includes(finalSearch.toLowerCase()))
    .map(file=>({...file,...agencyFileState(file)})).sort((a,b)=>rank[a.state]-rank[b.state]||a.file.localeCompare(b.file));
  target.innerHTML=finalNavigation(data)+`<div class="agency-file-toolbar"><p>${(data.files||[]).length} files · ${Number(data.counts?.errors||0)} errors · ${Number(data.counts?.warnings||0)} warnings</p><label>Find a file<input id="agency-file-search" type="search" value="${escapeHtml(finalSearch)}" placeholder="File name"></label></div><div class="agency-file-grid">${files.map(file=>`<button type="button" class="agency-file-card ${file.state}" data-agency-file="${escapeHtml(file.file)}"><span class="file-status ${file.state}">${file.label}</span><strong>${escapeHtml(file.file)}</strong><span class="file-counts">${file.counts.errors} errors · ${file.counts.warnings} warnings · ${file.counts.info} info</span><span class="file-action">${file.state==='clear'?'View details':'View findings'} →</span></button>`).join('')||'<p>No files match this search.</p>'}</div><div class="actions"><a href="/api/runs/${finalPayload.id}/final-validation.json" download>Export validation JSON</a></div>`;
  wireFinalNavigation(target);
  target.querySelectorAll('[data-agency-file]').forEach(button=>button.addEventListener('click',()=>openAgencyFile(button.dataset.agencyFile)));
  document.querySelector('#agency-file-search').addEventListener('input',event=>{
    finalSearch=event.target.value;renderFinalReview();const input=document.querySelector('#agency-file-search');input.focus();input.setSelectionRange(finalSearch.length,finalSearch.length);
  });
}
function renderFinalValidation(payload) {finalPayload=payload;finalPage=0;finalEngine='mobility';finalFile='';finalLevel='';finalSearch='';renderFinalReview();}
function renderFinalReview() {
  const target=document.querySelector('#final-content');
  const validation=finalPayload?.final_validation;
  if(!validation){target.innerHTML='<p>Add a final GTFS export to run validation.</p>';return;}
  const data=validation[finalEngine]||{status:'not_requested'};
  const rank={blocker:0,error:1,warning:2,info:3};
  const items=finalItems(finalEngine,data).sort((a,b)=>(rank[a.level]??4)-(rank[b.level]??4));
  const files=finalEngine==='agency'?(data.files||[]).map(file=>file.file).sort():[...new Set(items.map(item=>item.file).filter(Boolean))].sort();
  if(!files.includes(finalFile))finalFile='';
  if(finalEngine==='agency'&&!finalFile){renderAgencyFiles(target,data);return;}
  const selectedFile=finalEngine==='agency'?(data.files||[]).find(file=>file.file===finalFile):null;
  const scopedItems=items.filter(item=>!finalFile||item.file===finalFile);
  const filtered=scopedItems.filter(item=>(!finalLevel||item.level===finalLevel)&&(!finalSearch||`${item.title} ${item.message} ${item.file}`.toLowerCase().includes(finalSearch.toLowerCase())));
  finalPage=Math.max(0,Math.min(finalPage,Math.ceil(filtered.length/20)-1));
  const counts=selectedFile?agencyFileState(selectedFile).counts:data.counts||{};
  const sampled=finalEngine==='agency'&&Object.values(counts).reduce((sum,value)=>sum+Number(value||0),0)>scopedItems.length;
  const heading=selectedFile?`<div class="agency-file-heading"><button class="button secondary" type="button" id="agency-all-files">← All files</button><h4>${escapeHtml(selectedFile.file)}</h4><span class="file-status ${agencyFileState(selectedFile).state}">${agencyFileState(selectedFile).label}</span></div>`:'';
  target.innerHTML=finalNavigation(data)+heading+`<div class="missing-toolbar"><label>Level<select id="final-level"><option value="">All levels</option>${['blocker','error','warning','info'].map(level=>`<option value="${level}" ${finalLevel===level?'selected':''}>${level} (${scopedItems.filter(item=>item.level===level).length}${finalEngine==='mobility'?' types':''})</option>`).join('')}</select></label><label>File<select id="final-file"><option value="">All files</option>${files.map(file=>`<option ${finalFile===file?'selected':''}>${escapeHtml(file)}</option>`).join('')}</select></label><label>Search<input id="final-search" type="search" value="${escapeHtml(finalSearch)}" placeholder="Notice, file or message"></label></div><p>${filtered.length} matching ${finalEngine==='mobility'?'notice types':'items'} · ${Object.entries(counts).map(([key,value])=>`${value} ${escapeHtml(key.toLowerCase())}`).join(' · ')}</p>${sampled?'<p class="field-help">The list contains retained examples. Counts include all findings.</p>':''}<div class="pager"><button type="button" class="button secondary" id="final-prev" ${finalPage===0?'disabled':''}>Previous</button><span>Page ${finalPage+1} of ${Math.max(1,Math.ceil(filtered.length/20))}</span><button type="button" class="button secondary" id="final-next" ${(finalPage+1)*20>=filtered.length?'disabled':''}>Next</button></div><div class="review-list">${filtered.slice(finalPage*20,finalPage*20+20).map((item,index)=>`<article class="review-row"><span class="pill ${escapeHtml(item.level)}">${escapeHtml(item.level)}</span><div><strong>${escapeHtml(finalEngine==='agency'?(item.field||(item.row?'CSV row '+item.row:'File check')):item.title)}</strong><p>${escapeHtml(item.message)}</p>${item.row&&finalEngine!=='agency'?`<small>CSV row ${escapeHtml(item.row)}</small>`:''}</div><button type="button" class="button secondary" data-final-item="${finalPage*20+index}">View evidence</button></article>`).join('')||'<p>No items match these filters.</p>'}</div><div class="actions"><a href="/api/runs/${finalPayload.id}/final-validation.json" download>Export validation JSON</a>${finalEngine==='mobility'&&data.status==='complete'?`<a href="/api/runs/${finalPayload.id}/mobility-report.html" download>Export MobilityData report</a>`:''}</div>`;
  wireFinalNavigation(target);
  document.querySelector('#agency-all-files')?.addEventListener('click',()=>{finalFile='';finalLevel='';finalSearch='';finalPage=0;renderFinalReview();});
  document.querySelector('#final-level').addEventListener('change',event=>{finalLevel=event.target.value;finalPage=0;renderFinalReview();});
  document.querySelector('#final-file').addEventListener('change',event=>{finalFile=event.target.value;finalLevel='';finalSearch='';finalPage=0;renderFinalReview();});
  document.querySelector('#final-search').addEventListener('input',event=>{finalSearch=event.target.value;finalPage=0;renderFinalReview();const input=document.querySelector('#final-search');input.focus();input.setSelectionRange(finalSearch.length,finalSearch.length);});
  document.querySelector('#final-prev').addEventListener('click',()=>{finalPage--;renderFinalReview();});
  document.querySelector('#final-next').addEventListener('click',()=>{finalPage++;renderFinalReview();});
  target.querySelectorAll('[data-final-item]').forEach(button=>button.addEventListener('click',()=>{
    const item=filtered[Number(button.dataset.finalItem)];
    if(item.file&&item.row>=2)openEvidence('final',{file:item.file,row:Number(item.row),field:item.field},button);
    else openValidationEvidence(item,button);
  }));
}


document.querySelector('#metrics').addEventListener('click',event=>{
  const metric=event.target.closest('[data-finding-level]');if(!metric)return;
  const level=metric.dataset.findingLevel;
  const regular=activeFindings.some(item=>item.severity===level&&!item.rule_id.startsWith('PKG'));
  const packagingSource=Object.entries(inspectionData).find(([,feed])=>feed.validation?.findings.some(item=>item.severity===level&&item.rule_id.startsWith('PKG')))?.[0];
  if(!regular&&packagingSource){document.querySelector('#packaging-source').value=packagingSource;document.querySelector('[data-view="packaging"]').click();}
  else {severityFilter.value=level;renderFindings();document.querySelector('[data-view="findings"]').click();}
});
