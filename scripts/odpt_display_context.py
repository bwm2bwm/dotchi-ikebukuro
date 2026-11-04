"""Versioned private display context; never reads sources or generates payloads."""
import copy
from datetime import datetime, timedelta, timezone

if __package__:
    from . import odpt_quality_input as quality
else:
    import odpt_quality_input as quality

CONTRACT = 'odpt-display-evaluation-context'
SCENARIOS = [dict(id=mode+'-'+suffix, mode=mode, directOnly=direct,
                  horizonSeconds=86400, lineLimit=3, departureLimit=6)
             for mode in ('departure', 'line') for suffix, direct in (('all', False), ('direct', True))]
FIELDS = {'contract', 'schemaVersion', 'qualityContextFingerprint', 'observationInstants',
          'displayScenarios', 'timezone', 'requiredServiceDates', 'contextFingerprint'}


def required_dates(instant):
    if not isinstance(instant, str): quality.fail('display_instant_invalid')
    try:
        value = datetime.strptime(instant, '%Y-%m-%dT%H:%M:%SZ')
        if value.isoformat(timespec='seconds') + 'Z' != instant: raise ValueError()
        day = (value.replace(tzinfo=timezone.utc) + timedelta(hours=9)).date()
        return [(day + timedelta(days=n)).isoformat() for n in (-1, 0, 1)]
    except (ValueError, OverflowError): quality.fail('display_instant_invalid')


def normalize_context(context, quality_context, *, seal=False):
    q = quality.normalize_context(quality_context)
    if not isinstance(context, dict) or set(context) != FIELDS - ({'contextFingerprint'} if seal and 'contextFingerprint' not in context else set()):
        quality.fail('display_context_fields_invalid')
    c = copy.deepcopy(context)
    if c['contract'] != CONTRACT or type(c['schemaVersion']) is not int or c['schemaVersion'] != 1:
        quality.fail('display_context_contract_invalid')
    if c['qualityContextFingerprint'] != q['contextFingerprint']:
        quality.fail('display_quality_context_mismatch', 'incomparable')
    if c['timezone'] != 'Asia/Tokyo': quality.fail('display_timezone_invalid')
    c['observationInstants'] = quality._set_list(c['observationInstants'], 'display_instants_invalid')
    if not 1 <= len(c['observationInstants']) <= 1000: quality.fail('display_instants_invalid')
    expected = {instant: required_dates(instant) for instant in c['observationInstants']}
    if c['requiredServiceDates'] != expected: quality.fail('display_required_dates_mismatch')
    available = set(q['serviceDates'] + q['auxiliaryServiceDates'])
    if any(not set(days) <= available for days in expected.values()):
        quality.fail('display_quality_dates_missing', 'incomparable')
    if not isinstance(c['displayScenarios'], list) or len(c['displayScenarios']) != 4:
        quality.fail('display_scenarios_invalid')
    try: c['displayScenarios'].sort(key=lambda s: s['id'])
    except (TypeError, KeyError): quality.fail('display_scenarios_invalid')
    # Compare canonical bytes as Python equality alone equates bool and int.
    if quality.canonical(c['displayScenarios']) != quality.canonical(SCENARIOS): quality.fail('display_scenarios_invalid')
    fp = quality.digest({k: v for k, v in c.items() if k != 'contextFingerprint'})
    if not seal and c['contextFingerprint'] != fp: quality.fail('display_context_fingerprint_mismatch')
    c['contextFingerprint'] = fp
    return c


def create_context(quality_context, observation_instants):
    return normalize_context(dict(contract=CONTRACT, schemaVersion=1,
        qualityContextFingerprint=quality_context['contextFingerprint'], observationInstants=observation_instants,
        displayScenarios=copy.deepcopy(SCENARIOS), timezone='Asia/Tokyo',
        requiredServiceDates={i: required_dates(i) for i in observation_instants}), quality_context, seal=True)
