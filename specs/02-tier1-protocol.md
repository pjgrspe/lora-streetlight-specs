# 02 — Tier-1 Protocol (Master ↔ Slaves)

| | |
|---|---|
| **Spec** | 02 — Tier-1 protocol (Master ↔ Slave Gateways) |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-20 |
| **Owner** | pgorospe |
| **Reviewers** | Gateway hardware developer (for the client) |
| **Status** | Draft. Not frozen |

How the Master and the Slaves talk over LoRa: joining, the cycle, summaries and detail, commands, events, redundancy and time. The frame format, addressing, keys and message type numbers are in [00](00-common-frame-and-conventions.md). Channels, spreading factors and timing are in [04](04-channel-plan-and-airtime.md). Both ends of this link are pgorospe's firmware, so this spec is mainly a design record. It is still reviewed and signed at M1.

## 1. Roles

| Role | Address | Responsibilities on tier 1 |
|---|---|---|
| Master | `0x000` | Owns the clock and the cycle. Sends the BEACON and the standby HEARTBEAT. Accepts slave joins. Turns server jobs into commands. Collects summaries, detail and events into the Modbus image ([01](01-modbus-register-map.md)) |
| Slave n | `n << 8` (n = 1–14) | Joins the Master. Sends a SUMMARY in its slot every cycle, plus detail and events. Forwards commands into its cell ([03](03-tier2-device-protocol.md)). Runs its section on its own when the Master is gone |

The number of slaves is configured on the Master (`slave_count`, 1–14). A slave's GwID is set in its configuration at commissioning. Slots exist only for configured slaves.

## 2. Radios and channel use

- Master: radio **R0 on ch 0** (primary) and **R1 on ch 13** (standby). Slave: upstream radios **U0 on ch 0** and **U1 on ch 13**. Channels per [04 §3](04-channel-plan-and-airtime.md).
- **Every box receives on both tier-1 radios at all times** unless one of its own radios is transmitting (one TX scheduler per box; reception during own TX is discarded and not counted as loss).
- The **active channel** is the one carrying the BEACON. It is ch 0 normally and ch 13 after a Master failover. The other channel carries the HEARTBEAT.
- A transmitter picks the channel; receivers don't need to know in advance. The Master sends unicast frames to slave n on the channel where it last received a valid frame from slave n.
- Tier-1 SF: default SF7, configurable SF7–SF8, one value for the whole tier ([04 §4](04-channel-plan-and-airtime.md)).

## 3. The cycle

Timing is defined in [04 §6.1](04-channel-plan-and-airtime.md) and repeated here only for reference:

| Master time (s) | What |
|---|---|
| 0.0 | BEACON on the active channel |
| 0.5 | HEARTBEAT on the other channel |
| 1.0–2.0 | Contention window: urgent EVENTs and JOIN_REQs |
| 2 + 2(n−1) | Slot of slave n (2.0 s) |
| end of last slot → `CYCLE` | Master downlinks (commands, whitelist, fragments), retries |

**Inside slave n's slot** (offsets from slot start):

| Offset | Frame | Rule |
|---|---|---|
| +0.00 | slave → SUMMARY | Every cycle, always |
| +0.25 | master → ACK or CMD | Optional. Only if the Master has something for this slave |
| +0.75 | slave → DETAIL, EVENT or FRAG | Optional. One frame |
| +1.25 | master → ACK | Optional. Acknowledges the +0.75 frame |
| +2.00 | slot ends | |

The SUMMARY itself is acknowledged in the next BEACON (`summary_ack_bitmap`). A slave that sees its bit clear resends the missed SUMMARY's content in its next SUMMARY (it is a snapshot, so the newer one replaces it).

## 4. Joining

A slave joins the Master after every boot, and whenever the Master asks it to (an `ACK` with result `REJOIN`, §10). Slave sessions are persisted by the **Master** in FRAM, so a Master reboot does not force the slaves to rejoin.

### 4.1 JOIN_REQ (TYPE `0x07`), slave → Master, 17 bytes

Sent in the contention window on the active channel. If no JOIN_ACC arrives in the same cycle, the slave retries after a random 1–4 cycles. Header: `SRC = n << 8`, `DST = 0x000`, `DIR = 0`, `ACKREQ = 0`, `PRIO = 1`, `FCNT` = low 16 bits of `DevNonce`. MIC with `GwKey(n)`, `FCNT32` in B0 = `DevNonce`. Not encrypted.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 12 | `uid` | STM32 96-bit UID of the slave |
| 12 | 2 | `dev_nonce` | Persisted, strictly increasing. The Master rejects a value ≤ the last one it accepted from this GwID |
| 14 | 1 | `device_type` | `0x10` = Slave Gateway |
| 15 | 2 | `fw_version` | major << 8 \| minor |

