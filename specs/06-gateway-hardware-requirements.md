# 06 — Gateway Hardware Requirements

| | |
|---|---|
| **Spec** | 06 — Gateway hardware requirements |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-20 |
| **Owner** | pgorospe |
| **Reviewers** | Gateway hardware developer (signs), client |
| **Status** | Draft. Not frozen |

What the gateway hardware must provide so the Master and Slave firmware works as specified. It covers the development phase (client-supplied NUCLEO-L476RG boards + SX1276 modules) and the final board. Radio settings and channels are in [00](00-common-frame-and-conventions.md) and [04](04-channel-plan-and-airtime.md).

Each requirement has an ID (`HW-xx`), a level (MUST / SHOULD) and a verification method: **I** = inspection (schematic, BOM, layout), **T** = bench test, **M** = measurement.

## 1. One board design, two builds

| Build | Radios | RS485 | Notes |
|---|---|---|---|
| **Master** | 2 (R1 primary, R2 standby) | Yes, to the server | One per site |
| **Slave** | 4 (U1, U2 up to the master; D1, D2 down to devices) | Footprint only (not fitted) | One per section; the number of sections is configured (1–14) |

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-01 | One PCB design serves both builds. The Master fits radio positions 1–2; the Slave fits 1–4 | SHOULD | I |
| HW-02 | Same MCU family on both builds: **STM32L476** (dev phase: NUCLEO-L476RG) | MUST | I |
| HW-03 | Final board MCU in the **105 °C grade** (part number suffix `7`, e.g. STM32L476RGT7) | MUST | I |

## 2. Radios

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-10 | Radio: **Semtech SX1276, 915 MHz variant** (e.g. HopeRF RFM95W-915, Ai-Thinker Ra-01H). **Not** Ra-01/Ra-02 (433 MHz) | MUST | I, T (RegVersion 0x42 reads 0x12) |
| HW-11 | SPI-transparent modules only. No AT-command modules | MUST | I |
| HW-12 | TCXO-equipped module variant on gateways | SHOULD | I |
| HW-13 | Each radio has its own **NSS, NRESET, DIO0 and DIO1** lines to the MCU. DIO2/DIO3 optional | MUST | I |
| HW-14 | **The two radios of a pair are on different SPI buses** (Master: R1 / R2. Slave: U1 / U2 and D1 / D2). A stuck MISO on one bus can't take out both radios of a pair | MUST | I, T (hold one bus's MISO low: the other radio still works) |
| HW-15 | Each radio of a pair has its **own fused rail or LDO**. A shorted radio can't pull down its partner | MUST | I, T |
| HW-16 | Each radio has its **own antenna connector** (u.FL or SMA on the module), own coax run and own bulkhead | MUST | I |
| HW-17 | Radio NRESET lines are driven by the MCU (the firmware resets a hung radio) | MUST | T |
| HW-18 | Each radio's DIO0/DIO1 go to pins with **distinct EXTI line numbers** (EXTI lines are shared across ports) | MUST | I |

## 3. Proposed pin and bus allocation (NUCLEO-L476RG)

⚠ **Every pin below must be verified** against UM1724 (Nucleo-64 user manual) and the STM32L476RG datasheet alternate-function tables, including solder-bridge (SB) defaults, before wiring. This is a proposal for review, not a verified map.

### 3.1 Buses

