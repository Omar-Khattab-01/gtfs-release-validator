from pathlib import Path
import sys
import re
import calendar
from datetime import date, datetime, timedelta

import pandas as pd
from zoneinfo import available_timezones


# =============================================================================
# RULES
# =============================================================================

AGENCY_RULES = {
    "file_name": "agency.txt",
    "required_columns": ["agency_name", "agency_url", "agency_timezone"],
    "expected_columns": [
        "agency_id",
        "agency_lang",
        "agency_phone",
        "agency_fare_url",
        "agency_email",
    ],
    "optional_not_expected_yet": ["cemv_support"],
    "primary_key": "agency_id",
}


FEED_INFO_RULES = {
    "file_name": "feed_info.txt",
    "required_columns": [
        "feed_publisher_name",
        "feed_publisher_url",
        "feed_lang",
    ],
    "expected_columns": [
        "feed_start_date",
        "feed_end_date",
        "feed_version",
        "feed_contact_url",
    ],
    "allowed_blank_columns": ["default_lang", "feed_contact_email"],
    "optional_not_used_before": ["default_lang"],
}


CALENDAR_RULES = {
    "file_name": "calendar.txt",
    "required_columns": [
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
    ],
    "day_columns": [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ],
    "primary_key": "service_id",
}


CALENDAR_DATES_RULES = {
    "file_name": "calendar_dates.txt",
    "required_columns": ["service_id", "date", "exception_type"],
    "valid_exception_types": ["1", "2"],
}


ROUTES_RULES = {
    "file_name": "routes.txt",
    "sort_order_reference_file": "routes_sort_order_list.csv",
    "required_columns": [
        "route_id",
        "agency_id",
        "route_short_name",
        "route_long_name",
        "route_desc",
        "route_type",
        "route_url",
        "route_color",
        "route_text_color",
        "route_sort_order",
        "continuous_pickup",
        "continuous_drop_off",
        "network_id",
    ],
    "allowed_blank_columns": ["route_desc", "route_url", "route_sort_order", "network_id"],
    "blank_value_exceptions": {
        "899-371-1": ["route_long_name", "route_color", "route_text_color"],
    },
    "primary_key": "route_id",
    "valid_route_types": ["0", "1", "2", "3", "4", "5", "6", "7", "11", "12"],
    "valid_continuous_values": ["0", "1", "2", "3"],
}


TRIPS_RULES = {
    "file_name": "trips.txt",
    "required_columns": [
        "route_id",
        "service_id",
        "trip_id",
        "trip_headsign",
        "trip_short_name",
        "direction_id",
        "block_id",
        "shape_id",
        "wheelchair_accessible",
        "bikes_allowed",
    ],
    "allowed_blank_columns": ["trip_short_name"],
    "primary_key": "trip_id",
    "valid_direction_ids": ["0", "1"],
    "valid_accessibility_values": ["0", "1", "2"],
}


STOP_TIMES_RULES = {
    "file_name": "stop_times.txt",
    "required_columns": [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
        "stop_headsign",
        "pickup_type",
        "drop_off_type",
        "shape_dist_traveled",
        "timepoint",
    ],
    "allowed_blank_columns": ["stop_headsign"],
    "expected_empty_columns": ["stop_headsign"],
    "allowed_stop_headsign_values": ["Greenboro", "N Rideau"],
}


SHAPES_RULES = {
    "file_name": "shapes.txt",
    "required_columns": [
        "shape_id",
        "shape_pt_lat",
        "shape_pt_lon",
        "shape_pt_sequence",
        "shape_dist_traveled",
    ],
    "allowed_blank_columns": ["shape_dist_traveled"],
}


STOPS_RULES = {
    "file_name": "stops.txt",
    "required_columns": [
        "stop_id",
        "stop_code",
        "stop_name",
        "tts_stop_name",
        "stop_desc",
        "stop_lat",
        "stop_lon",
        "zone_id",
        "stop_url",
        "location_type",
        "parent_station",
        "stop_timezone",
        "wheelchair_boarding",
        "level_id",
        "platform_code",
    ],

    # These fields are expected to be empty in the current export.
    # wheelchair_boarding is optional, so it is not listed here.
    # location_type can be 0 or empty, so it is not listed here.
    "expected_empty_columns": [
        "tts_stop_name",
        "stop_desc",
        "zone_id",
        "stop_url",
        "level_id",
    ],

    # These columns are allowed to be blank depending on stop type/rules.
    "allowed_blank_columns": [
        "stop_code",
        "tts_stop_name",
        "stop_desc",
        "zone_id",
        "stop_url",
        "location_type",
        "wheelchair_boarding",
        "level_id",
        "stop_timezone",
        "parent_station",
        "platform_code",
    ],

    "primary_key": "stop_id",

    # GTFS: blank or 0 = Stop / Platform.
    "valid_location_types": ["", "0", "1", "2", "3", "4"],

    "valid_wheelchair_boarding_values": ["", "0", "1", "2"],

    # Known current OC Transpo station stops that do not have stop_code.
    # These are allowed, but the validator warns if one disappears later.
    "stop_code_blank_exceptions": [
        "10449",
        "10712",
        "10766",
    ],

    # Known current OC Transpo child/platform stops that have parent_station
    # but do not have platform_code. These are allowed, but new cases fail.
    "missing_platform_code_exceptions": [
        "3836",
        "455",
        "463",
        "519",
        "CG990",
        "CG995",
        "NA996",
        "NA997",
        "NB990",
        "NB995",
        "NB996",
        "RA990",
        "RC990",
        "RE990",
        "RE991",
        "RE992",
        "RE994",
        "RE995",
        "RE996",
        "RE997",
        "RF990",
        "RF995",
        "RF996",
        "RR990",
        "RR991",
    ],

    # Known current OC Transpo stops that have platform_code but do not have
    # parent_station. These are allowed, but new cases fail.
    "platform_code_without_parent_exceptions": [
        "5469",
        "555",
    ],
}


# =============================================================================
# MAIN FILE VALIDATORS
# =============================================================================