### 4.2 JOIN_ACC (TYPE `0x08`), Master → slave, 30 bytes

Sent in the slave's slot downlink window (+0.25) or, if the slot has passed, at the next free downlink moment. `DST = n << 8`, `DIR = 1`, `FCNT` = low 16 bits of `dev_nonce`. Encrypted and MIC'd with `GwKey(n)`, `FCNT32` in B0 and A_i = `dev_nonce`.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `join_nonce` | Master's counter, strictly increasing, persisted |
| 4 | 16 | `net_key` | `NetKey` for tier-1 broadcasts |
| 20 | 1 | `slot_index` | = GwID. Slot start = 2 + 2(slot_index − 1) s |
| 21 | 2 | `cycle_s` | Cycle length in seconds (default 120) |
| 23 | 1 | `t1_sf` | Tier-1 spreading factor (7 or 8) |
| 24 | 2 | `cycle_seq` | Current cycle number |
| 26 | 4 | `utc` | Master time when this frame completes (see §11) |

Both sides then derive `NwkSKey` and `AppSKey` per [00 §6.1](00-common-frame-and-conventions.md) and reset `FCNT32` to 0. The slave computes its cell offset `cell_start(n)` per [04 §6.3](04-channel-plan-and-airtime.md).

A JOIN_REQ from a GwID that isn't configured, or with a bad MIC, gets no reply. The Master raises event `JOIN_REJECTED` locally (§9).

## 5. BEACON (TYPE `0x01`), Master → all, 13 bytes

Fixed layout. `DST = 0xF00`, `DIR = 1`, `PRIO = 0`. Sent at cycle time 0.0 on the active channel. **MIC'd with `NetKey` but not encrypted**, so a slave that has just booted can read the timing before it joins (it can't trust the content until it has joined).

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `utc` | Master time at TxDone of this frame, seconds |
| 4 | 2 | `ms` | Sub-second part, ms |
| 6 | 2 | `cycle_seq` | Increments every cycle, wraps |
| 8 | 1 | `flags` | bit0 `clock_trusted` · bit1 `standby_active` (Master has failed over) · bit2 `server_online` · bits 3–7 reserved (0) |
| 9 | 1 | `config_ver` | Version of the site configuration. A slave whose copy differs requests it (§8) |
| 10 | 1 | `slave_count` | Number of configured slots |
| 11 | 2 | `summary_ack_bitmap` | bit n−1 = SUMMARY from slave n received last cycle |

## 6. SUMMARY (TYPE `0x10`), slave → Master, 32 bytes

Sent at +0.00 in the slave's slot, every cycle. `DST = 0x000`, `DIR = 0`, `PRIO = 2`, `ACKREQ = 0` (acknowledged by the BEACON). Encrypted with `AppSKey`.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `state` | 0 `SYNCED` · 1 `DEGRADED` · 2 `AUTONOMOUS` · 3 `CLOCK_UNTRUSTED` · 4 `REJOINING` (§12) |
| 1 | 1 | `flags` | bit0 `single_channel_mode` · bit1 down radio A ok · bit2 down radio B ok · bit3 up radio U0 ok · bit4 up radio U1 ok · bit5 commissioning window open · bit6 `events_pending` (buffered events waiting) · bit7 `detail_due` |
| 2 | 1 | `devices_configured` | Whitelisted devices in this section (incl. meter) |
| 3 | 1 | `devices_online` | Devices that reported within the last 3 cycles |
| 4 | 1 | `lamps_on` | Devices reporting `lamp_on` |
| 5 | 1 | `faults` | Devices with `driver_fault`, `lamp_fault` or `dali_ok = 0` |
| 6 | 4 | `power_w` | u32, W. Meter `P_total` if the meter is online, else Σ device power |
| 10 | 4 | `energy_wh` | u32, Wh. Meter `E_import` if online, else Σ device energy |
| 14 | 1 | `slotmap_ver` | Current cell slot-map version |
| 15 | 1 | `airtime_pct` | Box airtime used in the last hour, % of the 1% budget (0–100, 255 = n/a) |
| 16 | 2 | `config_hash` | Low 16 bits of CRC-32 over the slave's active configuration (schedule, levels, whitelist) |
| 18 | 2 | `clock_offset_ms` | i16. Slave clock minus Master clock at the last BEACON, ms, saturating |
| 20 | 8 | `changed_bitmap` | u64. bit k = NodeID k changed status (any status bit, `level_actual`, or `fault_code`) since the last SUMMARY |
| 28 | 2 | `cycle_seq` | The `cycle_seq` of the BEACON this SUMMARY answers |
| 30 | 1 | `buffered_events` | Events waiting to be sent (saturates at 255) |
| 31 | 1 | `reserved` | 0 |

