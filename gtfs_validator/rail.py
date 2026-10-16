"""Independent rail inspection and date-aware rail → final comparison."""
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
import csv
import sqlite3
import zipfile
from .feed_index import get_index
from .engine import validate_feed
from .details import _translation, _align_sequences


def _date(value):
    try:
        return datetime.strptime(value, '%Y%m%d').date()
    except (ValueError, TypeError):
        return None


def _window(index):
    info = index.rows('feed_info.txt') if 'feed_info.txt' in index.columns else []
    if info:
        start,end = _date(info[0].get('feed_start_date')), _date(info[0].get('feed_end_date'))
        if start and end and start <= end:
            return start,end
    dates = []
    for name,fields in [('calendar.txt',('start_date','end_date')),('calendar_dates.txt',('date',))]:
        for row in index.rows(name) if name in index.columns else []:
            dates.extend(value for field in fields if (value := _date(row.get(field))))
    return (min(dates),max(dates)) if dates else None


def _services(index,window):
    dates,known = defaultdict(set),set()
    days = ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')
    for row in index.rows('calendar.txt') if 'calendar.txt' in index.columns else []:
        service = row.get('service_id',''); known.add(service)
        start,end = _date(row.get('start_date')), _date(row.get('end_date'))
        if not start or not end or start>end:
            continue
        if window:
            start,end = max(start,window[0]),min(end,window[1])
        if (end-start).days > 3660:
            raise ValueError('Rail calendar exceeds the ten-year inspection limit')
        while start <= end:
            if row.get(days[start.weekday()]) == '1': dates[service].add(start.isoformat())
            start += timedelta(days=1)
    for row in index.rows('calendar_dates.txt') if 'calendar_dates.txt' in index.columns else []:
        service = row.get('service_id',''); known.add(service)
        day = _date(row.get('date'))
        if not day or (window and not window[0] <= day <= window[1]): continue
        if row.get('exception_type') == '1': dates[service].add(day.isoformat())
        elif row.get('exception_type') == '2': dates[service].discard(day.isoformat())
    return dates,known


def _canonical(trip):
    value,service = trip.get('trip_id',''),trip.get('service_id','')
    suffix = '-'+service
    return value[:-len(suffix)] if service and value.endswith(suffix) else value


def _models(index,route_ids,translation):
    trips = [trip for trip in index.small_tables.get('trips.txt',[]) if trip.get('route_id') in route_ids]
    times = defaultdict(list)
    for row in index.lookup_many('stop_times.txt',[trip['trip_id'] for trip in trips]):
        times[row.get('trip_id','')].append(row)
    models = []
    for trip in trips:
        rows = sorted(times[trip['trip_id']],key=lambda row:int(row.get('stop_sequence') or 0))
        sequence = tuple(translation.get(row.get('stop_id','').strip(),row.get('stop_id','').strip()) for row in rows)
        schedule = tuple((stop,*(row.get(field,'').strip() for field in ('arrival_time','departure_time','pickup_type','drop_off_type','timepoint'))) for stop,row in zip(sequence,rows))
        models.append({'record':trip,'sequence':sequence,'schedule':schedule,'canonical':_canonical(trip),
                       'source_sequence':tuple(row.get('stop_id','').strip() for row in rows),
                       'first_time':rows[0].get('departure_time','') if rows else '', 'last_time':rows[-1].get('arrival_time','') if rows else ''})
    return models


