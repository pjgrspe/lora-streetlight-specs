# 01 — Modbus Register Map

| | |
|---|---|
| **Spec** | 01 — Modbus register map (Server ↔ Master) |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-20 |
| **Owner** | pgorospe |
| **Reviewers** | Client |
| **Status** | Draft. Not frozen |

The contract between the Local Monitoring Server and the Master Gateway over RS485 / Modbus RTU. The Master is the Modbus server (slave); the Server is the only Modbus client (master). Shared conventions are in [00](00-common-frame-and-conventions.md).

**The machine-readable source is [`register-map/register-map.csv`](../register-map/register-map.csv).** The tables in this document show the same content. The firmware header and the Server's poller configuration are generated from the CSV, never written by hand. If this document and the CSV disagree, the CSV wins and the difference is a bug.

## 1. Design rules

- **Flat, sparse, fixed stride.** Every address is computable by hand. Nothing moves when a section or device is added. Unused space is reserved, not packed.
- **The register image is a cache.** Every read is answered from the Master's cache in RAM. A read never waits for a radio exchange.
- **Every value carries its age.** Device, meter and section blocks hold an age in seconds and a communication state. Old data is never presented as fresh.
- **Writes are jobs.** Commands go through an atomic mailbox and are tracked as jobs. Configuration is applied by one commit.
- **Fixed-stride reads never fail** because a section or device isn't configured. Unconfigured blocks read as zeros (§5.4).

## 2. Serial link

| Setting | Value |
|---|---|
| Physical | RS485, 2-wire, isolated at the Master ([06](06-gateway-hardware-requirements.md)) |
| Mode | Modbus RTU |
| Default | **19200 baud, 8 data bits, even parity, 1 stop bit (8E1)** |
| Selectable | 9600, 19200, 38400, 57600, 115200 baud; even, odd, or no parity with 2 stop bits (holding `0x0001`, `0x0002`) |
| Unit ID | **1** by default, configurable 1–247 |
| Broadcast (unit ID 0) | Not supported. The Master ignores frames to unit 0 and doesn't reply |
| Inter-frame silence (t3.5) | 3.5 character times at ≤19200 baud (2.005 ms at 19200 8E1). **Fixed 1.750 ms above 19200** |
| Inter-character limit (t1.5) | 1.5 character times at ≤19200 baud (0.859 ms at 19200 8E1). **Fixed 0.750 ms above 19200** |
| Master response time | The Master MUST start its response within **50 ms** of the end of a valid request |
| Server response timeout | The Server SHOULD wait at least **1 s** before treating a request as unanswered, then retry once |

Changes to unit ID, baud rate or parity take effect only after the Master reboots (§8.1).

## 3. Function codes and exceptions

| FC | Name | Use | Limit |
|---|---|---|---|
| `0x03` | Read Holding Registers | Configuration, mailbox readback, job table, fail masks, FC03 mirror of the input space | 125 registers |
| `0x04` | Read Input Registers | All telemetry and status | 125 registers |
| `0x06` | Write Single Register | Configuration registers, `mask_select_seq`, `event_ack_seq`. **Not** the mailbox command block | 1 register |
| `0x10` | Write Multiple Registers | Configuration registers, and the mailbox command block (one request, §8.2) | 123 registers |

Any other function code returns exception `0x01`.

| Exception | When the Master returns it |
|---|---|
| `0x01` Illegal Function | Function code not in the table above |
| `0x02` Illegal Data Address | Any part of the request lies outside the valid areas (§4); a write to a read-only register; a write to a reserved register |
| `0x03` Illegal Data Value | Quantity out of range (0, or above 125 / 123); a commit or trigger register written with a value other than `0xA5C3`; a write touching the mailbox command block that isn't exactly one FC16 covering `0x0100`–`0x0116`; an `event_ack_seq` outside the pending range |
| `0x04` Server Device Failure | Internal fault, e.g. the configuration store can't be written |
| `0x06` Server Device Busy | The job queue is full (8 jobs not yet finished), or a configuration commit is still being applied. Nothing was accepted; retry later |
| `0x0B` Gateway Target Device Failed to Respond | Only when `stale_policy` = 2 (§9): a read touching the block of a stale or offline device or meter |

**Unconfigured sections and devices are not an exception.** Their blocks read as zeros (§5.4). Exception `0x0A` is not used in v1.

## 4. Address plan

All addresses in this spec are **0-based Modbus protocol addresses in hex**, as they appear on the wire. The `3xxxx` / `4xxxx` notation is not used. Section index `s` = GwID, 1–14. Device index `n` = NodeID, 0–63 (0 is the gateway position and is always empty).

### 4.1 Input registers (FC04)

| Area | Address | Size | Content |
|---|---|---|---|
| System | `0x0000`–`0x00FF` | 256 | Master identity, clock, counts, faults, tier-1 radios, Modbus counters (§6.1) |
| Sections | `0x0100` + s × 16 | 16 per section | Slave state and section aggregates (§6.5) |
| Meters | `0x0200` + s × 32 | 32 per section | Section energy meter (§6.6) |
| Summary | `0x0400` + s × 64 + n | 1 per device | Packed status + level, for fast polling (§6.7) |
| Events | `0x0800`–`0x090F` | 4 + 32 × 8 | Event window (§7) |
| Devices | `0x1000` + s × 0x400 + n × 16 | 16 per device | Full device block (§6.8) |
| Diagnostics | `0x7000` + s × 16 | 16 per section | Tier-1 link statistics per slave (§6.9) |

Valid FC04 ranges: `0x0000`–`0x07FF`, `0x0800`–`0x090F`, `0x1400`–`0x4BFF`, `0x7000`–`0x70FF`. Positions inside these ranges with no field defined (including every s = 0 and n = 0 position) are **reserved and read 0**.

### 4.2 Holding registers (FC03 / FC06 / FC16)

| Area | Address | Content |
|---|---|---|
| Configuration | `0x0000`–`0x00FF` | Gateway and site configuration, commit and status (§8.1) |
| Command mailbox | `0x0100`–`0x013F` | Command block and current-job readback (§8.2) |
| Fail masks | `0x0140` + s × 4 | 64-bit fail mask per section for the selected job (§8.6) |
| Job table | `0x0180`–`0x01BF` | The last 8 jobs (§8.6) |
| Event acknowledge | `0x0200` | `event_ack_seq` (§7) |
| FC03 mirror | `0x8000` + a | Read-only copy of input address a (§8.7) |

### 4.3 Worked examples

| What | Address |
|---|---|
| Section 3 state | `0x0100 + 3×16` = `0x0130` |
| Section 3 meter total power (2 registers) | `0x0200 + 3×32 + 14` = `0x026E`–`0x026F` |
| Summary of device `0x311` (section 3, NodeID 17) | `0x0400 + 3×64 + 17` = `0x04D1` |
| Block of device `0x311` | `0x1000 + 3×0x400 + 17×16` = `0x1D10`–`0x1D1F` |
| Energy of device `0x311` | `0x1D17`–`0x1D18` |

## 5. Data conventions

### 5.1 Types

| Type | Registers | Meaning |
|---|---|---|
| `u16` / `i16` | 1 | Unsigned / two's-complement signed 16-bit |
| `u32` / `i32` | 2 | 32-bit, **high word first** (lower address = high word) |
| `enum16` | 1 | Enumerated value, listed in the description |
| `bits16` / `bits32` | 1 / 2 | Bit field; bit 0 = least significant bit |

Physical value = raw × scale, in the unit given. Byte-packed registers put the first-named byte in the **high byte**.

### 5.2 Not available

A value the source can't provide reads as all ones for its width: `0xFFFF` (u16), `0x7FFF` (i16), `0xFFFFFFFF` (u32), `0x7FFFFFFF` (i32). Levels use 255 for "unknown". Age registers saturate at `0xFFFE`; `0xFFFF` means "never received".

