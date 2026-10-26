"""Build a local GTFS merge candidate without consulting a reference final.

The receipt is part of the deliverable. A successful build is not a claim of
vendor equivalence or agency approval. Ambiguity is recorded, never hidden.
"""
from collections import Counter,defaultdict
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

from .release_matcher import Source,read_table,match_sources
from .engine import validate_feed

PACKAGE=Path(__file__).parent
DEFAULT_POLICY=PACKAGE/'release_policy.json'
FIELDS={
 'agency.txt':'agency_id agency_name agency_url agency_timezone agency_lang agency_phone agency_fare_url agency_email'.split(),
 'feed_info.txt':'feed_publisher_name feed_publisher_url feed_lang default_lang feed_start_date feed_end_date feed_version feed_contact_email feed_contact_url'.split(),
 'routes.txt':'route_id agency_id route_short_name route_long_name route_desc route_type route_url route_color route_text_color route_sort_order continuous_pickup continuous_drop_off network_id'.split(),
 'stops.txt':'stop_id stop_code stop_name tts_stop_name stop_desc stop_lat stop_lon zone_id stop_url location_type parent_station stop_timezone wheelchair_boarding level_id platform_code'.split(),
 'trips.txt':'route_id service_id trip_id trip_headsign trip_short_name direction_id block_id shape_id wheelchair_accessible bikes_allowed'.split(),
 'stop_times.txt':'trip_id arrival_time departure_time stop_id stop_sequence stop_headsign pickup_type drop_off_type shape_dist_traveled timepoint'.split(),
 'calendar.txt':'service_id monday tuesday wednesday thursday friday saturday sunday start_date end_date'.split(),
 'calendar_dates.txt':'service_id date exception_type'.split(),
 'shapes.txt':'shape_id shape_pt_lat shape_pt_lon shape_pt_sequence shape_dist_traveled'.split(),
}


def digest(path):
    value=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def load_policy(path):
    policy=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    required={'exclude_routes','direction_rules','timing_tolerance_seconds','minimum_stop_coverage','clear_block_ids','omit_tables','allow_omit_nonempty_tables'}
    if set(policy)!=required:raise ValueError('Policy keys must be exactly: '+', '.join(sorted(required)))
    if not isinstance(policy['timing_tolerance_seconds'],int) or not 0<=policy['timing_tolerance_seconds']<=60:raise ValueError('Timing tolerance must be 0..60 seconds')
    if not .8<=float(policy['minimum_stop_coverage'])<=1:raise ValueError('Stop coverage must be 0.8..1.0')
    for name in ('exclude_routes','clear_block_ids','omit_tables','allow_omit_nonempty_tables'):
        if not isinstance(policy[name],list) or not all(isinstance(x,str) for x in policy[name]):raise ValueError('Policy '+name+' must be a string list')
    for rule in policy['direction_rules']:
        if set(rule)!={'route_min','route_max','keep'} or not isinstance(rule['keep'],list):raise ValueError('Invalid direction rule')
    return policy


def eligible(route,trip,policy):
    name=route['route_short_name']
    if name in policy['exclude_routes']:return False
    for rule in policy['direction_rules']:
        if name.isdigit() and rule['route_min']<=int(name)<=rule['route_max'] and trip.get('direction_id') not in rule['keep']:return False
    return True


def numeric(value):
    if not value:return ''
    return format(Decimal(value).normalize(),'f')


@contextmanager
def csv_member(archive,name):
    info=zipfile.ZipInfo(name,date_time=(2000,1,1,0,0,0))
    info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
    info.compress_type=zipfile.ZIP_DEFLATED
    with archive.open(info,'w',force_zip64=True) as raw:
        with io.TextIOWrapper(raw,encoding='utf-8',newline='') as text:
            writer=csv.DictWriter(text,fieldnames=FIELDS[name],lineterminator='\r\n',extrasaction='ignore')
            writer.writeheader();yield writer


