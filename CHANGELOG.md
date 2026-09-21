# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- **Wiki published** (https://github.com/acdcnow/opendtu-ems/wiki) with a landing page that
  serves the current line *and* the superseded one:
  [Architecture Concept Document](https://github.com/acdcnow/opendtu-ems/wiki/Architecture-Concept-Document)
  (goals and non-goals, system context, concepts C1–C6, decisions AD-1…AD-12, NFRs, risks,
  roadmap),
  [Software Design Document](https://github.com/acdcnow/opendtu-ems/wiki/Software-Design-Document)
  (deployment model, entity inventory, freshness rules, component design with the exact
  formulas, the learning algorithm, the watchdog, 12 invariants, sequences, test/CI design,
  release process, traceability),
  [Workflow Diagrams](https://github.com/acdcnow/opendtu-ems/wiki/Workflow-Diagrams)
  (GitDiagram repository map — 14 components, 19 connections — plus mode ladder, meter
  arbitration, control cycle, learning, startup, fault and deployment flows) and
  [Control law 1.4.x (archived)](https://github.com/acdcnow/opendtu-ems/wiki/Archive-1.4-Control-Law)
  (the export-feedback law, its two failure modes, how to recognise them and the 1.5.x
  migration).
- README (incl. a wiki badge), INSTALL, CONFIGURATION and TROUBLESHOOTING link into the wiki;
  the package header now points at it as well.
- `docs/TROUBLESHOOTING.md`: the exact HACS error
  (`<Plugin …> Repository structure for vX.Y.Z is not compliant`) explained — what the category
  prefix and the version in the message mean, why no HACS type fits a package, and how to
  remove the entry (plus why pointing `hacs.json` at the dashboard YAML is not a workaround).

## [1.5.1] - 2026-09-20

**Documentation and CI only.** The package itself is unchanged (the version comment in the
header is the only difference to 1.5.0), so there is nothing to re-copy if you already run
1.5.0.

### Documentation

- README + `docs/INSTALL.md`: a **"Can HACS install this?"** section. HACS has no repository
type for packages — it only knows `integration`, plugin/dashboard, `theme`, `template`,
`python_script` and `appdaemon` — so this repository can never pass the structure check and
the install stays a file copy. HACS is used for the four dashboard cards only.
- Fixed a broken relative link in `docs/INSTALL.md` (`docs/CONFIGURATION.md`, which from
inside `docs/` resolves to `docs/docs/CONFIGURATION.md`).
- GitHub repository topics added (home-assistant, hacs, opendtu, hoymiles, zero-export,
energy-management, ems, victron, shelly, solar, battery) — the only HACS action check that
was failing, and the reason the repository was hard to find.

### Tests

- New guard: every relative link **and** heading anchor in `README.md`, `CHANGELOG.md` and
`docs/` is verified (39 links). It found the broken link above.
- New guard: the version in the package header must have a `## [x.y.z]` section in this
changelog, so a release can no longer be tagged without its entry.

## [1.5.0] - 2026-09-20

### Fixed — the battery was not charged at full power

The target used to be cut whenever the grid exported ("drop the charge term while
exporting"). Any export - the Victron ramp, a load switching off, the ~1 s lag between the
PV and the grid measurement - therefore reduced the array to `house load + the charge power it
was already taking`. The charge power could never grow, and with a slow Victron ramp the loop
kept cutting the very surplus the battery was about to absorb. The SoC taper made it worse at
the top of the charge: from 90 % SoC it reduced the offer linearly and at 99 % it cut it to
zero, so with a Seplos that reports 99 % during the CV phase the array dropped to the house
load and the battery was never finished.

Both are gone. The target is now purely feed forward — `house load + allowed charge power +
bias`, i.e. `solar + grid + (allowance − battery power) + bias` — and **the measured export
never appears in it**. The array is only reduced when the battery really cannot use the power,
and that is measured, not assumed.

### Added

* **Charge acceptance learning** (`input_number.ems_charge_allowance`): if the grid exports
  more than `EMS export tolerance` for longer than `EMS export grace` while the battery takes
  measurably less than it is offered, the offer is cut to what the battery is really taking (at
  most by half per step). It is reset to `EMS max charge power` on every discharge and probed
  upwards again (×1.5) after `EMS charge re-probe` without an export, so a battery that frees
  up is charged at full power again by itself. New helpers: `ems_charge_allowance`,
  `ems_export_tolerance`, `ems_export_grace`, `ems_export_ticks`, `ems_reprobe_seconds`.
* `input_number.ems_soc_stop` (**default 100 %**): the only remaining SoC influence. It stops
  the charge offer at that SoC **and only while the battery is measurably idle**, so a wrong or
  stuck SoC can no longer cut the array.
* New attributes on `sensor.ems_limit_target`: `allowance` (W the battery may take) and
  `charge_push` (W of the target meant for charging).
* The control loop now also runs at night — no writes, but that is when the battery
  discharges and the charge estimate is reset.
* Watchdog: the stale check also requires the mode to have been stable for the timeout, so the
  first run after the NIGHT → FULL transition cannot produce a spurious fail-safe alarm.
* Dashboard: a charge-offer chip plus the learning entities in the controls, diagnostics and
  source-sensor cards.

### Removed

* `input_number.ems_soc_taper_from` and `input_number.ems_soc_full` (replaced by `ems_soc_stop`
  plus the learning). **Delete them in Settings → Helpers after updating**, they are no longer
  used — a leftover `soc_taper_from = 90` would not just be dead, it would suggest a behaviour
  that no longer exists.

### Tests / CI

* 30 control scenarios (6 new: battery-first while exporting, battery at its allowance,
  allowance-capped offer, discharging battery, SoC stop idle vs. charging).
* 31 new learning checks: grace ticks, tick counting/capping, trim criteria and step size,
  discharge reset, upward probe conditions and the night standby stop.
* The suite now resolves the whole sensor chain for the learning cases and passes automation
  variables into the render context like Home Assistant does.

## [1.4.0] - 2026-09-20

### Added

- **Dashboard**: `dashboards/ems-overview.yaml` — a ready-made Lovelace view with the live energy
  flow (Power Flow Card Plus), status chips for the EMS and Victron operation modes (Mushroom),
  PV / house / grid / battery trends with the EMS limit on a second axis (ApexCharts Card), the
  battery SoC graph (Mini Graph Card), the manual controls and the diagnostics.
  `docs/DASHBOARD.md` explains which HACS cards are used and why, how to install them and how to
  adapt the two `EDIT` markers (per-inverter sensors, Victron charge stage).
- `sensor.ems_house_load` — house consumption derived from the energy balance
  (`solar + grid - battery`), used by the flow card's home circle and handy as a sanity check.

### Fixed

- Shortened the automation **aliases** (`OpenDTU EMS loop`, `... watchdog`, `... boot`) so the
  entity ids derived from them are the ones the documentation refers to. A YAML automation gets its
  entity id from the slugified **alias**, not from the `id:` key — the previous longer aliases
  produced entity ids ending in `_control_loop` / `_watchdog_fail_safe` / `_startup_marker`, which
  did not match the docs.
- CI now fails when a documented `automation.<id>` does not match a slug of the configured aliases,
  when the dashboard references an entity the package does not create, or when the dashboard uses an
  undocumented custom card.

### Documentation

- `docs/DASHBOARD.md` (new) plus README links; entity tables updated (7 EMS entities, 17 helpers,
  3 automations).

## [1.3.1] - 2026-09-20

Documentation and CI only — the package logic is unchanged from 1.3.0.

### Documentation

- INSTALL, README and TROUBLESHOOTING now show the two valid ways of enabling packages and warn
  about the two failure modes that produce
  `Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.` — the package file
  being used *as* the packages mapping (`packages: !include <this file>` without a name), and
  `!include_dir_merge_named` (merges the keys inside the files instead of using the file names).

### Added

- `tests/validate_package.py` asserts that every top level key of the package is a config domain,
  which catches that class of mistake before it reaches Home Assistant.

## [1.3.0] - 2026-09-20

### Added

- **`STARTING` mode**: after every Home Assistant start nothing is written for
  `input_number.ems_start_grace` seconds (default 120). This waits for the first sensor values
  and for the ESS to boot, instead of acting on half-initialised data. Recorded by the new
  `automation.opendtu_ems_boot` in the new helper `input_datetime.ems_started_at`.
- **`NIGHT` mode**: sun below the horizon and less than 200 W PV means the solar-powered
  inverters are asleep. The loop writes nothing, raises no notification, and
  `binary_sensor.ems_degraded` stays off. Starting Home Assistant at night therefore no longer
  produces a false `DTU_BLIND` alarm, and the loop takes over by itself at sunrise.
- `input_number.ems_start_grace` helper.
- TROUBLESHOOTING section *Mode is NIGHT or STARTING*.

### Changed

- In standalone mode (`STARTING` / `NIGHT` / `DTU_BLIND`) the loop's write condition and the
  watchdog's stale check stay quiet, because not writing is the correct behaviour then.
- README: standby states documented in the mode table and the day-to-day section.

## [1.2.0] - 2026-09-20

### Added

- **`DTU_BLIND` mode**: when no `number.*_limit_nonpersistent_relative` entity is readable
  (OpenDTU powered off, MQTT broker down, entity ids changed) the control loop stops writing
  instead of producing error logs, and the watchdog raises a persistent notification
  *OpenDTU EMS - no inverter reachable*. Everything resumes automatically once an inverter is
  reachable again. The mode is checked before the measurement checks, so a switched-off DTU is
  diagnosed as `DTU_BLIND` and not as a missing grid meter.
- README section *Day-to-day use* (what to watch, what to touch, when the system reports itself).
- TROUBLESHOOTING section *The EMS entities do not appear at all* (package/include checklist)
  and *Mode is DTU_BLIND*.

### Changed

- `GRID_BLIND` is now also entered when the solar sensor is unreadable while inverters are
  reachable (the house load cannot be computed then) — previously that was reported as a
  battery problem.
- `sensor.ems_pv_delivery` reports 0 % instead of a healthy 100 % when no inverter is
  reachable, and the *PV capacity short* notification no longer fires for that case (it is
  covered by the new DTU notification).
- The stale-loop alarm of the watchdog is suppressed while the mode is `DTU_BLIND`, because
  not writing is the correct behaviour then.

## [1.1.0] - 2026-09-19

### Added

- **PV delivery check** (`sensor.ems_pv_delivery`): compares the commanded output
  (percentage x reachable capacity) with what is actually produced, so an inverter that is
  still "available" but delivers nothing gets noticed. The watchdog raises a
  *PV under-delivering* notification when the ratio stays below 70 % and more than 800 W
  short for three consecutive runs (~6 minutes), so a passing cloud does not raise it.
  The counter resets when the output recovers, i.e. the notification is raised once per
  episode.
- **Persistent counter** helper `input_number.ems_delivery_short` for the above.
- Documentation set: `docs/INSTALL.md`, `docs/CONFIGURATION.md`,
  `docs/TROUBLESHOOTING.md`.
- CI: `tests/validate_package.py` plus a GitHub Actions workflow that parses the YAML and
  every Jinja template, and renders the documented behaviour scenarios.

### Changed

- Watchdog now performs three independent checks: stale loop, capacity shortfall and
  sustained under-delivery.

## [1.0.0] - 2026-09-19

First release: replacement for a 20 s polling automation that could force a grid export.

### Added

- Control loop with the target `solar + grid + (charge_limit - battery_power) + bias`,
  equivalent to `load + charge_limit + bias`, i.e. the battery gets every watt the house
  load leaves over.
- **No charge push while exporting** (`grid < -30 W`): fixes the runaway export of the
  original script when the battery could not absorb the extra PV.
- **Signed battery power**: discharging increases the target instead of breaking it.
- **Relative (percentage) inverter limits** for a mixed 1500 W / 2x 1600 W fleet, with the
  capacity summed from the reachable inverters only.
- **Redistribution**: an inverter whose limit entity is `unavailable` is excluded from the
  capacity, so its share goes to the remaining inverters (verified: 2 of 3 active at 0 W
  grid -> 100 %).
- Two grid meters with arbitration: Shelly primary, Victron smart meter as live backup, and
  the more conservative (smaller) value when they disagree by more than *EMS meter
  tolerance*.
- Fail-safe ladder `FULL` / `NO_BATTERY` / `GRID_BLIND` / `OFF` with staleness, plausibility
  and cross-source checks.
- Watchdog on an `input_datetime` heartbeat (300 s) that re-asserts a fail-safe limit and
  notifies; plus a *PV capacity short* notification.
- **Victron ramp handling**: `EMS settle time` after every write, `EMS max step` for
  increases (decreases immediate), 5 s trigger debounce, 15 s heartbeat, and a real export
  (> 500 W) bypassing the settle time.
- 180 s re-assert of the non-persistent limit (guards against the Hoymiles 2.0.4 behaviour).
- Continuous SoC charge taper (90 % -> 99 %) instead of a 1000 W cliff.
- Parallel, error tolerant writes (`continue_on_error`) instead of sequential writes with
  delays, so no half-written state can remain.
- Roughly 99 % fewer limit writes than the original 20 s polling loop.
