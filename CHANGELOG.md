# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Only the **current release line** is documented here. The notes of the superseded releases
(1.8.0 back to 1.0.0) are in the git history of this file and in the
[releases](https://github.com/acdcnow/opendtu-ems/releases).

## [Unreleased]

### Documentation

- **The licence statement was corrected to GPL-3.0.** `LICENSE` has always carried the GNU
  General Public License v3.0, while `README.md` (badge and licence section), `info.md` and the
  wiki still said *MIT*. All of them now say **GPL-3.0**.

## [1.10.0] - 2026-10-13

### Added

- **The day-start open phase.** At sunrise the array is held **wide open (100 %)** instead of
  being trimmed to "house load + charge need" (about 53 % with the reference installation), so
  the pack charges as fast as the sun allows and no PV is thrown away while the battery still has
  headroom. It is released — evaluated in the same render as the limit, so it can never lag a
  write — as soon as **any** of these is true:

  * the battery charges at its calculated maximum (`battery voltage × EMS max charge current`,
    capped at `EMS max charge power`),
  * the real PV power reaches `EMS open until solar` (3500 W by default) — the array is at full
    production, so throttling is possible again,
  * a **lasting** export appears: the loop's export tick counter reaches 2 (≈30 s), *not* a
    momentary reading. The ticks are reset while the battery is still climbing, so a load
    switching off or the ESS ramping — the transients `EMS export tolerance` and
    `EMS export grace` exist for — does **not** end the morning phase,
  * the SoC stop is reached while the battery takes nothing, or the mode leaves `FULL`.

  New helpers: `input_boolean.ems_open_phase` (the latch) and `input_number.ems_open_solar_w`
  (the threshold, 3500 W, **0 disables the phase**). New automation
  `automation.opendtu_ems_day_start` arms the latch at sunrise, on `NIGHT`→`FULL` and on
  `STARTING`→`FULL` (a Home Assistant restart during the day); the control loop clears it, so the
  phase cannot re-enter at the next export and only a new day start arms it again. The hand-over
  is written immediately (a step *down* can never cause an export), and
  `sensor.ems_pv_delivery` reports 100 % while the phase is open, so the watchdog cannot raise a
  false "PV under-delivering" alarm every morning.
- **The sensor mapping — every foreign entity id now lives in exactly one place.**
  Section 1 of the package is no longer a comment block with the ids typed into it; it is
  now 15 `input_text` helpers (`input_text.ems_src_*`). The package templates, both
  dashboards, the control loop's triggers and the write script all read the ids from there,
  so a renamed sensor is **one field** to change instead of ~60 occurrences across three
  files. Required: `grid`, `solar`, `batt_soc`, `batt_power`, `inv1_limit`, `inv2_limit`,
  `inv3_limit`. Optional: a backup grid meter, the Victron DC bus pair (voltage + current),
  the three per-inverter power sensors and the Victron charge stage.
- `blueprints/script/opendtu_ems/ems_map_sensors.yaml` — a **script blueprint** that asks for
  all fifteen names with entity pickers and writes them into the mapping helpers
  (Settings → Automations & scenes → Blueprints). The integration copies it to
  `<config>/blueprints/script/opendtu_ems/`, so a HACS install needs nothing copied by hand.
- `sensor.ems_map_status`: `ok`, or *"N required source(s) missing"*, with
  `required_missing` and `optional_empty` attributes — the first thing to look at after an
  install or an update.
- `automation.opendtu_ems_boot` raises a persistent notification at every start while a
  required mapping entry is still empty. An incomplete mapping is the one failure that
  otherwise only shows up as a permanently degraded mode (`GRID_BLIND` / `NO_BATTERY`).
- Five mapping mirrors — `sensor.ems_solar_power`, `sensor.ems_battery_soc`,
  `sensor.ems_battery_power`, `sensor.ems_battery_voltage`, `sensor.ems_battery_current` —
  so neither the control law nor the dashboards has to name a foreign entity any more. **The
  dashboards now use only EMS entities** apart from the mapping helpers.
- **Two diagnostic flags taken over from hand-made YAML**, with the same entity ids (and the
  same `unique_id` where there was one), so nothing that used them has to change — but they are
  now built from the EMS entities instead of foreign ids:
  * `binary_sensor.grid_export_throttling_required` — *"the grid exports more than the allowance
    of the moment"* (150 W from 90 % SoC, else 200 W, released at −50 W, with the matching
    30 s/60 s delay). The loop acts on this condition internally and `binary_sensor.ems_degraded`
    covers the *fault* modes, but neither **shows** "the array is exporting right now" — that is
    what this one is for. Its attributes expose grid, SoC, threshold and what the loop is doing
    about it (`battery`, `allowance`, `charge_push`).
  * `binary_sensor.high_consumption_ac_mode` — "the battery takes < 1200 W while the house draws
    > 1200 W and SoC < 90 %". A **mode flag** for your own automations; the control law does not
    read it (and cannot be affected by its thresholds). Delete it if nothing consumes it.
