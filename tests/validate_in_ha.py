#!/usr/bin/env python3
"""Load the EMS package in a REAL Home Assistant and check the wiring end to end.

Usage (needs the `homeassistant` package - CI installs only pyyaml + jinja2, so
this test *skips* there):

    python -m venv %TEMP%\\havalidate\\venv
    %TEMP%\\havalidate\\venv\\Scripts\\python -m pip install homeassistant==2026.10.1
    %TEMP%\\havalidate\\venv\\Scripts\\python tests/validate_in_ha.py

Why this test exists
--------------------
An **unknown or wrong config key does not raise at runtime**: Home Assistant
rejects the whole platform ("Invalid config for [template]") and every entity of
it silently never appears. The entities you already had keep working, the cards
that point at the missing ones show *nothing*, and no log line says "the card is
wired wrong". That is the failure this test is for - `validate_package.py`
(pyyaml + jinja2) and `validate_dashboards.py` (rendering) cannot see it.

What it checks, in a real interpreter
-------------------------------------
1. the package is loaded the way a user's HA loads it (a `packages:` folder), so
   every schema of `input_text`, `template`, `script` and `automation` is
   validated by this exact Home Assistant version
2. no setup error is logged for our domains
3. every entity the dashboards name exists afterwards, spelled exactly so
4. the mapping -> mirrors -> derived sensors chain really produces a value: the
   fake grid/PV/battery sources are wired through `input_text.set_value` and the
   assertions are made on `sensor.ems_mode`, `sensor.ems_solar_power`,
   `sensor.ems_limit_target`, `sensor.ems_map_status`, ...
5. `script.ems_apply` really writes the inverter limits (the `data: entity_id`
   templating), which is why the fake inverters are template `number` entities
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from homeassistant import bootstrap as ha_bootstrap
    from homeassistant import core as ha_core
    from homeassistant import loader as ha_loader
except ImportError:
    print("SKIP: `homeassistant` is not installed - see the docstring for how to run this")
    sys.exit(0)

import yaml  # noqa: E402  (after the skip check, so the message stays readable)

ENTITY_RE = re.compile(
    r"\b(?:sensor|binary_sensor|input_boolean|input_number|input_datetime"
    r"|input_text|script|automation)\.[a-z0-9_]+")

# created by the HACS integration, not by the package - see validate_integration.py
INTEGRATION_ENTITIES = {"sensor.ems_bundle"}


def all_strings(node):
    """Every string of a loaded card tree."""
    if isinstance(node, dict):
        for value in node.values():
            yield from all_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from all_strings(value)
    elif isinstance(node, str):
        yield node


def contract_ids(node) -> set[str]:
    """Every entity a board names - `entity:` keys AND the ids inside templates.

    Ids ending in an underscore are skipped: `input_text.ems_src_*` in prose is a
    family name, not an entity.
    """
    found: set[str] = set()
    for text in all_strings(node):
        found.update(entity for entity in ENTITY_RE.findall(text)
                     if not entity.endswith("_"))
    return found


# the contract between the package and everything outside it: the two ready-made
# boards, plus the two diagnostic flags carried over from a hand-made `template:`
# block (their entity ids must not change, or the automations using them break)
CONTRACT_ENTITIES = (
    "sensor.ems_mode", "sensor.ems_grid_power", "sensor.ems_solar_power",
    "sensor.ems_battery_soc", "sensor.ems_battery_power",
    "sensor.ems_battery_voltage", "sensor.ems_battery_current",
    "sensor.ems_battery_charge_power", "sensor.ems_charge_power_limit",
    "sensor.ems_house_load", "sensor.ems_limit_target",
    "sensor.ems_inverter_capacity", "sensor.ems_pv_delivery",
    "sensor.ems_map_status", "binary_sensor.ems_degraded",
    "binary_sensor.grid_export_throttling_required",
    "binary_sensor.high_consumption_ac_mode",
    "input_boolean.ems_enabled", "input_boolean.ems_automatic",
    "input_boolean.ems_expert_mode", "input_boolean.ems_verbose",
    "input_boolean.ems_simulate_battery_loss",
    "input_number.ems_manual_pct", "input_number.ems_grid_bias",
    "input_number.ems_charge_allowance", "input_number.ems_max_charge_power",
    "input_number.ems_max_charge_current", "input_number.ems_settle_seconds",
    "input_number.ems_max_step_pct", "input_number.ems_hysteresis_pct",
    "input_number.ems_start_grace", "input_number.ems_export_tolerance",
    "input_number.ems_export_grace", "input_number.ems_reprobe_seconds",
    "input_number.ems_export_ticks", "input_number.ems_bat_prev",
    "input_number.ems_failsafe_pct", "input_number.ems_meter_tolerance",
    "input_number.ems_soc_stop", "input_number.ems_delivery_short",
    "input_datetime.ems_last_apply", "input_datetime.ems_started_at",
    "input_boolean.ems_open_phase", "input_number.ems_open_solar_w",
    "script.ems_apply", "script.ems_set_defaults",
    "automation.opendtu_ems_loop", "automation.opendtu_ems_watchdog",
    "automation.opendtu_ems_boot", "automation.opendtu_ems_day_start",
)

# the stand-in for OpenDTU / Shelly / Victron / Seplos, so the chain can be
# driven in an isolated HA. The inverter limits are template `number` entities,
# so the write path (script.ems_apply) is exercised as well.
FAKE_SOURCES = """
input_number:
  fake_inv1_store: {name: fake inv1 store, min: 0, max: 100, step: 0.1, mode: box}
  fake_inv2_store: {name: fake inv2 store, min: 0, max: 100, step: 0.1, mode: box}
  fake_inv3_store: {name: fake inv3 store, min: 0, max: 100, step: 0.1, mode: box}
  # the physical side, so the test can drive the chain (the open phase needs a
  # changeable grid, PV power and battery power - a real day, not a frozen one)
  fake_grid_w: {name: fake grid W, min: -6000, max: 6000, step: 1, mode: box}
  fake_solar_w: {name: fake solar W, min: 0, max: 8000, step: 1, mode: box}
  fake_batt_w: {name: fake batt W, min: -6000, max: 6000, step: 1, mode: box}

