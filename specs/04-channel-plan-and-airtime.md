# 04 — Channel Plan and Airtime Budget

| | |
|---|---|
| **Spec** | 04 — Channel plan and airtime budget |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-29 |
| **Owner** | pgorospe |
| **Reviewers** | Gateway hardware developer (for the client), device developer |
| **Status** | Draft. Provisional until NTC confirms the radio limits (SOW assumption A3) |

Which frequencies each link uses, which spreading factors, the cycle timing on both tiers, and proof that the traffic fits the regulatory limits. Shared conventions are in [00](00-common-frame-and-conventions.md).

## 1. Radio limits designed to

| Limit | Value | Status |
|---|---|---|
| Band | 915–918 MHz | Decided. ⚠ Licensing status unconfirmed |
| Channel width | 125 kHz | Decided |
| Max EIRP | 16 dBm | ⚠ Awaiting NTC |
| Max single transmission | 400 ms | ⚠ Awaiting NTC |
| Duty cycle | ≤1%, rolling 1 hour, **per box** (all radios in one enclosure together) | ⚠ Awaiting NTC: per box or per radio (Q21) |

All of these are configuration values with a compile-time ceiling. A different NTC answer changes configuration and this budget, not the protocol.

## 2. Channel raster

14 channels, 200 kHz apart. Each 125 kHz channel stays inside 915–918 MHz.

| Ch | Centre (MHz) | Ch | Centre (MHz) |
|---|---|---|---|
| 0 | 915.2 | 7 | 916.6 |
| 1 | 915.4 | 8 | 916.8 |
| 2 | 915.6 | 9 | 917.0 |
| 3 | 915.8 | 10 | 917.2 |
| 4 | 916.0 | 11 | 917.4 |
| 5 | 916.2 | 12 | 917.6 |
| 6 | 916.4 | 13 | 917.8 |

`f(ch) = 915.2 MHz + ch × 0.2 MHz`. The SX1276 frequency register value is `Frf = f / 61.03515625 Hz`.

## 3. Channel assignment

| Link | Channel(s) | Why |
|---|---|---|
| **Tier 1, primary** | **Ch 0** (915.2) | Lowest band edge |
| **Tier 1, standby** | **Ch 13** (917.8) | Opposite band edge: maximum frequency diversity from the primary |
| **Section n, cell channel A** | **Ch n** | n = 1…6 |
| **Section n, cell channel B** | **Ch n + 6** | 1.2 MHz from channel A, so a slave's two receivers aren't on adjacent channels |

| Section | Ch A | Ch B |
|---|---|---|
| 1 | 1 (915.4) | 7 (916.6) |
| 2 | 2 (915.6) | 8 (916.8) |
| 3 | 3 (915.8) | 9 (917.0) |
| 4 | 4 (916.0) | 10 (917.2) |
| 5 | 5 (916.2) | 11 (917.4) |
| 6 | 6 (916.4) | 12 (917.6) |

**Sections 7–14 reuse the pairs of sections 1–6** (section n uses the pair of section n − 6). Reuse is only allowed between sections that are physically far apart, which must be confirmed by survey. The number of sections isn't fixed. Up to 6 need no reuse. Channel assignments are configuration, so the plan can change after the NTC answer and the site survey without a firmware change.

## 4. Spreading factor

| Link | Default SF | Allowed | Reason |
|---|---|---|---|
| Tier 1 | **SF7** | SF7–SF8 | Gateways are mounted high and near line of sight. SF9 on tier 1 breaks the slave's duty budget at the default cycle (§7) |
| Tier 2 (cell) | **SF9** | SF7–SF9, one value per cell | Street level, no line of sight. Slots are sized for SF9 |

SF10 and above are not used in v1. A link that doesn't close at SF9 is fixed with antenna height or placement, not with a slower data rate. Retries don't escalate SF inside a scheduled cell, because the slot length is fixed.

## 5. Time on air

125 kHz, CR 4/5, 8-symbol preamble, explicit header, CRC on. Frame size includes the 12-byte overhead.

