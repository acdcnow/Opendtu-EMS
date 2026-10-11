#!/usr/bin/env python3
"""10 s-resolution day simulation of the OpenDTU EMS control law.

Usage:
    python tests/simulate_day.py [path/to/opendtu_ems.yaml] [--quiet]

Why this exists
---------------
`validate_package.py` renders the sensor chain for *frozen* scenarios: one set of
sensor values in, one percentage out. That cannot show a *transient* - and the
complaint this harness was written for is exactly a transient:

    "the solar power gets set down even if the battery is not charging to the limit"

The interesting case is the morning ramp: first everything comes from the grid,
then PV grows past the house load and the battery **starts charging - slowly**.
A Victron needs tens of seconds to reach its charge current limit. While it is
still ramping, the array momentarily exports; a controller that reads that
export as "the battery cannot take the power" will cut the array *before* the
battery ever reached its charge limit, and the charge power is then pinned below
the limit it could take.

What the harness does
---------------------
* renders the **real templates** out of the package YAML (mode, capacity,
  limit target, the charge-allowance learning block and the write gate) - not a
  re-implementation, so a change in the package changes the simulation
* steps the whole system at ``DT`` seconds (default 10 s, as requested)
* models grid, PV, house load, a PV-driven ESS whose charge current *ramps*,
  and the battery SoC
* prints a protocol (a table of the day) and asserts the two properties that
  matter:

  1. **no premature curtailment** - while the battery is charging below its
     charge power limit, the array must not be cut below what the sun offers;
  2. **curtailment only at the limit** - once the battery *is* at its limit the
     array is cut to ``house load + charge limit`` and nothing is exported.

Exit code 0 = both properties hold for the whole simulated day.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# reuse the Home-Assistant Jinja stand-ins of the static validator
import validate_package as vp  # noqa: E402

DEFAULT_PACKAGE = ROOT / "packages" / "opendtu_ems.yaml"

# --------------------------------------------------------------------------- #
# simulation constants (reference installation)
# --------------------------------------------------------------------------- #
DAY_START_MIN = 5 * 60          # 05:00
DAY_END_MIN = 21 * 60           # 21:00
DT = 10.0                       # seconds per step - the requested 10 s grid
PV_PEAK = 4200.0                # W the roof could deliver at solar noon
CAP = 4700.0                    # 1500 + 1600 + 1600 W reachable capacity
CMS_MAX = 2500.0                # input_number.ems_max_charge_power default
BAT_KWH = 10.0                  # usable pack energy
ESS_TAU = 60.0                  # Victron charge-current ramp (s) - the crux
INV_TAU = 3.0                   # micro-inverter MPPT lag (s)
SOC0 = 45.0
EXPORT_TOL = 150.0              # marge used by the protocol checks

S = vp.S
V = vp.V
I1, I2, I3 = vp.I1, vp.I2, vp.I3
SOC = "sensor.serialbattery_seplos_ladestand"
BPOW = "sensor.serialbattery_seplos_leistung"
PV = "sensor.solarleistung_gesamt"
VBAT = "sensor.serialbattery_seplos_dc_bus_spannung"
IBAT = "sensor.venus_dc_batterie_stromstarke"


# --------------------------------------------------------------------------- #
# the physical day
# --------------------------------------------------------------------------- #
def pv_potential(minute: float) -> float:
    """Cloudless PV that the roof could produce (W) at a day-minute."""
    sunrise, sunset = 6 * 60.0, 20 * 60.0
    if minute <= sunrise or minute >= sunset:
        return 0.0
    frac = (minute - sunrise) / (sunset - sunrise)
    return max(0.0, PV_PEAK * math.sin(math.pi * frac))


def house_load(minute: float) -> float:
    """House consumption (W): a base load plus a few step loads."""
    load = 330.0
    if 7 * 60 <= minute < 7 * 60 + 25:      # kettle + toaster at breakfast
        load += 900.0
    if 12 * 60 <= minute < 12 * 60 + 30:    # washing machine at noon
        load += 250.0
    if 17 * 60 + 30 <= minute < 18 * 60 + 15:  # cooking in the evening
        load += 700.0
    return load


def battery_voltage(soc: float) -> float:
    """16S LiFePO4 pack voltage as a function of SoC (V)."""
    return 48.0 + 0.064 * soc


def flat_load(minute: float) -> float:
    """A constant house load - used by the cloud-break scenario."""
    return 330.0


def cloud_pv(minute: float) -> float:
    """Thin cloud until 09:00, then the sun breaks through - a step in the
    surplus that the ESS can only follow at its ramp rate."""
    base = pv_potential(minute)
    if minute < 9 * 60:
        return min(base, 700.0)
    return base


# scenario name -> (pv function, load function, ESS ramp time constant)
# ESS_TAU is how fast the ESS reaches its charge current limit after the array
# offers it more power. The package's own notes say "the Victron needs seconds
# to minutes to ramp" and default EMS export grace to 60 s, so 45 s is a fair
# model of a slow-but-plausible ESS/BMS; a faster one only makes the guard's
# job easier.
SCENARIOS = {
    "day": (pv_potential, house_load, 45.0),
    "cloud": (cloud_pv, flat_load, 45.0),
}


# --------------------------------------------------------------------------- #
# the controller under test
# --------------------------------------------------------------------------- #
class Controller:
    """Extracts and renders the EMS templates straight from the package YAML."""

    def __init__(self, package_path: Path) -> None:
        self.doc = yaml.safe_load(package_path.read_text(encoding="utf-8"))
        sensors = {s["unique_id"]: s for s in self.doc["template"][0]["sensor"]}
        automations = {a["id"]: a for a in self.doc["automation"]}
        loop = automations["opendtu_ems_loop"]

        self.grid = sensors["ems_grid_power"]
        self.capacity = sensors["ems_inverter_capacity"]
        self.mode = sensors["ems_mode"]
        self.target = sensors["ems_limit_target"]
        self.delivery = sensors["ems_pv_delivery"]
        self.charge_power = sensors.get("ems_battery_charge_power")
        self.charge_limit = sensors.get("ems_charge_power_limit")

        self.want_charge_sensor = self.charge_power is not None
        self.want_limit_sensor = self.charge_limit is not None

        def walk_strings(node):
            if isinstance(node, str):
                yield node
            elif isinstance(node, dict):
                for value in node.values():
                    yield from walk_strings(value)
            elif isinstance(node, list):
                for value in node:
                    yield from walk_strings(value)

        def find(predicate):
            return [t for t in walk_strings(loop["actions"])
                    if isinstance(t, str) and ("{{" in t or "{%" in t) and predicate(t)]

        def actions(kind):
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

        def set_value(substring):
            return next(str(a["data"]["value"]) for a in actions("input_number.set_value")
                        if substring in str(a["data"]["value"]))

        self.lrn_vars = next(a["variables"] for a in loop["actions"]
                             if isinstance(a, dict) and "variables" in a
                             and "lrn_ok" in a["variables"])
        self.lrn_tick_cond = find(lambda t: "lrn_exporting" in t and "lrn_ok" in t)[0]
        self.lrn_trim_cond = find(lambda t: "lrn_needed" in t)[0]
        self.lrn_new_tpl = find(lambda t: "lrn_allow / 2" in t)[0]
        self.lrn_reset_cond = find(lambda t: "lrn_bat < -1 * lrn_tol" in t)[0]
        self.lrn_probe_cond = find(lambda t: "lrn_quiet" in t)[0]
        self.lrn_tick_out = set_value("lrn_ticks + 1")
        self.lrn_new_out = set_value("lrn_new")
        self.lrn_reset_out = set_value("lrn_cmax | round")
        self.lrn_probe_out = set_value("1.5")
        # 1.9.0 only: the action that remembers this run's battery power
        try:
            self.lrn_prev_out = set_value("lrn_bat")
        except StopIteration:
            self.lrn_prev_out = None
        self.night_cond = find(lambda t: "== 'NIGHT'" in t)[0]
        self.write_cond = find(lambda t: "ems_settle_seconds" in t)[0]
        self.dtu_cond = next(c["value_template"] for c in loop["conditions"]
                             if "DTU_BLIND" in str(c.get("value_template", "")))

        # one environment, one mutable state dict - rendered thousands of times
        self.data = self._blank_state()
        self.env = vp.make_env(self.data, extra={"now": lambda: vp.REF})
        self._cache: dict[str, object] = {}

    # -- state plumbing ---------------------------------------------------- #
    def _blank_state(self) -> dict:
        return {
            "input_boolean.ems_enabled": "on",
            "input_boolean.ems_automatic": "on",
            "input_boolean.ems_simulate_battery_loss": "off",
            "input_boolean.ems_verbose": "off",
            "input_boolean.ems_expert_mode": "off",
            "input_number.ems_manual_pct": "0",
            "input_number.ems_grid_bias": "20",
            "input_number.ems_hysteresis_pct": "2",
            "input_number.ems_max_charge_power": str(int(CMS_MAX)),
            "input_number.ems_max_charge_current": "50",
            "input_number.ems_soc_stop": "100",
            "input_number.ems_charge_allowance": str(int(CMS_MAX)),
            "input_number.ems_bat_prev": "0",
            "input_number.ems_export_tolerance": "150",
            "input_number.ems_export_grace": "60",
            "input_number.ems_export_ticks": "0",
            "input_number.ems_reprobe_seconds": "900",
            "input_number.ems_failsafe_pct": "0",
            "input_number.ems_meter_tolerance": "100",
            "input_number.ems_delivery_short": "0",
            "input_number.ems_settle_seconds": "12",
            "input_number.ems_max_step_pct": "10",
            "input_number.ems_start_grace": "120",
            "sun.sun": "above_horizon",
            I1: "50.0", I2: "50.0", I3: "50.0",
            "__cap_active": "3", "__cap_current": "50.0",
            "__last_apply": vp.REF.timestamp() - 300,
        }

    def render(self, template: str) -> str:
        compiled = self._cache.get(template)
        if compiled is None:
            compiled = self.env.from_string(template)
            self._cache[template] = compiled
        return compiled.render().strip()  # type: ignore[attr-defined]

    def prepared(self, data: dict) -> dict:
        """Render the grid -> capacity -> mode chain and fold it back in."""
        d = data
        grid_ok = self.render(self.grid["availability"]) == "True"
        grid_value = self.render(self.grid["state"]) if grid_ok else "unavailable"
        source = self.render(self.grid["attributes"]["source"])
        d["sensor.ems_grid_power"] = grid_value
        d["__grid_source"] = source
        capacity = self.render(self.capacity["state"])
        active = self.render(self.capacity["attributes"]["active"])
        current = self.render(self.capacity["attributes"]["current_pct"])
        d["sensor.ems_inverter_capacity"] = capacity
        d["__cap_active"], d["__cap_current"] = active, current
        mode = self.render(self.mode["state"])
        d["sensor.ems_mode"] = mode
        if self.want_charge_sensor:
            cp = self.render(self.charge_power["state"])
            d["sensor.ems_battery_charge_power"] = cp
        if self.want_limit_sensor:
            cl = self.render(self.charge_limit["state"])
            d["sensor.ems_charge_power_limit"] = cl
        return d

    # -- one control run --------------------------------------------------- #
    def run(self, data: dict) -> dict:
        """One loop execution. Returns the write decision and diagnostics."""
        d = self.prepared(data)
        target_pct = self.render(self.target["state"])
        d["sensor.ems_limit_target"] = target_pct
        # the loop snapshots the target into an automation variable before it
        # touches the charge allowance; the write gate reads that variable
        self.env.globals["target_pct"] = target_pct

        out = {"target": float(target_pct or 0), "allowance": None, "push": None,
               "written": False, "mode": d["sensor.ems_mode"], "model": ""}

        # learning block - same order as the package
        values = {}
        for key, tpl in self.lrn_vars.items():
            raw = self.render(tpl)
            try:
                values[key] = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                values[key] = raw
        self.env.globals.update(values)
        out["model"] = self._model(values)

        if values.get("lrn_ok") and values.get("lrn_full") and values.get("lrn_exporting"):
            if self.render(self.lrn_trim_cond) == "True":
                # lrn_new is an automation variable of the trim branch
                self.env.globals["lrn_new"] = ast.literal_eval(
                    self.render(self.lrn_new_tpl))
                new = ast.literal_eval(self.render(self.lrn_new_out))
                self._set_number(d, "ems_charge_allowance", new)
                self._set_number(d, "ems_export_ticks", 0)
            elif values.get("lrn_rising"):
                # the ESS is still ramping - not proof, restart the grace
                self._set_number(d, "ems_export_ticks", 0)
            else:
                self._set_number(d, "ems_export_ticks",
                                 ast.literal_eval(self.render(self.lrn_tick_out)))
        if values.get("lrn_ok") and (not values.get("lrn_exporting")
                                     or values.get("lrn_rising")):
            self._set_number(d, "ems_export_ticks", 0)
            if self.lrn_prev_out is not None:
                self._set_number(d, "ems_bat_prev", values.get("lrn_bat", 0))
        if self.render(self.lrn_reset_cond) == "True":
            self._set_number(d, "ems_charge_allowance",
                             ast.literal_eval(self.render(self.lrn_reset_out)))
        if self.render(self.lrn_probe_cond) == "True":
            self._set_number(d, "ems_charge_allowance",
                             ast.literal_eval(self.render(self.lrn_probe_out)))

        out["allowance"] = float(d["input_number.ems_charge_allowance"])
        out["push"] = float(self.render(
            self.target["attributes"]["charge_push"]) or 0)

        if self.render(self.night_cond) == "True":
            return out
        gate = self.render(self.write_cond) == "True"
        enabled = d["input_boolean.ems_enabled"] == "on"
        mode_ok = self.render(self.dtu_cond) == "True"
        if gate and enabled and mode_ok and target_pct not in ("unknown", ""):
            out["written"] = True
            self._write(d, float(target_pct))
        return out

    def _model(self, values: dict) -> str:
        """Which source feeds the charge-power term (protocol column)."""
        if self.want_charge_sensor and self.data.get(VBAT) not in (None, "unknown"):
            return "V x I"
        return "seplos"

    def _set_number(self, data: dict, key: str, value) -> None:
        data[f"input_number.{key}"] = str(value)

    def _write(self, data: dict, pct: float) -> None:
        data["__cap_current"] = f"{pct:.1f}"
        for inverter in (I1, I2, I3):
            data[inverter] = f"{pct:.1f}"
        data["__last_apply"] = vp.REF.timestamp()
        data["__attr:input_datetime.ems_last_apply:timestamp"] = data["__last_apply"]


# --------------------------------------------------------------------------- #
# the simulation
# --------------------------------------------------------------------------- #
def simulate(controller: Controller, scenario: str = "day"):
    pv_fn, load_fn, ess_tau = SCENARIOS[scenario]
    data = controller.data
    # keep the freshness ages stable: everything is "fresh" every step
    soc = SOC0
    bat = 0.0
    pv_actual = 0.0
    inv_pct = 50.0
    allowance_ts = vp.REF.timestamp()
    log = []

    steps = int((DAY_END_MIN - DAY_START_MIN) * 60 / DT)
    for index in range(steps):
        minute = DAY_START_MIN + index * DT / 60.0
        vp.REF = vp.REF + dt.timedelta(seconds=DT)
        load = load_fn(minute)
        potential = pv_fn(minute)

        vbat = battery_voltage(soc)
        # what the battery can really take right now (CV taper near full)
        accept = min(CMS_MAX, 50.0 * vbat)
        if soc > 97.0:
            accept *= max(0.0, (100.0 - soc) / 3.0)
        ess_target = max(0.0, min(accept, pv_actual - load))
        bat += (ess_target - bat) * min(1.0, DT / ess_tau)

        pv_cmd = min(potential, inv_pct / 100.0 * CAP)
        pv_actual += (pv_cmd - pv_actual) * min(1.0, DT / INV_TAU)

        grid = load + bat - pv_actual

        data["sun.sun"] = ("above_horizon"
                           if 6 * 60 <= minute <= 20 * 60 else "below_horizon")
        data[S] = data[V] = f"{grid:.0f}"
        data[PV] = f"{pv_actual:.0f}"
        data[SOC] = f"{soc:.1f}"
        data[BPOW] = f"{bat:.0f}"
        data[VBAT] = f"{vbat:.2f}"
        data[IBAT] = f"{bat / vbat:.2f}"        # signed A, + = charging
        data["__cap_current"] = f"{inv_pct:.1f}"
        data["__attr:input_datetime.ems_last_apply:timestamp"] = data["__last_apply"]
        data["__attr:input_datetime.ems_started_at:timestamp"] = vp.REF.timestamp() - 3600
        # how long ago the learned allowance last changed - drives the upward
        # re-probe (lrn_quiet)
        data["__age:input_number.ems_charge_allowance"] = max(
            0, int(vp.REF.timestamp() - allowance_ts))
        before = data["input_number.ems_charge_allowance"]

        result = controller.run(data)

        if data["input_number.ems_charge_allowance"] != before:
            allowance_ts = vp.REF.timestamp()
        if result["written"]:
            inv_pct = result["target"]

        soc += (bat / 1000.0) * (DT / 3600.0) / BAT_KWH * 100.0
        soc = max(0.0, min(100.0, soc))

        log.append(dict(minute=minute, potential=potential, pv=pv_actual,
                        load=load, bat=bat, soc=min(soc, 100.0), grid=grid,
                        mode=result["mode"], limit=inv_pct,
                        allowance=result["allowance"], push=result["push"],
                        ceiling=min(CMS_MAX, 50.0 * battery_voltage(soc)),
                        accept=accept, model=result["model"],
                        wrote=result["written"]))

    return log


# --------------------------------------------------------------------------- #
# protocol
# --------------------------------------------------------------------------- #
def assess(log):
    """Return the two properties as violation lists.

    The reference for "the battery is not at its limit" is the battery's TRUE
    acceptance (including the CV taper of the model), not the nominal limit: a
    battery near full really cannot take the offered power, and curtailing then
    is correct behaviour, not a premature cut.
    """
    premature, missed = [], []
    for row in log:
        offered = min(row["potential"], CAP)
        curtailed = (row["limit"] / 100.0 * CAP) < offered - 100.0
        surplus = row["potential"] > row["load"] + 200.0
        below_limit = row["bat"] < row["accept"] - 100.0
        if row["mode"] == "FULL" and surplus and below_limit and curtailed:
            premature.append(row)
        at_limit = row["bat"] >= row["ceiling"] - 100.0
        not_tapering = row["accept"] >= row["ceiling"] - 50.0
        wants_more = row["potential"] > row["load"] + row["ceiling"] + 200.0
        if row["mode"] == "FULL" and at_limit and not_tapering and wants_more:
            expected = row["load"] + row["ceiling"]
            if abs(row["pv"] - expected) > 300.0:
                missed.append(row)
    return premature, missed


def report(log, scenario="day", quiet=False):
    def hm(minute):
        return f"{int(minute) // 60:02d}:{int(minute) % 60:02d}"

    print("=" * 100)
    print(f"OpenDTU EMS - day simulation protocol   [scenario: {scenario}]")
    print("=" * 100)
    print(f"steps           : {len(log)}  ({DT:.0f} s per step, "
          f"{hm(log[0]['minute'])}-{hm(log[-1]['minute'])})")
    print(f"charge power term: {log[0]['model']}")
    print(f"ESS ramp model  : {SCENARIOS[scenario][2]:.0f} s time constant "
          "(seconds to minutes, as the package notes allow)")
    print("assertions      : (1) no curtailment while battery below its charge limit")
    print("                  (2) at the limit the array is cut to load + limit, no export")
    print()

    print("--- the day (every 30 min, plus the charge start) -------------------"
          "------------------------------------")
    print(f"{'time':>5} {'PV pot':>7} {'PV act':>7} {'load':>6} {'bat':>7} "
          f"{'SoC':>5} {'grid':>7} {'limit%':>7} {'allow':>6} {'push':>6} {'mode':>9}")
    start = next((row for row in log if row["bat"] > 50.0), None)
    for row in log:
        if int(row["minute"]) % 30 and row is not start:
            continue
        mark = "  <- charge starts" if row is start else ""
        print(f"{hm(row['minute']):>5} {row['potential']:>7.0f} {row['pv']:>7.0f} "
              f"{row['load']:>6.0f} {row['bat']:>7.0f} {row['soc']:>5.1f} "
              f"{row['grid']:>7.0f} {row['limit']:>7.1f} {row['allowance']:>6.0f} "
              f"{row['push']:>6.0f} {row['mode']:>9}{mark}")
    print()

    # 10 s detail around the moment the battery starts charging - this is the
    # window the complaint is about: the charge current has to ramp up.
    starts = [i for i, row in enumerate(log) if row["bat"] > 50.0]
    if starts:
        first = starts[0]
        window = [row for row in log[first:first + 36] if row["minute"] * 60 % 10 == 0]
        print("--- charge start in 10 s steps (the ramp) ------------------------"
              "------------------------------------")
        print(f"{'time':>5} {'PV pot':>7} {'PV act':>7} {'load':>6} {'bat':>7} "
              f"{'grid':>7} {'limit%':>7} {'allow':>6} {'push':>6}")
        for row in window:
            print(f"{hm(row['minute']):>5} {row['potential']:>7.0f} {row['pv']:>7.0f} "
                  f"{row['load']:>6.0f} {row['bat']:>7.0f} {row['grid']:>7.0f} "
                  f"{row['limit']:>7.1f} {row['allowance']:>6.0f} {row['push']:>6.0f}")
        print()

    premature, missed = assess(log)

    # exported energy after charging began (zero-export promise)
    charging = [r for r in log if r["bat"] > 50.0]
    worst_export = min((r["grid"] for r in charging), default=0.0)
    export_energy = sum(max(0.0, -r["grid"]) for r in charging) * DT / 3600.0 / 1000.0

    peak_bat = max(r["bat"] for r in log)
    reach = next((r for r in log if r["bat"] >= r["ceiling"] - 100.0), None)

    print("--- findings -------------------------------------------------------"
          "-------------------------------------")
    if start:
        print(f"battery starts charging : {hm(start['minute'])} "
              f"(PV {start['pv']:.0f} W, load {start['load']:.0f} W)")
    print(f"peak battery charge     : {peak_bat:.0f} W of {CMS_MAX:.0f} W limit")
    if reach:
        print(f"charge limit reached    : {hm(reach['minute'])}")
    else:
        print("charge limit reached    : NEVER - the battery never got near its limit")
    print(f"worst export while charging: {worst_export:.0f} W "
          f"(tolerance {EXPORT_TOL:.0f} W)")
    print(f"exported energy         : {export_energy:.2f} kWh")
    print()
    print(f"violations (1) premature curtailment while bat < limit : {len(premature)}")
    for row in premature[:6]:
        print(f"      {hm(row['minute'])}  PV {row['pv']:.0f}/{row['potential']:.0f} W  "
              f"bat {row['bat']:.0f} W (limit {row['accept']:.0f})  "
              f"limit {row['limit']:.1f} %  allow {row['allowance']:.0f} W  "
              f"grid {row['grid']:.0f} W")
    if len(premature) > 6:
        print(f"      ... {len(premature) - 6} more")
    print(f"violations (2) not curtailed at the limit              : {len(missed)}")
    for row in missed[:6]:
        print(f"      {hm(row['minute'])}  PV {row['pv']:.0f}/{row['potential']:.0f} W  "
              f"bat {row['bat']:.0f} W (limit {row['accept']:.0f})  "
              f"limit {row['limit']:.1f} %  allow {row['allowance']:.0f} W  "
              f"grid {row['grid']:.0f} W")
    if len(missed) > 6:
        print(f"      ... {len(missed) - 6} more")
    print()
    ok = not premature and not missed
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    print("=" * 100)
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="?", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--scenario", default="all",
                        choices=[*SCENARIOS, "all"],
                        help="which day to simulate (default: all)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv[1:])

    selected = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    code = 0
    for scenario in selected:
        controller = Controller(Path(args.package))
        log = simulate(controller, scenario)
        code |= report(log, scenario=scenario, quiet=args.quiet)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
