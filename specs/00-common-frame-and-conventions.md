# 00 — Common Frame Format and Conventions

| | |
|---|---|
| **Spec** | 00 — Common frame format and conventions |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-20 |
| **Owner** | pgorospe |
| **Reviewers** | Device developer, gateway hardware developer (for the client) |
| **Status** | Draft. Not frozen |

This document holds everything the other specs share: units and byte order, addressing, the frame format used on both LoRa tiers, and the security layer. If another spec contradicts this one, this one wins and the conflict is a bug to report.

## 1. Words used in these specs

| Term | Meaning |
|---|---|
| **Server** | The Local Monitoring Server (PC). Talks Modbus RTU to the Master |
| **Master** | The Master LoRa Gateway. One per site. 2 radios |
| **Slave** | A Slave LoRa Gateway. One per section. 4 radios. The number of sections is configured, from 1 to 14 |
| **Device** | A per-pole LoRa LED driver/monitoring device, or a section energy meter. 1 radio. Built by the device developer |
| **Section** | The group of devices served by one Slave. Up to 60 devices (LED devices + the meter) |
| **Tier 1** | The radio link between the Master and the Slaves |
| **Tier 2** | The radio link between a Slave and its devices (the "cell") |
| **Cycle** | The repeating timing period on both tiers. Default 120 s ([04](04-channel-plan-and-airtime.md)) |
| **Uplink / downlink** | Uplink = toward the Master and Server. Downlink = away from them |
| **P0–P3** | Traffic priority. P0 = safety/control, P1 = alarms, P2 = routine telemetry, P3 = bulk |
| **MUST / SHOULD / MAY** | Requirement levels, as in RFC 2119 |

## 2. Conventions

### 2.1 Byte order

| Where | Rule |
|---|---|
| **LoRa frames (both tiers)** | **Little-endian** for every multi-byte field |
| **Modbus registers** | Each 16-bit register is big-endian (Modbus standard). **32-bit values use two registers, high word first** (lower address = high word) |

### 2.2 Units and encodings

| Quantity | Encoding |
|---|---|
| Time | `uint32` Unix time, seconds, **UTC**. Sub-second fields are `uint16` milliseconds |
| Local time | UTC + `tz_offset_min` (`int16`, minutes). Philippines = `+480`. No daylight saving |
| Light level | **DALI arc power level**, `uint8`: 0 = off, 1–254 = DALI logarithmic curve, 255 = unknown / no change. The server converts to and from percent |
| Voltage | `uint16`, 0.1 V (dV) |
| Current | `uint16`, mA (device) or 10 mA (meter phase currents) |
| Power | `uint16`, 0.1 W (device); `int32`, W (meter totals) |
| Energy | `uint32`, Wh, cumulative and monotonic |
| Temperature | `int8` (radio) / `int16` (Modbus), °C |
| RSSI / SNR | `int8` dBm / `int8` 0.25 dB steps (SX1276 native) |
| Not available | All bits set for that width (`0xFF`, `0xFFFF`, `0xFFFFFFFF`), or `0x7F…` for signed fields |

### 2.3 Identity

Three separate namespaces. They are never mixed.

| Namespace | Size | Example | Used where |
|---|---|---|---|
| **UID** | 96 bits (12 bytes), the STM32 unique device ID | `0x0037002B…` | Provisioning, joining, key derivation. Never in routine frames |
| **Address** | 12 bits, `GwID:4 | NodeID:8` | `0x311` = section 3, node 0x11 | Every radio frame, every Modbus device reference |
| **Asset ID** | text | `PH-SITE1-S3-P017` | Server only: maps, work orders |

## 3. Addressing

Each site has an 8-bit **NetID** (configured at commissioning, 1–254). Inside the site, every node has a 12-bit address:

```
address = (GwID << 8) | NodeID
```

| GwID | Meaning |
|---|---|
| 0 | The Master |
| 1–14 | Slave of section 1–14 |
| 15 | All gateways (tier-1 broadcast) |

