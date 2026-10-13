#!/usr/bin/env python3
"""Render the Lovelace views the way Home Assistant would.

Usage:
    python tests/validate_dashboards.py [path/to/opendtu_ems.yaml]

Why this exists
---------------
`validate_dashboards.py` complements `validate_package.py`. That test checks the
*literal* entity ids a dashboard names (`entity: sensor.x`); it cannot see the
ids a card builds inside a Jinja template - and a card whose template points at
a name that does not exist renders **nothing at all**: the entity has data, the
card stays empty, and nothing is logged in Home Assistant. That is the
"dashboards have data but show nothing" failure this test is for.

What it does
------------
1. resolves the sensor mapping to the reference installation, renders the whole
   sensor chain of the package (mirrors -> grid -> capacity -> mode -> target ->
   delivery -> degraded) so every EMS entity has a realistic state AND its
   attributes exist
2. walks both dashboard files and renders every embedded template with those
   states - mushroom chips, markdown cards and card `template:` options
3. fails when
     * a template raises (the card then shows "Entity not available")
     * a named entity (`entity:`, `state_of_charge:`, ...) is not created by the
       package
     * a template reads an entity id the package does not create (checked from
       the template source, so ids inside Jinja count)
     * a card entity's state is empty, `unknown` or `unavailable` on a sunny day
4. repeats the render with an EMPTY mapping (the state after an update, before
   the blueprint was run): the boards must still render, must not raise and must
   not print `None` anywhere - that is the difference between "no data because
   the mapping is empty" (expected, `sensor.ems_map_status` says so) and "the
   card is broken".
"""
from __future__ import annotations

import importlib.util
import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE = ROOT / "packages" / "opendtu_ems.yaml"
DASHBOARDS = ROOT / "dashboards"

# every domain a dashboard may reference, and the ones the package creates
ENTITY_RE = re.compile(
    r"\b(?:sensor|binary_sensor|input_boolean|input_number|input_datetime"
    r"|input_text|script|automation|number|switch|light)\.[a-z0-9_]+")
QUOTED_RE = re.compile( 
    r"['\"]((?:sensor|binary_sensor|input_boolean|input_number|input_datetime"
    r"|input_text|script|automation|sun)\.[a-z0-9_]+)['\"]")
BROKEN = ("", "none", "unknown", "unavailable", "entity not available", "undefined")

# created by the HACS integration, not by the package - see validate_integration.py
INTEGRATION_ENTITIES = {"sensor.ems_bundle"}

fails: list[tuple[str, list[str]]] = []


def load_module(path: Path, name: str):
    """Import a sibling test module so its harness can be reused."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


vp = load_module(ROOT / "tests" / "validate_package.py", "vp")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def created_entities(doc: dict) -> set[str]:
    """Every entity the package creates - same rules as validate_package.py."""
    created: set[str] = set()
    for domain in ("input_boolean", "input_number", "input_datetime", "input_text"):
        created |= {f"{domain}.{key}" for key in doc.get(domain, {})}
    created |= {f"script.{key}" for key in doc.get("script", {})}
    created |= {f"automation.{slugify(a.get('alias'))}" for a in doc.get("automation", [])}
    for block in doc["template"]:
        for domain, entities in block.items():
            created |= {f"{domain}.{slugify(e.get('name'))}" for e in entities}
    return created


def render(expr: str, data: dict) -> str:
    """Render one template with the package's fake Home Assistant globals."""
    return vp.make_env(data).from_string(str(expr)).render().strip()


