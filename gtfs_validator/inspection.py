"""Independent, read-only feed health. Does not require another export."""
from collections import defaultdict
from contextlib import closing
import csv
import sqlite3
import zipfile

from .engine import validate_feed
from .feed_index import get_index
from .models import ValidationReport
from .schema import REQUIRED_COLUMNS
from .archive import REQUIRED_FILES, AGENCY_EXPECTED_FILES

SOURCES = {'cad':'CleverCAD','hastus':'HASTUS','rail':'HASTUS rail','final':'Final merged GTFS'}
RAIL_TYPES = {'0','1','2','12'}


def inspect_feed(path, source, technical=None, rail_names=()):
    label=SOURCES[source]
    result=technical or validate_feed(path,profile='oc-transpo' if source=='final' else 'source-inspection')
    try:index=get_index(path)
    except (OSError,ValueError,KeyError,UnicodeError,csv.Error,zipfile.BadZipFile,RuntimeError,sqlite3.Error) as exc:
        return {'source':source,'label':label,'path':path,'status':'unavailable','message':str(exc),
                'validation':result.to_dict(),'files':[],'routes':[],'inventory':{}}
    routes=index.small_tables.get('routes.txt',[]);trips=index.small_tables.get('trips.txt',[])
    by_route=defaultdict(list)
    for row,trip in enumerate(trips,2):by_route[trip.get('route_id','')].append((row,trip))
    with closing(sqlite3.connect(index.database.as_uri()+'?mode=ro',uri=True)) as db:
        times={key:count for key,count in db.execute("SELECT parent,COUNT(*) FROM records INDEXED BY records_parent WHERE name='stop_times.txt' AND parent!='' GROUP BY parent")}
        shapes={key:count for key,count in db.execute("SELECT parent,COUNT(*) FROM records INDEXED BY records_parent WHERE name='shapes.txt' AND parent!='' GROUP BY parent")}
        counts={name:(db.execute('SELECT row_number FROM records WHERE name=? ORDER BY row_number DESC LIMIT 1',(name,)).fetchone() or [-1])[0]+1 for name in index.columns}
    def add(rule,severity,title,message,file=None,row=None,key=None,route_id='',trip_ids=None,category='Technical'):
        result.add(rule,severity,category,title,message,file=file,row=row,key=key,
                   context={'route_id':route_id,'trip_ids':trip_ids or []})
    # Core values are distinct from optional agency completeness checks.
    for name,fields in [('agency.txt',('agency_name','agency_url','agency_timezone')),('feed_info.txt',('feed_publisher_name','feed_publisher_url','feed_lang')),('trips.txt',('route_id','service_id','trip_id'))]:
        for row,record in enumerate(index.rows(name) if name in index.columns else [],2):
            for field in fields:
                if not record.get(field,'').strip():add('INS001','error','Required value is blank',f'{field} is blank.',name,row,record.get('trip_id'),record.get('route_id',''))
    for row,stop in enumerate(index.small_tables.get('stops.txt',[]),2):
        kind=stop.get('location_type','') or '0'
        if kind in {'0','1','2'} and not stop.get('stop_name','').strip():add('INS002','error','Stop or station name is blank','Supply the stop or station name.','stops.txt',row,stop.get('stop_id'))
        if kind in {'1','2'} or (kind=='0' and not stop.get('parent_station','')):
            for field in ('stop_lat','stop_lon'):
                if not stop.get(field,'').strip():add('INS003','error','Stop coordinate is missing',f'{field} is required for this stop without an inherited station position.','stops.txt',row,stop.get('stop_id'))
    calendar=index.rows('calendar.txt') if 'calendar.txt' in index.columns else []
    for row,record in enumerate(calendar,2):
        if record.get('start_date','') and record.get('end_date','') and record['start_date']>record['end_date']:
            add('INS004','error','Service dates are reversed','start_date is after end_date.','calendar.txt',row,record.get('service_id'))
    services_known={row.get('service_id','') for name in ('calendar.txt','calendar_dates.txt') if name in index.columns for row in index.rows(name)}
    active_services=None
    try:
        from .rail import _services, _window
        active,_=_services(index,_window(index));active_services={key for key,value in active.items() if value}
    except (ValueError,OverflowError) as exc:
        add('INS005','warning','Service coverage needs review',str(exc),'calendar.txt',category='Agency review')
    for row,route in enumerate(routes,2):
        rid=route.get('route_id','');items=by_route[rid]
        if not route.get('route_short_name','').strip() and not route.get('route_long_name','').strip():
            add('INS006','error','Route has no display name','Provide route_short_name or route_long_name.','routes.txt',row,rid,rid)
        if not items:add('INS007','warning','Route has no trips','This route has no trips.txt records.','routes.txt',row,rid,rid)
        is_rail=route.get('route_type','') in RAIL_TYPES
        if source in {'cad','hastus'} and is_rail:
            add('INS008','warning',f'Unexpected rail content in {label}',f'Route {route.get("route_short_name") or rid} is declared as rail. All records remain available for inspection.','routes.txt',row,rid,rid,category='Content scope')
        elif source in {'cad','hastus'} and route.get('route_short_name') in rail_names:
            add('INS015','warning','Route number also appears in the rail export',f'Route {route.get("route_short_name")} appears in both a bus source and HASTUS rail. Review its mode and intended source.','routes.txt',row,rid,rid,category='Content scope')
        if source=='rail' and route.get('route_type','') in {'3','11'}:
            add('INS009','warning','Unexpected bus content in HASTUS rail',f'Route {route.get("route_short_name") or rid} is declared as bus.','routes.txt',row,rid,rid,category='Content scope')
        groups=defaultdict(list)
        for trip_row,trip in items:
            tid=trip.get('trip_id','');count=times.get(tid,0);shape=trip.get('shape_id','')
            if count<2:groups['insufficient_stop_times'].append((trip_row,trip))
            if shape and shapes.get(shape,0)==1:groups['incomplete_shape'].append((trip_row,trip))
            if not shape:groups['blank_shape'].append((trip_row,trip))
            if not trip.get('trip_headsign',''):groups['blank_headsign'].append((trip_row,trip))
            if active_services is not None and trip.get('service_id') in services_known and trip.get('service_id') not in active_services:groups['inactive_service'].append((trip_row,trip))
        for kind,affected in groups.items():
            rule,severity,title,message,category={
                'insufficient_stop_times':('INS010','error','Trip has fewer than two stop-time records','Inspect missing stop-time content.','Technical'),
                'incomplete_shape':('INS011','warning','Referenced shape has only one point','The shape cannot describe a route line.','Agency review'),
                'blank_shape':('INS012','warning','Trips have no shape ID','Optional GTFS field: review whether agency geometry is expected.','Agency review'),
                'blank_headsign':('INS013','warning','Trips have no destination headsign','Optional GTFS field: review rider-facing destination information.','Agency review'),
                'inactive_service':('INS014','warning','Trips have no active service dates','No operating dates were established within the declared feed coverage.','Agency review')
            }[kind]
            add(rule,severity,title,f'{len(affected)} trips on this route. {message}','trips.txt',affected[0][0],affected[0][1].get('trip_id'),rid,[item[1].get('trip_id') for item in affected],category)
    result.finish();validation=result.to_dict()
    trip_routes={trip.get('trip_id'):trip.get('route_id') for trip in trips}
    route_ids={row.get('route_id') for row in routes}
    route_findings=defaultdict(list);unassigned=0
    for number,finding in enumerate(validation['findings']):
        rid=finding.get('context',{}).get('route_id')
        if not rid and finding.get('file')=='trips.txt' and isinstance(finding.get('row'),int) and 0<=finding['row']-2<len(trips):rid=trips[finding['row']-2].get('route_id')
        if not rid:
            key=str(finding.get('key') or '')
            rid=trip_routes.get(key) or trip_routes.get(key.split(':')[0])
            if not rid and finding.get('file')=='routes.txt' and key in route_ids:rid=key
        if rid:
            finding.setdefault('context',{})['route_id']=rid;route_findings[rid].append(number)
        elif finding['severity'] in {'error','blocker','warning'}:unassigned+=1
    route_health=[]
    for route in routes:
        rid=route.get('route_id','');items=by_route[rid];ids=route_findings[rid]
        serious=[number for number in ids if validation['findings'][number]['severity'] in {'warning','error','blocker'}]
        route_health.append({'route':route,'trip_count':len(items),'shape_count':len({trip.get('shape_id') for _,trip in items if trip.get('shape_id')}),
                             'direction_ids':sorted({trip.get('direction_id','') for _,trip in items}),
                             'finding_indices':ids,'status':'needs_review' if serious else 'no_route_findings'})
    files=[{**member,'rows':counts.get(member['name']),'columns':index.columns.get(member['name'],[]),
            'present':True,
            'check_coverage':'Core table checks' if member['name'] in REQUIRED_COLUMNS else 'Browse all records; no table-specific rules',
            'finding_indices':[number for number,finding in enumerate(validation['findings']) if finding.get('file')==member['name']]} for member in index.files]
    present={item['name'] for item in files}
    for name in sorted((REQUIRED_FILES | AGENCY_EXPECTED_FILES | {'calendar.txt','calendar_dates.txt'})-present):
        files.append({'name':name,'bytes':0,'rows':None,'columns':[],'present':False,
                      'check_coverage':'Missing required file' if name in REQUIRED_FILES else 'Not supplied (conditional / profile-dependent)',
                      'finding_indices':[number for number,finding in enumerate(validation['findings']) if finding.get('file')==name]})
    return {'source':source,'label':label,'path':path,'status':'incomplete' if any(item['rule_id']=='RUN002' for item in validation['findings']) else 'complete','validation':validation,'files':files,'routes':route_health,
            'unassigned_findings':unassigned,'inventory':{'routes':len(routes),'trips':len(trips),'stops':len(index.stops),'shapes':len(shapes),
            'rail_routes':sum(row.get('route_type') in RAIL_TYPES for row in routes),'bus_routes':sum(row.get('route_type') in {'3','11'} for row in routes)}}


