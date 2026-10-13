# OpenDTU Zero-Export EMS for Home Assistant

[![Validate](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml/badge.svg)](https://github.com/acdcnow/opendtu-ems/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-Integration-blue.svg)](https://hacs.xyz)
[![Wiki](https://img.shields.io/badge/docs-wiki-blue)](https://github.com/acdcnow/opendtu-ems/wiki)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

**Release 1.10.0** · Home Assistant **2026.10.1+** · one YAML package · no custom component to write

A **battery-first, zero-export** energy management loop for Hoymiles micro-inverters driven by
[OpenDTU](https://github.com/tbnobody/OpenDTU) (OpenDTU-OnBattery works too), next to a Victron ESS
and a Seplos battery.

The EMS is **one file**: `packages/opendtu_ems.yaml`. It creates its own helpers, sensors, scripts
and automations, computes one percentage for all inverters from the wattage the battery can still
take, learns the battery's real charge acceptance by itself and fails soft when a sensor
disappears. The HACS integration only installs and updates that file (plus two dashboards and a
blueprint).

---

## The four rules behind it

1. **Battery first.** The array may produce everything the *house load plus the battery charge
   power* needs — never "everything the sun gives".
2. **Never export.** The loop aims at a small grid **import** (`EMS grid bias`, +20 W by default),
   so the export boundary is never touched. A second grid meter can take over seamlessly.
3. **Learn, don't guess.** The array is only ever cut when a *lasting* export proves that the
   battery cannot take what it is offered — and only down to what the battery is measurably
   taking. An ESS that is still ramping is not proof of anything.
4. **Fail soft.** No battery data → pure zero export. No grid data → a low fixed limit. No
   inverter → nothing is written and you are told. A watchdog re-asserts the fail-safe limit if
   the loop ever stops.

## What 1.10.0 changes

| | |
| :--- | :--- |
| **The sensor mapping** | The package contains **no foreign entity id** any more: 15 `input_text` helpers hold them, and a shipped blueprint asks for them. A renamed sensor is one field instead of ~60 places. |
| **The day-start open phase** | At sunrise the array is held at **100 %** until there is something to throttle (the battery at its calculated maximum, PV at full production, or a lasting export). The morning is no longer capped at "house load + charge need" while the pack still has headroom. Set `EMS open until solar` = 0 to disable it. |
| **Two diagnostic flags** | `binary_sensor.grid_export_throttling_required` and `binary_sensor.high_consumption_ac_mode` moved from a hand-made `template:` block into the package, with unchanged entity ids. **Delete your own copies.** Neither is read by the control law. |
| **An optional house-load mapping** | Map your own consumption sensor and `sensor.ems_house_load` uses it instead of `solar + grid − battery` (display and diagnostics only). |
| **Three bugs fixed** | Every inverter write was silently blocked by a template condition; `sensor.ems_map_status` always reported `ok`; the mapping mirrors rendered a string where a number is required. All three made the loop *look* fine while doing nothing. |

Full list, with the migration steps: [CHANGELOG.md](CHANGELOG.md) ·
[Upgrading](https://github.com/acdcnow/opendtu-ems/wiki/Upgrading).

---

## Table of contents

* [Requirements](#requirements) · [Install](#install) · [The sensor mapping](#the-sensor-mapping)
* [How it works](#how-it-works) · [The fail-safe ladder](#the-fail-safe-ladder)
* [Settings: what every value does](#settings-what-every-value-does) · [Day-to-day use](#day-to-day-use)
* [Tests](#tests) · [Files](#files) · [Hardware backstop](#hardware-backstop)
* [Documentation](#documentation) · [License](#license)

---

## Requirements

| | |
| :--- | :--- |
| Home Assistant | **2026.10.1 or newer**, with `packages:` enabled |
| Inverters | one `number.<inverter>_limit_nonpersistent_relative` entity per micro-inverter |
| Grid meter | anything publishing watts, **positive = import** (a Shelly 3EM Pro is the reference). A second meter can act as a live backup |
| Battery | SoC **and** a *signed* power sensor (**positive = charging**) — a Seplos BMS, plus the Victron DC bus pair for the finer charge power |
| OpenDTU | 1.1.12 recommended. **Avoid Hoymiles firmware 2.0.4** — it forgets non-persistent limits after ~4 minutes. The EMS re-asserts every 180 s, which papers over it |

## Install

### With HACS (recommended)

1. HACS → ⋮ (top right) → **Custom repositories** →
   `https://github.com/acdcnow/opendtu-ems`, type **Integration** → *Add*
2. Search **OpenDTU Zero-Export EMS** → **Download** → **restart** Home Assistant
3. Settings → Devices & services → *Add integration* → **OpenDTU Zero-Export EMS** → confirm.
   It installs `packages/opendtu_ems.yaml`, both dashboards and the mapping blueprint.
4. Add the `packages:` key to `configuration.yaml` (once) and restart:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   If a `homeassistant:` block already exists, **merge** the key into it — a second block is not
   allowed.
5. Run the blueprint **OpenDTU EMS - the sensor names** (see below) or fill the helpers by hand.
6. Set a **low persistent limit** on every inverter in the OpenDTU web UI — see
   [Hardware backstop](#hardware-backstop).

### Manually

Copy `packages/opendtu_ems.yaml` to `<config>/packages/`, the two files from `dashboards/` to
`<config>/opendtu_ems/`, and `blueprints/script/opendtu_ems/ems_map_sensors.yaml` to
`<config>/blueprints/script/opendtu_ems/`, then restart.

Updating: HACS downloads the version, the action **`opendtu_ems.install_bundle`** applies it (or
re-add the integration), then restart. A file you edited is never overwritten — it is kept as
`.bak`. Your sensor mapping survives every update, because it lives in `input_text` entities, not
in the file that gets replaced.

## The sensor mapping

**The package contains no foreign entity id.** Section 1 declares 15 `input_text` helpers, and
every template, trigger, script and dashboard reads the ids from there — so a renamed sensor is
**one field**, not ~60 occurrences spread over two files.

| Helper | Required | What it must be |
| :--- | :---: | :--- |
| `input_text.ems_src_grid` | ✔ | grid meter, **positive = import** |
| `input_text.ems_src_grid_backup` | – | a second meter on the **same** metering point, same sign |
| `input_text.ems_src_solar` | ✔ | PV power, all inverters summed |
| `input_text.ems_src_house_load` | – | your own house-consumption sensor (display only) |
| `input_text.ems_src_batt_soc` | ✔ | battery state of charge, % |
| `input_text.ems_src_batt_power` | ✔ | battery power, **signed — positive = charging** |
| `input_text.ems_src_batt_voltage` | – | battery / DC bus voltage, V |
| `input_text.ems_src_batt_current` | – | battery current, **signed — positive = charging** |
| `input_text.ems_src_inv1_limit` … `ems_src_inv3_limit` | ✔ | the three `number.*_limit_nonpersistent_relative` entities |
| `input_text.ems_src_inv1_power` … `ems_src_inv3_power` | – | per-inverter AC power (dashboards only) |
| `input_text.ems_src_victron_state` | – | Victron charge stage, e.g. `Bulk` (display only) |

Fill it with the shipped script blueprint
`blueprints/script/opendtu_ems/ems_map_sensors.yaml`
(Settings → Automations & scenes → **Blueprints** → *OpenDTU EMS - the sensor names* →
*Create script* → run it once), or by hand in Settings → Devices & services → **Helpers**.

`sensor.ems_map_status` reads **`ok`** when every required entry is filled, otherwise
*"N required source(s) missing"*, with `required_missing` and `optional_empty` naming the gaps.
An incomplete mapping is the one failure that would otherwise only show up as a permanently
degraded mode — both dashboards start with a card that says so, and
`automation.opendtu_ems_boot` notifies you at every start until it is complete.

A **wrong** id (not an empty one) shows up as `unavailable` in Developer tools → States: the
helper holds the id, but no entity exists. Renaming an entity in Home Assistant does not change
the mapping — that is the point of it.

> **The reference ids** the shipped tests run against: `sensor.shelly_3em_pro_leistung` (primary
> grid) + `sensor.smart_meter_electric_consumption_w` (backup), `sensor.solarleistung_gesamt`,
> `sensor.serialbattery_seplos_ladestand` / `_leistung` / `_dc_bus_spannung`,
> `sensor.venus_dc_batterie_stromstarke` and the three
> `number.hm1500_limit_nonpersistent_relative` / `number.hms1600_{a,b}_limit_nonpersistent_relative`.
> For a different installation you change **nothing in the file** — you fill the mapping.

## How it works

`sensor.ems_limit_target` is the single source of truth: one percentage for all inverters.

```
offer   = min(EMS max charge power, EMS charge allowance)   # what the battery may take
push    = max(offer − bat, 0)                               # what is still missing
target  = clamp(solar + grid + push − EMS grid bias, 0, capacity)
limit % = target / capacity × 100
```

`solar + grid` is the house load from the energy balance, so the formula is really
**`PV allowed = house load + offer − bias`** — feed forward, with **no measured export in it**.
That is what stops an ESS ramp, a load switching off or a lagging meter from ratcheting the array
down, and `push` is clamped at ≥ 0 so a latched-down estimate can never ask for less than the
battery already takes.

`sensor.ems_mode` is the state machine everything keys off:

| Mode | When | Effect |
| :--- | :--- | :--- |
| `FULL` | everything fresh | the formula above |
| `NIGHT` | sun down and < 200 W PV | nothing is written (the loop still learns) |
| `STARTING` | less than `EMS start grace` (120 s) since a start | nothing is written |
| `NO_BATTERY` | no usable battery data | pure zero export — the charge push is dropped |
| `GRID_BLIND` | no usable grid or solar reading | the fail-safe percentage |
| `DTU_BLIND` | no inverter limit entity readable | nothing is written, you are notified |
| `OFF` | `EMS enabled` off, or a manual override | `EMS manual limit` is written |

**The day-start open phase (1.10.0).** At sunrise the array is deliberately held **wide open
(100 %)** instead of being trimmed to "house load + charge need" (about 53 % with the reference
installation), so the pack charges as fast as the sun allows. It is released — in the same render,
so it can never lag a write — as soon as the battery charges at its calculated maximum, PV reaches
`EMS open until solar` (3500 W), a *lasting* export appears (the loop's export counter, not a
momentary reading), or the SoC stop is reached. `automation.opendtu_ems_day_start` arms it at
sunrise (and when the mode leaves `NIGHT` / `STARTING`); the control loop clears the latch, so it
cannot re-enter until the next morning. Set `EMS open until solar` = 0 to switch the phase off.

The whole reasoning — the mode ladder, the loop's steps, the write gate, capacity redistribution,
the watchdog and the charge-acceptance learning with the 1.9.0 ramp guard — is in the wiki:
**[How it works](https://github.com/acdcnow/opendtu-ems/wiki/How-It-Works)** ·
**[Charge allowance](https://github.com/acdcnow/opendtu-ems/wiki/Charge-Allowance)**.

## The fail-safe ladder

| Situation | Reaction |
| :--- | :--- |
| battery data gone or stale | `NO_BATTERY` → zero export (pure house load), no charge push |
| primary grid meter dead/frozen | the backup takes over, the mode **stays** `FULL`, `source` says `victron` |
| both meters gone | `GRID_BLIND` → `EMS fail-safe limit` (0 % = inverters off) — export impossible |
| no inverter reachable | `DTU_BLIND` → nothing is written, notification, no error spam |
| loop stopped writing | `automation.opendtu_ems_watchdog` writes the fail-safe limit after 300 s and notifies |
| one inverter offline | excluded from the capacity, its share is redistributed to the rest |
| one inverter reachable but idle | `PV under-delivering` after ~6 min, while the grid still imports |
| not enough capacity | the array runs at 100 %, the grid imports the rest, `PV capacity short` |

`binary_sensor.ems_degraded` is on **only** in the fail-safe modes (`DTU_BLIND`, `GRID_BLIND`,
`NO_BATTERY`). `NIGHT`, `STARTING` and `OFF` are normal and stay silent.

## Settings: what every value does

Find them under Settings → Devices & services → **Helpers** (or on the *EMS Expert* board while
`input_boolean.ems_expert_mode` is on). `script.ems_set_defaults` writes exactly these values —
run it to reset the tuning.

### Charge power — how much of the array may run

| Helper | Default | Meaning |
| :--- | ---: | :--- |
| `input_number.ems_max_charge_power` | 2500 W | **hard ceiling** and the fallback. Set it to `min(DVCC max charge current, BMS CCL) × pack voltage`. 0 = never charge from PV |
| `input_number.ems_max_charge_current` | 50 A | `min(DVCC, BMS CCL)`; the offer follows the pack voltage (`voltage × current`, capped at the ceiling) |
| `input_number.ems_charge_allowance` | 2500 W | the **learned** acceptance — the loop lowers it when a lasting export proves the battery cannot take the offer, resets it on a discharge and probes upwards when the grid is quiet |
| `input_number.ems_open_solar_w` | 3500 W | **day start:** the array stays fully open below this PV power. 0 = no open phase |
| `input_number.ems_soc_stop` | 100 % | stop the charge offer at/above this SoC — only while the battery really takes nothing, so a wrong SoC cannot cut the array. 100 = never |

### Grid, meters and fail-safe

| Helper | Default | Meaning |
| :--- | ---: | :--- |
| `input_number.ems_grid_bias` | 20 W | the grid **import** the loop aims at (subtracted from the target). Raising it lets the array produce less |
| `input_number.ems_meter_tolerance` | 100 W | allowed disagreement between the two meters; the more conservative value wins |
| `input_number.ems_failsafe_pct` | 0 % | written in `GRID_BLIND` and by the watchdog. Raise to 2 % if your inverters dislike 0 % |
| `input_number.ems_manual_pct` | 0 % | the limit written while `EMS automatic mode` is off |
| `input_number.ems_start_grace` | 120 s | nothing is written for this long after a Home Assistant start |

### Charge-acceptance learning

| Helper | Default | Meaning |
| :--- | ---: | :--- |
| `input_number.ems_export_tolerance` | 150 W | an export up to this size is noise; nothing is curtailed inside it |
| `input_number.ems_export_grace` | 60 s | how long an export must last (with the charge power **no longer rising**) before it counts as proof |
| `input_number.ems_reprobe_seconds` | 900 s | no export for this long → probe the allowance upwards (×1.5). Raise to 3600 s for a quieter grid |

### Reaction speed

| Helper | Default | Meaning |
| :--- | ---: | :--- |
| `input_number.ems_settle_seconds` | 12 s | wait after each write for the ESS ramp. **Keep it below 15 s**, otherwise corrections wait for the heartbeat |
| `input_number.ems_max_step_pct` | 10 % | maximum **increase** per write (decreases are immediate — less PV can never cause an export) |
| `input_number.ems_hysteresis_pct` | 2 % | minimum change worth a write |

### Switches

| Helper | Default | Meaning |
| :--- | :--- | :--- |
| `input_boolean.ems_enabled` | on | master switch; off means `OFF` and nothing is written |
| `input_boolean.ems_automatic` | on | off = manual override: `EMS manual limit` is written, sensors are ignored, the learning freezes, the watchdog stands down |
| `input_boolean.ems_expert_mode` | off | dashboard only: reveals the tuning cards on *EMS Expert* |
| `input_boolean.ems_verbose` | off | one `opendtu.zero_export` log line per loop run |
| `input_boolean.ems_simulate_battery_loss` | off | test switch: forces `NO_BATTERY` so you can watch the fallback |

### Why the helpers start empty

Home Assistant creates an `input_number` **without** an `initial` value at its **minimum** — a
fresh installation would run with 0 W of charge power and never charge from PV. The boot automation
therefore applies the defaults **once**, on the very first start. `initial` would be wrong: it
would also overwrite your tuning and the learned allowance on every restart.

Every entity, with its meaning and its attributes, is listed in the wiki:
**[Reference](https://github.com/acdcnow/opendtu-ems/wiki/Reference)**.

## Day-to-day use

* **Two dashboards** come with it: *EMS Overview* (power flow, status chips, the day's history)
  and *EMS Expert* (the live control law, the learning, the inverter checks and the tuning cards).
  See [DASHBOARD.md](docs/DASHBOARD.md).
* **Normally you change nothing.** The loop regulates, learns and recovers by itself; the fail-safe
  ladder handles missing sensors.
* **Three things worth a look** when you want to know what is happening:
  `sensor.ems_limit_target` (the value written, with `allowance`, `charge_push` and `open_phase`),
  `sensor.ems_grid_power` (with its `source` attribute) and `input_number.ems_charge_allowance`.
* **`input_boolean.ems_automatic` off** is the emergency brake: the limit you set in
  `EMS manual limit` is written and nothing else is touched.
* **Updating** never loses the mapping or the learned values; see [Install](#install).

## Tests

Five suites, all runnable locally without a Home Assistant installation (the last one needs one):

| Command | What it proves |
| :--- | :--- |
| `python tests/validate_package.py` | every template parses and renders, the frozen control scenarios, the charge-allowance learning, the day-start open phase, the docs |
| `python tests/validate_dashboards.py` | every card template renders against a simulated sensor chain — including the ids a card builds *inside* its Jinja |
| `python tests/validate_integration.py` | the bundle is byte-identical to the sources, the manifest and `hacs.json` are valid, the install rules behave |
| `python tests/simulate_day.py` | a whole day at 10 s resolution (a `day` and a `cloud` scenario) against the real templates: no curtailment while the battery could take it, curtailment at its limit, and the day-start phase |
| `python tests/validate_in_ha.py` | boots a **real** Home Assistant, loads the package and drives the chain — platforms set up, no invalid config, every dashboard entity exists, the write path, the open phase |

The last one is the important one: an invalid config key does **not** raise, it silently drops a
whole platform with a single log line, and a dashboard wired to a non-existent entity renders
nothing and logs nothing. CI runs the first four on every push; the fifth needs
`pip install homeassistant==2026.10.1` and also asserts that the running Home Assistant satisfies
the minimum declared in `hacs.json`.

## Files

```
packages/opendtu_ems.yaml                     the EMS - helpers, sensors, scripts, automations
dashboards/ems-overview.yaml                  everyday board
dashboards/ems-expert.yaml                    diagnostics, tuning, maintenance
blueprints/script/opendtu_ems/ems_map_sensors.yaml   the mapping blueprint
custom_components/opendtu_ems/                the HACS integration that installs the four files
tests/                                        the five suites above
docs/                                         INSTALL, CONFIGURATION, DASHBOARD, TROUBLESHOOTING
```

## Hardware backstop

Everything above is software that has to be *running*. Set a **low persistent limit** on every
inverter in the OpenDTU web UI (Inverter → Limit): that is what the inverter falls back to when no
non-persistent limit is in force — after a reboot, when the DTU is offline, or when the limit
expires. Without it, "no export" depends on Home Assistant being up.

## Documentation

* **Wiki** — [What it does and how it works](https://github.com/acdcnow/opendtu-ems/wiki/How-It-Works) ·
  [The charge-allowance learning](https://github.com/acdcnow/opendtu-ems/wiki/Charge-Allowance) ·
  [The sensor mapping](https://github.com/acdcnow/opendtu-ems/wiki/Sensor-Mapping) ·
  [Installation](https://github.com/acdcnow/opendtu-ems/wiki/Installation) ·
  [Dashboards](https://github.com/acdcnow/opendtu-ems/wiki/Dashboards) ·
  [Reference](https://github.com/acdcnow/opendtu-ems/wiki/Reference) ·
  [Troubleshooting](https://github.com/acdcnow/opendtu-ems/wiki/Troubleshooting) ·
  [Upgrading](https://github.com/acdcnow/opendtu-ems/wiki/Upgrading)
* [docs/INSTALL.md](docs/INSTALL.md) · [docs/CONFIGURATION.md](docs/CONFIGURATION.md) ·
  [docs/DASHBOARD.md](docs/DASHBOARD.md) · [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
* [CHANGELOG.md](CHANGELOG.md) · [Releases](https://github.com/acdcnow/opendtu-ems/releases)

## Safety and disclaimer

This package writes to your inverters. It is built to fail *safe* (a wrong sensor leads to less
PV, never to more), but **you are responsible for your installation**: keep the persistent limit
in OpenDTU as a backstop, check the grid meter sign and the battery power sign before you trust
the regulation, and watch the first sunny day.

## License

GPL-3.0 — see [LICENSE](LICENSE).
