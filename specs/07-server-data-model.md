# 07 — Local Monitoring Server: Data Model, Dashboard and Control

| | |
|---|---|
| **Spec** | 07 — Local Monitoring Server data model, dashboard and control requirements |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-29 |
| **Owner** | pgorospe |
| **Reviewers** | Gateway hardware developer (for the client) |
| **Status** | Draft. Not frozen |

What the Local Monitoring Server stores, what operators see, and what they can control. The server reads the Master over Modbus RTU ([01](01-modbus-register-map.md)). Conventions are in [00](00-common-frame-and-conventions.md), and the timing that limits how fresh the data can be is in [04](04-channel-plan-and-airtime.md).

## 1. Scope

| In scope | Not in scope |
|---|---|
| One site, on a local network | Multi-site, cloud hosting |
| Browser UI on the local network, up to 10 users | Mobile app, remote access from the internet (optional add-on) |
| Client-supplied PC. ⚠ OS (Windows or Linux) still to confirm | Email/SMS notifications (optional add-on) |
| Monitoring, control, schedules, alarms, users, energy reports, CSV export | MQTT/TALQ/OPC UA northbound interfaces |
| Installation, backup and restore | Billing, asset management beyond pole/device records |

**The server is never in the nightly on/off path.** If the PC is off, the gateways and devices keep following their schedules ([05](05-fail-safe-behaviour.md)).

## 2. Stack

| Layer | Choice |
|---|---|
| Poller and API | Python 3.12, FastAPI, `pymodbus`. One process owns the serial port |
| Database | PostgreSQL 16 + TimescaleDB (hypertables for telemetry) |
| UI | One web app: React + TypeScript (Vite), built to static files that FastAPI serves on the server PC. Charts are part of the app (no embedded Grafana). Live values arrive over a WebSocket. Look and wording follow the Streetlight RMS design system |
| Packaging | Docker Compose on Linux, or native Windows services. Decided at installation |
| Serial | Isolated USB-RS485 adapter, identified by its serial number, not by port name |

## 3. Poller

| # | Requirement |
|---|---|
| POL-1 | Serial settings and unit ID as in [01](01-modbus-register-map.md) (default 19200 8E1, unit 1). Response timeout ≥ 1 s. Up to 2 retries, then the poll counts as failed |
| POL-2 | Follow the read strategy in [01 §10](01-modbus-register-map.md). Every 2 s: the system head `0x0000`–`0x0026` (includes `heartbeat` and `telemetry_epoch`) and the event header. When `telemetry_epoch` changes: the summary registers of each configured section, then the section and meter blocks, then the whole block of each device whose summary changed. Every detail interval (15 min): every configured device block |
| POL-2a | **Device blocks are read whole**, at most 7 per request (112 registers), so no 32-bit value is split across requests: **9 requests** for a 60-device section |
| POL-2b | At start-up, read `map_version_major` and refuse to poll if it doesn't match the version the poller was generated for (`MAP_VERSION_MISMATCH`) |
| POL-3 | Every poll stores the value **with its age** (`dev_age_status_s`, `dev_age_detail_s`, `sec_age_s`, `met_age_s` from [01](01-modbus-register-map.md)). The server never shows an old value as current |
| POL-4 | Connection health: link state (`up` / `degraded` / `down`), poll success rate, last good poll, CRC and exception counts. Down = 5 consecutive failed polls |
| POL-5 | If `heartbeat` stops changing while Modbus still answers, raise "master frozen" |
| POL-6 | Commands use the mailbox ([01 §8.2](01-modbus-register-map.md)): one FC16 write of `0x0100`–`0x0116` with `cmd_args_crc` and the trigger. The poller follows each job in the job table (holding `0x0180`) until it reaches a final state or its TTL (10 min) expires, and reads the per-section fail masks (`0x0140`) for PARTIAL jobs. A full queue (exception `0x06`) is retried later |
| POL-7 | Time: the server offers its NTP-synced time to the Master with `SET_TIME` (opcode 0x05) every hour and after each reconnect. The Master may reject a large jump; the server then raises an alarm, and only an admin may send it with `force = 1` |
| POL-8 | **Events:** every poll, read the event window (input `0x0800`, [01 §7](01-modbus-register-map.md)); store each event durably with its original timestamp, **then** acknowledge by writing `event_ack_seq` (holding `0x0200`). After a reconnect this drains everything the Master buffered |

