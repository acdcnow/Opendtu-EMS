# OpenDTU Zero-Export EMS for Home Assistant

[![Validate package](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml/badge.svg)](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/acdcnow/opendtu-ems)](https://github.com/acdcnow/opendtu-ems/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Wiki](https://img.shields.io/badge/docs-wiki-blue)](https://github.com/acdcnow/opendtu-ems/wiki)

A single-file Home Assistant package that runs a **battery-first, zero-export** energy
management loop for Hoymiles micro-inverters controlled through
[OpenDTU](https://github.com/tbnobody/OpenDTU) (or OpenDTU-OnBattery).

The loop holds the grid at a small import bias (+20 W by default) and gives the battery
every watt it can take but it never exports, not even when a sensor or a micro-inverter
dies.

* one YAML file: helpers, template sensors, two scripts and three automations
* a ready-made dashboard (`dashboards/ems-overview.yaml`) see [docs/DASHBOARD.md](docs/DASHBOARD.md)
* documented in depth in the [wiki](https://github.com/acdcnow/opendtu-ems/wiki): architecture
  concept, software design, workflow diagrams and the archived control law of ≤ 1.4.0
* no custom component needs to be written by you and the EMS stays one YAML file HACS
  delivers that file (see [Install with HACS](#install-with-hacs)) and provides the four
  dashboard cards
* written for **Home Assistant 2026.9+** (modern `triggers` / `conditions` / `actions` syntax)
* 76 Jinja templates, parsed and rendered by CI on every push

---

## Table of contents

- [What it does](#what-it-does)
- [Control law](#control-law)
- [Fail-safe ladder](#fail-safe-ladder)
- [Entities it creates](#entities-it-creates)
- [Requirements](#requirements)
- [Quick install](#quick-install)
- [Install with HACS](#install-with-hacs)
- [Settings: what every value does](#settings-what-every-value-does)
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
| The battery takes less than it is offered | The loop learns the real acceptance (`EMS charge allowance`) after `EMS export grace` and works at that level from then on so the export stops without starving the charge, and it probes upwards again by itself |
| Battery full (SoC `EMS SoC stop charging`, default 100 %) | PV covers the house load only, grid stays at +20 W. The stop counts only while the battery is measurably not charging, so a wrong SoC cannot cut the array |
| One inverter offline | Its capacity share is redistributed to the remaining inverters (up to 100 % each) |
| OpenDTU powered off / unplugged | `DTU_BLIND`: no writes, a notification says why, the loop resumes by itself |
| Night, or Home Assistant just started | `NIGHT` / `STARTING`: nothing is written and nothing alarms until real data arrives and PV is possible |
| Battery data lost | Pure zero export: `PV = house load - 20 W` (no charge push that could cause an export) |
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
target_PV = load + allowed charge power - bias        (bias = 20 W of import)
          = solar + grid + (allowance - battery_power) - bias
```

(`bias` is *subtracted*, so the loop settles at a small grid **import** and not at a small
export. Until 1.6.0 the sign was the other way round.)

leading to the same figure from two directions: `solar + grid` measures the house load
**without a load sensor**, and the energy balance says the house load plus what the battery
can take is exactly what the array may produce.

The **measured export does not appear in the formula**. That is the important part: a
Victron that is still ramping up, a load switching off or a lagging meter used to be read as
"too much PV" and cut the array to the house load which also cut the charge power that the
battery was about to take, so the charge could never grow. Battery first means the array is
only reduced when the battery really cannot use the power, and that is detected by
measurement, not by an export that may be transient:

1. **Charge acceptance learning.** If the grid exports more than `EMS export tolerance`
   (150 W) for longer than `EMS export grace` (60 s) while the battery takes measurably less
   than it is offered, the offer (`EMS charge allowance`) is cut to what the battery is
   really taking at most by half per step, so one bad reading cannot stop the charge. The
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
| `FULL` | all sensors plausible and fresh | `load + charge_limit - bias` |
| `STARTING` | less than *EMS start grace* (default 120 s) since Home Assistant started | nothing waiting for the first sensor values and for the ESS |
| `NIGHT` | sun below the horizon and less than 200 W PV | nothing the inverters are asleep, this is not a fault |
| `DTU_BLIND` | no inverter limit entity is readable (OpenDTU off, MQTT down, ids changed) | nothing is written, `no inverter reachable` notification |
| `NO_BATTERY` | SoC / battery power missing, stale, implausible or contradictory, or the test switch is on | `load - bias` zero export only |
| `GRID_BLIND` | no usable grid reading, or no solar reading to compute the house load | fail-safe limit (default 0 %) export impossible |
| `OFF` | kill switch off | no writes |

Additionally:

* **watchdog** no limit written for 300 s → notification + fail-safe write (the write also
  refreshes the heartbeat, so the alarm is not repeated)
* **no inverter reachable** OpenDTU off / MQTT down → nothing is written and the watchdog says so
* **PV capacity short** fewer than 3 inverters reachable, they already run at 100 % and the
  grid still imports
* **PV under-delivering** commanded output stays below 70 % and more than 800 W short for
  ~6 minutes (a passing cloud does not raise it)

## Entities it creates

| Entity | Purpose |
|---|---|
| `sensor.ems_grid_power` | resolved grid power, attributes `source` (`shelly`/`victron`/`disagree`/`none`), `shelly`, `victron` |
| `sensor.ems_mode` | `FULL`, `STARTING`, `NIGHT`, `DTU_BLIND`, `GRID_BLIND`, `NO_BATTERY` or `OFF` |
| `sensor.ems_inverter_capacity` | reachable inverter capacity in W, attributes `active`, `current_pct` |
| `sensor.ems_pv_delivery` | produced vs. commanded output in %, attributes `expected_w`, `actual_w` |
| `sensor.ems_house_load` | house consumption in W, derived from `solar + grid - battery` |
| `sensor.ems_limit_target` | the percentage to write, attributes `mode`, `grid`, `solar`, `active`, `capacity`, `allowance` (W the battery may take), `charge_push` (W asked from the array) |
| `binary_sensor.ems_degraded` | on when the system runs degraded: a non-`FULL` mode, or a grid reading that comes from the backup meter / two meters that disagree (only judged while the mode is `FULL`) |
| `script.ems_apply` | writes one percentage to all governed inverters in parallel |
| `script.ems_set_defaults` | restores the documented defaults of all 16 tuning helpers |
| `automation.opendtu_ems_loop` | the control loop |
| `automation.opendtu_ems_watchdog` | fail-safe + capacity/delivery monitoring |
| `automation.opendtu_ems_boot` | records the start time, so the loop stays `STARTING` after a restart |

Plus 21 helpers (3 switches, 16 numbers, 2 date/times) see
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

**Option A - HACS (recommended):** add this repository to HACS as an **Integration**, install
it, then add *OpenDTU Zero-Export EMS* under Settings → Devices & services. It writes
`packages/opendtu_ems.yaml` and the dashboard view into your config folder. Restart when asked.
See [Install with HACS](#install-with-hacs).

**Option B - manual copy:**

1. Copy `packages/opendtu_ems.yaml` into your Home Assistant `<config>/packages/` folder.
2. Enable packages in `configuration.yaml` **one of these two forms**:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   ```yaml
   homeassistant:
     packages:
       opendtu_ems: !include packages/opendtu_ems.yaml
   ```

   (A bare `packages: !include packages/opendtu_ems.yaml` does **not** work it produces
   `Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.`)

3. Restart Home Assistant and **disable the automation this package replaces**.
4. Check `sensor.ems_mode`: it should read `FULL` while the sun is up.
5. Set a **low persistent limit** on every inverter in the OpenDTU web UI (hardware backstop).

Full walkthrough with verification and fail-safe tests: [docs/INSTALL.md](docs/INSTALL.md).

## Install with HACS

This repository is a **HACS integration** (`custom_components/opendtu_ems/`). The integration is
deliberately small the EMS stays one YAML package but it is what makes HACS work: it ships
that package (and the ready-made dashboard view) inside itself and installs it for you.

1. HACS → ⋮ (top right) → **Custom repositories**
2. Repository: `https://github.com/acdcnow/opendtu-ems` · Type: **Integration** → *Add*
3. Search *OpenDTU Zero-Export EMS* in HACS → **Download** (mind that HACS downloads the latest
   **release**, so pick the version you want)
4. **Restart Home Assistant** (a custom integration is only loaded at start-up)
5. Settings → Devices & services → *Add integration* → **OpenDTU Zero-Export EMS**
   → confirm. The integration writes:

   | File | Content |
   |---|---|
   | `<config>/packages/opendtu_ems.yaml` | the EMS package |
   | `<config>/opendtu_ems/ems-overview.yaml` | the Lovelace view to paste into a dashboard |

   Existing files are **never replaced by setup**: the package is meant to be edited (section 1
   holds your entity ids), so only missing files are created. Is a newer package bundled, you get
   a notification and apply it yourself with the action `opendtu_ems.install_bundle`, which keeps
   the current file as `.bak`. The result is shown as a notification and in `sensor.ems_bundle`
   (installed version, action, `restart_required`, `update_available`).
6. If the notification says that `packages:` is missing, add it once to `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

7. **Restart** again the entities appear (`sensor.ems_mode` = `FULL` while the sun is up).

After a HACS update the new version is downloaded but not applied: run the action
`opendtu_ems.install_bundle` (Developer tools → Actions) or re-add the integration, then restart.
The action replaces the installed package: compare it with your own version first if you edited
section 1; the previous file stays as `.bak`.

Installing *without* HACS is supported and identical in effect copy `packages/opendtu_ems.yaml`
and, if you want, `dashboards/ems-overview.yaml` by hand.

### HACS for the dashboard cards

The four cards the dashboard uses are separate HACS downloads (type **Dashboard**):

| Card | Repository | Type |
|---|---|---|
| Power Flow Card Plus | `flixlix/power-flow-card-plus` | Dashboard |
| Mushroom | `piitaya/lovelace-mushroom` | Dashboard |
| ApexCharts Card | `RomRider/apexcharts-card` | Dashboard |
| Mini Graph Card | `kalkih/mini-graph-card` | Dashboard |

Search the name in HACS, Download, then paste the view see
[docs/DASHBOARD.md](docs/DASHBOARD.md#1-install-the-cards) for the details.

> Adding this repository with the type **Dashboard** (frontend/`plugin`) still fails with
> *Repository structure … is not compliant*: a plugin must be a JavaScript file, and this is not
> one. Use **Integration** or install by hand
> ([TROUBLESHOOTING](docs/TROUBLESHOOTING.md#hacs-repository-structure-is-not-compliant)).

## Settings: what every value does

The loop is tuned by 21 helpers (Settings → Devices & services → **Helpers**, search *EMS*).
This is the whole configuration surface: apart from the entity ids in section 1 of the package
nothing else has to be edited by hand.

Nothing in the tables below is compulsory: the values shown are what the reference installation
runs on, and every scenario in the test suite is checked against them. Raise or lower one value
at a time and watch `sensor.ems_limit_target` (attributes `allowance` and `charge_push`) plus
`sensor.ems_grid_power`.

### How the number is calculated

```
allowance  = min(EMS max charge power, EMS charge allowance)
house load = solar + grid - battery power           (measured, no load sensor needed)
target W   = house load + max(allowance, battery power) - EMS grid bias
limit %    = target W / reachable inverter capacity x 100
```

Three consequences worth internalising:

* the array is **never** allowed to produce more than `house load + allowance - bias`, no matter
  how much sun there is. Everything above that is curtailed. That is the zero-export promise,
  not a fault;
* if the battery takes **more** than the allowance (DVCC opened up, or the allowance was learned
  down earlier), the array follows the battery: `max(allowance, battery power)`;
* if the battery **discharges**, the discharge counts as load, so the array covers it too.

### Switches

| Helper | Default | What it does | If you change it |
|---|---|---|---|
| `input_boolean.ems_enabled` | on | Master switch. | **off**: the mode becomes `OFF` and nothing is written at all, neither limits nor fail-safe writes. The inverters keep their last limit until the DTU or the inverter reboots, then fall back to their persistent limit. |
| `input_boolean.ems_simulate_battery_loss` | off | Test switch for the fail-safe path: while it is on, the mode is forced to `NO_BATTERY`. | **on**: the array drops to `house load - bias`. Use it to prove that the loop degrades instead of exporting. |
| `input_boolean.ems_verbose` | off | Writes one debug line per run (mode, grid with its source, solar, SoC, battery, inverters, capacity, written limit). | **on**: add the `logger` entry from [docs/INSTALL.md](docs/INSTALL.md#6-verify-the-first-runs) to see it. Turn it off again afterwards, it is one line per 15 s. |

### The charge power: how much of the array may run

| Helper | Range (step) | Default | What it does | If you change it |
|---|---|---|---|---|
| `input_number.ems_max_charge_power` | 0…6000 (100) | 2500 W | The most charge power the array may be asked for: `min(DVCC max charge current, BMS CCL) x battery voltage`. Together with the house load this decides how much PV is used at all. | **Higher**: the array may produce more, so less sun is thrown away, but only the battery and the BMS decide whether it is really taken, and the allowance learning cuts it back if not. **Lower**: more curtailment. **0**: the loop never asks for charge power (zero export only, the battery is never charged from the array). |
| `input_number.ems_charge_allowance` | 0…6000 (50) | 2500 W | **Written by the loop.** The charge power the battery has been *observed* to accept. The effective offer is `min(EMS max charge power, this)`; the loop cuts it when a lasting export proves the battery cannot use the offer, resets it whenever the battery discharges, and probes it upwards when the grid has been quiet. | You can set it by hand to cap charging without touching the maximum, but it is the *second* cap: the smaller of the two always wins. If it sits permanently below the maximum, the battery or the BMS is the bottleneck (CV phase, cold pack, CCL), not the EMS. |
| `input_number.ems_soc_stop` | 80…100 (1) | 100 % | At or above this SoC the charge push is dropped and the array covers the house load only. It counts **only while the battery is measurably not charging** (`battery power < EMS export tolerance`), so a stuck or badly calibrated SoC can never cut the array. | **Lower** (e.g. 95): stop *asking* for charge earlier, but only once the battery has actually stopped taking current, so the array keeps running while it charges. `100`: never stop, the BMS and the ESS decide. |
| `input_number.ems_export_tolerance` | 0…1000 (10) | 150 W | An export up to this many watts is ignored: meter noise, the Victron ramp and the upward probe all live in this band. | **Higher**: more patience, fewer allowance cuts, but the grid may export that much for a while. **Never 0**: at 0 every watt of export counts as proof and the allowance is cut on the first tick. |
| `input_number.ems_export_grace` | 0…600 (15) | 60 s | How long an export may last (counted in 15 s loop runs) before it counts as proof that the battery cannot use the offer. | **Higher** (120…180 s) if your ESS or BMS reacts slowly. **Lower**: reacts faster, but cuts on a short ramp that would have passed. |
| `input_number.ems_export_ticks` | 0…99 (1) | 0 | Internal counter of consecutive exporting runs. `0` = quiet; at or above the grace in ticks the allowance is being cut. | Do not edit: a manual change only re-arms or silences the cut. |
| `input_number.ems_reprobe_seconds` | 60…3600 (60) | 900 s | How long the grid has to stay quiet before the allowance is probed upwards again (x1.5, at least +100 W). | **Higher**: a quieter grid, but a battery that freed up is charged at full power later. **Lower**: faster recovery, more small refused probes. |

### The grid, the meters and the fail-safe

| Helper | Range (step) | Default | What it does | If you change it |
|---|---|---|---|---|
| `input_number.ems_grid_bias` | 0…200 (5) | 20 W | The grid target. It is *subtracted* from the target, so the loop aims at this much grid **import** while the array produces that much less. | **Higher**: more safety margin against export if your meter is noisy or has a small offset, at the cost of buying those watts. `0`: the loop sits exactly on the boundary between import and export, where it is most likely to keep switching. |
| `input_number.ems_meter_tolerance` | 0…1000 (10) | 100 W | Allowed difference between the primary (Shelly) and the backup (Victron) meter. Beyond it the **smaller** value (the one showing more export) is used and `source` becomes `disagree`. | **Higher**: more tolerance for small permanent offsets between the two metering points, fewer `disagree` states. **Lower** (or 0): the source flips to `disagree` and `binary_sensor.ems_degraded` turns on for the slightest difference. |
| `input_number.ems_failsafe_pct` | 0…100 (1) | 0 % | Written in `GRID_BLIND` (no usable grid or solar reading) and by the watchdog when the loop stopped writing. | `0`: inverters stopped, export impossible. Raise to 2 % only if your inverters oscillate at 0 %. Higher: the fail-safe itself can export. |

### Reaction speed and writes

| Helper | Range (step) | Default | What it does | If you change it |
|---|---|---|---|---|
| `input_number.ems_hysteresis_pct` | 0…10 (0.5) | 2 % | Minimum change of the limit before a write happens. | **Higher**: fewer writes, coarser regulation. **Lower** (or 0): the loop chases every small deviation and writes much more often. |
| `input_number.ems_settle_seconds` | 0…120 (1) | 12 s | After every write the loop waits this long before it acts again, so it does not chase a Victron that is still ramping. Must stay **below 15 s** (the heartbeat), otherwise corrections only happen on the next heartbeat. | **Higher**: calmer, but corrections are slower. **Lower**: more responsive, more writes. An export above 500 W always bypasses it. |
| `input_number.ems_max_step_pct` | 1…100 (1) | 10 % | Maximum **increase** per write, in percent of the reachable capacity. Decreases are always applied immediately. | **Higher**: the limit reaches its target faster after a load step, with bigger export transients while the ESS catches up. **Lower** (5 %): gentler, slower to converge. |
| `input_number.ems_start_grace` | 0…900 (10) | 120 s | After every Home Assistant start the mode is `STARTING` for this long: nothing is written until the sensors and the ESS are up. | **Higher** if your Victron needs longer than two minutes to come up. `0` removes the protection. |
| `input_number.ems_manual_pct` | -1…100 (1) | -1 | `-1` = automatic. Any value ≥ 0 writes that percentage to all inverters, ignores every sensor and freezes the allowance learning. | `0`: the inverters are switched off, but the loop keeps running and the watchdog stands down. Handy for maintenance. |

### Diagnostics, not tuning

| Helper | Default | What it does | If you change it |
|---|---|---|---|
| `input_number.ems_delivery_short` | 0 | Counter of consecutive watchdog runs in which the inverters deliver much less than commanded. The *PV under-delivering* notification is raised exactly at 3. | Do not edit: a manual change only silences or triggers the notification. |
| `input_datetime.ems_last_apply` | - | Heartbeat, written before every inverter write. Drives the 180 s re-assert and the 300 s watchdog. | Clearing it makes the watchdog think the loop just started. |
| `input_datetime.ems_started_at` | - | Written by the boot automation at every start; drives `STARTING`. Having no value yet is what marks the very first start after the installation. | Clearing it makes the next start apply the documented defaults again. |

### Worked example: 3700 W of array, 738 W house, 2500 W of charge power

Reference fleet (1500 + 1600 + 1600 = 4700 W) with the defaults of the tables above:

```
allowance = min(2500, 2500)  = 2500 W
target    = 738 + 2500 - 20  = 3218 W  = 68.5 % of 4700 W
```

| The battery takes | Limit written | Array produces | Grid | What happens |
|---|---|---|---|---|
| 2500 W (the whole offer) | 3218 W, 68.5 % | 3218 of 3700 W | **+20 W import** | 482 W of sun are curtailed, because the battery cannot take more |
| 1500 W (less than offered) | 3218 W, 68.5 % | 3218 W | **-980 W export** | after `EMS export grace` the allowance is cut to `max(1500, 1250) = 1500 W` |
| 1500 W (after the learning) | 2218 W, 47.2 % | 2218 W | +20 W import | export gone, 1482 W curtailed |

To use the **whole** array in that situation the offer has to reach
`3700 - 738 + 20 = 2982 W`, so both `EMS max charge power` **and** the learned
`EMS charge allowance` must be at least that: set it to `3000` and make sure DVCC allows about
57 A at 52 V. With a 50 A DVCC (about 2600 W) you cannot use 3700 W while the house only takes
738 W. Either curtailing or exporting is unavoidable, and this package always chooses
curtailment. For the full 4700 W fleet the offer would have to be
`4700 - 738 + 20 = 3982 W` (about 76 A).

The SoC is not part of that arithmetic at all: below `EMS SoC stop charging` it has no influence
on the limit, and at or above it the stop only takes effect once the battery has measurably
stopped charging.

### Why the helpers start empty, and what the first start does

The 16 tuning numbers have **no `initial` value**. Home Assistant creates an `input_number`
without `initial` at its *minimum* and only restores a value that already exists (the official
`input_number` documentation: with `initial` it "will start with the state set to that value",
otherwise "it will restore the state it had before Home Assistant stopping"). A helper that was
just created has neither, so it starts at its minimum: `EMS max charge power` 0 W,
`EMS charge allowance` 0 W, `EMS grid bias` 0 W, `EMS start grace` 0 s, `EMS max step` 1 %.
In that state the array only ever covers the house load, which looks exactly like "the sun is
cut although the battery could take it".

Adding `initial` would **not** be the fix: it also overrides the restore, so it would reset your
tuning and the learned charge allowance on *every* Home Assistant restart. Instead:

1. on the **first start** after the installation, `automation.opendtu_ems_boot` sees that
   `input_datetime.ems_started_at` has never been written and runs `script.ems_set_defaults`,
   which writes every value in the tables above;
2. later restarts never touch the helpers again, so your tuning and the learned allowance
   survive;
3. an installation that existed before 1.6.0 keeps whatever it has. If `EMS max charge power` is
   0 W while the sun is up, the boot automation raises a *no charge power configured*
   notification, because that value means the loop never asks the array for charge power. Set it
   by hand, or run `script.ems_set_defaults`;
4. `script.ems_set_defaults` can be run at any time (Developer tools → Actions) to put the whole
   helper set back to the documented defaults.

## Day-to-day use

After the installation there is nothing to do the loop runs by itself. The entities worth
knowing:

| I want to… | Use |
|---|---|
| pause everything immediately | `input_boolean.ems_enabled` → off (no writes at all) |
| test the "battery data lost" path | `input_boolean.ems_simulate_battery_loss` → on |
| write a fixed limit by hand | `input_number.ems_manual_pct` → 0…100 (`-1` = automatic) |
| put every tuning value back to the documented default | run the action `script.ems_set_defaults` |
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
bottleneck (BMS current limit, temperature, CV phase) that is a battery/BMS matter, not an
EMS one. If `EMS export ticks` keeps climbing, the accepted charge power is being cut further
every `EMS export grace`; raise `EMS export tolerance` (meter noise) or `EMS export grace`
(give the Victron more time) if the underlying cause is a ramp rather than the battery.

Two modes are normal and not a fault: `NIGHT` (sun down the inverters are asleep) and
`STARTING` (up to `input_number.ems_start_grace`, default 120 s, after every Home Assistant
start nothing is written until the sensors and the ESS are up). Both end by themselves.

When something is off the system reports it itself: `binary_sensor.ems_degraded` turns on and
one of the notifications appears (`no inverter reachable`, `PV capacity short`,
`PV under-delivering`, `fail-safe active`).

## Why the relative limits

`limit_nonpersistent_relative` is a percentage of each inverter's own rating, so one single
value drives a mixed fleet correctly for example a 1500 W HM and two 1600 W HMS:

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
fails, SoC/voltage thresholds, per-inverter min/max and hysteresis and it keeps running
when Home Assistant is down. Note that the DPL expects **exclusive control** of the governed
inverters, so never run it next to this package.

## Documentation

**Wiki design and background** ([index](https://github.com/acdcnow/opendtu-ems/wiki)):

* [Architecture Concept Document (ACD)](https://github.com/acdcnow/opendtu-ems/wiki/Architecture-Concept-Document) goals, system context, concepts C1–C6, architectural decisions AD-1…AD-12, risks and roadmap
* [Software Design Document (SDD)](https://github.com/acdcnow/opendtu-ems/wiki/Software-Design-Document) entity inventory, exact formulas, learning algorithm, invariants, sequences, test design, traceability
* [Workflow Diagrams](https://github.com/acdcnow/opendtu-ems/wiki/Workflow-Diagrams) the GitDiagram repository map plus mode ladder, arbitration, control cycle, startup and fault flows
* [Control law 1.4.x (archived)](https://github.com/acdcnow/opendtu-ems/wiki/Archive-1.4-Control-Law) the superseded export-feedback design, why it starved the battery, and the migration steps

**In this repository:**

* [docs/INSTALL.md](docs/INSTALL.md) step by step: prerequisites, install, verification, fail-safe tests
* [docs/DASHBOARD.md](docs/DASHBOARD.md) the Lovelace view, the HACS cards used and how to adapt them
* [docs/CONFIGURATION.md](docs/CONFIGURATION.md) every helper, tuning guide, dashboard entities
* [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) symptoms, causes, fixes
* [CHANGELOG.md](CHANGELOG.md)

## Disclaimer

This package controls real hardware and switches power. Nobody but you is responsible for
your installation, your cabling ratings and your grid connection rules. Always keep a low
persistent limit as a hardware backstop and test the fail-safe paths before trusting the
system.

## License

[MIT](LICENSE)
