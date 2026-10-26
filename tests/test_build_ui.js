const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/build.js'),'utf8');
const escape = value => String(value ?? '').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const render = vm.runInNewContext(source.slice(source.indexOf('function buildPolicyHtml'),source.indexOf('function renderBuild'))+'\nbuildResultHtml',{escapeHtml:escape});
function fixture() {
  return {id:'abcdef123456',result:{output:'C:\\GTFS\\merged.zip',comparison:{status:'not_requested'},summary:{
    counts:{routes:2,bus_trips:5,rail_trips:3,stops:12,bus_stop_times:50,rail_stop_times:10},validation:{counts:{blocker:0,error:0,warning:0}},
    excluded_trip_count:1,policy:{exclude_routes:['898'],direction_rules:[],clear_block_ids:[]},sha256:'abc',archive_verification:{},
    review_groups:[{title:'Unmatched trips',kind:'unmatched_trip',count:1,examples:[{kind:'unmatched_trip',trip_id:'<script>bad</script>',message:'Review this trip'}]}]}}};
}
test('Build output exposes complete counts, local artifacts, policy and escaped review evidence',()=>{
  const html = render(fixture());
  assert.ok(html.includes('8</strong><span>Trip records'));
  assert.ok(html.includes('60</strong><span>Stop-time records'));
  assert.ok(html.includes('/api/builds/abcdef123456/download/zip'));
  assert.ok(html.includes('Preserve CAD block IDs'));
  assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert.ok(!html.includes('<script>bad</script>'));
  assert.ok(html.includes('not approved for publication'));
});
test('Reference differences identify changed, draft-only and reference-only records',()=>{
  const job=fixture();job.result.comparison={status:'complete',equivalent:false,reference_only_members:['translations.txt'],tables:{'stop_times.txt':{counts:{changed_rows:3,candidate_only_rows:2,reference_only_rows:1}}}};
  const html=render(job);
  assert.ok(html.includes('Reference differences found'));assert.ok(html.includes('stop_times.txt'));
  assert.ok(html.includes('translations.txt'));assert.ok(html.includes('download/comparison'));
  assert.ok(!html.includes('Reference data match'));
});
test('Pending comparison is not displayed as failed or as not requested',()=>{
  const job=fixture();job.result.comparison={status:'pending'};
  const html=render(job);
  assert.ok(html.includes('reference comparison is in progress'));
  assert.ok(!html.includes('No reference final supplied'));assert.ok(!html.includes('class="build-error"'));
});