| Bus | Pins (SCK / MISO / MOSI) | Carries | Note |
|---|---|---|---|
| **SPI1** | PA5 / PA6 / PA7 | R1 (Master) · U1 + D1 (Slave) | ⚠ On the Nucleo, PA5 also drives user LED LD2 through solder bridge SB21. Either accept the LED flickering with SPI clock, or **open SB21** so the LED doesn't load SCK (recommended on the bench boards). PA5 is not available as an indicator |
| **SPI2** | PB13 / PB14 / PB15 | R2 (Master) · U2 + D2 (Slave) | |
| **SPI3** | PC10 / PC11 / PC12 | FRAM + NOR flash | **A third SPI bus is required** so storage is never on a radio bus (HW-40) |
| USART1 | PA9 TX / PA10 RX / **PA12 DE** | RS485 (Master) | PA12 = USART1_DE (hardware driver enable). ⚠ PA11/PA12 are also USB OTG pins; confirm nothing is fitted on them on the Nucleo |
| USART2 | PA2 TX / PA3 RX | Service console | **Reserved for the ST-LINK virtual COM port** (SB13/SB14 default). Don't use PA2/PA3 for anything else |
| SWD | PA13 / PA14 (+ NRST) | Debug | Reserved |
| LSE | PC14 / PC15 | 32.768 kHz RTC crystal | Reserved |
| HSE | PH0 / PH1 | Main clock (ST-LINK MCO on Nucleo) | Reserved |

Alternative for RS485 if USART1 conflicts: USART3, PC4 TX / PC5 RX / PB1 DE (then move U2 DIO1 off PC5).

### 3.2 Radio control lines

| Radio | Bus | NSS | NRESET | DIO0 (EXTI) | DIO1 (EXTI) |
|---|---|---|---|---|---|
| R1 / U1 | SPI1 | PA4 | PA8 | PC0 (0) | PC1 (1) |
| D1 | SPI1 | PB6 | PC8 | PC2 (2) | PC3 (3) |
| R2 / U2 | SPI2 | PB12 | PB2 | PB4 (4) | PC5 (5) |
| D2 | SPI2 | PB7 | PC9 | PC6 (6) | PC7 (7) |

The Master uses the R1 and R2 rows only.

### 3.3 Storage, indicators, service

| Function | Pin | Note |
|---|---|---|
| FRAM CS | PA15 | |
| NOR CS | PD2 | |
| LED radio 1 / 2 / 3 / 4 | PA0 / PA1 / PB1 / PB10 | Per-radio TX/RX activity (HW-70) |
| LED FAULT | PB11 | |
| LED RS485 | PB8 | Not PA5: PA5 is SPI1 SCK (§3.1) |
| Service button | PC13 (B1 on Nucleo) | Hold at boot = console service mode |
| Spare | PB0, PB3, PB5, PB9, PC4 | PB3 = SWO if trace is wanted. PC4 is used if RS485 moves to USART3 (§3.1) |

## 4. RS485 (Master)

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-20 | **Isolated** transceiver: **ADM2587E** (signal + isolated DC-DC in one part), or equivalent ≥2.5 kV rms isolation | MUST | I |
| HW-21 | Driver enable from the USART hardware DE pin (§3.1). RE tied enabled so the firmware can read back its own transmission (echo check) | MUST | I, T |
| HW-22 | **120 Ω termination, jumper-selectable** (fitted only if the Master is a physical end of the bus) | MUST | I |
| HW-23 | **Fail-safe bias at the Master only**, jumper-selectable, from the isolated 5 V side: 560 Ω to A / B. (At 3.3 V use 300–390 Ω) | MUST | I, M (idle V_AB ≥ 200 mV with both terminations fitted) |
| HW-24 | Surge protection: **GDT → 10 Ω series PTC/fusible resistors → SM712 TVS** → transceiver | MUST | I |
| HW-25 | Terminal block for A, B, isolated common and shield. Shield bonded at one end only | MUST | I |
| HW-26 | Bench (dev phase): isolated USB-RS485 adapter on the server PC (FTDI/CP210x-based) | MUST | I |

## 5. Storage

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-40 | FRAM **MB85RS256B** (256 kbit, SPI) and NOR **W25Q64JV, industrial grade** (8 MB) on **SPI3**, never on a radio bus | MUST | I |
| HW-41 | Separate chip selects; pull-ups on both CS lines so they stay deselected during reset | MUST | I |
| HW-42 | Dev phase: FRAM and NOR on a small breakout wired to the Nucleo morpho headers | SHOULD | I |

