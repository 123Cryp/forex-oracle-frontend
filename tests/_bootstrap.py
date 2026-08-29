"""
Shared test bootstrap - wires up the offline genlayer SDK stub and
loads contract.py once. Standard pattern used across this project's
test files.
"""
import importlib.util
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUB_DIR = os.path.join(_THIS_DIR, "genlayer_stub")
if _STUB_DIR not in sys.path:
    sys.path.insert(0, _STUB_DIR)

_CONTRACT_PATH = os.path.join(os.path.dirname(_THIS_DIR), "contract.py")
_spec = importlib.util.spec_from_file_location("forexcrossrateoracle_contract", _CONTRACT_PATH)
_contract_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract_module)

ForexCrossRateOracle = _contract_module.ForexCrossRateOracle
gl = _contract_module.gl
Address = _contract_module.Address


def make_contract() -> "ForexCrossRateOracle":
    return ForexCrossRateOracle()


# Two fixed, valid, distinct addresses reused across test files so
# every test doesn't have to invent its own.
PARTY_A_ADDRESS = "0x" + "11" * 20
PARTY_B_ADDRESS = "0x" + "22" * 20
STRANGER_ADDRESS = "0x" + "33" * 20


def set_caller(address_str: str):
    """Simulate a specific wallet calling the next contract method."""
    gl.message.sender_address = Address(address_str)