def resolve_chain(doc: dict, data: dict, *, mapping: bool) -> tuple[dict, list[str]]:
    """Render the sensor chain in dependency order.

    Returns the state set plus the attributes as `__attr:<entity>:<name>` entries
    (which is what vp.make_env's state_attr reads), so dashboard templates that
    use `state_attr(...)` work too.
    """
    notes: list[str] = []
    sensors = {s["unique_id"]: s for s in doc["template"][0]["sensor"]}
    # keyed by name: one binary sensor deliberately has no unique_id
    binary = {f"binary_sensor.{slugify(b.get('name'))}": b
              for b in doc["template"][1]["binary_sensor"]}

    if not mapping:
        for key in doc["input_text"]:
            data[f"input_text.{key}"] = ""

    def apply(entity_id: str, spec: dict) -> None:
        available = True
        if "availability" in spec:
            available = render(spec["availability"], data) == "True"
        if not available:
            data[entity_id] = "unavailable"
            notes.append(f"{entity_id}: unavailable")
        else:
            data[entity_id] = render(spec["state"], data)
        for attr, tpl in (spec.get("attributes") or {}).items():
            value = render(tpl, data)
            # HA keeps the rendered type for a `attributes:` template that is a
            # whole template rendering a list/dict (sensor.ems_map_status does)
            if value[:1] in "[{(":
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
            data[f"__attr:{entity_id}:{attr}"] = value

    # 1. the mapping mirrors
    for uid in ("ems_solar_power", "ems_battery_soc", "ems_battery_power",
                "ems_battery_voltage", "ems_battery_current"):
        apply(f"sensor.{uid}", sensors[uid])
    # 2. everything derived from them, in the order the package needs it
    for uid in ("ems_map_status", "ems_grid_power", "ems_house_load",
                "ems_inverter_capacity", "ems_battery_charge_power",
                "ems_charge_power_limit", "ems_mode", "ems_limit_target",
                "ems_pv_delivery"):
        apply(f"sensor.{uid}", sensors[uid])
    for entity_id, spec in binary.items():
        apply(entity_id, spec)
    return data, notes


def sunny_day(doc: dict, *, mapping: bool) -> dict:
    """The reference installation at noon: PV 3000 W, battery charging 1200 W."""
    data = dict(vp.BASE)
    data["sun.sun"] = "above_horizon"
    data["__attr:input_datetime.ems_started_at:timestamp"] = vp.REF.timestamp() - 600
    data["__attr:input_datetime.ems_last_apply:timestamp"] = vp.REF.timestamp() - 60
    data, _ = resolve_chain(doc, data, mapping=mapping)
    return data


def card_entities(node, path=""):
    """Every entity a card names explicitly: `entity:`, `state_of_charge:`, ..."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity", "state_of_charge", "entities") and isinstance(value, str):
                yield f"{path}.{key}", value
            yield from card_entities(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str) and ENTITY_RE.fullmatch(value.strip()):
                yield f"{path}[{index}]", value.strip()
            else:
                yield from card_entities(value, f"{path}[{index}]")


def walk_templates(node, path=""):
    """Every string of a card that contains a Jinja template."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_templates(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_templates(value, f"{path}[{index}]")
    elif isinstance(node, str) and ("{{" in node or "{%" in node):
        yield path, node


def check_dashboard(name: str, dashboard: dict, created: set[str], data: dict,
                    *, mapping: bool) -> None:
    scenario = "mapping filled" if mapping else "mapping empty"
    templates = list(walk_templates(dashboard))
    print(f"  {name} [{scenario}]: {len(templates)} templates")

    # --- every entity a card names must exist -----------------------------
    if mapping:
        missing = sorted({e for _, e in card_entities(dashboard)
                          if e not in created and e not in INTEGRATION_ENTITIES
                          and not e.startswith("sun.")})
        if missing:
            fails.append((f"{name} [{scenario}] card entities",
                          [f"not created by the package: {missing}"]))
            print(f"    !! not created by the package: {missing}")

    for where, template in templates:
        try:
            out = render(template, data)
        except Exception as exc:  # noqa: BLE001 - the card would show nothing
            fails.append((f"{name} [{scenario}] {where}", [f"render error: {exc}"]))
            print(f"    !! render error {where}: {exc}")
            continue

        # entity ids INSIDE the template - the hook-up the literal check misses
        for entity_id in sorted(set(QUOTED_RE.findall(template))):
            if entity_id not in created:
                fails.append((f"{name} [{scenario}] {where}",
                              [f"template reads {entity_id}, which the package "
                               f"does not create"]))
                print(f"    !! template reads {entity_id} (not created)")
        if "None" in out:
            fails.append((f"{name} [{scenario}] {where}",
                          [f"renders 'None': {out.strip()!r}"]))
            print(f"    !! renders 'None' at {where}: {out.strip()!r}")
        if not out:
            fails.append((f"{name} [{scenario}] {where}", ["renders empty"]))
            print(f"    !! renders empty at {where}")
        elif mapping and out.strip().lower().split()[0] in ("unknown", "unavailable"):
            fails.append((f"{name} [{scenario}] {where}",
                          [f"renders {out.strip()!r} although the mapping is filled"]))
            print(f"    !! renders {out.strip()!r} at {where}")