## 7. DETAIL (TYPE `0x11`), slave → Master

Per-device and meter data that doesn't fit in the SUMMARY. Sent at +0.75 in the slot, one frame per cycle at most, `PRIO = 2`, `ACKREQ = 1`. Encrypted with `AppSKey`.

**Frame payload:** `kind` u8 · `count` u8 · `count` records. Max payload 243 B at SF7, 126 B at SF8.

| `kind` | Record | Size | Max per frame (SF7 / SF8) | When |
|---|---|---|---|---|
| `0x01` | basic | 12 B | 20 / 10 | Every 15 min for every device, and in the next free slot for every device set in `changed_bitmap` |
| `0x02` | extended | 12 B | 20 / 10 | Every 60 min for every device |
| `0x03` | meter | 44 B | 5 / 2 | Every 5 min (one record per section) |

**Basic record (12 B):**

| Off | Size | Field |
|---|---|---|
| 0 | 1 | `node_id` |
| 1 | 2 | `status` (device status bits, [03 §6](03-tier2-device-protocol.md)) |
| 3 | 1 | `level_actual` |
| 4 | 2 | `power_dw` (0.1 W) |
| 6 | 4 | `energy_wh` |
| 10 | 1 | `temp_c` (i8) |
| 11 | 1 | `fault_code` |

**Extended record (12 B):**

| Off | Size | Field |
|---|---|---|
| 0 | 1 | `node_id` |
| 1 | 2 | `voltage_dv` |
| 3 | 2 | `current_ma` |
| 5 | 2 | `lamp_hours` |
| 7 | 1 | `rssi` (i8 dBm, at the slave, last report) |
| 8 | 1 | `snr` (i8, 0.25 dB) |
| 9 | 1 | `slot` |
| 10 | 1 | `level_target` |
| 11 | 1 | `home_channel` (raster channel the device currently uses, [04 §2](04-channel-plan-and-airtime.md)) |

**Meter record (44 B):** `node_id` u8, then bytes 1–43 of the meter REPORT exactly as in [03 §7.2](03-tier2-device-protocol.md).

**Order of preference** when more than one frame is due: EVENT (P1) > changed-device basic records > meter > periodic basic > extended > FRAG. A slave with more due than one frame per cycle catches up over the following cycles. The Master ACKs each DETAIL with an `ACK` (§10); an unacknowledged DETAIL is resent once, then dropped (the next periodic round replaces it).

The Master updates each device's Modbus block from these records and stamps its age ([01](01-modbus-register-map.md)).

## 8. Configuration and whitelist

### 8.1 WHITELIST (TYPE `0x13`), Master → slave

The Master owns the site's device registry. Each slave holds only its section's entries. `AUTHORISE_DEVICE`, `REVOKE_DEVICE` and `REPLACE_DEVICE` jobs from the server ([01](01-modbus-register-map.md)) become WHITELIST frames. `PRIO = 2`, `ACKREQ = 1`, unicast, encrypted with `AppSKey`. Max 15 entries per frame at SF7 (4 + 15 × 15 = 229 B; 8 at SF8).

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `list_ver` | Version after this frame is applied |
| 2 | 1 | `op` | 1 add/update · 2 remove · 3 replace-all begin · 4 replace-all continue · 5 replace-all end |
| 3 | 1 | `count` | Entries in this frame |
| 4 | 15 × count | entries | See below |

**Entry (15 B):** `uid[12]` · `device_type` u8 (`0x01` LED, `0x02` meter) · `node_id` u8 (0 = slave picks) · `flags` u8 (bit0 authorised · bit1 decommissioned: refuse joins from this UID · bit2 replacement: takes over `node_id` from the previous holder).

A replace-all sequence (op 3, 4…, 5) is applied only when op 5 arrives with all frames acknowledged. Until then the old list stays active. The slave answers each frame with `ACK`. The new `list_ver` appears in the slave's `config_hash`.

### 8.2 Other configuration

Schedule, fail-safe levels and other section settings travel as CMDs (`SET_SCHEDULE`, `SET_FAILSAFE_LEVELS`, `REASSERT_CONFIG`). When the BEACON's `config_ver` differs from the slave's copy, the Master pushes the changed items to that slave in the following cycles. A slave never applies a configuration the Master didn't send.

## 9. EVENT (TYPE `0x03`), slave → Master

