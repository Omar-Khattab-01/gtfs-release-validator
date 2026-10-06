from __future__ import annotations


REQUIRED_COLUMNS: dict[str, set[str]] = {
    "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
    "feed_info.txt": {"feed_publisher_name", "feed_publisher_url", "feed_lang"},
    "routes.txt": {"route_id", "route_short_name", "route_long_name", "route_type"},
    "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
    "trips.txt": {"route_id", "service_id", "trip_id"},
    "stop_times.txt": {"trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"},
    "calendar.txt": {
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    },
    "calendar_dates.txt": {"service_id", "date", "exception_type"},
    "shapes.txt": {"shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"},
}

PRIMARY_KEYS = {
    "routes.txt": ("route_id",),
    "stops.txt": ("stop_id",),
    "trips.txt": ("trip_id",),
    "calendar.txt": ("service_id",),
    "calendar_dates.txt": ("service_id", "date"),
    "shapes.txt": ("shape_id", "shape_pt_sequence"),
}

ENUMS: dict[str, dict[str, set[str]]] = {
    "routes.txt": {
        "route_type": {"0", "1", "2", "3", "4", "5", "6", "7", "11", "12"},
        "continuous_pickup": {"0", "1", "2", "3", ""},
        "continuous_drop_off": {"0", "1", "2", "3", ""},
    },
    "trips.txt": {
        "direction_id": {"0", "1", ""},
        "wheelchair_accessible": {"0", "1", "2", ""},
        "bikes_allowed": {"0", "1", "2", ""},
    },
    "stops.txt": {
        "location_type": {"0", "1", "2", "3", "4", ""},
        "wheelchair_boarding": {"0", "1", "2", ""},
    },
    "stop_times.txt": {
        "pickup_type": {"0", "1", "2", "3", ""},
        "drop_off_type": {"0", "1", "2", "3", ""},
        "timepoint": {"0", "1", ""},
    },
    "calendar.txt": {
        day: {"0", "1"}
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    },
    "calendar_dates.txt": {"exception_type": {"1", "2"}},
}