## 6. RTC and clock

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-50 | 32.768 kHz LSE crystal with load capacitors **matched to its C_L** (allow 3–5 pF stray) | MUST | I, M (drift < 20 ppm at 25 °C before calibration) |
| HW-51 | **VBAT brought out separately** from VDD, backed by **CR2032 + 0.22 F supercap** (supercap charged through 100–470 Ω), with 1 kΩ + 100 nF filter on VBAT | MUST (final board) | I, T (RTC keeps time through a 1-h power cut) |
| HW-52 | ⚠ On NUCLEO-L476RG, VBAT is tied to 3V3 by default. **Open the solder bridge per UM1724 before fitting a backup cell.** Dev boards may run without backup (the firmware then boots `CLOCK_UNTRUSTED`, [05](05-fail-safe-behaviour.md) F14) | MUST (if backup fitted) | I |

## 7. Power

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-60 | Mains AC-DC: **Mean Well IRM-10-5** (85–305 VAC) or equivalent with safety approvals. **No HLK-PM01-class modules** | MUST | I |
| HW-61 | 3.3 V by **low-noise LDO**, sized for the radio count. **One LDO or fused rail per radio of a pair** (HW-15) | MUST | I, M |
| HW-62 | Input: fuse → thermally protected MOV (e.g. TMOV14R275E) L-N + GDT N-PE → X2/Y2 filter + common-mode choke | MUST | I |
| HW-63 | Hold-up: ≥470 µF on 3.3 V (enough for a FRAM write after power-fail detection) | MUST | I, T |
| HW-64 | Supply voltage readable by the MCU (internal VREFINT is enough; an external divider on the 5 V rail SHOULD be added) | SHOULD | I |
| HW-65 | Last-gasp supercap so the box can send one alarm after mains loss | SHOULD | T |
| HW-66 | Polymer or ceramic capacitors on the low-voltage side; no general-purpose electrolytics | MUST | I |

## 8. Surge, earthing, antennas

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-80 | Class II SPD at the cabinet incomer (L-N, L-PE, N-PE, Up ≤ 1.5 kV) with a visible status flag | MUST | I |
| HW-81 | **Single-point earth** at a cabinet ground bar. Target ≤ 5 Ω, measured and recorded at installation | MUST | M |
| HW-82 | **One N-type bulkhead per radio**, each with an inline **coaxial GDT arrester** bonded to the ground bar with a strap **< 0.5 m** | MUST | I |
| HW-83 | Coax: RG-316 for runs ≤ 1 m inside the box; **LMR-240 minimum for runs > 2 m**; LMR-400 for masts | MUST | I |
| HW-84 | Antennas: 915 MHz rated, gain recorded for each radio. **EIRP = conducted power + antenna gain − cable loss ≤ 16 dBm**; the firmware sets conducted power from the recorded values | MUST | I |
| HW-85 | Antennas of the same box as far apart as practical, **vertical stacking preferred** (≥ 1 m target). Final spacing set by the isolation test (§11) | SHOULD | M |
| HW-86 | All outdoor connectors weatherproofed (self-amalgamating tape + vinyl) | MUST | I |

## 9. Enclosure and environment

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-90 | **IP66** (IP65 minimum), UV-stabilised polycarbonate/GRP or powder-coated metal; stainless or plated hardware | MUST | I |
| HW-91 | Pressure-equalising (Gore-type) vent; drain path at the bottom; PCB mounted vertically | MUST | I |
| HW-92 | Conformal coating (acrylic or urethane), with connectors and RF feeds masked | MUST | I |
| HW-93 | Designed for **70–75 °C internal, 80 °C worst case**: 105 °C parts, industrial-grade FRAM/NOR | MUST | I |
| HW-94 | Layout: RF on solid ground with via fence; RS485 isolation gap ≥ 5 mm creepage with nothing routed under the isolator; mains primary in its own corner | MUST | I |

## 10. Indicators, service access, labelling

