"""Date-specific departure headways and block evidence for an exported route."""
from collections import Counter, defaultdict
import re
import unicodedata
from statistics import median

from .engine import _time_seconds
from .schedule import route_schedule
from .viewer import _sequence


def _clock(value):
    return _time_seconds(str(value or ''))


def _summary(values):
    return {'count': len(values), 'minimum': min(values) if values else None,
            'median': median(values) if values else None, 'maximum': max(values) if values else None}


TERMINI = {'1': {"Tunney's Pasture", 'Blair', 'Trim'},
           '2': {'Bayview', 'Limebank'}, '4': {'South Keys', 'Airport'}}


def _terminal(name):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().upper()
    text = re.sub(r"[^A-Z0-9 ]", '', text)
    text = ' '.join(text.split()).split(' OTRAIN')[0].split(' O TRAIN')[0]
    return {'TUNNEYS PASTURE': "Tunney's Pasture", 'BLAIR': 'Blair', 'TRIM': 'Trim',
            'BAYVIEW': 'Bayview', 'LIMEBANK': 'Limebank', 'LIME BANK': 'Limebank',
            'SOUTH KEYS': 'South Keys', 'AIRPORT': 'Airport', 'AEROPORT': 'Airport',
            'AIRPORT AEROPORT': 'Airport'}.get(text)


def _rail_route(route):
    return route.get('route_type', '').strip() in {'0', '1', '2', '12'}


def _rail_stations(index, route, trips, calls):
    allowed = TERMINI.get(route.get('route_short_name', '').strip(), set())
    stations, stop_keys = {}, {}
    for trip in trips:
        for call in calls[trip['trip_id'].strip()]:
            sid = call.get('stop_id', '').strip()
            stop = index.stops.get(sid, {})
            parent = stop.get('parent_station', '').strip()
            station = index.stops.get(parent, {}) if parent else stop
            name = station.get('stop_name') or stop.get('stop_name') or sid
            terminal = _terminal(name) or _terminal(stop.get('stop_name', ''))
            key = 'station:' + (parent or sid)
            stop_keys[sid] = key
            item = stations.setdefault(key, {'stop_id': key, 'stop_name': terminal or name,
                                              'stop_ids': set(), 'trip_ids': set(),
                                              'boarding': Counter(), 'terminus': terminal in allowed})
            item['stop_ids'].add(sid)
            item['trip_ids'].add(trip['trip_id'].strip())
            if call.get('pickup_type', '').strip() != '1' and _clock(call.get('departure_time')) is not None:
                item['boarding'][trip.get('direction_id', '').strip()] += 1
    # Some feeds omit parent_station; group the recognized terminus platforms by name.
    for key, item in list(stations.items()):
        if item['terminus']:
            target = 'terminus:' + item['stop_name']
            if target not in stations:
                stations[target] = {**item, 'stop_id': target, 'stop_ids': set(), 'trip_ids': set(), 'boarding': Counter()}
            merged = stations[target]
            merged['stop_ids'].update(item['stop_ids'])
            merged['trip_ids'].update(item['trip_ids'])
            merged['boarding'].update(item['boarding'])
            for sid in item['stop_ids']:
                stop_keys[sid] = target
            del stations[key]
    return stations, stop_keys


def _direction_labels(index, trips, calls, stations, stop_keys):
    origins, destinations = defaultdict(Counter), defaultdict(Counter)
    def name(call):
        sid = call.get('stop_id', '').strip()
        return stations.get(stop_keys.get(sid), {}).get('stop_name') or index.stops.get(sid, {}).get('stop_name', sid)
    for trip in trips:
        ordered = calls[trip['trip_id'].strip()]
        if not ordered:
            continue
        direction = trip.get('direction_id', '').strip()
        origins[direction][name(ordered[0])] += 1
        destinations[direction][name(ordered[-1]) or trip.get('trip_headsign', '')] += 1
    return {direction: f"{origin.most_common(1)[0][0]} → {destinations[direction].most_common(1)[0][0]}"
            for direction, origin in origins.items()}