def verify_package(path,expected_names):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():raise ValueError('Output ZIP integrity test failed')
        if set(archive.namelist())!=set(expected_names):raise ValueError('Unexpected output members')
        for item in archive.infolist():
            mode=item.external_attr>>16
            if item.create_system!=3 or stat.S_IMODE(mode)!=0o644 or not stat.S_ISREG(mode):raise ValueError('Output member is not a Unix regular file with mode 0644')
    # A child process controls its own umask; never change the application's
    # process-wide umask (which may be serving other local requests).
    with tempfile.TemporaryDirectory(prefix='gtfs-extract-check-') as folder:
        code="import os,sys,zipfile,pathlib,json;\nif os.name!='nt':os.umask(0o022)\nwith zipfile.ZipFile(sys.argv[1]) as z:z.extractall(sys.argv[2])\nprint(json.dumps({p.name:oct(p.stat().st_mode & 0o777) for p in pathlib.Path(sys.argv[2]).iterdir()}))"
        result=subprocess.run([sys.executable,'-c',code,str(path),folder],capture_output=True,text=True,check=True)
        modes=json.loads(result.stdout)
        if os.name!='nt' and any(v!='0o644' for v in modes.values()):raise ValueError('Extracted files are not mode 0644')
    return {'zip_integrity':'passed','root_members':sorted(expected_names),'stored_modes':'all regular files 0644',
            'extracted_modes':modes,'platform':os.name,
            'windows_note':'Windows extraction mode bits are not POSIX permissions; stored Unix modes were verified.' if os.name=='nt' else ''}


