"""Date-specific departure headways and block evidence for an exported route."""
from collections import defaultdict
from statistics import median

from .engine import _time_seconds
from .schedule import route_schedule
from .viewer import _sequence


def _clock(value):
    return _time_seconds(str(value or ''))


def _summary(values):
    return {'count': len(values), 'minimum': min(values) if values else None,
            'median': median(values) if values else None, 'maximum': max(values) if values else None}


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
    if stop_id and stop_id not in stop_trips:
        raise ValueError('This stop is not served by the selected route, date and direction')
    selected_stop = stop_id or (stops[0]['stop_id'] if stops else '')
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
        for call in ordered:
            if call.get('stop_id', '').strip() != selected_stop:
                continue
            if call.get('pickup_type', '').strip() == '1':
                no_boarding += 1
                continue
            clock = call.get('departure_time', '').strip()
            seconds = _clock(clock)
            if seconds is None:
                missing_times += 1
                continue
            departures.append({'trip_id': trip_id, 'time': clock, 'seconds': seconds,
                               'sequence': call.get('stop_sequence', ''), 'direction_id': trip.get('direction_id', '').strip(),
                               'block_id': trip.get('block_id', ''), 'pickup_type': call.get('pickup_type', '')})
    departures.sort(key=lambda item: (item['seconds'], item['direction_id'], item['trip_id'], _sequence(item['sequence'])))
    previous = {}
    hourly = defaultdict(list)
    gaps = []
    by_trip = defaultdict(list)
    for departure in departures:
        previous_departure = previous.get(departure['direction_id'])
        gap = departure['seconds'] - previous_departure['seconds'] if previous_departure else None
        departure['headway_seconds'] = gap
        departure['previous_trip_id'] = previous_departure['trip_id'] if previous_departure else ''
        by_trip[departure['trip_id']].append(departure)
        previous[departure['direction_id']] = departure
        hourly[(departure['seconds'] // 3600, departure['direction_id'])].append(gap)
        if gap is not None:
            gaps.append(gap)
            if gap == 0:
                issues.append({'kind': 'simultaneous_departure', 'trip_id': departure['trip_id'],
                               'other_trip_id': departure['previous_trip_id'], 'time': departure['time'],
                               'message': 'Two calls have the same departure time at this stop and direction.'})
            if threshold is not None and gap > threshold * 60:
                issues.append({'kind': 'long_gap', 'trip_id': departure['trip_id'],
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
    for hour, direction_id in hourly:
        hours_by_direction[direction_id].append(hour)
    for direction_id, hours in hours_by_direction.items():
        for hour in range(min(hours), max(hours) + 1):
            values = hourly.get((hour, direction_id), [])
            hourly_rows.append({'hour': hour, 'direction_id': direction_id, 'departures': len(values),
                                **_summary([value for value in values if value is not None])})
    hourly_rows.sort(key=lambda item: (item['hour'], item['direction_id']))
    return {'date': day.isoformat(), 'route': routes[route_id], 'directions': directions, 'direction': selected_direction,
            'stops': stops, 'stop_id': selected_stop, 'trips': records, 'departures': departures, 'headways': _summary(gaps),
            'hourly': hourly_rows,
            'issues': issues, 'block_count': len({row.get('block_id') for row in records if row.get('block_id')}),
            'unassigned_blocks': sum(not row.get('block_id', '').strip() for row in records),
            'excluded_no_pickup_calls': no_boarding, 'missing_departure_times': missing_times,
            'not_at_stop': sum(not row['departures'] for row in records)}