def route_headways(index, day, route_id, direction=None, stop_id='', threshold=None):
    routes = {route['route_id']: route for route in index.rows('routes.txt')}
    if route_id not in routes:
        raise ValueError('Select a route from this export')
    if threshold is not None and not 0 < threshold <= 1440:
        raise ValueError('Gap threshold must be between 0 and 1440 minutes')
    trips, calls = route_schedule(index, day, route_id)
    directions = sorted({trip.get('direction_id', '').strip() for trip in trips}, key=_sequence)
    selected_direction = direction if direction is not None else next(iter(directions), '')
    if selected_direction != 'all' and selected_direction not in directions and directions:
        raise ValueError('This direction has no trip records on the selected date')
    rail = _rail_route(routes[route_id])
    stations, stop_keys = _rail_stations(index, routes[route_id], trips, calls) if rail else ({}, {})
    labels = _direction_labels(index, trips, calls, stations, stop_keys)
    default_termini = rail and bool(TERMINI.get(routes[route_id].get('route_short_name', '').strip()))
    direction_adjusted = False
    if rail and stop_id and stop_id != '@termini':
        # Accept a raw platform or parent station ID as well as station selector IDs.
        stop_id = stop_keys.get(stop_id, stop_id)
        if stop_id not in stations:
            stop_id = next((key for key, item in stations.items()
                            if any(index.stops.get(sid, {}).get('parent_station', '').strip() == stop_id
                                   for sid in item['stop_ids'])), stop_id)
        boarding = stations.get(stop_id, {}).get('boarding', {})
        if selected_direction != 'all' and boarding and not boarding.get(selected_direction):
            selected_direction = max(boarding, key=boarding.get)
            direction_adjusted = True
    selected = [trip for trip in trips if selected_direction == 'all' or trip.get('direction_id', '').strip() == selected_direction]
    issues = []
    stop_trips = defaultdict(set)
    stop_positions = defaultdict(list)
    for trip in selected:
        trip_id = trip['trip_id'].strip()
        for position, call in enumerate(calls[trip_id]):
            sid = call.get('stop_id', '').strip()
            stop_trips[sid].add(trip_id)
            stop_positions[sid].append(position)
    stops = [{'stop_id': sid, 'stop_name': index.stops.get(sid, {}).get('stop_name', sid), 'trip_count': len(ids)}
             for sid, ids in stop_trips.items()]
    stops.sort(key=lambda stop: (-stop['trip_count'], sum(stop_positions[stop['stop_id']]) / len(stop_positions[stop['stop_id']]), stop['stop_id']))
    if rail:
        stops = [{'stop_id': key, 'stop_name': item['stop_name'], 'trip_count': len(item['trip_ids']),
                  'stop_ids': sorted(item['stop_ids']), 'terminus': item['terminus'],
                  'boarding_departures': sum(item['boarding'].values())} for key, item in stations.items()]
        stops.sort(key=lambda item: (not item['terminus'], item['stop_name']))
        if default_termini:
            stops.insert(0, {'stop_id': '@termini', 'stop_name': 'Terminus departures (by direction)',
                             'trip_count': len(trips), 'terminus': True, 'stop_ids': []})
    if stop_id and stop_id not in {item['stop_id'] for item in stops}:
        raise ValueError('This stop is not served by the selected route and date')
    selected_stop = stop_id or ('@termini' if default_termini else (stops[0]['stop_id'] if stops else ''))
    measurement_name = next((item['stop_name'] for item in stops if item['stop_id'] == selected_stop), '')
    departures = []
    records = []
    no_boarding = 0
    missing_times = 0
    for trip in selected:
        trip_id = trip['trip_id'].strip()
        ordered = calls[trip_id]
        first, last = (ordered[0], ordered[-1]) if ordered else ({}, {})
        row = {**trip, 'trip_id': trip_id, 'first_time': first.get('departure_time') or first.get('arrival_time') or '',
               'last_time': last.get('arrival_time') or last.get('departure_time') or '',
               'first_stop': index.stops.get(first.get('stop_id', '').strip(), {}).get('stop_name', first.get('stop_id', '')),
               'last_stop': index.stops.get(last.get('stop_id', '').strip(), {}).get('stop_name', last.get('stop_id', '')),
               'stop_count': len(ordered)}
        records.append(row)
        for position, call in enumerate(ordered):
            sid = call.get('stop_id', '').strip()
            measurement = stop_keys.get(sid, sid)
            if selected_stop == '@termini':
                if position != 0 or not stations.get(measurement, {}).get('terminus'):
                    continue
            elif (measurement if rail else sid) != selected_stop:
                continue
            if call.get('pickup_type', '').strip() == '1':
                no_boarding += 1
                continue
            clock = call.get('departure_time', '').strip()
            seconds = _clock(clock)
            if seconds is None:
                missing_times += 1
                continue
            departures.append({'stop_id': sid, 'stop_name': index.stops.get(sid, {}).get('stop_name', sid),
                               'station_id': measurement, 'station_name': stations.get(measurement, {}).get('stop_name', index.stops.get(sid, {}).get('stop_name', sid)),
                               'trip_id': trip_id, 'time': clock, 'seconds': seconds,
                               'sequence': call.get('stop_sequence', ''), 'direction_id': trip.get('direction_id', '').strip(),
                               'block_id': trip.get('block_id', ''), 'pickup_type': call.get('pickup_type', '')})
    departures.sort(key=lambda item: (item['seconds'], item['direction_id'], item['station_id'], item['trip_id'], _sequence(item['sequence'])))
    previous = {}
    hourly = defaultdict(list)
    gaps = []
    by_trip = defaultdict(list)
    for departure in departures:
        group = (departure['direction_id'], departure['station_id'])
        previous_departure = previous.get(group)
        gap = departure['seconds'] - previous_departure['seconds'] if previous_departure else None
        departure['headway_seconds'] = gap
        departure['previous_trip_id'] = previous_departure['trip_id'] if previous_departure else ''
        by_trip[departure['trip_id']].append(departure)
        previous[group] = departure
        hourly[(departure['seconds'] // 3600, departure['direction_id'], departure['station_id'])].append(gap)
        if gap is not None:
            gaps.append(gap)
            if gap == 0:
                issues.append({'kind': 'simultaneous_departure', 'trip_id': departure['trip_id'],
                               'station_name': departure['station_name'], 'direction_id': departure['direction_id'],
                               'other_trip_id': departure['previous_trip_id'], 'time': departure['time'],
                               'message': 'Two calls have the same departure time at this stop and direction.'})
            if threshold is not None and gap > threshold * 60:
                issues.append({'kind': 'long_gap', 'trip_id': departure['trip_id'],
                               'station_name': departure['station_name'], 'direction_id': departure['direction_id'],
                               'previous_trip_id': departure['previous_trip_id'], 'headway_seconds': gap,
                               'message': 'Departure gap exceeds the selected review threshold.'})
    for row in records:
        row['departures'] = by_trip[row['trip_id']]

    blocks = defaultdict(list)
    for trip in trips:
        trip_id = trip['trip_id'].strip()
        block = trip.get('block_id', '').strip()
        if not block or not calls[trip_id]:
            continue
        start = _clock(calls[trip_id][0].get('departure_time'))
        end = _clock(calls[trip_id][-1].get('arrival_time'))
        if start is not None and end is not None and end >= start:
            blocks[block].append((start, end, trip_id))
    for block, intervals in blocks.items():
        previous_interval = None
        for interval in sorted(intervals):
            if previous_interval and interval[0] < previous_interval[1]:
                issues.append({'kind': 'block_overlap', 'block_id': block, 'trip_id': interval[2],
                               'other_trip_id': previous_interval[2], 'overlap_seconds': previous_interval[1] - interval[0],
                               'message': 'Trip times overlap within this route on the same block and service date.'})
            if previous_interval is None or interval[1] > previous_interval[1]:
                previous_interval = interval
    def record_key(row):
        clock = row['departures'][0]['seconds'] if row['departures'] else _clock(row['first_time'])
        return clock is None, clock or 0, row['trip_id']
    records.sort(key=record_key)
    hourly_rows = []
    hours_by_direction = defaultdict(list)
    for hour, direction_id, station_id in hourly:
        hours_by_direction[(direction_id, station_id)].append(hour)
    for (direction_id, station_id), hours in hours_by_direction.items():
        for hour in range(min(hours), max(hours) + 1):
            values = hourly.get((hour, direction_id, station_id), [])
            hourly_rows.append({'hour': hour, 'direction_id': direction_id, 'station_name': stations.get(station_id, {}).get('stop_name', measurement_name), 'departures': len(values),
                                **_summary([value for value in values if value is not None])})
    hourly_rows.sort(key=lambda item: (item['hour'], item['direction_id'], item['station_name']))
    return {'date': day.isoformat(), 'route': routes[route_id], 'directions': directions, 'direction': selected_direction,
            'direction_labels': labels, 'direction_adjusted': direction_adjusted, 'rail': rail,
            'measurement_name': measurement_name, 'terminus_mode': selected_stop == '@termini',
            'stops': stops, 'stop_id': selected_stop, 'trips': records, 'departures': departures, 'headways': _summary(gaps),
            'hourly': hourly_rows,
            'issues': issues, 'block_count': len({row.get('block_id') for row in records if row.get('block_id')}),
            'unassigned_blocks': sum(not row.get('block_id', '').strip() for row in records),
            'excluded_no_pickup_calls': no_boarding, 'missing_departure_times': missing_times,
            'not_at_stop': sum(not row['departures'] for row in records),
            'measurement_notice': ('No recognized terminus departures on this date. Inspect the trip endpoints and station names.'
                                   if selected_stop == '@termini' and not departures else '')}