def audit_rail(rail_path,final_path,cad_path,bus_path,report):
    source = get_index(rail_path)
    source_checks = validate_feed(rail_path,profile='source-inspection')
    for finding in source_checks.findings:
        report.add('RAIL001',finding.severity,'Rail validation',finding.title,finding.message,
                   file='HASTUS rail:'+str(finding.file or ''),row=finding.row,key=finding.key,
                   context={'rail_source_rule':finding.rule_id})
    with open(rail_path,'rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    report.stats.setdefault('inputs',{})['HASTUS rail'] = {'path':str(source.path),'sha256':digest.hexdigest()}
    routes = source.small_tables.get('routes.txt',[])
    route_names = {route.get('route_short_name','').strip() for route in routes}
    contamination = []
    for label,path in [('CleverCAD',cad_path),('HASTUS bus',bus_path)]:
        if not path:continue
        try:other = get_index(path)
        except (OSError,ValueError,KeyError,UnicodeError,csv.Error,sqlite3.Error,zipfile.BadZipFile,RuntimeError) as exc:
            report.add('RAIL021','warning','Rail isolation','Bus-source overlap check unavailable',f'{label}: {exc}')
            continue
        for route in other.small_tables.get('routes.txt',[]):
            if route.get('route_short_name','').strip() in route_names:
                item={'source':label,'route':route,'trip_count':sum(trip.get('route_id')==route.get('route_id') for trip in other.small_tables.get('trips.txt',[]))}
                contamination.append(item)
                report.add('RAIL020','warning','Rail isolation','Rail route unexpectedly appears in a bus source',
                           f"Line {route.get('route_short_name')} appears in {label}; it is excluded from bus-to-bus comparison, not used as a rail reference.",
                           context={'route_short_name':route.get('route_short_name'),'source':label})
    final = get_index(final_path) if final_path else None
    window = _window(final) if final else None
    source_dates,known_source = _services(source,window)
    final_dates,known_final = _services(final,window) if final else ({},set())
    translation = _translation(final.stops,source.stops) if final else {}
    for stop in source.stops:
        if final and stop in final.stops:translation[stop]=stop
    source_models = _models(source,{route.get('route_id') for route in routes},translation)
    rail_final_routes = [route for route in final.small_tables.get('routes.txt',[]) if route.get('route_short_name','').strip() in route_names] if final else []
    final_models = _models(final,{route.get('route_id') for route in rail_final_routes},{}) if final else []
    stop_differences=[]
    if final and window:
        used_stops={stop for item in source_models if source_dates.get(item['record'].get('service_id'),set()) for stop in item['source_sequence']}
        used_stops |= {source.stops[stop].get('parent_station','') for stop in list(used_stops) if stop in source.stops} - {''}
        for stop_id in sorted(used_stops):
            first=source.stops.get(stop_id,{})
            target=translation.get(stop_id,stop_id);second=final.stops.get(target)
            changed=[]
            if second is None:changed=['unmapped_or_missing_stop']
            else:
                for field in ('stop_name','stop_code','stop_desc','location_type','wheelchair_boarding','platform_code','stop_timezone','zone_id','parent_station'):
                    expected=first.get(field,'')
                    if field=='parent_station':expected=translation.get(expected,expected)
                    if expected!=second.get(field,''):changed.append(field)
                for field in ('stop_lat','stop_lon'):
                    try:
                        if abs(float(first.get(field,''))-float(second.get(field,'')))>0.000001:changed.append(field)
                    except ValueError:
                        if first.get(field,'')!=second.get(field,''):changed.append(field)
            if changed:
                stop_differences.append({'rail_stop_id':stop_id,'final_stop_id':target if second else None,'fields':changed,'rail':first,'final':second})
                report.add('RAIL006','warning','Rail comparison','Rail stop is missing, unmapped or changed',
                           f"Rail stop {stop_id}: "+', '.join(changed),key=stop_id,context={'rail_stop_id':stop_id,'final_stop_id':target,'difference_fields':changed})
    changed_stop_ids={item['rail_stop_id'] for item in stop_differences}
    geometry_cache = {}
    def geometry(index,shape_id):
        key=(str(index.database),shape_id)
        if key not in geometry_cache:
            rows=index.lookup('shapes.txt',shape_id) if shape_id and 'shapes.txt' in index.columns else []
            rows.sort(key=lambda row:int(row.get('shape_pt_sequence') or 0))
            geometry_cache[key]=tuple((round(float(row['shape_pt_lat']),7),round(float(row['shape_pt_lon']),7)) for row in rows)
        return geometry_cache[key]
    route_results=[]
    for route in sorted(routes,key=lambda row:row.get('route_short_name','').zfill(5)):
        name=route.get('route_short_name','').strip()
        source_items=[item for item in source_models if item['record'].get('route_id')==route.get('route_id')]
        final_route_ids={row.get('route_id') for row in rail_final_routes if row.get('route_short_name','').strip()==name}
        final_items=[item for item in final_models if item['record'].get('route_id') in final_route_ids]
        route_changes=[]
        for other in rail_final_routes:
            if other.get('route_id') not in final_route_ids:continue
            changes=[field for field in ('route_type','route_long_name','route_color','route_text_color','agency_id') if route.get(field,'')!=other.get(field,'')]
            if changes:
                route_changes.append({'final_route_id':other.get('route_id'),'fields':changes})
                report.add('RAIL005','warning','Rail comparison','Rail route attributes differ',f"Line {name}: "+', '.join(changes),context={'route_short_name':name,'difference_fields':changes})
        by_id,by_schedule=defaultdict(list),defaultdict(list)
        for item in final_items:
            by_id[item['canonical']].append(item);by_schedule[item['schedule']].append(item)
        variations={};trip_results=[];used_final=set()
        for item in source_items:
            trip=item['record'];key=(trip.get('direction_id',''),item['sequence'],trip.get('shape_id',''))
            variation=variations.setdefault(key,{'variation_id':f'Rail V{len(variations)+1}','shape_id':trip.get('shape_id',''),'direction_id':trip.get('direction_id',''),
                'stop_count':len(item['sequence']),'example_trip_id':trip['trip_id'],'trips':[]})
            result={'trip_id':trip['trip_id'],'record':trip,'first_time':item['first_time'],'last_time':item['last_time'],
                    'stop_count':len(item['sequence']),'status':'not_compared','issues':[],'final_trip_ids':[],'matching_method':'none'}
            expected=source_dates.get(trip.get('service_id'),set())
            if final:
                if not window or trip.get('service_id') not in known_source:
                    result['status']='unverifiable';result['issues'].append('Service dates cannot be established; not a pass.')
                elif not expected:
                    result['status']='outside_final_window'
                else:
                    candidates=by_id[item['canonical']]
                    result['matching_method']='canonical trip ID' if candidates else 'exact stop schedule and operating dates'
                    if not candidates:candidates=[other for other in by_schedule[item['schedule']] if final_dates.get(other['record'].get('service_id'),set()) & expected]
                    result['final_trip_ids']=[other['record']['trip_id'] for other in candidates]
                    used_final.update(result['final_trip_ids'])
                    if not candidates:
                        result['status']='missing';result['issues'].append('Trip is missing from final GTFS in its publication window.')
                    else:
                        covered=set()
                        for other in candidates:
                            covered.update(final_dates.get(other['record'].get('service_id'),set()))
                        result['missing_dates']=sorted(expected-covered)
                        stop_ids=set(item['source_sequence'])
                        stop_ids |= {source.stops.get(stop,{}).get('parent_station','') for stop in list(stop_ids)} - {''}
                        if stop_ids & changed_stop_ids:result['issues'].append('Rail stop attributes are missing, unmapped or changed.')
                        if result['missing_dates']:result['issues'].append('Operating dates missing from final GTFS.')
                        if not any(final_dates.get(other['record'].get('service_id'),set()) & expected for other in candidates):
                            result['issues'].append("No matched final service operates on this source trip's expected dates.")
                        # A candidate must preserve both the schedule and trip metadata;
                        # same IDs alone are evidence of identity, not evidence of equality.
                        fields=('trip_headsign','direction_id','wheelchair_accessible','bikes_allowed','block_id','trip_short_name')
                        for other in candidates:
                            if not (final_dates.get(other['record'].get('service_id'),set()) & expected):continue
                            changes=[field for field in fields if trip.get(field,'')!=other['record'].get(field,'')]
                            if item['sequence']!=other['sequence']:result['issues'].append('Ordered stop sequence differs.')
                            elif item['schedule']!=other['schedule']:result['issues'].append('Stop times or boarding rules differ.')
                            if changes:result['issues'].append('Trip attributes differ: '+', '.join(changes))
                            shape=geometry(source,trip.get('shape_id',''));other_shape=geometry(final,other['record'].get('shape_id',''))
                            if not shape or not other_shape:result['issues'].append('Referenced shape geometry is missing.')
                            elif shape!=other_shape:result['issues'].append('Shape geometry differs.')
                        result['issues']=list(dict.fromkeys(result['issues']))
                        result['status']='issues' if result['issues'] else 'matching'
            variation['trips'].append(result);trip_results.append(result)
            if result['status'] in {'missing','issues','unverifiable'}:
                report.add('RAIL002','error' if result['status']=='missing' else 'warning','Rail comparison',
                           'Rail trip requires review',f"Line {name}: "+' '.join(result['issues']),key=trip['trip_id'],
                           context={'route_short_name':name,'rail_trip_id':trip['trip_id'],'final_trip_ids':result['final_trip_ids'],'variation_id':variation['variation_id']})
        has_expected=any(trip['status']!='outside_final_window' for trip in trip_results)
        extra=[{'trip_id':item['record']['trip_id'],'record':item['record'],'first_time':item['first_time'],'last_time':item['last_time']} for item in final_items if has_expected and item['record']['trip_id'] not in used_final and final_dates.get(item['record'].get('service_id'),set())]
        for item in extra:
            report.add('RAIL003','warning','Rail comparison','Final rail trip has no matched rail source',
                       f"Line {name}: final trip {item['trip_id']} has no identity or exact timetable match in the supplied rail export.",key=item['trip_id'],context={'route_short_name':name,'final_trip_id':item['trip_id']})
        for variation in variations.values():
            eligible=[trip for trip in variation['trips'] if trip['status']!='outside_final_window']
            variation['status']='not_compared' if not final else 'outside_final_window' if not eligible else 'missing' if all(trip['status']=='missing' for trip in eligible) else 'issues' if any(trip['status']!='matching' for trip in eligible) else 'matching'
            variation['trip_count']=len(variation['trips'])
        counts={state:sum(trip['status']==state for trip in trip_results) for state in ('matching','missing','issues','unverifiable','outside_final_window','not_compared')}
        if final and not final_route_ids and counts['missing']:
            report.add('RAIL004','error','Rail comparison','Rail route is missing from final GTFS',f'Line {name} has scheduled service in the final publication window, but no final route.',context={'route_short_name':name})
        if not source_items:report.add('RAIL008','warning','Rail validation','Rail route has no source trips',f'Line {name} has a routes.txt record but no trips.',context={'route_short_name':name})
        status='not_compared' if not final else 'issues' if route_changes or extra or counts['missing'] or counts['issues'] or counts['unverifiable'] or not source_items else 'outside_final_window' if not counts['matching'] else 'matching'
        route_results.append({'route':route,'route_short_name':name,'status':status,'counts':counts,'trip_count':len(trip_results),
                              'variations':list(variations.values()),'final_routes':[row for row in rail_final_routes if row.get('route_id') in final_route_ids],
                              'route_attribute_changes':route_changes,'final_variation_count':len({(item['record'].get('direction_id'),item['sequence'],item['record'].get('shape_id')) for item in final_items}),
                              'extra_final_trips':extra})
    return {'status':'compared' if final else 'not_compared','coverage_window':[day.isoformat() for day in window] if window else None,
            'source_checks':source_checks.to_dict(),'routes':route_results,'unexpected_bus_sources':contamination,
            'trip_count':len(source_models),'variation_count':sum(len(route['variations']) for route in route_results),'stop_differences':stop_differences,
            'stop_mapping':{'mapped':len(translation),'source_stops':len(source.stops),'method':'Exact stop ID or unique final operational stop_code; never shared station codes alone.'}}


def trip_evidence(rail_path,final_path,trip_id,final_trip_id=''):
    from .viewer import trip_detail
    source=trip_detail(rail_path,trip_id)
    final=trip_detail(final_path,final_trip_id) if final_path and final_trip_id else None
    translation=_translation(get_index(final_path).stops,get_index(rail_path).stops) if final_path else {}
    for stop in source['stops']:
        stop['canonical_stop_id']=translation.get(stop['source_stop_id'],stop['source_stop_id'])
    alignment=_align_sequences([{'stops':source['stops']},{'stops':final['stops']}],compare_schedule=True) if final else []
    service={}
    for label,path,trip in [('rail',rail_path,source['trip']),('final',final_path,final['trip'] if final else None)]:
        if not trip:continue
        index=get_index(path);id=trip.get('service_id','')
        service[label]={name:[row for row in index.rows(name) if row.get('service_id')==id] for name in ('calendar.txt','calendar_dates.txt') if name in index.columns}
    return {'rail':source,'final':final,'alignment':alignment,'service':service}
