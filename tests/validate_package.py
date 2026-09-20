#!/usr/bin/env python3
"""Static + behavioural validation of the OpenDTU EMS Home Assistant package.

Usage:
    python tests/validate_package.py [path/to/opendtu_ems.yaml]

What it does
------------
1. parses the YAML and checks that the expected sections exist
2. parses every Jinja template in the file (syntax errors, HA filters included)
3. checks that the inverters written by script.ems_apply match the capacity map
4. renders the whole sensor chain for the documented scenarios and asserts the
   expected mode, grid source, capacity, target percentage and write decision

The scenario data mirrors the reference installation (entity IDs and tuning
values of the shipped default configuration). When you change section 1 of the
package, update the constants below in the same way.
"""
from __future__ import annotations

import ast
import datetime as dt
import re
import sys
from pathlib import Path

import yaml
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import Namespace

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE = ROOT / "packages" / "opendtu_ems.yaml"

TOLERANCE = 0.15
REF = dt.datetime(2026, 9, 19, 12, 0, 0, tzinfo=dt.timezone.utc)
MISSING = {"unknown", "unavailable", "none", ""}

S = "sensor.shelly3mpro_total_active_power"
V = "sensor.smart_meter_electric_consumption_w"
I1 = "number.hm1500_limit_nonpersistent_relative"
I2 = "number.hms1600_a_limit_nonpersistent_relative"
I3 = "number.hms1600_b_limit_nonpersistent_relative"


class StateObj:
    """Minimal stand-in for a Home Assistant State object."""

    def __init__(self, value: str, age_s: int = 5) -> None:
        self.state = value
        self.last_updated = REF - dt.timedelta(seconds=age_s)
        self.last_changed = self.last_updated
        self.attributes: dict = {}

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return str(self.state)


class _Domain:
    """states.input_number.x -> StateObj (attribute and item access)."""

    def __init__(self, data: dict, domain: str) -> None:
        self._data = data
        self._domain = domain

    def _obj(self, item: str) -> StateObj:
        entity_id = f"{self._domain}.{item}"
        return StateObj(self._data.get(entity_id, "unknown"),
                        self._data.get(f"__age:{entity_id}", 5))

    def __getattr__(self, item: str) -> StateObj:
        if item.startswith("_"):
            raise AttributeError(item)
        return self._obj(item)

    def __getitem__(self, item: str) -> StateObj:
        return self._obj(item)


class States:
    """states('x') and states.domain.object_id.last_changed, like Home Assistant."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def __call__(self, entity_id: str):
        return self._data.get(entity_id, "unknown")

    def __getitem__(self, entity_id: str) -> StateObj:
        return StateObj(self._data.get(entity_id, "unknown"),
                        self._data.get(f"__age:{entity_id}", 5))

    def __getattr__(self, name: str) -> _Domain:
        # jinja2 probes these two to decide whether an object is callable
        if name.startswith("_") or name in ("unsafe_callable", "alters_data"):
            raise AttributeError(name)
        return _Domain(self._data, name)


def make_env(data: dict, extra: dict | None = None):
    """Build a sandboxed Jinja environment with the Home Assistant functions."""
    env = ImmutableSandboxedEnvironment()

    def has_value(entity_id):
        return str(data.get(entity_id, "unknown")).lower() not in MISSING

    def state_attr(entity_id, attr):
        generic = data.get(f"__attr:{entity_id}:{attr}", "__miss__")
        if generic != "__miss__":
            return generic
        if entity_id == "input_datetime.ems_last_apply":
            return data.get("__last_apply", REF.timestamp() - 60)
        if entity_id == "sensor.ems_grid_power" and attr == "source":
            return data.get("__grid_source")
        if entity_id == "sensor.ems_inverter_capacity":
            if attr == "active":
                return data.get("__cap_active")
            if attr == "current_pct":
                return data.get("__cap_current")
        return None

    def expand(ids):
        if isinstance(ids, str):
            ids = [i.strip() for i in ids.split(",")]
        return [StateObj(data.get(i, "unknown"), data.get(f"__age:{i}", 5))
                for i in ids]

    env.globals.update(
        states=States(data),
        has_value=has_value,
        is_state=lambda e, c: str(data.get(e, "unknown")) == c,
        state_attr=state_attr,
        expand=expand,
        now=lambda: REF,
        namespace=Namespace,
        last_ts=data.get("__last_apply", REF.timestamp() - 60),
        timeout=300,
    )
    if extra:
        env.globals.update(extra)
    env.filters["timestamp_local"] = lambda ts: dt.datetime.fromtimestamp(
        float(ts), dt.timezone.utc).strftime("%H:%M:%S")
    env.tests["has_value"] = lambda v: str(getattr(v, "state", v)).lower() not in MISSING
    return env


def walk_strings(node, path=""):
    """Yield every string in the document with a readable path."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_strings(value, f"{path}[{index}]")