def main() -> int:
    package = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PACKAGE
    doc = yaml.safe_load(package.read_text(encoding="utf-8"))
    created = created_entities(doc)
    print(f"== package ==")
    print(f"  {package.name}: {len(created)} entities")
    for group in ("input_text", "sensor", "binary_sensor"):
        names = sorted(e for e in created if e.startswith(f"{group}."))
        if group == "input_text":
            print(f"  mapping helpers: {len(names)}")
        elif group == "sensor":
            print(f"  template sensors: {len(names)}")

    dashboards = sorted(DASHBOARDS.glob("*.yaml"))
    for mapping in (True, False):
        data = sunny_day(doc, mapping=mapping)
        if mapping:
            print("\n== rendered chain (mapping filled) ==")
            for entity_id in ("sensor.ems_mode", "sensor.ems_solar_power",
                              "sensor.ems_battery_power", "sensor.ems_limit_target",
                              "sensor.ems_grid_power", "sensor.ems_house_load",
                              "sensor.ems_battery_charge_power",
                              "sensor.ems_charge_power_limit",
                              "sensor.ems_inverter_capacity", "sensor.ems_pv_delivery",
                              "sensor.ems_map_status", "binary_sensor.ems_degraded"):
                print(f"  {entity_id:<38}{data.get(entity_id)}")
            print(f"  attributes: "
                  f"{len([k for k in data if k.startswith('__attr:')])}")
            # the whole point of the mapping: the dashboards must have data
            for entity_id, expect in (("sensor.ems_solar_power", "3000.0"),
                                      ("sensor.ems_battery_soc", "85.0"),
                                      ("sensor.ems_battery_power", "1200.0"),
                                      ("sensor.ems_limit_target", None)):
                got = str(data.get(entity_id))
                if expect is not None and got != expect:
                    fails.append((f"chain[{entity_id}]", [f"{got} != {expect}"]))
                if got.lower() in BROKEN:
                    fails.append((f"chain[{entity_id}]", [f"no data: {got!r}"]))
        else:
            # regression guard: a `set` inside a Jinja for-loop does not survive
            # the loop, which made sensor.ems_map_status read "ok" with an empty
            # mapping - and then the warning card never appears on a board whose
            # cards are all empty. That is the state right after an update.
            map_state = str(data.get("sensor.ems_map_status"))
            print(f"\n== empty mapping ==")
            print(f"  sensor.ems_map_status: {map_state!r}")
            if map_state.startswith("ok"):
                fails.append(("chain[sensor.ems_map_status]",
                              ["reads 'ok' although every mapping entry is empty"]))
            for entity_id in ("sensor.ems_solar_power", "sensor.ems_battery_soc",
                              "sensor.ems_battery_power"):
                if str(data.get(entity_id)).lower() not in ("unavailable", "unknown"):
                    fails.append((f"chain[{entity_id}]",
                                  [f"{data.get(entity_id)!r} although the mapping "
                                   f"is empty - a stale value would be worse than "
                                   f"no value"]))
        print(f"\n== dashboards ({'mapping filled' if mapping else 'mapping empty'}) ==")
        for dashboard in dashboards:
            check_dashboard(dashboard.name,
                            yaml.safe_load(dashboard.read_text(encoding="utf-8")),
                            created, data, mapping=mapping)

    print("\n== result ==")
    if fails:
        for name, why in fails:
            print(f"  FAIL {name}: {'; '.join(why)}")
        print(f"\n{len(fails)} FAILURES")
        return 1
    print("  all dashboards render with data (and survive an empty mapping)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
