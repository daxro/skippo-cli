"""Command line interface for Skippo."""
import argparse
import datetime as dt
import getpass
import json
import math
import os
import re
import sys
from urllib.parse import quote

from . import __version__, assets, core, extended
from .core import Error


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Error(message + ". Run skippo --help for usage.", 2, "input")


def parser():
    p = Parser(prog="skippo", description="Manage your Skippo boat profile.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--json", action="store_true", help="Write JSON to stdout")
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress status messages")
    p.add_argument("--no-input", action="store_true", help="Never prompt")
    p.add_argument("--no-color", action="store_true", help="Disable color")
    subs = p.add_subparsers(dest="group", required=True)
    auth = subs.add_parser("auth").add_subparsers(dest="action", required=True)
    a = auth.add_parser("login")
    a.add_argument("--email")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--password-stdin", action="store_true")
    g.add_argument("--password-file")
    auth.add_parser("status")
    auth.add_parser("logout")
    config = subs.add_parser("config").add_subparsers(dest="action", required=True)
    config.add_parser("get")
    a = config.add_parser("set")
    a.add_argument("key", choices=["boat"])
    a.add_argument("value")
    boats = subs.add_parser("boats").add_subparsers(dest="action", required=True)
    boats.add_parser("list")
    a = boats.add_parser("show")
    a.add_argument("id", nargs="?")
    a = boats.add_parser("update")
    a.add_argument("id", nargs="?")
    a.add_argument("--name")
    a.add_argument("--year", type=int)
    a.add_argument("--dry-run", action="store_true")
    a = boats.add_parser("harbor", help="Set the boat's home harbor coordinates")
    a.add_argument("id", nargs="?")
    a.add_argument("--latitude", type=float, required=True)
    a.add_argument("--longitude", type=float, required=True)
    a.add_argument("--dry-run", action="store_true")
    engines = subs.add_parser("engines").add_subparsers(dest="action", required=True)
    for action in ("list", "add", "update"):
        a = engines.add_parser(action)
        a.add_argument("--boat")
        if action != "list":
            a.add_argument("--type", choices=["diesel", "petrol", "electric", "other", "none"])
            a.add_argument("--horsepower", type=float)
            a.add_argument("--year", type=int)
            a.add_argument("--number-of-engines", type=int)
            a.add_argument("--dry-run", action="store_true")
    checks = subs.add_parser("checklists").add_subparsers(dest="action", required=True)
    for action in ("list", "show", "check", "uncheck", "add-item", "delete-item"):
        a = checks.add_parser(action)
        a.add_argument("--boat")
        if action != "list":
            a.add_argument("id", help="Checklist ID")
        if action in ("check", "uncheck", "delete-item"):
            a.add_argument("item", help="Checklist item ID")
        if action == "add-item":
            a.add_argument("--text", required=True)
        if action in ("check", "uncheck", "add-item", "delete-item"):
            a.add_argument("--dry-run", action="store_true")
        if action == "delete-item":
            a.add_argument("--yes", action="store_true")
    for group in ("events", "notes"):
        sub = subs.add_parser(group).add_subparsers(dest="action", required=True)
        actions = ("list", "show", "add") if group == "events" else ("list", "show", "add", "update", "delete")
        for action in actions:
            a = sub.add_parser(action)
            a.add_argument("--boat")
            if action in ("show", "update", "delete"):
                a.add_argument("id")
            if action == "list" and group == "events":
                a.add_argument("--since", type=date)
                a.add_argument("--until", type=date)
                a.add_argument("--limit", type=positive, default=100)
            if action in ("add", "update"):
                a.add_argument("--title", required=action == "add")
                if group == "notes":
                    a.add_argument("--content")
                else:
                    a.add_argument("--description")
                    a.add_argument("--date", type=date, required=True)
                    a.add_argument("--category", choices=["purchase", "installation", "repair", "service", "fuel", "other"], required=True)
            if action in ("add", "update", "delete"):
                a.add_argument("--dry-run", action="store_true")
            if action == "delete":
                a.add_argument("--yes", action="store_true")
    extended.configure(subs, date)
    assets.configure(subs)
    trips = subs.add_parser("trips").add_subparsers(dest="action", required=True)
    a = trips.add_parser("list")
    a.add_argument("--since", type=date)
    a.add_argument("--until", type=date)
    a.add_argument("--limit", type=positive, default=100)
    a = trips.add_parser("show")
    a.add_argument("id")
    return p


def date(value):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use an ISO date (YYYY-MM-DD).") from None


