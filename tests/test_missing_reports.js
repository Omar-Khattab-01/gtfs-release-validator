const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/missing-reports.js'),'utf8');
const helper=source.slice(source.indexOf('function missingRows'),source.indexOf('function renderMissingReports'));
const routes=[
  {route_short_name:'19',clevercad_variations:[{variation_id:'CAD V1',headsigns:['Parliament'],trip_count:3}],hastus_variations:[],variation_pairs:[{status:'not_comparable',clevercad_variation_id:'CAD V1',hastus_variation_id:''}]},
  {route_short_name:'2',hastus_variations:[{variation_id:'HASTUS V2',headsigns:['Airport'],trip_count:2}],clevercad_variations:[],variation_pairs:[{status:'not_comparable',hastus_variation_id:'HASTUS V2',clevercad_variation_id:''}]},
  {route_short_name:'10',clevercad_variations:[{variation_id:'CAD V3',headsigns:['Centre'],trip_count:1}],variation_pairs:[{status:'not_comparable',clevercad_variation_id:'CAD V3'}]},
  {route_short_name:'30',clevercad_variations:[{variation_id:'CAD V4'}],variation_pairs:[{status:'issues',clevercad_variation_id:'CAD V4',hastus_variation_id:'HASTUS V1'}]}
];
test('Report tabs distinguish missing source, exclude paired mismatches and sort routes naturally',()=>{
  const missingRows=vm.runInNewContext(helper+'\nmissingRows');
  assert.equal(JSON.stringify(missingRows(routes,'hastus').map(row=>row.route.route_short_name)),JSON.stringify(['10','19']));
  assert.equal(JSON.stringify(missingRows(routes,'cad').map(row=>row.route.route_short_name)),JSON.stringify(['2']));
  assert.equal(missingRows(routes,'hastus','parliament').length,1);
  assert.equal(missingRows(routes,'cad','parliament').length,0);
});
test('Empty report and malformed source-only catalogs produce no misleading rows',()=>{
  const missingRows=vm.runInNewContext(helper+'\nmissingRows');
  assert.equal(missingRows([],'hastus').length,0);
  assert.equal(missingRows([{variation_pairs:[{status:'not_comparable',clevercad_variation_id:'missing-id'}]}],'hastus').length,0);
});