Alarms and state changes, including device events forwarded from the cell. `ACKREQ = 1` always. Encrypted with `AppSKey`.

**Where:** normally at +0.75 in the slave's own slot. Events with severity `critical` (`SECTION_DARK`, `MAINS_LOSS`, `PHASE_LOSS`) go in the **next contention window** if it comes sooner than the slot. Retry on no ACK: next slot, up to 3 times, then the event stays buffered (§13) and `events_pending` is set.

**Payload, 8–16 bytes:**

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `event_code` | Below, or a device event code `0x40`–`0x7F` from [03 §9](03-tier2-device-protocol.md) |
| 1 | 1 | `severity` | 0 info · 1 warning · 2 alarm · 3 critical |
| 2 | 2 | `subject` | 12-bit address the event is about (the slave itself = `n << 8`) |
| 4 | 4 | `utc` | When it happened (slave clock) |
| 8 | 0–8 | `data` | Event-specific |

**Slave and section event codes:**

| Code | Name | Severity | `data` |
|---|---|---|---|
| `0x01` | `SLAVE_RESTARTED` | warning | reset cause u8 (1 power-on, 2 brown-out, 3 watchdog, 4 software, 5 pin) |
| `0x02` | `NODE_MISSING` | alarm | last seen utc u32. Raised after **3 missed reports** (6 min) |
| `0x03` | `NODE_RETURNED` | info | — |
| `0x04` | `SECTION_DARK` | critical | expected level u8, measured power W u32 |
| `0x05` | `MAINS_LOSS` | critical | — (meter lost all phases, or all devices silent at once) |
| `0x06` | `PHASE_LOSS` | critical | phase mask u8 (bit0 L1, bit1 L2, bit2 L3) |
| `0x07` | `RADIO_FAILOVER` | alarm | radio id u8 (0 U0, 1 U1, 2 down A, 3 down B), reason u8 |
| `0x08` | `RADIO_FAILBACK` | info | radio id u8 |
| `0x09` | `DOWN_RADIO_FAILED` | alarm | radio id u8 (single-channel mode entered) |
| `0x0A` | `DOWN_RADIO_RESTORED` | info | radio id u8 |
| `0x0B` | `CLOCK_UNTRUSTED` | alarm | — |
| `0x0C` | `CLOCK_RESTORED` | info | correction applied, ms i32 |
| `0x0D` | `AIRTIME_EXHAUSTED` | warning | airtime_pct u8 |
| `0x0E` | `STATE_CHANGE` | info / alarm | old state u8, new state u8 (alarm when entering `DEGRADED`, `AUTONOMOUS` or `CLOCK_UNTRUSTED`) |
| `0x0F` | `CONFIG_DIVERGED` | warning | slave config_hash u16, expected hash u16 |
| `0x10` | `JOIN_REJECTED` | warning | first 8 bytes of the device UID |
| `0x11` | `BUFFER_OVERFLOW` | warning | events lost u16 |
| `0x12` | `STORAGE_FAULT` | alarm | storage id u8 (0 internal flash, 1 FRAM, 2 NOR) |
| `0x13` | `DEVICE_SWAPPED` | info | old UID first 4 bytes, new UID first 4 bytes |
| `0x14` | `STANDBY_RADIO_DOWN` | alarm | radio id u8 (0 U0, 1 U1). The inactive upstream radio failed self-test, or the Master's HEARTBEAT hasn't been heard on it for 3 consecutive cycles |
| `0x15` | `STANDBY_RADIO_RESTORED` | info | radio id u8 |
| `0x16` | `RF_DEGRADED` | warning | radio id u8 (0 U0, 1 U1, 2 down A, 3 down B), noise floor dBm i8, packet loss % u8. Noise floor more than 10 dB above the commissioning baseline, or packet loss above 20%, for 3 consecutive cycles |
| `0x17` | `RF_NORMAL` | info | radio id u8 |
| `0x18`–`0x3F` | reserved | | |

The Master also generates events about the tier-1 link and itself (section lost, its own radio failover, its own clock, server lost) directly into the Modbus event buffer, as codes `0x8001`+ ([01 §7.3](01-modbus-register-map.md)). Those never go over the air. A slave's own failover, clock and airtime events arrive only as the codes above, so nothing is reported twice.

## 10. ACK (TYPE `0x06`), 5 bytes, either direction

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | `acked_fcnt` | `FCNT32` of the frame being acknowledged |
| 4 | 1 | `result` | 0 OK · 1 duplicate · 2 rejected · 3 busy, retry later · 4 `REJOIN` (session unknown, join again) |

