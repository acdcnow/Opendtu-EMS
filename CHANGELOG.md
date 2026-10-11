# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Only the **current release line** is documented here. The notes of the superseded releases
(1.8.0 back to 1.0.0) moved to the wiki, where they are kept unchanged:
**[Changelog archive (1.8.0 and older)](https://github.com/acdcnow/opendtu-ems/wiki/Changelog-Archive)**.

## [Unreleased]

### Documentation

- **The licence statement was corrected to GPL-3.0.** `LICENSE` has always carried the GNU
  General Public License v3.0, while `README.md` (badge and licence section), `info.md` and the
  wiki still said *MIT*. All of them now say **GPL-3.0**.

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
