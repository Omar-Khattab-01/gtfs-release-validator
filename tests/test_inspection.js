const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/inspection.js'),'utf8');
const renderer=source.slice(source.indexOf('function inspectionSearch'),source.indexOf('async function inspectionOpenViewer'));
for (const view of ['overview','files','routes','diagnostics','findings','comparison']) {
  test(`Standalone HASTUS inspector renders ${view} without a CAD or final input`,()=>{
    const nodes={};
    const node=selector=>nodes[selector] ||= {innerHTML:'',value:'',textContent:''};
    node('#inspection-section').value=view;
    const data={hastus:{path:'HASTUS.zip',label:'HASTUS',status:'complete',inventory:{routes:1,trips:1,stops:2},
      files:[{name:'trips.txt',rows:1,columns:['trip_id'],bytes:20,check_coverage:'Core table checks',finding_indices:[0]}],
      routes:[{route:{route_id:'r1',route_short_name:'1',route_long_name:'Test',route_type:'0'},status:'needs_review',trip_count:1,shape_count:1,direction_ids:['0'],finding_indices:[0]}],
      validation:{counts:{warning:1},findings:[{rule_id:'INS008',severity:'warning',category:'Content scope',title:'Unexpected rail',message:'Review route',file:'routes.txt',row:2,key:'r1'}]}}};
    const sandbox={document:{querySelector:node},inspectionData:data,inspectionSource:'hastus',inspectionLabels:{cad:'CleverCAD',hastus:'HASTUS bus',rail:'HASTUS rail',final:'Final merged GTFS'},inspectionComparisons:{},inspectionFindingLimit:100,currentRunId:'test',escapeHtml:String};
    const render=vm.runInNewContext(renderer+'\nrenderInspection',sandbox);
    render();
    assert.ok(node('#inspection-sources').innerHTML.includes('Not supplied'));
    assert.ok(node('#inspection-content').innerHTML.includes('HASTUS bus'));
    if (view==='files')assert.ok(node('#inspection-content').innerHTML.includes('Open table'));
    if (view==='routes')assert.ok(node('#inspection-content').innerHTML.includes('Variations & trips'));
    if (view==='findings')assert.ok(node('#inspection-content').innerHTML.includes('Unexpected rail'));
    if (view==='comparison')assert.ok(node('#inspection-content').innerHTML.includes('Not supplied'));
  });
}

test('HASTUS diagnostics groups shapes, filters messages and opens complete trip evidence',()=>{
  const nodes={};
  const node=selector=>nodes[selector] ||= {innerHTML:'',value:'',textContent:'',open:false,showModal(){this.open=true;}};
  node('#inspection-section').value='diagnostics';
  const group={id:'0',route_id:'13-373',route:{route_short_name:'13'},direction_id:'0',shape_id:'130097',trip_count:1,headsigns:['Town'],stop_time_count:2,trips_without_stop_times:0,log_lines:[1],trips:[{trip_id:'t1',service_id:'WKD',stop_time_count:2,custom_field:'retained'}]};
  const diagnostics={counts:{missing_shapes:1,affected_trips:1,messages:2,source_review:1,source_errors:0,unknown_messages:1},missing_shapes:[group],rule_inventory:[],
    log:{status:'present',encoding:'UTF-8',messages:[{line:1,kind:'missing_itinerary',title:'Missing itinerary',raw:'Warning: missing itinerary',source_severity:'Warning',assessment:'confirmed_defect',action:'Repair pattern',route_ids:['13-373'],trip_ids:['t1'],evidence:[]},
      {line:2,kind:'unknown',title:'Unknown',raw:'<script>unsafe</script>',source_severity:'Warning',assessment:'source_review',action:'Review',route_ids:[],trip_ids:[],evidence:[]}]}};
  const escape=value=>String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const sandbox={URLSearchParams,document:{querySelector:node},inspectionData:{hastus:{path:'HASTUS.zip',status:'complete',files:[],validation:{counts:{}},hastus_diagnostics:diagnostics}},inspectionSource:'hastus',inspectionLabels:{hastus:'HASTUS bus'},inspectionComparisons:{},inspectionFindingLimit:100,currentRunId:'test',escapeHtml:escape,sourceCard:(_,record)=>escape(JSON.stringify(record)),diagnosticFilter:'',diagnosticTripLimit:100,inspectionEvidenceRequest:0,inspectionDialog:node('dialog')};
  vm.createContext(sandbox);vm.runInContext(renderer,sandbox);
  vm.runInContext('renderInspection()',sandbox);
  let html=node('#inspection-content').innerHTML;
  assert.ok(html.includes('130097'));assert.ok(html.includes('hastus-trips.csv?source=hastus'));
  assert.ok(html.includes('Needs HASTUS review'));assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  sandbox.diagnosticFilter='confirmed_defect';vm.runInContext('renderInspection()',sandbox);
  assert.ok(node('#inspection-content').innerHTML.includes('1 matching log messages'));
  assert.ok(!node('#inspection-content').innerHTML.includes('unsafe'));
  vm.runInContext("openDiagnostic('group','0')",sandbox);
  html=node('#inspection-dialog-body').innerHTML;
  assert.ok(html.includes('Full trip & stops'));assert.ok(html.includes('retained'));
  assert.ok(html.includes('group=0'));assert.ok(node('dialog').open);
  vm.runInContext("openDiagnostic('message','1')",sandbox);
  assert.ok(node('#inspection-dialog-body').innerHTML.includes('no trip identity was guessed'));
});

test('Direct trip evidence creates the selected-trip container before loading details',async()=>{
  const nodes={};const node=selector=>nodes[selector] ||= {innerHTML:'',value:'',click(){}};
  let opened='';
  const fn=source.slice(source.indexOf('async function inspectionOpenViewer'),source.indexOf('async function openInspectionFinding'));
  const sandbox={document:{querySelector:node,querySelectorAll:()=>[]},inspectionDialog:{close(){}},escapeHtml:String,
    loadViewer:async()=>{},openViewerTrip:async id=>{assert.ok(node('#viewer-content').innerHTML.includes('id="viewer-trip-choice"'));assert.ok(node('#viewer-content').innerHTML.includes('id="viewer-trip-detail"'));opened=id;}};
  const open=vm.runInNewContext(fn+'\ninspectionOpenViewer',sandbox);
  await open('hastus',{trip:'t1'});
  assert.equal('t1',opened);assert.equal('hastus',node('#viewer-source').value);
});

test('A missing shape map explicitly shows stops only, not reconstructed geometry',()=>{
  const app=fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/app.js'),'utf8');
  const fn=app.slice(app.indexOf('function renderShapeMap'),app.indexOf('async function openViewerTrip'));
  const render=vm.runInNewContext(fn+'\nrenderShapeMap',{escapeHtml:String});
  const html=render({shape:[],stops:[{sequence:'1',stop_name:'Station',source_record:{stop_lat:'45',stop_lon:'-75'}}]});
  assert.ok(html.includes('Blue: exported stops only'));
  assert.ok(!html.includes('Red: exported shape'));
});