- `input_text.ems_src_house_load` — an **optional** mapping entry for your own house-consumption
  sensor. `sensor.ems_house_load` prefers it over its own `solar + grid − battery` (its `source`
  attribute says which is in use) and the two flags above use it. Display only: the control law
  never reads the house load, so a missing or wrong entry cannot affect the regulation.

### Changed

- **The minimum Home Assistant is now 2026.10.1** (declared in `hacs.json`, the package header,
  both README/info, the docs and the wiki). It is the version the whole package is validated
  against: `tests/validate_in_ha.py` boots a real Home Assistant, and it now also asserts that the
  running version satisfies the declared minimum. CI installs `homeassistant==2026.10.1` for that
  step.
- The **reference installation** the shipped tests run against now uses the real ids of the
  reference meter: `sensor.shelly_3em_pro_leistung` (primary grid) instead of the earlier
  `sensor.shelly3mpro_total_active_power`. Only the fixtures changed — the package itself has
  held no entity id since this release, which is exactly the point of the mapping.
- The two `numeric_state` trigger pairs on the raw grid meters became **two triggers on
  `sensor.ems_grid_power`**, the already-arbitrated value: the same reaction (a crossing with
  a 5 s hold, no 20 s polling) without an entity id that a rename can silently break.
- `script.ems_apply` writes through `input_text.ems_src_inv1_limit` … `inv3_limit` using
  `data: entity_id` (which *is* templated — a trigger's `entity_id` is not), and skips an
  unmapped inverter instead of writing an empty entity id into the log.
- `sensor.ems_inverter_capacity` builds its capacity map from the mapping helpers; the
  `expand()` of three literal `number.*_limit_nonpersistent_relative` ids is gone, so an
  unmapped inverter simply does not count towards the capacity.
- `tests/validate_package.py` follows: the mapping is part of `BASE`, the mirrors are resolved
  before every render, `input_text` counts as a created domain, and the "script writes what
  the capacity map counts" check now compares the *mapping helpers* (and additionally that the
  script writes through them and not through a stale literal).
- **A mapping gate card at the top of both dashboards.** While `sensor.ems_map_status` is not
  `ok` it names the entries that are still empty and says how to fill them, then disappears by
  itself. Without it an incomplete mapping looks exactly like a broken dashboard — every card
  is empty and nothing says why.
- `tests/validate_dashboards.py` — renders **every template of both boards** against a
  simulated sensor chain and adds the check `validate_package.py` cannot do: the entity ids a
  card builds *inside* its Jinja (`states('sensor.x')`) must exist too. A card wired to a name
  that does not exist renders nothing and logs nothing. Also asserts that an empty mapping does
  **not** report `ok`.