def add_inspections(report, paths, final_technical=None, progress=None):
    inspections={}
    rail_names=set()
    if paths.get('rail'):
        try:rail_names={row.get('route_short_name') for row in get_index(paths['rail']).small_tables.get('routes.txt',[])}-{''}
        except (OSError,ValueError,KeyError,UnicodeError,csv.Error,zipfile.BadZipFile,RuntimeError,sqlite3.Error):pass
    for source,label in SOURCES.items():
        path=paths.get(source)
        if not path:continue
        if progress:progress(f'Inspecting individual feed: {label}')
        technical=None
        if source=='final' and final_technical:
            # Keep final technical validation separate from source/comparison findings.
            technical=ValidationReport(path)
            technical.files=final_technical.get('files',{});technical.sha256=final_technical.get('sha256')
            technical.archive_size=final_technical.get('archive_size')
            for item in final_technical.get('findings',[]):technical.add(**item)
        try:data=inspect_feed(path,source,technical,rail_names)
        except (OSError,ValueError,KeyError,UnicodeError,csv.Error,zipfile.BadZipFile,RuntimeError,sqlite3.Error) as exc:
            data={'source':source,'label':label,'path':path,'status':'failed','message':str(exc),'files':[],'routes':[],'inventory':{},'validation':{'counts':{},'findings':[],'files':{}}}
        inspections[source]=data
        if data['status']=='failed':report.add('INS999','error','Individual inspection',f'{label} inspection did not complete',data['message'],context={'inspection_source':source})
        # Individual results retain their own identities; the aggregate offers navigation.
        for number,finding in enumerate(data['validation']['findings']):
            if source=='final' and not finding['rule_id'].startswith('INS'):continue
            if source=='rail' and finding['rule_id'].startswith(('PKG','CSV','REL','TIME','VAL','RUN')):continue
            item=dict(finding);item['file']=label+':'+str(item.get('file') or '')
            item['context']={**item.get('context',{}),'inspection_source':source,'inspection_finding_index':number}
            report.add(**item)
        report.stats.setdefault('inputs',{})[label]={'path':path,'sha256':data['validation'].get('sha256')}
    report.stats['individual_feeds']=inspections
    report.stats['workflow']={'bus_comparison':'complete' if report.stats.get('trip_reconciliation') else 'not_available',
                              'final':'supplied' if paths.get('final') else 'not_supplied',
                              'sources_supplied':[source for source in ('cad','hastus','rail') if paths.get(source)]}
    return inspections