Encrypted with `AppSKey`. An ACK is never acknowledged.

## 11. Commands

### 11.1 CMD (TYPE `0x04`), Master → slave(s)

Unicast to `n << 8`, or broadcast to `0xF00` (all slaves, MIC/encrypted with `NetKey`). Unicast is encrypted with `AppSKey`. **Payload: 13-byte header + params.**

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `cmd_id` | Low 16 bits of the Master job ID. Also the end-to-end duplicate key |
| 2 | 1 | `opcode` | Table below |
| 3 | 2 | `target` | 12-bit address ([00 §3](00-common-frame-and-conventions.md)) or `0x8000 \| g` for group g (0–15) |
| 5 | 4 | `execute_at` | UTC seconds. 0 = execute on receipt |
| 9 | 4 | `not_after` | UTC seconds. Discard if received or still queued after this |
| 13 | 0–32 | `params` | Per opcode |

**Opcodes** (same numbers as the Modbus mailbox, [01](01-modbus-register-map.md)):

| Op | Name | Params | Priority on air |
|---|---|---|---|
| `0x01` | `SET_LEVEL` | `level` u8 · `fade` u8 (DALI fade index) · `override_ttl_min` u16 (0 = until next schedule step, max 720) | P0 if group/section/site, P1 if one device |
| `0x02` | `RESUME_SCHEDULE` | — | as `SET_LEVEL` |
| `0x03` | `IDENTIFY` | `pattern` u8 · `duration_s` u16 | P1 |
| `0x04` | `QUERY` | — | P2 |
| `0x05` | `SET_TIME` | Server → Master only. Never sent on tier 1 | — |
| `0x06` | `SET_SCHEDULE` | `lat` i32 (1e-5°) · `lon` i32 · `dusk_offset_min` i16 · `dawn_offset_min` i16 · `n_steps` u8 · up to 4 × {`local_minute` u16 · `level` u8} (13–25 B) | P2 |
| `0x07` | `REBOOT` | — | P2 |
| `0x08` | `OPEN_COMMISSIONING` | `duration_min` u16 | P2 |
| `0x09` | `AUTHORISE_DEVICE` | Becomes a WHITELIST frame (§8.1), not a CMD | — |
| `0x0A` | `REVOKE_DEVICE` | Becomes a WHITELIST frame | — |
| `0x0B` | `REPLACE_DEVICE` | Becomes a WHITELIST frame (flag `replacement`) | — |
| `0x0C` | `REPLACE_DRIVER` | — | P2 |
| `0x0D` | `REASSERT_CONFIG` | — | P2 |
| `0x0E` | `SET_FAILSAFE_LEVELS` | `power_on_level` u8 · `system_failure_level` u8 | P2 |
| `0x0F` | `FORCE_FAILOVER` | `mode` u8: 0 back to primary, 1 force standby | P1 |

### 11.2 CMD_ACK (TYPE `0x05`), slave → Master, 15 bytes

Sent once when the slave accepts the command, and again when the job ends in its section. Encrypted with `AppSKey`.

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `cmd_id` | |
| 2 | 1 | `result` | Result code, §11.5 |
| 3 | 1 | `n_targets` | Devices addressed in this section |
| 4 | 1 | `n_confirmed` | Devices whose report or CMD_ACK confirms the result |
| 5 | 1 | `n_failed` | Devices that didn't confirm by the deadline |
| 6 | 1 | `job_state` | Section-level state, same codes as the Modbus job state ([01](01-modbus-register-map.md)) |
| 7 | 8 | `fail_bitmap` | u64, bit k = NodeID k not confirmed |

A slave confirms a broadcast command from its devices' next REPORTs (`last_cmd_fcnt_lo` and `level_actual`, [03](03-tier2-device-protocol.md)). It sends the final CMD_ACK when every target has confirmed, or **2 cycles after `execute_at`**, whichever is first. The final CMD_ACK goes in the slave's slot at +0.75, or in the contention window if the job is P0.

### 11.3 From a Modbus job to radio frames

| Modbus `target` | Tier-1 action | Tier-2 action ([03](03-tier2-device-protocol.md)) |
|---|---|---|
| Device `0x0snn` | Unicast CMD to slave s | Unicast CMD to the device; CMD_ACK back |
| Section `0x0sFF` | Unicast CMD to slave s | Cell broadcast on both channels |
| Site `0x0FFF` | Broadcast CMD to `0xF00` | Every slave broadcasts into its cell |
| Group `0x8000 \| g` | Broadcast CMD to `0xF00` | Every slave broadcasts with group g |