| NodeID | Meaning |
|---|---|
| 0 | The gateway itself |
| 1–63 | Devices in that section (60 used at most; 61–63 spare) |
| 64–253 | Reserved for future growth. Not assigned in v1 |
| 254 | An unjoined device (used only in `JOIN_REQ`) |
| 255 | All devices in the section (cell broadcast) |

Examples: Master `0x000`. Slave of section 3 `0x300`. Device 17 in section 3 `0x311`. All devices in section 3 `0x3FF`. All slaves `0xF00`. Whole site, every device `0xFFF`.

**Device addresses are assigned by the Slave at join and never change for a given UID**, so a rejoining device gets the same address back. A device swap moves the old address to the new UID ([03](03-tier2-device-protocol.md)). The same 12-bit address is used as the device reference in the Modbus register map ([01](01-modbus-register-map.md)).

## 4. Radio settings common to both tiers

| Setting | Value |
|---|---|
| Radio | Semtech SX1276, 915 MHz module variants only |
| Modulation | LoRa, **125 kHz**, coding rate **4/5**, **explicit header**, **PHY CRC on** |
| Preamble | 8 symbols |
| Sync word | `0x12` (private). Configurable per site. Never `0x34` (LoRaWAN) |
| IQ | **Normal on uplink, inverted on downlink.** Devices don't hear each other's uplinks, and slaves don't hear each other's beacons |
| Spreading factor | SF7–SF9 in v1 (per tier, see [04](04-channel-plan-and-airtime.md)). SF11/SF12 are never used |
| Max single transmission | **400 ms** (dwell limit). Every TX is checked against the time-on-air formula before it is sent |
| Max EIRP | **16 dBm.** Conducted power = 16 dBm − antenna gain + cable loss, set per radio in configuration |
| Duty cycle | ≤1% per **box** (all radios in an enclosure share one budget), rolling 1-hour window |

## 5. Frame format

One frame format for both tiers and all roles. 8-byte header, payload, 4-byte MIC: **12 bytes of overhead**.

```
 Offset  Size  Field
 0       1     VER:4 | DIR:1 | ACKREQ:1 | PRIO:2      (bit 7 … bit 0)
 1       1     TYPE
 2       1     NETID
 3       3     DST:12 | SRC:12                         (24-bit little-endian; DST = bits 0–11, SRC = bits 12–23)
 6       2     FCNT                                    (low 16 bits of the sender's 32-bit frame counter, LE)
 8       0–N   PAYLOAD                                 (encrypted, see §6)
 8+N     4     MIC                                     (see §6)
```

| Field | Rule |
|---|---|
| `VER` | Protocol version, bits 7–4 of byte 0. **v1 = `0x1`.** A receiver MUST drop frames with a version it doesn't support, without replying |
| `DIR` | Bit 3. 0 = uplink, 1 = downlink. Also an input to the MIC, so an uplink can't be replayed as a downlink |
| `ACKREQ` | Bit 2. 1 = the receiver must acknowledge this frame |
| `PRIO` | Bits 1–0. 0 = P0 … 3 = P3 |
| `TYPE` | Message type, see §7 |
| `NETID` | Site ID. Frames for another NetID are dropped before any crypto work |
| `DST`, `SRC` | 12-bit addresses (§3) |
| `FCNT` | Low 16 bits of the 32-bit per-sender counter. Strictly increasing per sender and session. The receiver rebuilds the top 16 bits (§6.3) |
| `PAYLOAD` | Type-specific. Length = PHY payload length − 12. **There is no length field**: the LoRa explicit header carries the PHY length, and the PHY CRC protects it |
| `MIC` | 4-byte message integrity code (§6.2) |

**Maximum payload per spreading factor** (400 ms dwell, 12-byte overhead):

| SF | Max PHY payload | Max frame payload |
|---|---|---|
| 7 | 255 B | 243 B |
| 8 | 138 B | 126 B |
| 9 | 66 B | **54 B** |
| 10 | 24 B | 12 B (not used in v1) |