### 5.3 Consistency

- Each response is a **consistent snapshot** of the range it covers. The cache is never updated part-way through one response.
- The Master does not guarantee consistency across two requests. **The Server MUST NOT split a 32-bit pair across two requests**, and SHOULD read device blocks in whole blocks (§10).

### 5.4 Unconfigured sections and devices

- A section not set in `cfg_section_mask` reads `sec_section_state` = 0 and zeros elsewhere in its section, meter, summary and diagnostics positions.
- A device position (NodeID) with no authorised device reads **all zeros, except the two age registers, which read `0xFFFF`**. Its summary register reads 0 (comm state 0 = not configured).
- The Server MUST check the state field before using any value.

## 6. Input registers

### 6.1 System block (`0x0000`–`0x00FF`)

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `0x0000` | `map_version_major` | u16 | 1 |  | R | Register map major version. Changes when anything moves or changes meaning |
| `0x0001` | `map_version_minor` | u16 | 1 |  | R | Register map minor version. Changes when fields are added in reserved space |
| `0x0002` | `protocol_ver` | u16 | 1 |  | R | LoRa protocol VER implemented (00 section 5). v1 = 1 |
| `0x0003` | `fw_version` | u16 | 1 |  | R | Master firmware version: high byte major, low byte minor |
| `0x0004` | `fw_build` | u16 | 1 |  | R | Master firmware build number |
| `0x0005` | `gateway_role` | enum16 | 1 |  | R | 0 = master. Other values reserved |
| `0x0006–0x0007` | `boot_count` | u32 | 1 |  | R | Number of boots since manufacture |
| `0x0008–0x0009` | `uptime_s` | u32 | 1 | s | R | Seconds since boot |
| `0x000A–0x000B` | `utc` | u32 | 1 | s | R | Master clock, Unix time UTC |
| `0x000C` | `tz_offset_min` | i16 | 1 | min | R | Active local-time offset from UTC |
| `0x000D` | `clock_state` | enum16 | 1 |  | R | 0 = untrusted (lights-ON rule applies), 1 = holdover on RTC (not set by server for > 24 h), 2 = trusted (set by server within 24 h) |
| `0x000E` | `reset_cause` | enum16 | 1 |  | R | Cause of last reset: 0 power-on, 1 brown-out, 2 watchdog, 3 software (REBOOT or update), 4 pin reset, 5 fault handler, 0xFFFF unknown |
| `0x000F` | `heartbeat` | u16 | 1 |  | R | Increments by 1 every second, wraps at 65535. A value that stops changing means a frozen gateway |
| `0x0010` | `telemetry_epoch` | u16 | 1 |  | R | Increments (wrapping) whenever any telemetry value in the section, meter, summary or device areas changes. Age counters do not bump it |
| `0x0011` | `section_mask` | bits16 | 1 |  | R | Active section mask: bit s set = section s configured (bits 1-14). Bit 0 and 15 always 0 |
| `0x0012` | `devices_configured` | u16 | 1 |  | R | Devices authorised across all sections (LED devices + meters) |
| `0x0013` | `devices_online` | u16 | 1 |  | R | Devices whose summary state is online |
| `0x0014` | `devices_faulted` | u16 | 1 |  | R | Devices with driver_fault, lamp_fault or DALI not OK |
| `0x0015` | `lamps_on` | u16 | 1 |  | R | Devices with lamp_on set |
| `0x0016` | `fault_bitmap` | bits32 | 1 |  | R | Master fault bits, see spec 01 section 6.2 |
| `0x0018` | `net_id` | u16 | 1 |  | R | Active NetID (1-254) |
| `0x0019` | `cycle_s` | u16 | 1 | s | R | Active cycle length |
| `0x001A` | `cycle_seq` | u16 | 1 |  | R | Tier-1 cycle sequence number (wraps) |
| `0x001B` | `airtime_used_ds` | u16 | 0.1 | s | R | Master transmit time used in the last rolling hour, all radios |
| `0x001C` | `airtime_used_pct` | u16 | 0.1 | % | R | Master airtime used as a share of the 36 s hourly budget |
| `0x001D` | `cpu_temp_c` | i16 | 1 | degC | R | MCU die temperature |
| `0x001E` | `vdd_mv` | u16 | 1 | mV | R | MCU supply voltage |
| `0x001F` | `store_forward_depth` | u16 | 1 |  | R | Events held unacknowledged in the master buffer (RAM + NOR) |
| `0x0020` | `tier1_active_radio` | enum16 | 1 |  | R | Radio carrying scheduled tier-1 traffic: 0 = A (primary), 1 = B (standby) |
| `0x0021` | `tier1_failover_count` | u16 | 1 |  | R | Number of failovers since boot |
| `0x0022` | `tier1_failover_state` | enum16 | 1 |  | R | 0 normal on primary, 1 failed over to standby, 2 failback hold-off (primary recovering), 3 forced by FORCE_FAILOVER |
| `0x0023–0x0024` | `tier1_last_failover_utc` | u32 | 1 | s | R | Time of last failover or failback, 0 = never |
| `0x0025` | `jobs_queued` | u16 | 1 |  | R | Command jobs waiting in the master queue (max 8) |
| `0x0026` | `jobs_settling` | u16 | 1 |  | R | Dispatched jobs still collecting confirmations |
| `0x0030` | `radio_a_health` | enum16 | 1 |  | R | radio A (tier-1 primary): 0 OK, 1 degraded (PER above threshold), 2 failed, 3 not fitted |
| `0x0031` | `radio_a_channel` | u16 | 1 |  | R | radio A (tier-1 primary): Configured channel number (spec 04 section 2) |
| `0x0032` | `radio_a_sf` | u16 | 1 |  | R | radio A (tier-1 primary): Spreading factor in use (7-9) |
| `0x0033` | `radio_a_tx_power_dbm` | i16 | 1 | dBm | R | radio A (tier-1 primary): Configured conducted TX power |
| `0x0034–0x0035` | `radio_a_tx_ok` | u32 | 1 |  | R | radio A (tier-1 primary): Frames transmitted (TxDone) |
| `0x0036–0x0037` | `radio_a_tx_fail` | u32 | 1 |  | R | radio A (tier-1 primary): Transmissions that failed (timeout, SPI error, refused by airtime ledger) |
| `0x0038–0x0039` | `radio_a_rx_ok` | u32 | 1 |  | R | radio A (tier-1 primary): Frames received with valid PHY CRC |
| `0x003A–0x003B` | `radio_a_rx_crc_err` | u32 | 1 |  | R | radio A (tier-1 primary): Frames received with PHY CRC error |
| `0x003C` | `radio_a_rx_mic_fail` | u16 | 1 |  | R | radio A (tier-1 primary): Frames dropped for MIC or replay failure (wraps) |
| `0x003D` | `radio_a_last_rssi_dbm` | i16 | 1 | dBm | R | radio A (tier-1 primary): RSSI of last valid frame |
| `0x003E` | `radio_a_last_snr_qdb` | i16 | 0.25 | dB | R | radio A (tier-1 primary): SNR of last valid frame |
| `0x003F` | `radio_a_noise_floor_dbm` | i16 | 1 | dBm | R | radio A (tier-1 primary): Noise floor sampled in idle time |
| `0x0040` | `radio_b_health` | enum16 | 1 |  | R | radio B (tier-1 standby): 0 OK, 1 degraded (PER above threshold), 2 failed, 3 not fitted |
| `0x0041` | `radio_b_channel` | u16 | 1 |  | R | radio B (tier-1 standby): Configured channel number (spec 04 section 2) |
| `0x0042` | `radio_b_sf` | u16 | 1 |  | R | radio B (tier-1 standby): Spreading factor in use (7-9) |
| `0x0043` | `radio_b_tx_power_dbm` | i16 | 1 | dBm | R | radio B (tier-1 standby): Configured conducted TX power |
| `0x0044–0x0045` | `radio_b_tx_ok` | u32 | 1 |  | R | radio B (tier-1 standby): Frames transmitted (TxDone) |
| `0x0046–0x0047` | `radio_b_tx_fail` | u32 | 1 |  | R | radio B (tier-1 standby): Transmissions that failed (timeout, SPI error, refused by airtime ledger) |
| `0x0048–0x0049` | `radio_b_rx_ok` | u32 | 1 |  | R | radio B (tier-1 standby): Frames received with valid PHY CRC |
| `0x004A–0x004B` | `radio_b_rx_crc_err` | u32 | 1 |  | R | radio B (tier-1 standby): Frames received with PHY CRC error |
| `0x004C` | `radio_b_rx_mic_fail` | u16 | 1 |  | R | radio B (tier-1 standby): Frames dropped for MIC or replay failure (wraps) |
| `0x004D` | `radio_b_last_rssi_dbm` | i16 | 1 | dBm | R | radio B (tier-1 standby): RSSI of last valid frame |
| `0x004E` | `radio_b_last_snr_qdb` | i16 | 0.25 | dB | R | radio B (tier-1 standby): SNR of last valid frame |
| `0x004F` | `radio_b_noise_floor_dbm` | i16 | 1 | dBm | R | radio B (tier-1 standby): Noise floor sampled in idle time |
| `0x0050–0x0051` | `mb_rx_frames` | u32 | 1 |  | R | Modbus requests received addressed to this unit |
| `0x0052` | `mb_crc_errors` | u16 | 1 |  | R | Modbus frames dropped for CRC error (wraps) |
| `0x0053` | `mb_exceptions` | u16 | 1 |  | R | Exception responses sent (wraps) |
| `0x0054` | `mb_last_exception` | u16 | 1 |  | R | Code of the last exception sent (0 = none) |
| `0x0055` | `mb_last_poll_age_s` | u16 | 1 | s | R | Seconds since the previous valid request before this one |