- `tests/validate_in_ha.py` — loads the package in a **real Home Assistant**
  (`pip install homeassistant`, then run it): it asserts that all seven platforms are set up
  (an invalid config key silently drops a whole platform), that the boot automation ran, that
  every entity both boards name exists and carries the documented value, and that
  `script.ems_apply` really writes through the mapping. Not part of CI (the HA package is big);
  the workflow shows the two commands.

### Fixed

- **Every inverter write was silently blocked.** `script.ems_apply` skips inverters that are
  not mapped, and the guard was `value_template: "{{ inv1 }}"` — the entity id itself. A
  template condition is only *true* for `true`/`yes`/`on`/`enable`/a non-zero number, so a
  non-empty **string** is false: the script did nothing, reported nothing (the write is inside
  `continue_on_error`) and the array was never regulated. The guards now render a real boolean.
  Found by `tests/validate_in_ha.py` — the reason it advances the *commanded* value to the
  inverter entity and not just the template.
- **`sensor.ems_map_status` always read `ok`.** A plain `set` inside a Jinja `for` block does
  not survive the loop, so the counter stayed 0: the warning card never appeared and the boot
  notification never fired. It uses a `namespace` now and reports *"N required source(s)
  missing"*, with the regression guard in `tests/validate_dashboards.py`.
- **The five mapping mirrors rendered a string.** A template sensor with a `unit_of_measurement`
  or `state_class` must render a **number** — Home Assistant's template documentation is
  explicit that such a state template "must not render to a string, including `unknown` or
  `unavailable`". They now render `float(0)` behind an `availability` of
  `… and is_number(states(s))`, which is the documented pattern for exactly this case. Same for
  the fallback branch of `sensor.ems_battery_charge_power`, which had inherited the string.
- **The day simulation never drove the control law at all.** `tests/simulate_day.py` renders the
  real templates, but it was written before the sensor mapping and never learned about it: every
  `input_text.ems_src_*` was empty, `sensor.ems_inverter_capacity` was 0 and the whole simulated
  day ran in `DTU_BLIND` without a single write. Its two properties only inspect `FULL` rows, so
  they were vacuously true. The harness now provides the mapping and resolves the mirrors, and a
  **third** property asserts the day-start behaviour: the first write of the day is the full open,
  and the phase does not re-enter after the release. Re-running it immediately showed the phase
  being released by a *momentary* export at 07:25 (an ESS ramp after a kettle switched off) —
  which is why the release test uses the lasting-export counter described above.

### Migration

1. Apply the update (HACS → the `opendtu_ems.install_bundle` action, or copy the package).
2. Restart Home Assistant — the 15 `EMS source - …` helpers appear, empty.
3. Run the blueprint once, or paste the ids into the helpers by hand.
4. `sensor.ems_map_status` must read `ok`; the boot notification disappears by itself.
5. **Delete the hand-made `template:` definitions of `Grid Export Throttling Required` and
   `High Consumption AC Mode`** (and any hand-made copy of a sensor the package now owns). Both
   names are declared by the package now; two definitions of one entity id make Home Assistant
   log *"entity already exists"* and the state becomes a coin toss between the two. The ids and
   the `unique_id` of `High Consumption AC Mode` are unchanged on purpose, so automations and
   histories that use them keep working.
6. If you have your own house-consumption sensor (`sensor.hausverbrauch` on the reference
   installation), put it into the blueprint's **House consumption** field — optional, display
   only.
7. The day-start open phase is on by default. **Set `EMS open until solar` to 0** if you prefer
   the 1.9.0 behaviour (regulate from the first watt).