def build_release(cad_path,hastus_path,output_path,*,start_date,end_date,rail_path=None,
                  policy_path=DEFAULT_POLICY,sort_reference=None,allow_draft=False,progress=print):
    start=datetime.strptime(start_date,'%Y%m%d').date();end=datetime.strptime(end_date,'%Y%m%d').date()
    if start>end:raise ValueError('Publication start date is after end date')
    output=Path(output_path).expanduser().resolve();receipt_path=output.with_suffix('.report.json')
    if output.exists() or receipt_path.exists():raise ValueError('Output ZIP or receipt already exists; choose a new name')
    policy=load_policy(policy_path)
    inputs={k:Path(v).expanduser().resolve() for k,v in [('cad',cad_path),('hastus',hastus_path),('rail',rail_path)] if v}
    if output in inputs.values() or receipt_path in inputs.values():raise ValueError('Output cannot replace a source archive')
    before={k:digest(v) for k,v in inputs.items()}
    if progress:progress('Reading source ZIPs and calendars')
    feeds={k:Source(str(v),k) for k,v in inputs.items()};cad=feeds['cad'];bus=feeds['hastus'];rail=feeds.get('rail')
    warnings=[];changes=Counter();counts=Counter()
    def warn(kind,message,**context):warnings.append({'kind':kind,'message':message,**context})
    for label,feed in feeds.items():
        for name in feed.names:
            if name not in FIELDS and name not in policy['omit_tables'] and name!='error_warning.txt':
                warn('unsupported_source_table','No merge rule is implemented for this source member; it is not included in the core candidate.',source=label,file=name)
            if name in FIELDS:
                extra=set(feed.headers.get(name,[]))-set(FIELDS[name])
                if extra:warn('unsupported_source_columns','These columns have no merge rule and are omitted.',source=label,file=name,columns=sorted(extra))
        for table in policy['omit_tables']:
            if table not in feed.names:continue
            with zipfile.ZipFile(feed.path) as z:nonempty=next(read_table(z,table),None) is not None
            if nonempty and table not in policy['allow_omit_nonempty_tables']:raise ValueError('Policy does not authorize omitting nonempty '+table+' from '+label)
            if nonempty:warn('omitted_table','A nonempty source table is excluded by publication policy.',source=label,file=table)
    if not rail:warn('rail_not_supplied','Only bus service will be produced; provide the rail export for a complete agency feed.')
    kept={tid for tid,t in cad.trips.items() if eligible(cad.routes[t['route_id']],t,policy)}
    excluded=[{'trip_id':tid,'route':cad.routes[t['route_id']]['route_short_name'],'direction_id':t.get('direction_id')} for tid,t in cad.trips.items() if tid not in kept]
    codes=defaultdict(list)
    for sid,s in cad.stops.items():
        if s.get('stop_code'):codes[s['stop_code']].append(sid)
    bus_map={}
    for sid in bus.stops:
        targets=codes.get(sid,[])
        if len(targets)>1:raise ValueError('Ambiguous CAD stop_code '+sid+'; supply corrected source data before merging')
        bus_map[sid]=targets[0] if targets else sid
    if progress:progress('Loading compact source schedule models (original files stay read-only)')
    cad.load_models({sid:sid for sid in cad.stops},kept)
    bus.load_models(bus_map)
    matches=match_sources(cad,bus,policy['timing_tolerance_seconds'],policy['minimum_stop_coverage'],progress)
    if progress:progress('Applying source metadata and publication policy')
    candidate_rows={};final_trips={};match_receipt=[]
    for tid in sorted(kept):
        result=matches[tid];target=cad.models[tid];record=dict(cad.trips[tid]);ids=result['candidate_ids']
        if not ids:warn('unmatched_trip','CAD metadata retained where no HASTUS schedule counterpart was established.',trip_id=tid)
        if result['method']=='review_pattern':warn('lower_similarity_trip','Metadata consensus uses lower-similarity candidates; review required.',trip_id=tid,candidate_ids=ids)
        if result['uncovered_dates']:warn('partial_dates','HASTUS candidates do not cover all CAD source dates.',trip_id=tid,dates=result['uncovered_dates'])
        for field in ('trip_headsign','wheelchair_accessible','bikes_allowed'):
            values={bus.trips[hid].get(field,'') for hid in ids}
            if len(values)==1:
                value=next(iter(values))
                if value!=record.get(field,''):changes['trips.txt:'+field]+=1
                record[field]=value
            elif len(values)>1:warn('conflicting_trip_metadata','CAD value retained because candidate values disagree.',trip_id=tid,field=field,values=sorted(values))
        if record.get('block_id') in policy['clear_block_ids']:record['block_id']='';changes['trips.txt:block_id']+=1
        final_trips[tid]=record
        # Keep only conservative, explicit per-call consensus. An unresolved
        # stop never borrows the first matching ID from a loop.
        from array import array
        prepared=array('i')
        for position in range(len(target['seq'])):
            calls=[]
            for hid in ids:
                offset=result['alignments'][hid].get(position)
                if offset is not None:
                    row=bus.models[hid]['rows'];calls.append((row[offset*7+4],row[offset*7+6]))
            entry=[-1,-1]
            for column,field in [(0,'pickup_type'),(1,'stop_headsign')]:
                values={c[column] for c in calls}
                if len(calls)==len(ids) and ids and len(values)==1:entry[column]=next(iter(values))
                elif len(values)>1:warn('conflicting_stop_metadata','CAD pickup or blank destination retained because candidates disagree.',trip_id=tid,position=position+1,field=field)
            prepared.extend(entry)
        candidate_rows[tid]=prepared
        match_receipt.append({'cad_trip_id':tid,'hastus_candidates':ids,'method':result['method'],
                              'block_resolved':result.get('block_resolved',False),'ambiguous_dates':result['ambiguous_dates'],
                              'uncovered_dates':result['uncovered_dates']})
    used_routes={t['route_id'] for t in final_trips.values()}
    byname=defaultdict(list)
    for row in bus.routes.values():byname[row['route_short_name']].append(row)
    sort_path=Path(sort_reference) if sort_reference else PACKAGE/'routes_sort_order_list.csv'
    with sort_path.open(encoding='utf-8-sig',newline='') as stream:sorts={r['route_short_name']:r['route_sort_order'] for r in csv.DictReader(stream)}
    routes={}
    for rid in sorted(used_routes):
        original=cad.routes[rid];options=byname[original['route_short_name']];row=dict(original)
        for field in FIELDS['routes.txt']:
            if field in {'route_id','route_short_name','route_sort_order'}:continue
            values={r.get(field,'') for r in options}
            if len(values)==1:row[field]=next(iter(values))
            elif len(values)>1:warn('conflicting_route_metadata','CAD route attribute retained.',route_id=rid,field=field)
        row['route_sort_order']=sorts.get(row['route_short_name'],'')
        if not options:warn('unmatched_route','CAD route metadata retained.',route_id=rid)
        if not row['route_sort_order']:warn('missing_route_sort','No agency sort-order entry.',route_id=rid)
        routes[rid]=row
    rail_trip_ids={};shortened_rail_ids=set();rail_routes=set()
    if rail:
        for sid,t in rail.trips.items():
            suffix='-'+t['service_id'];tid=sid[:-len(suffix)] if sid.endswith(suffix) else sid
            if tid==sid:warn('rail_trip_id_preserved','Rail trip ID has no exact service suffix; original ID preserved.',trip_id=sid)
            if tid in final_trips or tid in shortened_rail_ids:raise ValueError('Rail trip ID collision after shortening: '+tid)
            rail_trip_ids[sid]=tid;shortened_rail_ids.add(tid);final_trips[tid]={**t,'trip_id':tid};rail_routes.add(t['route_id'])
        for rid in rail_routes:
            if rid in routes:raise ValueError('Bus and rail route ID collision: '+rid)
            routes[rid]={**rail.routes[rid],'route_sort_order':sorts.get(rail.routes[rid]['route_short_name'],'')}
    # HASTUS metadata, CAD positions. All source station rows remain intact;
    # bus station definitions take precedence over duplicate rail stations.
    stops={}
    for sid,row in bus.stops.items():
        dest=bus_map[sid];copy=dict(row);copy['stop_id']=dest
        if dest not in cad.stops and row.get('location_type')!='1':
            counts['unmapped_bus_stop_definitions_excluded']+=1
            continue
        if dest in cad.stops:
            for field in ('stop_lat','stop_lon'):copy[field]=cad.stops[dest].get(field,'')
        copy['parent_station']=bus_map.get(copy.get('parent_station'),copy.get('parent_station',''))
        stops[dest]=copy
    if rail:
        for sid,row in rail.stops.items():stops.setdefault(sid,dict(row))
    # Fallback CAD stops are retained only if a published bus trip uses them.
    used_bus_stops={cad.stop_keys[m['rows'][i+1]] for m in cad.models.values() for i in range(0,len(m['rows']),7)}
    for sid in used_bus_stops:
        if sid not in stops:stops[sid]=dict(cad.stops[sid])
    services={};exceptions={}
    for label,feed in [('cad',cad),('rail',rail)]:
        if not feed:continue
        for row in feed.rows('calendar.txt'):
            copy=dict(row);key=copy['service_id']
            if key in services:raise ValueError('Service ID collision: '+key)
            copy['start_date']=max(start_date,copy['start_date']);copy['end_date']=min(end_date,copy['end_date'])
            if copy['start_date']>copy['end_date']:
                warn('calendar_outside_window','Calendar retained with publication bounds; source has no dates inside this release.',service_id=key)
                for day in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday'):copy[day]='0'
                copy['start_date']=start_date;copy['end_date']=end_date
            services[key]=copy
        for row in feed.rows('calendar_dates.txt'):
            if start_date<=row['date']<=end_date:
                key=(row['service_id'],row['date'])
                if key in exceptions and exceptions[key]!=row:raise ValueError('Calendar-date collision')
                exceptions[key]=dict(row)
    for trip in final_trips.values():
        if trip['service_id'] not in services and not any(key[0]==trip['service_id'] for key in exceptions):raise ValueError('Trip references unknown service '+trip['service_id'])
    used_shapes={t.get('shape_id') for t in final_trips.values()}-{None,''}
    info=dict((bus.rows('feed_info.txt') or cad.rows('feed_info.txt') or [{}])[0])
    info.update(feed_start_date=start_date,feed_end_date=end_date,feed_version=(cad.rows('feed_info.txt') or [{}])[0].get('feed_version',''))
    receipt={'status':'DRAFT_NOT_APPROVED','source_only_builder':True,'publication_window':[start_date,end_date],
             'builder_version':'0.1.0-experimental',
             'inputs':{k:{'path':str(inputs[k]),'sha256':before[k]} for k in inputs},'policy':policy,
             'policy_file':{'path':str(Path(policy_path).resolve()),'sha256':digest(policy_path)},
             'route_sort_reference':{'path':str(sort_path.resolve()),'sha256':digest(sort_path)},
             'counts':{'bus_trips':len(kept),'rail_trips':len(rail_trip_ids),'routes':len(routes),'stops':len(stops)},
             'excluded_trips':excluded,'changes':changes,'warnings':warnings,'crosswalk':match_receipt,
             'limitations':['No vendor-equivalence claim. Run the independent reference comparison on a known release.',
                            'Unresolved joins use explicit CAD/blank fallbacks and require review.']}
    if warnings and not allow_draft:
        kinds=Counter(r['kind'] for r in warnings)
        raise ValueError('Review required before creating a candidate: '+str(dict(kinds))+'. Use --allow-draft to write a clearly reported draft candidate.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gtfs-merge-build-',dir=output.parent) as folder:
        staged=Path(folder)/'candidate.zip';positions=Counter();shape_seen=set()
        if progress:progress('Writing merged GTFS tables')
        with zipfile.ZipFile(staged,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,rows in [('agency.txt',cad.rows('agency.txt')),('feed_info.txt',[info]),('routes.txt',[routes[k] for k in sorted(routes)]),
                              ('stops.txt',[stops[k] for k in sorted(stops)]),('trips.txt',[final_trips[k] for k in sorted(final_trips)]),
                              ('calendar.txt',[services[k] for k in sorted(services)]),('calendar_dates.txt',[exceptions[k] for k in sorted(exceptions)])]:
                with csv_member(archive,name) as writer:
                    for row in rows:
                        if name=='stops.txt':row={**row,'stop_lat':numeric(row.get('stop_lat','')),'stop_lon':numeric(row.get('stop_lon',''))}
                        writer.writerow(row)
            with csv_member(archive,'stop_times.txt') as writer:
                with zipfile.ZipFile(cad.path) as source:
                    for row in read_table(source,'stop_times.txt'):
                        tid=row['trip_id']
                        if tid not in kept:continue
                        position=positions[tid];m=cad.models[tid];data=m['rows']
                        if 'position_by_sequence' in m:position=m['position_by_sequence'][int(row['stop_sequence'])]
                        if position>=len(candidate_rows[tid])//2 or int(row['stop_sequence'])!=data[position*7]:raise ValueError('Source stop order changed during production: '+tid)
                        pickup,head=candidate_rows[tid][position*2:position*2+2]
                        original_pickup=row.get('pickup_type') or '0';original_head=row.get('stop_headsign','')
                        row['stop_headsign']=bus.headsigns[head] if head>=0 else ''
                        if pickup>=0:row['pickup_type']=str(pickup)
                        if (row.get('pickup_type') or '0')!=original_pickup:changes['stop_times.txt:pickup_type']+=1
                        if row['stop_headsign']!=original_head:changes['stop_times.txt:stop_headsign']+=1
                        row['shape_dist_traveled']=numeric(row.get('shape_dist_traveled',''))
                        writer.writerow(row);positions[tid]+=1;counts['bus_stop_times']+=1
                if rail:
                    with zipfile.ZipFile(rail.path) as source:
                        for row in read_table(source,'stop_times.txt'):
                            if row['trip_id'] not in rail_trip_ids:continue
                            writer.writerow({**row,'trip_id':rail_trip_ids[row['trip_id']],
                                             'shape_dist_traveled':row.get('shape_dist_traveled') or '0'});counts['rail_stop_times']+=1
            with csv_member(archive,'shapes.txt') as writer:
                for label,feed in [('cad',cad),('rail',rail)]:
                    if not feed or 'shapes.txt' not in feed.names:continue
                    own=set()
                    with zipfile.ZipFile(feed.path) as source:
                        for row in read_table(source,'shapes.txt'):
                            sid=row['shape_id']
                            if sid not in used_shapes:continue
                            if label=='rail' and sid in shape_seen:raise ValueError('Bus/rail shape ID collision: '+sid)
                            own.add(sid)
                            for field in ('shape_pt_lat','shape_pt_lon','shape_dist_traveled'):row[field]=numeric(row.get(field,''))
                            writer.writerow(row);counts['shape_points']+=1
                    shape_seen.update(own)
        if used_shapes-shape_seen:raise ValueError('Missing referenced shapes: '+', '.join(sorted(used_shapes-shape_seen)[:20]))
        receipt['counts'].update(counts)
        if progress:progress('Checking ZIP integrity and stored/extracted permissions')
        receipt['archive_verification']=verify_package(staged,FIELDS)
        if progress:progress('Running independent core GTFS validation')
        validation=validate_feed(staged,profile='source-inspection').to_dict()
        receipt['validation']={'decision':validation['decision'],'counts':validation['counts'],'findings':validation['findings'],'suppressed_findings':validation.get('suppressed_findings',0)}
        if any(validation['counts'].get(s,0) for s in ('error','blocker')) and not allow_draft:raise ValueError('Candidate failed GTFS validation; use --allow-draft only for local investigation')
        for k,path in inputs.items():
            if digest(path)!=before[k]:raise ValueError('Source changed during build: '+k)
        receipt['output_sha256']=digest(staged)
        # Exclusive publication: never overwrite even if another process creates
        # the requested path while this long-running build is in progress.
        created=[]
        try:
            with output.open('xb') as dest,staged.open('rb') as src:
                created.append(output);shutil.copyfileobj(src,dest)
            with receipt_path.open('x',encoding='utf-8') as dest:
                created.append(receipt_path);json.dump(receipt,dest,ensure_ascii=False,indent=2)
        except BaseException:
            for own in created:own.unlink(missing_ok=True)
            raise
    return {'output':str(output),'receipt':str(receipt_path),'status':receipt['status'],'counts':receipt['counts'],
            'warning_counts':dict(Counter(w['kind'] for w in warnings)),'validation_counts':receipt['validation']['counts']}
