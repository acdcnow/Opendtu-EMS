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
        self.attributes: dict = {}

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return str(self.state)


def make_env(data: dict):
    """Build a sandboxed Jinja environment with the Home Assistant functions."""
    env = ImmutableSandboxedEnvironment()

    class States:
        def __call__(self, entity_id):
            return data.get(entity_id, "unknown")

        def __getitem__(self, entity_id):
            return StateObj(data.get(entity_id, "unknown"),
                            data.get(f"__age:{entity_id}", 5))

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
        states=States(),
        has_value=has_value,
        is_state=lambda e, c: str(data.get(e, "unknown")) == c,
        state_attr=state_attr,
        expand=expand,
        now=lambda: REF,
        namespace=Namespace,
        last_ts=data.get("__last_apply", REF.timestamp() - 60),
        timeout=300,
    )
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
    "input_number.ems_soc_taper_from": "90",
    "input_number.ems_soc_full": "99",
    "input_number.ems_failsafe_pct": "0",
    "input_number.ems_meter_tolerance": "100",
    "input_number.ems_delivery_short": "0",
    "input_number.ems_settle_seconds": "0",   # logic tests act immediately
    "input_number.ems_max_step_pct": "100",   # slew disabled in logic tests
    I1: "86.9", I2: "86.9", I3: "86.9",
}

# name: (data, mode, meter source, grid, capacity, active, target %, write?)
CONTROL_CASES = {
    "normal": (dict(BASE), "FULL", "shelly", -234, 4700, 3, 59.3, True),
    "primary meter DEAD": ({**BASE, S: "unavailable"},
                           "FULL", "victron", -240, 4700, 3, 59.1, True),
    "primary meter FROZEN": ({**BASE, f"__age:{S}": 600},
                             "FULL", "victron", -240, 4700, 3, 59.1, True),
    "backup importing 500 W": ({**BASE, S: "unavailable", V: "500"},
                               "FULL", "victron", 500, 4700, 3, 100.0, True),
    "meters disagree (export)": ({**BASE, V: "500"},
                                 "FULL", "disagree", -234, 4700, 3, 59.3, True),
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
    # OpenDTU off / unreachable
    "DTU off (no inverter readable)": ({**BASE, I1: "unavailable", I2: "unavailable",
                                         I3: "unavailable"},
                                        "DTU_BLIND", "shelly", -234, 0, 0, 0.0, True),
    "DTU off + solar dead": ({**BASE, I1: "unavailable", I2: "unavailable",
                               I3: "unavailable",
                               "sensor.solarleistung_gesamt": "unavailable"},
                              "DTU_BLIND", "shelly", -234, 0, 0, 0.0, True),
    "solar dead, inverters ok": ({**BASE, "sensor.solarleistung_gesamt": "unavailable"},
                                  "GRID_BLIND", "shelly", -234, 4700, 3, 0.0, True),
    # night and startup: standby, inverters asleep, nothing to control
    "night (inverters asleep)": ({**BASE, "sun.sun": "below_horizon",
                                 "sensor.solarleistung_gesamt": "0",
                                 I1: "unavailable", I2: "unavailable",
                                 I3: "unavailable"},
                                "NIGHT", "shelly", -234, 0, 0, 0.0, True),
    "night (inverters reachable)": ({**BASE, "sun.sun": "below_horizon",
                                     "sensor.solarleistung_gesamt": "0"},
                                    "NIGHT", "shelly", -234, 4700, 3, 0.0, True),
    "start grace active": ({**BASE,
                            "__attr:input_datetime.ems_started_at:timestamp":
                                REF.timestamp() - 30},
                           "STARTING", "shelly", -234, 4700, 3, 59.3, True),
    "start grace elapsed": ({**BASE,
                             "__attr:input_datetime.ems_started_at:timestamp":
                                 REF.timestamp() - 600},
                            "FULL", "shelly", -234, 4700, 3, 59.3, True),
    # Victron ramp: slew limit and settle time
    "slew: rise is limited": ({**BASE, "input_number.ems_max_step_pct": "10",
                               S: "500", V: "500"},
                              "FULL", "shelly", 500, 4700, 3, 96.9, True),
    "slew: cut is immediate": ({**BASE, "input_number.ems_max_step_pct": "10",
                                I1: "100", I2: "100", I3: "100", S: "-900", V: "-900"},
                               "FULL", "shelly", -900, 4700, 3, 45.1, True),
    "settle: too soon (no write)": ({**BASE, "input_number.ems_settle_seconds": "12",
                                     "__last_apply": REF.timestamp() - 3},
                                    "FULL", "shelly", -234, 4700, 3, 59.3, False),
    "settle: export bypasses": ({**BASE, "input_number.ems_settle_seconds": "12",
                                 "__last_apply": REF.timestamp() - 3, S: "-900", V: "-900"},
                                "FULL", "shelly", -900, 4700, 3, 45.1, True),
}

# name: (data, delivery %, under-delivery notification, expected output W)
DELIVERY_CASES = {
    "delivery ok": (dict(BASE), 108, False, 2787),
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
    write_cond = next(c["value_template"] for c in loop["conditions"]
                      if "ems_settle_seconds" in str(c.get("value_template", "")))
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
        return make_env(data).from_string(expr).render().strip()

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
        d4 = {**d3, "sensor.ems_limit_target": target}
        expected = render(delivery["attributes"]["expected_w"], d4)
        d5 = {**d4, "__attr:sensor.ems_pv_delivery:expected_w": expected}
        delivered = render(delivery["state"], d5)
        d6 = {**d5, "sensor.ems_pv_delivery": delivered}
        return dict(grid=grid_value, source=source, capacity=capacity,
                    active=active, current=current, mode=mode, target=target,
                    expected=expected, delivered=delivered,
                    write=render(write_cond, d6),
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
        if write is not None and got["write"] != str(write):
            why.append(f"write={got['write']}")
        if why:
            fails.append((name, why))
        print(f"  {'OK ' if not why else '!! '}{name:<30}{got['mode']:>11}"
              f"{got['target']:>7}%   {'; '.join(why)}")

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
        writes = render(dtu_cond, data)
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
