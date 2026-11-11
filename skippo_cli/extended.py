"""Boat settings, insurance, and fuel log operations."""
import argparse
import datetime as dt
import math
import sys
from decimal import Decimal, InvalidOperation

from . import core
from .core import Error


def decimal_number(value):
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError
        return number
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError('Must be a finite decimal number.') from None


def configure(subs, date):
    for group in ('settings', 'insurance'):
        sub = subs.add_parser(group).add_subparsers(dest='action', required=True)
        for action in ('show', 'update'):
            a = sub.add_parser(action)
            a.add_argument('--boat')
            if action == 'update':
                a.add_argument('--dry-run', action='store_true')
                if group == 'settings':
                    a.add_argument('--safe-depth', type=float, help='Metres')
                    a.add_argument('--safe-height', type=float, help='Metres')
                    a.add_argument('--average-speed', type=float, help='Knots')
                    a.add_argument('--consumption', type=float, help='Litres per nautical mile')
                else:
                    a.add_argument('--company-id')
                    a.add_argument('--policy-number')
                    a.add_argument('--expiration-date', type=date)
                    a.add_argument('--clear', action='append', choices=('expiration-date',), default=[],
                                   help='Remove an optional field (repeatable)')
                    reminders = a.add_mutually_exclusive_group()
                    reminders.add_argument('--reminder', action='store_const', const=True, default=None)
                    reminders.add_argument('--no-reminder', dest='reminder', action='store_const', const=False)
        if group == 'insurance':
            sub.add_parser('companies')
            a = sub.add_parser('delete')
            a.add_argument('--boat')
            a.add_argument('--yes', action='store_true')
            a.add_argument('--dry-run', action='store_true')
    fuel = subs.add_parser('fuel').add_subparsers(dest='action', required=True)
    for action in ('list', 'show', 'add', 'update', 'delete'):
        a = fuel.add_parser(action)
        a.add_argument('--boat')
        if action in ('show', 'update', 'delete'):
            a.add_argument('id')
        if action in ('add', 'update'):
            a.add_argument('--type', choices=('gasoline', 'diesel', 'hvo100'), required=action == 'add')
            a.add_argument('--liters', type=decimal_number)
            a.add_argument('--source', help='Supplier or station')
            prices = a.add_mutually_exclusive_group()
            prices.add_argument('--cost', type=float)
            prices.add_argument('--price-per-liter', type=decimal_number)
            a.add_argument('--currency', choices=('SEK', 'NOK', 'DKK', 'EUR'))
            a.add_argument('--date', type=date, required=action == 'add')
            if action == 'update':
                a.add_argument('--clear', action='append', choices=('liters', 'cost'), default=[],
                               help='Remove an optional field (repeatable)')
        if action in ('add', 'update', 'delete'):
            a.add_argument('--dry-run', action='store_true')
        if action == 'delete':
            a.add_argument('--yes', action='store_true')