def validate_agency_file(gtfs_folder: str) -> dict:
    result = new_result("agency.txt")
    df = load_required_file(gtfs_folder, AGENCY_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="agency.txt",
        headers=headers,
        result=result,
        required_columns=AGENCY_RULES["required_columns"],
        expected_columns=AGENCY_RULES["expected_columns"],
        optional_not_expected_yet=AGENCY_RULES["optional_not_expected_yet"],
    )

    if stop_if_empty(df, "agency.txt", result):
        return result

    validate_missing_values(
        file_name="agency.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=AGENCY_RULES["required_columns"] + AGENCY_RULES["expected_columns"],
        allowed_blank_columns=[],
        id_column="agency_id",
        warning_only=False,
    )

    validate_primary_key(df, headers, result, "agency.txt", AGENCY_RULES["primary_key"])
    validate_agency_formats(df, headers, result)

    finalize_status(result)
    return result


def validate_feed_info_file(gtfs_folder: str) -> dict:
    result = new_result("feed_info.txt")
    df = load_required_file(gtfs_folder, FEED_INFO_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="feed_info.txt",
        headers=headers,
        result=result,
        required_columns=FEED_INFO_RULES["required_columns"],
        expected_columns=FEED_INFO_RULES["expected_columns"],
        optional_not_expected_yet=[],
    )

    validate_optional_not_used_before(headers, result)

    if stop_if_empty(df, "feed_info.txt", result):
        return result

    if len(df) > 1:
        result["warnings"].append(
            f"feed_info.txt has {len(df)} rows. Usually this file should contain one feed information row."
        )

    validate_missing_values(
        file_name="feed_info.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=FEED_INFO_RULES["required_columns"] + FEED_INFO_RULES["expected_columns"],
        allowed_blank_columns=FEED_INFO_RULES["allowed_blank_columns"],
        id_column=None,
        warning_only=False,
    )

    validate_feed_info_formats(df, headers, result)
    validate_feed_dates(df, headers, result)
    highlight_feed_version(df, headers, result)

    finalize_status(result)
    return result


def validate_calendar_file(gtfs_folder: str) -> dict:
    result = new_result("calendar.txt")
    df = load_required_file(gtfs_folder, CALENDAR_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="calendar.txt",
        headers=headers,
        result=result,
        required_columns=CALENDAR_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "calendar.txt", result):
        return result

    validate_missing_values(
        file_name="calendar.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=CALENDAR_RULES["required_columns"],
        allowed_blank_columns=[],
        id_column="service_id",
        warning_only=False,
    )

    validate_primary_key(df, headers, result, "calendar.txt", CALENDAR_RULES["primary_key"])
    validate_calendar_day_values(df, headers, result)
    validate_yyyymmdd_column(df, headers, result, "calendar.txt", "start_date", warning_only=False)
    validate_yyyymmdd_column(df, headers, result, "calendar.txt", "end_date", warning_only=False)
    validate_calendar_start_and_end_dates(df, headers, result)

    finalize_status(result)
    return result


def validate_calendar_dates_file(gtfs_folder: str) -> dict:
    result = new_result("calendar_dates.txt")
    df = load_required_file(gtfs_folder, CALENDAR_DATES_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="calendar_dates.txt",
        headers=headers,
        result=result,
        required_columns=CALENDAR_DATES_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "calendar_dates.txt", result):
        return result

    validate_missing_values(
        file_name="calendar_dates.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=CALENDAR_DATES_RULES["required_columns"],
        allowed_blank_columns=[],
        id_column="service_id",
        warning_only=False,
    )

    validate_yyyymmdd_column(df, headers, result, "calendar_dates.txt", "date", warning_only=False)
    validate_calendar_dates_exception_type(df, headers, result)

    finalize_status(result)
    return result


def validate_routes_file(gtfs_folder: str) -> dict:
    result = new_result("routes.txt")
    df = load_required_file(gtfs_folder, ROUTES_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="routes.txt",
        headers=headers,
        result=result,
        required_columns=ROUTES_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "routes.txt", result):
        return result

    validate_routes_missing_values(df, headers, result)

    validate_primary_key(df, headers, result, "routes.txt", ROUTES_RULES["primary_key"])
    validate_routes_route_type(df, headers, result)
    validate_routes_continuous_values(df, headers, result)
    validate_routes_colors(df, headers, result)
    validate_routes_sort_order(df, headers, result, gtfs_folder)
    validate_routes_url(df, headers, result)

    for column in ROUTES_RULES["allowed_blank_columns"]:
        if column in headers:
            result["info"].append(f"routes.txt column '{column}' is allowed to be blank.")

    finalize_status(result)
    return result


def validate_trips_file(gtfs_folder: str) -> dict:
    result = new_result("trips.txt")
    df = load_required_file(gtfs_folder, TRIPS_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="trips.txt",
        headers=headers,
        result=result,
        required_columns=TRIPS_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "trips.txt", result):
        return result

    validate_missing_values(
        file_name="trips.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=TRIPS_RULES["required_columns"],
        allowed_blank_columns=TRIPS_RULES["allowed_blank_columns"],
        id_column="trip_id",
        warning_only=False,
        custom_blank_message="Only trip_short_name is expected to have no data.",
    )

    validate_primary_key(df, headers, result, "trips.txt", TRIPS_RULES["primary_key"])
    validate_trips_direction_id(df, headers, result)
    validate_trips_accessibility_values(df, headers, result)

    if "trip_short_name" in headers:
        result["info"].append("trips.txt column 'trip_short_name' is allowed to be blank.")

    finalize_status(result)
    return result


def validate_stops_file(gtfs_folder: str) -> dict:
    result = new_result("stops.txt")
    df = load_required_file(gtfs_folder, STOPS_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="stops.txt",
        headers=headers,
        result=result,
        required_columns=STOPS_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "stops.txt", result):
        return result

    validate_missing_values(
        file_name="stops.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=STOPS_RULES["required_columns"],
        allowed_blank_columns=STOPS_RULES["allowed_blank_columns"],
        id_column="stop_id",
        warning_only=False,
        custom_blank_message=(
            "Some stop fields are allowed to be blank based on OC Transpo stop structure rules."
        ),
    )

    validate_primary_key(df, headers, result, "stops.txt", STOPS_RULES["primary_key"])
    validate_stops_stop_code_exceptions(df, headers, result)
    validate_stops_expected_empty_columns(df, headers, result)
    validate_stops_location_type(df, headers, result)
    validate_stops_wheelchair_boarding(df, headers, result)
    validate_stops_lat_lon(df, headers, result)
    validate_stops_parent_platform_rules(df, headers, result)

    finalize_status(result)
    return result