## 6. Security layer

Message authentication and replay protection are in the wire format from v1. Full key management (provisioning tooling, key rotation, readout-protection procedures) is a later add-on and is not part of this spec.

### 6.1 Keys

| Key | Held by | Derived as | Protects |
|---|---|---|---|
| `SiteKey` | Master and every Slave, provisioned over the service console. Never on a device. Never sent over the air | Random 128-bit, generated at commissioning | Root for everything below |
| `DevKey` | One device + its Slave (+ Master) | `AES-CMAC(SiteKey, 0x44 ‖ UID[12] ‖ 0x00 × 3)` (one 16-byte block) | Device joins |
| `GwKey(n)` | Slave n + Master | `AES-CMAC(SiteKey, 0x47 ‖ n ‖ 0x00 × 14)` (one 16-byte block) | Slave joins to the Master |
| `NwkSKey`, `AppSKey` | Session pair per device and per slave | `AES-128-ECB(DevKey or GwKey, k ‖ JoinNonce[4] ‖ DevNonce[2] ‖ NetID ‖ 0x00 × 8)`, k = `0x01` for NwkSKey, `0x02` for AppSKey; nonces little-endian | MIC and encryption of unicast frames |
| `CellKey(n)` | Slave n and all its joined devices | Random per slave, persisted; given to each device inside its encrypted `JOIN_ACC` | Cell broadcasts (beacon, group commands) |
| `NetKey` | Master and all joined slaves | Random, persisted; given to each slave in its `JOIN_ACC` | Tier-1 broadcasts |

Per-device keys are derived, not stored in a table, so a Slave needs only `SiteKey`. A stolen device reveals only its own `DevKey`. ⚠ A stolen *gateway* reveals `SiteKey`; gateways sit in locked cabinets with STM32 readout protection level 1. Per-device stored keys are the hardening path.

### 6.2 MIC

```
B0   = 0x49 ‖ DIR ‖ NETID ‖ SRC[2, LE] ‖ DST[2, LE] ‖ FCNT32[4, LE] ‖ 0x00 0x00 0x00 0x00 ‖ LEN
       (16 bytes; LEN = header length + payload length, i.e. 8 + N)
MIC  = AES-CMAC(NwkSKey | CellKey | NetKey, B0 ‖ HEADER[8] ‖ ENCRYPTED_PAYLOAD[N]) [0..3]
```

- Unicast frames use the sender/receiver pair's `NwkSKey`. Cell broadcasts use `CellKey`. Tier-1 broadcasts use `NetKey`. `JOIN_REQ` / `JOIN_ACC` use `DevKey` or `GwKey`.
- **The MIC is checked before decryption and before any parsing.** A frame that fails is dropped silently. The receiver counts it in a diagnostic counter but sends no error reply.
- The MIC comparison is constant-time.

### 6.3 Frame counter and replay

- Each sender keeps a 32-bit `FCNT32` per session, starting at 0 after each join and incremented for every frame it sends (retransmissions included). Only the low 16 bits are sent.
- **One exception: P0 copies.** A P0 frame sent on both radios, and its repeat 1 s later, are byte-identical copies with the **same** `FCNT32`, so receivers deduplicate them (below). Any other retransmission takes a new counter.
- The receiver rebuilds `FCNT32` in two steps. First, if the low 16 bits match one of the last 32 accepted-or-skipped counters (the duplicate window below), it is that counter. Otherwise it is the smallest value greater than the last accepted one whose low 16 bits match; a jump of more than 16 384 is treated as a replay and dropped.
- The rebuilt `FCNT32` is used to check the MIC. The window is only updated **after** the MIC has verified, so a forged frame can't move it.
- **Duplicate window:** the receiver keeps the last accepted `FCNT32` per sender plus a 32-entry bitmap. A frame whose counter is already marked is a duplicate. It is acknowledged if it asked for an ACK, but **never executed twice**. This is also how the same P0 frame received on two radios is deduplicated.
- Counters survive reboots. A gateway writes a high-water mark to FRAM every 64 frames, and a device writes one to flash every 256 frames. After a reboot the sender jumps forward by that step.
- A sender that reaches `FCNT32 = 0xFFFF0000` MUST rejoin for new session keys.

