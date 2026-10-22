"""Shared GTFS stop-event classification and display resolution rules."""
from __future__ import annotations

from dataclasses import dataclass


CRITICAL_STOPS = {
    "6": {"kotake": "606", "hikawadai": "605", "senkawa": "607", "kanamecho": "608"},
    "9": {"kotake": "906", "hikawadai": "905", "senkawa": "907", "kanamecho": "908"},
}

FUKUTOSHIN_TYPE_PATTERN = {
    "Local": "local",
    "CommuterExpress": "commuter_express",
    "Express": "express_pattern",
    "F-Liner": "express_pattern",
}

TYPE_LABELS = {
    "Local": "各駅停車",
    "Express": "急行",
    "CommuterExpress": "通勤急行",
    "SemiExpress": "準急",
    "Rapid": "快速",
    "RapidExpress": "快速急行",
    "F-Liner": "Fライナー",
    "S-TRAIN": "S-TRAIN",
}


@dataclass(frozen=True)
class TypeResolution:
    train_type: str | None
    reported_train_type: str | None
    service_brand: str | None
    label: str
    source: str  # odpt_confirmed | gtfs_stop_pattern | unknown
    stop_pattern: str
    pattern_states: tuple[tuple[str, str], ...]
    validation: str  # consistent | unverifiable | conflict | not_applicable | unmatched
    diagnostic: str | None = None


def event_state(events, stop_id: str, origin_sequence: int) -> str:
    """Require usable times/access or an explicit no-time/no-board row."""
    event = next((item for item in events
                  if item.stop_id == stop_id and item.sequence > origin_sequence), None)
    if event is None:
        return "missing"
    has_time = event.arrival_seconds is not None or event.departure_seconds is not None
    board_or_alight = event.can_board or event.can_alight
    if has_time and board_or_alight:
        return "stop"
    if not has_time and event.pickup_type == "1" and event.drop_off_type == "1":
        return "pass"
    return "unknown"


def classify(route_id: str, states: dict[str, str]) -> str:
    if route_id == "9":
        if states["kotake"] != "stop":
            return "unclassifiable"
        k, s, h = states["kanamecho"], states["senkawa"], states["hikawadai"]
        if k == s == h == "stop":
            return "local"
        if k == s == "pass" and h == "stop":
            return "commuter_express"
        if k == s == h == "pass":
            return "express_pattern"
        return "unclassifiable"

    required = ("kanamecho", "senkawa", "kotake", "hikawadai")
    if all(states[key] == "stop" for key in required):
        return "all_stops_metro_section"
    if any(states[key] == "pass" for key in required):
        return "non_all_stop_pattern_unclassified"
    return "unclassifiable"


def resolve_type(route_id: str, odpt_status: str, odpt_type: str | None,
                 service_brand: str | None, pattern: str,
                 states: dict[str, str], reported_train_type: str | None = None) -> TypeResolution:
    """Resolve a display label while preserving provenance and contradictions."""
    state_tuple = tuple(sorted(states.items()))
    if odpt_status == "unique_match" and not odpt_type:
        if service_brand == "F-Liner":
            if route_id == "9" and pattern == "local":
                return TypeResolution(None, reported_train_type or service_brand, service_brand,
                                      "種別不明", "unknown", pattern, state_tuple,
                                      "conflict", "f_liner_conflicts_with_local_stop_pattern")
            validation = "consistent" if route_id == "9" and pattern == "express_pattern" else "unverifiable"
            return TypeResolution(None, reported_train_type or service_brand, service_brand,
                                  "Fライナー", "odpt_confirmed", pattern, state_tuple,
                                  validation, "service_brand_without_metro_line_type")
        return TypeResolution(None, reported_train_type, None, "種別不明", "unknown", pattern,
                              state_tuple, "unverifiable", "odpt_train_type_scope_unverified")
    if odpt_status == "unique_match" and odpt_type:
        expected = FUKUTOSHIN_TYPE_PATTERN.get(odpt_type) if route_id == "9" else None
        if route_id == "6" and odpt_type == "Local":
            if pattern not in ("all_stops_metro_section", "all_stops_to_kotake_segment"):
                return TypeResolution(None, reported_train_type or odpt_type, service_brand,
                                      "種別不明", "unknown", pattern, state_tuple,
                                      "unverifiable", "yurakucho_local_scope_not_verified")
            return TypeResolution(odpt_type, reported_train_type or odpt_type, service_brand,
                                  TYPE_LABELS[odpt_type], "odpt_confirmed", pattern,
                                  state_tuple, "consistent")
        if expected and pattern in ("local", "commuter_express", "express_pattern"):
            if expected != pattern:
                return TypeResolution(
                    None, odpt_type, service_brand, "種別不明", "unknown", pattern,
                state_tuple, "conflict", "odpt_stop_pattern_conflict",
                )
            validation = "consistent"
        elif expected:
            validation = "unverifiable"
        else:
            validation = "not_applicable"
        return TypeResolution(
            odpt_type, reported_train_type or odpt_type, service_brand, TYPE_LABELS.get(odpt_type, "種別不明"),
            "odpt_confirmed", pattern, state_tuple, validation,
            "odpt_type_label_unmapped" if odpt_type not in TYPE_LABELS else None,
        )

    if odpt_status != "unmatched":
        return TypeResolution(None, None, None, "種別不明", "unknown", pattern,
                              state_tuple, "unverifiable", f"odpt_match_{odpt_status}")

    if route_id == "9" and pattern in ("local", "commuter_express"):
        code = "Local" if pattern == "local" else "CommuterExpress"
        return TypeResolution(code, None, None, TYPE_LABELS[code], "gtfs_stop_pattern",
                              pattern, state_tuple, "consistent")
    if route_id == "9" and pattern == "express_pattern":
        return TypeResolution(None, None, None, "急行型", "gtfs_stop_pattern",
                              pattern, state_tuple, "not_applicable", "brand_unresolved")
    if route_id == "6" and pattern == "all_stops_metro_section":
        return TypeResolution(None, None, None, "全駅停車", "gtfs_stop_pattern",
                              pattern, state_tuple, "not_applicable", "metro_pattern_not_train_type")
    return TypeResolution(None, None, None, "種別不明", "unknown", pattern,
                          state_tuple, "unmatched", "required_stop_events_missing_or_unusable")
