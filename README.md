# OpenDTU Zero-Export EMS for Home Assistant

[![Validate package](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml/badge.svg)](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/acdcnow/opendtu-ems)](https://github.com/acdcnow/opendtu-ems/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A single-file Home Assistant package that runs a **battery-first, zero-export** energy
management loop for Hoymiles micro-inverters controlled through
[OpenDTU](https://github.com/tbnobody/OpenDTU) (or OpenDTU-OnBattery).

The loop holds the grid at a small import bias (+20 W by default) and gives the battery
every watt it can take — but it never exports, not even when a sensor or a micro-inverter
dies.

* one YAML file: helpers, template sensors, a script and three automations
* a ready-made dashboard (`dashboards/ems-overview.yaml`) — see [docs/DASHBOARD.md](docs/DASHBOARD.md)
* no custom integration, no Node-RED, no AppDaemon — and HACS is only needed for the dashboard cards (see [Can HACS install this?](#can-hacs-install-this))
* written for **Home Assistant 2026.9+** (modern `triggers` / `conditions` / `actions` syntax)
* 73 Jinja templates, parsed and rendered by CI on every push

---

## Table of contents

- [What it does](#what-it-does)
- [Control law](#control-law)
- [Fail-safe ladder](#fail-safe-ladder)
- [Entities it creates](#entities-it-creates)
- [Requirements](#requirements)
- [Quick install](#quick-install)
- [Can HACS install this?](#can-hacs-install-this)
- [Day-to-day use](#day-to-day-use)
- [Why the relative limits](#why-the-relative-limits)
- [Hardware backstop](#hardware-backstop)
- [Alternatives](#alternatives)
- [Documentation](#documentation)
- [License](#license)

---

## What it does

| Situation | Behaviour |
|---|---|
| Battery can take power, sun is available | PV is allowed to reach `house load + allowed charge power`, so every watt the battery can take is offered to it and the grid stays at +20 W. A momentary export (Victron ramp, a load switching off) does **not** cut the array |
| The battery takes less than it is offered | The loop learns the real acceptance (`EMS charge allowance`) after `EMS export grace` and works at that level from then on — so the export stops without starving the charge, and it probes upwards again by itself |
| Battery full (SoC `EMS SoC stop charging`, default 100 %) | PV covers the house load only, grid stays at +20 W. The stop counts only while the battery is measurably not charging, so a wrong SoC cannot cut the array |
| One inverter offline | Its capacity share is redistributed to the remaining inverters (up to 100 % each) |
| OpenDTU powered off / unplugged | `DTU_BLIND`: no writes, a notification says why, the loop resumes by itself |
| Night, or Home Assistant just started | `NIGHT` / `STARTING`: nothing is written and nothing alarms until real data arrives and PV is possible |
| Battery data lost | Pure zero export: `PV = house load + 20 W` (no charge push that could cause an export) |
| Grid meter lost | The second (backup) meter takes over seamlessly; only if **both** are gone the inverters are set to a fail-safe limit |
| Loop stopped / HA restarted | A watchdog re-asserts a safe limit and raises a notification |

## Control law

With `grid` positive = import and `battery power` positive = charging, the energy balance
at the metering point is:

```
grid + solar = load + battery_charge
```

which turns the target into a very simple statement:

```
target_PV = load + allowed charge power + bias (+20 W)
          = solar + grid + (allowance - battery_power) + bias
```

leading to the same figure from two directions: `solar + grid` measures the house load
**without a load sensor**, and the energy balance says the house load plus what the battery
can take is exactly what the array may produce.

The **measured export does not appear in the formula**. That is the important part: a
Victron that is still ramping up, a load switching off or a lagging meter used to be read as
"too much PV" and cut the array to the house load — which also cut the charge power that the
battery was about to take, so the charge could never grow. Battery first means the array is
only reduced when the battery really cannot use the power, and that is detected by
measurement, not by an export that may be transient:

1. **Charge acceptance learning.** If the grid exports more than `EMS export tolerance`
   (150 W) for longer than `EMS export grace` (60 s) while the battery takes measurably less
   than it is offered, the offer (`EMS charge allowance`) is cut to what the battery is
   really taking — at most by half per step, so one bad reading cannot stop the charge. The
   estimate is reset to `EMS max charge power` whenever the battery discharges (a new charge
   cycle), and probed upwards again (×1.5) after `EMS charge re-probe` (15 min) without an
   export. So a battery that frees up is charged at full power again by itself.
2. **Signed battery power.** Discharging must *increase* the target, so the raw signed
   value is used, not a value clamped at zero.
3. **The SoC never throttles the array.** The only SoC effect is the stop above, and it is
   corroborated by the battery power. A stuck or badly calibrated SoC can waste nothing.

The loop reacts to grid crossings (5 s debounce) plus a 15 s heartbeat, writes with a
hysteresis of 2 %, re-asserts the limit every 180 s and, to cope with the Victron ramp,
waits `EMS settle time` after every write and limits increases to `EMS max step` (decreases
are immediate). It also runs at night for the learning (that is when the battery discharges
and the estimate is reset) but writes nothing then.

## Fail-safe ladder

| Mode | When | Action |
|---|---|---|
| `FULL` | all sensors plausible and fresh | `load + charge_limit + bias` |
| `STARTING` | less than *EMS start grace* (default 120 s) since Home Assistant started | nothing — waiting for the first sensor values and for the ESS |
| `NIGHT` | sun below the horizon and less than 200 W PV | nothing — the inverters are asleep, this is not a fault |
| `DTU_BLIND` | no inverter limit entity is readable (OpenDTU off, MQTT down, ids changed) | nothing is written, `no inverter reachable` notification |
| `NO_BATTERY` | SoC / battery power missing, stale, implausible or contradictory, or the test switch is on | `load + bias` — zero export only |
| `GRID_BLIND` | no usable grid reading, or no solar reading to compute the house load | fail-safe limit (default 0 %) — export impossible |
| `OFF` | kill switch off | no writes |

Additionally:

* **watchdog** — no limit written for 300 s → notification + fail-safe write (the write also
  refreshes the heartbeat, so the alarm is not repeated)
* **no inverter reachable** — OpenDTU off / MQTT down → nothing is written and the watchdog says so
* **PV capacity short** — fewer than 3 inverters reachable, they already run at 100 % and the
  grid still imports
* **PV under-delivering** — commanded output stays below 70 % and more than 800 W short for
  ~6 minutes (a passing cloud does not raise it)

## Entities it creates

| Entity | Purpose |
|---|---|
| `sensor.ems_grid_power` | resolved grid power, attributes `source` (`shelly`/`victron`/`disagree`/`none`), `shelly`, `victron` |
| `sensor.ems_mode` | `FULL`, `NO_BATTERY`, `GRID_BLIND` or `OFF` |
| `sensor.ems_inverter_capacity` | reachable inverter capacity in W, attributes `active`, `current_pct` |
| `sensor.ems_pv_delivery` | produced vs. commanded output in %, attributes `expected_w`, `actual_w` |
| `sensor.ems_house_load` | house consumption in W, derived from `solar + grid - battery` |
| `sensor.ems_limit_target` | the percentage to write, attributes `mode`, `grid`, `solar`, `active`, `capacity`, `allowance` (W the battery may take), `charge_push` (W asked from the array) |
| `binary_sensor.ems_degraded` | on whenever the system runs degraded |
| `script.ems_apply` | writes one percentage to all governed inverters in parallel |
| `automation.opendtu_ems_loop` | the control loop |
| `automation.opendtu_ems_watchdog` | fail-safe + capacity/delivery monitoring |
| `automation.opendtu_ems_boot` | records the start time, so the loop stays `STARTING` after a restart |

Plus 21 helpers (3 switches, 16 numbers, 2 date/times) — see
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Requirements

* Home Assistant **2026.9 or newer**
* OpenDTU exposing a `number.<inverter>_limit_nonpersistent_relative` entity per inverter
  (the relative limit reports immediately, the absolute one lags up to ~4 minutes)
* a grid meter (Shelly 3EM Pro in the reference installation) and optionally a second one
  as a live backup (Victron smart meter)
* battery SoC and a **signed** battery power sensor (positive = charging)
* a Victron ESS with DVCC where the charge current limit is configured (50 A in the
  reference installation)
* `packages:` enabled in `configuration.yaml`

## Quick install

1. Copy `packages/opendtu_ems.yaml` into your Home Assistant `<config>/packages/` folder.
2. Enable packages in `configuration.yaml` — **one of these two forms**:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   ```yaml
   homeassistant:
     packages:
       opendtu_ems: !include packages/opendtu_ems.yaml
   ```

   (A bare `packages: !include packages/opendtu_ems.yaml` does **not** work — it produces
   `Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.`)

3. Restart Home Assistant and **disable the automation this package replaces**.
4. Check `sensor.ems_mode`: it should read `FULL` while the sun is up.
5. Set a **low persistent limit** on every inverter in the OpenDTU web UI (hardware backstop).

Full walkthrough with verification and fail-safe tests: [docs/INSTALL.md](docs/INSTALL.md).

## Can HACS install this?

**No — HACS has no repository type for packages**, and this is a package: a YAML file that
Home Assistant itself loads at start-up (`packages:` / `!include_dir_named`). HACS only knows
six types — `integration` (`custom_components/<domain>/manifest.json`), `plugin`/dashboard (a
`.js` file), `theme`, `template` (`.jinja`), `python_script` and `appdaemon` — so there is
nothing for it to copy into place. Adding this repository as a custom repository would end in
*a structure that is not compliant*, whichever type you pick. That is why the install is a
file copy.

HACS is however used **for the dashboard cards** in `dashboards/ems-overview.yaml`:

| Card | Repository | Type |
|---|---|---|
| Power Flow Card Plus | `flixlix/power-flow-card-plus` | Dashboard |
| Mushroom | `piitaya/lovelace-mushroom` | Dashboard |
| ApexCharts Card | `RomRider/apexcharts-card` | Dashboard |
| Mini Graph Card | `kalkih/mini-graph-card` | Dashboard |

Search the name in HACS, Download, then paste the view — see
[docs/DASHBOARD.md](docs/DASHBOARD.md#1-install-the-cards) for the details.

> If you want HACS to manage the EMS itself, that needs a real Python integration in
> `custom_components/` with a `manifest.json`, `config_flow.py` and entities. This repository
> deliberately is not one: a package needs no code, no integration reload and no HACS —
> one file, one restart.

## Day-to-day use

After the installation there is nothing to do — the loop runs by itself. The entities worth
knowing:

| I want to… | Use |
|---|---|
| pause everything immediately | `input_boolean.ems_enabled` → off (no writes at all) |
| test the "battery data lost" path | `input_boolean.ems_simulate_battery_loss` → on |
| write a fixed limit by hand | `input_number.ems_manual_pct` → 0…100 (`-1` = automatic) |
| see what the loop is doing | `sensor.ems_mode`, `sensor.ems_limit_target`, `sensor.ems_pv_delivery` |
| see how much charge power the battery is offered | attribute `allowance` of `sensor.ems_limit_target`, `input_number.ems_charge_allowance` |
| see how much charge power the array is asked for | attribute `charge_push` of `sensor.ems_limit_target` |
| see which meter is used | attribute `source` of `sensor.ems_grid_power` |
| see how many inverters answer | attribute `active` of `sensor.ems_inverter_capacity` |
| see when it last wrote | `input_datetime.ems_last_apply` |
| get a diagnostic line per run | `input_boolean.ems_verbose` plus the `logger` entry from [docs/INSTALL.md](docs/INSTALL.md#6-verify-the-first-runs) |
| check why it did nothing | Settings → Automations → *OpenDTU EMS loop* → ⋮ → Traces |

Healthy readings while the sun is up: mode `FULL`, `source` = `shelly`, `active` = 3,
`EMS PV delivery` near 100 %, `input_number.ems_export_ticks` at 0,
`input_number.ems_charge_allowance` at your `EMS max charge power`,
`sensor.ems_grid_power` a few watts **positive**, and `input_datetime.ems_last_apply` never
older than 3 minutes.

If `EMS charge allowance` sits permanently below `EMS max charge power`, the battery is the
bottleneck (BMS current limit, temperature, CV phase) — that is a battery/BMS matter, not an
EMS one. If `EMS export ticks` keeps climbing, the accepted charge power is being cut further
every `EMS export grace`; raise `EMS export tolerance` (meter noise) or `EMS export grace`
(give the Victron more time) if the underlying cause is a ramp rather than the battery.

Two modes are normal and not a fault: `NIGHT` (sun down — the inverters are asleep) and
`STARTING` (up to `input_number.ems_start_grace`, default 120 s, after every Home Assistant
start — nothing is written until the sensors and the ESS are up). Both end by themselves.

When something is off the system reports it itself: `binary_sensor.ems_degraded` turns on and
one of the notifications appears (`no inverter reachable`, `PV capacity short`,
`PV under-delivering`, `fail-safe active`).

## Why the relative limits

`limit_nonpersistent_relative` is a percentage of each inverter's own rating, so one single
value drives a mixed fleet correctly — for example a 1500 W HM and two 1600 W HMS:

* no wrong `target / 3` arithmetic
* a 1500 W unit never receives a value above its rating
* no absolute value below the stable minimum (roughly `inputs × 12 W`)
* updates are reported immediately, whereas `limit_nonpersistent_absolute` may take up to
  four minutes to show up (OpenDTU documentation)

## Hardware backstop

Software cannot protect you from a dead DTU or a rebooted inverter. Set a **low persistent
limit** on every inverter in the OpenDTU web UI: that is the value an inverter falls back to
whenever no non-persistent limit is in force.

Known issue: Hoymiles firmware **2.0.4** reports 100 % after ~4 minutes without a limit
update. Avoid that version, 1.1.12 is the recommended one. The 180 s re-assert in the
control loop exists for exactly this failure mode.

## Alternatives

If your DTU has enough flash (8 MB or more, or a board you are willing to re-flash once),
[OpenDTU-OnBattery](https://github.com/hoylabs/OpenDTU-OnBattery) implements the same idea in
firmware as the *Dynamic Power Limiter*: target grid consumption, base load when the meter
fails, SoC/voltage thresholds, per-inverter min/max and hysteresis — and it keeps running
when Home Assistant is down. Note that the DPL expects **exclusive control** of the governed
inverters, so never run it next to this package.

## Documentation

* [docs/INSTALL.md](docs/INSTALL.md) — step by step: prerequisites, install, verification, fail-safe tests
* [docs/DASHBOARD.md](docs/DASHBOARD.md) — the Lovelace view, the HACS cards used and how to adapt them
* [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every helper, tuning guide, dashboard entities
* [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — symptoms, causes, fixes
* [CHANGELOG.md](CHANGELOG.md)

## Disclaimer

This package controls real hardware and switches power. Nobody but you is responsible for
your installation, your cabling ratings and your grid connection rules. Always keep a low
persistent limit as a hardware backstop and test the fail-safe paths before trusting the
system.

## License

[MIT](LICENSE)
