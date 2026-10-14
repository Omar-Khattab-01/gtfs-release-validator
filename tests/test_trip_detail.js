// Browser rendering regression test; run with node --test tests/test_trip_detail.js.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/app.js'),'utf8');
const renderer = source.slice(source.indexOf('function renderTripDetail(detail)'),source.indexOf('function csvCell(value)'));

for (const filter of ['', 'any','first','middle','last']) {
  test(`Full trip is retained with filter ${filter || 'none'}`, () => {
    const stops = (name, sequence) => ({stop_name:name,sequence,source_stop_id:name,canonical_stop_id:name,departure_time:'08:10:00'});
    const alignment = ['first','','middle','','last'].map((position,i) => ({
      clevercad:stops('CAD '+i,i+1),hastus:stops('HASTUS '+i,i+1),final:stops('FINAL '+i,i+1),
      status:position ? 'different_stop':'match',fields:[],mismatch_positions:position ? [position]:[],final_source:'Both'
    }));
    const sandbox = {sequenceFilter:{value:filter},escapeHtml:String,sourceCard:()=>'<p>Complete attributes</p>',
      matchesSequenceFilter:positions => !filter || (filter==='any' ? positions.length>0 : positions.includes(filter))};
    const render = vm.runInNewContext(renderer+'\nrenderTripDetail',sandbox);
    const html = render({alignment,differences:alignment.filter(row=>row.status!=='match'),final_supplied:true});
    const table = html.match(/<tbody>([\s\S]*?)<\/tbody>/)[1];
    assert.equal((table.match(/<tr /g)||[]).length,5);
    assert.equal((table.match(/sequence-filter-highlight/g)||[]).length,filter==='any'?3:filter?1:0);
    for (let i=0;i<5;i++) for (const label of ['CAD','HASTUS','FINAL']) assert.ok(table.includes(label+' '+i));
    assert.ok(html.includes('3 explained differences'));
    assert.equal((html.match(/<details class="mismatch-evidence/g)||[]).length,3);
    assert.ok(html.includes('Full stop sequence shown'));
  });
}
