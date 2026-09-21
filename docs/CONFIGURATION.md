# Configuration reference

Everything the package creates, what it means and how to tune it.

> The reasoning behind the control law, the mode ladder and the acceptance learning is in the
> wiki: [Architecture Concept Document](https://github.com/acdcnow/opendtu-ems/wiki/Architecture-Concept-Document)
> and [Software Design Document](https://github.com/acdcnow/opendtu-ems/wiki/Software-Design-Document)
> (component design, formulas, invariants). The superseded 1.4.x behaviour is documented in
> [Control law 1.4.x (archived)](https://github.com/acdcnow/opendtu-ems/wiki/Archive-1.4-Control-Law).

---

## Modes

| Mode | Entered when | Target written |
|---|---|---|
| `FULL` | SoC and battery power are fresh and plausible, at least one grid meter is alive, solar is readable, at least one inverter is reachable | `house load + allowed charge power + bias`, clamped to the reachable capacity. The allowed charge power is `EMS max charge power` capped by the learned `EMS charge allowance`; the measured export is not part of the formula |
| `STARTING` | less than `EMS start grace` (default 120 s) since the Home Assistant start event | nothing — waiting for the first sensor values and for the ESS to boot |
| `NIGHT` | `sun.sun` is `below_horizon` **and** PV is below 200 W | nothing — solar-powered inverters sleep, this is a normal standby state |
| `DTU_BLIND` | **no** inverter limit entity is readable (OpenDTU powered off, MQTT broker down, entity ids changed) | nothing — the loop stops writing and the watchdog raises *no inverter reachable* |
| `GRID_BLIND` | neither grid meter has a value and a recent update, **or** the solar sensor is not readable while inverters are reachable (the house load cannot be computed) | `input_number.ems_failsafe_pct` (default 0 %) |
| `NO_BATTERY` | SoC or battery power missing / stale (> 120 s power, > 300 s SoC) / outside 0–100 %, or the test switch is on | `load + bias` (zero export only — the charge term is dropped) |
| `OFF` | `input_boolean.ems_enabled` is off | nothing is written |

Mode is published as `sensor.ems_mode`; `binary_sensor.ems_degraded` is on for everything
except `FULL`/`OFF` and also when the grid value comes from the backup meter or the two
meters disagree.

> The EMS entities (helpers, sensors, script, automations) are plain Home Assistant entities.
> They exist regardless of OpenDTU — a DTU that is switched off only makes the
> `number.*_limit_nonpersistent_relative` entities unavailable, which turns
> `sensor.ems_inverter_capacity` into 0 and the mode into `DTU_BLIND`.

---

## Helpers

### Switches

| Helper | Default | Meaning |
|---|---|---|
| `input_boolean.ems_enabled` | on | master switch; off = no writes at all |
| `input_boolean.ems_simulate_battery_loss` | off | forces `NO_BATTERY` to test the fail-safe |
| `input_boolean.ems_verbose` | off | writes a diagnostic line per run to the log |

### Numbers

| Helper | Default | Unit | Meaning / tuning |
|---|---|---|---|
| `ems_manual_pct` | -1 | % | `-1` = automatic. `0…100` writes this percentage to all inverters, ignoring every sensor. `0` therefore switches the inverters off. |
| `ems_grid_bias` | 20 | W | The grid target. The loop aims at a small *import* so that it never sits exactly on the export boundary. Raise if your meter is noisy. |
| `ems_hysteresis_pct` | 2 | % | Minimum change before a write happens. Raise to reduce writes, lower to react to smaller deviations. |
| `ems_max_charge_power` | 2500 | W | The charge power the array may feed the battery with. Derive it as `min(DVCC max A, BMS CCL) × battery voltage`. The learned `EMS charge allowance` can only go below it. |
| `ems_soc_stop` | 100 | % | At/above this SoC the EMS stops *asking* for charge power and only covers the house load. It counts only while the battery is measurably not charging, so a wrong or stuck SoC cannot cut the array. `100` = never stop. |
| `ems_charge_allowance` | 2500 | W | **Learned, written by the loop.** The charge power the battery has been observed to accept. Cut when a lasting export shows that the battery cannot use the offer, reset to `EMS max charge power` whenever the battery discharges, probed upwards again after `EMS charge re-probe`. Set it by hand to cap the charge power manually. |
| `ems_export_tolerance` | 150 | W | An export up to this is ignored (meter noise, Victron ramp, probe step). Do not set it to 0. |
| `ems_export_grace` | 60 | s | How long an export above the tolerance may last before the battery is assumed not to take the offered power. Raise it if your Victron needs longer to ramp. |
| `ems_export_ticks` | 0 | – | Internal counter of 15 s ticks with an export above the tolerance. 0 = quiet, ≥ the grace in ticks = the allowance is being cut. |
| `ems_reprobe_seconds` | 900 | s | After this long without an export the allowance is probed upwards (×1.5), so a battery that frees up is charged at full power again. `3600` = quieter grid, slower recovery. |
| `ems_failsafe_pct` | 0 | % | Written in `GRID_BLIND` and by the watchdog. `0` stops the inverters (export impossible); raise to 2 % only if your inverters oscillate at 0 %. |
| `ems_meter_tolerance` | 100 | W | Allowed difference between the two grid meters before the smaller (more export) value wins. |
| `ems_settle_seconds` | 12 | s | Wait time after every write, so the loop does not chase the ESS ramp. Must be **< 15 s** (the heartbeat). |
| `ems_max_step_pct` | 10 | % | Maximum *increase* per write. Decreases are always immediate. |
| `ems_delivery_short` | 0 | – | Internal counter of the delivery check. Do not edit (a manual change only silences/triggers the notification). |
| `ems_start_grace` | 120 | s | After a Home Assistant start nothing is written for this long, so the sensors deliver their first values and the ESS can finish booting. Raise it if your Victron needs longer than 2 minutes. |

### Date/time

| Helper | Meaning |
|---|---|
| `input_datetime.ems_last_apply` | Timestamp of the last write. Used for the hysteresis (`180 s` re-assert) and as the watchdog heartbeat. |
| `input_datetime.ems_started_at` | Timestamp of the last Home Assistant start, written by `automation.opendtu_ems_boot`. Drives the `STARTING` mode. |

---

## Sensors

| Entity | State | Attributes |
|---|---|---|
| `sensor.ems_grid_power` | grid power in W (positive = import) | `source` = `shelly` / `victron` / `disagree` / `none`, `shelly`, `victron` |
| `sensor.ems_mode` | `FULL` / `NO_BATTERY` / `GRID_BLIND` / `OFF` | – |
| `sensor.ems_inverter_capacity` | reachable inverter capacity in W | `active` = number of inverters counted, `current_pct` = value currently set on them |
| `sensor.ems_pv_delivery` | produced / commanded output in % | `expected_w`, `actual_w` |
| `sensor.ems_house_load` | house consumption in W (`solar + grid - battery`) | – |
| `sensor.ems_limit_target` | percentage to write | `mode`, `grid`, `solar`, `active`, `capacity`, `allowance` (W offered to the battery), `charge_push` (W asked from the array for charging) |
| `binary_sensor.ems_degraded` | `on` when degraded | – |

---

## Grid meter arbitration

Both meters are read every cycle.

* Both alive and within `EMS meter tolerance` → the **primary** (Shelly) is used.
* Primary dead/frozen (> 300 s without an update) → the **backup** (Victron) is used, the
  mode stays `FULL` and `binary_sensor.ems_degraded` turns on.
* Both alive but differing by more than the tolerance → the **smaller** value (the one
  showing more export) is used and the source becomes `disagree`. Erring towards less PV can
  never cause an export.
* Both dead/frozen → the sensor becomes `unavailable` and the mode becomes `GRID_BLIND`.

> The backup only helps if it measures the **same** metering point and uses the same sign.
> Verify by switching on a big load: both meters must move by the same amount.

---

## Deliberate design decisions

### Battery first: the target never contains the measured export

The target is feed forward:

```
target_PV = solar + grid + (allowed charge power − battery power) + bias
```

Since `solar + grid` is the house load plus what the battery currently takes, this is
`house load + allowed charge power + bias`. There is no feedback of the measured export, and
that is deliberate: in 1.4.x the charge term was dropped whenever the grid exported, so
every export — the Victron ramp, a load switching off, a lagging meter — cut the array to
`house load + the charge power it was already taking`, which meant the charge power could
never grow. That is the "the sun is cut although the battery could take it" failure.

### The charge allowance is learned, not configured

How much charge power the battery really accepts is a property of the battery, not of the
array: BMS current limit, cell temperature, the CV phase, and the ESS ramp all change it.
The loop therefore observes it:

| Situation | Reaction |
|---|---|
| export above `EMS export tolerance` for more than `EMS export grace`, battery takes measurably less than offered | `EMS charge allowance` → what the battery is taking (at most a 50 % cut per step) |
| battery discharges | `EMS charge allowance` → `EMS max charge power` (a new charge cycle starts) |
| no export for `EMS charge re-probe` | `EMS charge allowance` ×1.5, capped at `EMS max charge power` |
| manual override active | nothing (the override also freezes the learning) |

The price is explicit: every upward probe offers slightly more than the battery takes, so a
refused probe exports up to the probe step for up to `EMS export grace` seconds. With the
defaults that is a few Wh per 15 minutes while the battery is in its current-limited phase —
the trade for never starving the battery. Raise `EMS charge re-probe` if you prefer a
quieter grid.

### Signed battery power

`deficit = charge_limit − battery_power` uses the raw **signed** value, so a discharging
battery increases the target as well. A value clamped at zero would under-produce whenever
the battery is discharging.

### Relative (percentage) limits

One percentage drives a mixed fleet correctly (a 1500 W HM next to two 1600 W HMS), keeps
every inverter inside its own rating, and updates are reported immediately — the absolute
variant can take up to ~4 minutes to appear in OpenDTU, which would break the loop.

### Rate limiting for the ESS ramp

An instant PV increase can be exported while the ESS has not started charging yet. Hence:
`EMS max step` caps increases, `EMS settle time` spaces writes out, and only a real export
(> 500 W) bypasses the settle time. Decreases are never limited, because less PV can never
cause an export. A *transient* export while the battery is ramping does not curtail the
array any more — it is absorbed by `EMS export tolerance` and `EMS export grace`.

### 180 s re-assert

The non-persistent limit is re-written at least every 3 minutes. This covers firmware that
drops the limit (Hoymiles 2.0.4 reports 100 % after ~4 min without an update) and DTU
hiccups.

---

## Optional: per-inverter power sensors

Availability alone cannot detect an inverter that stays `available` but produces nothing.
The delivery check reports it (with a delay and a caveat), and it cannot identify which
inverter is at fault.

To make the loop *exclude* a dead inverter itself, extend the caps map in
`sensor.ems_inverter_capacity`. OpenDTU publishes per inverter (MQTT topics):
`<serial>/status/reachable`, `<serial>/status/producing`, `<serial>/0/power`. Find the
resulting Home Assistant entity IDs in Developer tools → States (search for `ac_power` or
`reachable`) and use them like this:

```jinja
{%- set caps = {'number.hm1500_limit_nonpersistent_relative':
                   {'w': 1500, 'power': 'sensor.hm1500_ac_power'},
                'number.hms1600_a_limit_nonpersistent_relative':
                   {'w': 1600, 'power': 'sensor.hms1600_a_ac_power'},
                'number.hms1600_b_limit_nonpersistent_relative':
                   {'w': 1600, 'power': 'sensor.hms1600_b_ac_power'}} -%}
{%- set ns = namespace(cap=0, n=0, cur=-1) -%}
{%- for e, i in caps.items() if has_value(e) -%}
  {#- only drop an inverter that produces nothing while the sun is up -#}
  {%- set lost = has_value(i.power) and (states(i.power) | float(0)) < 5
                 and (states('sensor.solarleistung_gesamt') | float(0)) > 200 -%}
  {%- if not lost -%}
    {%- set ns.cap = ns.cap + i.w -%}
    {%- set ns.n = ns.n + 1 -%}
    {%- if ns.cur < 0 -%}{%- set ns.cur = states(e) | float(-1) -%}{%- endif -%}
  {%- endif -%}
{%- endfor -%}
```

**Never** exclude an inverter purely because it reads 0 W — at night all of them do, and the
fail-safe would shut the system down.

---

## Absolute instead of relative limits

If your OpenDTU only exposes `..._limit_nonpersistent_absolute`, the single-percentage
approach does not work: each inverter needs its own watt value proportional to its rating,
e.g.

```jinja
value_for_hm1500 = target_total * 1500 / cap_total
```

and the three writes in `script.ems_apply` need those individual values (via `repeat` over a
list of `{entity, watts}` pairs). Also remember that absolute limits may take up to four
minutes to be reflected in OpenDTU.

---

## Dashboard

Minimal control card:

```yaml
type: entities
title: OpenDTU EMS
entities:
  - entity: sensor.ems_mode
  - entity: sensor.ems_grid_power
  - entity: sensor.ems_limit_target
  - entity: sensor.ems_pv_delivery
  - entity: sensor.ems_inverter_capacity
  - entity: binary_sensor.ems_degraded
  - entity: input_boolean.ems_enabled
  - entity: input_number.ems_manual_pct
  - entity: input_datetime.ems_last_apply
```

Live status line (mode, active meter, inverters, delivery):

```yaml
type: markdown
content: >-
  **{{ states('sensor.ems_mode') }}** ·
  meter: {{ state_attr('sensor.ems_grid_power', 'source') }} ·
  inverters: {{ state_attr('sensor.ems_inverter_capacity', 'active') }}/3
  ({{ states('sensor.ems_inverter_capacity') }} W) ·
  limit: {{ states('sensor.ems_limit_target') }} % ·
  delivery: {{ states('sensor.ems_pv_delivery') }} %
```

Tuning graph (grid vs. limit vs. delivery):

```yaml
type: history-graph
hours_to_show: 12
entities:
  - entity: sensor.ems_grid_power
  - entity: sensor.solarleistung_gesamt
  - entity: sensor.ems_limit_target
  - entity: sensor.ems_pv_delivery
```

The most useful thing to watch while tuning is `sensor.ems_grid_power`: it should stay
slightly positive and only dip negative for a few seconds after big loads switch off.