- For lighting commands to more than one device, the Master sets `execute_at` = now + 8 s (configurable, minimum 5 s), so every device switches together.
- The Master aggregates the slaves' CMD_ACKs into the job's progress and fail mask. The job ends `CONFIRMED`, `PARTIAL`, `FAILED` or `EXPIRED`.
- **Absolute commands only.** There is no toggle or relative command.
- The `cmd_id` lets every hop drop a duplicate: a slave or device that has already seen a `cmd_id` acknowledges it as `duplicate` and doesn't execute it again.

### 11.4 P0 handling

- A P0 CMD is sent **immediately**, not in a window, **on both tier-1 radios**, and repeated once 1 s later.
- **The copies are byte-identical** (same `FCNT`). Receivers drop the second and later copies by the duplicate window ([00 §6.3](00-common-frame-and-conventions.md)) and by `cmd_id`.
- A slave receiving a P0 CMD forwards it into its cell immediately ([04 §6.4](04-channel-plan-and-airtime.md)) and sends its first CMD_ACK (`result = 1`) in the next contention window or slot.
- P0 traffic may use the 25% airtime reserve ([04 §7](04-channel-plan-and-airtime.md)).
- A slave in `DEGRADED`, `AUTONOMOUS` or `CLOCK_UNTRUSTED` state **may refuse an unsafe command** (any `SET_LEVEL` below the scheduled level while its clock is untrusted) with `result = 4` (`REFUSED_UNSAFE`).
- A CMD received, or still queued, after `not_after` is discarded and answered `result = 3` (`EXPIRED`).

### 11.5 Result codes

**One table for the whole system.** The same numbers are used in tier-1 CMD_ACK (§11.2), tier-2 CMD_ACK ([03 §10.3](03-tier2-device-protocol.md)) and the Modbus `job_result` register ([01 §8.5](01-modbus-register-map.md)). ✓ = the code can appear there.

| Code | Name | Meaning | T1 CMD_ACK | T2 CMD_ACK | `job_result` |
|---|---|---|---|---|---|
| 0 | `OK` | Executed / confirmed / no error | ✓ | ✓ | ✓ |
| 1 | `ACCEPTED` | Accepted, waiting for `execute_at` (interim answer) | ✓ | ✓ | |
| 2 | `DUPLICATE` | Already seen (`FCNT` or `cmd_id`); acknowledged, not executed again | ✓ | ✓ | |
| 3 | `EXPIRED` | Received or still queued after `not_after` (radio) or the job TTL (Modbus); discarded | ✓ | ✓ | ✓ |
| 4 | `REFUSED_UNSAFE` | Refused by a safety rule, e.g. `SET_LEVEL` below 254 with an untrusted clock, or a `SET_TIME` jump without `force` | ✓ | ✓ | ✓ |
| 5 | `BAD_OPCODE` | Unknown or reserved opcode | ✓ | ✓ | ✓ |
| 6 | `BAD_PARAMS` | A parameter out of range, or an unused parameter not 0 | ✓ | ✓ | ✓ |
| 7 | `BUSY` | Can't accept now; retry later. (On Modbus a full queue is exception `0x06` instead) | ✓ | ✓ | |
| 8 | `TARGET_NOT_CONFIGURED` | Section or device not configured / not found | ✓ | | ✓ |
| 9 | `PARTIAL` | Some targets confirmed, some not (see the fail bitmap). On Modbus this is the job state `PARTIAL` | ✓ | | |
| 10 | `FAILED` | Execution failed (e.g. a DALI error), or no target confirmed. On Modbus this is the job state `FAILED` | ✓ | ✓ | |
| 11 | `BAD_TARGET` | Target not valid for this opcode | | | ✓ |
| 12 | `BAD_CRC` | `cmd_args_crc` doesn't match | | | ✓ |
| 13 | `TARGET_OFFLINE` | Target offline at dispatch (unicast only) | ✓ | | ✓ |
| 14 | `TIMEOUT` | TTL reached before every target confirmed | | | ✓ |
| 15 | `NOT_SUPPORTED` | Target doesn't support the opcode (e.g. `REPLACE_DRIVER` on a meter) | ✓ | ✓ | ✓ |
| 16 | `AIRTIME_DEFERRED` | Couldn't be sent within its TTL because of the airtime budget | ✓ | | ✓ |
| 17 | `SUPERSEDED` | Replaced by a newer command for the same target | | | ✓ |
| 18 | `TOO_LATE` | `execute_at` in the past or more than 24 h ahead | | | ✓ |
| 19–255 | — | Reserved | | | |

## 12. Redundant radios: HEARTBEAT, failover, failback

