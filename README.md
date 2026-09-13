# MatchGuard

**Adversarial Sports Event Settlement Intelligent Contract**, built for
[GenLayer](https://genlayer.com).

MatchGuard is a two-party settlement contract that doesn't just ask
*"what was the final score?"* - it settles the full, adversarial STATE
of a sports event (did it even happen? was it postponed, cancelled,
abandoned? do sources agree on the result?) and turns that into a
safe, always-terminal outcome: `party_a_wins`, `party_b_wins`, or
`refund`. It combines canonical event binding, a locked multi-source
evidence set, optimistic (challengeable) resolution, an immutable
versioned history, and deterministic timeout recovery so that a match
can never get permanently stuck.

MatchGuard is a clean-room design, not a fork of any prior project. It
reuses only proven, sport-agnostic URL/domain-parsing utilities from a
sibling GenLayer project, and one specific control - **locking the
voting source set only after real evidence, never on the literal
first call** - was rebuilt here from a documented reviewer finding on
that project (see the class docstring in `contract.py` for the full
account). Every other trust-sensitive control was designed from
scratch for adversarial, multi-state event settlement.

## Repository layout

```
matchguard-dapp/
├── contract.py              # The GenLayer intelligent contract
├── index.html                # Standalone reference frontend (genlayer-js)
├── README.md
├── LICENSE
└── tests/
    ├── _bootstrap.py                        # Shared test setup
    ├── genlayer_stub/genlayer/__init__.py   # Offline SDK stub (test-only)
    ├── test_party_binding_and_timing.py
    ├── test_domain_and_content_parsing.py
    ├── test_aggregation.py
    └── test_end_to_end.py
```

## The eight pillars this was built around

### 1. Canonical event identity
A match is never identified by a free-text team name alone.
`sport`, `competition`, `home_team`, `away_team`, and
`scheduled_start` are fixed, validated fields at creation time, and
every piece of fetched evidence must pass an `EVENT_MATCH` check
confirming it actually covers this exact fixture - not a different
meeting between the same two teams on a different date, and not a
different fixture entirely.

### 2. Locked source set, locked only after real evidence
`locked_source_urls` is set only once a `propose_resolution` (or
`challenge_resolution`) attempt actually clears the evidence-quality
bar (`MIN_INDEPENDENT_SOURCES` independent, reputable, on-fixture,
recognized-status sources) - never on the literal first call. An
attempt that fails to clear the bar leaves the match `open`, fully
retryable by anyone with different URLs, right up until the
resolution window closes. The same staged-locking discipline is
applied a second time to challenges: a challenge that doesn't move
the verdict never grows the locked evidence set either.

### 3. Multi-source semantic consensus over a rich state space
`_aggregate_verdict` runs a two-stage strict-majority rule:

1. **Status stage** - among eligible sources, the winning STATUS
   category (`Final` / `Postponed` / `Cancelled` / `Abandoned`) must
   have at least `MIN_INDEPENDENT_SOURCES` votes and strictly
   outnumber every other status category. No such category →
   `Disputed` (sources disagree about the event's status itself).
2. **Result stage** (only if the status stage resolved to `Final`) -
   the winning RESULT category (`HomeWin` / `AwayWin` / `Draw`) must
   equally strictly outnumber the others. No such category →
   `Disputed` (sources agree the match finished but disagree on the
   result).

Fewer than `MIN_INDEPENDENT_SOURCES` eligible sources at all →
`Indeterminate`. A lone dissenting source can prevent a false
majority elsewhere, but can never itself produce a verdict - see
`tests/test_aggregation.py` for explicit scenarios (a lone dissenter,
a status-level tie, a result-level tie, a postponed majority, etc).

### 4. Two-phase (optimistic) resolution
`propose_resolution` posts a verdict - even a decisive one - as
**provisional**, opening a `CHALLENGE_WINDOW_SECONDS` window before
anything is final. This protects against a single early resolver
being wrong without forcing every routine, undisputed result through
a slow multi-round dispute process.

### 5. Evidence-based challenge
`challenge_resolution` cannot register a bare objection. It requires
a concrete `source_url`, is restricted to the match's two bound
parties, and only changes anything if re-running the full consensus
pipeline over the union of the locked evidence and the new source
actually produces a different verdict. It is bounded to
`MAX_CHALLENGE_ROUNDS` total attempts per match - a liveness bound,
not a trust boundary (the very first proposal already goes through
one full challenge window even when never challenged).

### 6. Result versioning / immutable resolution history
`resolution_history` is append-only: every proposal, every challenge
(accepted **or** rejected), and the final finalization are each
logged as their own timestamped, versioned entry. Nothing already
appended is ever edited or removed - a later correction is a new
entry, never a silent rewrite.

### 7. Three-way, always-terminal settlement
`settlement_outcome` is only ever `party_a_wins`, `party_b_wins`, or
`refund` once finalized. A Draw, a Postponed/Cancelled/Abandoned
event, and a Disputed or Indeterminate verdict all deterministically
map to `refund` - there is no open-ended "unresolved" state for a
downstream escrow layer to be stuck holding.

### 8. Timeout recovery / source-failure handling - no permanent fund lock
Every path through the state machine has a permissionless,
time-bounded exit:

| State | Stuck condition | Recovery |
|---|---|---|
| `pending_acceptance` | party_b never accepts | `expire_match` once `scheduled_start` passes → `expired` |
| `open` | no quality-clearing proposal ever lands | `expire_match` once `resolution_window_closes_at` passes → `expired` |
| `proposed` | verdict stuck on Disputed/Indeterminate, or simply never challenged | `finalize_match`, permissionless, as soon as `challenge_deadline` passes → `finalized` with a deterministic `settlement_outcome` (always `refund` for non-decisive verdicts) |

A single unreachable, unreputable, off-fixture, or malformed source is
simply excluded from the eligible set; as long as
`MIN_INDEPENDENT_SOURCES` *other* sources clear the bar, resolution
proceeds normally around the failure.

## How resolution works, end to end

```
create_match (party_a)
      │
      ▼
accept_match (party_b)            [before scheduled_start]
      │
      ▼
      open  ──────────────────────────────────────────────┐
      │  propose_resolution (anyone, after resolution_     │  resolution_window_closes_at
      │  deadline, before window closes)                   │  passes with no quality-
      │                                                     │  clearing proposal
      ├─ independent_source_count < MIN_INDEPENDENT_SOURCES │
      │   → stays "open", nothing locked, fully retryable   │
      │                                                     ▼
      └─ clears the bar → locks source set, "proposed"   expire_match → expired
                  │
                  ▼
              proposed ⇄ challenge_resolution (party_a/party_b only,
                  │        before challenge_deadline, ≤ MAX_CHALLENGE_ROUNDS)
                  │        re-runs full consensus over locked ∪ {new source};
                  │        verdict changed → accepted, locked set grows,
                  │        version++, deadline resets; unchanged → rejected,
                  │        nothing grows, round consumed either way
                  │
                  ▼  challenge_deadline passes
            finalize_match (permissionless)
                  │
                  ▼
              finalized: final_verdict + settlement_outcome frozen forever
```

## Comparison with a score-only oracle

| | Score-only oracle | MatchGuard |
|---|---|---|
| Settles | Final score vs. a threshold | Full event state (Final/Postponed/Cancelled/Abandoned/Disputed/Indeterminate) |
| Evidence | Multi-source | Multi-source, canonical-event-bound |
| Party binding | Address-bound | Address-bound + canonical event binding |
| Resolution timing | One deadline + window | Proposal window + independent challenge window |
| Consensus | Single-pass majority | Two-stage strict majority (status, then result) |
| Result record | Final value | Versioned, immutable, append-only history |
| Settlement | Win / Lose | Win / Lose / Refund - always terminal |
| Source validation | Domain allowlist | Domain allowlist + canonical event identity |
| Dispute handling | — | Evidence-based challenge mechanism |
| Stuck-fund protection | Expiry window | Expiry window **and** permissionless finalize on every proposed match |

## v1 scope

- Settlement market is a straight moneyline on `side_a` ("home" or
  "away") plus a built-in Draw outcome that always refunds.
  Handicap/spread markets are out of v1 scope, for the same reason a
  sibling project excluded margin-of-victory markets: folding a
  second settlement metric into one prompt/parsing pipeline doubles
  the surface area for subtle validator disagreement in a first
  version.
- This contract produces an authoritative, auditable, **versioned**
  settlement decision. It does not itself move funds - actual value
  transfer is intentionally left to a separate escrow/payout layer
  that consumes `get_match`'s `settlement_outcome`.
- `REPUTABLE_SPORTS_DOMAINS` is a bare-registrable-domain allowlist;
  a specific section of a domain can still be pinned down via the
  optional `domain/path` form in `required_source_domains` (see
  `_parse_endpoint_requirement`).

## Frontend

`index.html` is a single-file, dependency-free (besides
`genlayer-js` from a CDN) reference frontend: create a match, accept
it as party_b, propose a resolution, challenge it, finalize it, or
read any match's full state and resolution history. Every dynamic
value is rendered via `textContent`/`createElement`, never
`innerHTML`, so nothing in contract storage can ever be interpreted
as markup. Set `CONTRACT_ADDRESS` near the top of the `<script>` block
to your deployed instance before using it.

## Test suite

Offline, fully deterministic unit + integration tests using a minimal
stub of the `genlayer` SDK (`tests/genlayer_stub/`) - no real network,
LLM, or multi-validator consensus involved; those are exercised
against the live GenLayer Studio/testnet separately.

```bash
pip install pytest
cd matchguard-dapp
pytest tests/ -v
```

Coverage includes: party binding and every timing boundary; canonical
event identity and required-domain coverage checks; URL/domain
parsing and content classification; the two-stage aggregation logic
(lone dissenters, status-level ties, result-level ties, postponed/
cancelled majorities); the full propose → challenge → finalize
lifecycle (including a challenge that resolves an initially Disputed
proposal into a clear verdict, and a second challenge that reopens it
into Disputed again); the `MAX_CHALLENGE_ROUNDS` liveness bound; and
every timeout-recovery path (never-proposed expiry, and an
Indeterminate proposal that still finalizes safely to `refund`).

## Deploying

Deploy `contract.py` through GenLayer Studio or the GenLayer CLI to a
GenLayer network exactly as any other `gl.Contract`. No constructor
arguments are required (`__init__` only zeroes the match counter).
After deployment, update `CONTRACT_ADDRESS` in `index.html` to point
at it.

## Known limitations (disclosed, not hidden)

- `MAX_CHALLENGE_ROUNDS` bounds worst-case dispute latency at a small,
  fixed number of rounds; a truly protracted real-world dispute
  (conflicting official corrections issued days apart, for example)
  is out of scope for v1's single-match challenge window.
- A challenge can only add ONE new source per call; flipping a
  verdict that needs several additional corroborating sources at once
  requires several successive challenge calls, still bounded by
  `MAX_CHALLENGE_ROUNDS`.
- As in the sibling project, `REPUTABLE_SPORTS_DOMAINS` and
  `KNOWN_MULTI_PART_SUFFIXES` are maintained on-chain constants, not a
  live registry - adding a new reputable domain requires a contract
  upgrade.
