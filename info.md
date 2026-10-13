# OpenDTU Zero-Export EMS

A **battery-first, zero-export** energy management loop for Hoymiles micro-inverters driven by
[OpenDTU](https://github.com/tbnobody/OpenDTU) (OpenDTU-OnBattery works too), next to a Victron ESS
and a Seplos battery.

**Release 1.10.0** · Home Assistant **2026.10.1 or newer** · GPL-3.0

The EMS is **one YAML package**. It creates its own helpers, sensors, scripts and automations,
computes one percentage for all inverters from the wattage the battery can still take, learns the
battery's real charge acceptance by itself, and fails soft when a sensor disappears. The HACS
integration only installs and updates that file — plus two dashboards and a mapping blueprint.

---

## What it does

* Holds the grid at a small **import** bias (+20 W by default) and gives the battery every watt it
  can take — the array is never allowed to export, not even when a sensor or an inverter dies.
* **Battery first, never on the back of a momentary export.** The target is feed forward
  (`house load + what the battery can take − bias`); a Victron ramp, a load switching off or a
  lagging meter cannot ratchet the array down.
* **Learns the real charge acceptance** and probes it upwards again, so the array is never held
  below what the battery can really take (the ramp guard of 1.9.0).
* **Day-start open phase (1.10.0).** At sunrise the array runs **wide open** until there is
  something to throttle — the battery at its calculated maximum, PV at full production, or a
  lasting export. No PV is thrown away while the pack still has headroom.
* **Fail-soft ladder** — `FULL`, `STARTING`, `NIGHT`, `DTU_BLIND`, `NO_BATTERY`, `GRID_BLIND`,
  `OFF`. A second grid meter takes over seamlessly; a watchdog re-asserts a fail-safe limit and
  tells you why.
* **The sensor mapping (1.10.0).** The package contains **no foreign entity id**: 15 `input_text`
  helpers hold them, a shipped blueprint asks for them, and `sensor.ems_map_status` says what is
  still missing. A renamed sensor is one field, not ~60 places.
* **Two ready-made dashboards** — *EMS Overview* (everyday) and *EMS Expert* (diagnostics, the
  live control law and the tuning cards).
* **HACS integration** that installs the package, both dashboards and the blueprint, never
  overwrites a file you edited (it keeps a `.bak`) and reports its state in `sensor.ems_bundle`.

## Requirements

| | |
| :--- | :--- |
| Home Assistant | **2026.10.1 or newer**, with `packages:` enabled |
| Inverters | one `number.<inverter>_limit_nonpersistent_relative` entity per micro-inverter |
| Grid meter | anything publishing watts, **positive = import** (a Shelly 3EM Pro is the reference); a second meter can act as a live backup |
| Battery | SoC **and** a *signed* power sensor (**positive = charging**); a Victron ESS with DVCC is the reference |
| OpenDTU | 1.1.12 recommended — **avoid Hoymiles firmware 2.0.4**, it forgets non-persistent limits after ~4 minutes |

## Install

1. HACS → ⋮ (top right) → **Custom repositories** → `https://github.com/acdcnow/opendtu-ems`,
   type **Integration** → *Add*
2. Search **OpenDTU Zero-Export EMS** → **Download** → **restart** Home Assistant
3. Settings → Devices & services → *Add integration* → **OpenDTU Zero-Export EMS** → confirm
4. Add the `packages:` key to `configuration.yaml` **once** (merge it into an existing
   `homeassistant:` block — a second block is not allowed), then restart:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

5. Run the blueprint **OpenDTU EMS - the sensor names** (or fill the 15 `EMS source - …` helpers
   by hand) until `sensor.ems_map_status` reads **`ok`**
6. Set a **low persistent limit** on every inverter in the OpenDTU web UI — the hardware backstop
   if Home Assistant is ever down

Updating: HACS downloads the new version, the action `opendtu_ems.install_bundle` (or re-adding the
integration) applies it, then restart. The previous package file is kept as `.bak`. **Your sensor
mapping and the learned values survive**, because they live in entities, not in the replaced file.
After the update check `sensor.ems_map_status` and fill anything it reports as missing with the
blueprint.

## Documentation

* **Wiki** — [What it does and how it works](https://github.com/acdcnow/opendtu-ems/wiki/How-It-Works) ·
  [The charge-allowance learning](https://github.com/acdcnow/opendtu-ems/wiki/Charge-Allowance) ·
  [The sensor mapping](https://github.com/acdcnow/opendtu-ems/wiki/Sensor-Mapping) ·
  [Installation](https://github.com/acdcnow/opendtu-ems/wiki/Installation) ·
  [Dashboards](https://github.com/acdcnow/opendtu-ems/wiki/Dashboards) ·
  [Reference](https://github.com/acdcnow/opendtu-ems/wiki/Reference) ·
  [Troubleshooting](https://github.com/acdcnow/opendtu-ems/wiki/Troubleshooting) ·
  [Upgrading](https://github.com/acdcnow/opendtu-ems/wiki/Upgrading)
* **README** — the full picture, the settings tables and the test suites:
  [README.md](https://github.com/acdcnow/opendtu-ems#readme)
* **Changelog** — [CHANGELOG.md](https://github.com/acdcnow/opendtu-ems/blob/main/CHANGELOG.md)
* **Issues** — [github.com/acdcnow/opendtu-ems/issues](https://github.com/acdcnow/opendtu-ems/issues)

## Safety and disclaimer

This package writes to your inverters. It is built to fail *safe* — a wrong sensor leads to less PV,
never to more — but **you are responsible for your installation**: keep the persistent limit in
OpenDTU as a backstop, verify the sign of your grid meter and of the battery power sensor before
you trust the regulation, and watch the first sunny day.

## License

GPL-3.0