Freshness the server can expect (from [04](04-channel-plan-and-airtime.md) §8): device status ≤ 1 cycle (2 min), per-device power and energy ≤ 15 min, meter every 5 min, offline after 6 min of missed reports.

## 4. Data model

Types are PostgreSQL. `ts` columns are `timestamptz` stored in UTC and displayed in local time (UTC+8). Telemetry tables are TimescaleDB hypertables on `ts`.

### 4.1 Site and topology

| Table | Columns |
|---|---|
| `site` | `id` smallint PK · `name` text · `net_id` smallint (1–254) · `lat` numeric(8,5) · `lon` numeric(8,5) · `tz_offset_min` smallint (default 480) · `created_at` ts |
| `section` | `id` smallint PK · `site_id` FK · `gw_id` smallint UNIQUE (1–14) · `name` text · `cell_ch_a` smallint · `cell_ch_b` smallint · `phase` text NULL · `design_unbalance_pct` numeric NULL |
| `gateway` | `id` serial PK · `site_id` FK · `role` text (`master` / `slave`) · `gw_id` smallint (0 = master) · `section_id` FK NULL · `uid` bytea(12) · `fw_version` text · `hw_rev` text · `installed_at` ts |
| `radio` | `id` serial PK · `gateway_id` FK · `position` text (`t1_primary`, `t1_standby`, `cell_a`, `cell_b`) · `channel` smallint · `sf` smallint · `tx_power_dbm` smallint |
| `pole` | `id` serial PK · `section_id` FK · `asset_id` text UNIQUE (e.g. `PH-SITE1-S3-P017`) · `lat` / `lon` numeric NULL · `road_class` text NULL · `luminaire_model` text NULL · `nominal_power_w` numeric NULL · `group_mask` smallint (bit g = member of group g, 0–15) |
| `device` | `id` serial PK · `uid` bytea(12) UNIQUE · `device_type` smallint (1 = LED, 2 = meter) · `fw_version` text · `hw_rev` text · `state` text (`authorised`, `joined`, `revoked`, `decommissioned`) · `capabilities` jsonb (D4i, etc.) · `first_seen` ts · `last_seen` ts |
| `device_assignment` | `id` serial PK · `device_id` FK · `pole_id` FK NULL (NULL for a meter) · `section_id` FK · `address` smallint (12-bit, [00](00-common-frame-and-conventions.md) §3) · `valid_from` ts · `valid_to` ts NULL · `reason` text (`commission`, `swap`, `revoke`) · `technician` text · UNIQUE(address) WHERE `valid_to` IS NULL |
| `meter` | `device_id` PK FK · `section_id` FK · `wiring` text (`wye` / `delta`) · `ct_ratio` numeric NULL · `accuracy_class` text |

`device_assignment` is the permanent history of UID ↔ address ↔ pole. A swap closes the old row and opens a new one with the same address and pole ([03](03-tier2-device-protocol.md), `REPLACE_DEVICE`). Data stays attached to the **pole and address**, so a pole's history survives device swaps.

### 4.2 Telemetry (hypertables)

