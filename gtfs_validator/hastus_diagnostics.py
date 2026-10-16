"""Read-only interpretation of the reviewed HASTUS OIG's export messages.

The OIG is never executed or bundled. Internal-source warnings and independently
observed GTFS defects are deliberately separate. Unrecognized text is retained.
"""
from collections import defaultdict
from contextlib import closing
import csv
import io
import re
import sqlite3
import unicodedata


LOG_NAME = 'error_warning.txt'
LOG_LIMIT = 8 * 1024 * 1024
RULES = {
    'scheduling_units': ('Overlapping scheduling units', 'Review scheduling-unit selection in HASTUS; GTFS cannot reconstruct internal units.'),
    'operating_exception': ('Exception has no operating variation', 'Review the service, exception date and operating variations in HASTUS.'),
    'missing_itinerary': ('Pattern has missing itineraries', 'Repair or regenerate the pattern itineraries in HASTUS and re-export. Check every referenced shape.'),
    'deleted_pattern': ('Assigned pattern no longer exists', 'Regenerate the assigned trip patterns for the named vehicle schedule in HASTUS.'),
    'stop_location': ('Non-default stop location', 'Review the pattern’s effective stop-location version in HASTUS; exported GTFS does not retain version IDs.'),
    'destination_names': ('End place has no bilingual name', 'Review the end-place descriptions and exported headsigns. A public-direction fallback may supply the headsign.'),
    'station_code': ('Station usage / stop code discrepancy', 'Review source stop usage and the agency’s 560-code convention. This prefix is not a GTFS requirement.'),
    'stop_usage': ('Stop usage / station code discrepancy', 'Review source stop usage and intended station parentage. Exported location_type alone cannot establish source usage.'),
    'station_description': ('English station description missing', 'Review the English source description. An exported name may still exist through bilingual or station-name fallback.'),
    'route_colours': ('Route colour values missing', 'Review main and secondary route colours. Blank optional colours are agency review items, not required-field errors.'),
    'route_directions': ('Public route directions missing', 'Review both Public Information direction names and the resulting route name / trip headsigns.'),
    'unknown': ('Unrecognized export message', 'Review the original text with the export owner; no automatic interpretation was made.'),
}


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def decode_log(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return raw.decode('utf-16'), 'UTF-16', ''
        except UnicodeError:
            return raw.decode('utf-16', errors='replace'), 'UTF-16 (replacement characters)', 'Invalid UTF-16 bytes were replaced; verify the original log.'
    try:
        return raw.decode('utf-8-sig'), 'UTF-8', ''
    except UnicodeError:
        try:
            return raw.decode('cp1252'), 'Windows-1252 (assumed)', 'Not UTF-8: Windows-1252 was assumed. Verify accented text against the original log.'
        except UnicodeError:
            return raw.decode('utf-8', errors='replace'), 'UTF-8 (replacement characters)', 'Unknown encoding: invalid bytes were replaced; verify the original log.'


def parse_message(raw, line):
    text = ' '.join(raw.split())
    value = folded(text)
    severity = re.match(r'^(warning|error|avertissement|erreur)\s*:', value)
    source_severity = {'warning':'Warning', 'avertissement':'Warning', 'error':'Error', 'erreur':'Error'}.get(severity[1] if severity else '', 'Unspecified')
    kind = 'unknown'
    if 'more than one scheduling unit' in value or "plus d'une unite horaire" in value: kind = 'scheduling_units'
    elif 'no variations operating on the day' in value or 'sans variations en service pour ce jour' in value: kind = 'operating_exception'
    elif 'missing itinerary' in value or 'itineraire manquant' in value: kind = 'missing_itinerary'
    elif 'does not exist anymore' in value or "parcours type assigne n'existant plus" in value: kind = 'deleted_pattern'
    elif 'different from the default stop location' in value or 'differente de la localisation de defaut' in value: kind = 'stop_location'
    elif 'has no name for its last node/timpoint' in value: kind = 'destination_names'
    elif 'usage station but does not have' in value: kind = 'station_code'
    elif 'usage stop not station' in value: kind = 'stop_usage'
    elif 'missing an english station description' in value: kind = 'station_description'
    elif 'colour value' in value and 'is missing its' in value: kind = 'route_colours'
    elif 'missing its public information direction names' in value: kind = 'route_directions'
    entry = {'line':line, 'raw':raw, 'source_severity':source_severity, 'kind':kind,
             'title':RULES[kind][0], 'action':RULES[kind][1], 'assessment':'source_review',
             'evidence':[], 'route_ids':[], 'trip_ids':[], 'shape_id':'', 'pattern_id':''}
    pattern = re.search(r'(?:trip pattern route|parcours type ligne):\s*(\S+)\s+(?:number|numero):\s*(\d+)\b', value)
    if pattern:
        # Preserve original case for internal route identifiers. Padding is a
        # minimum width, never a truncation or last-four-digits heuristic.
        original = re.search(r':\s*(\S+)\s+(?:Number|Num[eé]ro):', text, re.I)
        route = original[1] if original else pattern[1]
        entry.update(internal_route=route, pattern_id=pattern[2], shape_id=route + f'{int(pattern[2]):04d}')
    destination = re.search(r'Trips for route:\s*(\S+)\s+Direction:\s*(.*?)\s+has no name for its last node/timpoint:\s*(.*)', text, re.I)
    if destination:
        entry.update(internal_route=destination[1], public_direction=destination[2], end_place=destination[3])
    location = re.search(r'(?:uses a stop location identifier|utilise une localisation d.arr[eê]t):\s*(\S+)\s+(?:different from the default stop location|diff[eé]rente de la localisation de d[eé]faut):\s*(\S+)', text, re.I)
    if location:entry.update(pattern_stop_location=location[1], default_stop_location=location[2])
    stop = re.search(r'\b(?:Stop|Station)\s+(\S+)\s*\(\s*([^()]+?)\s*\)', text, re.I)
    if stop: entry.update(stop_id=stop[2].strip(), stop_code=stop[1])
    route = re.search(r'\bRoute\s+(\S+)\s+is missing its', text, re.I)
    if route: entry['public_route'] = route[1]
    service = re.search(r'^(?:Error|Erreur):\s*(.*?)\s+(?:is planned|has at least one day exception|est planifi|a au moins une variation)', text, re.I)
    if service: entry['service_id'] = service[1].strip()
    exception = re.search(r'(?:operating on the day|en service pour ce jour):\s*(.*?)\s+(?:for scheduling unit|pour l.unite horaire)\s+(.*?)(?:\.\s|$)', folded(text))
    if exception:entry.update(exception_date=exception[1], scheduling_unit=exception[2])
    return entry


def diagnose(index, times, shapes):
    """Reuse existing counts; never rescan large ZIP tables or infer lost trips."""
    trips = index.small_tables.get('trips.txt', [])
    routes = index.small_tables.get('routes.txt', [])
    by_shape = defaultdict(list)
    for trip in trips: by_shape[trip.get('shape_id', '')].append(trip)
    by_route = {route.get('route_id',''):route for route in routes}
    groups = []
    affected = defaultdict(list)
    for trip in trips:
        shape = trip.get('shape_id', '')
        if shape and shape not in shapes:
            affected[(trip.get('route_id',''), trip.get('direction_id',''), shape)].append(trip)
    for (rid, direction, shape), items in sorted(affected.items()):
        groups.append({'id':str(len(groups)), 'route_id':rid, 'route':by_route.get(rid, {}),
                       'direction_id':direction, 'shape_id':shape, 'trip_count':len(items),
                       'headsigns':sorted({trip.get('trip_headsign','') for trip in items}),
                       'trips':[{**trip, 'stop_time_count':times.get(trip.get('trip_id',''),0)} for trip in items],
                       'stop_time_count':sum(times.get(trip.get('trip_id',''),0) for trip in items),
                       'trips_without_stop_times':sum(not times.get(trip.get('trip_id',''),0) for trip in items),
                       'log_lines':[], 'pattern_ids':[]})
    log = {'status':'not_supplied', 'encoding':'', 'warning':'', 'messages':[]}
    member = next((item for item in index.files if item['name']==LOG_NAME), None)
    if member:
        # Raw log records were decoded once during indexing (including cache restore).
        log_rows = index.rows(LOG_NAME)
        metadata = member.get('text_log', {})
        log.update(status='present' if log_rows else 'empty', encoding=metadata.get('encoding',''), warning=metadata.get('warning',''))
        for record in log_rows:
            raw = record['message']
            if raw.strip(): log['messages'].append(parse_message(raw, record['line_number']))
    missing_shapes = {group['shape_id'] for group in groups}
    for entry in log['messages']:
        candidates = by_shape.get(entry['shape_id'], []) if entry['shape_id'] else []
        if candidates:
            entry['trip_ids'] = [trip.get('trip_id','') for trip in candidates]
            entry['route_ids'] = sorted({trip.get('route_id','') for trip in candidates})
            entry['evidence'].append({'referenced_shape':entry['shape_id'], 'shape_points':shapes.get(entry['shape_id'],0),
                                      'referencing_trips':len(candidates), 'trips_with_stop_times':sum(times.get(trip.get('trip_id',''),0)>0 for trip in candidates)})
            if entry['kind']=='missing_itinerary' and entry['shape_id'] in missing_shapes:
                entry['assessment']='confirmed_defect'
                for group in groups:
                    if group['shape_id']==entry['shape_id']:
                        group['log_lines'].append(entry['line'])
                        if entry['pattern_id'] not in group['pattern_ids']:group['pattern_ids'].append(entry['pattern_id'])
        if entry.get('stop_id'):
            stop = index.stops.get(entry['stop_id'])
            entry['evidence'].append({'stop':stop, 'parent_station':index.stops.get(stop.get('parent_station','')) if stop else None})
        if entry.get('public_route'):
            matched = [route for route in routes if route.get('route_short_name')==entry['public_route']]
            entry['route_ids'] = [route.get('route_id','') for route in matched]
            entry['evidence'].append({'routes':matched, 'mapping':'Public route name; all matching route versions retained.'})
        if entry.get('service_id'):
            entry['evidence'].append({name:[row for row in index.rows(name) if row.get('service_id')==entry['service_id']]
                                      for name in ('calendar.txt','calendar_dates.txt') if name in index.columns})
            service_trips = [trip for trip in trips if trip.get('service_id')==entry['service_id']]
            entry['trip_ids'] = [trip.get('trip_id','') for trip in service_trips]
            entry['route_ids'] = sorted({trip.get('route_id','') for trip in service_trips})
            entry['evidence'].append({'mapping':'Trips referencing this exact service_id; not proof that every linked trip is invalid.',
                                      'exception_date':entry.get('exception_date',''), 'scheduling_unit':entry.get('scheduling_unit','')})
        if entry.get('internal_route') and not entry['route_ids']:
            # The reviewed OIG writes route_id as internal identifier + '-' +
            # version number. Retain all versions and describe this convention.
            matched = [route for route in routes if route.get('route_id','').rpartition('-')[0]==entry['internal_route']
                       and route.get('route_id','').rpartition('-')[2].isdigit()]
            entry['route_ids'] = [route.get('route_id','') for route in matched]
            if matched:entry['evidence'].append({'routes':matched, 'mapping':'OIG internal-route/version route_id convention; no exact trip association inferred.'})
        if entry['kind']=='missing_itinerary' and not candidates:
            entry['evidence'].append({'mapping':'No trips reference the OIG-derived shape ID. Confirm this log belongs to this export; no trip association was guessed.'})
    # Attribute stop warnings to routes using indexed stop-time records in one
    # bounded streaming pass, not one full-table scan per source message.
    stop_entries = defaultdict(list)
    for entry in log['messages']:
        if entry.get('stop_id'):stop_entries[entry['stop_id']].append(entry)
    if stop_entries and 'stop_times.txt' in index.columns:
        stop_trips = defaultdict(set)
        # SQLite extracts only the stop ID; avoid constructing a Python dict
        # for every stop-time row merely to attribute a handful of warnings.
        with closing(sqlite3.connect(index.database.as_uri()+'?mode=ro',uri=True)) as db:
            for tid,stop in db.execute("SELECT parent,json_extract(data,'$.stop_id') FROM records WHERE name='stop_times.txt'"):
                if stop in stop_entries:stop_trips[stop].add(tid)
        trip_routes = {trip.get('trip_id',''):trip.get('route_id','') for trip in trips}
        for stop, entries in stop_entries.items():
            for entry in entries:
                entry['trip_ids']=sorted(stop_trips[stop])
                entry['route_ids']=sorted({trip_routes[tid] for tid in entry['trip_ids'] if tid in trip_routes})
    return {'log':log, 'missing_shapes':groups,
            'counts':{'messages':len(log['messages']), 'source_errors':sum(e['source_severity']=='Error' for e in log['messages']),
                      'unknown_messages':sum(e['kind']=='unknown' for e in log['messages']),
                      'missing_shapes':len(missing_shapes), 'affected_trips':sum(g['trip_count'] for g in groups),
                      'source_review':sum(e['assessment']=='source_review' for e in log['messages'])},
            'rule_inventory':[{'kind':key,'title':value[0],'action':value[1]} for key,value in RULES.items() if key!='unknown']}


def export_trips(diagnostics, group_id=''):
    groups = diagnostics['missing_shapes']
    if group_id:
        groups = [group for group in groups if group['id']==group_id]
        if not groups:raise ValueError('Unknown missing-shape group')
    records = [{**trip, 'oig_pattern_ids':';'.join(group.get('pattern_ids',[]))} for group in groups for trip in group['trips']]
    columns = list(dict.fromkeys(['route_id','oig_pattern_ids','shape_id','trip_id','service_id','trip_headsign','direction_id','block_id','stop_time_count'] + [key for row in records for key in row]))
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in records:
        # Prevent spreadsheet formula execution while leaving ordinary IDs intact.
        writer.writerow({key:("'"+str(value) if str(value).lstrip().startswith(('=','+','-','@')) else value) for key,value in row.items()})
    return output.getvalue().encode('utf-8-sig')