Registers `0x0027`–`0x002F`, `0x0056`–`0x00FF` are reserved.

### 6.2 Master fault bits (`fault_bitmap`, `0x0016`–`0x0017`)

| Bit | Meaning |
|---|---|
| 0 | Clock untrusted (lights-ON rule in force at every node that depends on it) |
| 1 | Tier-1 radio A (primary) failed |
| 2 | Tier-1 radio B (standby) failed |
| 3 | Configuration store CRC error at boot (defaults or last good copy in use) |
| 4 | FRAM fault |
| 5 | NOR flash fault |
| 6 | Airtime reserve reached: P1–P3 traffic is being deferred |
| 7 | Event buffer overflow (events lost) |
| 8 | Last reset was a watchdog reset |
| 9 | At least one section DEGRADED |
| 10 | At least one section AUTONOMOUS or LOST |
| 11 | RTC backup invalid (time was lost at the last power cycle) |
| 12 | Last server time proposal rejected (jump too large without `force`) |
| 13 | Configuration written but not committed |
| 14–31 | Reserved (0) |

### 6.3 Tier-1 radio counters

Radio A (`0x0030`–`0x003F`) and radio B (`0x0040`–`0x004F`) have identical layouts; both are listed in §6.1. Counters are 32-bit and wrap; `rx_mic_fail` is 16-bit and wraps. Counters reset at boot.

### 6.4 Device status bits

Used in `dev_status`, `met_status` and on the radio ([03](03-tier2-device-protocol.md)).

| Bit | Name | Meaning |
|---|---|---|
| 0 | `lamp_on` | Output level > 0 |
| 1 | `dali_ok` | DALI bus and driver responding |
| 2 | `driver_fault` | Driver reports a fault |
| 3 | `lamp_fault` | Lamp failure |
| 4 | `clock_trusted` | Device clock is set and trusted |
| 5 | `fallback_mode` | Device lost its slave and is running its own schedule |
| 6 | `override_active` | A manual override is in force |
| 7 | `commanded_off` | Off by command or schedule (never set for loss of power) |
| 8 | `d4i_available` | Driver supports D4i data |
| 9 | `config_mismatch` | Device configuration differs from what the gateway holds |
| 10 | `restarted` | First report after a device boot |
| 11–15 | — | Reserved (0) |

### 6.5 Section blocks (`0x0100` + s × 16)

Source: the slave's SUMMARY frame each cycle ([02](02-tier1-protocol.md)), plus the Master's own link view.

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0` | `sec_section_state` | enum16 | 1 |  | R | Master view of the section: 0 not configured, 1 SYNCED, 2 DEGRADED, 3 AUTONOMOUS, 4 CLOCK_UNTRUSTED, 5 REJOINING, 6 LOST (no SUMMARY for 3 cycles) |
| `+1` | `sec_age_s` | u16 | 1 | s | R | Seconds since the last SUMMARY from this slave. 0xFFFF = never |
| `+2` | `sec_section_flags` | bits16 | 1 |  | R | bit0 single-channel mode, bit1 up radio A OK, bit2 up radio B OK, bit3 down radio A OK, bit4 down radio B OK, bit5 slave using standby uplink, bit6 commissioning window open, bit7 config mismatch with master |
| `+3` | `sec_devices_configured` | u16 | 1 |  | R | Devices authorised in this section |
| `+4` | `sec_devices_online` | u16 | 1 |  | R | Devices reporting normally |
| `+5` | `sec_lamps_on` | u16 | 1 |  | R | Devices with lamp_on set |
| `+6` | `sec_faults` | u16 | 1 |  | R | Devices with any fault bit set |
| `+7–+8` | `sec_power_w` | u32 | 1 | W | R | Aggregate section power (meter if present, else sum of devices) |
| `+9–+10` | `sec_energy_wh` | u32 | 1 | Wh | R | Section energy, cumulative (meter if present, else sum of devices) |
| `+11` | `sec_config_hash` | u16 | 1 |  | R | Hash of the slave's active configuration |
| `+12` | `sec_clock_offset_ms` | i16 | 1 | ms | R | Slave clock minus master clock at the last SUMMARY |
| `+13` | `sec_airtime_used_pct` | u16 | 1 | % | R | Slave airtime used in the last hour as a share of its budget |
| `+14` | `sec_slotmap_ver` | u16 | 1 |  | R | Slave slot-map version (low byte significant) |
| `+15` | `sec_last_rssi_dbm` | i16 | 1 | dBm | R | RSSI at the master of the last frame from this slave |

### 6.6 Meter blocks (`0x0200` + s × 32)

Source: the meter record sent by the slave every 5 min ([02](02-tier1-protocol.md)). Offsets +25 to +31 are reserved.

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0` | `met_state` | enum16 | 1 |  | R | 0 no meter configured, 1 online, 2 stale, 3 offline |
| `+1` | `met_age_s` | u16 | 1 | s | R | Seconds since the meter data was measured. 0xFFFF = never |
| `+2` | `met_address` | u16 | 1 |  | R | 12-bit protocol address of the meter (spec 00 section 3) |
| `+3` | `met_status` | bits16 | 1 |  | R | Device status bits (spec 01 section 6.4) |
| `+4` | `met_v_l1` | u16 | 0.1 | V | R | Voltage L1-N (L1-L2 on delta) |
| `+5` | `met_v_l2` | u16 | 0.1 | V | R | Voltage L2-N (L2-L3 on delta) |
| `+6` | `met_v_l3` | u16 | 0.1 | V | R | Voltage L3-N (L3-L1 on delta) |
| `+7` | `met_i_l1` | u16 | 0.01 | A | R | Current L1 |
| `+8` | `met_i_l2` | u16 | 0.01 | A | R | Current L2 |
| `+9` | `met_i_l3` | u16 | 0.01 | A | R | Current L3 |
| `+10` | `met_i_n` | u16 | 0.01 | A | R | Neutral current |
| `+11` | `met_p_l1` | i16 | 1 | W | R | Active power L1 |
| `+12` | `met_p_l2` | i16 | 1 | W | R | Active power L2 |
| `+13` | `met_p_l3` | i16 | 1 | W | R | Active power L3 |
| `+14–+15` | `met_p_total` | i32 | 1 | W | R | Total active power |
| `+16` | `met_pf_total` | i16 | 0.001 |  | R | Total power factor |
| `+17` | `met_freq` | u16 | 0.01 | Hz | R | Frequency |
| `+18–+19` | `met_e_import` | u32 | 1 | Wh | R | Active energy import, cumulative |
| `+20–+21` | `met_e_export` | u32 | 1 | Wh | R | Active energy export, cumulative |
| `+22` | `met_thd_i` | u16 | 0.1 | % | R | Current THD (average of phases) |
| `+23` | `met_meter_flags` | bits16 | 1 |  | R | bit0 wye (1) / delta (0), bit1 CT-connected, bit2 phase loss L1, bit3 phase loss L2, bit4 phase loss L3 |
| `+24` | `met_fault_code` | u16 | 1 |  | R | Meter fault code (spec 03), 0 = none |

