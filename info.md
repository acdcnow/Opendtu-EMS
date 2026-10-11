# OpenDTU Zero-Export EMS

A single-file Home Assistant package that runs a **battery-first, zero-export** energy
management loop for Hoymiles micro-inverters driven by
[OpenDTU](https://github.com/tbnobody/OpenDTU) (OpenDTU-OnBattery works too), next to a
Victron ESS and a Seplos battery.

**Release 1.9.0** · Home Assistant **2026.9 or newer**

## Highlights

* Holds the grid at a small **import** bias (+20 W by default) and gives the battery every watt
  it can take — the array is never allowed to export, not even when a sensor or an inverter dies.
* **Charge-acceptance learning with the 1.9.0 ramp guard.** An export while the ESS is still
  climbing towards its limit is *not* read as a refusal any more, so the array is no longer held
  below what the battery can really take.
* **Dynamic charge power** from the Victron DC bus (`DC bus voltage × signed battery current`);
  the charge limit is `voltage × EMS max charge current`, capped at a hard maximum. A negative
  current means discharge and never curtails the array.
* **Fail-soft ladder** — `FULL`, `STARTING`, `NIGHT`, `DTU_BLIND`, `NO_BATTERY`, `GRID_BLIND`,
  `OFF`. A second grid meter takes over seamlessly, and a watchdog re-asserts a fail-safe limit
  and notifies you.
* **Two ready-made dashboards** — *EMS Overview* (everyday) and *EMS Expert* (diagnostics and
  tuning, revealed only while `input_boolean.ems_expert_mode` is on).
* **HACS integration** that installs the package and both dashboards, never overwrites your
  edits, keeps the previous file as `.bak` and reports its state in `sensor.ems_bundle`.
* One YAML file: **25 helpers, 9 entities, 2 scripts, 3 automations, 91 templates** — every
  template parsed and rendered by CI, plus a 10 s-resolution day simulation.
* No custom component is written by you: the EMS logic stays the one YAML package.

## Requirements

| | |
|---|---|
| Home Assistant | 2026.9 or newer, with `packages:` enabled |
| Inverters | one `number.<inverter>_limit_nonpersistent_relative` entity each |
| Grid meter | Shelly 3EM Pro (reference), optionally a second meter as a live backup |
| Battery | SoC **and** a *signed* power sensor (`+ = charging`), Victron ESS with DVCC |

## Install

1. HACS → ⋮ (top right) → **Custom repositories** → `https://github.com/acdcnow/opendtu-ems`,
   type **Integration** → *Add*
2. Search *OpenDTU Zero-Export EMS* → **Download** → **restart** Home Assistant
3. Settings → Devices & services → *Add integration* → **OpenDTU Zero-Export EMS** → confirm
4. If the notification asks for it, add `homeassistant: packages: !include_dir_named packages`
   to `configuration.yaml` once, then restart
5. Set a **low persistent limit** on every inverter in the OpenDTU web UI (hardware backstop)

Updating: HACS downloads the new version, the action `opendtu_ems.install_bundle` (or re-adding
the integration) applies it, then restart. The previous package file is kept as `.bak`.
Please compare it with your own edits — section 1 of the file holds your entity ids.

## Documentation

**[Documentation wiki](https://github.com/acdcnow/opendtu-ems/wiki)** ·
[README](https://github.com/acdcnow/opendtu-ems/blob/main/README.md) ·
[Changelog](https://github.com/acdcnow/opendtu-ems/blob/main/CHANGELOG.md) ·
[Releases](https://github.com/acdcnow/opendtu-ems/releases)

**GPL-3.0** licensed (see [`LICENSE`](LICENSE)). This package controls real hardware: nobody but
you is responsible for your installation, your cabling ratings and your grid connection rules.
