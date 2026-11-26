const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const read=name=>fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets',name),'utf8');
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function dom(){
  const nodes={};
  const node=id=>nodes[id] ||= {childNodes:[],value:'',textContent:'',open:false,hidden:false,scrollTop:0,
    _html:'',get innerHTML(){return this._html;},set innerHTML(value){this._html=value;this.childNodes=[{html:value}];},
    events:{},addEventListener(type,fn){this.events[type]=fn;},querySelectorAll(){return[];},querySelector(){return null;},
    replaceChildren(...children){this.childNodes=children;this._html='';},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},focus(){this.focused=true;}};
  return {node,document:{querySelector:node,querySelectorAll:()=>[],getElementById:id=>node('#'+id),addEventListener(){},activeElement:node('opener')}};
}

test('Export inputs start blank even when old paths exist in browser storage',()=>{
  const {node,document}=dom();for(const id of ['clevercad-path','hastus-path','final-path','rail-path'])node('#'+id).value='old.zip';
  let removed='';
  vm.runInNewContext(read('cache-manager.js').split('function cacheSize')[0],{document,localStorage:{getItem(){throw Error('Paths must not be restored');},removeItem(key){removed=key;}}});
  for(const id of ['clevercad-path','hastus-path','final-path','rail-path'])assert.equal('',node('#'+id).value);
  assert.equal('gtfs.validator.paths.v1',removed);
});

test('Nested evidence Back restores the exact prior content and scroll; Close restores focus',()=>{
  const {node,document}=dom();
  const context=vm.createContext({document});vm.runInContext(read('evidence.js'),context);
  vm.runInContext("beginEvidence('First')",context);
  const original={id:'original-row-with-event-handlers'};node('#evidence-body').childNodes=[original];node('#evidence-body').scrollTop=112;
  vm.runInContext("beginEvidence('Second')",context);
  assert.equal(false,node('#evidence-back').hidden);
  node('#evidence-back').events.click();
  assert.equal(original,node('#evidence-body').childNodes[0]);assert.equal(112,node('#evidence-body').scrollTop);
  assert.equal('First',node('#evidence-title').textContent);
  node('#evidence-dialog').close();assert.ok(node('opener').focused);
});

test('An evidence response arriving after Close cannot reopen or overwrite the panel',async()=>{
  const {node,document}=dom();let resolve;
  const response=new Promise(done=>resolve=done);
  const context=vm.createContext({document,URLSearchParams,currentRunId:'test',inspectionLabels:{hastus:'HASTUS'},fetch:()=>response});
  vm.runInContext(read('evidence.js'),context);
  const pending=vm.runInContext("openEvidence('hastus',{file:'stops.txt',row:2})",context);
  node('#evidence-dialog').close();resolve({ok:true,json:async()=>({rows:[],columns:[]})});await pending;
  assert.equal(false,node('#evidence-dialog').open);assert.equal(0,node('#evidence-body').childNodes.length);
});

test('Validation defaults to MobilityData and pages OC Transpo warnings without long concatenated lists',()=>{
  const {node,document}=dom();const context=vm.createContext({document,escapeHtml:escape});
  const script=read('workspace.js');vm.runInContext(script.slice(script.indexOf('let finalPayload')),context);
  const messages=Array.from({length:47},(_,index)=>({message:'Warning '+index,row:index+2}));
  context.payload={id:'test',final_validation:{mobility:{status:'unavailable',message:'Java not configured'},agency:{status:'complete',counts:{warnings:47},files:[{file:'stops.txt',warnings:messages,errors:[],info:[]}]},technical:{status:'complete',findings:[]}}};
  vm.runInContext('renderFinalValidation(payload)',context);
  let html=node('#final-content').innerHTML;
  assert.ok(html.indexOf('data-final-engine="mobility"')<html.indexOf('data-final-engine="agency"'));
  assert.ok(html.includes('Java not configured'));assert.ok(!html.includes('Warning 0'));
  vm.runInContext("finalEngine='agency';renderFinalReview()",context);
  html=node('#final-content').innerHTML;
  assert.equal(1,(html.match(/data-agency-file=/g)||[]).length);
  assert.ok(!html.includes('Warning 0'));
  vm.runInContext("openAgencyFile('stops.txt')",context);
  html=node('#final-content').innerHTML;
  assert.equal(20,(html.match(/class="review-row"/g)||[]).length);
  assert.ok(html.includes('Warning 0'));assert.ok(!html.includes('Warning 20<'));
  node('#final-next').events.click();html=node('#final-content').innerHTML;
  assert.ok(html.includes('Warning 20'));assert.ok(!html.includes('Warning 0<'));
  assert.ok(html.includes('Page 2 of 3'));
});

