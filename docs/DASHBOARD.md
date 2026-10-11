# Dashboards

Two ready-made Lovelace views ship with the package. They are deliberately split: one for
everyday use, one for tuning and troubleshooting.

| View | File | What it is for |
|---|---|---|
| **Energy** | [`dashboards/ems-overview.yaml`](../dashboards/ems-overview.yaml) | The board you leave open: live energy flow, status chips, the key figures, the day's history and the three controls you touch daily. |
| **EMS Expert** | [`dashboards/ems-expert.yaml`](../dashboards/ems-expert.yaml) | Diagnostics and tuning: the control law live, the learned charge offer, the ramp-guard internals, charts, and — **only while `input_boolean.ems_expert_mode` is on** — every adjustable parameter plus the maintenance/test actions. |

The HACS integration writes both into `<config>/opendtu_ems/` when it installs the package, so
after a HACS install there is nothing to copy.

---

## Which cards would I use?

Almost everything is a **built-in** card. Only four HACS downloads are used, all in the
**HACS default repositories**, so they install with two clicks (HACS → Frontend → search the
name → Download). No custom repository needed.

| Card | HACS repository | What it is for here |
|---|---|---|
| **Power Flow Card Plus** | `flixlix/power-flow-card-plus` | The centrepiece of the overview: animated flow grid ⇄ house ⇄ battery ⇄ PV, with the battery SoC in the battery circle. |
| **Mushroom** | `piitaya/lovelace-mushroom` | The status chips and — on the expert board — the number cards (sliders) for every tuning helper. |
| **ApexCharts Card** | `RomRider/apexcharts-card` | The trend charts: PV / house / grid / battery on the watt axis, the EMS limit (%) on a hidden second axis, and charge power vs limit vs learned offer. |
| **Mini Graph Card** | `kalkih/mini-graph-card` | The compact battery SoC graph and the PV-delivery graph with colour thresholds. |

Everything else — `gauge`, `history-graph`, `entities`, `grid`, `markdown`, `conditional` —
is built into Home Assistant.

Optional, depending on taste:

| Card | HACS repository | When |
|---|---|---|
| Energy Flow Card Plus | `flixlix/energy-flow-card-plus` | Same flow picture, but with **kWh** (daily energy) instead of live power |
| Sankey Chart | `MindFreeze/ha-sankey-chart` | Energy distribution of the day as a Sankey diagram |
| Bubble Card | `Clooos/Bubble-Card` | Pop-ups / a mobile-first layout around the same entities |
| card-mod | `thomasloven/lovelace-card-mod` | Styling the built-in cards |
| Button Card | `custom-cards/button-card` | Fully custom buttons if Mushroom is not your style |

> No HACS? The flow card is the only piece that is hard to replace. The overview still works
> without it: `tile`, `heading` and `history-graph` cover the rest.

---

## 1. Install the cards

HACS → **Frontend** → search each name → **Download** → reload the browser (HACS adds the
resources itself).

## 2. Add the views

**Option A — two new dashboards** (simplest)

1. Settings → Dashboards → **Add dashboard** → *New dashboard from scratch* → title "Energy".
2. Open it → ✏️ *Edit* → ⋮ → **Raw configuration editor** → paste the **whole**
   [`dashboards/ems-overview.yaml`](../dashboards/ems-overview.yaml).
3. Repeat for a second dashboard ("EMS Expert") with
   [`dashboards/ems-expert.yaml`](../dashboards/ems-expert.yaml).

**Option B — into one existing dashboard**

Paste each file's `cards:` list as a *new view* under the existing `views:` key, and keep the
indentation (two spaces under `- title:`). Give the second view a different `path`.

**Option C — card by card**

Add card → **Manual** (bottom of the list) → paste a single card block. Start with the
`custom:power-flow-card-plus` block; it gives you the most value.

## 3. Turn on expert mode

The expert board shows diagnostics immediately, but the **tuning card and the maintenance card
stay hidden** until `input_boolean.ems_expert_mode` is on — flip it with the switch at the top
of the board. That way the same dashboard can be left open on a wall tablet: without the switch
it is a read-only diagnostics page, and a stray tap cannot change a tuning value.

The switch is only a dashboard gate. The control loop never reads it, and every helper stays
reachable under **Settings → Devices & services → Helpers** either way.

## 4. Adjust the two EDIT markers

Both are marked `EDIT` in the overview file and degrade gracefully if you leave them alone:

* **per-inverter power sensors** (`sensor.hm1500_ac_power`, `sensor.hms1600_a_ac_power`,
  `sensor.hms1600_b_ac_power`) — shown as secondary information in the PV circle. Find the real
  ids in Developer tools → States (search `ac_power`). If the ids do not exist, the chip shows
  `3 inputs` instead.