BASE = {
    S: "-234", V: "-240",
    "sensor.solarleistung_gesamt": "3000",
    "sensor.serialbattery_seplos_ladestand": "85",
    "sensor.serialbattery_seplos_leistung": "1200",
    "input_boolean.ems_enabled": "on",
    "input_boolean.ems_simulate_battery_loss": "off",
    "input_boolean.ems_verbose": "off",
    "input_number.ems_manual_pct": "-1",
    "input_number.ems_grid_bias": "20",
    "input_number.ems_hysteresis_pct": "2",
    "input_number.ems_max_charge_power": "2500",
    "input_number.ems_soc_stop": "100",
    "input_number.ems_charge_allowance": "2500",
    "input_number.ems_export_tolerance": "150",
    "input_number.ems_export_grace": "60",
    "input_number.ems_export_ticks": "0",
    "input_number.ems_reprobe_seconds": "900",
    "input_number.ems_failsafe_pct": "0",
    "input_number.ems_meter_tolerance": "100",
    "input_number.ems_delivery_short": "0",
    "input_number.ems_settle_seconds": "0",   # logic tests act immediately
    "input_number.ems_max_step_pct": "100",   # slew disabled in logic tests
    I1: "50.0", I2: "50.0", I3: "50.0",      # inverters start at 50 %
}

# name: (data, mode, meter source, grid, capacity, active, target %, write?)
# target % is "house load + allowed charge power + bias" scaled to the reachable
# capacity - the battery-first law: solar + grid + (allowance - battery) + bias.
CONTROL_CASES = {
    "normal": (dict(BASE), "FULL", "shelly", -234, 4700, 3, 86.9, True),
    # the array exports, but the battery still has 1300 W of headroom: the
    # offer must NOT be cut (that was the 1.4.x bug)
    "battery-first, exporting 1200 W": ({**BASE, S: "-1200", V: "-1200",
                                         "sensor.solarleistung_gesamt": "4500"},
                                        "FULL", "shelly", -1200, 4700, 3, 98.3, True),
    # battery at its allowance: the surplus is curtailed (load + charge + bias)
    "battery at allowance, curtailing": ({**BASE, S: "-1600", V: "-1600",
                                          "sensor.solarleistung_gesamt": "4600",
                                          "sensor.serialbattery_seplos_leistung": "2500"},
                                         "FULL", "shelly", -1600, 4700, 3, 64.3, True),
    # the learned acceptance caps the offer
    "charge allowance 800 W": ({**BASE, S: "-400", V: "-400",
                                "sensor.solarleistung_gesamt": "1000",
                                "sensor.serialbattery_seplos_leistung": "0",
                                "input_number.ems_charge_allowance": "800"},
                               "FULL", "shelly", -400, 4700, 3, 30.2, True),
    # discharging: the offer also covers what the battery is giving up
    "battery discharging 800 W": ({**BASE, S: "300", V: "300",
                                   "sensor.solarleistung_gesamt": "500",
                                   "sensor.serialbattery_seplos_leistung": "-800"},
                                  "FULL", "shelly", 300, 4700, 3, 87.7, True),
    # SoC stop: only honoured while the battery is measurably idle
    "SoC stop, battery idle": ({**BASE, S: "-1000", V: "-1000",
                                "sensor.solarleistung_gesamt": "3500",
                                "sensor.serialbattery_seplos_leistung": "0",
                                "sensor.serialbattery_seplos_ladestand": "100"},
                               "FULL", "shelly", -1000, 4700, 3, 53.6, True),
    "SoC stop ignored while charging": ({**BASE, S: "-1000", V: "-1000",
                                         "sensor.solarleistung_gesamt": "3500",
                                         "sensor.serialbattery_seplos_leistung": "800",
                                         "sensor.serialbattery_seplos_ladestand": "100"},
                                        "FULL", "shelly", -1000, 4700, 3, 89.8, True),
    "primary meter DEAD": ({**BASE, S: "unavailable"},
                           "FULL", "victron", -240, 4700, 3, 86.8, True),
    "primary meter FROZEN": ({**BASE, f"__age:{S}": 600},
                             "FULL", "victron", -240, 4700, 3, 86.8, True),
    "backup importing 500 W": ({**BASE, S: "unavailable", V: "500"},
                               "FULL", "victron", 500, 4700, 3, 100.0, True),
    "meters disagree (export)": ({**BASE, V: "500"},
                                 "FULL", "disagree", -234, 4700, 3, 86.9, True),
    "meters disagree (import)": ({**BASE, S: "100", V: "900"},
                                 "FULL", "disagree", 100, 4700, 3, 94.0, True),
    "both meters DEAD": ({**BASE, S: "unavailable", V: "unavailable"},
                         "GRID_BLIND", "none", None, 4700, 3, 0.0, True),
    "both meters FROZEN": ({**BASE, f"__age:{S}": 600, f"__age:{V}": 600},
                           "GRID_BLIND", "none", None, 4700, 3, 0.0, True),
    "battery data lost": ({**BASE, "sensor.serialbattery_seplos_leistung": "unknown"},
                          "NO_BATTERY", "shelly", -234, 4700, 3, 59.3, True),
    "manual 50 %": ({**BASE, "input_number.ems_manual_pct": "50"},
                    "FULL", "shelly", -234, 4700, 3, 50.0, True),
    "kill switch off": ({**BASE, "input_boolean.ems_enabled": "off"},
                        "OFF", "shelly", -234, 4700, 3, 0.0, None),
    # redistribution: one inverter off
    "2 of 3 active (grid 0)": ({**BASE, I3: "unavailable", S: "0", V: "0"},
                               "FULL", "shelly", 0, 3100, 2, 100.0, True),
    "2 of 3 active (import 300)": ({**BASE, I3: "unavailable", S: "300", V: "300"},
                                   "FULL", "shelly", 300, 3100, 2, 100.0, True),
    # OpenDTU off / unreachable: nothing can be written at all
    "DTU off (no inverter readable)": ({**BASE, I1: "unavailable", I2: "unavailable",
                                         I3: "unavailable"},
                                        "DTU_BLIND", "shelly", -234, 0, 0, 0.0, False),
    "DTU off + solar dead": ({**BASE, I1: "unavailable", I2: "unavailable",
                               I3: "unavailable",
                               "sensor.solarleistung_gesamt": "unavailable"},
                              "DTU_BLIND", "shelly", -234, 0, 0, 0.0, False),
    "solar dead, inverters ok": ({**BASE, "sensor.solarleistung_gesamt": "unavailable"},
                                  "GRID_BLIND", "shelly", -234, 4700, 3, 0.0, True),
    # night and startup: standby, inverters asleep, nothing to write
    "night (inverters asleep)": ({**BASE, "sun.sun": "below_horizon",
                                 "sensor.solarleistung_gesamt": "0",
                                 I1: "unavailable", I2: "unavailable",
                                 I3: "unavailable"},
                                "NIGHT", "shelly", -234, 0, 0, 0.0, False),
    "night (inverters reachable)": ({**BASE, "sun.sun": "below_horizon",
                                     "sensor.solarleistung_gesamt": "0"},
                                    "NIGHT", "shelly", -234, 4700, 3, 0.0, False),
    "start grace active": ({**BASE,
                            "__attr:input_datetime.ems_started_at:timestamp":
                                REF.timestamp() - 30},
                           "STARTING", "shelly", -234, 4700, 3, 59.3, False),
    "start grace elapsed": ({**BASE,
                             "__attr:input_datetime.ems_started_at:timestamp":
                                 REF.timestamp() - 600},
                            "FULL", "shelly", -234, 4700, 3, 86.9, True),
    # Victron ramp: slew limit and settle time
    "slew: rise is limited": ({**BASE, "input_number.ems_max_step_pct": "10",
                               I1: "86.9", I2: "86.9", I3: "86.9", S: "500", V: "500"},
                              "FULL", "shelly", 500, 4700, 3, 96.9, True),
    "slew: cut is immediate": ({**BASE, "input_number.ems_max_step_pct": "10",
                                I1: "100", I2: "100", I3: "100", S: "-900", V: "-900"},
                               "FULL", "shelly", -900, 4700, 3, 72.8, True),
    "settle: too soon (no write)": ({**BASE, "input_number.ems_settle_seconds": "12",
                                     "__last_apply": REF.timestamp() - 3},
                                    "FULL", "shelly", -234, 4700, 3, 86.9, False),
    "settle: export bypasses": ({**BASE, "input_number.ems_settle_seconds": "12",
                                 "__last_apply": REF.timestamp() - 3, S: "-900", V: "-900"},
                                "FULL", "shelly", -900, 4700, 3, 72.8, True),
}

