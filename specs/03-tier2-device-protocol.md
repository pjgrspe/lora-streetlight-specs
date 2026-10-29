# 03 — Tier-2 Device Protocol (Slave ↔ Devices)

| | |
|---|---|
| **Spec** | 03 — Tier-2 device protocol (Slave Gateway ↔ LED devices and energy meter) |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-29 |
| **Owner** | pgorospe |
| **Reviewers** | **Device developer** (primary), gateway hardware developer (for the client) |
| **Status** | Draft. Not frozen |

How a device joins its section's Slave, reports, receives commands and survives the loss of its Slave. **This is the contract between pgorospe and the device developer.** The device developer does not implement this protocol from scratch: pgorospe supplies a **device-role library** that implements it (§14). This spec says what goes over the air and what the device firmware must do around the library.

Frame format, addressing, keys and type numbers: [00](00-common-frame-and-conventions.md). Channels and cell timing: [04](04-channel-plan-and-airtime.md). Fail-safe behaviour: [05](05-fail-safe-behaviour.md).

## 1. Summary for the device developer

- Your device has **one SX1276 radio**, mains power, and **listens all the time** except while transmitting.
- It finds its Slave by listening for a **cell BEACON**, joins once, and is given a **NodeID, a channel and a slot**.
- **Every cycle (default 120 s) it sends one REPORT in its slot.** No polling.
- Commands arrive any time in the downlink window. Group commands carry **`execute_at`**: all devices switch at that second.
- **Lights are switched by the device's own astronomical schedule**, with no radio traffic. Commands override it temporarily; every override expires.
- If the Slave disappears, the device keeps running its schedule (`fallback_mode`). If its clock can't be trusted, it drives the lamp to **100%**.
- You write: DALI control, measurements, the astronomical schedule, RTC, persistence and the hardware glue. The library does everything on the radio.

## 2. Device lifecycle

| State | Meaning | Leaves to |
|---|---|---|
| `UNPROVISIONED` | No `DevKey`/UID record yet (factory). Radio silent | `SCANNING` once provisioned on the bench |
| `SCANNING` | Listening for a cell BEACON (§3) | `JOINING` when a BEACON from the site's NetID is heard |
| `JOINING` | Sending JOIN_REQ in the contention window (§4) | `JOINED` on JOIN_ACC; `SCANNING` after 8 failed attempts on this Slave |
| `JOINED` | Reporting in its slot, following commands | `REJOINING` after reboot or on request; `FALLBACK` on Slave loss |
| `REJOINING` | Holds a slot from before; sends REJOIN_REQ in that slot (§5) | `JOINED` on JOIN_ACC; `JOINING` after 3 failed cycles |
| `FALLBACK` | Lost its Slave (§11). Runs its own schedule. Keeps listening | `JOINED` when its Slave's BEACON returns |

**The lamp is controlled in every state** by the device's own schedule (§10). The radio state never leaves the lamp uncontrolled.

## 3. Channel scan and section discovery

- Cell channels are raster channels 1–12 ([04 §2–3](04-channel-plan-and-airtime.md)). Downlink frames use **inverted IQ**; uplink frames normal IQ ([00 §4](00-common-frame-and-conventions.md)).
- A device that has joined before **first listens on its persisted home channel** for 2 cycles.
- Otherwise it listens on channels 1–12 in turn, **one full cycle (`CYCLE` + 1 s) per channel**, at the cell SF (SF9 by default; then SF8, SF7). Worst case for a first join: 12 cycles (24 min at 120 s).
- A BEACON is accepted for discovery if its `NETID` matches the site's NetID (provisioned on the bench, or learned from the first BEACON whose JOIN_ACC succeeds). **The BEACON is MIC'd but not encrypted**, so an unjoined device can read its timing. It can't verify the MIC until it holds `CellKey`; it uses the timing only to place its JOIN_REQ. After a boot, a device with a stored `CellKey` does the same until its REJOIN_REQ is answered: the JOIN_ACC gives the broadcast counter the MIC needs, and the time ([00 §6.3](00-common-frame-and-conventions.md)).
- If it hears several Slaves, it tries the strongest (RSSI) first. A Slave that doesn't have the device's UID in its whitelist never answers, and after 8 attempts the device moves on to the next Slave.

## 4. Joining

### 4.1 JOIN_REQ (TYPE `0x07`), device → Slave, 17 bytes