* **Victron charge stage** (`sensor.victron_battery_state`) — appended to the mode chip
  ("FULL · Bulk"). Use your Victron entity id; while it is missing, only the EMS mode is shown.

---

## What the cards show

### Overview (`ems-overview.yaml`)

| Card | Entities |
|---|---|
| Energy flow | grid `sensor.ems_grid_power` (secondary info: which meter, `source`), PV `sensor.solarleistung_gesamt` (secondary info: the three inputs), battery `sensor.serialbattery_seplos_leistung` + SoC `sensor.serialbattery_seplos_ladestand`, house `sensor.ems_house_load` with `override_state: true` |
| Chips | `sensor.ems_mode` (+ Victron stage), `sensor.ems_limit_target`, **charge offer / push** (`allowance` and `charge_push` attributes), `sensor.ems_inverter_capacity` (`active`, W), `binary_sensor.ems_degraded` |
| Gauges | `sensor.serialbattery_seplos_ladestand`, `sensor.ems_limit_target`, `sensor.ems_battery_charge_power`, `sensor.ems_charge_power_limit` |
| Trends | `sensor.solarleistung_gesamt`, `sensor.ems_house_load`, `sensor.ems_grid_power` (green below 0 = export, red above = import), `sensor.serialbattery_seplos_leistung`, `sensor.ems_limit_target` (%) |
| SoC graph | `sensor.serialbattery_seplos_ladestand` |
| Daily controls | `input_boolean.ems_enabled`, `input_boolean.ems_automatic`, `input_number.ems_manual_pct`, `input_boolean.ems_expert_mode`, `input_datetime.ems_last_apply` |
| Diagnostics | `sensor.ems_pv_delivery` attributes, `sensor.ems_inverter_capacity` attributes, `sensor.ems_battery_charge_power` (+ `source`), `sensor.ems_charge_power_limit`, `input_datetime.ems_started_at` |

### Expert (`ems-expert.yaml`)

| Card | Entities |
|---|---|
| Status | `input_boolean.ems_expert_mode`, `input_boolean.ems_enabled`, `input_boolean.ems_automatic`, `sensor.ems_mode`, `binary_sensor.ems_degraded`, both `input_datetime`s |
| Control law (markdown) | house load, grid, solar, `sensor.ems_limit_target` with its `allowance` / `charge_push` attributes |
| History graph | `sensor.ems_limit_target`, `sensor.ems_grid_power`, `sensor.ems_battery_charge_power` |
| Battery & charge power | `sensor.ems_battery_charge_power`, `sensor.ems_charge_power_limit`, `input_number.ems_charge_allowance`, the Seplos power and `sensor.serialbattery_seplos_dc_bus_spannung` / `sensor.venus_dc_batterie_stromstarke` for comparison |
| Charge learning | `input_number.ems_bat_prev` (baseline), `input_number.ems_export_ticks`, `ems_export_tolerance`, `ems_export_grace`, `ems_reprobe_seconds` |
| Charge chart | `sensor.ems_battery_charge_power`, `sensor.ems_charge_power_limit`, `input_number.ems_charge_allowance` |
| Inverters | `sensor.ems_inverter_capacity`, `sensor.ems_pv_delivery`, `sensor.ems_grid_power`, `sensor.ems_house_load` + a delivery mini-graph |
| **Expert mode only** | every `input_number.ems_*` as a Mushroom slider, grouped: charge power, grid & fail-safe, charge-acceptance learning, reaction speed |
| **Expert mode only** | `input_boolean.ems_verbose`, `input_boolean.ems_simulate_battery_loss`, `sensor.ems_bundle`, `automation.opendtu_ems_loop`, `automation.opendtu_ems_watchdog`, `automation.opendtu_ems_boot`, and buttons for `script.ems_set_defaults` (with a confirmation) and `script.ems_apply` |

### Reading the charge offer

`charge_push` is the part of the limit that is meant for charging, and `allowance` is what the
battery is allowed to take right now:

* `push` ≈ `offer` → the array is working for the battery (normal while charging);
* `push` = 0 while the sun is up → either the learned `offer` has been cut (the battery is not
  taking it — check `sensor.ems_battery_charge_power` against
  `sensor.ems_charge_power_limit`) or `EMS SoC stop charging` is reached and the battery is
  measurably idle;
* `offer` permanently below the charge power limit → the battery (BMS CCL, CV phase,
  temperature) is the bottleneck, not the EMS. Compare
  `sensor.ems_battery_charge_power` and `sensor.ems_charge_power_limit` on the charge chart:
  **if the charge power is climbing, the offer must not be cut** — that is exactly what
  `input_number.ems_bat_prev` (the baseline) and the export grace now guarantee.
