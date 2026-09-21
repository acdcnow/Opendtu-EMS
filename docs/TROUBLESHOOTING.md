# Troubleshooting

Work through the symptom table first, then the detail sections.

| Symptom | Look at | Likely cause |
|---|---|---|
| **No `ems_*` entities at all** | `configuration.yaml`, Logs | the package was not loaded — see [below](#the-ems-entities-do-not-appear-at-all) |
| **`<Plugin …> Repository structure for vX.Y.Z is not compliant`** in HACS | the HACS custom repository list | the repository was added to HACS, which has no type for packages — see [below](#hacs-repository-structure-is-not-compliant) |
| `Integration 'ems_enabled' not found` | `packages:` in `configuration.yaml` | the package file is used **as** the packages mapping — see [below](#setup-of-package-input_boolean-failed) |
| `sensor.ems_mode` is `OFF` | `input_boolean.ems_enabled` | master switch off |
| `sensor.ems_mode` is `NIGHT` | `sun.sun`, PV | normal at night — not a fault |
| `sensor.ems_mode` is `STARTING` | `input_datetime.ems_started_at` | normal for `EMS start grace` seconds after a restart |
| `sensor.ems_mode` is `DTU_BLIND` | `sensor.ems_inverter_capacity` = 0 | OpenDTU off, MQTT down, ids changed |
| `sensor.ems_mode` is `GRID_BLIND` | `sensor.ems_grid_power` → `source`, `sensor.solarleistung_gesamt` | both meters dead, renamed or stale — or the solar sensor is gone |
| `sensor.ems_mode` is `NO_BATTERY` | `sensor.serialbattery_seplos_*` | SoC/power sensor unavailable, stale or out of range |
| Limit stays at `0 %` | mode, `input_number.ems_failsafe_pct` | `GRID_BLIND` fail-safe, or `ems_manual_pct = 0` |
| Limit never changes | trace of the loop, `input_datetime.ems_last_apply` | condition blocked (settle/hysteresis) or the loop errors |
| Exports after load steps | `history` of `sensor.ems_grid_power` | `EMS max step` too high / `EMS settle time` too short |
| **PV is cut although the battery could take it** | `input_number.ems_charge_allowance`, attributes `allowance`/`charge_push` of `sensor.ems_limit_target`, `input_number.ems_export_ticks` | the loop measured that the battery is not taking the offer — see [below](#pv-is-cut-although-the-battery-could-take-it) |
| Battery stops charging near the top | `EMS SoC stop charging`, `input_number.ems_charge_allowance`, BMS CCL | the SoC stop is at 100 % by default; if `charge allowance` is at the limit, the BMS is the bottleneck (CV phase) |
| Charging is slow | DVCC, BMS CCL, `EMS max charge power`, `ems_charge_allowance` | charge current limited by the Victron side, or the learned allowance is below the maximum |
| Redistribution does not happen | `active` attribute | the offline inverter's limit entity stays available → add power sensors |
| *PV capacity short* notification | OpenDTU inverter page | an inverter is offline / its limit entity disappeared |
| *PV under-delivering* notification | `sensor.ems_pv_delivery` attributes | inverter not delivering **or** heavy clouds/shading |
| *fail-safe active* notification | `automation.opendtu_ems_loop` | the loop stopped writing (disabled, error, restart) |

---

## HACS: Repository structure is not compliant

The full line looks like this:

```
<Plugin acdcnow/opendtu-ems> Repository structure for v1.5.1 is not compliant
```

**What it means:** the repository was added to HACS as a *custom repository*, and HACS checked
its file tree for the files that type requires. Nothing is wrong with your installation — HACS
simply cannot handle a package:

* `<Plugin …>` is the **type you selected** in the *Add custom repository* dialog (the frontend
  calls it *Dashboard*, the backend calls it `plugin`).
* `v1.5.1` is the **release** HACS looked at (with releases present it validates the latest
  tag, not the default branch).
* For a plugin HACS needs a JavaScript file named like the repository — `opendtu-ems.js`,
  `opendtu-ems.umd.js`, `opendtu-ems-bundle.js` (or `lovelace-` stripped) in the repository
  root, in `dist/`, or as a release asset. For plugins HACS installs into
  `www/community/<repo>/` and registers the file as a Lovelace **resource of type `module`** —
  which is why it must be JavaScript at all.

No other type works either:

| Type | HACS needs | This repository |
|---|---|---|
| Integration | `custom_components/opendtu_ems/manifest.json` | ✗ (a package has no Python) |
| Dashboard (plugin) | `dist/opendtu-ems.js` or `opendtu-ems.js` in the root | ✗ |
| Template | `hacs.json` + `opendtu-ems.jinja` in the root | ✗ |
| Theme / Python script / AppDaemon | a theme `.yaml`, `.py`, or `apps/` in the root | ✗ |

**Fix:** remove the entry — HACS → the ⋮ menu (top right) → *Custom repositories* → the
repository → remove. It only removes the HACS entry, nothing on disk and nothing of the EMS:
the package is installed by copying `packages/opendtu_ems.yaml`, and HACS is only used for the
four dashboard cards.

> Do **not** try to satisfy the check by pointing `filename` in a `hacs.json` at
> `ems-overview.yaml`. The structure check would pass, but HACS would then register that YAML
> file as a JavaScript module for the frontend, which the browser fails to load — a broken
> resource instead of a clear message.

HACS *could* host parts of this project (a JavaScript dashboard strategy, or a real custom
integration for the EMS); those would be new components, see
[README](../README.md#can-hacs-install-this).

## Setup of package 'input_boolean' failed

Typical log output:

```
Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.
Setup of package 'input_number' failed: Integration 'ems_manual_pct' not found.
Setup of package 'template' failed: Invalid package definition 'template': expected a mapping.
Setup of package 'automation' failed: Invalid package definition 'automation': expected a mapping.
```

**What it means:** `packages:` points *at the package file itself*. Home Assistant then treats the
top level keys of that file (`input_boolean`, `input_number`, `template`, `script`, `automation`)
as package **names**, and their children (`ems_enabled`, `ems_manual_pct`, …) as integration
domains — hence "Integration 'ems_enabled' not found". The two "expected a mapping" lines are the
same problem: `template:` and `automation:` are lists, and a package must be a mapping.

**Fix — use one of these two forms:**

```yaml
# A: folder - every file inside packages/ becomes one package
homeassistant:
  packages: !include_dir_named packages
```

```yaml
# B: name the package explicitly (works with !include)
homeassistant:
  packages:
    opendtu_ems: !include packages/opendtu_ems.yaml
```

**Broken:** `packages: !include packages/opendtu_ems.yaml` (no name) or a `packages:` mapping
whose value is this file's content. Also broken: `!include_dir_merge_named packages`, which
merges the *keys inside* the files instead of using the file names as package names.
If your `packages:` already includes another file, add this one
as a second key instead of replacing it:

```yaml
homeassistant:
  packages:
    my_existing_package: !include packages/other.yaml
    opendtu_ems: !include packages/opendtu_ems.yaml
```

After the fix: **Check configuration** must be clean, then **restart** (helpers and templates are
only created at startup).

## The EMS entities do not appear at all

A missing `sensor.ems_*`, missing helpers or missing automations have nothing to do with
OpenDTU — the package is not loaded. Check, in this order:

1. **File location** — the file must be exactly `<config>/packages/opendtu_ems.yaml`.
   `<config>` is the directory that contains `configuration.yaml` (via Samba: `\\<host>\config\`).
2. **The include** — `configuration.yaml` must contain

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   The folder name must match: `!include_dir_named packages` reads `packages/`.
3. **Do not add a second `homeassistant:` block.** If one already exists (very common),
   *merge* the `packages:` key into it — duplicate top-level keys make Home Assistant
   reject the configuration.
4. **Restart, do not reload.** Helpers and template entities are only created at startup.
5. **Check the configuration before restarting**: Settings → Developer tools → *Check
   configuration*. After the restart look at Settings → Logs for `Invalid config` and for
   `Package packages/... setup failed` — a single YAML or Jinja error rejects the whole file.
6. **Verify what should exist**: Search `ems_` in Developer tools → States (7 entities),
   Settings → Automations (3), Settings → Helpers (21, search "EMS").

   Note that a YAML automation's entity id is the slug of its **alias**, not its `id:`
   (`OpenDTU EMS loop` → `automation.opendtu_ems_loop`), and that the registry keeps an entity id
   once it exists — after renaming an alias, search `opendtu` in Developer tools → States.

As a quick sanity check of the file itself, you can run the repository test suite locally:

```bash
pip install pyyaml jinja2
python tests/validate_package.py packages/opendtu_ems.yaml
```

### Only *some* entities: `Entity not available: sensor.ems_…` in a card

A card that prints `Entity not available: <entity_id>` is saying that the id is **not in Home
Assistant's state machine at all** — the ApexCharts card, for example, looks every series up in
`hass.states` and reports this for each id it cannot resolve. It is never about the recorder, the
history or the card configuration (an invalid card config flags *every* series at once), and it is
never the package being wrong: the test suite cross-checks every entity referenced in the
dashboard **and** in these docs against the entities the package creates.

So a single missing id means it exists under a **different** id, or not at all:

1. **A second definition of the same entity.** A leftover copy of the EMS (an older file next to
   the package, a copy in `configuration.yaml`, or a helper created in the UI) already uses the id
   or the `unique_id`. Home Assistant keeps the first definition and silently drops the second.
   Search the whole config directory:

   ```bash
   grep -rn "ems_house_load\|ems_limit_target" /config --include=*.yaml
   ```

   There must be exactly one definition of each id.
2. **Renamed or disabled in the registry.** Settings → Devices & services → **Entities**, search
   `ems_`: an entity whose *entity id* was changed by hand (e.g. `sensor.ems_limit_target_2`) or a
   **disabled** entity does not appear in the frontend and reads `unknown` in `states()` — exactly
   this symptom. Set the entity id back to the one the card uses, or enable the entity.
3. **The package is older than the dashboard.** `sensor.ems_house_load` exists since **v1.4.0**
   only, so an older package plus a current view produces the message for it.
4. **A template entity failed.** Developer tools → States: if these ids are missing while
   `sensor.ems_grid_power` and the helpers are there, look for `TemplateError` in Settings → Logs
   and check that no `name:` was changed.

In all four cases the fix is the same: leave exactly one definition, re-copy the current package,
restart, and restore the entity ids in the registry. **No dashboard change is needed** — the series
draws again as soon as the id exists.

## Mode is NIGHT or STARTING

Both are normal. `NIGHT` means the sun is below the horizon *and* PV is under 200 W — the
solar-powered inverters are asleep, so there is nothing to control; no writes, no
notifications, and `binary_sensor.ems_degraded` stays off. `STARTING` means Home Assistant
started less than `EMS start grace` seconds ago; it prevents half-initialised sensors or an
ESS that is still booting from causing a wrong write. Both end by themselves — at sunrise, or
when the grace time is over.

If you start Home Assistant at night, the expected sequence is: `STARTING` for two minutes,
then `NIGHT` until the sun comes up, then `FULL` (or `DTU_BLIND` if the DTU is really off).

## Mode is DTU_BLIND

No `number.*_limit_nonpersistent_relative` entity has a value, so the loop cannot control
anything and stops writing. Typical causes: the ESP32 running OpenDTU is unplugged or
rebooting, the MQTT broker is down, the DTU has no Wi-Fi, or the entity IDs were renamed
(section 1 of the package). The grid and battery sensors are unaffected, and the loop resumes
by itself as soon as one inverter entity is readable again. A persistent notification
*OpenDTU EMS - no inverter reachable* is raised while it lasts.

---

## The loop does not write

Check in this order:

1. **Trace** — Settings → Automations → *OpenDTU EMS loop* → ⋮ → Traces. The last
   trace shows the trigger, the condition result and the executed steps.
2. **Condition** — the second condition blocks writes when
   `current_pct` and `sensor.ems_limit_target` differ by less than `EMS hysteresis`, the last
   write is younger than `EMS settle time`, and no export > 500 W is present. This is normal:
   the loop is designed not to chatter.
3. **Settle time** — if it is above 15 s, corrections only happen on the heartbeat. Keep it
   around 10-12 s.
4. **Errors** — Settings → Logs, filter for `opendtu.zero_export`. Template errors there mean
   an entity ID in section 1 of the package is wrong.
5. **Availability** — if all three `number.*_limit_nonpersistent_relative` entities are
   unavailable, `sensor.ems_inverter_capacity` is 0 and the loop writes the fail-safe value
   into nothing. Check the DTU/OpenDTU itself.

## Exports keep appearing

1. Confirm the sign convention of your grid meter: with the battery charging and PV covering
   the load, `sensor.ems_grid_power` must be slightly positive.
2. Confirm the battery power sign (positive = charging). A wrong sign makes the loop push PV
   *and* export.
3. Lower `EMS max step` (start at 5 %) and raise `EMS settle time` (e.g. 20 s, but keep the
   heartbeat shorter — or the corrections wait).
4. Watch `sensor.ems_pv_delivery`: if it is ~100 % while exporting, the export comes from a
   load step or from the ESS itself, not from the inverters.
5. Check the ESS grid setpoint in the Victron GX: if it is configured to export, the loop
   fights your own ESS.

## PV is cut although the battery could take it

> Running **1.4.0 or older?** Then this is expected behaviour of that version — read
> [Control law 1.4.x (archived)](https://github.com/acdcnow/opendtu-ems/wiki/Archive-1.4-Control-Law).
> It explains the export ratchet, the SoC taper and the migration to 1.5.x.

This was a real bug up to 1.4.x and is fixed in 1.5.0. Understand the numbers first, then
check the ones on your system:

```
limit target = house load + allowed charge power + bias
allowed charge power = min(EMS max charge power, EMS charge allowance)
```

1. **Read the attributes.** `sensor.ems_limit_target` → `allowance` (how much charge power the
   battery is offered right now) and `charge_push` (how much of the target is meant for
   charging). `charge_push = 0` means the target only covers the house load — and that is
   only allowed to happen when (a) `EMS SoC stop charging` is reached *and* the battery is
   measurably not charging, or (b) the mode is not `FULL`.
2. **Check the learned allowance.** `input_number.ems_charge_allowance` below `EMS max charge
   power` means the loop saw an export that the battery did not absorb for at least
   `EMS export grace`. That is measurement, not a guess:
   * if the Victron was simply slow, raise `EMS export grace` (e.g. 180 s)
   * if your meter is noisy or has an offset, raise `EMS export tolerance` (e.g. 200 W)
   * if the battery really is limited (BMS CCL, cold pack, CV phase), the value is correct —
     check DVCC and the CCL, and watch `bat` in the verbose log
3. **Check `EMS export ticks`.** It counts the 15 s ticks of the current export run. Values at
   or above the grace mean the allowance is being reduced further.
4. **Check the SoC.** With `EMS SoC stop charging = 100` the stop can only bite at 100 %, and
   even then only while the battery takes less than `EMS export tolerance`. A stuck SoC is
   therefore harmless. Lower the helper only on purpose.
5. **Reset the estimate by hand.** Set `input_number.ems_charge_allowance` back to
   `EMS max charge power` and watch: it is reset automatically on the next discharge anyway.

## Charging is slower than expected

The loop cannot change how fast the battery charges; it only decides how much PV is allowed.
Check:

* DVCC max charge current (50 A in the reference installation) is set on the GX device.
* The BMS charge current limit (CCL) is not the bottleneck — the BMS reduces it in cold
  weather or near full.
* `EMS max charge power` matches `min(DVCC, CCL) × voltage`.
* `input_number.ems_charge_allowance` is at `EMS max charge power`. If it sits lower, the loop
  measured that the battery does not take the offer — watch `bat` in the verbose log while the
  grid exports, and compare it with the allowance. The estimate recovers by itself (×1.5 every
  `EMS charge re-probe` without an export) and is reset on every discharge.
* `sensor.ems_mode` is `FULL` (not `NO_BATTERY`) while the battery charges.

Remember that the loop only decides how much PV is *allowed*; it cannot make the Victron
charge faster. A battery that takes 800 W while 2500 W are offered is a battery/BMS matter, and
the loop will work at those 800 W instead of exporting the difference.

## Redistribution does not kick in

`sensor.ems_inverter_capacity` → `active` stays 3 when an inverter is off:

* some OpenDTU versions keep the limit entity available even when the inverter does not
  answer. In that case add the per-inverter power sensors (see
  [CONFIGURATION.md](CONFIGURATION.md#optional-per-inverter-power-sensors)).
* Check in OpenDTU which inverters are `reachable` / `producing`.

Note that total power alone cannot distinguish "one inverter is dead" from "it is cloudy".
That is why the delivery check reports the situation instead of silently recalculating the
capacity.

## Notifications

All notifications use `persistent_notification` with a fixed `notification_id`, so they
update in place instead of piling up. They disappear when you dismiss them.

| `notification_id` | Meaning |
|---|---|
| `opendtu_ems_failsafe` | the loop stopped writing — fail-safe limit applied |
| `opendtu_ems_dtu` | no inverter is reachable at all (OpenDTU off / MQTT down) |
| `opendtu_ems_capacity` | fewer than 3 inverters reachable, the rest already at 100 %, grid still imports |
| `opendtu_ems_delivery` | commanded output stays below 70 % and > 800 W short for ~6 min |

## Debugging aids

* `input_boolean.ems_verbose` + `logger: logs: opendtu.zero_export: debug` → one line per run,
  plus a `CHARGE ALLOWANCE:` warning line whenever the offer is reduced.
* `input_number.ems_charge_allowance` / `ems_export_ticks` → "how much can the battery take"
  and "is the array exporting right now".
* attributes `allowance` and `charge_push` of `sensor.ems_limit_target` → the same two numbers
  next to the target percentage.
* `input_boolean.ems_simulate_battery_loss` → tests the `NO_BATTERY` path.
* `input_number.ems_manual_pct` → writes a fixed percentage, ignoring all sensors
  (`-1` restores automatic operation).
* `input_datetime.ems_last_apply` → history shows exactly when and how often the loop wrote.

## Starting over

1. `input_boolean.ems_enabled` → off (stops all writes).
2. Delete the package file and the helpers it created (Settings → Helpers → *EMS*).
3. Restart Home Assistant and re-enable your previous automation.
