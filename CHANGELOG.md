# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- INSTALL, README and TROUBLESHOOTING now show the two valid ways of enabling packages and warn
  about the two failure modes that produce
  `Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.` — the package file
  being used *as* the packages mapping (`packages: !include <this file>` without a name), and
  `!include_dir_merge_named` (merges the keys inside the files instead of using the file names).

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