def validate_stop_times_file(gtfs_folder: str) -> dict:
    result = new_result("stop_times.txt")
    df = load_required_file(gtfs_folder, STOP_TIMES_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="stop_times.txt",
        headers=headers,
        result=result,
        required_columns=STOP_TIMES_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "stop_times.txt", result):
        return result

    validate_missing_values(
        file_name="stop_times.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=STOP_TIMES_RULES["required_columns"],
        allowed_blank_columns=STOP_TIMES_RULES["allowed_blank_columns"],
        id_column="trip_id",
        warning_only=False,
        custom_blank_message="Only stop_headsign is expected to have no data.",
    )

    validate_stop_times_expected_empty_columns(df, headers, result)

    finalize_status(result)
    return result


def validate_shapes_file(gtfs_folder: str) -> dict:
    result = new_result("shapes.txt")
    df = load_required_file(gtfs_folder, SHAPES_RULES["file_name"], result)

    if df is None:
        return result

    headers = list(df.columns)

    validate_columns(
        file_name="shapes.txt",
        headers=headers,
        result=result,
        required_columns=SHAPES_RULES["required_columns"],
        expected_columns=[],
        optional_not_expected_yet=[],
    )

    if stop_if_empty(df, "shapes.txt", result):
        return result

    validate_missing_values(
        file_name="shapes.txt",
        df=df,
        headers=headers,
        result=result,
        columns_to_check=SHAPES_RULES["required_columns"],
        allowed_blank_columns=SHAPES_RULES["allowed_blank_columns"],
        id_column="shape_id",
        warning_only=False,
        custom_blank_message="shape_dist_traveled is optional and may be blank.",
    )

    validate_shapes_formats(df, headers, result)

    finalize_status(result)
    return result


# =============================================================================
# AGENCY VALIDATION HELPERS
# =============================================================================

