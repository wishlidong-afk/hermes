# Phase 10 Report - Soft Data Adapter Contracts

Date: 2026-06-01

## Scope

Phase 10 adds soft-data adapter contracts for:

- GEX
- SKEW/VVIX
- Net liquidity
- BTC microstructure

No external data is fabricated. When a source is disabled or not configured, it emits a dated missing record with source, reason, latency, proxy, and quality fields.

## Verification

- Default adapter names are stable.
- Missing records are explicit and do not return numeric zero.
- Adapter collection writes dated snapshots.
- Offline/no-network guard passes.
- CLI command added: `python3 -m hermes_escape_top.cli soft-data --as-of YYYY-MM-DD`.

## Status

BLOCKED-PENDING-DATA for live values. The contract and archival path are implemented; real provider credentials/API endpoints are still required for non-missing records.