| Table | Columns | Source / rate |
|---|---|---|
| `device_status` | `ts` · `address` smallint · `status` int (status bits, [01 §6.4](01-modbus-register-map.md)) · `level_actual` smallint · `level_commanded` smallint · `online_state` smallint (summary comm state: 0 not configured, 1 online, 2 stale, 3 offline) · `age_status_s` int | Summary and status registers; stored **on change** plus once every 15 min |
| `device_detail` | `ts` · `address` · `power_dw` int · `energy_wh` bigint · `voltage_dv` int · `current_ma` int · `temp_c` smallint · `lamp_hours` int · `fault_code` smallint · `rssi_dbm` smallint · `snr_db` numeric · `slot` smallint · `channel` smallint · `age_detail_s` int | Device block; every 15 min (basic) and hourly (extended) |
| `meter_reading` | `ts` · `address` · `v_l1/l2/l3_dv` int · `i_l1/l2/l3/n_10ma` int · `p_l1/l2/l3_w` int · `p_total_w` int · `pf_total` numeric(4,3) · `freq_hz` numeric(5,2) · `e_import_wh` bigint · `e_export_wh` bigint · `thd_i_pct` numeric · `flags` int · `age_s` int | Meter block; every 5 min |
| `gateway_health` | `ts` · `gateway_id` · `state` text (SYNCED, DEGRADED, AUTONOMOUS, CLOCK_UNTRUSTED, REJOINING, LOST) · `active_t1_radio` text · `airtime_pct` numeric · `devices_online` smallint · `uptime_s` bigint · `boot_count` int · `fault_bitmap` bigint · per-radio counters jsonb | System and section blocks; every 60 s |
| `modbus_link` | `ts` · `state` · `polls_ok` int · `polls_failed` int · `crc_errors` int · `exceptions` int | Poller; every 60 s |

### 4.3 Events, alarms, commands

| Table | Columns |
|---|---|
| `event` | `id` bigserial · `ev_seq` int · `ts` (original time, from the gateway) · `received_at` ts · `source` smallint (12-bit address) · `code` int (`ev_code`, [01 §7](01-modbus-register-map.md)) · `name` text · `severity` smallint (0–3) · `arg1` int · `arg2` int. Append-only |
| `alarm` | `id` bigserial · `code` text · `severity` smallint (0 info · 1 warning · 2 alarm · 3 critical) · `source` text · `raised_at` ts · `acked_at` ts NULL · `acked_by` FK NULL · `cleared_at` ts NULL · `count` int (repeats while open) · `detail` jsonb. At most one open alarm per (`code`, `source`) |
| `command_job` | `id` bigserial · `cmd_seq` int (mailbox sequence) · `opcode` smallint · `target` int (16-bit target, [01](01-modbus-register-map.md)) · `params` jsonb · `execute_at` ts NULL · `override_ttl_min` int NULL · `state` text (IDLE, ACCEPTED, QUEUED, DISPATCHING, PARTIAL, CONFIRMED, FAILED, EXPIRED, REJECTED) · `result` smallint (result code, [02 §11.5](02-tier1-protocol.md)) · `n_targets` int · `n_confirmed` int · `n_failed` int · `created_by` FK · `created_at` ts · `finished_at` ts NULL |
| `job_target` | `job_id` FK · `address` smallint · `result` text (`pending`, `confirmed`, `failed`, `unknown`) · `level_reported` smallint NULL · `updated_at` ts |

### 4.4 Configuration and users

| Table | Columns |
|---|---|
| `schedule_profile` | `id` serial · `name` text · `dusk_offset_min` smallint · `dawn_offset_min` smallint · `steps` jsonb (up to 4 × {`local_minute`, `level`}) · `min_level` smallint (dim floor) · `version` int |
| `schedule_assignment` | `profile_id` FK · `section_id` FK NULL (NULL = whole site) · `valid_from` ts · `pushed_at` ts NULL · `confirmed_config_ver` int NULL |
| `config_intent` | `id` serial · `scope` text (`site`, `section`, `device`) · `scope_ref` int · `key` text · `value` jsonb · `version` int · `changed_by` FK · `changed_at` ts. The intended configuration of every node: source for `REASSERT_CONFIG` |
| `app_user` | `id` serial · `username` text UNIQUE · `password_hash` text (argon2) · `role` text (`viewer`, `operator`, `admin`) · `active` bool · `last_login` ts |
| `audit_log` | `id` bigserial · `ts` · `user_id` FK NULL · `action` text · `target` text · `before` jsonb · `after` jsonb. Append-only; every command, config change, acknowledgement and login |

## 5. Retention

| Data | Full resolution | Then |
|---|---|---|
| `device_status`, `device_detail` | 90 days | 15-min aggregates for 2 years |
| `meter_reading` | 2 years | Daily aggregates kept indefinitely |
| `gateway_health`, `modbus_link` | 30 days | Hourly aggregates for 1 year |
| `event`, `alarm`, `command_job`, `job_target`, `audit_log`, `device_assignment` | Kept indefinitely | — |