### 6.7 Summary registers (`0x0400` + s × 64 + n)

One register per device position, so a whole section's state is one 64-register read.

| Bits | Field |
|---|---|
| 0–7 | `level_actual` (DALI arc 0–254, 255 unknown) |
| 8–9 | Comm state: 0 not configured, 1 online, 2 stale, 3 offline (§9) |
| 10 | `lamp_on` |
| 11 | Fault: `driver_fault` or `lamp_fault` set, or `dali_ok` clear |
| 12 | `fallback_mode` |
| 13 | `override_active` |
| 14 | `commanded_off` |
| 15 | `config_mismatch` |

The meter's summary register carries its comm state in bits 8–9, bit 11 for a meter fault, and level 255.

### 6.8 Device blocks (`0x1000` + s × 0x400 + n × 16)

Source: the slave's DETAIL records ([02](02-tier1-protocol.md)) and status changes reported in each SUMMARY. Status fields (+0, +2, +3) are refreshed every cycle for changed devices and confirmed every cycle for unchanged online devices (`age_status_s`). Power, energy and electrical fields are refreshed at the detail interval (default 15 min, `age_detail_s`). Extended fields (+5, +6, +10/+11, +13, +14) are refreshed hourly. `level_commanded` comes from the extended record and is also set by the Master when it dispatches a level command.

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0` | `dev_status` | bits16 | 1 |  | R | Device status bits (spec 01 section 6.4) |
| `+1` | `dev_age_status_s` | u16 | 1 | s | R | Seconds since the master last confirmed this device's status. 0xFFFF = never |
| `+2` | `dev_level_actual` | u16 | 1 |  | R | Output level reported by the device: DALI arc 0-254, 255 unknown |
| `+3` | `dev_level_commanded` | u16 | 1 |  | R | Level the device is trying to hold (schedule or override): DALI arc 0-254, 255 unknown |
| `+4` | `dev_power_dw` | u16 | 0.1 | W | R | Device input power |
| `+5` | `dev_voltage_dv` | u16 | 0.1 | V | R | Supply voltage at the device |
| `+6` | `dev_current_ma` | u16 | 1 | mA | R | Supply current |
| `+7–+8` | `dev_energy_wh` | u32 | 1 | Wh | R | Device energy, cumulative |
| `+9` | `dev_temp_c` | i16 | 1 | degC | R | Device temperature |
| `+10–+11` | `dev_lamp_hours` | u32 | 1 | h | R | Lamp burning hours |
| `+12` | `dev_fault_code` | u16 | 1 |  | R | Device fault code (spec 03), 0 = none |
| `+13` | `dev_rssi_snr` | u16 | 1 |  | R | Link quality at the slave: high byte RSSI (int8, dBm), low byte SNR (int8, 0.25 dB) |
| `+14` | `dev_slot_channel` | u16 | 1 |  | R | High byte slot position 0-63 (0xFF none), low byte radio channel number in use (spec 04) |
| `+15` | `dev_age_detail_s` | u16 | 1 | s | R | Seconds since the power, energy and extended fields were measured. 0xFFFF = never |

### 6.9 Diagnostics (`0x7000` + s × 16)

Offsets +12 to +15 are reserved.

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0–+1` | `diag_summary_rx` | u32 | 1 |  | R | SUMMARY frames received from this slave |
| `+2–+3` | `diag_summary_missed` | u32 | 1 |  | R | Tier-1 slots in which no SUMMARY arrived |
| `+4` | `diag_last_snr_qdb` | i16 | 0.25 | dB | R | SNR at the master of the last frame from this slave |
| `+5` | `diag_uplink_radio` | enum16 | 1 |  | R | Slave uplink radio in use: 0 A (primary), 1 B (standby) |
| `+6–+7` | `diag_detail_records_rx` | u32 | 1 |  | R | DETAIL records received from this slave |
| `+8` | `diag_cmd_frames_tx` | u16 | 1 |  | R | CMD frames sent to this slave (wraps) |
| `+9` | `diag_cmd_retries` | u16 | 1 |  | R | CMD retransmissions to this slave (wraps) |
| `+10` | `diag_events_rx` | u16 | 1 |  | R | EVENT frames received from this slave (wraps) |
| `+11` | `diag_slave_fw_version` | u16 | 1 |  | R | Slave firmware version (high byte major, low byte minor), 0 = unknown |

## 7. Events

The Master keeps every event (device alarms forwarded by slaves, slave events, and its own) in a store-and-forward buffer until the Server acknowledges it. The buffer MUST hold at least 1000 events and survive a Master reboot ([06](06-gateway-hardware-requirements.md), NOR flash). ⚠ The final capacity depends on the storage fitted.

### 7.1 Event window

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `0x0800` | `ev_oldest_seq` | u16 | 1 |  | R | Sequence number of the first event in the window (oldest unacknowledged) |
| `0x0801` | `ev_window_count` | u16 | 1 |  | R | Valid events in the window (0-32) |
| `0x0802` | `ev_pending_total` | u16 | 1 |  | R | Unacknowledged events held by the master, window included |
| `0x0803` | `ev_dropped` | u16 | 1 |  | R | Events lost to buffer overflow since boot (wraps) |

Event slot i (0–31) starts at `0x0810 + i × 8`. **Slot 0 is always the oldest unacknowledged event.**

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0` | `ev_seq` | u16 | 1 |  | R | Event sequence number (wraps; compare modulo 65536). Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+1–+2` | `ev_utc` | u32 | 1 | s | R | Time the event happened at its source. Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+3` | `ev_source` | u16 | 1 |  | R | 12-bit protocol address of the source (spec 00 section 3). Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+4` | `ev_code` | u16 | 1 |  | R | Event code. 0x0000-0x7FFF = codes carried from radio EVENT frames (specs 02 and 03), 0x8000-0xFFFF = generated by the master (spec 01 section 7.3). Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+5` | `ev_arg1` | u16 | 1 |  | R | First event argument (code-specific). Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+6` | `ev_arg2` | u16 | 1 |  | R | Second event argument (code-specific). Event slot i (0-31) is at 0x0810 + i*8; slot 0 is the oldest |
| `+7` | `ev_severity` | enum16 | 1 |  | R | 0 info, 1 warning, 2 alarm, 3 critical. Event slot i (0-31) is at 0x0810 + i*8 |

### 7.2 Reading and acknowledging

1. Read `0x0800`–`0x0803`. If `ev_window_count` = 0, stop.
2. Read `ev_window_count × 8` registers from `0x0810` (at most 15 events per request, in whole events).
3. Store the events durably.
4. Write `event_ack_seq` (holding `0x0200`, FC06) = the `seq` of the last event stored. The Master discards that event and every older one, and refills the window.

