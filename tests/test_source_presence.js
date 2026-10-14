const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../gtfs_validator/web_assets/app.js'), 'utf8');
const helpers = source.slice(source.indexOf('function matchesSourcePresence'), source.indexOf('const matchesSequenceFilter'));
const cadOnly = {status:'not_comparable', clevercad_variation_id:'CAD V1', hastus_variation_id:''};
const hastusOnly = {status:'not_comparable', clevercad_variation_id:'', hastus_variation_id:'HASTUS V1'};
const paired = {status:'issues', clevercad_variation_id:'CAD V2', hastus_variation_id:'HASTUS V2', mismatch_positions:['first']};
for (const filter of ['', 'clevercad', 'hastus']) {
  test(`Source presence direction and finding evidence: ${filter || 'all'}`, () => {
    const context = {sourcePresenceFilter:{value:filter}, routeHealthData:[{route_short_name:'19', variation_pairs:[cadOnly,hastusOnly,paired]}]};
    const funcs = vm.runInNewContext(helpers + '\n({matchesSourcePresence,matchesFindingPresence})',context);
    assert.equal(funcs.matchesSourcePresence(cadOnly), !filter || filter==='hastus');
    assert.equal(funcs.matchesSourcePresence(hastusOnly), !filter || filter==='clevercad');
    assert.equal(funcs.matchesSourcePresence(paired), !filter);
    assert.equal(funcs.matchesSourcePresence({status:'not_comparable'}), !filter);
    assert.equal(funcs.matchesFindingPresence({context:{route_short_name:'19',clevercad_variation_ids:['CAD V1']}}), !filter || filter==='hastus');
    assert.equal(funcs.matchesFindingPresence({context:{route_short_name:'19',hastus_variation_id:'HASTUS V1'}}), !filter || filter==='clevercad');
    assert.equal(funcs.matchesFindingPresence({context:{route_short_name:'19',clevercad_variation_id:'CAD V2',hastus_variation_id:'HASTUS V2'}}), !filter);
    assert.equal(funcs.matchesFindingPresence({rule_id:'RAIL002'}), !filter);
  });
}
for (const filter of ['clevercad','hastus']) {
  test(`Variation tabs keep only the requested missing source: ${filter}`, () => {
    const nodes = {};
    const node = selector => nodes[selector] ||= {innerHTML:'',textContent:'',classList:{toggle(){}},querySelectorAll:()=>[]};
    const pairs = [
      {...cadOnly,id:'cad-only',cad:{variation_id:'CAD V1'},hastus:null},
      {...hastusOnly,id:'hastus-only',cad:null,hastus:{variation_id:'HASTUS V1'}},
      {...paired,id:'paired',cad:{variation_id:'CAD V2'},hastus:{variation_id:'HASTUS V2'}}
    ];
    const context = {document:{querySelector:node},sourcePresenceFilter:{value:filter},activeVariation:'',escapeHtml:String,matchesSequenceFilter:()=>true,buildVariationPairs:()=>pairs};
    const renderer = source.slice(source.indexOf('function renderVariationPanel'),source.indexOf('async function selectVariation'));
    const render = vm.runInNewContext(helpers + renderer + '\nrenderVariationPanel',context);
    render({route_short_name:'19'});
    const html = node('#variation-tabs').innerHTML;
    assert.equal(html.includes('data-pair-id="cad-only"'),filter==='hastus');
    assert.equal(html.includes('data-pair-id="hastus-only"'),filter==='clevercad');
    assert.equal(html.includes('data-pair-id="paired"'),false);
  });
}
for (const filter of ['', 'clevercad', 'hastus']) {
  test(`Route cards narrow to source-only variations: ${filter || 'all'}`, () => {
    const nodes = {};
    const node = selector => nodes[selector] ||= {innerHTML:'',textContent:'',classList:{toggle(){}},querySelectorAll:()=>[]};
    const routes = [
      {route_short_name:'2',status:'issues',variation_pairs:[cadOnly,paired]},
      {route_short_name:'10',status:'not_comparable',variation_pairs:[hastusOnly]},
      {route_short_name:'19',status:'issues',variation_pairs:[paired]}
    ];
    const context = {document:{querySelector:node}, sourcePresenceFilter:{value:filter},sequenceFilter:{value:''},routeSort:{value:'number'},activeRoute:'',escapeHtml:String,matchesSequenceFilter:()=>true,renderVariationPanel(){}};
    const renderer = source.slice(source.indexOf('function renderRouteHealth'),source.indexOf('function buildVariationPairs'));
    const render = vm.runInNewContext(helpers + renderer + '\nrenderRouteHealth',context);
    render(routes);
    const html = node('#route-grid').innerHTML;
    assert.equal(html.includes('data-route="2"'),!filter || filter==='hastus');
    assert.equal(html.includes('data-route="10"'),!filter || filter==='clevercad');
    assert.equal(html.includes('data-route="19"'),!filter);
    if (!filter) assert.ok(html.indexOf('data-route="2"') < html.indexOf('data-route="10"'));
  });
}
