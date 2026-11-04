"""Scheduled service by date, using the validator's existing read-only index."""

from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date

from .engine import _time_seconds
from .inspection import RAIL_TYPES
from .rail import _date, _services
from .viewer import _sequence


GROUPS = ('bus', 'line1', 'lines24', 'other')


def service_group(route):
    route_type = route.get('route_type')
    if route_type in {'3', '11'}:
        return 'bus'
    if route_type in RAIL_TYPES:
        number = route.get('route_short_name')
        if number == '1':
            return 'line1'
        if number in {'2', '4'}:
            return 'lines24'
    return 'other'


def service_bounds(index):
    dates = []
    for name, fields in (('calendar.txt', ('start_date', 'end_date')), ('calendar_dates.txt', ('date',))):
        if name in index.columns:
            for row in index.rows(name):
                dates.extend(day for field in fields if (day := _date(row.get(field))))
    if not dates:
        raise ValueError('This export has no readable service dates in calendar.txt or calendar_dates.txt')
    return min(dates), max(dates)


def _route_key(route):
    name = route.get('route_short_name') or route['route_id']
    return _sequence(name), route['route_id']


def _matching_routes(index, search):
    routes = index.small_tables.get('routes.txt', [])
    needle = search.strip().casefold()
    exact = [route for route in routes if needle in (route.get('route_short_name', '').casefold(), route['route_id'].casefold())]
    if needle and (exact or needle.isdecimal()):
        routes = exact
    elif needle:
        routes = [route for route in routes if needle in route.get('route_long_name', '').casefold()
                  or needle in route.get('route_short_name', '').casefold() or needle in route['route_id'].casefold()]
    return {route['route_id']: route for route in sorted(routes, key=_route_key)}


def _day_rows(index, start, end, search):
    routes = _matching_routes(index, search)
    services, _ = _services(index, (start, end))
    days = defaultdict(set)
    for service_id, dates in services.items():
        for day in dates:
            days[day].add(service_id)
    changes = defaultdict(dict)
    if 'calendar_dates.txt' in index.columns:
        for row in index.rows('calendar_dates.txt'):
            day = _date(row.get('date'))
            if day and start <= day <= end:
                changes[day.isoformat()][row['service_id']] = row.get('exception_type')

    by_service = defaultdict(Counter)
    for trip in index.small_tables.get('trips.txt', []):
        if trip.get('route_id') in routes:
            by_service[trip.get('service_id', '')][trip['route_id']] += 1

    result = []
    for ordinal in range(start.toordinal(), end.toordinal() + 1):
        day = date.fromordinal(ordinal).isoformat()
        route_counts = defaultdict(dict)
        groups = {key: {'routes': [], 'service_ids': set(), 'trip_count': 0, 'added': set(), 'removed': set()} for key in GROUPS}
        for service in days[day]:
            for route_id, count in by_service[service].items():
                route_counts[route_id][service] = count
        for route_id, route in routes.items():
            counts = route_counts.get(route_id)
            if not counts:
                continue
            group = groups[service_group(route)]
            added = sum(count for service, count in counts.items() if changes[day].get(service) == '1')
            group['routes'].append({**route, 'trip_count': sum(counts.values()), 'services': counts, 'added_trips': added})
            group['service_ids'].update(counts)
            group['trip_count'] += sum(counts.values())
        for service, exception in changes[day].items():
            if exception in {'1', '2'}:
                for route_id in by_service[service]:
                    groups[service_group(routes[route_id])]['added' if exception == '1' else 'removed'].add(service)
        for group in groups.values():
            group['route_count'] = len(group['routes'])
            for key in ('service_ids', 'added', 'removed'):
                group[key] = sorted(group[key], key=_sequence)
        result.append({'date': day, 'groups': groups})
    return result


def calendar_month(index, month, search):
    first, last = service_bounds(index)
    selected = date.fromisoformat(month + '-01') if month else min(max(date.today(), first), last).replace(day=1)
    end = selected.replace(day=monthrange(selected.year, selected.month)[1])
    days = _day_rows(index, selected, end, search)
    for item in days:
        for group in item['groups'].values():
            del group['routes']
    return {'month': selected.isoformat()[:7], 'first_date': first.isoformat(), 'last_date': last.isoformat(), 'days': days}


def calendar_day(index, day, search):
    return _day_rows(index, day, day, search)[0]


def calendar_trips(index, day, route_id, service_id):
    services, _ = _services(index, (day, day))
    active = {service for service, dates in services.items() if day.isoformat() in dates}
    trips = [trip for trip in index.lookup('trips.txt', route_id)
             if trip.get('service_id', '').strip() in active and (not service_id or trip['service_id'].strip() == service_id)]
    times = defaultdict(list)
    if 'stop_times.txt' in index.columns:
        for row in index.lookup_many('stop_times.txt', list({trip['trip_id'].strip() for trip in trips})):
            times[row['trip_id'].strip()].append(row)
    for trip in trips:
        calls = sorted(times[trip['trip_id'].strip()], key=lambda row: _sequence(row.get('stop_sequence')))
        for prefix, call in (('first', calls[0] if calls else {}), ('last', calls[-1] if calls else {})):
            stop_id = (call.get('stop_id') or '').strip()
            trip[prefix + '_stop_id'] = stop_id
            trip[prefix + '_stop_name'] = index.stops.get(stop_id, {}).get('stop_name', '')
            preferred, fallback = ('departure_time', 'arrival_time') if prefix == 'first' else ('arrival_time', 'departure_time')
            trip[prefix + '_time'] = (call.get(preferred) or call.get(fallback) or '').strip()

    def departure_key(trip):
        seconds = _time_seconds(trip['first_time'])
        return (seconds is None, seconds or 0, trip['trip_id'])

    return {'trips': sorted(trips, key=departure_key)}