### 12.1 HEARTBEAT (TYPE `0x12`), 4 bytes

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | `cycle_seq` | Current cycle |
| 2 | 1 | `radio_flags` | bit0 primary radio healthy · bit1 standby radio healthy · bit2 sender is failed over |
| 3 | 1 | `peer_rssi` | i8 dBm. RSSI of the last frame the sender received from the peer on this channel (127 = none) |

- **Master:** every cycle at 0.5 s on the channel that isn't carrying the BEACON. Broadcast `0xF00`, MIC'd with `NetKey`, not encrypted.
- **Slave n:** every 5th cycle, on the inactive upstream radio, at +1.50 in its own slot, in cycles where `(cycle_seq + n) mod 5 = 0`. Unicast to `0x000`, MIC'd with `NwkSKey`, not encrypted ([00 §6.4](00-common-frame-and-conventions.md)).

### 12.2 Failover and failback

| Who | Fails over when | Fails back when |
|---|---|---|
| **Master** | Its primary radio fails a self-test (SPI register read-back, TX-done timeout), **or** no valid frame from any slave arrives on the primary for **3 consecutive cycles** while frames do arrive on the standby | The primary passes self-test and receives at least one valid frame, for **5 consecutive cycles** (10 min) |
| **Slave** (per its own upstream radios) | It misses **3 consecutive BEACONs** on the active channel while it still hears the Master's HEARTBEAT on the other channel, or its upstream radio fails self-test. It then sends its SUMMARY on the other channel | It hears the BEACON on the active channel again for **5 consecutive cycles** |

- After a Master failover, the BEACON moves to ch 13 and the HEARTBEAT to ch 0 (`standby_active` set). The primary keeps being exercised by the HEARTBEAT.
- Every failover and failback raises an event and is shown in the Modbus map: a slave sends `RADIO_FAILOVER` / `RADIO_FAILBACK` (§9); the Master raises its own as `TIER1_FAILOVER` / `TIER1_FAILBACK` ([01 §7.3](01-modbus-register-map.md)).
- A failed standby radio raises `STANDBY_RADIO_DOWN`. Detection: radio self-test fails, or no HEARTBEAT is heard on it for **3 consecutive cycles at a slave** (the Master sends one every cycle) or **10 consecutive cycles at the Master** (each slave sends one every 5th cycle). Event codes: §9 for a slave, [01 §7.3](01-modbus-register-map.md) for the Master.
- `FORCE_FAILOVER` (§11.1) triggers the same switch on demand. It is used for the M3 acceptance test together with disconnecting the primary antenna.
- During failover, slots, timing and addresses don't change. Only the channel does.

## 13. Time

### 13.1 Distribution

- The Master is the time root. Its time comes from its RTC, corrected by the server's `SET_TIME` ([01](01-modbus-register-map.md)). The Master rejects a jump of more than 5 minutes unless `force = 1`.
- **The `utc` + `ms` in a BEACON is the Master's clock at the moment the frame's transmission ends (TxDone).** The Master computes it as scheduled TX start + time on air.
- A slave timestamps the BEACON at RxDone (DIO0 interrupt) and computes `offset = beacon_time − local_time_at_rxdone`.
- The slave filters the offset with an EWMA (α = 1/4), estimates its own rate error over at least 10 BEACONs, and extrapolates between BEACONs. It steps its clock only if the offset exceeds 1 s; otherwise it slews.
- A slave that hears only the HEARTBEAT (no BEACON) uses its known send time (cycle start + 0.5 s) as the time reference.

### 13.2 Clock trust

| Node | Clock is trusted when | Untrusted when |
|---|---|---|
| Master | The RTC kept time through the last power cycle (backup domain valid), **or** a `SET_TIME` was accepted since boot | RTC invalid after power-up and no `SET_TIME` yet |
| Slave | It accepted a BEACON with `clock_trusted = 1` in the last 24 h, **or** its RTC kept time through the last power cycle and it was synced within the last 7 days | Neither |

An untrusted clock puts the slave in `CLOCK_UNTRUSTED`: lights at **100% (level 254)** until time is restored ([05](05-fail-safe-behaviour.md)).

## 14. Slave state machine

Timers assume `CYCLE = 120 s`. They are counted in cycles, so they scale with the cycle length.

