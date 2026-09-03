# Cross-Rate Desk — a ForexCrossRateOracle dApp

A two-party, address-bound, deadline-gated, multi-source forex cross-rate settlement Intelligent Contract for GenLayer, plus a minimal no-build-step frontend that talks to it directly. Built from a clean slate for the forex vertical — it borrows only proven structural patterns (the fetch → LLM-extraction → deterministic-comparison pipeline, prompt_comparative validator consensus) from a prior, unrelated GenLayer project, and rebuilds every trust-sensitive control from scratch specifically for two-party FX agreements.

**Live contract:** `0x63E42c828DBd622f157FaBD27C71392d49C98247` on GenLayer Studio  
**Explorer:** https://explorer-studio.genlayer.com/address/0x63E42c828DBd622f157FaBD27C71392d49C98247  
**Live frontend:** https://123cryp.github.io/forex-oracle-frontend/

## Repository layout

- `contract.py` — the Intelligent Contract (GenLayer / GenVM, Python)
- `index.html` — the entire frontend — HTML/CSS/JS, no build step
- `tests/` — contract.py's offline test suite (129/129 passing)
- `README.md`

Run tests with:
```
python3 -m unittest discover -s tests -p "test_*.py" -v
```

(pytest also works with these same files; they're written as plain `unittest.TestCase` classes, which pytest auto-discovers.)

## The three security properties this was built around

The project brief asked for a trust model designed in from day one, not retrofitted. Three properties anchor it:

### 1. Party binding
`party_a` and `party_b` are never free-text names. `party_a` is always whoever calls `create_agreement` (`gl.message.sender_address`); `party_b` is an on-chain address supplied at creation time, and that *exact* address must itself call `accept_agreement` before the agreement becomes binding (`status` moves from `pending_acceptance` to `open`). Both sides are therefore cryptographically tied to real wallets that actually signed a transaction — never to a string either side could have typed on behalf of someone else.

### 2. Resolution timing / deadline & timestamped rate verification
Every agreement carries a `resolution_deadline` (an ISO-8601 UTC timestamp) fixed at creation time, at least 5 minutes and at most 365 days out. `resolve_agreement` cannot be called before that deadline (so nobody can race to resolve at a moment that happens to favor one side), and cannot be called after `resolution_deadline + 7 days` (so a stale, forgotten agreement can never be resolved against a rate with no relationship to the agreed moment). Once that window closes unresolved, anyone can permissionlessly call `expire_agreement`.

**Timestamped Rate Verification:** Every source must provide a `TIMESTAMP` (ISO-8601 UTC) alongside its rate. The contract verifies that the timestamp falls within the valid window **relative to the agreed deadline**:
- Rate timestamp must be >= `resolution_deadline - 24 hours`
- Rate timestamp must be <= `resolution_deadline`

This ensures settlement is based on rates actually relevant to the agreed moment. A rate with a timestamp outside this window is automatically flagged as `quality_flag: "timestamp_invalid_or_stale"` and excluded from consensus.

The production extraction prompt built by `_build_prompt` (the exact text sent to `gl.nondet.exec_prompt` inside `resolve_agreement`) explicitly requires the model to answer a fifth field, `TIMESTAMP`, in strict ISO-8601 UTC, alongside `PAIR`, `FRESHNESS`, `RATE`, and `COMPARISON` — it is not enough for the validation logic to exist if the model is never asked for a timestamp in the first place. `tests/test_end_to_end.py::ProductionPromptContractEndToEndTests` asserts directly against the real prompt text (not a hand-written mock reply in isolation) that `TIMESTAMP` is requested, then exercises the full pipeline with the exact five-line `PAIR/FRESHNESS/RATE/TIMESTAMP/COMPARISON` output contract to prove two fresh, agreeing sources reach quorum and produce a concrete winner, and that a source which genuinely omits a timestamp is flagged with the same `timestamp_invalid_or_stale` value declared in `QUALITY_FLAGS` and excluded from quorum.

### 3. Mandatory multi-source corroboration with fully locked voting source set
`required_source_domains` is **not optional** and is **locked at creation** — every agreement must commit at least 2 distinct, reputable, allowlisted FX data domains at creation time. **The voting source set is fully locked:** at resolution time, submitted source URLs must match exactly the committed domains. No additional domains beyond the committed set may participate in voting.

The contract enforces this strict policy: if extra domains are submitted, resolution fails with a clear error. If any required domain is missing, resolution fails. This locks the voting set completely — both parties agreed upfront on exactly who decides the settlement, and no surprise voters can change the outcome.

On top of domain locking, each source's evidence is also checked for **pair/direction match** (a EUR/USD agreement rejects a USD/EUR quote) and **freshness** (stale data is excluded), and the model's self-reported comparison is cross-checked against a comparison computed deterministically in Python — any disagreement excludes that source.

#### Quorum & Dissenting Sources Rule
- **2 sources (minimum):** Both must agree (both Above, both Below, or both Equal). If they disagree → `Indeterminate`, no winner.
- **3+ sources:** Majority vote wins. Dissenting (minority) sources are flagged with `is_dissenting: true` in evidence records so both parties can see the breakdown and understand the settlement basis.

---

## What this is

A single static page (`index.html`, no build step, no framework) plus the contract it calls, that lets a person:

1. **Create an agreement** — enter counterparty address, currency pair, threshold rate, comparison direction, description, resolution deadline, and required source domains, and submit `create_agreement`. The caller automatically becomes `party_a`.
2. **Accept or cancel** — the counterparty calls `accept_agreement` to bind themselves as `party_b`; creator can `cancel_agreement` before acceptance.
3. **Resolve an agreement** — once the deadline arrives, submit 2–6 candidate source URLs and call `resolve_agreement`, which triggers the contract's real fetch → LLM-extraction → deterministic-comparison → validator-consensus pipeline.
4. **Expire a lapsed agreement** — permissionlessly, once its deadline or resolution window has closed.
5. **Read an agreement** — call `get_agreement` and see the full evidence trail rendered as a readable list, plus the final verdict and winner.

All actions call the deployed contract directly through [`genlayer-js`](https://github.com/genlayerlabs/genlayer-js) — no backend server. Read calls use an unauthenticated client. Write calls support:

- **MetaMask** — click "connect MetaMask." Requires MetaMask or another injected-provider wallet.
- **Test session** — click "start test session." Generates a fresh, throwaway keypair in the browser, holds no real value, resets on reload.

## DOM-safe frontend

Every dynamic value `index.html` renders — party addresses, descriptions, domains, URLs, quality flags, raw contract JSON — is written using only `document.createElement` and `.textContent`. `innerHTML` is never used anywhere, so nothing returned from the contract or fetched off-chain can ever be interpreted as HTML/script by the page.

## Running it

No build step.

```
python3 -m http.server 8000
# then open http://localhost:8000
```

(Opening `index.html` directly via `file://` can fail in some browsers due to ES module restrictions — hence the static server. The live version is hosted on GitHub Pages: https://123cryp.github.io/forex-oracle-frontend/)

## How it talks to GenLayer

```javascript
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

// Read-only (no wallet needed)
const readClient = createClient({ chain: studionet });
const agreement = await readClient.readContract({
  address: CONTRACT_ADDRESS,
  functionName: "get_agreement",
  args: [agreementId],
});

// Write, via MetaMask
const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
const client = createClient({ chain: studionet, account: accounts[0] });

// Write, via a throwaway in-browser test account (no wallet needed)
const testAccount = createAccount();
const client2 = createClient({ chain: studionet, account: testAccount });

const txHash = await client.writeContract({
  address: CONTRACT_ADDRESS,
  functionName: "create_agreement",
  args: [partyB, pair, threshold, comparison, description, deadlineIso, requiredDomains],
});
await client.waitForTransactionReceipt({ hash: txHash, status: "FINALIZED" });
```

This page loads `genlayer-js` from a CDN, so it needs no npm install or bundler.

## Testing

### Offline unit/integration tests (129/129 passing)

```
tests/
├── _bootstrap.py                          shared contract loader + offline SDK stub
├── genlayer_stub/genlayer/__init__.py     minimal offline stand-in for the genlayer SDK
├── test_domain_and_rate_parsing.py        35 tests — domain/path/rate/timestamp parsing
├── test_aggregation.py                    11 tests — multi-source verdict aggregation
├── test_party_binding_and_timing.py       38 tests — party binding, state machine, deadlines
├── test_quorum_and_dissenting.py          15 tests — quorum scenarios and dissenting source tracking
├── test_timestamp_verification.py         10 tests — timestamped rate validation
└── test_end_to_end.py                     20 tests — full resolve pipeline (17 base + 3 production-prompt-contract regression tests, incl. the exact 5-field PAIR/FRESHNESS/RATE/TIMESTAMP/COMPARISON output the real prompt requires)
```

Run with:
```
python3 -m unittest discover -s tests -p "test_*.py" -v
```

The `genlayer_stub` reproduces just enough of the real GenLayer SDK (gl.Contract, gl.public, gl.vm.UserError, gl.message.sender_address, TreeMap/u256/Address) to import and exercise contract.py's deterministic logic in plain Python, with `gl.nondet.web.render` / `gl.nondet.exec_prompt` mocked per test case. It does not simulate real network access, real LLM behavior, or actual multi-validator consensus — those require the live GenLayer Studio.

### Live end-to-end tests on GenLayer Studio

Every method was exercised against the real, deployed contract on GenLayer Studio, with real validator consensus, confirming offline test assumptions hold on the actual network:

| Test | Result |
|---|---|
| Deploy | ✅ FINALIZED |
| create_agreement (valid inputs) | ✅ agreement created |
| accept_agreement by party_a (should reject) | ✅ rejected — "Only the address designated as party_b..." |
| accept_agreement by party_b | ✅ status → open |
| resolve_agreement before deadline (should reject) | ✅ rejected — "...has not been reached yet" |
| resolve_agreement after deadline, valid sources | ✅ status → resolved, correct winner |
| resolve_agreement with extra sources beyond committed set | ✅ rejected — "voting source set is locked" |
| cancel_agreement by party_a before acceptance | ✅ status → cancelled |
| expire_agreement before deadline (should reject) | ✅ rejected |
| expire_agreement after deadline, never accepted | ✅ status → expired |
| Frontend: connect via test session, create_agreement | ✅ tx finalized (agreement ID 5), confirmed on v1.3.0 |
| Frontend: get_agreement read + DOM-safe render | ✅ rendered correctly — full JSON + fields verified on v1.3.0 |
| Frontend: get_role, total_agreements | ✅ get_role returned "party_b" correctly; total_agreements returned accurate count, verified on v1.3.0 |

Not exercised live from the frontend UI: a same-browser, two-tab accept_agreement/cancel_agreement round trip. Mobile browsers routinely reclaim memory from backgrounded tabs by reloading them, and since a "test session" wallet lives only in that page load's JavaScript memory, a background reload silently discards it — this is a mobile browser memory-management behavior, not a defect in the contract or frontend. The underlying logic was already confirmed both on live GenLayer Studio (table above) and in the offline suite.

## Known limitations (disclosed intentionally, not hidden)

- **No fund movement.** This contract produces a settlement decision — it does not hold or transfer value. Wiring a winner payout up to an actual escrow is left to a separate layer.
- **RATE_EPSILON is one fixed tolerance for every pair** (0.0001, roughly one pip for most non-JPY pairs). JPY crosses are conventionally quoted to 2 decimal places, so this tolerance is tighter than their usual quoting precision — deliberately conservative (it will rarely call a genuinely different rate "Equal"), not a bug.
- **No backend, database, or indexer.** Every read comes straight from `get_agreement` on-chain; there is no caching layer.
- **No private key management.** The frontend only requests `eth_requestAccounts` from injected providers, or generates a throwaway `genlayer-js` test account — it never stores or transmits a private key.

## License

MIT — see LICENSE.