# name: (data, delivery %, under-delivery notification, expected output W)
DELIVERY_CASES = {
    "delivery ok": (dict(BASE), 73, False, 4084),
    "one inverter dead": ({**BASE, S: "500", V: "500",
                           "sensor.solarleistung_gesamt": "800"}, 31, True, 2618),
    "cloudy, big gap": ({**BASE, S: "500", V: "500",
                         "sensor.solarleistung_gesamt": "2400"}, 57, True, 4221),
    "night": ({**BASE, S: "300", V: "300", "sensor.solarleistung_gesamt": "0",
               "sensor.serialbattery_seplos_leistung": "-100"}, 0, False, 2919),
    "low sun": ({**BASE, S: "500", V: "500",
                 "sensor.solarleistung_gesamt": "150"}, 8, False, 1969),
    "manual 5 % (expected < 300 W)": ({**BASE, "input_number.ems_manual_pct": "5"},
                                      100, False, 235),
}

COUNTER_CASES = {"0": "1", "2": "3", "9": "9"}
NOTIFY_CASES = {"0": False, "2": False, "3": True, "4": False}


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PACKAGE
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fails: list[tuple[str, list[str]]] = []

    print(f"package: {path}")

    # --- 1. structure -----------------------------------------------------
    print("\n== structure ==")
    for section in ("input_boolean", "input_number", "input_datetime",
                    "template", "script", "automation"):
        if section not in doc:
            fails.append((f"section {section}", ["missing"]))
    for key, value in doc.items():
        print(f"  {key:<16} {type(value).__name__:<6} "
              f"n={len(value) if hasattr(value, '__len__') else '-'}")
    # every top level key must be a config domain. If one is not, the file was
    # loaded as the packages mapping itself (packages: !include <this file>),
    # which Home Assistant reports as
    # "Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found."
    known_domains = {"input_boolean", "input_number", "input_datetime", "input_text",
                     "input_select", "template", "script", "automation", "sensor",
                     "binary_sensor", "switch", "light", "cover", "scene", "group",
                     "timer", "counter", "homeassistant"}
    unknown = [key for key in doc if key not in known_domains]
    if unknown:
        fails.append(("top level keys are not config domains",
                      [f"{unknown}: is 'packages:' pointing at this file instead of "
                       "at a directory ('!include_dir_named packages')?"]))

    # YAML automations derive their entity id from the slugified ALIAS, not from
    # their "id:" key. Every automation.<x> reference in the package and the docs
    # must therefore match a slug of one of the configured aliases.
    def slugify(text):
        return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")

    expected_automations = {f"automation.{slugify(a.get('alias'))}"
                            for a in doc.get("automation", [])}
    print(f"  automation entity ids: {', '.join(sorted(expected_automations))}")
    also = {Path(ROOT / name) for name in ("README.md", "CHANGELOG.md")}
    also |= set(ROOT.glob("docs/*.md"))
    referenced_automations: set[str] = set()
    for source in [path, *sorted(also)]:
        if Path(source).exists():
            referenced_automations |= set(
                re.findall(r"automation\.[a-z0-9_]+", Path(source).read_text(encoding="utf-8")))
    wrong_ids = sorted(referenced_automations - expected_automations)
    if wrong_ids:
        fails.append(("automation entity ids",
                      [f"{wrong_ids} - the entity id is the slug of the alias, "
                       f"not the 'id:' key"]))
    print(f"  automation ids referenced in docs: "
          f"{', '.join(sorted(referenced_automations)) or '-'}")

    # --- 1c. dashboard references ----------------------------------------
    dashboard = ROOT / "dashboards" / "ems-overview.yaml"
    if dashboard.exists():
        raw_dashboard = dashboard.read_text(encoding="utf-8")
        cards = set(re.findall(r"\btype:\s*(custom:[a-z0-9-]+)", raw_dashboard))
        allowed_cards = {"custom:power-flow-card-plus", "custom:mushroom-chips-card",
                         "custom:apexcharts-card", "custom:mini-graph-card"}
        unknown_cards = sorted(cards - allowed_cards)
        if unknown_cards:
            fails.append(("dashboard cards", [f"undocumented: {unknown_cards}"]))
        created_entities = set()
        for domain in ("input_boolean", "input_number", "input_datetime"):
            created_entities |= {f"{domain}.{key}" for key in doc.get(domain, {})}
        created_entities |= {f"script.{key}" for key in doc.get("script", {})}
        created_entities |= expected_automations
        for block in doc["template"]:
            for domain, entities in block.items():
                created_entities |= {f"{domain}.{slugify(e.get('name'))}" for e in entities}
        dash = yaml.safe_load(raw_dashboard)
        referenced: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str) and re.fullmatch(
                    r"(?:sensor|binary_sensor|input_boolean|input_number|input_datetime"
                    r"|script|automation)\.[a-z0-9_]+", node.strip()):
                referenced.add(node.strip())

        walk(dash)
        ems_scope = ("sensor.ems_", "binary_sensor.ems_", "input_", "script.ems",
                     "automation.opendtu")
        dangling = sorted(e for e in referenced
                          if e.startswith(ems_scope) and e not in created_entities)
        if dangling:
            fails.append(("dashboard entities", [f"not created by the package: {dangling}"]))
        external = sorted(referenced - created_entities - set(dangling))
        print(f"  dashboard: {len(cards)} custom card types, "
              f"{len(referenced)} entity references")
        print(f"  existing (external) sensors used: {', '.join(external) or '-'}")
    automations = {a["id"]: a for a in doc.get("automation", [])}
    for identifier in ("opendtu_ems_loop", "opendtu_ems_watchdog"):
        if identifier not in automations:
            fails.append((identifier, ["automation missing"]))
    print(f"  automations: {', '.join(automations)}")

    # --- 2. Jinja syntax --------------------------------------------------
    print("\n== jinja syntax ==")
    env = make_env(BASE)
    total = broken = 0
    for where, template in walk_strings(doc):
        if "{{" not in template and "{%" not in template:
            continue
        total += 1
        try:
            env.parse(template)
        except Exception as exc:  # noqa: BLE001
            broken += 1
            fails.append((where, [str(exc)]))
            print(f"  FAIL {where}: {exc}")
    print(f"  {total} templates parsed, {broken} broken")

    # --- 3. consistency: written inverters == capacity map ----------------
    print("\n== consistency ==")
    written = {action["target"]["entity_id"]
               for action in doc["script"]["ems_apply"]["sequence"][1]["parallel"]}
    cap_sensor = next(s for s in doc["template"][0]["sensor"]
                      if s["unique_id"] == "ems_inverter_capacity")
    mapped = set(re.findall(r"'number\.[a-z0-9_]+'", cap_sensor["state"]))
    mapped = {m.strip("'") for m in mapped}
    print(f"  written by script : {sorted(written)}")
    print(f"  capacity map      : {sorted(mapped)}")
    if written != mapped:
        fails.append(("capacity map", sorted(written ^ mapped)))
        print("  !! the script and the capacity map disagree")

    # --- 4. behaviour -----------------------------------------------------
    sensors = {s["unique_id"]: s for s in doc["template"][0]["sensor"]}
    bsens = {b["unique_id"]: b for b in doc["template"][1]["binary_sensor"]}
    grid, delivery = sensors["ems_grid_power"], sensors["ems_pv_delivery"]
    loop = automations["opendtu_ems_loop"]
    watch = automations["opendtu_ems_watchdog"]

    def loop_templates(predicate, node=None):
        """Every template in the loop's actions that matches the predicate."""
        found = []

        def walk(item):
            if isinstance(item, dict):
                for value in item.values():
                    if isinstance(value, str) and ("{{" in value or "{%" in value):
                        if predicate(value):
                            found.append(value)
                    else:
                        walk(value)
            elif isinstance(item, list):
                for value in item:
                    walk(value)

        walk(loop["actions"] if node is None else node)
        return found

    def loop_actions(kind):
        """All actions of a given service in the loop's actions."""
        found = []

        def walk(item):
            if isinstance(item, dict):
                if item.get("action") == kind:
                    found.append(item)
                for value in item.values():
                    walk(value)
            elif isinstance(item, list):
                for value in item:
                    walk(value)

        walk(loop["actions"])
        return found

    # 1.5.0 moved the write gate out of the conditions into the actions (the
    # learning has to run even when nothing is written), and added a night stop
    write_cond = loop_templates(lambda t: "ems_settle_seconds" in t)[0]
    night_cond = loop_templates(lambda t: "== 'NIGHT'" in t)[0]
    lrn_vars = next(action["variables"] for action in loop["actions"]
                    if isinstance(action, dict) and "variables" in action
                    and "lrn_ok" in action["variables"])
    lrn_tick = loop_templates(lambda t: "lrn_exporting" in t and "lrn_ok" in t)[0]
    lrn_trim = loop_templates(lambda t: "lrn_needed" in t)[0]
    lrn_new_tpl = loop_templates(lambda t: "lrn_allow / 2" in t)[0]
    lrn_reset = loop_templates(lambda t: "lrn_bat < -1 * lrn_tol" in t)[0]
    lrn_probe = loop_templates(lambda t: "lrn_quiet" in t)[0]

    def set_value(substring):
        return next(str(action["data"]["value"])
                    for action in loop_actions("input_number.set_value")
                    if substring in str(action["data"]["value"]))

    lrn_tick_out = set_value("lrn_ticks + 1")          # tick increment
    lrn_new_out = set_value("lrn_new")                 # trim
    lrn_reset_out = set_value("lrn_cmax | round")       # discharge reset
    lrn_probe_out = set_value("1.5")                   # upward probe
    dtu_cond = next(c["value_template"] for c in loop["conditions"]
                    if "DTU_BLIND" in str(c.get("value_template", "")))
    ifs = [a["if"][0]["value_template"] for a in watch["actions"]
           if isinstance(a.get("if"), list)]
    capacity_tpl = next(t for t in ifs if "99.5" in t)
    short_tpl = next(t for t in ifs if "ems_pv_delivery" in t)
    notify_tpl = next(t for t in ifs if "== 3" in t)
    dtu_tpl = next(t for t in ifs if "DTU_BLIND" in t)
    incr_tpl = next(a["then"][0]["data"]["value"] for a in watch["actions"]
                    if isinstance(a.get("if"), list)
                    and "ems_pv_delivery" in str(a["if"][0].get("value_template", "")))

    def render(expr, data):
        # "__var:<name>" entries stand in for automation variables, which Home
        # Assistant makes available to every template of the same script run
        env = make_env(data)
        env.globals.update({key[6:]: value for key, value in data.items()
                            if key.startswith("__var:")})
        return env.from_string(expr).render().strip()

    def chain(data):
        grid_ok = render(grid["availability"], data) == "True"
        grid_value = render(grid["state"], data) if grid_ok else "unavailable"
        source = render(grid["attributes"]["source"], data)
        d1 = {**data, "sensor.ems_grid_power": grid_value, "__grid_source": source}
        capacity = render(cap_sensor["state"], d1)
        active = render(cap_sensor["attributes"]["active"], d1)
        current = render(cap_sensor["attributes"]["current_pct"], d1)
        d2 = {**d1, "sensor.ems_inverter_capacity": capacity,
              "__cap_active": active, "__cap_current": current}
        mode = render(sensors["ems_mode"]["state"], d2)
        d3 = {**d2, "sensor.ems_mode": mode}
        target = render(sensors["ems_limit_target"]["state"], d3)
        # the loop snapshots the target into the automation variable target_pct
        # before it touches the charge allowance, and uses that everywhere
        d4 = {**d3, "sensor.ems_limit_target": target, "__var:target_pct": target}
        expected = render(delivery["attributes"]["expected_w"], d4)
        d5 = {**d4, "__attr:sensor.ems_pv_delivery:expected_w": expected}
        delivered = render(delivery["state"], d5)
        d6 = {**d5, "sensor.ems_pv_delivery": delivered}
        return dict(grid=grid_value, source=source, capacity=capacity,
                    active=active, current=current, mode=mode, target=target,
                    expected=expected, delivered=delivered,
                    write=render(write_cond, d6),
                    night=render(night_cond, d6),
                    mode_ok=render(dtu_cond, d6),
                    dtu_skip=render(dtu_cond, d6),
                    dtu_alert=render(dtu_tpl, d6),
                    degraded=render(bsens["ems_degraded"]["state"], d6),
                    capacity_alert=render(capacity_tpl, d6),
                    delivery_alert=render(short_tpl, d6))

    print("\n== control scenarios ==")
    for name, (data, mode, source, grid_w, cap, active, target, write) in CONTROL_CASES.items():
        got = chain(data)
        why = []
        if got["mode"] != mode:
            why.append(f"mode={got['mode']}")
        if got["source"] != source:
            why.append(f"source={got['source']}")
        if grid_w is not None and str(got["grid"]) != str(grid_w):
            why.append(f"grid={got['grid']}")
        if got["capacity"] != str(cap) or got["active"] != str(active):
            why.append(f"capacity={got['capacity']}/active={got['active']}")
        if abs(float(got["target"]) - target) > TOLERANCE:
            why.append(f"target={got['target']}")
        if write is not None:
            # the loop only writes when the gate AND the mode condition pass and
            # the run has not stopped at the night standby check
            effective = (got["write"] == "True" and got["mode_ok"] == "True"
                         and got["night"] != "True")
            if effective != bool(write):
                why.append(f"write={effective}")
        if why:
            fails.append((name, why))
        print(f"  {'OK ' if not why else '!! '}{name:<30}{got['mode']:>11}"
              f"{got['target']:>7}%   {'; '.join(why)}")

    print("\n== charge allowance learning (control loop) ==")
    IMPORTING = {**BASE, S: "500", V: "500"}
    EXPORTING = {**BASE, S: "-600", V: "-600"}
    QUIET = {**BASE, S: "500", V: "500",
             "__age:input_number.ems_charge_allowance": 1200}

    def lrn_input(data):
        """Resolve what the sensor chain would give the loop (grid + mode),
        unless the case sets it explicitly."""
        got = chain(data)
        out = dict(data)
        out.setdefault("sensor.ems_grid_power", got["grid"])
        out.setdefault("sensor.ems_mode", got["mode"])
        return out

    def lrn_env(data):
        """Render the loop's variable block, then the templates that use it."""
        values = {}
        for key, tpl in lrn_vars.items():
            raw = make_env(data).from_string(tpl).render().strip()
            try:
                values[key] = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                values[key] = raw
        return make_env(data, values), values

    def learned(name, got, want):
        try:
            ok = abs(float(got) - float(want)) < 1e-6
        except (TypeError, ValueError):
            ok = str(got) == str(want)
        if not ok:
            fails.append((f"learning: {name}", [f"got {got!r}, want {want!r}"]))
            print(f"  !! {name:<46}{got}   (want {want})")
        else:
            print(f"  OK {name:<46}{got}")

    def lrn_cond(name, data, tpl, want):
        env, _ = lrn_env(lrn_input(data))
        learned(name, env.from_string(tpl).render().strip(), want)

    def lrn_value(name, data, tpl, want):
        env, _ = lrn_env(lrn_input(data))
        got = env.from_string(tpl).render().strip()
        try:
            got = ast.literal_eval(got)
        except (ValueError, SyntaxError):
            pass
        learned(name, got, want)

    # "EMS export grace" seconds are counted in 15 s ticks (loop heartbeat)
    for grace, ticks in (("0", 1), ("30", 2), ("60", 4), ("90", 6), ("600", 40)):
        _, vals = lrn_env(lrn_input({**BASE, "input_number.ems_export_grace": grace}))
        learned(f"grace {grace} s -> {ticks} tick(s)", vals["lrn_needed"], ticks)

    lrn_value("tick up while exporting", EXPORTING, lrn_tick_out, 1)
    lrn_value("ticks continue while exporting",
              {**EXPORTING, "input_number.ems_export_ticks": "3"}, lrn_tick_out, 4)
    lrn_value("ticks capped at 99", {**EXPORTING, "input_number.ems_export_ticks": "99"},
              lrn_tick_out, 99)
    lrn_cond("tick branch off while importing", IMPORTING, lrn_tick, "False")
    lrn_cond("tick branch off when nothing is written",
             {**EXPORTING, "sensor.ems_mode": "NIGHT", "input_number.ems_export_ticks": "3"},
             lrn_tick, "False")
    lrn_cond("tick branch off on manual override",
             {**EXPORTING, "input_number.ems_manual_pct": "50"}, lrn_tick, "False")
    lrn_cond("tick branch off when the battery data is gone",
             {**EXPORTING, "sensor.serialbattery_seplos_leistung": "unknown"},
             lrn_tick, "False")

    # the trim criterion: only after the whole grace, and only while the
    # battery takes measurably less than it is offered
    lrn_cond("trim after the grace", {**EXPORTING, "input_number.ems_export_ticks": "3"},
             lrn_trim, "True")
    lrn_cond("no trim before the grace", {**EXPORTING, "input_number.ems_export_ticks": "1"},
             lrn_trim, "False")
    lrn_cond("no trim while the battery takes the offer",
             {**EXPORTING, "input_number.ems_export_ticks": "9",
              "sensor.serialbattery_seplos_leistung": "2450"}, lrn_trim, "False")
    env, _ = lrn_env(lrn_input({**EXPORTING, "input_number.ems_export_ticks": "3",
                                "sensor.serialbattery_seplos_leistung": "300"}))
    learned("trim: at most half, never below what it takes",
            ast.literal_eval(env.from_string(lrn_new_tpl).render().strip()), 1250)
    env, _ = lrn_env(lrn_input({**EXPORTING,
                                "sensor.serialbattery_seplos_leistung": "1500"}))
    learned("trim: uses the measured battery power",
            ast.literal_eval(env.from_string(lrn_new_tpl).render().strip()), 1500)

    # the discharge reset: a new charge cycle gets the full offer back
    lrn_cond("reset while discharging",
             {**IMPORTING, "sensor.serialbattery_seplos_leistung": "-500",
              "input_number.ems_charge_allowance": "800"}, lrn_reset, "True")
    lrn_cond("no reset while exporting",
             {**EXPORTING, "sensor.serialbattery_seplos_leistung": "-500",
              "input_number.ems_charge_allowance": "800"}, lrn_reset, "False")
    lrn_cond("no reset when already at the maximum",
             {**IMPORTING, "sensor.serialbattery_seplos_leistung": "-500"},
             lrn_reset, "False")
    lrn_value("reset value = max charge power",
              {**IMPORTING, "sensor.serialbattery_seplos_leistung": "-500",
               "input_number.ems_charge_allowance": "800"}, lrn_reset_out, 2500)

    # the upward probe: never starve a battery that freed up
    lrn_cond("probe when quiet long enough",
             {**QUIET, "input_number.ems_charge_allowance": "1000",
              "sensor.serialbattery_seplos_leistung": "500"}, lrn_probe, "True")
    lrn_cond("no probe too soon",
             {**BASE, S: "500", V: "500",
              "input_number.ems_charge_allowance": "1000",
              "sensor.serialbattery_seplos_leistung": "500"}, lrn_probe, "False")
    lrn_cond("no probe while discharging",
             {**QUIET, "input_number.ems_charge_allowance": "1000",
              "sensor.serialbattery_seplos_leistung": "-500"}, lrn_probe, "False")
    lrn_cond("no probe at the maximum", dict(QUIET), lrn_probe, "False")
    lrn_value("probe step x1.5",
              {**QUIET, "input_number.ems_charge_allowance": "1000"}, lrn_probe_out, 1500)
    lrn_value("probe capped at max charge power",
              {**QUIET, "input_number.ems_charge_allowance": "2400"}, lrn_probe_out, 2500)

    # standby: the loop still runs at night (that is when the estimate is
    # reset) but writes nothing
    lrn_cond("night stop in NIGHT", {**BASE, "sensor.ems_mode": "NIGHT"},
             night_cond, "True")
    lrn_cond("no night stop in FULL", {**BASE, "sensor.ems_mode": "FULL"},
             night_cond, "False")

    print("\n== house load (sensor.ems_house_load) ==")
    load_tpl = sensors["ems_house_load"]["state"]
    load_avail = sensors["ems_house_load"]["availability"]
    for name, data, expected in (
            ("normal: 3000 - 234 - 1200",
             {**BASE, "sensor.ems_grid_power": "-234"}, 1566),
            ("exporting 900 W",
             {**BASE, "sensor.ems_grid_power": "-900", S: "-900", V: "-900"}, 900),
            ("battery discharging 800 W",
             {**BASE, "sensor.ems_grid_power": "-234",
              "sensor.serialbattery_seplos_leistung": "-800"}, 3566),
            ("battery sensor gone",
             {**BASE, "sensor.ems_grid_power": "-234",
              "sensor.serialbattery_seplos_leistung": "unavailable"}, None)):
        available = render(load_avail, data) == "True"
        got = round(float(render(load_tpl, data))) if available else None
        why = []
        if got != expected:
            why.append(f"load={got} expected={expected}")
        if why:
            fails.append((f"house load {name}", why))
        print(f"  {'OK ' if not why else '!! '}{name:<34}available={available!s:<6}"
              f"load={got}")

    print("\n== delivery check ==")
    for name, (data, ratio, notify, expected_w) in DELIVERY_CASES.items():
        got = chain(data)
        why = []
        if abs(float(got["delivered"]) - ratio) > 0.5:
            why.append(f"delivery={got['delivered']}")
        if int(float(got["expected"])) != expected_w:
            why.append(f"expected={got['expected']}")
        if got["delivery_alert"] != str(notify):
            why.append(f"notify={got['delivery_alert']}")
        if why:
            fails.append((name, why))
        print(f"  {'OK ' if not why else '!! '}{name:<30}{got['delivered']:>6}%"
              f"  expected {got['expected']:>7} W   {'; '.join(why)}")

    print("\n== delivery counter (persistence) ==")
    for current, expected in COUNTER_CASES.items():
        got = render(incr_tpl, {**BASE, "input_number.ems_delivery_short": current})
        if got != expected:
            fails.append((f"counter {current}", [got]))
        print(f"  counter {current} -> {got:<3} (expect {expected})")
    for current, expected in NOTIFY_CASES.items():
        got = render(notify_tpl, {**BASE, "input_number.ems_delivery_short": current})
        if got != str(expected):
            fails.append((f"notify at {current}", [got]))
        print(f"  notify at {current} -> {got:<6} (expect {expected})")

    print("\n== OpenDTU unreachable handling ==")
    for mode, expect_alert, expect_writes in (("DTU_BLIND", True, "False"),
                                              ("FULL", False, "True"),
                                              ("NO_BATTERY", False, "True")):
        data = {**BASE, "sensor.ems_mode": mode}
        alert = render(dtu_tpl, data)
        writes = render(dtu_cond, data)
        why = []
        if alert != str(expect_alert):
            why.append(f"alert={alert}")
        if writes != expect_writes:
            why.append(f"writes={writes}")
        if why:
            fails.append((f"dtu handling {mode}", why))
        print(f"  mode {mode:<11} notify={alert:<6} loop-writes={writes:<6} "
              f"{'OK' if not why else '!! ' + '; '.join(why)}")

    print("\n== standby states (normal, must not alarm or write) ==")
    # OFF is not tested here: it is blocked by the first condition (the master
    # switch) and is covered by the "kill switch off" control scenario.
    for mode in ("STARTING", "NIGHT"):
        data = {**BASE, "sensor.ems_mode": mode,
                "__attr:sensor.ems_grid_power:source": "shelly"}
        mode_ok = render(dtu_cond, data)
        night = render(night_cond, data)
        writes = str(mode_ok == "True" and night != "True")
        degraded = render(bsens["ems_degraded"]["state"], data)
        why = []
        if writes != "False":
            why.append(f"writes={writes}")
        if degraded != "False":
            why.append(f"degraded={degraded}")
        if why:
            fails.append((f"standby {mode}", why))
        print(f"  mode {mode:<10} loop-writes={writes:<6} degraded={degraded:<6} "
              f"{'OK' if not why else '!! ' + '; '.join(why)}")

    # a missing inverter must not be reported as a capacity shortfall
    for active, expect in ((0, False), (2, True)):
        data = {**BASE, "sensor.ems_mode": "FULL",
                "__attr:sensor.ems_inverter_capacity:active": str(active),
                "__attr:sensor.ems_inverter_capacity:current_pct": "100",
                "sensor.ems_grid_power": "400",
                "sensor.solarleistung_gesamt": "3000"}
        got = render(capacity_tpl, data)
        if got != str(expect):
            fails.append((f"capacity alert with {active} active", [got]))
        print(f"  capacity alert with {active} active -> {got:<6}"
              f" (expect {expect})")

    # --- 5. documentation links -------------------------------------------
    print("\n== documentation links ==")
    md_files = [ROOT / "README.md", ROOT / "CHANGELOG.md",
                *sorted((ROOT / "docs").glob("*.md"))]

    def slug(heading: str) -> str:
        """GitHub's heading anchor: lowercase, punctuation dropped, spaces -> '-'."""
        return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))

    anchors = {md.name: {slug(m.group(1)) for m in
                         re.finditer(r"^#{1,6}\s+(.*)$", md.read_text(encoding="utf-8"), re.M)}
               for md in md_files}
    broken, checked = [], 0
    for md in md_files:
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            checked += 1
            path, _, fragment = target.partition("#")
            resolved = (md.parent / path).resolve() if path else md
            if path and not resolved.exists():
                broken.append(f"{md.name} -> {target} (missing file)")
            elif fragment and resolved.name in anchors \
                    and fragment not in anchors[resolved.name]:
                broken.append(f"{md.name} -> {target} (no such heading)")
    if broken:
        fails.append(("documentation links", broken))
    print(f"  {checked} relative links checked, {len(broken)} broken")
    for item in broken:
        print(f"  !! {item}")

    print("\n== result ==")
    if fails:
        for name, why in fails:
            print(f"  FAIL {name}: {'; '.join(why)}")
        print(f"\n{len(fails)} FAILURES")
        return 1
    print(f"  all checks passed ({total} templates, "
          f"{len(CONTROL_CASES)} control + {len(DELIVERY_CASES)} delivery scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