Header: `SRC = (GwID << 8) | 0xFE` (unjoined), `DST = GwID << 8`, `DIR = 0`, `PRIO = 1`, `FCNT` = low 16 bits of `dev_nonce`. MIC with `DevKey`; `FCNT32` in B0 = `dev_nonce`. **Not encrypted.** Frame 29 B, 226 ms at SF9.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 12 | `uid` | STM32 96-bit unique ID |
| 12 | 2 | `dev_nonce` | Persisted, incremented before every JOIN_REQ / REJOIN_REQ. The Slave rejects a value ≤ the last accepted for this UID |
| 14 | 1 | `device_type` | `0x01` LED driver/monitoring device · `0x02` energy meter |
| 15 | 2 | `fw_version` | major << 8 \| minor |

### 4.2 Contention window access

- The contention window is cell time 0.60–1.60 s, on both channels ([04 §6.2](04-channel-plan-and-airtime.md)). It has **3 sub-slots of 333 ms**.
- The device sends on the channel where it heard the BEACON, at the start of a randomly chosen sub-slot, **after a CAD check** shows the channel clear (if busy, it skips this cycle).
- **Backoff:** after the k-th failure, wait a random 0 … 2^min(k,4) − 1 cycles before the next attempt.
- **Randomness** comes from the SX1276 wideband RSSI register (LSBs of `RegRssiWideband`, collected 32 times), seeded with the UID. The library does this.
- A new (never joined) UID is accepted only while the Slave's **commissioning window is open** (BEACON flag bit1). A UID that has joined before may join any time.

### 4.3 JOIN_ACC (TYPE `0x08`), Slave → device, 45 bytes

