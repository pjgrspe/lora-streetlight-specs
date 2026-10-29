# 05 — Fail-Safe Behaviour

| | |
|---|---|
| **Spec** | 05 — Fail-safe behaviour table |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-29 |
| **Owner** | pgorospe |
| **Reviewers** | Gateway hardware developer (for the client), device developer (both sign) |
| **Status** | Draft. Not frozen |

What every part of the system does when something fails, and what the lights do as a result. The hardware developer signs this for the client, because it defines the safety behaviour of the road. The device developer signs it because layer 3 (the device's own fallback) and the DALI driver settings live in their firmware.

Shared conventions are in [00](00-common-frame-and-conventions.md). Timers assume the default cycle of 120 s ([04](04-channel-plan-and-airtime.md)). If the cycle is changed, timers defined in cycles scale with it.

## 1. The rule

> **Any failure whose effect on lighting is ambiguous resolves to LIGHTS ON at 100% during the local astronomical night.**

A dark road is a safety and liability problem. Wasted energy is only a cost. Every decision below follows from this rule.

**What "lights ON" means by day.** Every fallback layer still switches by the astronomical schedule (sunset/sunrise computed locally from latitude and longitude). So a failure that happens by day keeps the lights **off until dusk**, then switches them on at 100% for the whole night. There are two exceptions where lights go ON whatever the time of day:

- **Clock untrusted** (the node doesn't know the time, so it can't know whether it's day): 100% ON until time is re-established.
- **DALI link lost at the driver** (layer 4): the driver doesn't know the time either. It goes to its System Failure Level.

## 2. Five independent layers

| Layer | If this fails… | …this keeps the road lit | Owner |
|---|---|---|---|
| 1 | Local Monitoring Server | Master runs the schedules and keeps all overrides that haven't expired | pgorospe |
| 2 | Master Gateway | Each Slave runs its section on its own astronomical schedule | pgorospe |
| 3 | Slave Gateway, or a device's link to it | Each device runs its own cached astronomical fallback schedule | **Device developer** |
| 4 | Device, or its DALI link to the driver | The DALI driver goes to its stored **System Failure Level** (100%) | Driver setting, configured by the device |
| 5 | Mains on a section or phase | Nothing can light the road. The system's job is a fast, accurate alarm | pgorospe (alarm) |

Dual radios reduce how often layers 2 and 3 are needed, by covering radio, antenna and coax faults. They don't replace the layers: a whole-box failure (power supply, lightning, MCU) still falls through to the next layer.

## 3. Shared timers (defaults, cycle = 120 s)

| Timer | Value | Used by |
|---|---|---|
| Tier-1 radio failover | 3 consecutive missed exchanges on the primary radio → switch to standby | Master, Slave |
| Tier-1 radio failback | Primary clean for 5 cycles (10 min) → switch back | Master, Slave |
| Slave → `DEGRADED` | 3 missed tier-1 beacons (6 min) | Slave |
| Slave → `AUTONOMOUS` | 30 missed tier-1 beacons (60 min) | Slave |
| Device → try other channel | 2 missed beacons on its home channel | Device |
| Device → `fallback_mode` | 3 missed cycles on both of the section's channels (6 min) | Device |
| Device declared offline | 3 missed reports (6 min) | Slave, Master |
| Server declared lost | No valid Modbus frame for 30 min (configurable) | Master |
| Override maximum lifetime | 720 min (12 h) | All |
| Command job lifetime | 10 min (server → master job TTL). Radio commands carry `execute_at` and `not_after` | Master, Slave, Device |

## 4. Fail-safe behaviour table

**Alarm names in this table are the server alarm codes in [07 §6](07-server-data-model.md)**, which also lists the event codes behind each one.

"Night" and "day" mean the node's own astronomical schedule. "Schedule" means the normal astronomical on/off with the configured dimming profile. "Fallback" means the same astronomical times at **100%, no dimming**.

| # | Failure | Detection + timer | Server | Master | Slave | Device | DALI driver | Lights | Alarm | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 | **Server down / PC off** | Master: no valid Modbus frame for 30 min | — (down) | Runs schedules; keeps unexpired overrides; buffers events with original timestamps | Normal (`SYNCED`) | Normal | Normal | Schedule, unchanged | `SERVER_LOST` (Master event `0x8013`, read by the server on reconnect) | Server reconnects; master replays the buffered events oldest first. No manual step |
| F2 | **RS485 cut** | Server: link down after 5 consecutive failed polls ([07](07-server-data-model.md) POL-4). Master: as F1 | Marks master offline; every device shown `STALE` with its age | As F1 | Normal | Normal | Normal | Schedule, unchanged | `MASTER_OFFLINE` at server | Link restored; as F1 |
| F3 | **Master dead** (PSU, MCU, surge) | Server: Modbus timeouts. Slaves: no tier-1 beacon on either radio | Marks master and site offline; all data `STALE` | — (dead) | `DEGRADED` after 6 min: keeps unexpired overrides. `AUTONOMOUS` after 60 min: **discards all overrides**, runs its own astronomical schedule, buffers events | Normal: still served by its slave | Normal | Schedule until 60 min, then **fallback (100%) at night** | `MASTER_OFFLINE` at server | Master restarts or the spare is fitted. Slaves rejoin (`REJOINING`), master compares config versions and pushes only differences. Divergence logged as an event, **never silently overwritten** |
| F4 | **Master primary radio failed** (radio, antenna, coax) | Master: 3 missed exchanges on primary | Shows failover state | **Switches all tier-1 traffic to standby**; P0 still sent on both | Follows the master to the standby channel | Normal | Normal | Unchanged | `RADIO_FAILOVER` (Master, which radio) | Failback after primary is clean for 10 min. Alarm cleared with an event |
| F5 | **Master standby radio failed** | Missed heartbeats on standby (heartbeat every cycle) | Shows standby down | Keeps running on primary | Normal | Normal | Normal | Unchanged | `STANDBY_RADIO_DOWN` | Repair. Standby heartbeat resumes; alarm clears |
| F6 | **Slave dead** (PSU, MCU, surge) | Master: no SUMMARY for 3 cycles. Devices: no beacon on either channel | Section shown offline; devices `STALE` | Marks section offline; can't reach it | — (dead) | Tries the other channel after 2 missed beacons; **`fallback_mode` after 6 min**: own astronomical schedule at 100% | Normal | **Fallback (100%) at night**, per device | `SECTION_LOST` (section) | Slave restarts with its persisted device table and slot table; devices resume in their slots **without rejoining as a mass** (rejoin in own slot). Overrides are not restored |
| F7 | **Slave upstream radio failed** | Slave: 3 missed exchanges on its primary up radio | Shows failover | Hears the slave on standby | **Switches tier-1 to standby radio** | Normal | Normal | Unchanged | `RADIO_FAILOVER` (slave, which radio) | Failback after 10 min clean |
| F8 | **Both slave upstream radios failed** | As F3, but only for this section | Section `STALE` | Section `LOST` after 3 cycles | `DEGRADED` → `AUTONOMOUS` as F3 | Normal | Normal | Schedule until 60 min, then fallback (100%) at night | `SECTION_LOST` | Repair; slave rejoins as F3 |
| F9 | **Slave downstream radio failed** (one of two) | Slave: radio health check / no reports on that channel | Shows single-channel mode | No change: the slave's tier-1 slot stays where it is | **Single-channel mode**: surviving radio serves all slots; beacon flag set; the slave starts its cell cycle 10 s earlier so its tier-1 slot still falls in its quiet window ([04](04-channel-plan-and-airtime.md) §6.2, [02](02-tier1-protocol.md) §15) | Devices on the dead channel miss 2 beacons, move to the other channel and re-register | Normal | Unchanged (a few devices may be in fallback for a few minutes while they move) | `CELL_SINGLE_CHANNEL` | Repair; slave returns devices to their home channel at the next slot-map update |
| F10 | **Device lost its slave** (local link only) | Device: 3 missed cycles on both channels. Slave: 3 missed reports | Device `OFFLINE` | Device offline in register map | Device offline | **`fallback_mode`**: own astronomical schedule at 100%; keeps trying to rejoin | Normal | **Fallback (100%) at night** for that pole | `DEVICE_OFFLINE` | Beacon heard again → rejoin in own slot; normal schedule resumes |
| F11 | **Device dead, or DALI link fault** (short, open, water) | Slave: 3 missed reports (device dead), or device reports `dali_ok = 0` | Pole shown faulty | Records fault | Reports fault | If alive: retries DALI, reports `dali_ok = 0` and fault code | Loses control signal → **System Failure Level** after the DALI interruption time (⚠ ~550 ms, to verify against IEC 62386). ⚠ Only if the dead device actually interrupts the bus (O-05-7) | **100%, day and night** (uncontrolled) until repaired | `DEVICE_OFFLINE` or `DALI_BUS_FAULT` | Field repair. Device re-asserts DALI config on recovery |
| F12 | **DALI driver replaced** | Device: status shows missing short address / reset state | Starts `REPLACE_DRIVER` (operator action) | Forwards command | Forwards command | Addresses only unaddressed gear, programs the same short address, **re-pushes all config incl. fail-safe levels**, re-runs capability discovery | Factory state until configured: Power On = 254, so 100% on power-up | 100% until configured, then schedule | `CONFIG_MISMATCH` until done | Driver configured and verified by read-back; asset record updated |
| F13 | **Mains loss on a section or one phase** | Meter: zero voltage on phase(s); devices on that phase stop reporting all at once; slave infers a section-wide loss | Shows `NO_POWER` for affected poles, **distinct from commanded off** | Raises section alarm | Reports pattern (many devices lost together + meter phase loss) | — (unpowered) | — (unpowered) | **Dark** (nothing can light it) | `SECTION_POWER_LOST` (section, phase) | Mains restored → see F15/F16 |
| F14a | **Clock lost at the master** (RTC invalid after power loss) | RTC validity flag at boot | Offers time over Modbus (`SET_TIME`) | Marks `clock_trusted = 0` in beacon; accepts server time with `force`, or waits | Keeps its own RTC if valid; ignores an untrusted master clock | Normal | Normal | Unchanged while slaves keep their own time | `GW_CLOCK_UNTRUSTED` (Master) | Server time accepted (sanity-checked) |
| F14b | **Clock lost at a slave** | RTC invalid, and no trusted beacon yet | — | — | **`CLOCK_UNTRUSTED`: commands its section to 100% ON** (day or night) | Follows slave command | Normal | **100% ON**, any time | `GW_CLOCK_UNTRUSTED` (slave) | Trusted tier-1 beacon received → schedule resumes |
| F14c | **Clock lost at a device** | Device RTC invalid at boot, and no beacon | — | — | — | **100% ON** until a beacon gives time | Normal | **100% ON** for that pole, any time | `DEVICE_CLOCK_UNTRUSTED` (`restarted` + `clock_trusted = 0` in its first report) | First beacon heard → schedule |
| F15 | **Power restored at night** | Boot | Normal | Boots, resumes | Boots with persisted tables; resumes | Boots; DALI driver already at Power On Level; device takes over by schedule | **Power On Level = 254 (100%)** immediately at power-up | **100% at once**, then the schedule level once the device is running and has time | `SECTION_POWER_LOST` clears | Automatic. Devices rejoin in their own slots (no join storm) |
| F16 | **Power restored by day** | Boot | Normal | Normal | Normal | Device boots, knows time from its RTC or the first beacon → commands OFF | Power On Level = 254 until the device commands OFF (seconds) | Brief 100% flash, then **off** until dusk | `SECTION_POWER_LOST` clears | Automatic. If the device has no valid time, it stays 100% ON (F14c) |
| F17 | **Corrupted configuration** (storage CRC fail at boot) | CRC check on every record at boot | Shows `CONFIG_FAULT` alarm | Loads the second copy; if both bad, loads factory defaults and **runs fallback (100% at night)** | Same rule | Same rule (device developer) | Normal | Fallback (100%) at night until restored | `CONFIG_FAULT` | Registry and config restored from the server's mirror (re-assert configuration). No re-commissioning |
| F18 | **Airtime budget exhausted** (usually a retry storm) | Airtime ledger above (100% − P0 reserve) | Shows ledger state | Defers P1–P3; **P0 uses the 25% reserve** | Same | Same (device budget is far below its limit) | Normal | Unchanged. Telemetry slows; switching and emergency commands still work | `AIRTIME_HIGH` (box) | Automatic as the rolling 1-hour window clears |
| F19 | **Interference / jamming** | Noise floor in idle slots, rising packet loss, RSSI without valid packets | Shows link quality | Fails over to standby channel if the primary channel is the one jammed (F4) | Same on tier 1; single-channel mode if one cell channel is jammed (F9) | If both channels are jammed: `fallback_mode` (F10) | Normal | Unchanged, or fallback (100%) at night if a cell is fully jammed | `RF_DEGRADED` | Automatic when interference stops |

## 5. Rules that apply everywhere

1. **Overrides always expire.** Every override carries a lifetime, at most 720 min. An override with lifetime 0 lasts until the next schedule step. All overrides are cleared when a slave enters `AUTONOMOUS` and when any node reboots. A "dim to 30% for maintenance" can never outlive its purpose.
2. **Never a toggle.** Every command is absolute (`SET_LEVEL(level)`), never "toggle" or "step". A lost acknowledgement plus a retry can't invert the state.
3. **Commanded off ≠ no power.** A light switched off by command (`status.commanded_off = 1`) and a light that has lost mains (`NO_POWER`, inferred) never share a status code or a colour on the dashboard. Otherwise "section dark" can't be detected.
4. **Untrusted clock → 100% ON**, never off.
5. **The nightly switch costs no radio traffic.** Every slave and device switches by its own astronomical schedule. A congested or dead network can't prevent the lights coming on.
6. **A late command is not executed.** Every radio command carries `not_after`; a command received after it is dropped and reported as expired.
7. **Duplicates are harmless.** A command received twice (retry, or both radios) is executed once ([00](00-common-frame-and-conventions.md) §6.3).
8. **A slave may refuse an unsafe command**, e.g. "off" at night when its clock is untrusted. Refusals are reported in `CMD_ACK`.

## 6. DALI driver settings (configured by the device on every driver)

| Setting | Value | Why |
|---|---|---|
| `POWER ON LEVEL` | **254 (100%)** | A mains restore at night lights the street immediately (F15) |
| `SYSTEM FAILURE LEVEL` | **254 (100%)** — default | A dead device or broken DALI link leaves the light at full brightness (F11) |
| `FADE TIME` | Index 7–10 (5.7–16 s) for scheduled changes | Avoids visible flicker and inrush when many lights change together |
| `MIN LEVEL` | Not below the road-class lux floor (⚠ awaiting DOE/DPWH figures) | Legal dimming floor |

**Option — diagnostic System Failure Level.** Set `SYSTEM FAILURE LEVEL = 250` (≈90%) instead of 254. A technician can then tell from the road which fault occurred: 100% = power-up, ≈90% = device or DALI failure. The difference is barely visible to drivers. **To choose (hardware developer, for the client): ☐ 254 (default) ☐ 250 (diagnostic).**

These settings live in the driver and **don't survive a driver replacement**, which is why F12 re-pushes them. The device re-asserts them after every `REPLACE_DRIVER` and every `REASSERT_CONFIG`.

## 7. Device developer obligations

Each item is testable on the bench. The device developer confirms each one in writing at M4.

| # | Obligation | Test |
|---|---|---|
| DD-1 | Keep a real-time clock and a trusted/untrusted flag. The clock is set from cell beacons | Power-cycle without beacon: report shows `clock_trusted = 0` |
| DD-2 | Store latitude, longitude and dusk/dawn offsets (from `SET_SCHEDULE`), and the timezone offset (provisioned on the bench, +480; [00](00-common-frame-and-conventions.md) §1), in non-volatile memory | Power-cycle; values read back unchanged |
| DD-3 | Compute sunset/sunrise locally, and run the **fallback schedule**: ON at 100% from dusk to dawn, no dimming, when in `fallback_mode` | Switch the slave off: within 6 min the device enters fallback and follows dusk/dawn (test with a shifted clock) |
| DD-4 | With no trusted time and no beacon, drive the light to **100%**, day or night | Boot with no RTC backup and no slave: light at 100% |
| DD-5 | Enter `fallback_mode` after 3 missed cycles on both channels; try the other channel after 2 missed beacons on the home channel | Kill one slave radio, then both; check timing |
| DD-6 | Set `POWER ON LEVEL` and `SYSTEM FAILURE LEVEL` per §6 at commissioning, after `REPLACE_DRIVER`, and on `REASSERT_CONFIG`; verify by DALI query and report `config_mismatch` if they differ | Replace a driver with a factory-new one; levels read back correct |
| DD-7 | Execute commands only as absolute levels; drop commands past `not_after`; execute duplicates once | Replay a captured command; resend after `not_after` |
| DD-8 | Expire overrides at their lifetime (max 720 min) and clear all overrides on reboot | Set a 2-min override; it ends on time. Reboot during an override: back to schedule |
| DD-9 | Report `dali_ok`, `driver_fault`, `lamp_fault`, `commanded_off`, `fallback_mode`, `clock_trusted`, `restarted` truthfully, per the status bits in [03](03-tier2-device-protocol.md) | Inject each condition; check the report |
| DD-10 | After a reboot with a valid stored slot, rejoin in its own slot, not the contention window | Power-cycle a full bench section together; no join storm |
| DD-11 | Never switch off on an ambiguous condition (unknown time, lost link, config error): the answer is always 100% ON at night | Covered by DD-3, DD-4 and F17 test |

## 8. M6 acceptance tests

Run on the bench system (server, master, at least two slaves, devices). Pass = every check true, with no manual intervention during the test and no invented data on the server.

| Test | Action | Pass criteria |
|---|---|---|
| **T1 Server down** | Stop the server for 1 h during simulated night, with an override active | Lights follow the schedule; the unexpired override is kept and then expires on time; Master raises `SERVER_LOST`; on restart the server receives the buffered events with original timestamps |
| **T2 Master down** | Power off the master for 90 min during simulated night | Slaves go `DEGRADED` at 6 min (±1 cycle) and `AUTONOMOUS` at 60 min (±1 cycle); overrides dropped at `AUTONOMOUS`; lights stay on schedule / at 100%; server shows `MASTER_OFFLINE` and all data `STALE` with age; on power-on, slaves rejoin and no configuration is silently overwritten |
| **T3 Slave down** | Power off one slave for 15 min during simulated night | Its devices enter `fallback_mode` within 6 min and light at 100%; other sections unaffected; the server shows `SECTION_LOST`; on power-on, devices resume in their slots without a join storm (all back within 3 cycles) |
| **T4 Radio failed** | Disconnect the master's primary antenna (TX off first); then one slave downstream antenna | Master fails over within 3 exchanges with `RADIO_FAILOVER`; no loss of switching; slave enters single-channel mode and all its devices are back online within 3 cycles; failback after 10 min clean once reconnected |
| **T5 Clock untrusted** | Clear a slave's RTC and power-cycle it with the master off | Its section goes to 100% ON regardless of time; `GW_CLOCK_UNTRUSTED` raised; returns to schedule when a trusted beacon arrives |

## 9. Sign-off

By signing, each party agrees that the system behaves as described in this table, and the device developer accepts obligations DD-1 to DD-11.

| Party | Name | Signature | Date |
|---|---|---|---|
| Gateway hardware developer (for the client) | | | |
| Device developer | | | |
| pgorospe | | | |

## Open items

| # | Item | Needed by |
|---|---|---|
| O-05-1 | Hardware developer (for the client) to choose the System Failure Level: 254 (default) or 250 (diagnostic) | M1 sign-off |
| O-05-2 | ⚠ Verify the DALI control-interruption time (~550 ms) and the exact System Failure / Power On semantics against IEC 62386 | Before M4 |
| O-05-3 | Can the device developer's hardware hold time through a power cut (RTC backup)? If not, DD-1/DD-4 mean every power restore by day gives 100% until the first beacon | M1 sign-off |
| O-05-4 | DOE/DPWH road-class lux floor for `MIN LEVEL` and dimming profiles | Before dimming profiles are fixed |
| O-05-5 | Is the 30-min "server lost" threshold right for the client's operations? | M1 sign-off |
| O-05-6 | Hardware developer (for the client) to confirm that a full-night 100% fallback (no dimming) is acceptable while a section is autonomous | M1 sign-off |
| O-05-7 | ⚠ Layer 4 and F11 assume a dead device interrupts the DALI bus. On the device developer's bench (2026-10-28) the DALI interface (Waveshare Pico-DALI2) released the bus by itself within 10 ms of being told to hold it low, and the bus supply runs independently of the MCU, so a halted MCU would leave the bus high and the driver at its last level, possibly off or dimmed at night. Device developer to define how the device guarantees a bus interruption longer than the System Failure time when its MCU stops (for example a bus supply enabled by a watchdog-refreshed signal), and whether a DD obligation and an M6 test should cover it | M1 sign-off |
