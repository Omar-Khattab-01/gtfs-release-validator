const evidenceDialog=document.querySelector('#evidence-dialog');
const evidenceBody=document.querySelector('#evidence-body');
const evidenceHistory=[];
let evidenceRequest=0;
let evidenceOpener=null;
function beginEvidence(title,opener=null,push=true) {
  if(evidenceDialog.open&&push)evidenceHistory.push({title:document.querySelector('#evidence-title').textContent,nodes:[...evidenceBody.childNodes],scroll:evidenceBody.scrollTop});
  if(!evidenceDialog.open) {evidenceOpener=opener||document.activeElement;evidenceHistory.length=0;}
  document.querySelector('#evidence-title').textContent=title;
  evidenceBody.replaceChildren();evidenceBody.scrollTop=0;
  document.querySelector('#evidence-back').hidden=!evidenceHistory.length;
  if(!evidenceDialog.open)evidenceDialog.showModal();
  return ++evidenceRequest;
}
async function evidenceFetch(source,params={}) {
  const response=await fetch(`/api/runs/${currentRunId}/viewer?${new URLSearchParams({source,...params})}`,{cache:'no-store'});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Could not load evidence');return data;
}
async function openEvidence(source,options={},opener=null,push=true) {
  const {file='',row=0,field='',route='',trip='',offset}=options;
  const request=beginEvidence(`${inspectionLabels[source]||source} · ${trip?'Trip '+trip:route?'Route '+route:file||'Evidence'}`,opener,push);
  evidenceBody.textContent='Loading evidence…';
  try {
    const params=trip?{trip_id:trip}:route?{route_id:route}:{table:file,offset:offset??(row>=2?Math.floor((row-2)/100)*100:0)};
    const data=await evidenceFetch(source,params);
    if(request!==evidenceRequest||!evidenceDialog.open)return;
    if(trip) {
      evidenceBody.innerHTML=renderShapeMap(data)+sourceCard('Trip',data.trip)+`<div class="table-wrap"><table><thead><tr><th>Sequence</th><th>Stop</th><th>Arrival</th><th>Departure</th><th>Pickup / drop-off</th></tr></thead><tbody>${data.stops.map(stop=>`<tr><td>${escapeHtml(stop.sequence)}</td><td><details><summary>${escapeHtml(stop.stop_name)} · ${escapeHtml(stop.source_stop_id)}</summary>${sourceCard('Stop',stop.source_record)}</details></td><td>${escapeHtml(stop.arrival_time)}</td><td>${escapeHtml(stop.departure_time)}</td><td>${escapeHtml(stop.pickup_type)} / ${escapeHtml(stop.drop_off_type)}</td></tr>`).join('')}</tbody></table></div>`;
    } else if(route) {
      const variations=data.variations||[];
      evidenceBody.innerHTML=`<label>Variation<select id="evidence-variation">${variations.map((variation,index)=>`<option value="${index}">${escapeHtml(variation.variation_id)} · ${variation.stop_count} stops · ${variation.trip_count} trips · ${escapeHtml(variation.shape_ids.join(', '))}</option>`).join('')}</select></label><div id="evidence-route-trips"></div>`;
      const show=()=>{
        const variation=variations[Number(document.querySelector('#evidence-variation').value)];
        document.querySelector('#evidence-route-trips').innerHTML=variation?`<div class="table-wrap"><table><thead><tr><th>Trip</th><th>Destination</th><th>Times</th><th>Service</th><th></th></tr></thead><tbody>${variation.trips.map(item=>`<tr><td>${escapeHtml(item.trip_id)}</td><td>${escapeHtml(item.trip_headsign)}</td><td>${escapeHtml(item.first_time)}–${escapeHtml(item.last_time)}</td><td>${escapeHtml(item.service_id)}</td><td><button class="button secondary" data-evidence-source="${source}" data-evidence-trip="${escapeHtml(item.trip_id)}">View trip</button></td></tr>`).join('')}</tbody></table></div>`:'<p>No trips in this route.</p>';
      };
      document.querySelector('#evidence-variation').addEventListener('change',show);show();
    } else {
      const start=Number(params.offset);
      evidenceBody.innerHTML=`<p>CSV rows ${start+2}–${start+data.rows.length+1}</p><div class="table-wrap"><table><thead><tr><th>CSV row</th>${data.columns.map(column=>`<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${data.rows.map((record,index)=>`<tr class="${start+index+2===row?'evidence-row':''}"><td>${start+index+2}</td>${data.columns.map(column=>`<td class="${start+index+2===row&&column===field?'evidence-field':''}">${escapeHtml(record[column])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="pager"><button class="button secondary" data-evidence-source="${source}" data-evidence-file="${escapeHtml(file)}" data-evidence-offset="${Math.max(0,start-100)}" ${start===0?'disabled':''}>Previous rows</button><button class="button secondary" data-evidence-source="${source}" data-evidence-file="${escapeHtml(file)}" data-evidence-offset="${start+100}" ${data.rows.length<100?'disabled':''}>Next rows</button></div>`;
      evidenceBody.querySelector('.evidence-row')?.scrollIntoView({block:'center'});
    }
  } catch(error) {if(request===evidenceRequest)evidenceBody.textContent=error.message;}
}
function openValidationEvidence(item,opener) {
  beginEvidence(item.title,opener);
  const notice=item.notice;
  const source=item.source || 'final';
  const rowLink=(file,row,field='')=>file?`<button type="button" class="button secondary" data-evidence-source="${escapeHtml(source)}" data-evidence-file="${escapeHtml(file)}" data-evidence-row="${Number(row)||0}" data-evidence-field="${escapeHtml(field)}">View ${escapeHtml(file)}${row>=2?' · row '+Number(row):''}</button>`:'';
  evidenceBody.innerHTML=`<p>${escapeHtml(item.message)}</p>${!notice?rowLink(item.file,item.row,item.field):''}${item.context&&Object.keys(item.context).length?`<details><summary>Details</summary><pre>${escapeHtml(JSON.stringify(item.context,null,2))}</pre></details>`:''}${item.context?.route_id?`<button class="button secondary" data-evidence-source="${escapeHtml(source)}" data-evidence-route="${escapeHtml(item.context.route_id)}">View route</button>`:''}${notice?(notice.sampleNotices||[]).map(sample=>`<section class="validation-file"><pre>${escapeHtml(JSON.stringify(sample,null,2))}</pre>${rowLink(sample.filename || ({feed_expiration_date30_days:'feed_info.txt',missing_feed_contact_email_and_url:'feed_info.txt',platform_without_parent_station:'stops.txt',decreasing_or_equal_stop_time_distance:'stop_times.txt'})[notice.code],sample.csvRowNumber,sample.fieldName)}${sample.tripCsvRowNumber?rowLink('trips.txt',sample.tripCsvRowNumber):''}${sample.stopTimeCsvRowNumber?rowLink('stop_times.txt',sample.stopTimeCsvRowNumber):''}</section>`).join(''):''}`;
}
evidenceBody.addEventListener('click',event=>{
  const button=event.target.closest('[data-evidence-source]');if(!button)return;
  openEvidence(button.dataset.evidenceSource,{file:button.dataset.evidenceFile,row:Number(button.dataset.evidenceRow)||0,field:button.dataset.evidenceField,trip:button.dataset.evidenceTrip,route:button.dataset.evidenceRoute,offset:button.dataset.evidenceOffset!==undefined?Number(button.dataset.evidenceOffset):undefined},button,button.dataset.evidenceOffset===undefined);
});
document.querySelector('#evidence-back').addEventListener('click',()=>{
  const previous=evidenceHistory.pop();if(!previous)return;
  evidenceRequest++;document.querySelector('#evidence-title').textContent=previous.title;
  evidenceBody.replaceChildren(...previous.nodes);evidenceBody.scrollTop=previous.scroll;
  document.querySelector('#evidence-back').hidden=!evidenceHistory.length;
});
document.querySelector('#evidence-close').addEventListener('click',()=>evidenceDialog.close());
evidenceDialog.addEventListener('close',()=>{evidenceRequest++;evidenceHistory.length=0;evidenceBody.replaceChildren();evidenceOpener?.focus({preventScroll:true});});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-advanced-viewer]');if(!button)return;
  beginEvidence('Standalone GTFS file viewer',button);evidenceBody.innerHTML='<p class="field-help">Choose a ZIP in this viewer. It opens independently of the current validation.</p><iframe class="advanced-viewer" title="GTFS file viewer" src="/file-viewer/"></iframe>';
});