Downsampling uses TimescaleDB continuous aggregates and retention policies. ⚠ Disk sizing assumes up to 14 sections × 60 devices. Confirm against the client PC's disk at installation.

## 6. Alarm catalogue

This is **the system's alarm catalogue**: every alarm an operator can see, and exactly which source raises and clears it. Alarm codes are names; the numbers behind them are the event codes, fault codes and status bits defined in [01 §7.3](01-modbus-register-map.md) (Master events `0x8001`+), [02 §9](02-tier1-protocol.md) (slave events `0x01`–`0x17`) and [03 §6, §9](03-tier2-device-protocol.md) (device status bits, fault codes, device events `0x40`–`0x53`). [05](05-fail-safe-behaviour.md) uses these alarm names. Events that map to no alarm below are stored in `event` only.

**Severity, everywhere in the system:** 0 info · 1 warning · 2 alarm · 3 critical.

### 6.1 From gateways and devices

| Code | Severity | Raised when | Cleared when | Source codes |
|---|---|---|---|---|
| `LAMP_FAULT` | 2 | Status bit `lamp_fault` set | Bit clear for one report | Status bit 3; event `0x41`; fault code 1 |
| `DRIVER_FAULT` | 2 | Status bit `driver_fault` set | Bit clear | Status bit 2; event `0x42`; fault code 2 |
| `DALI_BUS_FAULT` | 2 | Status bit `dali_ok` clear, or no DALI gear answers | Bit set | Status bit 1; events `0x43`, `0x44`; fault codes 3–6. Also cleared by `0x46` |
| `DEVICE_OFFLINE` | 2 | Comm state offline (3 missed reports) | Report received | Summary comm state 3; slave events `0x02` / `0x03`; Master events `0x8005` / `0x8006` |
| `DEVICE_FALLBACK` | 1 | Status bit `fallback_mode` set | Bit clear | Status bit 5; events `0x47` / `0x48` |
| `DEVICE_CLOCK_UNTRUSTED` | 1 | Status bit `clock_trusted` clear | Bit set | Status bit 4; event `0x49` |
| `CONFIG_MISMATCH` | 1 | Status bit `config_mismatch` set | Bit clear after re-assert | Status bit 9; event `0x4C` |
| `DEVICE_ENVIRONMENT` | 1 | Over-temperature or supply out of range | Fault code back to 0 | Events `0x4A`, `0x4B`; fault codes 7, 8 |
| `DEVICE_HW_FAULT` | 2 | Device storage, RTC or radio fault | Fault code back to 0 | Fault codes 9, 10, 11 |
| `TAMPER` | 2 | Tamper input triggered | Operator ack | Event `0x4D` |
| `METER_FAULT` | 2 | Meter fault reported | Fault code back to 0 | Event `0x52`; meter fault codes 20, 22 |
| `METER_OVERCURRENT` | 1 | Overcurrent on a phase | Operator ack | Event `0x53` |
| `SECTION_POWER_LOST` | 3 | Mains or a phase lost on a section (never shared with commanded off) | Voltage restored | Slave events `0x05`, `0x06`; meter events `0x50` / `0x51`; meter flags bits 2–4; fault code 21 |
| `SECTION_DARK` | 3 | Lights expected on but the section draws no power | Power back to expected | Slave event `0x04` |
| `SECTION_LOST` | 3 | Master hears no SUMMARY from a slave for 3 cycles | SUMMARY received | Master events `0x8001` / `0x8002`; section state 6 |
| `SECTION_DEGRADED` | 2 | Slave state DEGRADED (lost the Master for 6 min) | SYNCED | Slave event `0x0E`; section state 2 |
| `SECTION_AUTONOMOUS` | 3 | Slave state AUTONOMOUS (lost the Master for 60 min) | SYNCED | Slave event `0x0E`; section state 3 |
| `GW_CLOCK_UNTRUSTED` | 2 | A gateway's clock is untrusted (lights held at 100%) | Clock trusted | Master `0x8007` / `0x8018`; slave `0x0B` / `0x0C`; section state 4 |
| `RADIO_FAILOVER` | 2 | A tier-1 link switched to its standby radio | Failback to primary | Master `0x8003` / `0x8004`; slave `0x07` / `0x08` |
| `STANDBY_RADIO_DOWN` | 2 | A standby radio failed (self-test or missing heartbeats) | Standby restored | Master `0x8011` / `0x8012`; slave `0x14` / `0x15` |
| `CELL_SINGLE_CHANNEL` | 2 | A slave runs its cell on one channel | Both channels back | Slave `0x09` / `0x0A`; section flag bit 0 |
| `RF_DEGRADED` | 1 | Interference: noise floor or packet loss above threshold | RF normal | Master `0x8015` / `0x8016`; slave `0x16` / `0x17` |
| `AIRTIME_HIGH` | 1 | A box reached its airtime reserve (P1–P3 deferred) | Below 60% of budget | Master `0x800C`; slave `0x0D`; `airtime_used_pct` > 75% |
| `CONFIG_FAULT` | 3 | Configuration storage CRC error at boot (second copy or defaults in use) | Configuration re-asserted | Master `0x8017`; slave `0x12`; device fault code 9 |
| `CONFIG_DIVERGED` | 1 | A slave's configuration differs from the Master's on rejoin | Hashes match | Master `0x800A`; slave `0x0F` |
| `SERVER_LOST` | 1 | The Master went 30 min without a valid Modbus request (seen after reconnect) | `SERVER_RESTORED` read | Master `0x8013` / `0x8014` |
| `EVENT_LOSS` | 1 | Events lost to a full buffer | Operator ack | Master `0x800D`; slave `0x11` |
| `GW_RESTARTED` | 0 | A gateway restarted | Auto-clear after ack | Master `0x800B`; slave `0x01`; `boot_count` increments |

