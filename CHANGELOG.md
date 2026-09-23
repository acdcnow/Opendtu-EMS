# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-09-23

### Added

- `script.ems_set_defaults`: the documented defaults of all 16 tuning helpers in one place,
  callable from Developer tools → Actions at any time.

### Fixed

- **The grid bias was applied with the wrong sign.** The target was
  `solar + grid + push + bias`, so the loop settled at `-(push + bias)`: a permanent
  **export** of about `EMS grid bias` watts, the opposite of what the README, the fail-safe
  table and the helper description promise (“the grid stays at +20 W”). Raising the bias made
  that export bigger instead of safer. The bias is now **subtracted**, so the steady state is a
  small grid **import** of `EMS grid bias` watts:
  `PV = house load + allowed charge power - bias`. `NO_BATTERY` produces `house load - bias`,
  the export triggers sit `2 x bias` further away, and nothing else changes: the charge
  allowance learning, the tolerance band and the fail-safe ladder work as before.
- **A fresh installation ran with empty helpers.** Home Assistant creates an `input_number`
  that has no `initial` value at its **minimum** and only restores a value that already exists,
  so every helper started at its floor: `EMS max charge power` 0 W, `EMS charge allowance`
  0 W, `EMS grid bias` 0 W, `EMS start grace` 0 s, `EMS max step` 1 %. The array then only
  ever covered the house load — the “the sun is cut although the battery could take it”
  symptom, on a brand new installation. `automation.opendtu_ems_boot` now calls the new
  `script.ems_set_defaults` once, on the first start after the install (`ems_started_at` is
  still empty then). `initial` was deliberately **not** used: it overrides the restore and
  would reset the user's tuning *and* the learned allowance on every restart. Installations
  that were created before 1.6.0 and never set by hand get a persistent notification while
  `EMS max charge power` is 0 W and the sun is up.
- **`binary_sensor.ems_degraded` alarmed in a standby state.** The “which meter is in use”
  clause was evaluated in every mode, so both meters going stale at night (`source: none`
  while the mode is `NIGHT`) raised a problem alarm — contradicting NOTES §K and the v1.3.0
  changelog, which both promise that the standby states stay silent. The clause is now only
  judged while the loop is really regulating (`FULL`).

### Documentation

- `README.md`: new section **Settings: what every value does** — the control law in one
  formula, every helper with its range, its default, what it does and what changes when you
  raise or lower it, a worked example (3700 W array / 738 W house / 2500 W charge power) and
  the reason the helpers are created empty. The mode list of `sensor.ems_mode`, the entity
  table and the fail-safe table were corrected at the same time.
- `docs/CONFIGURATION.md`: the mode table, the design-decision formula and the
  `binary_sensor.ems_degraded` description corrected; the helper tables now state where the
  defaults come from.

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
- `docs/TROUBLESHOOTING.md` + `docs/DASHBOARD.md`: the frontend message
  `Entity not available: sensor.ems_…` explained. It always means the id is absent from the state
  machine — the ApexCharts card reports it per series it cannot resolve — with the four causes
  (a second definition of the same id or `unique_id`, a registry rename or a disabled entity, a
  package older than the view, a failed template entity) and the fix.

### Tests

- New guard: every entity id mentioned in `README.md` and `docs/*.md` must be created by the
  package — the dashboard was already checked, the prose was not. `CHANGELOG.md` is excluded on
  purpose because it documents removed entities.

## [1.5.2] - 2026-09-21

**HACS can now install this project.** The package itself is unchanged (1.5.1 is what the
integration ships) — if you already run 1.5.1 by copying the file, there is nothing to update.

### Added

- `custom_components/opendtu_ems/` — a HACS **integration** that delivers the package. Add the
  repository to HACS with the type *Integration*, install it, add *OpenDTU Zero-Export EMS* and
  it writes `<config>/packages/opendtu_ems.yaml` plus `<config>/opendtu_ems/ems-overview.yaml`
  (the dashboard view) into the config folder. The EMS itself stays the one YAML file it was.
  - safe update rules: setup only **creates** files - it never replaces an existing package, so
    the entity ids a user edited in section 1 survive. A newer bundled version is reported in the
    notification and on `sensor.ems_bundle`, and applied explicitly with the action
    `opendtu_ems.install_bundle`, which keeps the current file as `.bak`,
  - result as a persistent notification and in `sensor.ems_bundle` (installed version, action,
    `restart_required`), plus the action `opendtu_ems.install_bundle` for updates,
  - a separate notification when `configuration.yaml` has no `packages:` key, naming the two
    lines that are missing,
  - brand images (`brand/icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`) and `hacs.json`,
    both required by HACS for the integration category.

### Documentation

- README: *Quick install* now lists both paths and *Can HACS install this?* (which said "no")
  became **Install with HACS** with the exact HACS steps.
- `docs/INSTALL.md`: new *2.1 With HACS*, the manual copy moved to *2.2 By hand*.
- `docs/TROUBLESHOOTING.md`: the `Repository structure … is not compliant` section rewritten —
  the category has to be **Integration**, and a stale release (before 1.5.2) is the second cause.

### Tests

- New `tests/validate_integration.py` (runs in CI next to the package suite): manifest keys and
  hassfest key order, `hacs.json` keys, integration structure, brand image sizes, translation
  parity, and the install rules against a temporary config folder (fresh install, identical file,
  older file + backup, newer file untouched, locally edited file untouched, `force`, missing
  bundle). It reads the version with the same code the integration uses, and fails when the
  bundled YAML drifts away from `packages/opendtu_ems.yaml`.

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
