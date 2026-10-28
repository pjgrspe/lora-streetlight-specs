# Decision Log

One line per decision: what was decided, when, and who agreed. Newest at the bottom. A decision is only final when it is here.

| # | Date | Decision | Agreed by | Spec |
|---|---|---|---|---|
| D-001 | 2026-10-20 | Specs live in this repo, reviewed through GitHub issues, signed off on tag `spec-v1.0` | pgorospe | README |
| D-002 | 2026-10-20 | Radio frames are little-endian; Modbus 32-bit values are high word first | pgorospe (proposal) | 00, 01 |
| D-003 | 2026-10-20 | 12-bit address `GwID:4 | NodeID:8` inside an 8-bit site NetID; up to 14 sections, up to 63 NodeIDs per section in v1 | pgorospe (proposal) | 00 |
| D-004 | 2026-10-20 | Frame header is 8 bytes plus a 4-byte MIC (12 bytes of overhead). No length or header-CRC field: the LoRa PHY header and CRC cover them | pgorospe (proposal) | 00 |
| D-005 | 2026-10-20 | Per-device keys derived from a site key held only by gateways; full key management is outside the current scope | pgorospe (proposal) | 00 |
| D-006 | 2026-10-20 | 14 channels on a 200 kHz raster (915.2–917.8 MHz). Tier 1 on ch 0 + ch 13; section n on ch n + ch n+6 | pgorospe (proposal) | 04 |
| D-007 | 2026-10-20 | Default cycle 120 s on both tiers. 60 s does not fit a per-box 1% duty cycle (needs ~112%); possible only if NTC allows one budget per radio | pgorospe (proposal) | 04 |
| D-008 | 2026-10-20 | Tier 1 at SF7 (SF8 allowed), cells at SF9. SF10+ not used in v1 | pgorospe (proposal) | 04 |
| D-009 | 2026-10-20 | Routine device reports are not acknowledged (they are snapshots); events are acknowledged through the beacon's event-ACK bitmap | pgorospe (proposal) | 03, 04 |
| D-010 | 2026-10-20 | Light levels are DALI arc levels (0–254) on the radio and in Modbus; the server converts to percent | pgorospe (proposal) | 00, 01 |
| D-011 | 2026-10-21 | P0 copies (both radios + 1 s repeat) reuse the same frame counter so receivers deduplicate them; all other retransmissions take a new counter | pgorospe (proposal) | 00, 02 |
| D-012 | 2026-10-21 | Beacons (both tiers) and the tier-1 heartbeat are MIC'd but not encrypted, so unjoined nodes can read timing | pgorospe (proposal) | 00, 02, 03 |
| D-013 | 2026-10-21 | Single-channel mode: the slave shifts its own cell cycle 10 s earlier; the Master's slot plan never moves | pgorospe (proposal) | 02, 04 |
| D-014 | 2026-10-21 | One system-wide command result-code table (02 §11.5) used by tier-1 and tier-2 CMD_ACK and the Modbus job result | pgorospe (proposal) | 01, 02, 03 |
| D-015 | 2026-10-21 | Event code ranges: slave 0x01–0x3F (02), device 0x40–0x7F (03), Master 0x8000+ (01). Spec 07 §6 is the single server alarm catalogue; severity 0 info · 1 warning · 2 alarm · 3 critical everywhere | pgorospe (proposal) | 01, 02, 03, 05, 07 |
| D-016 | 2026-10-21 | Modbus addresses are 0-based protocol addresses in hex; a server reads whole device blocks, ≤7 per request (9 requests per 60-device section) | pgorospe (proposal) | 01, 07 |
| D-017 | 2026-10-21 | The gateway hardware developer decides technical matters for the client: reviews and signs the specs in the client's place. Written approval by message counts | pgorospe | README, all |
| D-018 | 2026-10-21 | Spec 00 clarified from the reference implementation: key-derivation inputs are single zero-padded 16-byte blocks with little-endian nonces; FCNT32 rebuild checks the duplicate window first, and the window updates only after the MIC verifies | pgorospe (proposal) | 00 |
| D-019 | 2026-10-21 | Fixes found while coding the message formats: the slave HEARTBEAT is MIC-only like every HEARTBEAT (02 §12.1, matches 00 §6.4); a WHITELIST frame holds at most 15 entries at SF7, not 16 (02 §8.1) | pgorospe (proposal) | 02 |
| D-020 | 2026-10-21 | REJOIN_REQ is MIC-only like JOIN_REQ (00 §6.4 now lists it, matching 03 §5); found by the cell simulator | pgorospe (proposal) | 00 |
| D-021 | 2026-10-21 | Single-channel mode detection and failback: a downstream radio silent for 2 cycles (while its devices should report and the other radio hears its own) is declared failed; the slave keeps beaconing on it as a probe, moved devices report on their home channel once per 10 cycles, and the first frame heard on the failed radio ends single-channel mode. Shown working in the cell simulator | pgorospe (proposal) | 02, 03 |
| D-022 | 2026-10-21 | JOIN_ACC carries milliseconds on both tiers (`utc_ms`; device JOIN_ACC 41 B, tier-1 32 B), so clocks are right from the join; found when a just-rejoined device switched 355 ms late | pgorospe (proposal) | 02, 03 |
| D-023 | 2026-10-21 | A device transmits only in a cycle whose beacon it received; a slave ignores radio silence for 5 cycles after leaving single-channel mode; a slave can take the Master's timing from the HEARTBEAT. All found in the full-system simulation | pgorospe (proposal) | 02, 03 |
| D-024 | 2026-10-21 | Master failback: after at least 5 cycles on the standby, fail back once the primary has heard slave frames in 2 cycles (slave heartbeats reach it only every 5th cycle, so 5 clean consecutive cycles can never happen) | pgorospe (proposal) | 02 |

"Proposal" means put forward in a draft and still open for review. It becomes agreed when the relevant parties sign the spec.

## Open ideas and issues (not decided)

Written down so they aren't lost. None of these is in a spec yet.

| # | Date | Idea or issue | Next step | Spec |
|---|---|---|---|---|
| I-001 | 2026-10-25 | **Faster recovery when a slave's downstream antenna fails.** Measured in the simulator: for about 4½ min after the cut, the devices on the dead channel (about half the section) miss commands; after that they move over by themselves and all respond. Idea: a device that misses a single beacon listens on its section's other channel for the rest of that cycle. Group commands already go out on both channels, so the gap would drop below one cycle with no extra airtime. Cost: about 1 cycle in 100 a device hops because of ordinary noise, and a unicast sent on its home channel in that cycle waits for the next retry. | First, the server automatically resends to the targets that didn't confirm (fail mask), a few minutes later. That covers every cause of a missed command (M5). Revisit this idea only if the gap still matters after that | 03, 07 |
| I-002 | 2026-10-25 | **Single-channel mode: the downlink window overlaps uplink slots.** With one channel lost, uplink slots run back to back to 20.8 s, but the downlink window still starts at 16 s, so a JOIN_ACC can collide with device reports (seen in the simulator, seed 19). The downlink window probably needs to start after the moved quiet window | Propose a fix to 04 §6.2 before sign-off | 04 |