### 6.2 Derived by the server

| Code | Severity | Raised when | Cleared when |
|---|---|---|---|
| `MASTER_OFFLINE` | 3 | Modbus link down (POL-4) | 3 consecutive good polls |
| `MASTER_FROZEN` | 3 | `heartbeat` unchanged for 30 s while Modbus answers | Heartbeat moves |
| `MAP_VERSION_MISMATCH` | 3 | The Master's `map_version_major` doesn't match the server's ([01 §11](01-modbus-register-map.md)); polling stops | Versions match |
| `DATA_STALE` | 1 | A section has no fresh device data for > 3 cycles while its slave reports online | Fresh data |
| `TIME_REJECTED` | 1 | The Master rejected `SET_TIME` (job result `REFUSED_UNSAFE`, Master event `0x8008`) | An accepted `SET_TIME` |
| `DAY_BURNER` | 1 | Meter `P_total` above 10 % of expected night load during computed daytime, for 30 min | Below threshold |
| `LIGHTS_OUT_ESTIMATE` | 1 | `(P_expected − P_measured) / P_per_light` ≥ 2 lights for 2 consecutive meter readings, with no matching device alarms | Back under threshold. ⚠ Needs exact commanded levels and `nominal_power_w` per pole |
| `PHASE_UNBALANCE` | 0 | Unbalance exceeds the section's `design_unbalance_pct` by > 10 points for 1 h | Back within baseline |
| `POWER_DIVERGENCE` | 1 | A section's measured power differs from expected (commanded level × nominal power × dim curve) by > 15 % for 1 h | Within 10 % |
| `JOB_PARTIAL` | 1 | A command job ends PARTIAL or FAILED | Operator ack |

**Alarm rules:** alarms are rate-limited and aggregated. A section with 12 lamp faults shows **one** grouped alarm row with the 12 poles, not 12 rows. "Commanded off" and "no power" never share an alarm or a status.

## 7. Dashboard requirements