8. **The prose moved out of the package.** `packages/opendtu_ems.yaml` now ends with a short
   pointer section instead of ~230 lines of `NOTES A…M`; the reasoning lives in the rewritten
   wiki ([How it works](https://github.com/acdcnow/opendtu-ems/wiki/How-It-Works),
   [Charge allowance](https://github.com/acdcnow/opendtu-ems/wiki/Charge-Allowance),
   [Sensor mapping](https://github.com/acdcnow/opendtu-ems/wiki/Sensor-Mapping),
   [Installation](https://github.com/acdcnow/opendtu-ems/wiki/Installation),
   [Dashboards](https://github.com/acdcnow/opendtu-ems/wiki/Dashboards),
   [Reference](https://github.com/acdcnow/opendtu-ems/wiki/Reference),
   [Troubleshooting](https://github.com/acdcnow/opendtu-ems/wiki/Troubleshooting),
   [Upgrading](https://github.com/acdcnow/opendtu-ems/wiki/Upgrading)), which also replaces the
   former Architecture Concept Document, Software Design Document and Workflow Diagrams pages.

Your ids survive the update: the mapping lives in `input_text` entities, whose values Home
Assistant restores, not in the file that gets replaced.

## [1.9.0] - 2026-10-11

### Fixed

- **The array is no longer held below what the battery could take while the
  battery is still ramping up.** The learned `EMS charge allowance` was cut as
  soon as the grid exported for `EMS export grace` while the battery took less
  than it was offered — and a Victron that is still ramping up from 0 to its
  charge current limit looks exactly like that. The allowance was then latched
  under the battery's real acceptance and recovered only slowly (re-probe after
  `EMS charge re-probe`, ×1.5), so PV stayed cut although the battery was
  nowhere near its charge limit: *"the solar power gets set down even if the
  battery is not charging to the limit"*. The cut now additionally requires that
  the charge power has **stopped rising** (`lrn_rising`, from the new
  `input_number.ems_bat_prev`): an export while the charge is still climbing is
  the ESS ramping, not proof that the battery cannot take the offer — it
  restarts the grace counter instead of trimming. `tests/simulate_day.py`
  reproduces the old behaviour and shows the fix.

### Added

- **Dynamic charge power from the Victron DC bus.**
  `sensor.ems_battery_charge_power` is `battery voltage × SIGNED battery
  current` (`sensor.serialbattery_seplos_dc_bus_spannung` ×
  `sensor.venus_dc_batterie_stromstarke`) whenever both are readable and the
  Seplos BMS power otherwise. A **negative** value means the battery is
  discharging — the battery is then not the bottleneck and the value never
  curtails the array. `sensor.ems_charge_power_limit` is `battery voltage ×
  input_number.ems_max_charge_current`, capped at `EMS max charge power`, which
  is also the fallback when the voltage sensor is missing (behaviour then is
  exactly the pre-1.9 one).
- `input_number.ems_max_charge_current` (default `50` A): the DVCC / BMS charge
  current limit the dynamic charge power is derived from.
- `input_number.ems_bat_prev`: internal, written by the loop — the battery power
  of the previous run, which is what tells a still-ramping ESS from a battery
  that has really stopped accepting power.
- `input_boolean.ems_expert_mode` (default `off`): a dashboard switch. The
  ready-made dashboards keep the tuning controls and the risk actions hidden
  until it is switched on.
- `tests/simulate_day.py`: a 10 s-resolution day simulation that renders the
  **real templates** of the package (scenarios `day` and `cloud`) and asserts
  that PV is not curtailed while the battery is below its charge limit, and that
  at the limit it is cut to `house load + charge limit` with no export.

### Changed

- `sensor.ems_limit_target` works with the derived charge power and the dynamic
  charge power limit; the `allowance` and `charge_push` attributes report the
  same figures.
- The ready-made dashboard is two views now: `ems-overview.yaml` (live picture,
  status, trends) and `ems-expert.yaml` (diagnostics and the tuning controls,
  which appear only while `input_boolean.ems_expert_mode` is on). The HACS
  integration installs both.

### Documentation

- `README.md`, `docs/CONFIGURATION.md` and `docs/DASHBOARD.md` describe the
  dynamic charge power, the ramp guard, the new helpers, the two dashboards and
  the expert-mode switch.