| State | Entered when | Behaviour |
|---|---|---|
| `SYNCED` | BEACON received within the last 2 cycles, session valid | Normal operation |
| `DEGRADED` | **3 missed BEACONs** (6 min) | Keep running the local astronomical schedule. Keep an override **only if it hasn't expired**. Buffer events. Event `STATE_CHANGE` |
| `AUTONOMOUS` | **30 missed BEACONs** (60 min) | **Discard all overrides.** Run the pure local schedule. Set `slave_autonomous` in the cell beacon. Look for the Master every cycle; try to rejoin with backoff (1, 2, 4 … cycles, max 5 cycles = 10 min) |
| `CLOCK_UNTRUSTED` | Clock untrusted (§13.2), in any state | **Lights 100%** in the section until time is restored. Overrides ignored |
| `REJOINING` | BEACON heard again after `DEGRADED` or `AUTONOMOUS`, or after boot | Join (§4), resync time, send SUMMARY with `config_hash`. Return to `SYNCED` once joined and the configuration is checked |

**On rejoin:**

1. The Master compares the slave's `config_hash` with its own record.
2. If they differ, the Master raises `CONFIG_DIVERGED` and pushes **only the changed items** from its registry and configuration (the server-intended configuration wins). It never wipes and reloads the slave without logging it.
3. Overrides from before the outage are not re-applied.
4. The slave replays buffered events **oldest first**, one per slot (plus one in the contention window if critical), keeping each event's original timestamp.

## 15. Single-channel mode

When one downstream radio fails ([04 §6.2](04-channel-plan-and-airtime.md)):

1. The slave sets `single_channel_mode` in its SUMMARY and its cell beacon, and raises `DOWN_RADIO_FAILED`.
2. All 64 slot positions run back to back on the surviving channel. The cell's uplink period ends at cell time 20.8 s.
3. **The slave moves its own cell cycle 10 s earlier** (`cell_start'(n) = cell_start(n) − 10 s`). The Master's slot for that slave doesn't move. It now falls at cell time 23–25 s, inside a quiet window of 21–26 s.
4. The cycle in which the shift happens is 10 s shorter for that cell. Devices resynchronise on the next cell beacon ([03](03-tier2-device-protocol.md)).
5. The shifted beacons never coincide with the Master's beacon (0–0.6 s): `cell_start'(n) = 2n − 23` is always odd, so the nearest are 119 s and 1 s.

## 16. Store-and-forward

| Box | Buffers | Size (minimum) | On reconnect |
|---|---|---|---|
| Slave | Events | 1 000 events, ring, oldest overwritten, `BUFFER_OVERFLOW` raised | Replayed oldest first (§14) |
| Slave | Section summary every 15 min | 7 days | Sent as low-priority DETAIL catch-up only if the Master asks (`QUERY` to the slave) |
| Master | Events for the server | 2 000 events, ring | Read by the server from the Modbus event buffer ([01](01-modbus-register-map.md)) |

Event buffers are persisted (NOR or FRAM), so they survive a reboot.

## 17. FRAG / FRAG_STATUS (TYPEs `0x0A`, `0x0B`)

For anything bigger than one frame: a full whitelist dump, configuration blobs, log retrieval. Ordinary commands, including `SET_SCHEDULE`, fit in one frame and don't use this.

**FRAG payload:**

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | `session` | Chosen by the sender, unique among its open transfers |
| 1 | 1 | `index` | 0 … `total − 1` |
| 2 | 1 | `total` | Number of fragments (max 255) |
| 3 | N | `data` | Fragment 0 starts with a 7-byte block header: `content` u8 (1 config blob, 2 whitelist dump, 3 log, 4 schedule table) · `length` u16 · `crc32` u32 over the whole block |

**Fragment size:** SF7 = 232 B, SF8 = 120 B, SF9 = 48 B (tier 2 only). All fragments except the last are full.

**FRAG_STATUS payload:** `session` u8 · `total` u8 · `missing_bitmap` (⌈total/8⌉ bytes, bit i = fragment i missing).

**Procedure:**

1. The sender sends all fragments, P3, in downlink time (Master) or its own slot (slave, one per cycle).
2. After the last fragment, the receiver answers with FRAG_STATUS.
3. The sender resends only the missing fragments. Up to 3 rounds.
4. The receiver checks the block CRC-32. An all-zero FRAG_STATUS means done. A CRC failure discards the block and the receiver reports all fragments missing.
5. A session idle for 10 cycles is abandoned by both sides.

## Open items

| # | Item | Needed by |
|---|---|---|
| O-02-4 | Validate the failover thresholds (3 missed / 5 clean cycles) on the bench by pulling the primary antenna | M3 |
| O-02-5 | ⚠ Confirm the slave's clock-trust window (24 h synced / 7 days on RTC) against measured RTC drift in a hot enclosure | M3 |
| O-02-6 | Decide the outage history retention the client wants (7 days of 15-min summaries assumed) | M1 sign-off |