| # | Requirement |
|---|---|
| UI-1 | **Site view:** every section with its counts (online / stale / offline / not configured / on / faulted), section power, slave state and open alarms |
| UI-2 | **Section view:** every pole in the section, in pole order, with state, level and last report time. Plus the slave's radios, failover state and airtime |
| UI-3 | **Pole view:** current and recent values, a 7-day chart (level, power), the event history, the assignment history (device swaps) and command history |
| UI-4 | **Device states and colours:** online = green, stale = amber, offline = red, not configured = grey, faulted = red outline, each always with its word on screen (Working, Late, Not responding, Not set up, Faulty). **Every value shows its age** ("12 s ago") |
| UI-5 | Optional **map view** when poles have coordinates. Not required for acceptance |
| UI-6 | **Alarm list:** filter by severity, section and state. Acknowledge (operator) and view cleared alarms. Unacknowledged critical alarms are shown on every page. Acknowledging ("Seen") records who and when; an alarm that ends with a partner event stays listed until it clears, a one-off alarm is done once seen; many can be acknowledged at once (D-034) |
| UI-7 | **Job progress:** each command shows its state and `n_confirmed / n_targets`. PARTIAL is shown plainly, with the failed poles listed and a "retry failed" action |
| UI-8 | **Action and confirmation are shown separately.** "Command sent — lights switch at 18:02:05" first. Per-device confirmation fills in as reports arrive (up to one cycle) |
| UI-9 | **Gateway health page:** Modbus link, Master and every slave: state, uptime, radios, counters, airtime |
| UI-10 | **Energy page:** section kWh per day and month, power charts from the meter |
| UI-11 | The UI works in current Chrome and Edge on a desktop screen, and on a phone browser connected to the site's own network (one column, larger touch targets). Access from outside the site network stays an optional add-on (§1) |
| UI-12 | **Plain language.** Operators and crews are not engineers: every screen uses the design system's vocabulary (light, area, brightness, Main gateway, Area gateway; alerts titled in words with what to do). Engineering values (addresses, DALI levels, dBm, channels, codes) appear only in a closed "Technical details" section |

## 8. Control requirements

| # | Requirement |
|---|---|
| CTL-1 | Switch on, off or dim **one pole, a group (0–15), a section or the whole site** with `SET_LEVEL` (opcode 0x01). Targets per [01](01-modbus-register-map.md) |
| CTL-2 | **Every manual override has an expiry.** The operator picks a duration (default 60 min, maximum 720 min) or "until the next schedule step". The UI never offers an override without an expiry |
| CTL-3 | Group, section and site commands are sent with `execute_at` so every light switches together. The UI shows the switch time |
| CTL-4 | Site-wide and section-wide OFF needs a confirmation dialog that states the number of poles affected |
| CTL-5 | `RESUME_SCHEDULE` (0x02) cancels overrides on any target |
| CTL-6 | `IDENTIFY` (0x03) blinks one pole for a technician in the field |
| CTL-7 | **Schedule editing:** dusk/dawn offsets and up to 4 dimming steps per profile; assign a profile to a section or the site; push it with `SET_SCHEDULE` (0x06). The UI shows when each gateway confirms the new configuration version |
| CTL-8 | **Dim floor:** each profile has a `min_level`, and the UI refuses commands and steps below it. ⚠ The legal floor (DOE/DPWH lux by road class) is unverified; the client sets the value |
| CTL-9 | **Commissioning (admin):** open a commissioning window (0x08), authorise a device UID for a section and pole (0x09), revoke (0x0A), replace a device (0x0B), replace a driver (0x0C), re-assert configuration (0x0D), set fail-safe levels (0x0E) |
| CTL-10 | `FORCE_FAILOVER` (0x0F) and `REBOOT` (0x07) are admin-only and shown on the gateway health page |
| CTL-11 | Retrying a failed job retries only the poles that didn't confirm |
| CTL-11a | **Automatic resend (D-034):** 2 min after a level command ends with poles that didn't confirm, the Server resends once to those poles (one unicast each, at most 4 in flight, the override time left). Poles not responding are resent when they are heard again, until the override ends. Never when a newer command covers them |
| CTL-12 | Commands are absolute (a level, never "up 10 %"). ON/OFF is never a toggle |

## 9. Users and roles

