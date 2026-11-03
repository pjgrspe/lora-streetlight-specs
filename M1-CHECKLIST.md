# M1 sign-off checklist (spec-v1.0)

What is left before the specs are signed, and who answers each question. **Every question has a default.** If the default is fine, you don't need to reply to it: the spec is signed with the default, and it can still change later through a change request.

Review round: **`review-r2`**, 3 working days. Then the set is tagged `spec-v1.0`, exported to PDF, and each party replies "Approved spec-v1.0" (see [README](README.md), "How sign-off works").

## 1. What changed since the last review (`review-r1d`, 2026-10-29)

| Decision | What changed | Specs |
|---|---|---|
| D-030 | The Master resends a command to a slave that didn't confirm it | 01, 02, 03 |
| D-031, D-032 | Device events, deferred results, FALLBACK rescan and Slave choice | 03 |
| D-033, D-034 | Server UI (one web app, plain language); automatic resend of unconfirmed light commands, "Seen" for alerts | 07 |
| D-035 | A device reports a restart only once after a boot (no false restart alerts) | 03 |
| D-036 | **Every radio is the Ra-01SH (SX1262)**, not the SX1276. BUSY pin needed; DIO2 drives the antenna switch | 00, 03, 04, 06 |
| D-037, D-038 | Device recovery after losing its Slave; device clock steps after a large correction | 03 |
| D-039 | Faster command feedback on the dashboard | 02 |
| D-040, D-041 | 433 MHz for tier 1 considered and **withdrawn: everything stays on 915–918 MHz**. Gateway power ceiling 14 dBm; in-box damage check (TX − isolation ≤ 0 dBm) | 00, 01, 04, 06 |
| D-042 | **Pole sensors:** light sensor (switches on when dark), motion (dims at night, back to full on motion, never off), tilt and impact alarms. Decided on the device; readings sent up hourly; settings per section from the dashboard | 01, 02, 03, 04, 05, 07 |

Full text of each decision: [DECISIONS.md](DECISIONS.md).

## 2. Questions for the hardware developer (for the client)

| # | Question | Default if no answer |
|---|---|---|
| O-01-1 | Do 19200 baud, 8E1, unit ID 1 suit the RS485 run (cable length, other equipment on the bus)? | 19200 8E1, unit 1 |
| O-01-4 | Is a 15-minute refresh of per-light power and energy enough? | 15 min |
| O-01-5, O-05-1 | Light level when a light loses its controller (DALI System Failure Level): 254 (full) or 250 (≈ 90 %, shows a fault)? | 254 |
| O-02-6 | How much outage history should the gateways keep? | 7 days of 15-min summaries |
| O-04-2 | Is a 2-minute status cycle acceptable? (1 minute needs NTC to allow a duty budget per radio) | 120 s |
| O-05-5 | After how long without any message from the server should the Master declare it lost? (The site keeps running its schedules either way) | 30 min |
| O-05-6 | Is full-night 100 % (no dimming) acceptable while a section runs on its own? | Yes |
| D-042 | Motion dimming: the light idles dim (default 30 %) and returns to full on motion, but **never switches off** for lack of motion, for safety. Is that acceptable to the client? And the light sensor switches lights on when dark even by day (storms)? | Yes to both |
| O-07-7 | Default length of a manual override, and the confirmation rule for switching a whole site or section OFF | 60 min (max 12 h); OFF for a site or section asks to confirm and shows how many poles it affects (CTL-4) |

## 3. Questions for the device developer

| # | Question | Default if no answer |
|---|---|---|
| O-00-1 | Is the STM32 96-bit unique ID readable and unique on your (possibly clone) F103 boards? | Yes. If not, you write a unique ID when flashing |
| O-03-1 | Are the device obligations in 03 §13 achievable on the Blue Pill (especially the astro schedule DP-3 and measurements DP-6)? | Yes |
| O-03-2 | Which measurements does the LED device give: voltage, current, power, energy, temperature? | As DP-6: power, voltage, current, energy, and temperature where the hardware can; "not measured" otherwise |
| O-03-3 | First join can take up to 24 min (the device scans 12 channels). OK for commissioning, or pre-set each device's section on the bench? | OK as is |
| O-03-4 | Meter: which model, and read how (metering IC or external Modbus meter)? Confirms the meter REPORT fields | Fields as in 03 |
| O-03-5 | Which sensors does the LED device carry (light, motion, tilt / impact): models, and how they connect to the Blue Pill (pins, I²C or analog)? Also a tamper input? Note the end client excludes materials from China, sensors included | Needed: no default. Spec 03 §7.3 and DP-13 describe what the firmware does with them |
| O-05-3 | Can the device keep time through a power cut (RTC backup)? | No: after a daytime power restore, lights go 100 % until the first beacon |

## 4. Proposed to close or move (no answer needed)

| # | Proposal |
|---|---|
| O-00-2 | Sync word `0x12`: keep it. A site-specific one is a setting |
| O-01-2 | Event buffer of 1000 events needs about 16 KB; the W25Q64 NOR flash (06 §12) has 8 MB. **Close** |
| O-06-2 | Whether the Ra-01SH's CE/FCC certificates help NTC type approval: **move to "before field use"** |
| O-07-1 | Client PC (OS, CPU, RAM): needed for installation, not for the specs. **Move to M5** |
| I-009 | Final result of a long deferred command (REPLACE_DRIVER) is sent once with no retry. Rare; **defer to spec-v1.1** |

## 5. Signed as open items (on purpose)

These depend on the bench, the site or NTC. They stay listed in their spec and don't block sign-off.

- **NTC** (O-00-3, O-04-1): power, dwell, duty cycle and licensing. Spec 04 is signed as provisional until NTC answers; a different answer changes configuration, not the protocol. ⚠ The NTC letter is still needed from the client.
- **Bench, M3–M4**: failover thresholds by pulling an antenna (O-02-4), slave clock-trust window (O-02-5), device library size on the real boards (O-03-6), P0 during device slots (I-005).
- **Real enclosure**: in-box isolation test (O-06-3), touching channels ch 0/1 and 12/13 (O-04-4, I-012).
- **Site and client data**: band scan (O-04-3), channel reuse distance (O-04-5), cabinet (O-06-4), earthing (O-06-5), surge immunity (O-06-6), tariff (O-07-2), road-class dim floors (O-05-4, O-07-3), pole list (O-07-4), groups (O-07-5).
- **DALI details** (O-05-2, O-05-7): checked on the device developer's bench before M4.
- **Firmware bugs found in the simulator** (I-010, I-011): code fixes, no spec change.
