const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/headways.js'),'utf8');
const escape = value => String(value ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

test('Trip table preserves blocks, dates after midnight and escaped exported metadata',()=>{
  const nodes={};
  const node=selector=>nodes[selector] ||= {innerHTML:'',textContent:'',value:'',addEventListener(){}};
  const sandbox={document:{querySelector:node},escapeHtml:escape,headwayContent:node('content'),headwayLimit:60,
    headwayData:{trips:[{trip_id:'trip-a',trip_headsign:'<script>Town</script>',block_id:'14531136',direction_id:'0',service_id:'WKD',shape_id:'shape-a',first_time:'25:00:00',last_time:'25:20:00',first_stop:'First',last_stop:'Last',departures:[{time:'25:00:00',sequence:'1',headway_seconds:312.5,previous_trip_id:'previous'}]}],
      issues:[],headways:{minimum:300,median:312.5,maximum:600},block_count:1,unassigned_blocks:0,not_at_stop:0,excluded_no_pickup_calls:0,missing_departure_times:0,
      hourly:[{hour:25,direction_id:'0',departures:4,minimum:300,median:312.5,maximum:600}]} };
  const duration=source.slice(source.indexOf('function headwayDuration'),source.indexOf('function setupHeadways'));
  const renderers=source.slice(source.indexOf('function renderHeadwayTrips'),source.indexOf('async function openHeadways'));
  vm.runInNewContext(duration+renderers+'\nrenderHeadways()',sandbox);
  const rows=node('#headway-trip-rows').innerHTML;
  assert.ok(rows.includes('14531136'));assert.ok(rows.includes('25:00:00'));assert.ok(rows.includes('5m 12.5s'));
  assert.ok(rows.includes('&lt;script&gt;Town&lt;/script&gt;'));assert.ok(!rows.includes('<script>'));
  assert.ok(node('content').innerHTML.includes('Departures in hour'));
});

test('Hidden feed viewer defers indexing until the user opens it',async()=>{
  const app=fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/app.js'),'utf8');
  const method=app.slice(app.indexOf('async function setupViewer'),app.indexOf('async function loadViewer'));
  const select={options:[{value:'final',disabled:false},{value:'cad',disabled:false}],value:''};
  let loads=0;
  const setup=vm.runInNewContext(method+'\nsetupViewer',{document:{querySelector:id=>id==='#viewer-source' ? select : {classList:{contains:()=>true}}},viewerInventory:{},loadViewer:async()=>{loads++;}});
  await setup({'Final merged GTFS':{path:'final.zip'}});
  assert.equal(0,loads);assert.equal('final',select.value);assert.ok(select.options[1].disabled);
});