Sequence numbers wrap at 65536 and are compared modulo 2¹⁶. Writing a value outside the pending range returns exception `0x03`. Events are never removed without an acknowledgement. If the buffer is full, the oldest events are dropped, `ev_dropped` is incremented and event `0x800D` is raised.

### 7.3 Event codes

Codes `0x0000`–`0x7FFF` are carried unchanged from radio EVENT frames; slaves and devices define them in [02](02-tier1-protocol.md) and [03](03-tier2-device-protocol.md). Codes `0x8000`–`0xFFFF` are generated by the Master:

| Code | Name | Source | arg1 | arg2 | Severity |
|---|---|---|---|---|---|
| `0x8001` | `SECTION_LOST` | Slave | — | — | 3 |
| `0x8002` | `SECTION_RECOVERED` | Slave | Minutes lost | — | 0 |
| `0x8003` | `TIER1_FAILOVER` | Master | Radio now active (1 = B) | Cause: 1 missed exchanges, 2 PER, 3 forced | 2 |
| `0x8004` | `TIER1_FAILBACK` | Master | Radio now active (0 = A) | — | 0 |
| `0x8005` | `DEVICE_OFFLINE` | Device | — | — | 2 |
| `0x8006` | `DEVICE_ONLINE` | Device | — | — | 0 |
| `0x8007` | `CLOCK_UNTRUSTED` | Master | — | — | 3 |
| `0x8008` | `SERVER_TIME_REJECTED` | Master | Proposed − current, minutes (i16) | — | 1 |
| `0x8009` | `CONFIG_COMMITTED` | Master | New `cfg_version` | — | 0 |
| `0x800A` | `SECTION_CONFIG_DIVERGED` | Slave | Slave `config_hash` | Master expected hash | 1 |
| `0x800B` | `MASTER_BOOT` | Master | `reset_cause` | — | 1 |
| `0x800C` | `AIRTIME_RESERVE_REACHED` | Master | Used, % of budget | — | 1 |
| `0x800D` | `EVENT_BUFFER_OVERFLOW` | Master | Events dropped | — | 2 |
| `0x800E` | `DEVICE_COMMISSIONED` | Device | NodeID | Device type | 0 |
| `0x800F` | `DEVICE_REPLACED` | Device | NodeID | — | 0 |
| `0x8010` | `JOB_FINISHED` | Master | cmd_seq | Final job_state | 0 |
| `0x8011` | `STANDBY_RADIO_DOWN` | Master | Radio (1 = B) | Cause: 1 self-test, 2 no slave HEARTBEAT for 10 cycles | 2 |
| `0x8012` | `STANDBY_RADIO_RESTORED` | Master | Radio | — | 0 |
| `0x8013` | `SERVER_LOST` | Master | Minutes since the last valid Modbus request | — | 2 |
| `0x8014` | `SERVER_RESTORED` | Master | Minutes the server was away | — | 0 |
| `0x8015` | `RF_DEGRADED` | Master | Radio (0 = A, 1 = B) | Noise floor, dBm (i16) | 1 |
| `0x8016` | `RF_NORMAL` | Master | Radio | — | 0 |
| `0x8017` | `CONFIG_FAULT` | Master | 1 = second copy loaded, 2 = factory defaults loaded | Storage: 0 flash, 1 FRAM, 2 NOR | 3 |
| `0x8018` | `CLOCK_RESTORED` | Master | Correction applied, s (i16, saturating) | — | 0 |

**These codes are about the Master itself and the tier-1 link as the Master sees it.** A slave's own failover, standby, clock, airtime and RF events arrive as slave codes passed through from [02 §9](02-tier1-protocol.md) (`0x07`, `0x08`, `0x0B`, `0x0D`, `0x14`–`0x17`), so no event is reported twice. `SERVER_LOST` is raised after 30 min without a valid Modbus request ([05](05-fail-safe-behaviour.md)); the Server reads it, with `SERVER_RESTORED`, when it reconnects. Severity uses the same scale as everywhere: 0 info · 1 warning · 2 alarm · 3 critical.

## 8. Holding registers

### 8.1 Configuration (`0x0000`–`0x00FF`)

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `0x0000` | `cfg_unit_id` | u16 | 1 |  | RW | Modbus unit ID, 1-247. Default 1. Takes effect after reboot |
| `0x0001` | `cfg_baud_code` | enum16 | 1 |  | RW | 0 = 9600, 1 = 19200 (default), 2 = 38400, 3 = 57600, 4 = 115200. Takes effect after reboot |
| `0x0002` | `cfg_parity_code` | enum16 | 1 |  | RW | 0 = none with 2 stop bits, 1 = even (default, 8E1), 2 = odd. Takes effect after reboot |
| `0x0003` | `cfg_net_id` | u16 | 1 |  | RW | Site NetID, 1-254 |
| `0x0004–0x0005` | `cfg_latitude` | i32 | 0.00001 | deg | RW | Site latitude, positive north |
| `0x0006–0x0007` | `cfg_longitude` | i32 | 0.00001 | deg | RW | Site longitude, positive east |
| `0x0008` | `cfg_tz_offset_min` | i16 | 1 | min | RW | Local time offset from UTC. Default +480 |
| `0x0009` | `cfg_dusk_offset_min` | i16 | 1 | min | RW | Switch-on time relative to computed sunset (negative = earlier) |
| `0x000A` | `cfg_dawn_offset_min` | i16 | 1 | min | RW | Switch-off time relative to computed sunrise (positive = later) |
| `0x000B` | `cfg_cycle_s` | u16 | 1 | s | RW | Cycle length: 120 (default), 180 or 300. 60 only if NTC confirms a per-radio duty budget (spec 04) |
| `0x000C` | `cfg_section_mask` | bits16 | 1 |  | RW | Configured sections: bit s = section s (bits 1-14) |
| `0x000D` | `cfg_t1_primary_ch` | u16 | 1 |  | RW | Tier-1 primary channel number. Default 0 |
| `0x000E` | `cfg_t1_standby_ch` | u16 | 1 |  | RW | Tier-1 standby channel number. Default 13 |
| `0x000F` | `cfg_t1_sf` | u16 | 1 |  | RW | Tier-1 spreading factor, 7 (default) or 8 |
| `0x0010` | `cfg_radio_a_tx_dbm` | i16 | 1 | dBm | RW | Radio A conducted TX power. Must keep EIRP at or below 16 dBm |
| `0x0011` | `cfg_radio_b_tx_dbm` | i16 | 1 | dBm | RW | Radio B conducted TX power. Must keep EIRP at or below 16 dBm |
| `0x0012` | `cfg_cell_sf` | u16 | 1 |  | RW | Default cell spreading factor pushed to slaves, 7-9. Default 9 |
| `0x0013` | `cfg_stale_threshold_s` | u16 | 1 | s | RW | Age after which device data counts as stale. Default 360 |
| `0x0014` | `cfg_stale_policy` | enum16 | 1 |  | RW | 0 = return value plus age (default), 1 = return not-available sentinel for stale values, 2 = exception 0x0B on reads of a stale device block |
| `0x0015` | `cfg_fc03_mirror` | u16 | 1 |  | RW | 1 = input space mirrored at holding 0x8000 + address (default), 0 = off |
| `0x0016` | `cfg_detail_interval_min` | u16 | 1 | min | RW | Interval for full device detail on tier 1. Default 15 |
| `0x0017` | `cfg_power_on_level` | u16 | 1 |  | RW | DALI POWER ON LEVEL pushed to drivers. Default 254 |
| `0x0018` | `cfg_system_failure_level` | u16 | 1 |  | RW | DALI SYSTEM FAILURE LEVEL pushed to drivers. Default 254 |
| `0x0019` | `cfg_sync_word` | u16 | 1 |  | RW | LoRa sync word (low byte). Default 0x12, never 0x34 |
| `0x001A` | `cfg_p0_reserve_pct` | u16 | 1 | % | RW | Share of the hourly airtime budget reserved for P0. Default 25 |
| `0x0020` | `cfg_dim_step1_minute` | u16 | 1 | min | RW | Site default dimming step 1: local minute of day 0-1439 at which the step starts, 0xFFFF = unused |
| `0x0021` | `cfg_dim_step1_level` | u16 | 1 |  | RW | Site default dimming step 1: level (DALI arc 0-254) |
| `0x0022` | `cfg_dim_step2_minute` | u16 | 1 | min | RW | Site default dimming step 2: local minute of day 0-1439 at which the step starts, 0xFFFF = unused |
| `0x0023` | `cfg_dim_step2_level` | u16 | 1 |  | RW | Site default dimming step 2: level (DALI arc 0-254) |
| `0x0024` | `cfg_dim_step3_minute` | u16 | 1 | min | RW | Site default dimming step 3: local minute of day 0-1439 at which the step starts, 0xFFFF = unused |
| `0x0025` | `cfg_dim_step3_level` | u16 | 1 |  | RW | Site default dimming step 3: level (DALI arc 0-254) |
| `0x0026` | `cfg_dim_step4_minute` | u16 | 1 | min | RW | Site default dimming step 4: local minute of day 0-1439 at which the step starts, 0xFFFF = unused |
| `0x0027` | `cfg_dim_step4_level` | u16 | 1 |  | RW | Site default dimming step 4: level (DALI arc 0-254) |
| `0x00F0` | `cfg_commit` | u16 | 1 |  | W | Write 0xA5C3 to validate and apply all written config registers at once. Any other value: exception 0x03. Reads 0 |
| `0x00F1` | `cfg_status` | enum16 | 1 |  | R | 0 applied (nothing pending), 1 pending (written, not committed), 2 applying, 3 rejected (see cfg_error_reg), 4 applied, reboot needed for serial settings |
| `0x00F2` | `cfg_error_reg` | u16 | 1 |  | R | Address of the first register that failed validation at the last commit. 0xFFFF = none |
| `0x00F3` | `cfg_version` | u16 | 1 |  | R | Increments on each successful commit |