| ID | Requirement | Level | Verify |
|---|---|---|---|
| HW-70 | LEDs visible without opening the enclosure (or through a window): **PWR**, **one per radio**, **FAULT**, and **RS485** (Master) | MUST | I |
| HW-71 | Console header (USART, 3.3 V TTL, 3-pin + GND) reachable without removing the PCB | MUST | I |
| HW-72 | SWD header (Tag-Connect or 10-pin Cortex debug) | MUST | I |
| HW-73 | Reset button and boot/service button, both reachable inside the enclosure | MUST | I |
| HW-74 | Label inside the door: unit type (Master/Slave), section number, hardware revision, MCU UID, LED meanings, antenna-to-radio map | MUST | I |
| HW-75 | Each antenna cable and bulkhead labelled with its radio (R1/R2 or U1/U2/D1/D2) | MUST | I |

## 11. In-box radio isolation measurement (mandatory)

Open question Q24: how badly does one radio transmitting deafen the other radios in the same box? The firmware assumes **any TX blinds every other radio in the box** and uses one TX scheduler per box. This test decides whether that rule can be relaxed.

**Setup.** One Slave build in its real enclosure, with the real antennas and coax. A separate test transmitter board 20–50 m away, sending fixed frames to D2 at a level 10 dB above D2's SF9 sensitivity (attenuator or distance).

**Procedure.**

1. With all in-box radios silent, record D2 packet error rate (PER) over 500 frames. Baseline.
2. Make U1 transmit continuously at its configured power, on tier-1 channel 0, while the test transmitter sends to D2 on a cell channel. Record D2 PER and RSSI.
3. Repeat with U1 on channel 13, and with D1 transmitting on the section's other cell channel.
4. Repeat for antenna spacings of 0.3 m, 0.6 m and 1 m, and vertical vs side by side.
5. Measure antenna-to-antenna coupling directly with a signal generator and spectrum analyser (or a second SX1276 reading RSSI) for each spacing.

**Decision.**

| Result | Consequence |
|---|---|
| D2 PER rises measurably (> 1% above baseline) in any configuration that will be built | **Keep the rule**: one TX scheduler per box, other radios blanked during any TX |
| D2 PER unchanged at the built spacing, for all channel combinations, with ≥ 10 dB margin (repeat at 10 dB weaker test signal) | Rule MAY be relaxed for the measured channel pairs only. Recorded as a change request against [04](04-channel-plan-and-airtime.md) |

Results are recorded in the specs repo with photos of the antenna arrangement.

## 12. Bench hardware set (needed from week 2, SOW assumption A7)

| Item | Qty | For |
|---|---|---|
| NUCLEO-L476RG | 3 (1 Master + 2 Slaves) | Gateway firmware |
| SX1276 915 MHz modules with antennas | 10 (2 + 4 + 4) | Gateway radios |
| SPI breakout for FRAM MB85RS256B + NOR W25Q64JV | 3 | Storage |
| Isolated USB-RS485 adapter + 3.3 V RS485 transceiver board for the Master | 1 + 1 | Modbus link |
| Server PC (client-supplied) | 1 | Monitoring server |
| ST-LINK (on-board on Nucleo) + spare ST-LINK/V2 | 1 | Device boards |
| From M4: device developer's boards — 1 energy meter + 6 LED devices | 7 | Integration |

## 13. Sign-off

| Party | Name | Signature | Date |
|---|---|---|---|
| Gateway hardware developer | | | |
| pgorospe | | | |

## Open items

| # | Item | Needed by |
|---|---|---|
| O-06-1 | ⚠ Verify every pin in §3 against UM1724 and the L476RG datasheet (alternate functions, SB defaults, LD2 on PA5, USB on PA11/PA12) | Before bench wiring (week 2) |
| O-06-2 | Exact radio module part: RFM95W-915 vs Ra-01H vs a TCXO variant; and whether its certification helps NTC type approval (Q10) | M1 sign-off |
| O-06-3 | In-box isolation measurement results (§11) | Before final board layout |
| O-06-4 | Cabinet type and location (pole-top vs ground cabinet) decide coax lengths and enclosure size | Hardware developer |
| O-06-5 | Earthing resistance achievable at the site | Survey |
| O-06-6 | ⚠ Mean Well IRM-10-5 surge immunity isn't published; confirm the staged protection is enough | Hardware developer |