test('Technical findings exclude Packaging, which has a dedicated view',()=>{
  const script=read('workspace.js');const fn=script.slice(script.indexOf('function finalItems'),script.indexOf('function renderFinalValidation'));
  const finalItems=vm.runInNewContext(fn+'\nfinalItems');
  const items=finalItems('technical',{findings:[{rule_id:'PKG009',severity:'blocker'},{rule_id:'CSV005',severity:'error'}]});
  assert.equal(1,items.length);assert.equal('CSV005',items[0].rule_id);
});


test('OC Transpo shows each file once, preserves total counts, and marks clean files green',()=>{
  const {node,document}=dom();const context=vm.createContext({document,escapeHtml:escape});
  const script=read('workspace.js');vm.runInContext(script.slice(script.indexOf('let finalPayload')),context);
  const files=['agency.txt','calendar.txt','calendar_dates.txt','feed_info.txt','routes.txt','trips.txt','stops.txt','stop_times.txt','shapes.txt'].map(file=>({file,status:'PASS',counts:{errors:0,warnings:0,info:1},errors:[],warnings:[],info:[{message:'Present'}]}));
  Object.assign(files.find(file=>file.file==='trips.txt'),{status:'FAIL',counts:{errors:400,warnings:2,info:0},errors:[{message:'Trip problem',row:2}],warnings:[{message:'Trip warning'}],info:[]});
  Object.assign(files.find(file=>file.file==='routes.txt'),{status:'PASS WITH WARNINGS',counts:{errors:0,warnings:1,info:0},warnings:[{message:'Route problem'}],info:[]});
  context.payload={id:'test',final_validation:{agency:{status:'complete',files,counts:{errors:400,warnings:3,info:7}},mobility:{status:'not_requested'}}};
  vm.runInContext("renderFinalValidation(payload);finalEngine='agency';renderFinalReview()",context);
  let html=node('#final-content').innerHTML;
  assert.equal(9,(html.match(/data-agency-file=/g)||[]).length);
  assert.equal(7,(html.match(/agency-file-card clear/g)||[]).length);
  assert.ok(html.includes('400 errors'));assert.ok(!html.includes('Trip problem'));
  vm.runInContext("openAgencyFile('trips.txt')",context);html=node('#final-content').innerHTML;
  assert.ok(html.includes('Trip problem'));assert.ok(!html.includes('Trip warning'));
  assert.ok(html.includes('retained examples'));
  node('#agency-all-files').events.click();
  assert.equal(9,(node('#final-content').innerHTML.match(/data-agency-file=/g)||[]).length);
  vm.runInContext("openAgencyFile('shapes.txt')",context);
  assert.ok(node('#final-content').innerHTML.includes('file-status clear'));
  assert.ok(node('#final-content').innerHTML.includes('Present'));
});

test('A failed or unchecked file cannot appear green just because its count is zero',()=>{
  const {node,document}=dom();const context=vm.createContext({document,escapeHtml:escape});
  const script=read('workspace.js');vm.runInContext(script.slice(script.indexOf('let finalPayload')),context);
  context.failed={status:'FAIL',counts:{errors:0,warnings:0,info:0}};
  assert.equal('error',vm.runInContext('agencyFileState(failed).state',context));
  assert.equal('unchecked',vm.runInContext('agencyFileState({}).state',context));
});
