# LoRa Street Lighting — System Specifications

The interface contracts for the LoRa smart street lighting system. These documents are what the gateway hardware developer (who also decides technical matters for the client), the device developer and pgorospe agree on before and while the system is built. **They are milestone M1** of the project: the specifications are frozen once all parties have signed them.

## The specs

| # | Spec | What it fixes | Signed by | Version | Status |
|---|---|---|---|---|---|
| 00 | [Common frame format and conventions](specs/00-common-frame-and-conventions.md) | Byte order, units, addressing, the frame format and security layer used on both radio tiers | All | 0.1 | Draft |
| 01 | [Modbus register map](specs/01-modbus-register-map.md) + [CSV](register-map/register-map.csv) | Every register the Master exposes to the Server | Hardware developer (for the client) | 0.1 | Draft |
| 02 | [Tier-1 protocol](specs/02-tier1-protocol.md) | Master ↔ Slave Gateways radio protocol | Hardware developer (for the client) | 0.1 | Draft |
| 03 | [Tier-2 device protocol](specs/03-tier2-device-protocol.md) | Slave Gateway ↔ devices radio protocol, and what device firmware must do | **Device developer**, hardware developer (for the client) | 0.1 | Draft |
| 04 | [Channel plan and airtime budget](specs/04-channel-plan-and-airtime.md) | Frequencies, spreading factors, cycle timing, duty-cycle proof | Hardware developer (for the client) | 0.1 | Draft, provisional until NTC answers |
| 05 | [Fail-safe behaviour](specs/05-fail-safe-behaviour.md) | What the lights do in every failure case | **Hardware developer (for the client), device developer** | 0.1 | Draft |
| 06 | [Gateway hardware requirements](specs/06-gateway-hardware-requirements.md) | What the gateway hardware must provide | **Gateway hardware developer** | 0.1 | Draft |
| 07 | [Server data model and requirements](specs/07-server-data-model.md) | What the Local Monitoring Server stores, shows and controls | Hardware developer (for the client) | 0.1 | Draft |

Decisions made along the way are logged in [DECISIONS.md](DECISIONS.md).

**New here? Start with the [system guide](guide/system-guide.html)** (download it and open it in a browser): diagrams of how everything fits together, each pointing to the spec that holds the details.

## How review works

1. **Drafts are `0.x`.** Each review round gets a tag (`review-r1`, `review-r2`…) so everyone comments on the same text.
2. **Review window: 3 working days** per round.
3. **Comment with a GitHub issue**, one issue per question or problem, using the *Review comment* template. Say which spec and section. If you can't use GitHub, mark up the PDF or just send a message; it will be logged as an issue for you.
4. **One walkthrough call per round** (about 60 minutes) goes through the open issues and decides each one. The decision goes in [DECISIONS.md](DECISIONS.md) and the spec is updated.
5. Repeat until no blocking issues remain.

**Proposing text changes:** work on a branch (`git checkout -b <topic>`) and open a pull request. Don't push to `main` directly.

## How sign-off works

1. The spec set is tagged **`spec-v1.0`** and exported to PDF, each with a sign-off page.
2. Each signing party replies **"Approved spec-v1.0"** in writing (a message is fine), or signs the sign-off page of the specs they own (see the table above). The gateway hardware developer is the client's technical decision-maker and reviews and approves on the client's behalf. Non-technical client items (purchasing, the NTC letter, tariff questions) are passed to the client through them.
3. When every party has approved, M1 is complete.

## After sign-off: changes

A frozen spec changes only through a **change request**: a GitHub issue using the *Change request* template, stating what changes, why, and the effect on effort and schedule. It is approved in writing before the change is made, then released as `spec-v1.1`, `spec-v1.2`, and so on.

## Conventions

- **The register map is generated** from [`register-map/register-map.csv`](register-map/register-map.csv). Code and tables are produced from it, never typed by hand.
- **⚠** marks a claim that isn't verified yet. Each spec ends with its open items.
- Byte order: little-endian on the radio, big-endian (high word first) on Modbus.

## Exporting PDFs

```
python -m venv .venv
.venv\Scripts\pip install markdown
.venv\Scripts\python tools\build_pdf.py            # all specs → pdf/
```

The script uses an installed Chrome or Edge to print each spec, with a sign-off page, to `pdf/`.