Sent in the downlink window of the same cycle. `DST = (GwID << 8) | 0xFE` for a first join (the device recognises its own JOIN_ACC by the MIC, which only its `DevKey` verifies), or the device's address for a rejoin. `FCNT` = low 16 bits of `dev_nonce`. Encrypted and MIC'd with `DevKey`; `FCNT32` in B0 and A_i = `dev_nonce`. Frame 57 B, 349 ms at SF9.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `join_nonce` | Slave's counter, strictly increasing, persisted |
| 4 | 1 | `node_id` | 1–63. **The same NodeID is always given back to the same UID** |
| 5 | 1 | `home_channel` | Raster channel number (the section's channel A or B) |
| 6 | 1 | `slot` | 0–63. Slots 0–31 on channel A, 32–63 on channel B. A meter also owns `slot + 1` |
| 7 | 2 | `cycle_s` | Cycle length, s (default 120) |
| 9 | 1 | `cell_sf` | 7, 8 or 9 |
| 10 | 2 | `slot_ms` | Slot length, ms (default 300) |
| 12 | 2 | `slot0_ms` | Start of slot 0 after cell start, ms (default 1600) |
| 14 | 2 | `beacon_offset_ms` | When the BEACON on `home_channel` is sent, after cell start (0 on channel A, 250 on channel B) |
| 16 | 16 | `cell_key` | `CellKey` for cell broadcasts |
| 32 | 2 | `group_mask` | bit g = member of group g (0–15) |
| 34 | 4 | `utc` | Slave time at TxDone of this frame, s |
| 38 | 2 | `utc_ms` | Sub-second part, ms. A device that has just (re)joined may receive a group command before its next BEACON; without milliseconds its clock could be up to 1 s off |
| 40 | 1 | `flags` | bit0 meter (double slot) · bit1 single-channel mode active · bits 2–7 reserved |
| 41 | 4 | `bcast_fcnt` | `FCNT32` of the Slave's next `CellKey` broadcast. The device starts its broadcast receive window here ([00 §6.3](00-common-frame-and-conventions.md)) |

Both sides then derive `NwkSKey` and `AppSKey` ([00 §6.1](00-common-frame-and-conventions.md)) and set `FCNT32` to 0. The device persists `node_id`, `home_channel`, `slot`, the cell parameters, `cell_key` and `group_mask` (§12).

### 4.4 Slot assignment rules (Slave side)

- The Slave keeps the UID → {NodeID, slot, home channel} table in FRAM. A device that rejoins gets the same values unless the slot map has changed.
- New devices are placed to balance the two channels. The meter is placed on a slot pair that doesn't cross the channel boundary (31/32).
- A change to the slot map increments `slotmap_ver` in the BEACON. A device that sees a new `slotmap_ver` keeps its slot unless it is told otherwise by a new JOIN_ACC.

## 5. Rejoining without a join storm

After a power cut, every device in the section boots at once. To avoid all of them using the contention window:

- **A device that holds a persisted slot sends REJOIN_REQ in its own slot**, not in the contention window. No collisions, by construction.
- The Slave answers with a JOIN_ACC (new `join_nonce`, new session keys) addressed to the device, in the downlink window of the same cycle.
- After 3 cycles without a JOIN_ACC, the device falls back to a normal JOIN_REQ (§4).

### REJOIN_REQ (TYPE `0x09`), device → Slave, 5 bytes

`SRC` = the device's address. MIC with `DevKey`, `FCNT32` in B0 = `dev_nonce`. Not encrypted.

| Off | Size | Field |
|---|---|---|
| 0 | 2 | `dev_nonce` (incremented first) |
| 2 | 2 | `fw_version` |
| 4 | 1 | `reset_cause` (1 power-on, 2 brown-out, 3 watchdog, 4 software, 5 pin) |

## 6. Device status bits (u16)

Used in REPORT, in the tier-1 DETAIL record ([02 §7](02-tier1-protocol.md)) and in the Modbus device block ([01](01-modbus-register-map.md)).

| Bit | Name | Set when |
|---|---|---|
| 0 | `lamp_on` | The output level is > 0 |
| 1 | `dali_ok` | The DALI bus is powered and the gear answers queries |
| 2 | `driver_fault` | The DALI gear reports control gear failure |
| 3 | `lamp_fault` | The DALI gear reports lamp failure |
| 4 | `clock_trusted` | The device clock is trusted (§10.3) |
| 5 | `fallback_mode` | The device has lost its Slave and runs on its own (§11) |
| 6 | `override_active` | A commanded level overrides the schedule |
| 7 | `commanded_off` | The lamp is off because a command or the schedule said so (never set for a fault) |
| 8 | `d4i_available` | The gear supports DALI Parts 251–253 |
| 9 | `config_mismatch` | A read-back of the DALI gear settings doesn't match the configured values |
| 10 | `restarted` | Set in the first REPORT after a boot, cleared afterwards |
| 11–15 | reserved | 0 |

For the meter, bits 1–3, 6–9 are 0 and `lamp_on` is 0.

## 7. REPORT (TYPE `0x02`), device → Slave

Sent **once per cycle, in the device's slot**. `DST = GwID << 8`, `DIR = 0`, `PRIO = 2`, `ACKREQ = 0`. Encrypted with `AppSKey`. **Reports are not acknowledged**: each one is a snapshot, and a lost one is replaced by the next.

**A device transmits only in a cycle whose BEACON it received.** A missed beacon costs that cycle's REPORT, but stale timing can never put a device on top of a shifted beacon or another device's slot (the Slave moves its cell when it enters or leaves single-channel mode). That one cycle is 10 s shorter or 10 s longer. The device takes each beacon's timing as it comes; a stretched cycle shows up as one missed beacon, which costs nothing ([02](02-tier1-protocol.md) §15).

**Slot timing:** slot k starts at `cell_start + slot0_ms + (k mod 32) × slot_ms` (k ≥ 32 uses channel B at the same times). In single-channel mode it starts at `cell_start + slot0_ms + k × slot_ms` on the surviving channel. **The device starts transmitting 20 ms after the slot start, within ±20 ms.**

### 7.1 LED device REPORT, 20 bytes (frame 32 B, 247 ms at SF9)

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `report_fmt` | `0x01` = LED v1 |
| 1 | 2 | `status` | §6 |
| 3 | 1 | `level_actual` | DALI arc level the gear is at now (`QUERY ACTUAL LEVEL`), 255 = unknown |
| 4 | 1 | `level_target` | Level the device is trying to hold (schedule or override) |
| 5 | 2 | `power_dw` | Input power, 0.1 W. `0xFFFF` = not measured |
| 7 | 2 | `voltage_dv` | Supply voltage, 0.1 V. `0xFFFF` = not measured |
| 9 | 2 | `current_ma` | Supply current, mA. `0xFFFF` = not measured |
| 11 | 4 | `energy_wh` | Cumulative energy, Wh, monotonic, persisted. `0xFFFFFFFF` = not measured |
| 15 | 1 | `temp_c` | i8, °C (device or driver). `0x7F` = n/a |
| 16 | 2 | `lamp_hours` | Lamp operating hours, saturating at 65 534. `0xFFFF` = n/a |
| 18 | 1 | `fault_code` | §9.1 |
| 19 | 1 | `last_cmd_fcnt_lo` | Low byte of the `FCNT` of the last CMD frame the device executed. The Slave uses it with `level_actual` to confirm commands |

### 7.2 Meter REPORT, 44 bytes (frame 56 B, 349 ms at SF9, double slot)

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `report_fmt` | `0x02` = meter v1 |
| 1 | 2 | `status` | §6 |
| 3 | 6 | `v_l1`, `v_l2`, `v_l3` | u16 each, 0.1 V (line–neutral; line–line if delta) |
| 9 | 8 | `i_l1`, `i_l2`, `i_l3`, `i_n` | u16 each, 10 mA. `i_n` = `0xFFFF` if not measured |
| 17 | 6 | `p_l1`, `p_l2`, `p_l3` | i16 each, W |
| 23 | 4 | `p_total` | i32, W |
| 27 | 2 | `pf_total` | i16, × 1000 |
| 29 | 2 | `freq` | u16, × 100 Hz |
| 31 | 4 | `e_import` | u32, Wh, monotonic |
| 35 | 4 | `e_export` | u32, Wh, monotonic |
| 39 | 2 | `thd_i` | u16, 0.1 % |
| 41 | 2 | `meter_flags` | bit0 wye (1) / delta (0) · bit1 CT-connected · bit2 phase loss L1 · bit3 L2 · bit4 L3 · others 0 |
| 43 | 1 | `fault_code` | §9.1 |

The meter measures continuously and reports the latest values every cycle. The Slave forwards meter data to the Master every 5 min ([02 §7](02-tier1-protocol.md)).

## 8. Cell BEACON (TYPE `0x01`), Slave → devices

Sent every cycle on both channels: channel A at cell time 0.00, channel B at 0.25. `DST = (GwID << 8) | 0xFF`, `DIR = 1`, `PRIO = 0`. **MIC'd with `CellKey`, not encrypted.** 11 bytes, or 15 with the event-ACK bitmap.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `utc` | Slave time at TxDone of this frame, s |
| 4 | 2 | `ms` | Sub-second part, ms |
| 6 | 2 | `cycle_seq` | Increments every cycle |
| 8 | 1 | `flags` | bit0 `clock_trusted` · bit1 commissioning window open · bit2 `single_channel_mode` · bit3 `has_event_ack_bitmap` · bit4 `slave_autonomous` (lost the Master) · bits 5–7 reserved |
| 9 | 1 | `slotmap_ver` | |
| 10 | 1 | `config_ver` | Section configuration version. A device whose stored value differs expects a configuration push |
| 11 | 4 | `event_ack_bitmap` | Present only if flag bit3. Each beacon acknowledges the EVENTs received **on its own channel** last cycle: bit (slot mod 32) for the sending device. In single-channel mode the surviving channel's beacon covers every device on it, so slots k and k + 32 share a bit; if both sent an EVENT in the same cycle, one may take the other's ACK (⚠ rare; its state is still in every REPORT). The beacon on the failed channel can't be heard, so it can't carry them |

**Timing from the BEACON:** the device timestamps RxDone, computes `cell_start = beacon_time − beacon_offset_ms` in Slave time, and keeps an EWMA of its clock offset (α = 1/4). Devices need slot accuracy of ±20 ms. Drift between two ±20 ppm crystals over one 120 s cycle is under 5 ms.

## 9. EVENT (TYPE `0x03`), device → Slave

Unsolicited alarms. **Sent in the contention window** of the next cycle (§4.2 access rules), on the home channel, `ACKREQ = 1`, `PRIO = 1`. Encrypted with `AppSKey`. Acknowledged by the bit for the device's slot in the next BEACON's `event_ack_bitmap`. Not acknowledged → retry with backoff (§4.2), up to 5 attempts, then the device drops the event (its state still shows in every REPORT).

Events are for changes; the state itself is always in the REPORT. A device sends at most one EVENT per cycle; if several are pending, the most severe goes first.

**Payload, 6–12 bytes** (frame ≤ 24 B, ≤ 206 ms at SF9):

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `event_code` | §9.2 |
| 1 | 1 | `severity` | 0 info · 1 warning · 2 alarm · 3 critical |
| 2 | 4 | `utc` | When it happened (device clock) |
| 6 | 0–6 | `data` | Event-specific |

### 9.1 Fault codes (`fault_code`, u8)

The single most important current fault. 0 when healthy.

| Code | Fault | Device |
|---|---|---|
| 0 | None | both |
| 1 | Lamp failure (DALI status) | LED |
| 2 | Control gear failure (DALI status) | LED |
| 3 | DALI bus has no power | LED |
| 4 | DALI bus short circuit | LED |
| 5 | No DALI gear answers | LED |
| 6 | DALI gear unaddressed / factory state | LED |
| 7 | Over-temperature | both |
| 8 | Supply voltage out of range | both |
| 9 | Internal storage fault | both |
| 10 | RTC fault | both |
| 11 | Radio fault (self-detected) | both |
| 20 | Metering IC not responding | meter |
| 21 | Phase loss | meter |
| 22 | Reverse power / CT reversed | meter |
| 255 | Unknown fault | both |

### 9.2 Device event codes (`0x40`–`0x7F`)

Forwarded unchanged by the Slave in tier-1 EVENTs ([02 §9](02-tier1-protocol.md)).

| Code | Name | Severity | `data` |
|---|---|---|---|
| `0x40` | `DEVICE_RESTARTED` | warning | reset cause u8. **Raised by the Slave** when it accepts the device's REJOIN_REQ (which carries the reset cause), never sent by the device: after a mains restore every device would send it in the same contention window |
| `0x41` | `LAMP_FAULT` | alarm | — |
| `0x42` | `DRIVER_FAULT` | alarm | — |
| `0x43` | `DALI_BUS_FAULT` | alarm | fault code u8 (3 or 4) |
| `0x44` | `DALI_GEAR_MISSING` | alarm | — |
| `0x45` | `DALI_GEAR_REPLACED` | warning | new gear detected in factory state |
| `0x46` | `FAULT_CLEARED` | info | cleared fault code u8 |
| `0x47` | `FALLBACK_ENTERED` | warning | — (sent after the Slave is found again) |
| `0x48` | `FALLBACK_EXITED` | info | minutes spent in fallback u16 |

`FALLBACK_ENTERED` and `FALLBACK_EXITED` start after a random 0–15 cycles, because a whole cell may leave `FALLBACK` together. The library queues both itself.
| `0x49` | `CLOCK_UNTRUSTED` | alarm | — |
| `0x4A` | `OVER_TEMPERATURE` | warning | temperature i8 |
| `0x4B` | `SUPPLY_OUT_OF_RANGE` | warning | voltage dV u16 |
| `0x4C` | `CONFIG_MISMATCH` | warning | — |
| `0x4D` | `TAMPER` | alarm | — (only if the hardware has a tamper input) |
| `0x50` | `METER_PHASE_LOSS` | critical | phase mask u8 |
| `0x51` | `METER_PHASE_RESTORED` | info | phase mask u8 |
| `0x52` | `METER_FAULT` | alarm | fault code u8 |
| `0x53` | `METER_OVERCURRENT` | warning | phase mask u8 |
| `0x54`–`0x7F` | reserved | | |

## 10. Commands

### 10.1 CMD (TYPE `0x04`), Slave → device(s)

Sent in the downlink window (cell time ≥ 16 s), or **immediately** for P0 ([04 §6.4](04-channel-plan-and-airtime.md)). Same 10-byte header for unicast and group commands.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `cmd_id` | From the Master job. Duplicate key end to end |
| 2 | 1 | `opcode` | §10.2 |
| 3 | 1 | `group` | Group command: `0xFF` = every device in the cell, 0–15 = group g. Unicast: `0xFE` |
| 4 | 4 | `execute_at` | UTC seconds. 0 = execute on receipt |
| 8 | 2 | `not_after_s` | Seconds after `execute_at` (or after receipt if `execute_at` = 0) beyond which the command is discarded. 0 = 60 s. For a group command from the Master, the Slave copies the Master's deadline (60–600 s, [02 §11.6](02-tier1-protocol.md)) |
| 10 | … | `params` | Per opcode |

- **Unicast:** `DST` = device address, encrypted with `AppSKey`, `ACKREQ = 1`. Params up to 44 B (SF9).
- **Group / cell broadcast:** `DST = (GwID << 8) | 0xFF`, encrypted with `CellKey`, `ACKREQ = 0`. **Fixed 16-byte payload: 6 bytes of params, zero-padded.** Sent on both channels and repeated once 1 s later. Copies are byte-identical. Frame 28 B, 226 ms at SF9.

### 10.2 Opcodes on tier 2

Numbers match the Modbus mailbox and tier 1 ([02 §11.1](02-tier1-protocol.md)).

| Op | Name | Params | Unicast | Group |
|---|---|---|---|---|
| `0x01` | `SET_LEVEL` | `level` u8 · `fade` u8 · `override_ttl_min` u16 | ✅ | ✅ |
| `0x02` | `RESUME_SCHEDULE` | — | ✅ | ✅ |
| `0x03` | `IDENTIFY` | `pattern` u8 · `duration_s` u16 | ✅ | ✅ |
| `0x04` | `QUERY` | — (device sends a REPORT immediately as its CMD_ACK follow-up) | ✅ | — |
| `0x06` | `SET_SCHEDULE` | as tier 1: `lat` i32 · `lon` i32 · `dusk_offset_min` i16 · `dawn_offset_min` i16 · `n_steps` u8 · up to 4 × {`local_minute` u16 · `level` u8} | ✅ | — |
| `0x07` | `REBOOT` | — | ✅ | — |
| `0x0C` | `REPLACE_DRIVER` | `short_addr` u8 (DALI short address to program, normally 0) | ✅ | — |
| `0x0D` | `REASSERT_CONFIG` | `config_ver` u8 · `group_mask` u16 · `power_on_level` u8 · `system_failure_level` u8 · `default_fade` u8 | ✅ | — |
| `0x0E` | `SET_FAILSAFE_LEVELS` | `power_on_level` u8 · `system_failure_level` u8 | ✅ | — |

`SET_TIME`, `OPEN_COMMISSIONING`, `AUTHORISE_DEVICE`, `REVOKE_DEVICE`, `REPLACE_DEVICE` and `FORCE_FAILOVER` are never sent to devices.

### 10.3 CMD_ACK (TYPE `0x05`), device → Slave, 7 bytes

Answers **every unicast CMD**, sent 100–300 ms after the CMD's RxDone, on the home channel. Encrypted with `AppSKey`. Group commands get no CMD_ACK; they are confirmed by the next REPORT.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `cmd_id` | |
| 2 | 1 | `result` | Result code from the system-wide table in [02 §11.5](02-tier1-protocol.md). A device uses only: 0 `OK` · 1 `ACCEPTED` (waiting for `execute_at`) · 2 `DUPLICATE` · 3 `EXPIRED` · 4 `REFUSED_UNSAFE` · 5 `BAD_OPCODE` · 6 `BAD_PARAMS` · 7 `BUSY` · 10 `FAILED` · 15 `NOT_SUPPORTED` |
| 3 | 2 | `status` | Status bits after the command (§6) |
| 5 | 1 | `level_actual` | |
| 6 | 1 | `level_target` | |

If the Slave gets no CMD_ACK, it retries up to 3 times, 2 s apart, within `not_after`. It starts a unicast at least 0.8 s plus its airtime before the end of the downlink window, so the CMD_ACK (and a `QUERY`'s REPORT) never runs into the next beacon.

**A command that takes longer** (`REPLACE_DRIVER`; a REBOOT that must first send its CMD_ACK): a device that answers `ACCEPTED` to a command with `execute_at` = 0 sends a second, final CMD_ACK with the same `cmd_id` when it is done, in the contention window of a following cycle (§4.2 access rules). The Slave stops retrying on the `ACCEPTED` and waits up to 3 cycles for the final one, then reports `FAILED`. `QUERY` answers with a REPORT also when the CMD is a retry (`DUPLICATE`), since the first REPORT may be the frame that was lost.

### 10.4 Rules every device follows

1. **Absolute commands only.** `SET_LEVEL(level)` sets a level. Nothing toggles or adds.
2. **Duplicates:** a command whose `FCNT` is already in the duplicate window, or whose `cmd_id` is among the last 8 executed, is acknowledged (`result = 2`) and **not executed again**.
3. **`execute_at`:** execute when the device clock reaches `execute_at` (to the second, ±50 ms). Received after `execute_at` but before the `not_after` deadline → execute immediately. After the deadline → discard (`result = 3`).
4. **Overrides expire.** `SET_LEVEL` with `override_ttl_min` = 0 lasts until the next schedule step; otherwise for that many minutes (max 720). Every override is cleared on reboot and on entering `FALLBACK`.
5. **Unsafe commands:** a device whose clock is untrusted refuses any `SET_LEVEL` below 254 (`result = 4`). The lamp stays at 100%.
6. A device executes only commands addressed to it, to its cell (`group = 0xFF`) or to a group in its `group_mask`.

## 11. Channel failover and losing the Slave

| Condition | Device action |
|---|---|
| 2 consecutive BEACONs missed on the home channel | Listen on the section's other channel |
| BEACON heard on the other channel with `single_channel_mode` set | Move there. Use the single-channel slot timing (§7) with the same slot number. No rejoin needed. Once every 10 cycles (when `(cycle_seq + NodeID) mod 10 = 0`) send that cycle's REPORT on the **home** channel instead, at the same slot time: this probe tells the Slave when the failed radio works again ([02 §15](02-tier1-protocol.md)) |
| Moved for single-channel mode, then a BEACON without `single_channel_mode` | Return to the home channel. No rejoin needed |
| BEACON heard on the other channel without `single_channel_mode` (and not moved for single-channel mode) | The Slave is fine but this device's link isn't. Send REJOIN_REQ in the **contention window** of that channel (never in its own slot time, which belongs to another device there); the Slave assigns a new home channel and slot on that channel |
| 3 consecutive cycles with no BEACON on either channel | Enter **`FALLBACK`**: set `fallback_mode`, clear overrides, run the local schedule (§12.2). Keep listening: alternate the two section channels every cycle; every 30 min do a full scan (§3) |
| BEACON from its own Slave again | Leave `FALLBACK`, send REJOIN_REQ in its slot if the slot map is unchanged, send `FALLBACK_EXITED` |

## 12. Configuration, swap and driver replacement

### 12.1 Configuration push

- On join, and whenever the BEACON's `config_ver` differs from the device's stored value, the Slave sends `SET_SCHEDULE` and `REASSERT_CONFIG` as unicast CMDs. The device stores them and acknowledges.
- `REASSERT_CONFIG` also tells the device to **write the DALI settings again** (`POWER ON LEVEL`, `SYSTEM FAILURE LEVEL`, fade, groups), read them back, and clear or set `config_mismatch`.
- `SET_FAILSAFE_LEVELS` writes the two DALI levels immediately. Defaults are 254 / 254 ([05](05-fail-safe-behaviour.md)).

### 12.2 Swapping a device

1. The server issues `REPLACE_DEVICE(old address, new UID)`. The Master sends a WHITELIST entry with the `replacement` flag ([02 §8.1](02-tier1-protocol.md)), and the old UID is marked decommissioned.
2. The Slave opens a 5-minute commissioning window for that NodeID only.
3. The new device joins normally (§4). The Slave gives it the **old device's NodeID, slot and home channel**.
4. The Slave pushes the configuration (§12.1) and raises `DEVICE_SWAPPED`.
5. Joins from the old UID are refused from then on.

### 12.3 Replacing a failed LED driver (`REPLACE_DRIVER`)

The device, not the radio library, runs this on its DALI line:

1. Find the new gear (`QUERY CONTROL GEAR PRESENT`, `QUERY MISSING SHORT ADDRESS`).
2. Address **only unaddressed gear** (`INITIALISE` with the "no short address" argument). Never re-address gear that already has an address.
3. Program the short address given in the command (normally 0).
4. Write all configuration again (as `REASSERT_CONFIG`).
5. Re-probe capabilities (D4i, physical minimum).
6. Answer with CMD_ACK (`result = 0` or `10`) and send `DALI_GEAR_REPLACED` / `FAULT_CLEARED` as appropriate.

## 13. What the device developer's firmware must do

Protocol-side obligations are numbered DP-n. The fail-safe obligations DD-1 to DD-11 are in [05](05-fail-safe-behaviour.md) §7 and are signed there.

| # | Obligation | Detail |
|---|---|---|
| DP-1 | **Drive the lamp over DALI** | Set levels with the requested fade; read `ACTUAL LEVEL` and status for every REPORT |
| DP-2 | **Set the DALI fail-safe levels** | `POWER ON LEVEL` and `SYSTEM FAILURE LEVEL` as configured (default 254), at commissioning and on every `REASSERT_CONFIG` / `REPLACE_DRIVER` ([05](05-fail-safe-behaviour.md)) |
| DP-3 | **Run the astronomical schedule locally, always** | Sunrise/sunset from `lat`/`lon`/date (NOAA algorithm or equivalent), plus the offsets and up to 4 dimming steps from `SET_SCHEDULE`. Within **±2 min** of the reference test vectors. This is what switches the lights every night, with no radio traffic |
| DP-4 | **Keep an RTC** | Disciplined by the BEACON time via the library. Clock untrusted (no valid time since power-up and no BEACON) → lamp at **100%** |
| DP-5 | **Honour the command rules** | §10.4, using the library's callbacks |
| DP-6 | **Measure** | Power, voltage, current, energy and temperature where the hardware can; report `0xFFFF…` where it can't. Energy is cumulative and persisted |
| DP-7 | **Persist** | NodeID, slot, home channel, cell parameters, `cell_key`, `group_mask`, schedule, fail-safe levels, `dev_nonce` (written before each JOIN_REQ / REJOIN_REQ is sent), energy and lamp hours. No frame-counter high-water mark: every boot rejoins with new session keys ([00](00-common-frame-and-conventions.md) §6.3). Use a wear-aware scheme: the F103 flash takes ~10 k erase cycles |
| DP-8 | **Give the library the hardware** | SPI to the SX1276, NSS, NRESET and a busy-wait delay, through `lp_sx1276_hw_t`; a DIO0 interrupt that records the time; a wrapping millisecond counter. The firmware stores `lp_dev_persist_t` itself (DP-7). See §14.2 |
| DP-9 | **Radio power** | Set conducted power so that **EIRP ≤ 16 dBm** for the antenna and cable fitted (conducted = 16 − antenna gain + cable loss) |
| DP-10 | **Timing** | Call the library's poll function at least every 5 ms, and service DIO interrupts within 1 ms, so slot TX starts within ±20 ms and CMD_ACKs within 300 ms |
| DP-11 | **Watchdog** | Independent watchdog enabled. A reboot must leave the lamp in a safe state (DALI `POWER ON LEVEL` covers the gap) |
| DP-12 | **Provisioning** | On the bench: store UID record, `DevKey` (or the data to derive it) and `tz_offset_min` (+480) in protected flash; enable readout protection level 1. Never ship a default key |

**The library provides:** frame encode/decode, AES-128 CMAC/CTR, keys and session derivation, replay and duplicate windows, channel scan, join/rejoin/backoff, BEACON tracking and clock offset, slot timing, channel failover, event retry, command parsing and dispatch to callbacks, CMD_ACK, airtime checks, CAD before contention frames, the SX1276 driver (behind `lp_port_t`, written from the Semtech datasheet).

## 14. Device-role library

### 14.1 Budget

**≤ 16 KB flash, ≤ 3 KB RAM**, on STM32F103 (Cortex-M3, no FPU). Bare metal, no RTOS, no malloc, no floating point. C99. Portable to the device developer's final board.

Measured on the Cortex-M3 (arm-none-eabi-gcc `-Os`, unused code removed by the linker), 2026-10-29: the library with its SX1276 driver, events and deferred results is **9.7 KB flash**. A device holds **1.1 KB RAM** of library state, plus ⚠ about 0.9 KB of stack at the deepest point (estimated).

### 14.2 API

The API is the reference code, not a sketch: `lora/lp_dev.h`, `lora/lp_port.h` and `lora/lp_sx1276.h` in `lora-streetlight/protocol/`. Its README shows the wiring.

| Who | Calls | When |
|---|---|---|
| Firmware → library | `lp_sx1276_init()`, `lp_sx1276_port()`, `lp_dev_init()` | Boot |
| Firmware → library | `lp_dev_poll(now_ms)` | At the deadline it returns, and at least every 5 ms (DP-10) |
| Firmware → library | `lp_sx1276_service()`, then `lp_dev_on_rx()` or `lp_dev_on_tx_done()` with the time the DIO0 interrupt recorded | After each DIO0 interrupt |
| Firmware → library | `lp_dev_persist_dirty()` | After each call above; store `lp_dev_persist_t` when it returns 1 (DP-7) |
| Library → firmware | `lp_dev_app_t`: `execute`, `build_report`, `levels` | Commands, the REPORT, CMD_ACK contents |
| Library → board | `lp_sx1276_hw_t`: `select`, `xfer`, `reset`, `delay_ms` | SPI and pins (DP-8) |

| Firmware → library | `lp_dev_event()` | An EVENT (§9); the library sends and retries it |
| Firmware → library | `lp_dev_set_time()` | At boot, from a valid RTC (05 DD-1) |
| Firmware → library | `lp_dev_cmd_done()` | When a command whose `execute` returned `ACCEPTED` is finished |
| Firmware → library | `lp_dev_busy()` | Before a REBOOT: reset only once it returns 0 |
| Library → firmware | `lp_dev_app_t.on_state` | Every state change; on `FALLBACK`, clear overrides and run the local schedule |

Time is a wrapping 32-bit millisecond counter, compared with `lp_ms_diff()`. `lp_dev_config_t.reset_cause` carries the cause into the REJOIN_REQ. Still planned before M4: a 30-min rescan in `FALLBACK` and strongest-Slave selection. Exact signatures are frozen when the library is delivered (M4).

### 14.3 Test vectors

Delivered **with the library at M4**, generated from the reference implementation: frame encodings for every message type, MIC and encryption with fixed keys and counters, session key derivation, airtime values, and sunrise/sunset times for the site's coordinates (for DP-3). Both sides run them in their builds.

## Open items

| # | Item | Needed by |
|---|---|---|
| O-03-1 | Device developer confirms the obligations in §13 are achievable on the Blue Pill (especially DP-3 astro schedule and DP-6 measurements) | M1 sign-off |
| O-03-2 | Which measurements the LED device hardware actually provides (V, I, P, E, temperature) | M1 sign-off |
| O-03-3 | Worst-case first-join time is 12 cycles (24 min) because the device scans 12 channels. Acceptable for commissioning, or should the device be bench-provisioned with its section? | M1 sign-off |
| O-03-4 | Meter model and how the device developer reads it (direct metering IC or an external Modbus meter); confirms the meter REPORT fields | M1 sign-off |
| O-03-5 | Does the LED device hardware have a tamper input? (`TAMPER` event) | M1 sign-off |
| O-03-6 | ⚠ Confirm the 16 KB / 3 KB library budget on the actual F103 boards (clone chips) | M4 |
