# Dashboard

A ready-made Lovelace view that shows **PV inputs, operation modes, battery power and
SoC, and grid usage** at a glance: [`dashboards/ems-overview.yaml`](../dashboards/ems-overview.yaml).

---

## Which cards would I use?

All of the recommended cards are in the **HACS default repositories**, so you install them
with two clicks (HACS → Frontend → search the name → Download). No custom repository needed.

| Card | HACS repository | What it is for here |
|---|---|---|
| **Power Flow Card Plus** | `flixlix/power-flow-card-plus` | The centrepiece: animated flow grid ⇄ house ⇄ battery ⇄ PV, with the battery SoC in the battery circle. This is the card to use for "solar, battery, grid" in one picture. |
| **Mushroom** | `piitaya/lovelace-mushroom` | The status chips: EMS mode (with colour), grid meter in use, inverters online, delivery %, degraded flag. Also perfect for the control cards if you prefer a modern look. |
| **ApexCharts Card** | `RomRider/apexcharts-card` | The trend chart: PV / house load / grid / battery on the watt axis, the EMS limit (%) on a hidden second axis. |
| **Mini Graph Card** | `kalkih/mini-graph-card` | The compact battery SoC graph with colour thresholds. |

Optional, depending on taste:

| Card | HACS repository | When |
|---|---|---|
| Energy Flow Card Plus | `flixlix/energy-flow-card-plus` | Same flow picture, but with **kWh** (daily energy) instead of live power |
| Sankey Chart | `MindFreeze/ha-sankey-chart` | Energy distribution of the day as a Sankey diagram |
| Bubble Card | `Clooos/Bubble-Card` | Pop-ups / a mobile-first layout around the same entities |
| card-mod | `thomasloven/lovelace-card-mod` | Styling the built-in cards (e.g. hiding the zero line of the flow card) |
| Button Card | `custom-cards/button-card` | Fully custom buttons if Mushroom is not your style |

> No HACS? The flow card is the only piece that is hard to replace. You can get most of the
> value from built-in cards: a `tile` row for the modes, `history-graph` for the trends and
> `gauge` for the SoC.

---

## Install

### 1. Install the cards

HACS → **Frontend** → search each name → **Download** → reload the browser (HACS adds the
resources itself).

### 2. Add the view

**Option A — a new dashboard** (simplest)

1. Settings → Dashboards → **Add dashboard** → *New dashboard from scratch* → title "Energy".
2. Open it → ✏️ *Edit* → ⋮ → **Raw configuration editor**.
3. Paste the **whole** file [`dashboards/ems-overview.yaml`](../dashboards/ems-overview.yaml).

**Option B — into an existing dashboard**

Paste only the `cards:` list under the correct `views:` entry of your raw configuration, and
keep the indentation (two spaces under `- title:`).

**Option C — card by card**

Add card → **Manual** (bottom of the list) → paste a single card block. Start with the
`custom:power-flow-card-plus` block; it gives you the most value.

### 3. Adjust the two EDIT markers

Both are marked `EDIT` in the file and degrade gracefully if you leave them alone:

* **per-inverter power sensors** (`sensor.hm1500_ac_power`, `sensor.hms1600_a_ac_power`,
  `sensor.hms1600_b_ac_power`) — shown as secondary information in the PV circle, so you see
  the three inputs separately. Find the real ids in Developer tools → States (search
  `ac_power`). If the ids do not exist, the chip shows `3 inputs` instead.
* **Victron charge stage** (`sensor.victron_battery_state`) — appended to the mode chip
  ("FULL · Bulk") and optionally inside the battery circle. Use your Victron entity id
  (e.g. `sensor.victron_ess_battery_state`); while it is missing, only the EMS mode is shown.

---

## What the cards show

| Card | Entities |
|---|---|
| Energy flow | grid `sensor.ems_grid_power` (secondary info: which meter, `source`), PV `sensor.solarleistung_gesamt` (secondary info: the three inputs), battery `sensor.serialbattery_seplos_leistung` + SoC `sensor.serialbattery_seplos_ladestand`, house `sensor.ems_house_load` with `override_state: true` |
| Chips | `sensor.ems_mode` (+ Victron stage), `sensor.ems_limit_target`, **charge offer / push** (`allowance` and `charge_push` attributes of `sensor.ems_limit_target`), `sensor.ems_inverter_capacity` (`active`, W), `sensor.ems_pv_delivery`, `binary_sensor.ems_degraded` |
| Trends | `sensor.solarleistung_gesamt`, `sensor.ems_house_load`, `sensor.ems_grid_power` (green below 0 = export, red above = import), `sensor.serialbattery_seplos_leistung`, `sensor.ems_limit_target` (%) |
| SoC graph | `sensor.serialbattery_seplos_ladestand` |
| Controls | `input_boolean.ems_enabled`, `input_number.ems_manual_pct`, `input_boolean.ems_simulate_battery_loss`, bias / settle / step / hysteresis / fail-safe, SoC stop, export tolerance / grace, charge re-probe, `input_datetime.ems_last_apply` |
| Diagnostics | `sensor.ems_pv_delivery` attributes, `sensor.ems_inverter_capacity` attributes, `input_datetime.ems_started_at`, `input_number.ems_charge_allowance`, `input_number.ems_export_ticks` |

### The charge offer chip

`charge_push` is the part of the limit that is meant for charging, and `allowance` is what the
battery is allowed to take right now:

* `push` ≈ `offer` → the array is working for the battery (normal while charging)
* `push` = 0 while the sun is up → either the learned `offer` has been cut (the battery is not
taking it, see
  [TROUBLESHOOTING](../docs/TROUBLESHOOTING.md#pv-is-cut-although-the-battery-could-take-it)) or
  `EMS SoC stop charging` is reached and the battery is measurably idle
* `offer` permanently below `EMS max charge power` → the battery (BMS CCL, CV phase,
  temperature) is the bottleneck, not the EMS

### Why the sign conventions work without `invert_state`

The flow card expects **grid**: negative = production (export), positive = consumption
(import), and **battery**: negative = discharging, positive = charging. The EMS sensors use
exactly these conventions, so nothing has to be inverted. If your battery sensor is the other
way round, add `invert_state: true` under `entities.battery`.

### House load instead of the calculated home circle

Without `home.entity`, the card derives the house consumption from the other circles. With
`sensor.ems_house_load` (computed in the package as `solar + grid − battery`) plus
`override_state: true`, the house circle shows the measured value and the flows add up
exactly. If you would rather see the card's own calculation, drop those two lines.

### Watts or kilowatts

`kilo_threshold: 10000` keeps the numbers in watts up to 10 kW, which suits a 4.7 kW PV +
14.6 kWh setup. Lower it to e.g. `1000` if you prefer kW.

---

## Reading the result

| Situation | What the dashboard shows |
|---|---|
| Normal sunny charging | PV ≈ house + charge power, grid a few W **positive**, `EMS limit` tracking the charge need, battery circle charging |
| Battery full | PV ≈ house load only, grid ≈ +20 W, battery ≈ 0 W, SoC high |
| Heavy clouds | delivery % below 100 %, PV low, grid importing, `EMS limit` pushed up |
| One inverter offline | `inverters 2/3` chip orange, the other two at 100 %, notification *PV capacity short* |
| Night | mode chip `NIGHT`, PV 0, battery covering the house (circle discharging), grid ≈ 0 |
| After a Home Assistant restart | mode chip `STARTING` for two minutes, `last write` stays old, then normal operation |
