# Troubleshooting

Work through the symptom table first, then the detail sections.

| Symptom | Look at | Likely cause |
|---|---|---|
| `sensor.ems_mode` is `OFF` | `input_boolean.ems_enabled` | master switch off |
| `sensor.ems_mode` is `GRID_BLIND` | `sensor.ems_grid_power` → `source` | both meters dead, renamed or stale |
| `sensor.ems_mode` is `NO_BATTERY` | `sensor.serialbattery_seplos_*` | SoC/power sensor unavailable, stale or out of range |
| Limit stays at `0 %` | mode, `input_number.ems_failsafe_pct` | `GRID_BLIND` fail-safe, or `ems_manual_pct = 0` |
| Limit never changes | trace of the loop, `input_datetime.ems_last_apply` | condition blocked (settle/hysteresis) or the loop errors |
| Exports after load steps | `history` of `sensor.ems_grid_power` | `EMS max step` too high / `EMS settle time` too short |
| Charging is slow | DVCC, BMS CCL, `EMS max charge power`, taper helpers | charge current limited by the Victron side, or the taper starts too early |
| Redistribution does not happen | `active` attribute | the offline inverter's limit entity stays available → add power sensors |
| *PV capacity short* notification | OpenDTU inverter page | an inverter is offline / its limit entity disappeared |
| *PV under-delivering* notification | `sensor.ems_pv_delivery` attributes | inverter not delivering **or** heavy clouds/shading |
| *fail-safe active* notification | `automation.opendtu_ems_loop` | the loop stopped writing (disabled, error, restart) |

---

## The loop does not write

Check in this order:

1. **Trace** — Settings → Automations → *OpenDTU EMS - control loop* → ⋮ → Traces. The last
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

## Charging is slower than expected

The loop cannot change how fast the battery charges; it only decides how much PV is allowed.
Check:

* DVCC max charge current (50 A in the reference installation) is set on the GX device.
* The BMS charge current limit (CCL) is not the bottleneck — the BMS reduces it in cold
  weather or near full.
* `EMS max charge power` matches `min(DVCC, CCL) × voltage`.
* The SoC taper (`taper from` 90 %, `full` 99 %) is not stopping the push too early. Watch
  `bat` in the verbose log against `EMS max charge power`.
* `sensor.ems_mode` is `FULL` (not `NO_BATTERY`) while the battery charges.

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
| `opendtu_ems_capacity` | fewer than 3 inverters reachable, the rest already at 100 %, grid still imports |
| `opendtu_ems_delivery` | commanded output stays below 70 % and > 800 W short for ~6 min |

## Debugging aids

* `input_boolean.ems_verbose` + `logger: logs: opendtu.zero_export: debug` → one line per run.
* `input_boolean.ems_simulate_battery_loss` → tests the `NO_BATTERY` path.
* `input_number.ems_manual_pct` → writes a fixed percentage, ignoring all sensors
  (`-1` restores automatic operation).
* `input_datetime.ems_last_apply` → history shows exactly when and how often the loop wrote.

## Starting over

1. `input_boolean.ems_enabled` → off (stops all writes).
2. Delete the package file and the helpers it created (Settings → Helpers → *EMS*).
3. Restart Home Assistant and re-enable your previous automation.