template:
  - sensor:
      - name: "Fake grid"
        unique_id: fake_grid
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "{{ states('input_number.fake_grid_w') }}"
      - name: "Fake solar"
        unique_id: fake_solar
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "{{ states('input_number.fake_solar_w') }}"
      - name: "Fake batt soc"
        unique_id: fake_batt_soc
        unit_of_measurement: "%"
        device_class: battery
        state_class: measurement
        state: "85"
      - name: "Fake batt power"
        unique_id: fake_batt_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "{{ states('input_number.fake_batt_w') }}"
      - name: "Fake batt voltage"
        unique_id: fake_batt_voltage
        unit_of_measurement: V
        device_class: voltage
        state_class: measurement
        state: "51.2"
      # the Victron pair is what the package's charge power uses (V x I), so the
      # current follows the power: 51.2 V x 23.44 A = 1200 W, the documented
      # base value
      - name: "Fake batt current"
        unique_id: fake_batt_current
        unit_of_measurement: A
        device_class: current
        state_class: measurement
        state: "{{ (states('input_number.fake_batt_w') | float(0) / 51.2) | round(2) }}"
      - name: "Fake inv1 power"
        unique_id: fake_inv1_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "900"
      - name: "Fake inv2 power"
        unique_id: fake_inv2_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "1050"
      - name: "Fake inv3 power"
        unique_id: fake_inv3_power
        unit_of_measurement: W
        device_class: power
        state_class: measurement
        state: "1050"
      - name: "Fake victron state"
        unique_id: fake_victron_state
        state: "Bulk"
  - number:
      - name: "Fake inv1 limit"
        unique_id: fake_inv1_limit
        unit_of_measurement: "%"
        min: 0
        max: 100
        step: 0.1
        set_value:
          - action: input_number.set_value
            target:
              entity_id: input_number.fake_inv1_store
            data:
              value: "{{ value }}"
        state: "{{ states('input_number.fake_inv1_store') }}"
      - name: "Fake inv2 limit"
        unique_id: fake_inv2_limit
        unit_of_measurement: "%"
        min: 0
        max: 100
        step: 0.1
        set_value:
          - action: input_number.set_value
            target:
              entity_id: input_number.fake_inv2_store
            data:
              value: "{{ value }}"
        state: "{{ states('input_number.fake_inv2_store') }}"
      - name: "Fake inv3 limit"
        unique_id: fake_inv3_limit
        unit_of_measurement: "%"
        min: 0
        max: 100
        step: 0.1
        set_value:
          - action: input_number.set_value
            target:
              entity_id: input_number.fake_inv3_store
            data:
              value: "{{ value }}"
        state: "{{ states('input_number.fake_inv3_store') }}"