Registers `0x001B`–`0x001F`, `0x0028`–`0x00EF` and `0x00F4`–`0x00FF` are reserved.

**Commit rules:**

1. Write any configuration registers (FC06 or FC16). Written values are held as **pending**; reads return the pending value. `cfg_status` = 1.
2. Write `0xA5C3` to `cfg_commit`. The Master validates **all** pending values together. If any is invalid, **none** is applied: `cfg_status` = 3 and `cfg_error_reg` names the first bad register.
3. If valid, the values are applied and stored, `cfg_version` increments, event `0x8009` is raised, and site parameters (location, offsets, dimming steps, cell SF, fail-safe levels) are distributed to the slaves as an internal job.
4. Pending values that are never committed are lost at reboot.
5. Serial settings (`cfg_unit_id`, `cfg_baud_code`, `cfg_parity_code`) are stored at commit but used only after a reboot (`cfg_status` = 4). Send `REBOOT` to the Master to apply them.

### 8.2 Command mailbox (`0x0100`–`0x013F`)

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `0x0100` | `cmd_seq` | u16 | 1 |  | W | Idempotency key, 1-65535 (0 invalid). Server increments for each new command |
| `0x0101` | `cmd_opcode` | u16 | 1 |  | W | Command opcode (spec 01 section 8.3) |
| `0x0102` | `cmd_target` | u16 | 1 |  | W | Target: 12-bit protocol address, or 0x8000 + group (0-15) |
| `0x0103–0x0104` | `cmd_execute_at` | u32 | 1 | s | W | Execution time, Unix UTC. 0 = as soon as possible (broadcasts get at least 5 s lead time) |
| `0x0105` | `cmd_param0` | u16 | 1 |  | W | Command parameter register 0; meaning per opcode (spec 01 section 8.3) |
| `0x0106` | `cmd_param1` | u16 | 1 |  | W | Command parameter register 1; meaning per opcode (spec 01 section 8.3) |
| `0x0107` | `cmd_param2` | u16 | 1 |  | W | Command parameter register 2; meaning per opcode (spec 01 section 8.3) |
| `0x0108` | `cmd_param3` | u16 | 1 |  | W | Command parameter register 3; meaning per opcode (spec 01 section 8.3) |
| `0x0109` | `cmd_param4` | u16 | 1 |  | W | Command parameter register 4; meaning per opcode (spec 01 section 8.3) |
| `0x010A` | `cmd_param5` | u16 | 1 |  | W | Command parameter register 5; meaning per opcode (spec 01 section 8.3) |
| `0x010B` | `cmd_param6` | u16 | 1 |  | W | Command parameter register 6; meaning per opcode (spec 01 section 8.3) |
| `0x010C` | `cmd_param7` | u16 | 1 |  | W | Command parameter register 7; meaning per opcode (spec 01 section 8.3) |
| `0x010D` | `cmd_param8` | u16 | 1 |  | W | Command parameter register 8; meaning per opcode (spec 01 section 8.3) |
| `0x010E` | `cmd_param9` | u16 | 1 |  | W | Command parameter register 9; meaning per opcode (spec 01 section 8.3) |
| `0x010F` | `cmd_param10` | u16 | 1 |  | W | Command parameter register 10; meaning per opcode (spec 01 section 8.3) |
| `0x0110` | `cmd_param11` | u16 | 1 |  | W | Command parameter register 11; meaning per opcode (spec 01 section 8.3) |
| `0x0111` | `cmd_param12` | u16 | 1 |  | W | Command parameter register 12; meaning per opcode (spec 01 section 8.3) |
| `0x0112` | `cmd_param13` | u16 | 1 |  | W | Command parameter register 13; meaning per opcode (spec 01 section 8.3) |
| `0x0113` | `cmd_param14` | u16 | 1 |  | W | Command parameter register 14; meaning per opcode (spec 01 section 8.3) |
| `0x0114` | `cmd_param15` | u16 | 1 |  | W | Command parameter register 15; meaning per opcode (spec 01 section 8.3) |
| `0x0115` | `cmd_args_crc` | u16 | 1 |  | W | CRC-16/MODBUS over registers 0x0100-0x0114 taken as big-endian bytes |
| `0x0116` | `cmd_trigger` | u16 | 1 |  | W | Must be 0xA5C3, written in the same FC16 request as 0x0100-0x0115 |
| `0x0117` | `mask_select_seq` | u16 | 1 |  | RW | Selects the job whose fail masks are shown at 0x0140: a cmd_seq present in the job table, or 0 = latest job |
| `0x0120` | `job_ack_seq` | u16 | 1 |  | R | cmd_seq of the latest accepted job |
| `0x0121` | `job_state` | enum16 | 1 |  | R | 0 IDLE, 1 ACCEPTED, 2 QUEUED, 3 DISPATCHING, 4 PARTIAL, 5 CONFIRMED, 6 FAILED, 7 EXPIRED, 8 REJECTED |
| `0x0122` | `job_result` | enum16 | 1 |  | R | Result code (spec 02 section 11.5) |
| `0x0123` | `job_n_targets` | u16 | 1 |  | R | Devices or gateways targeted |
| `0x0124` | `job_n_acked` | u16 | 1 |  | R | Targets confirmed so far |
| `0x0125` | `job_n_failed` | u16 | 1 |  | R | Targets that failed or did not confirm before the TTL |
| `0x0126–0x0127` | `job_accepted_utc` | u32 | 1 | s | R | Time the job was accepted |
| `0x0128–0x0129` | `job_execute_at` | u32 | 1 | s | R | Execution time actually used |
| `0x012A` | `job_response0` | u16 | 1 |  | R | Opcode-specific response register 0 |
| `0x012B` | `job_response1` | u16 | 1 |  | R | Opcode-specific response register 1 |
| `0x012C` | `job_response2` | u16 | 1 |  | R | Opcode-specific response register 2 |
| `0x012D` | `job_response3` | u16 | 1 |  | R | Opcode-specific response register 3 |
| `0x012E` | `job_response4` | u16 | 1 |  | R | Opcode-specific response register 4 |
| `0x012F` | `job_response5` | u16 | 1 |  | R | Opcode-specific response register 5 |
| `0x0130` | `job_response6` | u16 | 1 |  | R | Opcode-specific response register 6 |
| `0x0131` | `job_response7` | u16 | 1 |  | R | Opcode-specific response register 7 |

