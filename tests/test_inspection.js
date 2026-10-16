const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../gtfs_validator/web_assets/inspection.js'),'utf8');
const renderer=source.slice(source.indexOf('function inspectionSearch'),source.indexOf('async function inspectionOpenViewer'));
for (const view of ['overview','files','routes','findings','comparison']) {
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