| Frame | Size | SF7 | SF8 | SF9 |
|---|---|---|---|---|
| Tier-1 heartbeat | 16 B | 51 ms | 93 ms | 165 ms |
| Tier-1 beacon | 25 B | 62 ms | 113 ms | 206 ms |
| Tier-1 summary | 44 B | 92 ms | 164 ms | 288 ms |
| Tier-1 detail (20 device records) | 252 B | 394 ms | — | — |
| Cell beacon (with event-ACK bitmap) | 27 B | — | — | 226 ms |
| LED device report | 32 B | 72 ms | 134 ms | **247 ms** |
| Meter report | 56 B | 108 ms | 195 ms | **349 ms** |
| Cell group command | 28 B | — | — | 226 ms |

Firmware computes time on air with the Semtech formula (`lora_airtime_ms()`) and refuses any frame over 400 ms.

## 6. Cycle timing

**One cycle length for the whole site: `CYCLE = 120 s` (default).** Allowed values: 120, 180, 300 s. 60 s is allowed only if NTC confirms one duty-cycle budget **per radio** (§7).

### 6.1 Tier-1 superframe (Master clock)

```
t (s)                       Master time, from the start of the cycle
0.0    BEACON on the primary channel (ch 0)
0.5    HEARTBEAT on the standby channel (ch 13)       ← proves the standby path every cycle
1.0    contention window, 1 s: slave EVENTs and JOIN_REQs
2.0    slot for slave 1      ┐
4.0    slot for slave 2      │  T1_SLOT = 2.0 s each, in GwID order.
…                            │  Slots exist only for configured slaves.
2 + 2(n−1)  slot for slave n ┘  14 slaves end at 30 s.
30 → 120   master downlinks: unicast commands, whitelist pushes, fragment transfers, retries
```

Inside a slave's 2-second slot:

```
+0.00  slave → master   SUMMARY                      (always)
+0.25  master → slave   ACK / CMD (optional)         (downlink window, 0.5 s)
+0.75  slave → master   DETAIL or FRAG (optional)    (if the slave has detail due)
+1.25  master → slave   ACK (optional)
+2.00  slot ends
```

### 6.2 Cell cycle (one per slave)

```
t (s)   cell time, from the start of the slave's cell cycle
0.00    BEACON on channel A
0.25    BEACON on channel B
0.60    contention window, 1 s, both channels: device EVENTs, JOIN_REQs
1.60    uplink slots: 32 per channel, 0.30 s each           → ends 11.20
11.20   guard
12.00   QUIET WINDOW, 4 s: no cell traffic. The slave does its tier-1 slot here
16.00   downlink window: unicast CMDs, group CMDs, JOIN_ACCs, fragment transfers, retries
120.00  next cycle
```

- **Slots:** 64 slot positions per cell, numbered 0–63. Slots 0–31 run on channel A and 32–63 on channel B, at the same times. An LED device uses 1 slot. The meter uses 2 consecutive slots (0.6 s) on the same channel. 60 devices with one meter need 61 slot positions.
- **One channel lost:** if one downstream radio fails, the surviving channel runs all slot positions back to back. 64 × 0.3 s = 19.2 s starting at 1.6 s, so it ends at 20.8 s. The quiet window moves to 21–26 s, and **the downlink window starts at 26 s**. **The slave starts its cell cycle 10 s earlier** (`cell_start(n) − 10 s`), so its unchanged tier-1 slot now falls at cell time 23–25 s, inside the new quiet window. The Master's slot plan doesn't change, so neighbouring slaves are unaffected. The slave reports the mode change in its SUMMARY ([02](02-tier1-protocol.md) §15).
- **The mode changes only at a cycle boundary.** To enter single-channel mode, the slave cuts the current cycle to `CYCLE − 10 s`. To leave it, the slave stretches the current cycle to `CYCLE + 10 s`. The first beacon with the new flag is also the first at the new timing, so the slave and its devices never run on different timings within a cycle.
- **Devices listen continuously** outside their own slot. A unicast or group command can therefore be sent at any time in the downlink window, and needs no prior announcement.

### 6.3 Aligning a cell with its tier-1 slot

A slave can't receive from its devices while it transmits to the master, so its tier-1 slot must fall inside its quiet window. Each slave starts its cell cycle at a fixed offset from master time:

```
cell_start(n) = ( 2 + 2(n − 1) − 13 ) mod CYCLE        seconds of master time
```