def validate_agency_formats(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column in ["agency_url", "agency_fare_url"]:
        validate_url_column(df, headers, result, "agency.txt", column, id_column="agency_id", warning_only=False)

    if "agency_timezone" in headers:
        valid_timezones = available_timezones()

        for index, value in df["agency_timezone"].items():
            value = str(value).strip()

            if value and value not in valid_timezones:
                add_error(
                    result,
                    f"agency.txt invalid agency_timezone: agency_id {get_row_id(df, index, 'agency_id')}, "
                    f"current value '{value}', row {index + 2}"
                )

    validate_language_column(df, headers, result, "agency.txt", "agency_lang", id_column="agency_id")
    validate_email_column(df, headers, result, "agency.txt", "agency_email", id_column="agency_id")
    validate_phone_column(df, headers, result, "agency.txt", "agency_phone", id_column="agency_id")


# =============================================================================
# FEED_INFO VALIDATION HELPERS
# =============================================================================

def validate_optional_not_used_before(headers: list[str], result: dict) -> None:
    for column in FEED_INFO_RULES["optional_not_used_before"]:
        if column not in headers:
            result["info"].append(
                f"Optional column not present: {column}. This is acceptable because it was not used before."
            )
        else:
            result["info"].append(
                f"Optional column present: {column}. Blank value is acceptable because it was not used before."
            )


def validate_feed_info_formats(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    validate_url_column(df, headers, result, "feed_info.txt", "feed_publisher_url", id_column=None, warning_only=False)
    validate_url_column(df, headers, result, "feed_info.txt", "feed_contact_url", id_column=None, warning_only=False)
    validate_language_column(df, headers, result, "feed_info.txt", "feed_lang", id_column=None)
    validate_language_column(df, headers, result, "feed_info.txt", "default_lang", id_column=None)
    validate_email_column(df, headers, result, "feed_info.txt", "feed_contact_email", id_column=None)
    validate_yyyymmdd_column(df, headers, result, "feed_info.txt", "feed_start_date", warning_only=False)
    validate_yyyymmdd_column(df, headers, result, "feed_info.txt", "feed_end_date", warning_only=False)


def validate_feed_dates(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    expected_start_date = get_upcoming_friday(date.today())
    expected_start = expected_start_date.strftime("%Y%m%d")

    expected_end_date = add_one_month(expected_start_date)
    expected_end = expected_end_date.strftime("%Y%m%d")

    result["info"].append(f"feed_info.txt expected feed_start_date based on upcoming Friday: {expected_start}")
    result["info"].append(f"feed_info.txt expected feed_end_date based on one month after feed_start_date: {expected_end}")

    if "feed_start_date" in headers:
        actual = str(df.loc[0, "feed_start_date"]).strip()

        if actual != expected_start:
            add_error(
                result,
                f"feed_start_date is not the correct upcoming Friday. Current value: {actual}. Expected value: {expected_start}."
            )

    if "feed_end_date" in headers:
        actual = str(df.loc[0, "feed_end_date"]).strip()

        if actual != expected_end:
            add_error(
                result,
                f"feed_end_date is not one month from the expected feed_start_date. Current value: {actual}. Expected value: {expected_end}."
            )


def highlight_feed_version(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "feed_version" not in headers:
        return

    values = df["feed_version"].astype(str).str.strip().unique().tolist()
    result["info"].append(f"CHECK FEED VERSION MANUALLY: feed_version value(s): {values}")


# =============================================================================
# CALENDAR VALIDATION HELPERS
# =============================================================================

def validate_calendar_day_values(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column in CALENDAR_RULES["day_columns"]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            value = str(value).strip()

            if value not in ["0", "1"]:
                add_error(
                    result,
                    f"calendar.txt invalid day value: service_id {get_row_id(df, index, 'service_id')}, "
                    f"column '{column}', current value '{value}', row {index + 2}, expected 0 or 1"
                )


def validate_calendar_start_and_end_dates(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    expected_start_date = get_upcoming_friday(date.today())
    expected_start = expected_start_date.strftime("%Y%m%d")

    expected_end_date = add_one_month(expected_start_date)
    expected_end = expected_end_date.strftime("%Y%m%d")

    result["info"].append(f"calendar.txt expected start_date based on upcoming Friday: {expected_start}")
    result["info"].append(f"calendar.txt expected end_date based on one month after start_date: {expected_end}")

    if "start_date" in headers:
        for index, value in df["start_date"].items():
            if is_blank(value):
                continue

            actual = str(value).strip()

            if actual != expected_start:
                result["warnings"].append(
                    f"calendar.txt start_date warning: service_id {get_row_id(df, index, 'service_id')}, "
                    f"current value {actual}, expected {expected_start}"
                )

    if "end_date" in headers:
        for index, value in df["end_date"].items():
            if is_blank(value):
                continue

            actual = str(value).strip()

            if actual != expected_end:
                result["warnings"].append(
                    f"calendar.txt end_date warning: service_id {get_row_id(df, index, 'service_id')}, "
                    f"current value {actual}, expected {expected_end}"
                )


# =============================================================================
# CALENDAR_DATES VALIDATION HELPERS
# =============================================================================

def validate_calendar_dates_exception_type(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "exception_type" not in headers:
        return

    valid = CALENDAR_DATES_RULES["valid_exception_types"]

    for index, value in df["exception_type"].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if value not in valid:
            add_error(
                result,
                f"calendar_dates.txt invalid exception_type: service_id {get_row_id(df, index, 'service_id')}, "
                f"current value '{value}', row {index + 2}, expected 1 or 2"
            )


# =============================================================================
# ROUTES VALIDATION HELPERS
# =============================================================================

def validate_routes_missing_values(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    exception_map = ROUTES_RULES["blank_value_exceptions"]

    for column in headers:
        if column in ROUTES_RULES["allowed_blank_columns"]:
            continue

        for row_index, value in df[column].items():
            if not is_blank(value):
                continue

            route_id = get_row_id(df, row_index, "route_id")
            exception_columns = exception_map.get(route_id, [])

            if column in exception_columns:
                result["info"].append(
                    f"routes.txt known route exception allowed blank value: "
                    f"route_id {route_id}, column '{column}', row {row_index + 2}"
                )
                continue

            add_error(
                result,
                f"routes.txt missing value: route_id {route_id}, column '{column}', row {row_index + 2}. "
                "Only route_desc, route_url, route_sort_order, network_id, and known route exceptions are expected to have no data."
            )


def validate_routes_route_type(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "route_type" not in headers:
        return

    valid = ROUTES_RULES["valid_route_types"]

    for index, value in df["route_type"].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if value not in valid:
            add_error(
                result,
                f"routes.txt invalid route_type: route_id {get_row_id(df, index, 'route_id')}, "
                f"current value '{value}', row {index + 2}"
            )


def validate_routes_continuous_values(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    valid = ROUTES_RULES["valid_continuous_values"]

    for column in ["continuous_pickup", "continuous_drop_off"]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            if value not in valid:
                add_error(
                    result,
                    f"routes.txt invalid {column}: route_id {get_row_id(df, index, 'route_id')}, "
                    f"current value '{value}', row {index + 2}, expected 0, 1, 2, or 3"
                )


def validate_routes_colors(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    pattern = re.compile(r"^[0-9A-Fa-f]{6}$")

    for column in ["route_color", "route_text_color"]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            if not pattern.match(value):
                add_error(
                    result,
                    f"routes.txt invalid {column}: route_id {get_row_id(df, index, 'route_id')}, "
                    f"current value '{value}', row {index + 2}, expected 6-character HEX value"
                )


def validate_routes_sort_order(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    gtfs_folder: str,
) -> None:
    needed_columns = ["route_short_name", "route_sort_order"]

    for column in needed_columns:
        if column not in headers:
            return

    reference_df = load_routes_sort_order_reference(gtfs_folder, result)

    if reference_df is None:
        return

    reference_headers = list(reference_df.columns)

    for column in needed_columns:
        if column not in reference_headers:
            result["warnings"].append(
                f"{ROUTES_RULES['sort_order_reference_file']} is missing required column: {column}"
            )
            return

    reference_df["route_short_name"] = reference_df["route_short_name"].astype(str).str.strip()
    reference_df["route_sort_order"] = reference_df["route_sort_order"].astype(str).str.strip()

    blank_reference_routes = reference_df.index[reference_df["route_short_name"] == ""].tolist()

    if blank_reference_routes:
        result["warnings"].append(
            f"{ROUTES_RULES['sort_order_reference_file']} has blank route_short_name value(s) at row(s): "
            f"{[row_index + 2 for row_index in blank_reference_routes]}"
        )

    duplicate_reference_routes = sorted(
        reference_df.loc[
            reference_df["route_short_name"].duplicated(keep=False),
            "route_short_name",
        ].unique().tolist()
    )

    if duplicate_reference_routes:
        result["warnings"].append(
            f"{ROUTES_RULES['sort_order_reference_file']} route_short_name must map once only. "
            f"Duplicate route_short_name value(s): {duplicate_reference_routes}"
        )

    route_sort_lookup = {
        str(row["route_short_name"]).strip(): str(row["route_sort_order"]).strip()
        for _, row in reference_df.iterrows()
        if str(row["route_short_name"]).strip()
    }

    route_short_names = sorted(
        route_short_name
        for route_short_name in df["route_short_name"].astype(str).str.strip().unique().tolist()
        if route_short_name
    )

    for route_short_name in route_short_names:
        route_rows = df.index[df["route_short_name"].astype(str).str.strip() == route_short_name].tolist()

        if route_short_name not in route_sort_lookup:
            sample_route_ids = [
                str(df.loc[row_index, "route_id"]).strip()
                for row_index in route_rows[:10]
                if "route_id" in headers
            ]
            result["warnings"].append(
                f"routes.txt route_short_name is missing from {ROUTES_RULES['sort_order_reference_file']}: "
                f"route_short_name '{route_short_name}', sample route_id(s): {sample_route_ids}"
            )
            continue

        expected_sort_order = route_sort_lookup[route_short_name]

        rows_with_sort_order = [
            row_index
            for row_index in route_rows
            if str(df.loc[row_index, "route_sort_order"]).strip()
        ]

        if not rows_with_sort_order:
            result["warnings"].append(
                f"routes.txt route_short_name does not map to a route_sort_order row: "
                f"route_short_name '{route_short_name}'. "
                f"Expected route_sort_order {expected_sort_order} from {ROUTES_RULES['sort_order_reference_file']}."
            )
            continue

        if len(rows_with_sort_order) > 1:
            sample_values = [
                f"route_id {get_row_id(df, row_index, 'route_id')} row {row_index + 2} value "
                f"'{str(df.loc[row_index, 'route_sort_order']).strip()}'"
                for row_index in rows_with_sort_order[:20]
            ]
            result["warnings"].append(
                f"routes.txt route_short_name maps to route_sort_order more than once: "
                f"route_short_name '{route_short_name}'. Sample: {sample_values}"
            )
            continue

        index = rows_with_sort_order[0]
        actual_sort_order = str(df.loc[index, "route_sort_order"]).strip()

        if not actual_sort_order.isdigit():
            result["warnings"].append(
                f"routes.txt invalid route_sort_order: route_id {get_row_id(df, index, 'route_id')}, "
                f"route_short_name '{route_short_name}', current value '{actual_sort_order}', "
                f"row {index + 2}, expected integer"
            )
            continue

        if not expected_sort_order.isdigit():
            result["warnings"].append(
                f"{ROUTES_RULES['sort_order_reference_file']} invalid route_sort_order: "
                f"route_short_name '{route_short_name}', current value '{expected_sort_order}', expected integer"
            )
            continue

        if actual_sort_order != expected_sort_order:
            result["warnings"].append(
                f"routes.txt route_sort_order does not match {ROUTES_RULES['sort_order_reference_file']}: "
                f"route_id {get_row_id(df, index, 'route_id')}, route_short_name '{route_short_name}', "
                f"current value '{actual_sort_order}', expected '{expected_sort_order}', row {index + 2}"
            )

    used_routes = set(df["route_short_name"].astype(str).str.strip().tolist())
    unused_reference_routes = sorted(set(route_sort_lookup.keys()) - used_routes)

    result["info"].append(
        f"routes.txt route_sort_order checked against {ROUTES_RULES['sort_order_reference_file']}. "
        f"Reference route count: {len(route_sort_lookup)}; unused reference route count: {len(unused_reference_routes)}."
    )


def load_routes_sort_order_reference(gtfs_folder: str, result: dict):
    file_name = ROUTES_RULES["sort_order_reference_file"]
    candidate_paths = [
        Path(gtfs_folder) / file_name,
        Path(__file__).resolve().parent / file_name,
    ]

    for file_path in candidate_paths:
        if file_path.exists() and file_path.is_file():
            try:
                return pd.read_csv(
                    file_path,
                    dtype=str,
                    encoding="utf-8-sig",
                    keep_default_na=False,
                )
            except Exception as e:
                result["warnings"].append(f"Could not read or parse {file_name}: {e}")
                return None

    result["warnings"].append(
        f"{file_name} is missing. Place it in the GTFS folder or in the same folder as this validator."
    )
    return None


def validate_routes_url(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    validate_url_column(df, headers, result, "routes.txt", "route_url", id_column="route_id", warning_only=False)


# =============================================================================
# TRIPS VALIDATION HELPERS
# =============================================================================

def validate_trips_direction_id(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "direction_id" not in headers:
        return

    valid = TRIPS_RULES["valid_direction_ids"]

    for index, value in df["direction_id"].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if value not in valid:
            add_error(
                result,
                f"trips.txt invalid direction_id: trip_id {get_row_id(df, index, 'trip_id')}, "
                f"current value '{value}', row {index + 2}, expected 0 or 1"
            )


def validate_trips_accessibility_values(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    valid = TRIPS_RULES["valid_accessibility_values"]

    for column in ["wheelchair_accessible", "bikes_allowed"]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            if value not in valid:
                add_error(
                    result,
                    f"trips.txt invalid {column}: trip_id {get_row_id(df, index, 'trip_id')}, "
                    f"current value '{value}', row {index + 2}, expected 0, 1, or 2"
                )


# =============================================================================
# STOP_TIMES VALIDATION HELPERS
# =============================================================================

def validate_stop_times_expected_empty_columns(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column in STOP_TIMES_RULES["expected_empty_columns"]:
        if column not in headers:
            continue

        allowed_values = set(STOP_TIMES_RULES.get("allowed_stop_headsign_values", []))
        non_empty_rows = []
        allowed_exception_count = 0

        for row_index, value in df[column].items():
            value = str(value).strip()

            if not value:
                continue

            if value in allowed_values:
                allowed_exception_count += 1
                continue

            non_empty_rows.append(row_index)

        if non_empty_rows:
            sample_rows = non_empty_rows[:20]
            sample_messages = []

            for row_index in sample_rows:
                sample_messages.append(
                    f"trip_id {get_row_id(df, row_index, 'trip_id')} row {row_index + 2} value '{df.loc[row_index, column]}'"
                )

            add_error(
                result,
                f"stop_times.txt column '{column}' is expected to be empty, but has data in "
                f"{len(non_empty_rows)} row(s). Sample: {sample_messages}"
            )
        else:
            if allowed_exception_count:
                result["info"].append(
                    f"stop_times.txt column '{column}' is expected to be empty except known headsign value(s) "
                    f"{sorted(allowed_values)}. Allowed exception count: {allowed_exception_count}."
                )
            else:
                result["info"].append(f"stop_times.txt column '{column}' is expected to be empty and is empty.")


# =============================================================================
# SHAPES VALIDATION HELPERS
# =============================================================================

def validate_shapes_formats(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column, minimum, maximum in [
        ("shape_pt_lat", -90.0, 90.0),
        ("shape_pt_lon", -180.0, 180.0),
    ]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            try:
                number = float(value)
            except ValueError:
                add_error(
                    result,
                    f"shapes.txt invalid {column}: shape_id {get_row_id(df, index, 'shape_id')}, "
                    f"current value '{value}', row {index + 2}, expected numeric coordinate"
                )
                continue

            if number < minimum or number > maximum:
                add_error(
                    result,
                    f"shapes.txt invalid {column}: shape_id {get_row_id(df, index, 'shape_id')}, "
                    f"current value '{value}', row {index + 2}, outside valid coordinate range"
                )

    if "shape_pt_sequence" in headers:
        for index, value in df["shape_pt_sequence"].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            if not value.isdigit():
                add_error(
                    result,
                    f"shapes.txt invalid shape_pt_sequence: shape_id {get_row_id(df, index, 'shape_id')}, "
                    f"current value '{value}', row {index + 2}, expected integer"
                )

    if "shape_dist_traveled" in headers:
        non_empty_count = 0

        for index, value in df["shape_dist_traveled"].items():
            if is_blank(value):
                continue

            non_empty_count += 1
            value = str(value).strip()

            try:
                number = float(value)
            except ValueError:
                add_error(
                    result,
                    f"shapes.txt invalid shape_dist_traveled: shape_id {get_row_id(df, index, 'shape_id')}, "
                    f"current value '{value}', row {index + 2}, expected non-negative number or blank"
                )
                continue

            if number < 0:
                add_error(
                    result,
                    f"shapes.txt invalid shape_dist_traveled: shape_id {get_row_id(df, index, 'shape_id')}, "
                    f"current value '{value}', row {index + 2}, expected non-negative number or blank"
                )

        result["info"].append(
            f"shapes.txt shape_dist_traveled is optional. Non-empty value count: {non_empty_count}"
        )


# =============================================================================
# STOPS VALIDATION HELPERS
# =============================================================================

def validate_stops_stop_code_exceptions(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "stop_id" not in headers or "stop_code" not in headers:
        return

    exception_stop_ids = set(STOPS_RULES["stop_code_blank_exceptions"])
    existing_stop_ids = set(df["stop_id"].astype(str).str.strip().tolist())
    missing_exception_ids = sorted(exception_stop_ids - existing_stop_ids)

    if missing_exception_ids:
        result["warnings"].append(
            f"stops.txt stop_code blank exception stop_id(s) are no longer present in the file: {missing_exception_ids}"
        )

    for index, row in df.iterrows():
        stop_id = str(row["stop_id"]).strip()
        stop_code = str(row["stop_code"]).strip()

        if stop_code:
            continue

        if stop_id in exception_stop_ids:
            result["info"].append(
                f"stops.txt known station stop allowed without stop_code: stop_id {stop_id}, row {index + 2}"
            )
        else:
            add_error(
                result,
                f"stops.txt missing value: stop_id {stop_id}, column 'stop_code', row {index + 2}. "
                "Only known station exceptions are allowed to have blank stop_code."
            )


def validate_stops_expected_empty_columns(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column in STOPS_RULES["expected_empty_columns"]:
        if column not in headers:
            continue

        non_empty_rows = df.index[df[column].astype(str).str.strip() != ""].tolist()

        if non_empty_rows:
            sample_rows = non_empty_rows[:20]
            sample_messages = []

            for row_index in sample_rows:
                sample_messages.append(
                    f"stop_id {get_row_id(df, row_index, 'stop_id')} row {row_index + 2} value '{df.loc[row_index, column]}'"
                )

            add_error(
                result,
                f"stops.txt column '{column}' is expected to be empty, but has data in "
                f"{len(non_empty_rows)} row(s). Sample: {sample_messages}"
            )
        else:
            result["info"].append(f"stops.txt column '{column}' is expected to be empty and is empty.")


def validate_stops_location_type(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "location_type" not in headers:
        return

    valid = STOPS_RULES["valid_location_types"]

    blank_count = 0
    zero_count = 0
    parent_count = 0

    for index, value in df["location_type"].items():
        value = str(value).strip()

        if value == "":
            blank_count += 1
        elif value == "0":
            zero_count += 1
        elif value == "1":
            parent_count += 1

        if value not in valid:
            add_error(
                result,
                f"stops.txt invalid location_type: stop_id {get_row_id(df, index, 'stop_id')}, "
                f"current value '{value}', row {index + 2}, expected blank, 0, 1, 2, 3, or 4"
            )

    result["info"].append(
        f"stops.txt location_type summary: blank={blank_count}, 0={zero_count}, parent stations/location_type 1={parent_count}. "
        "Blank and 0 are both accepted as regular stops/platforms."
    )


def validate_stops_wheelchair_boarding(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    if "wheelchair_boarding" not in headers:
        return

    valid = STOPS_RULES["valid_wheelchair_boarding_values"]

    non_empty_count = 0

    for index, value in df["wheelchair_boarding"].items():
        value = str(value).strip()

        if value:
            non_empty_count += 1

        if value not in valid:
            add_error(
                result,
                f"stops.txt invalid wheelchair_boarding: stop_id {get_row_id(df, index, 'stop_id')}, "
                f"current value '{value}', row {index + 2}, expected blank, 0, 1, or 2"
            )

    result["info"].append(
        f"stops.txt wheelchair_boarding is optional. Non-empty value count: {non_empty_count}"
    )


def validate_stops_lat_lon(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    for column, minimum, maximum in [
        ("stop_lat", -90.0, 90.0),
        ("stop_lon", -180.0, 180.0),
    ]:
        if column not in headers:
            continue

        for index, value in df[column].items():
            if is_blank(value):
                continue

            value = str(value).strip()

            try:
                number = float(value)
            except ValueError:
                add_error(
                    result,
                    f"stops.txt invalid {column}: stop_id {get_row_id(df, index, 'stop_id')}, "
                    f"current value '{value}', row {index + 2}, expected numeric coordinate"
                )
                continue

            if number < minimum or number > maximum:
                add_error(
                    result,
                    f"stops.txt invalid {column}: stop_id {get_row_id(df, index, 'stop_id')}, "
                    f"current value '{value}', row {index + 2}, outside valid coordinate range"
                )


def validate_stops_parent_platform_rules(df: pd.DataFrame, headers: list[str], result: dict) -> None:
    needed_columns = ["stop_id", "stop_name", "location_type", "parent_station", "platform_code"]

    for column in needed_columns:
        if column not in headers:
            return

    platform_exception_stop_ids = set(STOPS_RULES["missing_platform_code_exceptions"])
    existing_stop_ids = set(df["stop_id"].astype(str).str.strip().tolist())
    missing_exception_ids = sorted(platform_exception_stop_ids - existing_stop_ids)
    platform_without_parent_exception_stop_ids = set(
        STOPS_RULES["platform_code_without_parent_exceptions"]
    )
    missing_platform_without_parent_exception_ids = sorted(
        platform_without_parent_exception_stop_ids - existing_stop_ids
    )

    if missing_exception_ids:
        result["warnings"].append(
            f"stops.txt platform_code exception stop_id(s) are no longer present in the file: {missing_exception_ids}"
        )

    if missing_platform_without_parent_exception_ids:
        result["warnings"].append(
            f"stops.txt platform_code without parent_station exception stop_id(s) are no longer present in the file: "
            f"{missing_platform_without_parent_exception_ids}"
        )

    parent_stop_ids = set(
        df.loc[df["location_type"].astype(str).str.strip() == "1", "stop_id"]
        .astype(str)
        .str.strip()
        .tolist()
    )

    referenced_parent_ids = set(
        value
        for value in df["parent_station"].astype(str).str.strip().tolist()
        if value
    )

    result["info"].append(
        f"stops.txt detected {len(parent_stop_ids)} parent stop(s) using location_type = 1."
    )

    for parent_id in sorted(parent_stop_ids):
        child_rows = df.index[df["parent_station"].astype(str).str.strip() == parent_id].tolist()
        platform_codes = sorted(
            {
                str(df.loc[row_index, "platform_code"]).strip()
                for row_index in child_rows
                if str(df.loc[row_index, "platform_code"]).strip()
            }
        )

        off_only_children = [
            str(df.loc[row_index, "stop_id"]).strip()
            for row_index in child_rows
            if is_off_only_stop(str(df.loc[row_index, "stop_name"]).strip())
        ]

        result["info"].append(
            f"stops.txt parent stop {parent_id} has {len(child_rows)} child/platform stop(s); "
            f"platform_code value(s): {platform_codes}; OFF ONLY child stop(s): {off_only_children}"
        )

    missing_parent_ids = sorted(referenced_parent_ids - parent_stop_ids)

    if missing_parent_ids:
        add_error(
            result,
            f"stops.txt has parent_station value(s) that do not match a stop_id with location_type = 1: {missing_parent_ids}"
        )

    for index, row in df.iterrows():
        stop_id = str(row["stop_id"]).strip()
        stop_name = str(row["stop_name"]).strip()
        location_type = str(row["location_type"]).strip()
        parent_station = str(row["parent_station"]).strip()
        platform_code = str(row["platform_code"]).strip()

        is_parent_stop = location_type == "1"
        is_off_only = is_off_only_stop(stop_name)
        is_platform_exception = stop_id in platform_exception_stop_ids
        is_platform_without_parent_exception = stop_id in platform_without_parent_exception_stop_ids

        if is_parent_stop:
            if parent_station:
                add_error(
                    result,
                    f"stops.txt parent stop should not have parent_station: stop_id {stop_id}, "
                    f"parent_station '{parent_station}', row {index + 2}"
                )

            if platform_code:
                add_error(
                    result,
                    f"stops.txt parent stop should not have platform_code: stop_id {stop_id}, "
                    f"platform_code '{platform_code}', row {index + 2}"
                )

            continue

        if parent_station and not platform_code:
            if is_off_only:
                result["info"].append(
                    f"stops.txt OFF ONLY stop allowed without platform_code: stop_id {stop_id}, "
                    f"stop_name '{stop_name}', parent_station {parent_station}, row {index + 2}"
                )
            elif is_platform_exception:
                result["info"].append(
                    f"stops.txt known stop allowed without platform_code: stop_id {stop_id}, "
                    f"stop_name '{stop_name}', parent_station {parent_station}, row {index + 2}"
                )
            else:
                add_error(
                    result,
                    f"stops.txt child/platform stop has parent_station but missing platform_code: "
                    f"stop_id {stop_id}, stop_name '{stop_name}', parent_station {parent_station}, row {index + 2}. "
                    "Only known exceptions and OFF ONLY stops are allowed without platform_code."
                )

        if platform_code and not parent_station:
            if is_platform_without_parent_exception:
                result["info"].append(
                    f"stops.txt known stop allowed with platform_code but no parent_station: "
                    f"stop_id {stop_id}, stop_name '{stop_name}', platform_code {platform_code}, row {index + 2}"
                )
            else:
                add_error(
                    result,
                    f"stops.txt stop has platform_code but no parent_station: "
                    f"stop_id {stop_id}, stop_name '{stop_name}', platform_code {platform_code}, row {index + 2}. "
                    "Only known exceptions are allowed to have platform_code without parent_station."
                )


def is_off_only_stop(stop_name: str) -> bool:
    return "OFF ONLY" in stop_name.upper()


# =============================================================================
# SHARED VALIDATION HELPERS
# =============================================================================

def load_required_file(gtfs_folder: str, file_name: str, result: dict):
    gtfs_path = Path(gtfs_folder)

    if not validate_gtfs_folder(gtfs_path, gtfs_folder, result):
        return None

    file_path = gtfs_path / file_name

    if not file_path.exists():
        add_error(result, f"{file_name} is missing.")
        return None

    df = read_gtfs_txt_file(file_path, result)

    if df is None:
        return None

    validate_headers(file_name, list(df.columns), result)

    return df


def validate_gtfs_folder(gtfs_path: Path, original_path: str, result: dict) -> bool:
    if not gtfs_path.exists():
        add_error(result, f"GTFS folder does not exist: {original_path}")
        return False

    if not gtfs_path.is_dir():
        add_error(result, f"Path is not a folder: {original_path}")
        return False

    return True


def read_gtfs_txt_file(file_path: Path, result: dict):
    try:
        return pd.read_csv(
            file_path,
            dtype=str,
            encoding="utf-8-sig",
            keep_default_na=False,
        )
    except Exception as e:
        add_error(result, f"Could not read or parse {file_path.name}: {e}")
        return None


def stop_if_empty(df: pd.DataFrame, file_name: str, result: dict) -> bool:
    if df.empty:
        add_error(result, f"{file_name} has headers but no data rows.")
        return True

    return False


def is_blank(value) -> bool:
    if value is None:
        return True

    if pd.isna(value):
        return True

    return str(value).strip() == ""


def validate_headers(file_name: str, headers: list[str], result: dict) -> None:
    if not headers:
        add_error(result, f"{file_name} has no header row.")
        return

    blank_headers = [
        index + 1
        for index, header in enumerate(headers)
        if str(header).strip() == ""
    ]

    if blank_headers:
        add_error(result, f"{file_name} has blank column name(s) at position(s): {blank_headers}")

    duplicate_headers = sorted({header for header in headers if headers.count(header) > 1})

    if duplicate_headers:
        add_error(result, f"{file_name} has duplicate column(s): {duplicate_headers}")


def validate_columns(
    file_name: str,
    headers: list[str],
    result: dict,
    required_columns: list[str],
    expected_columns: list[str],
    optional_not_expected_yet: list[str],
) -> None:
    for column in required_columns:
        if column not in headers:
            add_error(result, f"{file_name} is missing required/expected column: {column}")
        else:
            result["info"].append(f"{file_name} required/expected column present: {column}")

    for column in expected_columns:
        if column not in headers:
            result["warnings"].append(
                f"{file_name} missing expected OC Transpo column: {column}."
            )
        else:
            result["info"].append(f"{file_name} expected OC Transpo column present: {column}")

    for column in optional_not_expected_yet:
        if column not in headers:
            result["info"].append(
                f"{file_name} optional column not present: {column}. This is acceptable because it is not currently launched/expected."
            )
        else:
            result["warnings"].append(
                f"{file_name} optional column present: {column}. Confirm this is intentional."
            )


def validate_missing_values(
    file_name: str,
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    columns_to_check: list[str],
    allowed_blank_columns: list[str],
    id_column: str | None,
    warning_only: bool,
    custom_blank_message: str | None = None,
) -> None:
    for column in columns_to_check:
        if column not in headers:
            continue

        if column in allowed_blank_columns:
            continue

        for row_index, value in df[column].items():
            if is_blank(value):
                row_id = get_row_id(df, row_index, id_column)

                message = (
                    f"{file_name} missing value: "
                    f"{id_column + ' ' if id_column else ''}{row_id}, "
                    f"column '{column}', row {row_index + 2}."
                )

                if custom_blank_message:
                    message += f" {custom_blank_message}"

                if warning_only:
                    result["warnings"].append(message)
                else:
                    add_error(result, message)


def validate_primary_key(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    primary_key: str,
) -> None:
    if primary_key not in headers:
        return

    duplicated_rows = df[df[primary_key].duplicated(keep=False)]

    if not duplicated_rows.empty:
        duplicated_values = sorted(duplicated_rows[primary_key].unique().tolist())
        add_error(
            result,
            f"{file_name} {primary_key} must be unique. Duplicate value(s): {duplicated_values}"
        )


def validate_yyyymmdd_column(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    column: str,
    warning_only: bool,
) -> None:
    if column not in headers:
        return

    for index, value in df[column].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            message = (
                f"{file_name} invalid date: column '{column}', "
                f"current value '{value}', row {index + 2}, expected YYYYMMDD"
            )

            if warning_only:
                result["warnings"].append(message)
            else:
                add_error(result, message)


def validate_url_column(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    column: str,
    id_column: str | None,
    warning_only: bool,
) -> None:
    if column not in headers:
        return

    for index, value in df[column].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if not value.startswith(("http://", "https://")):
            message = (
                f"{file_name} invalid URL: {id_column + ' ' if id_column else ''}{get_row_id(df, index, id_column)}, "
                f"column '{column}', current value '{value}', row {index + 2}"
            )

            if warning_only:
                result["warnings"].append(message)
            else:
                add_error(result, message)


def validate_language_column(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    column: str,
    id_column: str | None,
) -> None:
    if column not in headers:
        return

    pattern = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2})?$")

    for index, value in df[column].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if not pattern.match(value):
            result["warnings"].append(
                f"{file_name} possible invalid language code: {id_column + ' ' if id_column else ''}{get_row_id(df, index, id_column)}, "
                f"column '{column}', current value '{value}', row {index + 2}"
            )


def validate_email_column(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    column: str,
    id_column: str | None,
) -> None:
    if column not in headers:
        return

    pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    for index, value in df[column].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if not pattern.match(value):
            result["warnings"].append(
                f"{file_name} possible invalid email: {id_column + ' ' if id_column else ''}{get_row_id(df, index, id_column)}, "
                f"column '{column}', current value '{value}', row {index + 2}"
            )


def validate_phone_column(
    df: pd.DataFrame,
    headers: list[str],
    result: dict,
    file_name: str,
    column: str,
    id_column: str | None,
) -> None:
    if column not in headers:
        return

    pattern = re.compile(r"^[0-9+\-().\s]+$")

    for index, value in df[column].items():
        if is_blank(value):
            continue

        value = str(value).strip()

        if not pattern.match(value):
            result["warnings"].append(
                f"{file_name} possible invalid phone: {id_column + ' ' if id_column else ''}{get_row_id(df, index, id_column)}, "
                f"column '{column}', current value '{value}', row {index + 2}"
            )


def get_row_id(df: pd.DataFrame, row_index: int, id_column: str | None) -> str:
    if id_column is None or id_column not in df.columns:
        return f"row {row_index + 2}"

    value = str(df.loc[row_index, id_column]).strip()

    if value:
        return value

    return f"row {row_index + 2}"


def get_upcoming_friday(today: date) -> date:
    days_until_friday = (4 - today.weekday()) % 7
    return today + timedelta(days=days_until_friday)


def add_one_month(input_date: date) -> date:
    year = input_date.year
    month = input_date.month + 1
    day = input_date.day

    if month == 13:
        month = 1
        year += 1

    last_day_of_target_month = calendar.monthrange(year, month)[1]

    if day > last_day_of_target_month:
        day = last_day_of_target_month

    return date(year, month, day)


# =============================================================================
# RESULT / OUTPUT HELPERS
# =============================================================================

def new_result(file_name: str) -> dict:
    return {
        "file": file_name,
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "info": [],
    }


def add_error(result: dict, message: str) -> None:
    result["errors"].append(message)
    result["status"] = "FAIL"


def finalize_status(result: dict) -> None:
    if result["errors"]:
        result["status"] = "FAIL"
    elif result["warnings"]:
        result["status"] = "PASS WITH WARNINGS"
    else:
        result["status"] = "PASS"


def print_result(result: dict) -> None:
    print("=" * 80)
    print(f"{result['file']}: {result['status']}")
    print("=" * 80)

    if result["errors"]:
        print("\nERRORS:")
        for error in result["errors"]:
            print(f"  - {error}")

    if result["warnings"]:
        print("\nWARNINGS:")
        for warning in result["warnings"]:
            print(f"  - {warning}")

    if result["info"]:
        print("\nINFO:")
        for info in result["info"]:
            print(f"  - {info}")

    print()


def print_summary(results: list[dict]) -> None:
    failed_count = sum(1 for result in results if result["status"] == "FAIL")
    warning_count = sum(1 for result in results if result["status"] == "PASS WITH WARNINGS")
    passed_count = sum(1 for result in results if result["status"] == "PASS")

    print("=" * 80)
    print("GTFS VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Passed: {passed_count}")
    print(f"Passed with warnings: {warning_count}")
    print(f"Failed: {failed_count}")
    print()


def get_gtfs_folder_from_user() -> str:
    if len(sys.argv) >= 2:
        return sys.argv[1]

    print("Enter the folder path that contains the GTFS .txt files.")
    print(r"Example: C:\Users\khattabom\Downloads\GTFSExport.next 2026")
    return input("GTFS folder path: ").strip().strip('"')


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    gtfs_folder = get_gtfs_folder_from_user()

    results = [
        validate_agency_file(gtfs_folder),
        validate_feed_info_file(gtfs_folder),
        validate_calendar_file(gtfs_folder),
        validate_calendar_dates_file(gtfs_folder),
        validate_routes_file(gtfs_folder),
        validate_trips_file(gtfs_folder),
        validate_stops_file(gtfs_folder),
        validate_stop_times_file(gtfs_folder),
        validate_shapes_file(gtfs_folder),
    ]

    for result in results:
        print_result(result)

    print_summary(results)


if __name__ == "__main__":
    main()