def confirm(a, label):
    if a.dry_run or a.yes:
        return
    if a.no_input or not sys.stdin.isatty():
        raise Error('Deletion requires --yes in non-interactive mode.', 2, 'input')
    print(f'Delete this {label}? [y/N] ', end='', file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() not in ('y', 'yes'):
        raise Error('Deletion cancelled.', 2, 'cancelled')


def execute(a, b, helpers):
    find, pathid, boat, collection, write = helpers
    bid = pathid(b['id'])
    if a.group in ('settings', 'insurance'):
        field = 'navigationSettings' if a.group == 'settings' else 'insurance'
        old = b.get(field) or {}
        if a.action == 'show':
            return old
        if not isinstance(old, dict):
            raise Error('Invalid profile data.', 5, 'service')
        if a.group == 'insurance' and a.action == 'delete':
            if not old.get('id'):
                raise Error('Insurance not found.', 4, 'not_found')
            confirm(a, 'insurance')
            return write(f"/boat-profiles/{bid}/boat-insurance/insurance/{pathid(old['id'])}", {}, 'DELETE', a.dry_run,
                         lambda _: {'deleted': str(old['id'])} if not boat(str(b['id'])).get('insurance') else None,
                         f'skippo insurance show --boat {bid}')
        if a.group == 'settings':
            vals = {'safeDepthInMeters': a.safe_depth, 'safeHeightInMeters': a.safe_height,
                    'speedInMs': a.average_speed / 1.9438444924406 if a.average_speed is not None else None,
                    'fuelConsumptionInLitersPerNm': a.consumption}
            path = f'/boat-profiles/{bid}/navigation-settings'
        else:
            vals = {'insuranceCompanyId': a.company_id, 'insuranceNumber': a.policy_number,
                    'expirationDateEpochMs': int(dt.datetime.combine(a.expiration_date, dt.time(), dt.timezone.utc).timestamp()*1000) if a.expiration_date else None,
                    'reminderEnabled': a.reminder}
            path = f'/boat-profiles/{bid}/boat-insurance'
        changes = {k: v for k, v in vals.items() if v is not None}
        cleared = set(getattr(a, 'clear', []))
        if 'expiration-date' in cleared and a.expiration_date is not None:
            raise Error('--clear expiration-date cannot be combined with --expiration-date.', 2, 'input')
        if not changes and not cleared:
            raise Error('Provide at least one field to update.', 2, 'input')
        for value in changes.values():
            if isinstance(value, float) and (not math.isfinite(value) or value < 0):
                raise Error('Numeric fields must be finite and non-negative.', 2, 'input')
        if a.group == 'insurance':
            keys = ('id', 'insuranceCompanyId', 'insuranceNumber', 'expirationDateEpochMs', 'reminderEnabled')
        else:
            keys = ('safeDepthInMeters', 'safeHeightInMeters', 'speedInMs', 'fuelConsumptionInLitersPerNm')
        obj = {k: old[k] for k in keys if k in old}
        obj.update(changes)
        if 'expiration-date' in cleared:
            obj.pop('expirationDateEpochMs', None)
        if a.group == 'insurance' and not obj.get('insuranceCompanyId'):
            raise Error('Provide --company-id when creating insurance.', 2, 'input')
        if a.group == 'insurance' and a.company_id is not None and a.company_id != '-':
            companies = core.hub('/insurances/companies/list')
            if not isinstance(companies, list):
                raise Error('Invalid insurance companies response.', 5, 'service')
            find(companies, a.company_id, 'Insurance company')
        def verify(_):
            fresh = boat(str(b['id'])).get(field) or {}
            if 'expiration-date' in cleared and fresh.get('expirationDateEpochMs') is not None:
                return None
            return fresh if all((math.isclose(fresh.get(k), v, rel_tol=0, abs_tol=0.00501) if k == 'speedInMs' and isinstance(fresh.get(k), (float, int)) else fresh.get(k) == v) for k, v in changes.items()) else None
        return write(path, obj, 'POST', a.dry_run, verify, f'skippo {a.group} show --boat {bid}')
    items = [e for e in collection(b, 'boat-events') if e.get('category') == 4]
    if a.action == 'list':
        return items
    old = find(items, a.id, 'Fuel event') if a.action in ('show', 'update', 'delete') else None
    if a.action == 'show':
        return old
    prefix = f'/boat-profiles/{bid}/boat-events'
    if a.action == 'delete':
        confirm(a, 'fuel event')
        return write(prefix + '/event/' + pathid(a.id), {}, 'DELETE', a.dry_run,
                     lambda _: {'deleted': a.id} if not any(str(x.get('id')) == a.id for x in collection(b, 'boat-events')) else None,
                     f'skippo fuel list --boat {bid}')
    obj = {k: old[k] for k in ('id', 'title', 'description', 'dateEpochMs', 'cost', 'costSource') if old and k in old}
    obj['category'] = 4
    cleared = set(getattr(a, 'clear', []))
    if 'liters' in cleared and (a.liters is not None or a.price_per_liter is not None):
        raise Error('--clear liters cannot be combined with --liters or --price-per-liter.', 2, 'input')
    if 'cost' in cleared and (a.cost is not None or a.price_per_liter is not None or a.currency is not None):
        raise Error('--clear cost cannot be combined with a price or currency.', 2, 'input')
    for name, key in (('liters', 'description'), ('cost', 'cost')):
        if name in cleared:
            obj.pop(key, None)
    if a.type is not None:
        obj['title'] = {'gasoline': 'Gasoline', 'diesel': 'Diesel', 'hvo100': 'HVO100'}[a.type]
    if a.date is not None:
        obj['dateEpochMs'] = int(dt.datetime.combine(a.date, dt.time(), dt.timezone.utc).timestamp()*1000)
    for name in ('liters', 'cost'):
        value = getattr(a, name)
        if value is not None and (not math.isfinite(value) or value < 0):
            raise Error(f'--{name} must be finite and non-negative.', 2, 'input')
    if a.liters is not None:
        if a.liters > Decimal(100000000) or a.liters.as_tuple().exponent < -12:
            raise Error('--liters must be at most 100000000 with at most 12 decimal places.', 2, 'input')
        obj['description'] = format(a.liters, 'f')
    if a.source is not None:
        obj['costSource'] = a.source
    if a.price_per_liter is not None:
        if a.price_per_liter < 0 or a.price_per_liter > Decimal(100000000):
            raise Error('--price-per-liter must be non-negative and at most 100000000.', 2, 'input')
        if a.liters is None:
            raise Error('--price-per-liter requires --liters.', 2, 'input')
        a.cost = float(a.price_per_liter * a.liters)
    if a.currency is not None and a.cost is None:
        raise Error('--currency requires --cost or --price-per-liter.', 2, 'input')
    if a.cost is not None:
        currency = a.currency or (old or {}).get('cost', {}).get('currency') or 'SEK'
        obj['cost'] = {'amount': a.cost, 'currency': currency}
    if a.action == 'update' and not cleared and not any(getattr(a, k) is not None for k in ('type', 'date', 'liters', 'cost', 'source')):
        raise Error('Provide a field to update.', 2, 'input')
    def attachment_ids(event):
        values = event.get('assets') or []
        if not isinstance(values, list) or any(not isinstance(x, dict) or not x.get('id') for x in values):
            raise Error('Invalid fuel attachment metadata.', 5, 'service')
        return {str(x['id']) for x in values}
    existing_attachments = attachment_ids(old) if old else set()
    def verify(result):
        identifier = (result or {}).get('id') if isinstance(result, dict) else None
        if not identifier:
            return None
        found = find(collection(b, 'boat-events'), identifier, 'Fuel event')
        if old and str(identifier) != str(old['id']):
            return None
        if any(found.get(key) is not None for name, key in (('liters', 'description'), ('cost', 'cost')) if name in cleared):
            return None
        if not existing_attachments.issubset(attachment_ids(found)):
            return None
        return found if all(found.get(k) == v for k, v in obj.items()) else None
    return write(prefix, obj, 'POST', a.dry_run, verify, f'skippo fuel list --boat {bid}')