This puts slave n's tier-1 slot at cell time 13–15 s, inside the 12–16 s quiet window. The offset also keeps every slave's cell beacons clear of the master's beacon at 0–0.6 s.

### 6.4 P0 exception

A P0 command (emergency lights on, group switching) doesn't wait for a window:

- The Master sends it immediately, on **both** tier-1 radios, and repeats it once 1 s later.
- A Slave receiving it broadcasts it into its cell immediately, on both channels, and repeats it once 1 s later. Any device reports lost to this pre-emption are not retried: reports are snapshots, and the next cycle's report replaces them.
- Every P0 command carries `execute_at` at least 5 s in the future, so all devices act at the same moment.

## 7. Duty-cycle budget

Budget per box: 1% of 3600 s = **36 s of transmit time per hour**. **25% (9 s) is reserved for P0** and can't be used by anything else.

### 7.1 Slave (the critical box)

At `CYCLE = 120 s` (30 cycles per hour), SF9 cell, SF7 tier 1:

| Traffic | Per cycle | Per hour |
|---|---|---|
| Cell beacons, 2 channels | 453 ms | 13.6 s |
| Tier-1 SUMMARY | 92 ms | 2.8 s |
| Standby HEARTBEAT (every 5th cycle) | 10 ms average | 0.3 s |
| Tier-1 DETAIL basic records, all 60 devices every 15 min (3 frames per 15 min) | — | 4.7 s |
| Tier-1 DETAIL extended records, all 60 devices every hour (3 frames) | — | 1.2 s |
| Tier-1 meter record, every 5 min | — | 1.3 s |
| **Scheduled total** | | **23.9 s (66%)** |
| P0 reserve | | 9.0 s (25%) |
| Left for commands, retries, joins, fragments | | 3.1 s (9%) |

The margin left for commands and retries is thin. If it proves too thin on the bench, the first lever is the detail interval: 30 min instead of 15 frees 2.4 s/h.

| Cycle | Scheduled slave load | Verdict |
|---|---|---|
| 60 s | ~40 s/h = **~112%** | ❌ Doesn't fit under a per-box 1% budget |
| **120 s** | 23.9 s/h = **66%** | ✅ Default |
| 180 s | ~18 s/h = ~51% | ✅ More margin, slower status |

**If NTC confirms one budget per radio**, the slave's load is spread over 4 radios and a 60 s cycle fits.

### 7.2 Master

Beacon + standby heartbeat every cycle: 3.7 s/h (10%) at 120 s. The rest is for commands, whitelist pushes and retries. The Master is not the limiting box.

### 7.3 Device

An LED device sends one 247 ms report per cycle: 0.2% at 120 s. The meter sends 349 ms: 0.3%. Events and rejoins are rare. Devices are far inside the limit.

### 7.4 Enforcement

- Every box keeps a **rolling 1-hour airtime ledger** across all its radios.
- Before each TX: if the frame would push the box over `(100% − P0 reserve)`, a P1–P3 frame is deferred, and only P0 may use the reserve.
- The ledger state (seconds used in the last hour) is reported in diagnostics and in the Modbus map.

## 8. What the timing means for users

| Operation | Expected time |
|---|---|
| Group on/off/dim (P0 path), from server command to lights switching | **5–10 s**, all lights together |
| Single-pole command | Up to ~30 s, inside the next downlink window |
| Device status visible at the server | Within one cycle (≤ 2 min) |
| Per-device power and energy at the server | Within 15 min (configurable detail interval) |
| Device alarm at the server | Usually < 2 min (next contention window and tier-1 slot) |
| Device declared offline | After 3 missed reports (6 min) |

## Open items

| # | Item | Needed by |
|---|---|---|
| O-04-1 | NTC answers: EIRP, dwell, duty cycle, per-box or per-radio, licensing (SOW A3, wiki Q1/Q21) | End of week 3 |
| O-04-2 | Is a 2-minute status cycle acceptable to the client? (60 s needs a per-radio duty answer) | M1 sign-off |
| O-04-3 | Band occupancy scan at the site before channels are fixed | Before field use |
| O-04-4 | Confirm the sections that will reuse a channel pair are far enough apart (only if there are more than 6 sections) | Survey |