### 6.4 Encryption

`PAYLOAD` is encrypted with AES-128-CTR using `AppSKey` for unicast, `CellKey` / `NetKey` for broadcast, and `DevKey` / `GwKey` for `JOIN_ACC` only.

**Not encrypted (MIC only):** `JOIN_REQ`, `BEACON` on both tiers, and the tier-1 `HEARTBEAT`. Beacons carry only timing and versions, and a node that hasn't joined yet must be able to read them to find its slot timing. Their MIC still stops forgery and replay.

```
A_i = 0x01 ‖ DIR ‖ NETID ‖ SRC[2] ‖ DST[2] ‖ FCNT32[4] ‖ 0x00 0x00 0x00 0x00 ‖ i      (i = 1, 2, …)
keystream block i = AES-128-ECB(key, A_i)
```

## 7. Message type registry

All message types on both tiers, in one number space. Payloads are defined in [02](02-tier1-protocol.md) (tier 1) and [03](03-tier2-device-protocol.md) (tier 2).

| TYPE | Name | Tier | Direction | Purpose |
|---|---|---|---|---|
| `0x01` | `BEACON` | 1, 2 | down | Time, cycle number, configuration versions, ACK bitmaps |
| `0x02` | `REPORT` | 2 | up | A device's scheduled status report |
| `0x03` | `EVENT` | 1, 2 | up | Alarm or event, outside the schedule. Always `ACKREQ` |
| `0x04` | `CMD` | 1, 2 | down | A command, unicast or broadcast, with `execute_at` |
| `0x05` | `CMD_ACK` | 1, 2 | up | Command result, carrying the resulting state |
| `0x06` | `ACK` | 1, 2 | both | Plain acknowledgement of a frame (echoes its `FCNT32`) |
| `0x07` | `JOIN_REQ` | 1, 2 | up | Join request (contention window) |
| `0x08` | `JOIN_ACC` | 1, 2 | down | Join accept: address, slot, channel, keys |
| `0x09` | `REJOIN_REQ` | 2 | up | Rejoin by a device that already holds a slot, sent in its own slot |
| `0x0A` | `FRAG` | 1, 2 | both | One fragment of a larger transfer |
| `0x0B` | `FRAG_STATUS` | 1, 2 | both | Missing-fragment bitmap |
| `0x10` | `SUMMARY` | 1 | up | Section summary, every cycle |
| `0x11` | `DETAIL` | 1 | up | Batch of per-device detail records |
| `0x12` | `HEARTBEAT` | 1 | both | Standby-radio heartbeat |
| `0x13` | `WHITELIST` | 1 | down | Device authorisation entries for a section |
| `0x14`–`0x7F` | — | | | Reserved for this protocol |
| `0x80`–`0xFF` | — | | | Reserved for vendor/diagnostic use; never sent in production |

## 8. Versioning of these specs

- Spec versions are `MAJOR.MINOR`. `0.x` = draft. `1.0` = frozen at M1.
- After 1.0, a change is a **change request** (a GitHub issue labelled `change-request`) with its effort impact. It goes through review and sign-off again.
- The wire protocol has its own `VER` field (§5). A change that breaks existing devices increments `VER`.

## Open items

| # | Item | Needed by |
|---|---|---|
| O-00-1 | Confirm the STM32 96-bit UID is unique and readable on the device developer's actual (possibly clone) F103 boards | M1 sign-off |
| O-00-2 | Confirm the sync word `0x12` is acceptable, or choose a site-specific one | M1 sign-off |
| O-00-3 | NTC confirmation of EIRP, dwell and duty cycle (SOW assumption A3) | End of week 3 |
