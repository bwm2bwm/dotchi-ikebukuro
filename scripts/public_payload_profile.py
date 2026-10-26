"""Project a local schema-v1 timetable into the allowlisted public profile.

This module is deliberately offline. It accepts only the private preview profile
and returns a new object with a distinct public dataScope. It does not read files,
fetch data, or modify its input.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


LOCAL_DATA_SCOPE = "local-preview-only"
PUBLIC_DATA_SCOPE = "public-display-v1"
TIMEZONE = "Asia/Tokyo"
DESTINATIONS = frozenset({
    "Kanamecho", "Senkawa", "KotakeMukaihara", "Hikawadai", "Heiwadai",
    "ChikatetsuAkatsuka", "ChikatetsuNarimasu", "Wakoshi",
})
ROUTES = frozenset({"6", "9"})


class PublicPayloadProfileError(ValueError):
    """Raised when local input cannot safely be projected to the public profile."""


def _fail(path: str, message: str) -> None:
    raise PublicPayloadProfileError(f"{path}: {message}")


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "object required")
    return value


def _fields(value: Any, path: str, required: tuple[str, ...],
            optional: tuple[str, ...] = ()) -> dict[str, Any]:
    source = _object(value, path)
    missing = [key for key in required if key not in source]
    if missing:
        _fail(path, "missing required field(s): " + ", ".join(missing))
    return {key: source[key] for key in (*required, *optional) if key in source}


def _string(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        _fail(path, "nonempty string required" if not nullable else "string or null required")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(path, "nonnegative integer required")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "boolean required")
    return value


def _date(value: Any, path: str) -> str:
    if not isinstance(value, str):
        _fail(path, "YYYY-MM-DD date required")
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(path, "YYYY-MM-DD date required")
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        _fail(path, "YYYY-MM-DD date required")
    return value


def _timestamp(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        _fail(path, "ISO timestamp with timezone required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "ISO timestamp with timezone required")
    if parsed.tzinfo is None:
        _fail(path, "timezone offset required")
    return value


def _string_list(value: Any, path: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(path, "array of strings required")
    return [_string(item, f"{path}[{index}]") for index, item in enumerate(value)]  # type: ignore[list-item]


def _transfer(value: Any, path: str) -> dict[str, Any]:
    required = ("stationId", "stationName", "waitSeconds", "outgoingRouteId",
                "outgoingRouteName", "outgoingHeadsign", "outgoingTrainType",
                "outgoingDestinationIds")
    optional = ("outgoingReportedTrainType", "outgoingServiceBrand", "outgoingTypeLabel")
    result = _fields(value, path, required, optional)
    _string(result["stationId"], f"{path}.stationId")
    _string(result["stationName"], f"{path}.stationName", nullable=True)
    _integer(result["waitSeconds"], f"{path}.waitSeconds")
    _string(result["outgoingRouteId"], f"{path}.outgoingRouteId")
    _string(result["outgoingRouteName"], f"{path}.outgoingRouteName")
    _string(result["outgoingHeadsign"], f"{path}.outgoingHeadsign", nullable=True)
    _string(result["outgoingTrainType"], f"{path}.outgoingTrainType", nullable=True)
    for key in ("outgoingReportedTrainType", "outgoingServiceBrand"):
        if key in result:
            _string(result[key], f"{path}.{key}", nullable=True)
    if "outgoingTypeLabel" in result:
        _string(result["outgoingTypeLabel"], f"{path}.outgoingTypeLabel")
    result["outgoingDestinationIds"] = _string_list(
        result["outgoingDestinationIds"], f"{path}.outgoingDestinationIds")
    return result


def _journey(value: Any, path: str, *, expected_kind: str | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    required = ("kind", "departureServiceSeconds", "arrivalServiceSeconds", "departureText",
                "arrivalText", "arrivalStationId", "transfer", "platformStatus",
                "connectionGuaranteed")
    result = _fields(value, path, required)
    kind = _string(result["kind"], f"{path}.kind")
    if kind not in {"direct", "transfer"} or (expected_kind and kind != expected_kind):
        _fail(f"{path}.kind", f"expected {expected_kind or 'direct or transfer'}")
    _integer(result["departureServiceSeconds"], f"{path}.departureServiceSeconds")
    arrival = result["arrivalServiceSeconds"]
    if arrival is not None:
        _integer(arrival, f"{path}.arrivalServiceSeconds")
    for key in ("departureText", "arrivalText", "arrivalStationId"):
        _string(result[key], f"{path}.{key}", nullable=True)
    _string(result["platformStatus"], f"{path}.platformStatus")
    _boolean(result["connectionGuaranteed"], f"{path}.connectionGuaranteed")
    if kind == "direct":
        if result["transfer"] is not None:
            _fail(f"{path}.transfer", "must be null for direct journey")
    else:
        result["transfer"] = _transfer(result["transfer"], f"{path}.transfer")
    return result


def _route_status(value: Any, path: str, *, transfer_metrics: bool) -> dict[str, int]:
    required = ("originTripCount", "candidateCount", "directCandidateCount",
                "passThroughCount", "dataInsufficientCount")
    optional = ("scheduledTripCount", "transferDataInsufficientCount")
    if transfer_metrics:
        required += ("transferCandidateCount", "transferPairCount", "transferOnlyCount")
    result = _fields(value, path, required, optional)
    for key, count in result.items():
        result[key] = _integer(count, f"{path}.{key}")
    if "scheduledTripCount" in result and result["scheduledTripCount"] < result["originTripCount"]:
        _fail(f"{path}.scheduledTripCount", "must cover originTripCount")
    if "directCandidateCount" in result and result["directCandidateCount"] > result["candidateCount"]:
        _fail(f"{path}.directCandidateCount", "must not exceed candidateCount")
    return result


def _destination_status(value: Any, path: str, destination_id: str,
                        departures: list[dict[str, Any]]) -> dict[str, Any]:
    required = ("status", "candidateCount", "passThroughCount", "dataInsufficientCount", "routes")
    optional = ("directCandidateCount", "transferCandidateCount", "transferPairCount", "transferOnlyCount",
                "transferPassThroughCount", "transferDataInsufficientCount")
    transfer_metrics = destination_id in {"Heiwadai", "ChikatetsuAkatsuka", "ChikatetsuNarimasu", "Wakoshi"}
    if transfer_metrics:
        required += ("directCandidateCount", "transferCandidateCount", "transferPairCount",
                     "transferOnlyCount", "transferPassThroughCount", "transferDataInsufficientCount")
    result = _fields(value, path, required, optional)
    if result["status"] not in {"normal", "no_candidates", "data_insufficient", "unsupported", "invalid"}:
        _fail(f"{path}.status", "unsupported destination status")
    for key in optional:
        if key in result:
            result[key] = _integer(result[key], f"{path}.{key}")
    routes = _object(result["routes"], f"{path}.routes")
    if set(routes) != ROUTES:
        _fail(f"{path}.routes", "route keys must be exactly 6 and 9")
    result["routes"] = {
        route_id: _route_status(routes[route_id], f"{path}.routes.{route_id}",
                                transfer_metrics=transfer_metrics)
        for route_id in ("6", "9")
    }
    for key in ("candidateCount", "passThroughCount", "dataInsufficientCount"):
        result[key] = _integer(result[key], f"{path}.{key}")
    route_totals = {key: sum(route[key] for route in result["routes"].values())
                    for key in ("candidateCount", "passThroughCount", "dataInsufficientCount")}
    if result["candidateCount"] != sum(item["primary"] is not None for item in departures):
        _fail(f"{path}.candidateCount", "must match departures with a primary itinerary")
    if result["candidateCount"] != route_totals["candidateCount"]:
        _fail(f"{path}.candidateCount", "must match route totals")
    if result["passThroughCount"] != route_totals["passThroughCount"]:
        _fail(f"{path}.passThroughCount", "must match route totals")
    if result["status"] == "normal" and result["candidateCount"] == 0:
        _fail(f"{path}.status", "normal requires at least one candidate")
    if result["status"] == "no_candidates" and (result["candidateCount"] or result["dataInsufficientCount"]):
        _fail(f"{path}.status", "no_candidates requires zero candidates and no incomplete data")
    if result["status"] == "data_insufficient" and (result["candidateCount"] or not result["dataInsufficientCount"]):
        _fail(f"{path}.status", "data_insufficient requires incomplete data and zero candidates")
    return result


def _departure(value: Any, path: str) -> dict[str, Any]:
    required = ("id", "originTripId", "routeId", "routeName", "headsign", "trainType",
                "destination", "odptDestinationIds", "odptMatchStatus", "departureServiceSeconds",
                "departureText", "primary", "directAlternative", "bestTransferAlternative",
                "transferCandidateCount", "status", "dataQuality")
    optional = ("reportedTrainType", "serviceBrand", "typeLabel", "typeSource", "destinationSource")
    result = _fields(value, path, required, optional)
    for key in ("id", "originTripId", "routeId", "routeName", "odptMatchStatus", "departureText", "status"):
        _string(result[key], f"{path}.{key}")
    if result["routeId"] not in ROUTES:
        _fail(f"{path}.routeId", "unsupported route")
    for key in ("headsign", "trainType", "destination", "reportedTrainType", "serviceBrand", "destinationSource"):
        if key in result:
            _string(result[key], f"{path}.{key}", nullable=True)
    if "typeLabel" in result:
        _string(result["typeLabel"], f"{path}.typeLabel")
    if "typeSource" in result and result["typeSource"] not in {
        "odpt_confirmed", "official_route_rule", "gtfs_stop_pattern", "unknown"
    }:
        _fail(f"{path}.typeSource", "unsupported type source")
    result["odptDestinationIds"] = _string_list(result["odptDestinationIds"], f"{path}.odptDestinationIds")
    _integer(result["departureServiceSeconds"], f"{path}.departureServiceSeconds")
    _integer(result["transferCandidateCount"], f"{path}.transferCandidateCount")
    result["dataQuality"] = _string_list(result["dataQuality"], f"{path}.dataQuality")
    result["primary"] = _journey(result["primary"], f"{path}.primary")
    result["directAlternative"] = _journey(result["directAlternative"], f"{path}.directAlternative",
                                           expected_kind="direct")
    result["bestTransferAlternative"] = _journey(result["bestTransferAlternative"],
                                                  f"{path}.bestTransferAlternative",
                                                  expected_kind="transfer")
    for key in ("primary", "directAlternative", "bestTransferAlternative"):
        journey = result[key]
        if journey is None:
            continue
        if journey["departureServiceSeconds"] != result["departureServiceSeconds"]:
            _fail(f"{path}.{key}.departureServiceSeconds", "must match departure")
        if journey["arrivalServiceSeconds"] is not None and journey["arrivalServiceSeconds"] < result["departureServiceSeconds"]:
            _fail(f"{path}.{key}.arrivalServiceSeconds", "must not precede departure")
        if journey["kind"] == "transfer":
            wait = journey["transfer"]["waitSeconds"]
            if not 60 <= wait <= 600:
                _fail(f"{path}.{key}.transfer.waitSeconds", "outside supported connection policy")
            if journey["transfer"]["outgoingRouteId"] == result["routeId"]:
                _fail(f"{path}.{key}.transfer.outgoingRouteId", "must use the opposite route")
    return result


def project_public_payload(payload: Any) -> dict[str, Any]:
    """Return a validated, allowlisted public-display-v1 payload.

    Unknown input fields are intentionally ignored. Only a schema-v1 local
    preview payload may be used as input, preventing local and public profiles
    from being accidentally chained or confused.
    """
    source = _object(payload, "payload")
    if source.get("schemaVersion") != 1:
        _fail("payload.schemaVersion", "schema version 1 required")
    if source.get("dataScope") != LOCAL_DATA_SCOPE:
        _fail("payload.dataScope", f"{LOCAL_DATA_SCOPE} input required")

    required = ("schemaVersion", "dataScope", "generatedAt", "timezone", "feed", "odpt",
                "applicationPeriod", "webApp", "connectionPolicy", "serviceDays", "excludedServiceDates")
    result = _fields(source, "payload", required)
    _timestamp(result["generatedAt"], "payload.generatedAt")
    if result["timezone"] != TIMEZONE:
        _fail("payload.timezone", f"{TIMEZONE} required")

    feed = _fields(result["feed"], "payload.feed", ("version", "validFrom", "validThrough", "sourceUpdatedAt"))
    _string(feed["version"], "payload.feed.version")
    feed["validFrom"] = _date(feed["validFrom"], "payload.feed.validFrom")
    feed["validThrough"] = _date(feed["validThrough"], "payload.feed.validThrough")
    if feed["validFrom"] > feed["validThrough"]:
        _fail("payload.feed", "validFrom must not follow validThrough")
    feed["sourceUpdatedAt"] = _timestamp(feed["sourceUpdatedAt"], "payload.feed.sourceUpdatedAt", nullable=True)
    result["feed"] = feed

    odpt = _fields(result["odpt"], "payload.odpt", ("sourceUpdatedAt",))
    odpt["sourceUpdatedAt"] = _timestamp(odpt["sourceUpdatedAt"], "payload.odpt.sourceUpdatedAt", nullable=True)
    result["odpt"] = odpt

    period = _fields(result["applicationPeriod"], "payload.applicationPeriod", ("startsAt", "endsAt"))
    period["startsAt"] = _timestamp(period["startsAt"], "payload.applicationPeriod.startsAt")
    period["endsAt"] = _timestamp(period["endsAt"], "payload.applicationPeriod.endsAt")
    if datetime.fromisoformat(period["endsAt"].replace("Z", "+00:00")) <= datetime.fromisoformat(period["startsAt"].replace("Z", "+00:00")):
        _fail("payload.applicationPeriod", "endsAt must follow startsAt")
    result["applicationPeriod"] = period

    web_app = _fields(result["webApp"], "payload.webApp", ("builtAt",))
    web_app["builtAt"] = _timestamp(web_app["builtAt"], "payload.webApp.builtAt", nullable=True)
    result["webApp"] = web_app

    policy = _fields(result["connectionPolicy"], "payload.connectionPolicy",
                     ("minimumWaitSeconds", "maximumWaitSeconds", "platformStatus", "connectionGuaranteed"))
    policy["minimumWaitSeconds"] = _integer(policy["minimumWaitSeconds"], "payload.connectionPolicy.minimumWaitSeconds")
    policy["maximumWaitSeconds"] = _integer(policy["maximumWaitSeconds"], "payload.connectionPolicy.maximumWaitSeconds")
    if policy["maximumWaitSeconds"] < policy["minimumWaitSeconds"]:
        _fail("payload.connectionPolicy", "maximum wait must be >= minimum wait")
    _string(policy["platformStatus"], "payload.connectionPolicy.platformStatus")
    _boolean(policy["connectionGuaranteed"], "payload.connectionPolicy.connectionGuaranteed")
    result["connectionPolicy"] = policy

    days = result["serviceDays"]
    if not isinstance(days, list) or not days:
        _fail("payload.serviceDays", "nonempty array required")
    projected_days = []
    seen_dates: set[str] = set()
    selected_destinations: set[str] = set()
    departure_count = 0
    for index, raw_day in enumerate(days):
        path = f"payload.serviceDays[{index}]"
        day = _fields(raw_day, path, ("serviceDate", "originStationId", "destinationStationId", "departures"),
                      ("destinationStatus",))
        day["serviceDate"] = _date(day["serviceDate"], f"{path}.serviceDate")
        if day["serviceDate"] in seen_dates:
            _fail(f"{path}.serviceDate", "duplicate service date")
        seen_dates.add(day["serviceDate"])
        _string(day["originStationId"], f"{path}.originStationId")
        destination_id = _string(day["destinationStationId"], f"{path}.destinationStationId")
        if destination_id not in DESTINATIONS:
            _fail(f"{path}.destinationStationId", "unsupported destination")
        selected_destinations.add(destination_id)
        if len(selected_destinations) != 1:
            _fail("payload.serviceDays", "destination must be consistent across service dates")
        departures = day["departures"]
        if not isinstance(departures, list):
            _fail(f"{path}.departures", "array required")
        day["departures"] = [_departure(item, f"{path}.departures[{item_index}]")
                             for item_index, item in enumerate(departures)]
        for item_index, departure in enumerate(day["departures"]):
            for journey_key in ("primary", "directAlternative", "bestTransferAlternative"):
                journey = departure[journey_key]
                if journey is not None and journey["arrivalStationId"] != destination_id:
                    _fail(f"{path}.departures[{item_index}].{journey_key}.arrivalStationId",
                          "must match destinationStationId")
        departure_count += len(day["departures"])
        if destination_id != "Hikawadai" and "destinationStatus" not in day:
            _fail(f"{path}.destinationStatus", "required for non-default destination")
        if "destinationStatus" in day:
            day["destinationStatus"] = _destination_status(day["destinationStatus"],
                                                           f"{path}.destinationStatus", destination_id,
                                                           day["departures"])
        projected_days.append(day)
    if len(selected_destinations) != 1:
        _fail("payload.serviceDays", "destination must be consistent across service dates")
    if departure_count == 0:
        _fail("payload.serviceDays", "at least one departure is required")
    result["serviceDays"] = projected_days

    excluded = result["excludedServiceDates"]
    if not isinstance(excluded, list):
        _fail("payload.excludedServiceDates", "array required")
    result["excludedServiceDates"] = [_date(item, f"payload.excludedServiceDates[{index}]")
                                      for index, item in enumerate(excluded)]
    result["dataScope"] = PUBLIC_DATA_SCOPE
    return result