"""

# what the mapping is pointed at in this test
MAPPING = {
    "ems_src_grid": "sensor.fake_grid",
    "ems_src_grid_backup": "sensor.fake_grid",
    "ems_src_solar": "sensor.fake_solar",
    "ems_src_batt_soc": "sensor.fake_batt_soc",
    "ems_src_batt_power": "sensor.fake_batt_power",
    "ems_src_batt_voltage": "sensor.fake_batt_voltage",
    "ems_src_batt_current": "sensor.fake_batt_current",
    "ems_src_inv1_limit": "number.fake_inv1_limit",
    "ems_src_inv2_limit": "number.fake_inv2_limit",
    "ems_src_inv3_limit": "number.fake_inv3_limit",
    "ems_src_inv1_power": "sensor.fake_inv1_power",
    "ems_src_inv2_power": "sensor.fake_inv2_power",
    "ems_src_inv3_power": "sensor.fake_inv3_power",
    "ems_src_victron_state": "sensor.fake_victron_state",
}

fails: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"  {'OK  ' if condition else '!!  '}{message}")
    if not condition:
        fails.append(message)


class Warnings(logging.Handler):
    """Collects ERROR/CRITICAL records so a rejected platform cannot hide."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")


def build_config_dir(package: Path) -> tuple[Path, dict]:
    """A minimal config dir: the package plus the fake sources, merged the way
    Home Assistant merges a `packages:` folder (lists append, mappings merge).

    The merge happens here rather than through HA's own loader because that one
    needs a bootstrapped hass (integration cache) - and `!include_dir_named`
    cannot be read with plain yaml.safe_load() in the first place.
    """
    root = Path(tempfile.mkdtemp(prefix="ems-in-ha-"))
    packages = root / "packages"
    packages.mkdir()
    shutil.copy(package, packages / "opendtu_ems.yaml")
    (packages / "fake_sources.yaml").write_text(FAKE_SOURCES, encoding="utf-8")
    (root / "configuration.yaml").write_text(
        "homeassistant:\n  latitude: 48.2082\n  longitude: 16.3738\n"
        "  time_zone: UTC\n", encoding="utf-8")

    config: dict = {}
    for source in (root / "configuration.yaml", *sorted(packages.glob("*.yaml"))):
        for key, value in (yaml.safe_load(source.read_text(encoding="utf-8")) or {}).items():
            if key not in config:
                config[key] = value
            elif isinstance(config[key], dict) and isinstance(value, dict):
                config[key] = {**config[key], **value}
            elif isinstance(config[key], list) and isinstance(value, list):
                config[key] = [*config[key], *value]
            else:
                config[key] = value
    return root, config


async def settle(hass: ha_core.HomeAssistant, rounds: int = 6) -> None:
    """Let the template chain re-render (each hop is one state change)."""
    for _ in range(rounds):
        await hass.async_block_till_done()
        await asyncio.sleep(0)