Registers `0x0118`–`0x011F` and `0x0132`–`0x013F` are reserved.

**Submitting a command:**

1. Write `0x0100`–`0x0116` (23 registers) in **one FC16 request**: `cmd_seq`, opcode, target, `execute_at`, the parameters, `cmd_args_crc`, and `cmd_trigger` = `0xA5C3`. Any other write touching this block returns exception `0x03` and does nothing.
2. The Master validates the request within 50 ms and replies. Validation failures still create a job, with state `REJECTED` and a reason in `job_result`, so the Server can see why.
3. If the job queue is full, the Master returns exception `0x06` and creates no job.
4. Poll `job_ack_seq` and `job_state` (FC03, `0x0120`–`0x0129`) until the state is final (§8.4).

**Idempotency:** if `cmd_seq` matches a job still in the job table, no new job is created and the readback shows that job. A Modbus retry of the same write therefore never sends a command twice. The Server MUST use a new `cmd_seq` for every new command and MUST NOT reuse a value within 24 hours.

### 8.3 Opcodes and parameters

Opcode numbers are the same in the mailbox and in radio CMD frames ([02](02-tier1-protocol.md), [03](03-tier2-device-protocol.md)). Parameters are listed by mailbox register (`p0` = `cmd_param0` at `0x0105`). 32-bit parameters are high word first. A UID occupies `p0`–`p5`, with UID byte 0 in the high byte of `p0`.

| Opcode | Name | Valid targets | Parameters | Response |
|---|---|---|---|---|
| `0x01` | `SET_LEVEL` | Device, section, site, group | `p0` level 0–254 · `p1` DALI fade index 0–15 · `p2` override TTL, minutes, 0–720 (0 = until the next schedule step) | — |
| `0x02` | `RESUME_SCHEDULE` | Device, section, site, group | — | — |
| `0x03` | `IDENTIFY` | Device, section, group | `p0` blink pattern · `p1` duration, s | — |
| `0x04` | `QUERY` | Device, section | — | Device or section blocks refreshed. `r0` = records received |
| `0x05` | `SET_TIME` | Master (`0x000`) only | `p0`–`p1` UTC · `p2` `tz_offset_min` (i16) · `p3` force (0/1) | `r0` = applied correction, s (i16, saturating) |
| `0x06` | `SET_SCHEDULE` | Section, site | `p0`–`p1` latitude (i32, 1e-5°) · `p2`–`p3` longitude · `p4` dusk offset, min (i16) · `p5` dawn offset, min (i16) · `p6`–`p13` four dimming steps as (local minute 0–1439 or `0xFFFF` = unused, level) | — |
| `0x07` | `REBOOT` | Master, slave, device | — | — |
| `0x08` | `OPEN_COMMISSIONING` | Section | `p0` duration, min, 1–60 | — |
| `0x09` | `AUTHORISE_DEVICE` | Section | `p0`–`p5` UID · `p6` device type (1 LED, 2 meter) · `p7` requested NodeID (0 = slave picks) | `r0` = assigned 12-bit address |
| `0x0A` | `REVOKE_DEVICE` | Device | — | — |
| `0x0B` | `REPLACE_DEVICE` | Device (the old address) | `p0`–`p5` new UID | — |
| `0x0C` | `REPLACE_DRIVER` | Device | — | `r0` = DALI result code from the device |
| `0x0D` | `REASSERT_CONFIG` | Device, section, site | — | — |
| `0x0E` | `SET_FAILSAFE_LEVELS` | Device, section, site, group | `p0` POWER ON LEVEL · `p1` SYSTEM FAILURE LEVEL | — |
| `0x0F` | `FORCE_FAILOVER` | Master, slave | `p0` 0 = return to primary, 1 = force standby | — |

Unused parameter registers MUST be 0. **Target encoding:** a device is its 12-bit address (`0x0snn`); a section is `0x0sFF`; the whole site is `0x0FFF`; the Master is `0x0000`; a slave is `0x0s00`; a group is `0x8000 + g` (g = 0–15). Any other value gives `REJECTED` / `BAD_TARGET`.

`SET_LEVEL` and `RESUME_SCHEDULE` to a section, site or group are **P0**: they jump to the head of the queue and are sent as broadcasts with `execute_at` ([04](04-channel-plan-and-airtime.md) §6.4). A newer level command for the same target supersedes one still queued: the older job ends `EXPIRED` with result `SUPERSEDED`.

### 8.4 Job lifecycle

| State | Value | Meaning | Final? |
|---|---|---|---|
| `IDLE` | 0 | No job has been submitted since boot | — |
| `ACCEPTED` | 1 | Valid, entered in the queue | No |
| `QUEUED` | 2 | Waiting for airtime or a tier-1 slot | No |
| `DISPATCHING` | 3 | Sent; collecting confirmations. `job_n_acked` rises as targets confirm | No |
| `PARTIAL` | 4 | Finished with some targets confirmed and some not (see the fail masks) | Yes |
| `CONFIRMED` | 5 | Every target confirmed | Yes |
| `FAILED` | 6 | No target confirmed | Yes |
| `EXPIRED` | 7 | Not dispatched before its TTL, or superseded | Yes |
| `REJECTED` | 8 | Failed validation | Yes |

- **Job TTL: 10 minutes** from acceptance. A job not finished by then becomes final (`PARTIAL`, `FAILED` or `EXPIRED`). The radio CMD carries `execute_at` and a matching `not_after`, so a late frame is never executed.
- Group and section commands are confirmed by the devices' next reports, normally within two cycles.
- To retry stragglers after `PARTIAL`, the Server submits a new job targeting only the devices in the fail mask.
- The Master holds up to **8 jobs not yet final**. A ninth gives exception `0x06`.

### 8.5 Result codes (`job_result`)

Result codes are **one system-wide table**, defined in [02 §11.5](02-tier1-protocol.md) and shared with the radio CMD_ACKs. The codes that can appear in `job_result`:

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | No error |
| 3 | `EXPIRED` | Not dispatched before its TTL; or the radio command passed its `not_after` |
| 4 | `REFUSED_UNSAFE` | Refused by a safety rule, e.g. `SET_TIME` jump > 5 min without `force`, or a slave refusing a level below 254 with an untrusted clock |
| 5 | `BAD_OPCODE` | Unknown or reserved opcode |
| 6 | `BAD_PARAMS` | A parameter out of range, or an unused parameter not 0 |
| 8 | `TARGET_NOT_CONFIGURED` | Section or device not configured |
| 11 | `BAD_TARGET` | Target not valid for this opcode |
| 12 | `BAD_CRC` | `cmd_args_crc` doesn't match |
| 13 | `TARGET_OFFLINE` | Target offline at dispatch (unicast only) |
| 14 | `TIMEOUT` | TTL reached before every target confirmed |
| 15 | `NOT_SUPPORTED` | Target doesn't support the opcode (e.g. `REPLACE_DRIVER` on a meter) |
| 16 | `AIRTIME_DEFERRED` | Couldn't be sent within its TTL because of the airtime budget |
| 17 | `SUPERSEDED` | Replaced by a newer command for the same target |
| 18 | `TOO_LATE` | `execute_at` is in the past or more than 24 h ahead |