def positive(value):
    try:
        n = int(value)
        if not 1 <= n <= 1000:
            raise ValueError
        return n
    except ValueError:
        raise argparse.ArgumentTypeError("Must be between 1 and 1000.") from None


def pathid(value):
    if not isinstance(value, (str, int)) or not str(value) or "/" in str(value) or str(value) in (".", ".."):
        raise Error("Invalid resource ID.", 2, "input")
    return quote(str(value), safe="")


def profiles():
    result = core.hub("/boat-profiles")
    if not isinstance(result, dict) or not isinstance(result.get("boatProfiles"), list):
        raise Error("Invalid boat profile response.", 5, "service")
    return result["boatProfiles"]


def find(items, identifier, label):
    found = [x for x in items if isinstance(x, dict) and str(x.get("id")) == str(identifier)]
    if len(found) != 1:
        raise Error(f"{label} not found: {identifier}", 4, "not_found")
    return found[0]


def boat(identifier=None):
    all_boats = profiles()
    identifier = identifier or core.read("config.json").get("boat")
    if identifier:
        return find(all_boats, identifier, "Boat")
    if len(all_boats) != 1:
        raise Error("Select a boat with --boat or run skippo config set boat ID.", 2, "config")
    return all_boats[0]


def collection(b, kind):
    result = core.hub(f"/boat-profiles/{pathid(b['id'])}/{kind}/all")
    if not isinstance(result, list):
        raise Error(f"Invalid {kind} response.", 5, "service")
    return result


def engines(profile):
    """Normalize the legacy and current single-engine profile representations."""
    plural = profile.get("engines")
    singular = profile.get("engine")
    if plural is not None:
        if not isinstance(plural, list) or any(not isinstance(x, dict) for x in plural):
            raise Error("Invalid engines response.", 5, "service")
        if plural:
            return plural
    if singular is not None:
        if not isinstance(singular, dict):
            raise Error("Invalid engine response.", 5, "service")
        return [singular]
    return []


def write(path, payload, method, dry, verify, reconcile):
    if dry:
        return {"dry_run": True, "method": method, "path": path, "body": payload}
    try:
        result = core.hub(path, method=method, payload=payload)
    except Error as e:
        if e.code == 5:
            raise Error(f"Write outcome unknown; inspect with: {reconcile}", 5, "outcome_unknown") from None
        raise
    try:
        verified = verify(result)
        if not verified:
            raise ValueError
    except (Error, ValueError, KeyError, TypeError):
        raise Error(f"Write completed but could not be verified; inspect with: {reconcile}", 5, "written_not_verified") from None
    return verified