| Action | Viewer | Operator | Admin |
|---|---|---|---|
| View dashboards, charts, alarms | ✅ | ✅ | ✅ |
| Export CSV and reports | ✅ | ✅ | ✅ |
| Acknowledge alarms | — | ✅ | ✅ |
| Switch/dim poles, groups, sections (CTL-1–6, 11) | — | ✅ | ✅ |
| Site-wide commands | — | ✅ | ✅ |
| Edit and push schedules, dim floor (CTL-7, 8) | — | — | ✅ |
| Commissioning, swaps, fail-safe levels (CTL-9) | — | — | ✅ |
| Failover test, reboot, forced time set (CTL-10, POL-7) | — | — | ✅ |
| Manage users, backup and restore | — | — | ✅ |

Up to 10 user accounts. Passwords are hashed (argon2). Sessions time out after 8 hours. Every action is written to `audit_log`.

## 10. Reports

| Report | Content |
|---|---|
| Energy per section | kWh per day and per month, from meter `e_import_wh`, plus the site total |
| Burning hours | Hours on per pole per month, from status history |
| Availability | % of the night each pole was confirmed on, per section per month |
| Alarm summary | Alarms raised and cleared per month, by code and section |
| CSV export | Any table view and any chart range, with local timestamps |

⚠ **Savings figures are shown only as energy (kWh).** On a flat-rate (unmetered) streetlight tariff, dimming saves no money. The report doesn't show peso savings unless the client confirms a metered service and enters the tariff.

## 11. Installation, backup and restore (SOW L-8)

| # | Requirement |
|---|---|
| INS-1 | Install procedure for the chosen OS, documented step by step, including the RS485 adapter and serial-number binding |
| INS-2 | The PC runs on a UPS. NTP is configured and checked |
| INS-3 | **Nightly automatic backup** (database dump plus configuration) to a second disk or USB drive, keeping 14 days |
| INS-4 | **Restore procedure**, tested at installation: a clean PC restored from a backup is back in service in under 2 hours |
| INS-5 | The registry (devices, assignments, config intent) can be exported to a file and re-pushed to a replacement Master without re-commissioning |
| INS-6 | Services start automatically on boot and restart if they crash |

## 12. Performance targets

| Target | Value |
|---|---|
| Users at once | 10 |
| Page load (site, section, pole views) | < 2 s on the local network |
| A new value from the Master visible in the UI | < 5 s after the poller reads it |
| Command submitted to job accepted | < 2 s |
| Database size | Fits the retention table in §5 on a 256 GB SSD at the 14-section ceiling ⚠ to verify |

## 13. Acceptance checks (M5)

Run against the bench network (Master, at least two slaves, real and simulated devices):

1. Site, section and pole views show live data, with correct states and ages. A device unplugged turns stale, then offline, on time.
2. Switch a pole, a group, a section and the site. Each job reaches CONFIRMED. A forced failure (device switched off) shows PARTIAL with the right pole listed, and "retry failed" retries only that pole.
3. An override with a 10-minute expiry ends by itself and the pole returns to schedule.
4. Edit a schedule, push it, and see each gateway confirm the new configuration version.
5. Raise, acknowledge and clear at least: `LAMP_FAULT`, `DEVICE_OFFLINE`, `RADIO_FAILOVER`, `MASTER_OFFLINE`.
6. Energy report and CSV export produce correct totals for a test period.
7. A viewer can't send commands. An operator can't edit schedules. Every action shows up in the audit log.
8. Backup, then restore onto a clean install, and the system resumes polling with its history intact.

## Open items

| # | Item | Needed by |
|---|---|---|
| O-07-1 | Client PC: OS (Windows or Linux), CPU, RAM, disk; whether it can run Docker | M1 sign-off |
| O-07-2 | Tariff: metered or flat-rate streetlight service (decides whether peso savings are shown) | M5 |
| O-07-3 | Dim floor per road class (DOE/DPWH lux) ⚠ unverified | M5 |
| O-07-4 | Pole list with asset IDs, sections and (optionally) coordinates and luminaire model / nominal power | Before commissioning |
| O-07-5 | Group definitions (which poles are in groups 0–15), if groups are wanted | M5 |
| O-07-7 | Override default duration (60 min proposed) and site-wide OFF confirmation rule | M1 sign-off |
