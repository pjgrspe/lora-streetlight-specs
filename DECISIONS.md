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

"Proposal" means put forward in a draft and still open for review. It becomes agreed when the relevant parties sign the spec.