def execute(a):
    if a.group == "auth":
        if a.action == "logout":
            core.logout()
            return {"authenticated": False}
        if a.action == "status":
            profiles()
            return {"authenticated": True}
        if not a.email:
            if a.no_input or not sys.stdin.isatty():
                raise Error("Provide --email.", 2, "input")
            print("Email: ", end="", file=sys.stderr, flush=True)
            a.email = sys.stdin.readline().strip()
        if not a.email:
            raise Error("Email is empty.", 2, "input")
        if a.password_file:
            try:
                with open(a.password_file, encoding="utf-8") as f:
                    password = f.read().rstrip("\r\n")
            except (OSError, UnicodeError):
                raise Error("Could not read password file.", 2, "input") from None
        elif a.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        elif a.no_input or not sys.stdin.isatty():
            raise Error("Provide --password-stdin or --password-file.", 2, "input")
        else:
            password = getpass.getpass()
        if not password:
            raise Error("Password is empty.", 2, "input")
        core.login(a.email, password)
        return {"authenticated": True}
    if a.group == "config":
        if a.action == "get":
            return core.read("config.json")
        b = find(profiles(), a.value, "Boat")
        with core.locked():
            config = core.read("config.json")
            config["boat"] = str(b["id"])
            core.save("config.json", config)
        return config
    if a.group == "trips":
        if a.action == "show":
            return decode_document(core.firestore("/" + pathid(a.id)))
        if a.since and a.until and a.since > a.until:
            raise Error("--since must not be after --until.", 2, "input")
        documents = []
        token = None
        seen = set()
        for _ in range(10):
            query = "?pageSize=100" + ("&pageToken=" + quote(token, safe="") if token else "")
            result = core.firestore(query)
            if not isinstance(result, dict) or not isinstance(result.get("documents", []), list):
                raise Error("Invalid trips response.", 5, "service")
            documents.extend(decode_document(x) for x in result.get("documents", []))
            token = result.get("nextPageToken")
            if token is not None and not isinstance(token, str):
                raise Error("Invalid trip pagination cursor.", 5, "service")
            if not token:
                break
            if token in seen:
                raise Error("Trip pagination repeated a cursor.", 5, "service")
            seen.add(token)
        else:
            raise Error("Trip account exceeds the supported scan bound of 1000 documents.", 5, "service")
        def include_trip(item):
            try:
                d = dt.datetime.fromtimestamp(item["startTimeInMillis"] / 1000, dt.timezone.utc).date()
            except (KeyError, TypeError, ValueError, OverflowError):
                raise Error("Invalid trip date in service response.", 5, "service") from None
            return (not a.since or d >= a.since) and (not a.until or d <= a.until)
        return sorted(filter(include_trip, documents), key=lambda x: x["startTimeInMillis"], reverse=True)[:a.limit]
    if a.group == "insurance" and a.action == "companies":
        result = core.hub("/insurances/companies/list")
        if not isinstance(result, list):
            raise Error("Invalid insurance companies response.", 5, "service")
        return result + ([{"id": "-", "name": "Other"}] if not any(str(x.get('id')) == '-' for x in result if isinstance(x, dict)) else [])
    if a.group == "boats" and a.action == "list":
        return profiles()
    b = boat(getattr(a, "boat", None) or (getattr(a, "id", None) if a.group == "boats" else None))
    bid = pathid(b["id"])
    if a.group == "attachments":
        return assets.execute(a, b, (find, pathid, collection, extended.confirm))
    if a.group in ("settings", "insurance", "fuel"):
        return extended.execute(a, b, (find, pathid, boat, collection, write))
    if a.group == "boats":
        if a.action == "show":
            return b
        if a.action == "harbor":
            if not math.isfinite(a.latitude) or not -90 <= a.latitude <= 90 or not math.isfinite(a.longitude) or not -180 <= a.longitude <= 180:
                raise Error("Coordinates must be finite latitude [-90, 90] and longitude [-180, 180].", 2, "input")
            coordinate = {"lat": a.latitude, "lon": a.longitude}
            return write(f"/boat-profiles/{bid}/home-harbor", coordinate, "POST", a.dry_run,
                         lambda _: next((x.get("homeHarbor") for x in profiles() if str(x.get("id")) == str(b['id']) and (x.get("homeHarbor") or {}).get("coordinate") == coordinate), None), "skippo boats show " + bid)
        changes = {k: v for k, v in {"name": a.name, "year": a.year}.items() if v is not None}
        if not changes or (a.year is not None and not 1800 <= a.year <= 2100):
            raise Error("Provide valid --name or --year (1800–2100).", 2, "input")
        data = dict(b.get("baseData") or {})
        data.update(changes)
        return write(f"/boat-profiles/{bid}/base-data", data, "POST", a.dry_run,
                     lambda _: next((x.get("baseData") for x in profiles() if str(x.get("id")) == str(b['id']) and all((x.get("baseData") or {}).get(k) == v for k, v in changes.items())), None), "skippo boats show " + bid)
    if a.group == "engines":
        existing = engines(b)
        if a.action == "list":
            return existing
        if len(existing) > 1:
            raise Error("Multiple engines require explicit selection; this service operation is not established.", 5, "unsupported_schema")
        engine = existing[0] if existing else None
        if (a.action == "add" and engine) or (a.action == "update" and not engine):
            raise Error("Engine already exists." if engine else "Engine not found.", 2 if engine else 4, "input")
        obj = {k: v for k, v in (engine or {}).items() if k in ("type", "data")}
        if obj.get("data") is not None and not isinstance(obj["data"], dict):
            raise Error("Invalid engine data response.", 5, "service")
        data = dict(obj.get("data") or {})
        if a.number_of_engines is not None:
            raise Error("The service did not retain number of engines during verification; this field is unavailable.", 2, "unsupported_schema")
        changes = {"horsePower": a.horsepower, "year": a.year, "numberOfEngines": a.number_of_engines}
        if all(v is None for v in changes.values()) and a.type is None:
            raise Error("Provide an engine field.", 2, "input")
        if any(v is not None and (not math.isfinite(v) or v <= 0) for v in changes.values()) or (a.year is not None and not 1800 <= a.year <= 2100):
            raise Error("Engine numeric fields must be finite and positive; year must be 1800–2100.", 2, "input")
        data.update({k: v for k, v in changes.items() if v is not None})
        if a.type is not None:
            obj["type"] = ["diesel", "petrol", "electric", "other", "none"].index(a.type)
        if "type" not in obj:
            raise Error("--type is required for a new engine.", 2, "input")
        if obj["type"] == 4 and any(v is not None for v in changes.values()):
            raise Error("Engine data fields cannot be combined with type none.", 2, "input")
        obj["data"] = None if obj["type"] == 4 else data
        def verify_engine(_):
            current = engines(boat(str(b['id'])))
            if len(current) != 1 or current[0].get("type") != obj["type"]:
                return None
            saved = current[0]
            if obj["type"] == 4:
                return saved if not saved.get("data") else None
            saved_data = saved.get("data")
            if not isinstance(saved_data, dict):
                return None
            return saved if all(saved_data.get(k) == v for k, v in data.items()) else None
        return write(f"/boat-profiles/{bid}/engine", obj, "POST", a.dry_run,
                     verify_engine, "skippo engines list --boat " + bid)
    if a.group == "checklists":
        lists = b.get("checklists") or []
        if a.action == "list":
            return lists
        check = find(lists, a.id, "Checklist")
        if a.action == "show":
            return check
        if a.action == "add-item":
            if not a.text.strip() or len(a.text) > 1000:
                raise Error("Item text must contain 1–1000 characters.", 2, "input")
            def verify_added(result):
                if not isinstance(result, dict) or not result.get("id"):
                    return None
                fresh = boat(str(b['id']))
                return find(find(fresh.get('checklists') or [], a.id, 'Checklist').get('items') or [], result['id'], 'Item')
            return write(f"/checklists/{pathid(a.id)}/item?text={quote(a.text, safe='')}", {}, "POST", a.dry_run, verify_added, f"skippo checklists show {pathid(a.id)} --boat {bid}")
        item = find(check.get("items") or [], a.item, "Checklist item")
        if a.action == "delete-item":
            if item.get("type") != 0:
                raise Error("Only user-created checklist items can be deleted.", 2, "input")
            extended.confirm(a, "checklist item")
            def verify_deleted(_):
                fresh = boat(str(b['id']))
                items = find(fresh.get('checklists') or [], a.id, 'Checklist').get('items') or []
                return {"deleted": a.item} if not any(str(x.get('id')) == a.item for x in items) else None
            return write(f"/checklists/item/{pathid(item['id'])}", None, "DELETE", a.dry_run, verify_deleted, f"skippo checklists show {pathid(a.id)} --boat {bid}")
        checked = a.action == "check"
        def verify(_):
            fresh = boat(str(b['id']))
            return find(find(fresh.get('checklists') or [], a.id, 'Checklist').get('items') or [], a.item, 'Item') if find(find(fresh.get('checklists') or [], a.id, 'Checklist').get('items') or [], a.item, 'Item').get('checked') == checked else None
        return write(f"/checklists/item/{pathid(item['id'])}?checked={str(checked).lower()}", {}, "PUT", a.dry_run, verify, f"skippo checklists show {pathid(a.id)} --boat {bid}")
    kind = "boat-events" if a.group == "events" else "notes"
    items = collection(b, kind)
    if a.action == "list":
        if a.group == "events":
            if a.since and a.until and a.since > a.until:
                raise Error("--since must not be after --until.", 2, "input")
            def include(item):
                try:
                    d = dt.datetime.fromtimestamp(item['dateEpochMs'] / 1000, dt.timezone.utc).date()
                    return (not a.since or d >= a.since) and (not a.until or d <= a.until)
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise Error("Invalid event date in service response.", 5, "service") from None
            return sorted(filter(include, items), key=lambda x: x['dateEpochMs'], reverse=True)[:a.limit]
        return items
    old = find(items, a.id, a.group[:-1].title()) if a.action in ("show", "update", "delete") else None
    if a.action == "show":
        return old
    if a.action == "delete" and not a.dry_run and not a.yes:
        if a.no_input or not sys.stdin.isatty():
            raise Error("Deletion requires --yes in non-interactive mode.", 2, "input")
        print("Delete this note? [y/N] ", end="", file=sys.stderr, flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            raise Error("Deletion cancelled.", 2, "cancelled")
    prefix = f"/boat-profiles/{bid}/{kind}"
    if a.group == "notes":
        if a.action == "delete":
            return write(prefix + "/note/" + pathid(a.id), {}, "DELETE", a.dry_run,
                         lambda _: {"deleted": a.id} if not any(str(x.get("id")) == a.id for x in collection(b, kind)) else None, f"skippo notes list --boat {bid}")
        obj = dict(old or {})
        if a.title is not None:
            obj["title"] = a.title
        if a.content is not None:
            obj["content"] = a.content
        if not obj.get("title"):
            raise Error("A note title is required.", 2, "input")
        obj.setdefault("content", "")
        def verify_notes(_):
            fresh = collection(b, kind)
            matches = [x for x in fresh if x.get('title') == obj['title'] and x.get('content', '') == obj['content'] and (not old or str(x.get('id')) == str(old['id'])) and (old or all(str(x.get('id')) != str(y.get('id')) for y in items))]
            return matches[0] if len(matches) == 1 else None
        return write(prefix + "/note", obj, "POST", a.dry_run, verify_notes, f"skippo notes list --boat {bid}")
    obj = {"category": ["purchase", "installation", "repair", "service", "fuel", "other"].index(a.category), "title": a.title,
           "dateEpochMs": int(dt.datetime.combine(a.date, dt.time(), dt.timezone.utc).timestamp() * 1000)}
    if a.description:
        obj["description"] = a.description
    def verify_events(result):
        fresh = collection(b, kind)
        if isinstance(result, dict) and result.get('id'):
            found = find(fresh, result['id'], 'Event')
            return found if all(found.get(k) == v for k, v in obj.items()) else None
        return None
    return write(prefix, obj, "POST", a.dry_run, verify_events, f"skippo events list --boat {bid}")


def decode_document(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("fields", {}), dict) or not isinstance(doc.get("name"), str):
        raise Error("Invalid trip document.", 5, "service")
    uid = core.session().get("uid")
    marker = "/users/" + str(uid) + "/tracks2026/"
    if not uid or marker not in doc["name"] or "/" in doc["name"].split(marker, 1)[1]:
        raise Error("Unexpected trip document path.", 5, "service")
    def decode(value):
        if not isinstance(value, dict) or len(value) != 1:
            raise Error("Invalid trip field.", 5, "service")
        kind, v = next(iter(value.items()))
        if kind == "integerValue":
            return int(v)
        if kind in ("stringValue", "doubleValue", "booleanValue", "timestampValue", "nullValue", "referenceValue", "geoPointValue", "bytesValue"):
            return v
        if kind == "mapValue":
            return {k: decode(x) for k, x in v.get("fields", {}).items()}
        if kind == "arrayValue":
            return [decode(x) for x in v.get("values", [])]
        raise Error("Unsupported trip field type.", 5, "service")
    try:
        result = {k: decode(v) for k, v in doc.get("fields", {}).items()}
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise Error("Invalid trip fields in service response.", 5, "service") from None
    result["id"] = doc["name"].rsplit("/", 1)[-1]
    return result


def redact_urls(value):
    if isinstance(value, dict):
        return {k: redact_urls(v) for k, v in value.items() if k not in ('originalUrl', 'scaledUrl')}
    if isinstance(value, list):
        return [redact_urls(x) for x in value]
    return value


def print_human(value, indent=0):
    prefix = " " * indent
    if isinstance(value, list):
        if not value:
            print(prefix + "(none)")
        for index, item in enumerate(value):
            if index:
                print()
            print_human(item, indent)
    elif isinstance(value, dict):
        if not value:
            print(prefix + "(none)")
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(prefix + str(key) + ":")
                print_human(item, indent + 2)
            else:
                safe = "".join(c if c >= " " and c != "\x7f" else f"\\x{ord(c):02x}" for c in str(item))
                print(prefix + str(key) + ": " + safe)
    else:
        print(prefix + str(value))


def main():
    argv = sys.argv[1:]
    globals_ = []
    rest = []
    end_options = False
    for x in argv:
        if x == "--":
            end_options = True
        if not end_options and x in ("--json", "--quiet", "-q", "--no-input", "--no-color"):
            globals_.append(x)
        else:
            rest.append(x)
    argv = globals_ + rest
    machine = "--json" in argv
    try:
        try:
            a = parser().parse_args(argv)
        except SystemExit:
            sys.stdout.flush()
            raise
        result = redact_urls(execute(a))
        if machine:
            print(json.dumps(result, ensure_ascii=False))
        elif result is not None:
            print_human(result)
        sys.stdout.flush()
        return 0
    except Error as e:
        print(json.dumps({"error": {"type": e.kind, "message": str(e)}}) if machine else f"Error: {e}", file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print(json.dumps({"error": {"type": "interrupted", "message": "Interrupted."}}) if machine else "Interrupted.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(fd, sys.stdout.fileno())
        os.close(fd)
        return 0
    except Exception:  # noqa: BLE001 - keep unexpected errors and secrets off stderr
        print(json.dumps({"error": {"type": "unexpected", "message": "Unexpected error."}}) if machine else "Error: Unexpected error.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