`PARTIAL` and `FAILED` outcomes are job **states** (§8.4), not result codes. A full queue is exception `0x06`, not a result code.

### 8.6 Job table and fail masks

The job table holds the last 8 jobs, **newest first**, at `0x0180 + k × 8` (k = 0–7). The Server uses it to follow jobs that are still settling after it has submitted newer ones.

| Offset | Name | Type | Scale | Unit | Access | Description |
|---|---|---|---|---|---|---|
| `+0` | `jobtab_seq` | u16 | 1 |  | R | cmd_seq of this job, 0 = empty entry. Entry k (0-7) at 0x0180 + k*8, newest first |
| `+1` | `jobtab_opcode` | u16 | 1 |  | R | Opcode. Entry k (0-7) at 0x0180 + k*8, newest first |
| `+2` | `jobtab_state` | enum16 | 1 |  | R | Job state (as job_state). Entry k (0-7) at 0x0180 + k*8, newest first |
| `+3` | `jobtab_result` | enum16 | 1 |  | R | Result code (as job_result). Entry k (0-7) at 0x0180 + k*8, newest first |
| `+4` | `jobtab_n_targets` | u16 | 1 |  | R | Targets. Entry k (0-7) at 0x0180 + k*8, newest first |
| `+5` | `jobtab_n_acked` | u16 | 1 |  | R | Confirmed. Entry k (0-7) at 0x0180 + k*8, newest first |
| `+6` | `jobtab_n_failed` | u16 | 1 |  | R | Failed or unconfirmed. Entry k (0-7) at 0x0180 + k*8, newest first |
| `+7` | `jobtab_age_s` | u16 | 1 | s | R | Seconds since the job was accepted. Entry k (0-7) at 0x0180 + k*8, newest first |

**Fail masks** (`0x0140 + s × 4`, 4 registers per section) show the job selected by `mask_select_seq` (0 = latest). Register `+k` holds NodeIDs `16k` to `16k + 15`; bit (n mod 16) set = NodeID n failed or didn't confirm. Masks are kept while the job is in the job table.

### 8.7 FC03 mirror

When `cfg_fc03_mirror` = 1 (default), FC03 at holding address `0x8000 + a` returns the same data as FC04 at input address `a`, for every valid input range. The mirror is read-only. It exists for diagnostic tools that only speak FC03 (QModMaster, Modpoll). The Server uses FC04.

## 9. Staleness

| Comm state | Condition |
|---|---|
| 1 online | `age_status_s` ≤ `stale_threshold_s` (default 360 s = 3 cycles), and the slave hasn't reported the device missing |
| 2 stale | `age_status_s` > `stale_threshold_s`: the Master hasn't had confirmation, e.g. because the section is LOST |
| 3 offline | The slave reports the device missing (3 missed reports, [03](03-tier2-device-protocol.md)) |

`stale_policy` (holding `0x0014`) chooses what a stale or offline block returns:

| Policy | Behaviour |
|---|---|
| **0 (default)** | Last known values, with their ages and the comm state. The most informative, and what the Server is built for |
| 1 | Status and ages as normal; every other value field reads "not available" (§5.2) |
| 2 | Any read touching the block returns exception `0x0B`. ⚠ A bulk read across one stale device then fails entirely, so policy 2 is only for third-party tools reading one device at a time |

## 10. Polling

### 10.1 Recommended Server strategy

| Every | Read | Registers | Requests |
|---|---|---|---|
| 2 s | System head `0x0000`–`0x0026` | 39 | 1 |
| 2 s | Event header `0x0800`–`0x0803`, then the window if `ev_window_count` > 0 | 4 + 8 per event | 1–3 |
| When `telemetry_epoch` changes | Summary of each configured section (`0x0400 + s×64`, 64 registers) | 64 per section | 1 per section |
| When `telemetry_epoch` changes | Section blocks `0x0110`–`0x01EF` and meter blocks of configured sections | 16 / 32 per section | 1–2 / 1 per 3 sections |
| When a device's summary changes | That device's block, whole | 16 | grouped |
| Each detail interval (15 min) | Every configured device block, whole blocks | 16 per device | 9 per 60-device section |

**Device blocks are read in whole blocks**, at most 7 per request (112 registers), so no 32-bit value or block is split across requests (§5.3). A full 60-device section (NodeIDs 1–60, `0x...10`–`0x...3CF`) is **9 requests**: 8 of 7 devices and 1 of 4.

### 10.2 Timing at 19200 8E1

One character = 11 bits = 0.573 ms. The figures include the request, t3.5 gaps and a typical 5 ms Master reply latency.

| Request | Response size | Approx. time |
|---|---|---|
| System head, 39 registers | 83 B | ~60 ms |
| Summary, 64 registers | 133 B | ~90 ms |
| 7 device blocks, 112 registers | 229 B | ~145 ms |
| Full section of device blocks (9 requests) | — | ~1.3 s |

At 115200 baud the full-section read takes about 0.3 s. Routine polling (system head + event header every 2 s) uses about 4% of the bus at 19200.

## 11. Versioning

- `map_version_major` / `map_version_minor` (input `0x0000`–`0x0001`). This draft is **0.1**. The frozen map at M1 is **1.0**.
- **Minor** version: fields added in reserved space only. Existing addresses and meanings don't change.
- **Major** version: anything moved, removed, rescaled or redefined.
- The Server MUST read the major version at start-up and refuse to poll (raising an alarm) if it doesn't match the version it was generated for.

## 12. The CSV source

`register-map/register-map.csv`, UTF-8, comma-separated, one header row.

| Column | Meaning |
|---|---|
| `space` | `input` or `holding` |
| `address` | `base + offset` (hex). For repeated rows this is the formula origin (s = 0, n = 0), not necessarily a valid address |
| `base` | Base address of the area (hex) |
| `offset` | Offset of the field inside its block (hex) |
| `section_stride` | Address step per section index s (hex). `0x0000` = not repeated per section |
| `device_stride` | Address step per inner index n (hex). `0x0000` = not repeated |
| `count` | Registers the field occupies (1 or 2) |
| `name` | Unique field name (the generated C and Python identifier) |
| `type` | `u16`, `i16`, `u32`, `i32`, `enum16`, `bits16`, `bits32` |
| `scale`, `unit` | Physical value = raw × scale, in unit |
| `access` | `R` read-only, `RW` read/write, `W` write (reads return the last written value, or 0 for commit/trigger) |
| `repeat` | `none`, `per_section`, `per_device`, `per_event`, `per_job` |
| `description` | Meaning, enum values, bit fields |

**Expansion rule:** `address(s, n) = base + s × section_stride + n × device_stride + offset`, where

| `repeat` | s | n |
|---|---|---|
| `none` | 0 | 0 |
| `per_section` | 1–14 | 0 |
| `per_device` | 1–14 | 0–63 |
| `per_event` | 0 | 0–31 |
| `per_job` | 0 | 0–7 |

A generator expands only the configured sections when building a site-specific poll list. Expanded over all 14 sections, the map defines 16 512 registers with no overlaps.

## Open items

| # | Item | Needed by |
|---|---|---|
| O-01-1 | Client confirmation that 19200 8E1 and unit ID 1 suit their RS485 setup (cable length, other equipment on the bus) | M1 sign-off |
| O-01-2 | Event buffer capacity (≥ 1000 events) to be confirmed against the NOR flash fitted ([06](06-gateway-hardware-requirements.md)) | M1 sign-off |
| O-01-4 | Confirm a 15-minute detail interval (power and energy freshness) is acceptable to the client ([04](04-channel-plan-and-airtime.md)) | M1 sign-off |
| O-01-5 | Decide whether the diagnostic DALI levels option (system failure 250 ≈ 90 %) is used ([05](05-fail-safe-behaviour.md)); defaults stay 254 / 254 | M1 sign-off |