async def main() -> int:
    package = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "packages" / "opendtu_ems.yaml")
    config_dir, config = build_config_dir(package)
    print("== real Home Assistant ==")
    try:
        from homeassistant.const import __version__ as ha_version
        print(f"  homeassistant {ha_version}  ({config_dir})")
    except Exception:  # pragma: no cover
        ha_version = None

    # the minimum declared for HACS (hacs.json) has to be satisfied by the Home
    # Assistant that loads the package - that is the version the schemas are
    # validated against, and the version the docs promise
    declared = None
    hacs_json = ROOT / "hacs.json"
    if hacs_json.exists():
        declared = json.loads(hacs_json.read_text(encoding="utf-8")).get("homeassistant")
    if ha_version and declared:
        def as_tuple(text):
            return tuple(int(part) for part in re.findall(r"\d+", str(text)))

        check(as_tuple(ha_version) >= as_tuple(declared),
              f"the running Home Assistant ({ha_version}) satisfies the declared "
              f"minimum {declared} from hacs.json")
        print(f"      declared minimum (hacs.json): {declared}")

    captured = Warnings()
    logging.getLogger().addHandler(captured)
    logging.getLogger().setLevel(logging.WARNING)

    hass = ha_core.HomeAssistant(str(config_dir))
    try:
        # HA's own bootstrap: loader.async_setup() creates the data structures
        # (without it async_setup_component raises KeyError: 'integrations'),
        # async_from_config_dict() then does what a real start does - config
        # entries, base functionality, core config, and every integration of the
        # config. That is what makes this a REAL load and not a schema guess.
        ha_loader.async_setup(hass)
        hass.config.skip_pip = True
        booted = await ha_bootstrap.async_from_config_dict(config, hass)
        check(booted is not None, "Home Assistant bootstrapped the config")
        await hass.async_start()
        await settle(hass)

        # ---- every platform we rely on was really set up ------------------
        # a rejected schema would leave the domain out of hass.config.components
        # (and log "Invalid config for [...]") - the automations are the ones a
        # user notices first, because nothing regulates without them
        for domain in ("input_text", "input_boolean", "input_number",
                       "input_datetime", "template", "script", "automation"):
            check(domain in hass.config.components, f"platform '{domain}' was set up")

        # ---- the setup must not have logged a rejection -------------------
        ours = [r for r in captured.records
                if re.search(r"input_text|template|script|automation|ems", r)]
        for record in ours:
            print(f"      log: {record}")
        check(not ours, "no setup error for our domains (invalid key check)")

        # ---- the boot automation ran (it records the start time) ----------
        # a fresh install leaves every input_number at its minimum, so the boot
        # automation applies the documented defaults - including this timestamp
        started = hass.states.get("input_datetime.ems_started_at")
        check(started is not None and started.attributes.get("timestamp"),
              "automation.opendtu_ems_boot ran (started_at has a timestamp)")

        # ---- the mapping is empty at first: say so ------------------------
        helpers = {key.split(".", 1)[1]: hass.states.get(key)
                   for key in hass.states.async_entity_ids("input_text")}
        blank = [key for key, state in helpers.items()
                 if state is None or state.state in ("", "unknown", "unavailable")]
        print(f"      mapping helpers: {len(blank)} of {len(helpers)} still empty")
        check(len(helpers) == 15, f"the package declares 15 mapping helpers "
                                  f"(found {len(helpers)})")
        if blank:
            print(f"      empty: {blank}")
        check(hass.states.get("sensor.ems_map_status") is not None,
              "sensor.ems_map_status exists before the mapping is filled")
        map_state = hass.states.get("sensor.ems_map_status")
        check(map_state is not None and not map_state.state.startswith("ok")
              and "missing" in map_state.state,
              f"sensor.ems_map_status reports the gaps: {map_state.state!r}")

        # ---- the fresh-install defaults, as the boot automation applies them
        # (a real first start does this itself; calling it again is harmless)
        if "script.ems_set_defaults" in hass.states.async_entity_ids("script"):
            await hass.services.async_call("script", "ems_set_defaults", blocking=True)
            await settle(hass)
        check(hass.states.get("input_number.ems_max_charge_power").state == "2500.0",
              "script.ems_set_defaults set the documented defaults")

        # ---- fill the mapping the way the blueprint does ------------------
        for key, value in MAPPING.items():
            await hass.services.async_call(
                "input_text", "set_value",
                {"entity_id": f"input_text.{key}", "value": value}, blocking=True)
        # the physical side of the reference day: the numbers every assertion
        # below is built on (those helpers start at their minimum)
        for entity_id, value in (("input_number.fake_grid_w", -234),
                                 ("input_number.fake_solar_w", 3000),
                                 ("input_number.fake_batt_w", 1200)):
            await hass.services.async_call(
                "input_number", "set_value",
                {"entity_id": entity_id, "value": value}, blocking=True)
        # "Home Assistant started a while ago": otherwise the STARTING grace is
        # active and nothing is regulated - which is exactly what a restart does
        await hass.services.async_call(
            "input_datetime", "set_datetime",
            {"entity_id": "input_datetime.ems_started_at",
             "timestamp": 1700000000}, blocking=True)
        # slew and settle are knobs, not logic: disable both so the asserted
        # numbers are the documented ones (validate_package.py does the same)
        for entity_id, value in (("input_number.ems_max_step_pct", 100),
                                 ("input_number.ems_settle_seconds", 0)):
            await hass.services.async_call(
                "input_number", "set_value",
                {"entity_id": entity_id, "value": value}, blocking=True)
        await settle(hass)
        check(hass.states.get("sensor.ems_map_status").state == "ok",
              "sensor.ems_map_status reads 'ok' once the mapping is filled")

        # ---- the chain has data -------------------------------------------
        expected = {
            "sensor.ems_solar_power": "3000.0",
            "sensor.ems_battery_soc": "85.0",
            "sensor.ems_battery_power": "1200.0",
            "sensor.ems_battery_voltage": "51.2",
            "sensor.ems_battery_current": "23.44",
            "sensor.ems_battery_charge_power": "1200.0",
            "sensor.ems_charge_power_limit": "2500",
            "sensor.ems_house_load": "1566",
            "sensor.ems_grid_power": "-234",
            "sensor.ems_inverter_capacity": "4700",
            "sensor.ems_mode": "FULL",
        }
        for entity_id, want in expected.items():
            state = hass.states.get(entity_id)
            got = state.state if state else "<missing>"
            # compare numerically when both are numbers: Home Assistant writes
            # "1200" for an integer and "1200.0" for a float, and which one comes
            # out depends on the arithmetic, not on the value
            ok = got == want
            if not ok:
                try:
                    ok = abs(float(got) - float(want)) < 0.005
                except (TypeError, ValueError):
                    ok = False
            check(ok, f"{entity_id} = {got} (want {want})")

        limit = hass.states.get("sensor.ems_limit_target")
        check(limit is not None and limit.state not in ("unknown", "unavailable"),
              f"sensor.ems_limit_target = {limit.state if limit else '<missing>'}")
        check(limit is not None and limit.attributes.get("allowance") is not None,
              "sensor.ems_limit_target carries the 'allowance' attribute")
        degraded = hass.states.get("binary_sensor.ems_degraded")
        check(degraded is not None and degraded.state == "off",
              f"binary_sensor.ems_degraded = {degraded.state if degraded else '<missing>'}")

        # ---- every entity the dashboards name exists ----------------------
        # read from the LOADED yaml: comments are gone there (a comment like
        # "input_text.ems_src_*" is not an entity reference), but the ids inside
        # the card templates are still strings and are checked as well
        for dashboard in sorted((ROOT / "dashboards").glob("*.yaml")):
            loaded = yaml.safe_load(dashboard.read_text(encoding="utf-8"))
            named = contract_ids(loaded)
            missing = sorted(e for e in named
                             if hass.states.get(e) is None
                             and e not in INTEGRATION_ENTITIES)
            check(not missing, f"{dashboard.name}: all named entities exist "
                               f"({len(named)} ids)")
            if missing:
                print(f"      missing: {missing}")

        for entity_id in CONTRACT_ENTITIES:
            if hass.states.get(entity_id) is None:
                check(False, f"{entity_id} was not created")
        check(all(hass.states.get(e) is not None for e in CONTRACT_ENTITIES),
              f"all {len(CONTRACT_ENTITIES)} contract entities exist")

        # ---- the write path: script.ems_apply through the mapping ---------
        target = hass.states.get("sensor.ems_limit_target").state
        captured.records.clear()
        await hass.services.async_call(
            "script", "ems_apply", {"pct": 42}, blocking=True)
        await settle(hass)
        for record in captured.records:
            print(f"      log after the write: {record}")
        written = hass.states.get("number.fake_inv1_limit")
        got = written.state if written else "<missing>"
        check(got == "42.0" or got.startswith("42"), 
              f"script.ems_apply wrote 42 %% into number.fake_inv1_limit (got {got})")
        for store in ("input_number.fake_inv2_store", "input_number.fake_inv3_store"):
            state = hass.states.get(store)
            check(state is not None and str(state.state).startswith("42"),
                  f"script.ems_apply wrote 42 %% into {store} (got "
                  f"{state.state if state else '<missing>'})")
        print(f"      target before the write was {target}")

        # ---- the automations exist and are usable -------------------------
        for entity_id in ("automation.opendtu_ems_loop",
                          "automation.opendtu_ems_watchdog",
                          "automation.opendtu_ems_boot"):
            state = hass.states.get(entity_id)
            check(state is not None, f"{entity_id} exists (state "
                                     f"{state.state if state else '<missing>'})")

        # ---- the OPTIONAL house-load override -----------------------------
        # unmapped (up to here) the house load is calculated - asserted as 1566
        # above. Mapping a sensor must switch sensor.ems_house_load over to it
        # AND say so in 'source'.
        await hass.services.async_call(
            "input_text", "set_value",
            {"entity_id": "input_text.ems_src_house_load",
             "value": "sensor.fake_solar"}, blocking=True)
        await settle(hass)
        house = hass.states.get("sensor.ems_house_load")
        check(house is not None and house.state == "3000",
              f"mapping a house-load sensor switches the source (got "
              f"{house.state if house else '<missing>'}, want 3000)")
        check(house is not None
              and house.attributes.get("source") == "mapped sensor",
              f"… and reports source={house.attributes.get('source') if house else '?'}")

        # ---- the day-start open phase -------------------------------------
        # arm it by hand - that is exactly what automation.opendtu_ems_day_start
        # does at sunrise - and drive its two exits
        for entity_id, value in (("input_number.fake_solar_w", 1200),
                                 ("input_number.fake_grid_w", 300),
                                 ("input_number.fake_batt_w", 700)):
            await hass.services.async_call(
                "input_number", "set_value",
                {"entity_id": entity_id, "value": value}, blocking=True)
        await hass.services.async_call(
            "input_boolean", "turn_on",
            {"entity_id": "input_boolean.ems_open_phase"}, blocking=True)
        await settle(hass)
        opened = hass.states.get("sensor.ems_limit_target")
        check(opened is not None and opened.state == "100.0",
              f"an armed open phase holds the array at 100 % (got "
              f"{opened.state if opened else '<missing>'})")
        check(opened is not None and opened.attributes.get("open_phase") == "on",
              f"… and reports open_phase="
              f"{opened.attributes.get('open_phase') if opened else '?'}")
        # the battery reaches its calculated maximum -> released in the same
        # render (no export, no waiting for a loop cycle)
        await hass.services.async_call(
            "input_number", "set_value",
            {"entity_id": "input_number.fake_batt_w", "value": 2400}, blocking=True)
        await settle(hass)
        released = hass.states.get("sensor.ems_limit_target")
        check(released is not None and float(released.state) < 99.0,
              f"the battery at its maximum ends the phase (got "
              f"{released.state if released else '<missing>'} %)")
        # … and the control loop clears the latch, so it cannot re-enter
        await hass.services.async_call(
            "automation", "trigger",
            {"entity_id": "automation.opendtu_ems_loop"}, blocking=True)
        await settle(hass)
        latch = hass.states.get("input_boolean.ems_open_phase")
        check(latch is not None and latch.state == "off",
              f"the control loop clears the latch (got "
              f"{latch.state if latch else '<missing>'})")
        # … and a lasting export ends it as well (the tick counter is the loop's
        # "sustained export" memory - one tick is still a ramp)
        await hass.services.async_call(
            "input_number", "set_value",
            {"entity_id": "input_number.fake_batt_w", "value": 700}, blocking=True)
        await hass.services.async_call(
            "input_boolean", "turn_on",
            {"entity_id": "input_boolean.ems_open_phase"}, blocking=True)
        await hass.services.async_call(
            "input_number", "set_value",
            {"entity_id": "input_number.ems_export_ticks", "value": 2}, blocking=True)
        await settle(hass)
        exporting = hass.states.get("sensor.ems_limit_target")
        check(exporting is not None and float(exporting.state) < 99.0,
              f"a lasting export ends the phase as well (got "
              f"{exporting.state if exporting else '<missing>'} %)")
    finally:
        await hass.async_stop(force=True)
        logging.getLogger().removeHandler(captured)
        shutil.rmtree(config_dir, ignore_errors=True)

    print("\n== result ==")
    if fails:
        for message in fails:
            print(f"  FAIL {message}")
        print(f"\n{len(fails)} FAILURES")
        return 1
    print("  the package loads, every dashboard entity exists and has data")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
