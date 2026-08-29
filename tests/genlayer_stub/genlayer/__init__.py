"""
Minimal offline stub of the `genlayer` SDK.

THIS IS A TEST-ONLY SHIM, NOT PART OF THE DEPLOYABLE CONTRACT.

The real GenLayer SDK (`genlayer` package + GenVM runtime) is only
available inside a GenLayer node / GenLayer Studio / testnet, and
provides trustless, consensus-checked implementations of web access,
LLM calls, the caller's cryptographic identity, and the
equivalence-principle voting protocols.

For fast, fully offline unit testing of ForexCrossRateOracle's
DETERMINISTIC logic (domain extraction, rate parsing, timing windows,
party binding, verdict aggregation), this stub reproduces just enough
of the SDK's surface area to import and exercise `contract.py` in
plain Python, with `gl.nondet.web.render` / `gl.nondet.exec_prompt`
monkeypatched per test case and `gl.message.sender_address` settable
per test case to simulate different callers.

It intentionally does NOT attempt to simulate:
  - real network access,
  - real LLM behavior,
  - multi-validator consensus / leader rotation, or
  - GenVM's real deterministic clock (this stub simply uses the host
    machine's system clock via `datetime.datetime.now`, which is fine
    for these tests since they only assert relative ordering/behavior
    around timestamps, never an exact wall-clock value).

Those require the actual GenLayer Studio or testnet - see the
project's README for how the live end-to-end tests were run there.
"""

__all__ = ["gl", "TreeMap", "u256", "DynArray", "i256", "bigint", "Address"]


class _SubscriptableContainer:
    """Base for storage-type stand-ins that support `Type[K, V]` syntax
    used in class-level annotations (e.g. `TreeMap[str, str]`)."""

    def __class_getitem__(cls, item):
        return cls


class TreeMap(_SubscriptableContainer, dict):
    """Stand-in for genlayer's persistent TreeMap - behaves like a dict."""


class DynArray(_SubscriptableContainer, list):
    """Stand-in for genlayer's persistent DynArray - behaves like a list."""


class u256(int):
    """Stand-in for genlayer's fixed-width unsigned integer type."""


class i256(int):
    """Stand-in for genlayer's fixed-width signed integer type."""


class bigint(int):
    """Stand-in for genlayer's arbitrary-precision integer type."""


class Address:
    """
    Minimal stand-in for genlayer's Address type: validates a
    40-hex-character, "0x"-prefixed string and compares/hashes
    case-insensitively, matching how EVM-style addresses behave.
    """

    def __init__(self, value):
        text = str(value)
        if not text.startswith("0x") or len(text) != 42:
            raise ValueError(f"invalid address: {text!r}")
        int(text[2:], 16)  # raises ValueError if not valid hex
        self._value = text

    def __str__(self):
        return self._value

    def __repr__(self):
        return f"Address({self._value!r})"

    def __eq__(self, other):
        return str(self).lower() == str(other).lower()

    def __hash__(self):
        return hash(str(self).lower())


class UserError(Exception):
    """Stand-in for genlayer.gl.vm.UserError."""


class _Vm:
    """Stand-in for `gl.vm` - exposes UserError at its real SDK path."""

    UserError = UserError


class _PublicNamespace:
    """Stand-in for `gl.public` - decorators are no-ops that just mark
    a method as a plain callable (no ABI/consensus wiring needed for
    unit tests of internal logic)."""

    @staticmethod
    def write(fn):
        return fn

    @staticmethod
    def view(fn):
        return fn


class _NondetWeb:
    """
    Stand-in for `gl.nondet.web`. `render` raises by default; tests
    monkeypatch this with `unittest.mock.patch` to simulate specific
    fetch outcomes (success, timeout, empty page, garbage content...).
    """

    @staticmethod
    def render(url, mode="text"):
        raise NotImplementedError(
            "gl.nondet.web.render must be patched in tests"
        )


class _Nondet:
    web = _NondetWeb()

    @staticmethod
    def exec_prompt(prompt, response_format="text"):
        raise NotImplementedError(
            "gl.nondet.exec_prompt must be patched in tests"
        )


class _EqPrinciple:
    """
    Stand-in for `gl.eq_principle`.

    The contract uses `prompt_comparative` (never `strict_eq`) for its
    fetch+LLM pipeline, per GenLayer's documented guidance that
    strict_eq must never be used for LLM-derived output. In the real
    SDK, prompt_comparative runs `fn` on the leader, has each
    validator independently run `fn` again, and uses an NLP comparator
    (guided by the `principle` argument) to judge whether the leader's
    and a validator's results are equivalent - not byte-for-byte
    identical.

    For offline unit tests we simply run `fn` once and return its
    result; simulating the actual NLP comparator (or real
    multi-validator consensus at all) requires the live GenLayer
    Studio/testnet.
    """

    @staticmethod
    def strict_eq(fn):
        return fn()

    @staticmethod
    def prompt_comparative(fn, principle=None):
        return fn()

    @staticmethod
    def prompt_non_comparative(fn, task="", criteria=""):
        return fn()


class _Message:
    """
    Stand-in for `gl.message`. `sender_address` is a plain mutable
    attribute here (in the real SDK it's derived from the actual
    signed transaction) - tests set it directly before each call to
    simulate a specific caller, e.g.:

        gl.message.sender_address = Address("0x" + "11" * 20)
    """

    sender_address = None


class _Contract:
    """
    Stand-in base class for `gl.Contract`.

    In real GenVM, fields declared with persistent storage types
    (TreeMap, DynArray, ...) are automatically backed by chain state
    and start out empty - contracts are not expected to initialize
    them by hand in `__init__`. This stub reproduces that by scanning
    class annotations at construction time and pre-populating any
    TreeMap/DynArray fields with empty instances before the contract's
    own `__init__` runs.
    """

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in vars(klass).get("__annotations__", {}).items():
                if isinstance(annotation, type) and issubclass(
                    annotation, (TreeMap, DynArray)
                ):
                    setattr(instance, name, annotation())
        return instance

    def __init__(self, *args, **kwargs):
        pass


class _GL:
    Contract = _Contract
    public = _PublicNamespace()
    nondet = _Nondet()
    eq_principle = _EqPrinciple()
    vm = _Vm()
    message = _Message()


gl = _GL()
