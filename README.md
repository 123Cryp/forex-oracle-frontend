![License](https://img.shields.io/badge/license-MIT-blue)
![GenLayer](https://img.shields.io/badge/GenLayer-genlayer--js-2CA6A4)
![Tests](https://img.shields.io/badge/tests-101%2F101%20passing-3FA66B)

# Cross-Rate Desk — a ForexCrossRateOracle dApp

A two-party, address-bound, deadline-gated, multi-source forex cross-rate
settlement Intelligent Contract for GenLayer, plus a minimal no-build-step
frontend that talks to it directly. Built from a clean slate for the forex
vertical — it borrows only proven *structural* patterns (the
fetch → LLM-extraction → deterministic-comparison pipeline,
`prompt_comparative` validator consensus) from a prior, unrelated
GenLayer project, and rebuilds every trust-sensitive control from scratch
specifically for two-party FX agreements.

**Live contract:** `0x63E42c828DBd622f157FaBD27C71392d49C98247` on GenLayer Studio
**Explorer:** https://explorer-studio.genlayer.com/address/0x63E42c828DBd622f157FaBD27C71392d49C98247
**Live frontend:** https://123cryp.github.io/forex-oracle-frontend/

---

## Repository layout

```
contract.py     the Intelligent Contract (GenLayer / GenVM, Python)
index.html      the entire frontend — HTML/CSS/JS, no build step
tests/          contract.py's offline test suite (101/101 passing)
README.md
```

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

`pytest` also works with these same files (they're written as plain
`unittest.TestCase` classes, which `pytest` auto-discovers) if you have it
installed; the command above uses the standard-library `unittest` runner
instead so the suite needs no installation step at all.

---

## The three security properties this was built around

The project brief asked for a trust model designed in from day one, not
retrofitted. Three properties anchor it:

### 1. Party binding
`party_a` and `party_b` are never free-text names. `party_a` is always
whoever calls `create_agreement` (`gl.message.sender_address`); `party_b`
is an on-chain address supplied at creation time, and that *exact* address
must itself call `accept_agreement` before the agreement becomes binding
(`status` moves from `pending_acceptance` to `open`). Both sides are
therefore cryptographically tied to real wallets that actually signed a
transaction — never to a string either side could have typed on behalf of
someone else.

### 2. Resolution timing / deadline
Every agreement carries a `resolution_deadline` (an ISO-8601 UTC
timestamp) fixed at creation time, at least 5 minutes and at most 365
days out. `resolve_agreement` cannot be called before that deadline (so
nobody can race to resolve at a moment that happens to favor one side),
and cannot be called after `resolution_deadline + 7 days` (so a stale,
forgotten agreement can never be resolved against a rate with no
relationship to the agreed moment). Once that window closes unresolved,
anyone can permissionlessly call `expire_agreement`.

### 3. Mandatory multi-source corroboration with explicit quorum rules
`required_source_domains` is **not optional** — every agreement must
commit at least 2 distinct, reputable, allowlisted FX data domains
(`xe.com`, `oanda.com`, `bloomberg.com`, `reuters.com`, and 12 others —
see `REPUTABLE_FX_DOMAINS` in `contract.py`) at creation time, and
`resolve_agreement` can only succeed once evidence from *all* of those
committed domains has been fetched, classified, and found to agree. A
single caller-chosen web page can never decide a settlement outcome.

On top of the domain allowlist, each source's evidence is also checked
for **pair/direction match** (a EUR/USD agreement rejects a USD/EUR quote
rather than silently inverting it) and **freshness** (a source not
presenting a current live rate is excluded), and the model's
self-reported Above/Below/Equal comparison is cross-checked against a
comparison computed deterministically in Python from the extracted rate —
any disagreement excludes that source rather than trusting either answer
blindly.

#### Quorum & Dissenting Sources Rule
- **2 sources (minimum):** Both must agree (both Above, both Below, or both Equal). 
  If they disagree (one Above, one Below) → `Indeterminate`, no winner.
- **3+ sources:** Majority vote wins. If 2 agree and 1 disagrees, the 1 is marked 
  as `is_dissenting: true` in the evidence record but does not prevent consensus.
- **Dissenting sources** are recorded in the full audit trail with 
  `is_dissenting: true` so both parties can see which sources disagreed and 
  potentially appeal or dispute the outcome offline based on methodology differences.

---

## What this is

A single static page (`index.html`, no build step, no framework) plus the
contract it calls, that lets a person:

1. **Create an agreement** — enter the counterparty's address, currency
   pair, threshold rate, comparison direction, description, resolution
   deadline, and required source domains, and submit `create_agreement`
   as a signed transaction. The caller automatically becomes `party_a`.
2. **Accept or cancel** — the counterparty calls `accept_agreement` to
   bind themselves as `party_b`; the creator can `cancel_agreement`
   instead, while it's still awaiting acceptance.
3. **Resolve an agreement** — once the deadline arrives, submit 2–6
   candidate source URLs and call `resolve_agreement`, which triggers the
   contract's real fetch → LLM-extraction → deterministic-comparison →
   validator-consensus pipeline on GenLayer Studio.
4. **Expire a lapsed agreement** — permissionlessly, once its deadline (or
   resolution window) has passed without acceptance/resolution.
5. **Read an agreement** — call the read-only `get_agreement` method and
   see the full evidence trail (per-source domain, fetch status, quality
   flag, comparison) rendered as a readable list, plus the final verdict
   and winner.

All actions call the deployed contract directly through
[`genlayer-js`](https://github.com/genlayerlabs/genlayer-js), the
official GenLayer JavaScript SDK — there is no backend server in between.
Read calls use an unauthenticated read client. For write calls, the page
supports **both**:

- **MetaMask** — click "connect MetaMask." Requires MetaMask (or another
  injected-provider wallet) installed.
- **Test session** — click "start test session" instead. This generates a
  fresh, throwaway keypair in the browser using `genlayer-js`'s own
  `createAccount()`, with no external wallet setup required. It holds no
  real value, isn't saved anywhere, and resets on page reload.

## DOM-safe frontend

Every dynamic value `index.html` renders — party addresses, descriptions,
domains, URLs, quality flags, the raw contract JSON — is written using
only `document.createElement` and `.textContent`. `innerHTML` is never
used anywhere in the file, so nothing returned from the contract or
fetched off-chain can ever be interpreted as HTML/script by the page,
even if a malicious value somehow made it into contract storage.

## Running it

No build step.

```bash
python3 -m http.server 8000
# then open http://localhost:8000
```

(Opening `index.html` directly via `file://` can fail in some browsers,
since they restrict ES module imports from the local filesystem — hence
the static server above. The live version is also hosted for free via
GitHub Pages: https://123cryp.github.io/forex-oracle-frontend/)

## How it talks to GenLayer

```js
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

This page loads `genlayer-js` from a CDN (`esm.sh`) as an ES module, so it
needs no `npm install` or bundler to run.

---

## Testing

### Offline unit/integration tests (101/101 passing)

```
tests/
├── _bootstrap.py                          shared contract loader + offline SDK stub
├── genlayer_stub/genlayer/__init__.py     minimal offline stand-in for the genlayer SDK
├── test_domain_and_rate_parsing.py        35 tests — domain/path/rate/timestamp parsing
├── test_aggregation.py                    11 tests — multi-source verdict aggregation
├── test_party_binding_and_timing.py       38 tests — party binding, state machine, deadlines
└── test_end_to_end.py                     17 tests — full resolve_agreement pipeline, web/LLM mocked
```

Run with:
```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

The `genlayer_stub` package reproduces just enough of the real GenLayer
SDK's surface (`gl.Contract`, `gl.public`, `gl.vm.UserError`,
`gl.message.sender_address`, `TreeMap`/`u256`/`Address`) to import and
exercise `contract.py`'s deterministic logic in plain Python, with
`gl.nondet.web.render` / `gl.nondet.exec_prompt` mocked per test case to
simulate specific fetch/LLM outcomes (agreement, pair mismatch, stale
data, unparseable rate, model self-report disagreeing with the
deterministic comparison, fetch timeouts, and more). It intentionally
does **not** simulate real network access, real LLM behavior, or actual
multi-validator consensus — those require the live GenLayer Studio or
testnet, which is what the manual testing below covers.

### Live end-to-end tests on GenLayer Studio

Every method was also exercised against the real, deployed contract on
GenLayer Studio, with real validator consensus (typically 3–5 validators
per transaction, using a mix of hosted models), confirming the offline
test assumptions hold on the actual network:

| Test | Result |
|---|---|
| Deploy | ✅ FINALIZED |
| `create_agreement` (valid inputs) | ✅ agreement created |
| `accept_agreement` called by `party_a` (should be rejected) | ✅ rejected — *"Only the address designated as party_b..."* |
| `accept_agreement` called by `party_b` | ✅ `status` → `open` |
| `resolve_agreement` before `resolution_deadline` (should be rejected) | ✅ rejected — *"...has not been reached yet"* |
| `resolve_agreement` after deadline, two agreeing sources | ✅ `status` → `resolved`, correct `winner` |
| `cancel_agreement` by `party_a` before acceptance | ✅ `status` → `cancelled` |
| `expire_agreement` before deadline (should be rejected) | ✅ rejected |
| `expire_agreement` after deadline, never accepted | ✅ `status` → `expired` |
| Frontend: connect via test session, `create_agreement` | ✅ tx finalized, ID auto-filled into other panels |
| Frontend: `get_agreement` read + DOM-safe render (fields, status badge, evidence list) | ✅ rendered correctly |
| Frontend: `get_role`, `total_agreements` | ✅ correct values |

**Not exercised live from the frontend UI:** a same-browser, two-tab
`accept_agreement`/`cancel_agreement` round trip. Mobile browsers
routinely reclaim memory from backgrounded tabs by reloading them, and
since a "test session" wallet lives only in that page load's JavaScript
memory, a background reload silently discards it — this is a mobile
browser memory-management behavior, not a defect in the contract or
frontend. The underlying logic this would have exercised (party binding
enforcement on `accept_agreement`/`cancel_agreement`) was already
confirmed both on live GenLayer Studio (table above) and in the offline
suite (`test_party_binding_and_timing.py`).

---

## Known limitations (disclosed intentionally, not hidden)

- **No fund movement.** This contract produces an authoritative,
  auditable settlement *decision* (`winner`) — it does not itself hold or
  transfer value. Wiring a `winner` value up to an actual payout is left
  to a separate escrow layer, deliberately kept out of scope for a first
  version of a two-party trust primitive.
- **`RATE_EPSILON` is one fixed tolerance for every pair** (`0.0001`,
  roughly one pip for most non-JPY pairs). JPY crosses are conventionally
  quoted to 2 decimal places, so this tolerance is tighter than their
  usual quoting precision — deliberately conservative (it will rarely
  call a genuinely different rate "Equal"), not a bug. See the
  `RATE_EPSILON` comment in `contract.py` for the full rationale.
- **No backend, database, or indexer.** Every read comes straight from
  `get_agreement` on-chain; there is no caching layer.
- **No private key management.** The frontend only requests
  `eth_requestAccounts` from whatever provider is already injected, or
  generates a throwaway `genlayer-js` test account — it never stores or
  transmits a private key anywhere.

## License

MIT — see `LICENSE`.
