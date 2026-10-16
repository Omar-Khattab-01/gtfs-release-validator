"""Date-aware source → final checks when only one bus source is available."""
from collections import Counter, defaultdict
from .feed_index import get_index
from .rail import _models, _services, _window


def compare_source_final(source_path, final_path):
    source=get_index(source_path);final=get_index(final_path);window=_window(final)
    source_dates,known=_services(source,window);final_dates,_=_services(final,window)
    final_codes=defaultdict(list)
    for row in final.stops.values():
        if row.get('stop_code'):final_codes[row['stop_code']].append(row['stop_id'])
    translation={}
    source_codes=Counter(row.get('stop_code') for row in source.stops.values() if row.get('stop_code'))
    for stop,record in source.stops.items():
        if stop in final.stops:translation[stop]=stop;continue
        matches=final_codes.get(stop,[])
        if len(matches)!=1 and source_codes[record.get('stop_code')]==1:matches=final_codes.get(record.get('stop_code'),[])
        if len(matches)==1:translation[stop]=matches[0]
    by_name=defaultdict(set)
    for row in source.small_tables.get('routes.txt',[]):by_name[row.get('route_short_name') or row.get('route_id')].add(row.get('route_id'))
    final_by_name=defaultdict(set)
    for row in final.small_tables.get('routes.txt',[]):final_by_name[row.get('route_short_name') or row.get('route_id')].add(row.get('route_id'))
    routes=[]
    for name,route_ids in by_name.items():
        items=_models(source,route_ids,translation)
        final_ids=final_by_name.get(name,set());others=_models(final,final_ids,{})
        eligible=any(source_dates.get(item['record'].get('service_id'),set()) for item in items)
        route_changes=[];stop_changes=[]
        if eligible:
            for first in source.small_tables.get('routes.txt',[]):
                if first.get('route_id') not in route_ids:continue
                for second in final.small_tables.get('routes.txt',[]):
                    if second.get('route_id') not in final_ids:continue
                    fields=[field for field in ('route_type','route_long_name','agency_id','route_color','route_text_color') if first.get(field,'')!=second.get(field,'')]
                    if fields:route_changes.append({'source_route_id':first.get('route_id'),'final_route_id':second.get('route_id'),'fields':fields})
            used={stop for item in items if source_dates.get(item['record'].get('service_id'),set()) for stop in item['source_sequence']}
            for stop in sorted(used):
                first=source.stops.get(stop,{});target=translation.get(stop,stop);second=final.stops.get(target)
                fields=[]
                if second is None:fields=['missing_stop']
                else:
                    for field in ('stop_name','stop_code','stop_desc','location_type','wheelchair_boarding','platform_code','zone_id','stop_timezone','parent_station'):
                        value=first.get(field,'')
                        if field=='parent_station':value=translation.get(value,value)
                        if value!=second.get(field,''):fields.append(field)
                    for field in ('stop_lat','stop_lon'):
                        try:
                            if abs(float(first.get(field,''))-float(second.get(field,'')))>0.000001:fields.append(field)
                        except ValueError:
                            if first.get(field,'')!=second.get(field,''):fields.append(field)
                if fields:stop_changes.append({'source_stop_id':stop,'final_stop_id':target,'fields':fields,'source':first,'final':second})
        changed_stops={row['source_stop_id'] for row in stop_changes}
        by_id=defaultdict(list);by_schedule=defaultdict(list)
        for item in others:by_id[item['canonical']].append(item);by_schedule[item['schedule']].append(item)
        counts=Counter();examples=[];used=set();geometry={}
        def shape(index,shape_id):
            key=(str(index.database),shape_id)
            if key not in geometry:
                rows=index.lookup('shapes.txt',shape_id) if shape_id and 'shapes.txt' in index.columns else []
                rows.sort(key=lambda row:int(row.get('shape_pt_sequence') or 0))
                geometry[key]=tuple((round(float(row['shape_pt_lat']),7),round(float(row['shape_pt_lon']),7)) for row in rows)
            return geometry[key]
        for item in items:
            trip=item['record'];expected=source_dates.get(trip.get('service_id'),set());issues=[]
            candidates=[]
            if not window or trip.get('service_id') not in known:status='unverifiable'
            elif not expected:status='outside_final_window'
            else:
                candidates=by_id[item['canonical']] or [other for other in by_schedule[item['schedule']] if expected & final_dates.get(other['record'].get('service_id'),set())]
                used.update(other['record']['trip_id'] for other in candidates)
                if not candidates:status='missing';issues=['Trip not found in final GTFS']
                else:
                    if set(item['source_sequence']) & changed_stops:issues.append('Stop attributes are missing or changed')
                    coverage=set().union(*(final_dates.get(other['record'].get('service_id'),set()) for other in candidates))
                    if expected-coverage:issues.append(f'{len(expected-coverage)} operating dates missing')
                    for other in candidates:
                        if not expected & final_dates.get(other['record'].get('service_id'),set()):continue
                        if item['sequence']!=other['sequence']:issues.append('Ordered stops differ')
                        elif item['schedule']!=other['schedule']:issues.append('Stop times or boarding rules differ')
                        fields=[field for field in ('direction_id','trip_headsign','wheelchair_accessible','bikes_allowed','block_id') if trip.get(field,'')!=other['record'].get(field,'')]
                        if fields:issues.append('Trip attributes differ: '+', '.join(fields))
                        if trip.get('shape_id'):
                            first=shape(source,trip.get('shape_id'));second=shape(final,other['record'].get('shape_id'))
                            if not first or not second:issues.append('Referenced geometry is missing')
                            elif first!=second:issues.append('Shape geometry differs')
                    status='changed' if issues else 'matching'
            counts[status]+=1
            if status not in {'matching','outside_final_window'} and len(examples)<200:
                examples.append({'trip_id':trip['trip_id'],'route_id':trip.get('route_id'),'shape_id':trip.get('shape_id'),
                                 'status':status,'issues':list(dict.fromkeys(issues)),'final_trip_ids':[other['record']['trip_id'] for other in candidates]})
        routes.append({'route_short_name':name,'route_ids':sorted(route_ids),'final_route_ids':sorted(final_ids),
                       'route_attribute_changes':route_changes,'stop_difference_count':len(stop_changes),'stop_difference_examples':stop_changes[:200],
                       'counts':dict(counts),'examples':examples,'example_limit':200,
                       'status':'needs_review' if route_changes or stop_changes or counts['missing'] or counts['changed'] or counts['unverifiable'] else 'matching' if counts['matching'] else 'outside_final_window'})
    return {'status':'complete','coverage_window':[value.isoformat() for value in window] if window else None,'routes':routes,
            'counts':dict(sum((Counter(route['counts']) for route in routes),Counter()))}
