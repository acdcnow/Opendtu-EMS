# Installation

Step-by-step guide for the OpenDTU Zero-Export EMS package.
Entity IDs below are the ones of the reference installation (a Victron ESS with a Seplos
battery, a Shelly 3EM Pro, a Victron smart meter and three Hoymiles inverters on an
OpenDTU). Replace them with yours wherever they appear.

> **Design background** (why the package works the way it does) lives in the wiki:
> [Architecture Concept Document](https://github.com/acdcnow/opendtu-ems/wiki/Architecture-Concept-Document) ·
> [Software Design Document](https://github.com/acdcnow/opendtu-ems/wiki/Software-Design-Document) ·
> [Workflow Diagrams](https://github.com/acdcnow/opendtu-ems/wiki/Workflow-Diagrams).
> Coming from **1.4.0 or older**, read the
> [archived 1.4 control law](https://github.com/acdcnow/opendtu-ems/wiki/Archive-1.4-Control-Law)
> first — two helpers disappear and the charging behaviour changes.

---

## 1. Prerequisites checklist

| # | Requirement | How to check |
|---|---|---|
| 1 | Home Assistant **2026.9+** | Settings → About |
| 2 | `packages:` enabled | see step 3 |
| 3 | one `number.<inverter>_limit_nonpersistent_relative` per inverter | Developer tools → States |
| 4 | a grid meter sensor, positive = import | compare with a big load |
| 5 | battery **SoC** and **signed** battery power (positive = charging) | Developer tools → States while charging |
| 6 | Victron ESS with DVCC max charge current configured | Victron GX → DVCC |
| 7 | **low persistent limit** set on every inverter | OpenDTU → Inverter → Limit |
| 8 | the automation this package replaces | disable it in Settings → Automations |

### 1.1 Verify the OpenDTU entities

Developer tools → Template, paste:

```jinja
{{ expand(['number.hm1500_limit_nonpersistent_relative',
           'number.hms1600_a_limit_nonpersistent_relative',
           'number.hms1600_b_limit_nonpersistent_relative'])
   | map(attribute='state') | list }}
```

All three must be numeric. If your OpenDTU only exposes `..._limit_nonpersistent_absolute`,
read the note in [CONFIGURATION.md](CONFIGURATION.md#absolute-instead-of-relative-limits)
first — the package must be adapted.

### 1.2 Verify the battery power sign

```jinja
{{ states('sensor.serialbattery_seplos_leistung') }}
```

While the battery is charging this **must** be positive. If it is negative, either swap to
the Victron battery power sensor or negate the sensor — with the wrong sign the loop would
drive the inverters to full output and export.

### 1.3 Verify that an offline inverter becomes unavailable

Switch one inverter off in the OpenDTU web UI and watch its limit entity. If it turns
`unavailable`, the redistribution works automatically. If it keeps its last value, add the
per-inverter power sensors as described in
[CONFIGURATION.md](CONFIGURATION.md#optional-per-inverter-power-sensors).

---

## 2. Install the package

### 2.1 With HACS

This is the recommended path — the repository is a HACS **integration** that installs the
package for you:

1. HACS → ⋮ (top right) → **Custom repositories** → `https://github.com/acdcnow/opendtu-ems`,
   type **Integration** → *Add*.
2. Search *OpenDTU Zero-Export EMS* in HACS → **Download**, then **restart** Home Assistant
   (a custom integration is loaded at start-up only).
3. Settings → Devices & services → *Add integration* → **OpenDTU Zero-Export EMS** → confirm.
   It writes `<config>/packages/opendtu_ems.yaml` and `<config>/opendtu_ems/ems-overview.yaml`
   and reports the result as a notification and in `sensor.ems_bundle`.
4. Continue with step 2 in [2.2](#22-by-hand) below (the `packages:` key) — the integration
   tells you when it is missing — and then **restart** once more.

An existing package file is only replaced when it is **older**; the old file stays as
`opendtu_ems.yaml.bak`, and a newer or hand-edited file is left untouched (the notification says
which case applied). After a HACS update, run the action `opendtu_ems.install_bundle` and restart.

### 2.2 By hand

1. Copy `packages/opendtu_ems.yaml` to your Home Assistant configuration directory:

   ```
   <config>/packages/opendtu_ems.yaml
   ```

   Use the Samba share, the *Studio Code Server* app, or the *File Editor* app.

2. Enable packages in `configuration.yaml`. **One of these two forms** (both are
   correct, pick what fits your setup):

   **A - folder (recommended, one file = one package):**

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

   **B - name the package explicitly** (use this when you prefer `!include`):

   ```yaml
   homeassistant:
     packages:
       opendtu_ems: !include packages/opendtu_ems.yaml
   ```

   > **Do not do this:** `packages: !include packages/opendtu_ems.yaml` without a name
   > (or pointing `packages:` at this file in any other way). Home Assistant then reads the
   > *top level keys of the package* as package names and reports
   > `Setup of package 'input_boolean' failed: Integration 'ems_enabled' not found.` —
   > one such line for every helper, plus
   > `Setup of package 'template' failed: Invalid package definition 'template': expected a mapping.`
   > The same happens if `packages:` already points at a file that contains this package,
   > or if you used `!include_dir_merge_named packages` — that merges the *keys inside* the
   > files, which turns them into package names as well. The correct directive for a folder of
   > packages is `!include_dir_named` (one file = one package, named after the file).
   > Also: if a `homeassistant:` block already exists, **merge** the `packages:` key into it
   > instead of adding a second `homeassistant:` block.

3. Check the file before reloading: Settings → Developer tools → **Check configuration**.
   It must report no errors — the package errors above are not warnings, they mean nothing
   was created.

4. Restart Home Assistant (helpers cannot be created by a reload).

5. Verify the entities exist — Developer tools → States:

   `sensor.ems_mode`, `sensor.ems_grid_power`, `sensor.ems_inverter_capacity`,
   `sensor.ems_pv_delivery`, `sensor.ems_house_load`, `sensor.ems_limit_target`,
   `binary_sensor.ems_degraded`, `script.ems_apply`,
   `automation.opendtu_ems_loop`, `automation.opendtu_ems_watchdog`,
   `automation.opendtu_ems_boot`.

   > YAML automations derive their entity id from the **alias**, slugified — not from the `id:`
   > key. That is why the aliases in this package are short (`OpenDTU EMS loop` →
   > `automation.opendtu_ems_loop`). If you rename an alias later, the registry keeps the old
   > entity id; find it by searching `opendtu` in Developer tools → States.

6. Disable the old automation. Two writers on the same inverters will fight each other.

> **Not via HACS.** HACS has no repository type for packages (only `integration`, plugin/
> dashboard, `theme`, `template`, `python_script`, `appdaemon`), so a custom repository entry
> for this project would always report a non-compliant structure. The install is the file copy
> in step 1 — HACS is only used for the four dashboard cards, see
> [DASHBOARD.md](DASHBOARD.md#1-install-the-cards).

---

## 3. Adapt to your installation

### 3.1 Section 1 of the package

The header block *"1) ENTITY IDS - EDIT HERE ONLY"* documents every entity the package
reads. If a name differs, change it **everywhere** it appears (Search & Replace over the
file, e.g. `sensor.shelly3mpro_total_active_power`).

### 3.2 Inverter capacities

In `sensor.ems_inverter_capacity` there is one map at the top of the `state:` template:

```jinja
{%- set caps = {'number.hm1500_limit_nonpersistent_relative': 1500,
                'number.hms1600_a_limit_nonpersistent_relative': 1600,
                'number.hms1600_b_limit_nonpersistent_relative': 1600} -%}
```

The numbers are the **AC rating** of each inverter (not the panel power). Add or remove rows
for your fleet — the loop divides by their sum, so this map is what makes the redistribu-
tion and the delivery check work.

---

## 4. Set the helpers

All 21 helpers are created by the package (Settings → Devices & services → Helpers).
Start with the defaults and change them in the order given in
[Tuning](#8-tuning-order).

| Helper | Default | Set it to |
|---|---|---|
| `input_number.ems_max_charge_power` | 2500 W | your real charge power: `min(DVCC A, BMS CCL) × battery voltage` |
| `input_number.ems_soc_stop` | 100 % | leave at 100 unless you deliberately want to stop charging earlier |
| `input_number.ems_grid_bias` | 20 W | keep small; raise if the meter is noisy |
| `input_number.ems_settle_seconds` | 12 s | how long your ESS needs to react (see tuning) |
| `input_number.ems_max_step_pct` | 10 % | higher = faster charging, bigger export transients |
| `input_number.ems_hysteresis_pct` | 2 % | raise to reduce writes |
| `input_number.ems_export_tolerance` | 150 W | export that is ignored (meter noise); do not set it to 0 |
| `input_number.ems_export_grace` | 60 s | how long an export may last before the charge offer is reduced |
| `input_number.ems_reprobe_seconds` | 900 s | how often the charge offer is probed upwards again |
| `input_number.ems_failsafe_pct` | 0 % | `0` stops the inverters (no export possible) |
| `input_number.ems_meter_tolerance` | 100 W | allowed difference between the two meters |
| `input_number.ems_manual_pct` | -1 | `-1` = off, otherwise a fixed percentage |

The remaining helpers are internal (`ems_charge_allowance`, `ems_export_ticks`,
`ems_delivery_short`), are timestamps (`ems_last_apply`, `ems_started_at`) or are the
switches/tests — leave them alone until
[CONFIGURATION.md](CONFIGURATION.md#numbers) tells you otherwise.

---

## 5. Dashboard

Copy the ready-made card from
[CONFIGURATION.md](CONFIGURATION.md#dashboard) so that you can watch `EMS mode`,
`EMS limit target` (`active`, `capacity`), `EMS PV delivery` and `EMS grid power`
(`source`) while tuning.

---

## 6. Verify the first runs

1. **Trace**: Settings → Automations → *OpenDTU EMS loop* → ⋮ → Traces. Each run
   shows which trigger fired, whether the condition passed and the written value.
2. **Verbose log**: turn on `input_boolean.ems_verbose` and add

   ```yaml
   logger:
     logs:
       opendtu.zero_export: debug
   ```

   to `configuration.yaml`. Every write then logs a line such as:

   ```
   FULL | grid -234W [shelly] | solar 3000W | SoC 85% | bat 1200W | inv 3/3 cap 4700W | limit 86.9%
   ```

   With the battery-first law this line reads `house load (1566 W) + charge offer (2500 W)`,
   i.e. the array is allowed 4086 W; the log also writes a `CHARGE ALLOWANCE:` line whenever
the offer is reduced.

3. **Expected steady state**: `sensor.ems_grid_power` hovers around `+20 W`, the limit moves
   only when the load or the SoC changes, `sensor.ems_pv_delivery` stays near 100 % and
   `input_number.ems_charge_allowance` stays at your `EMS max charge power` while the battery
   accepts the full offer.

---

## 7. Fail-safe tests

Do all five, in this order, while watching the grid power:

| # | Action | Expected result |
|---|---|---|
| 1 | turn on **EMS test - simulate battery loss** | mode becomes `NO_BATTERY`, the limit drops to `load + 20 W`, the grid stays ≥ 0 |
| 2 | power off the **primary** meter | mode stays `FULL`, `source` becomes `victron`, control continues |
| 3 | power off **both** meters (or block the mqtt/tcp source for 5 min) | mode becomes `GRID_BLIND`, the limit becomes `EMS fail-safe limit` |
| 4 | disable `automation.opendtu_ems_loop` | within ~5 min the watchdog raises *fail-safe active* and writes the fail-safe limit |
| 5 | re-enable it and check the history | `sensor.ems_grid_power` only dips negative briefly when big loads switch off |

---

## 8. Tuning order

1. **`EMS settle time`** — measure how long the grid takes to return to the bias after a
   step. Set it slightly above that. Must stay below 15 s (the heartbeat).
2. **`EMS max step`** — if charging is too slow in the morning, raise it in 5 % steps. Watch
   the export transients after each increase.
3. **`EMS hysteresis`** — raise until the number of writes is comfortable (check
   `input_datetime.ems_last_apply` history).
4. **`EMS grid bias`** — raise only if your meter is noisy or you are billed for tiny
   imports.
5. **Export knobs (`EMS export tolerance`, `EMS export grace`, `EMS charge re-probe`)** —
   these decide how much patience the array gives the battery and the Victron. Symptoms and
their direction:
   * short exports repeated at every limit increase → raise `EMS export grace` (give the ESS
     more time) or lower `EMS max step`
   * a standing export while the battery is only partly charged → the loop will cut
     `EMS charge allowance` after the grace. If that happens while the battery really could
     take more, the tolerance is too small for your meter noise: raise it to 200 W
   * `EMS charge allowance` recovers too slowly after the battery freed up → lower
     `EMS charge re-probe` (e.g. 300 s)
6. **`EMS SoC stop charging`** — leave at 100 %. Lower it only if you deliberately want to
   stop charging before the pack is full (then the array covers the house load only from that
   SoC on).

---

## 9. Rollback

* Turn off `input_boolean.ems_enabled` (the loop stops writing immediately).
* Delete `<config>/packages/opendtu_ems.yaml`, remove `packages:` if unused, restart.
* Re-enable your old automation.
* The inverters keep their last non-persistent limit until the DTU or the inverter reboots,
  then fall back to the **persistent** limit — which is why that one must be low.
