"""Self-checking cocotb testbench for the PIC core (vhdl/PIC/pic.vhd).

Drives the `opcode` input one instruction slot at a time, exactly like
vhdl/PIC/tb_pic.vhd does, but compares every slot against model.PicModel
instead of just logging a PC trace.

Split into many small @cocotb.test() functions (one per directed opcode,
plus a handful of random-stress chunks) rather than two large ones, so
cocotb's summary table and results.xml report each case individually --
a failure names the exact opcode, not "test_directed_opcodes, somewhere".

Timing note: with this GHDL+cocotb/VPI combination, reading DUT signals
right after the clock edge where `instruction_return` goes high shows the
result of the *previous* opcode, not the one just completed -- a one
instruction, constant-offset latency in VPI visibility (confirmed by
direct experimentation; GHDL's own simulation is correct, only the
VPI-visible snapshot lags). `_PipelinedChecker` below accounts for this by
always comparing the current readout against the model state from one
step back, and flushing one extra trailing NOP at the end to check the
last real instruction.

W is not a port of the original PIC entity. Reading it through GHDL's VPI
as an internal signal (`dut.work_reg`) turned out to have *additional*,
harder-to-reason-about staleness on top of the constant one-instruction
lag above, and GHDL's VPI does not expose directly-instantiated
sub-entities (U_RAM, U_FSM) by name at all, so RAM can't be peeked at
directly either. `work_reg_dbg` was added to vhdl/PIC/pic.vhd as a
verification-only output port (behaves like the other ports, no extra
lag); RAM contents are instead verified architecturally, by following any
instruction the model predicts will write RAM with a MOVF probe of that
address and checking it shows up in W.
"""

import os
import random
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.pic_model import (  # noqa: E402
    ALL_OPS,
    PicModel,
    encode_bit_oriented,
    encode_byte_oriented,
    encode_control,
    encode_literal,
)

CLK_PERIOD_NS = 100
RANDOM_INSTRUCTION_COUNT = int(os.environ.get("PIC_RANDOM_INSTRUCTIONS", "2000"))
RANDOM_CHUNKS = int(os.environ.get("PIC_RANDOM_CHUNKS", "4"))
RANDOM_SEED = int(os.environ.get("PIC_RANDOM_SEED", "1234"))

_BYTE_ORIENTED_OPS = [
    "ADDWF", "ANDWF", "CLRF", "CLRW", "COMF", "DECF", "DECFSZ", "INCF", "INCFSZ",
    "IORWF", "MOVF", "MOVWF", "RLF", "RRF", "SUBWF", "SWAPF", "XORWF",
]
_BIT_ORIENTED_OPS = ["BCF", "BSF", "BTFSC", "BTFSS"]
_LITERAL_OPS = ["ADDLW", "ANDLW", "IORLW", "MOVLW", "SUBLW", "XORLW", "RETLW"]


async def _wait_for_instr_ret(dut):
    while True:
        await RisingEdge(dut.clk)
        if dut.instruction_return.value == 1:
            return


def _random_instruction(rng: random.Random):
    op = rng.choice(ALL_OPS)
    if op in _BYTE_ORIENTED_OPS:
        return op, encode_byte_oriented(op, rng.randrange(128), rng.randrange(2))
    if op in _BIT_ORIENTED_OPS:
        return op, encode_bit_oriented(op, rng.randrange(128), rng.randrange(8))
    if op in _LITERAL_OPS:
        return op, encode_literal(op, rng.randrange(256))
    if op in ("GOTO", "CALL"):
        return op, encode_control(op, rng.randrange(2048))
    return op, encode_control(op)


class _PipelinedChecker:
    """Feeds opcodes to the DUT and checks each one's effect once it
    becomes visible -- one feed *later* than when it was issued, per the
    VPI latency explained in the module docstring. Also inserts a MOVF
    probe after any instruction the model predicts writes RAM, since RAM
    can't be read back any other way."""

    def __init__(self, dut):
        self.dut = dut
        self.model = PicModel()
        self._pending_opcode = 0  # the implicit leading NOP from reset
        self._pending_label = "reset-NOP"
        self._probe_queue = []
        self.coverage = {op: 0 for op in ALL_OPS}
        self.flags_seen = {k: False for k in ("Z0", "Z1", "DC0", "DC1", "C0", "C1")}

    async def start(self):
        """Reset the DUT and drive it to a known-clean architectural state.

        cocotb runs every @cocotb.test() in the same simulation instance,
        one after another, with no re-elaboration in between. pic.vhd's
        reset does not clear work_reg or the 8-level CALL/RETURN stack
        array, and dpram.vhd has no reset input at all (it's a plain
        synchronous RAM) -- all genuine RTL properties, not bugs -- so W,
        the 128-byte file-register RAM, and the hardware stack can carry
        real leftover values from whichever test ran earlier. Explicitly
        normalizing them here (through the checked feed() pipeline
        itself) keeps each test's PicModel() in sync with the DUT
        regardless of run order, and doubles as extra coverage.
        """
        cocotb.start_soon(Clock(self.dut.clk, CLK_PERIOD_NS, unit="ns").start())
        self.dut.reset.value = 1
        self.dut.opcode.value = 0
        await Timer(100, unit="ns")
        self.dut.reset.value = 0
        await _wait_for_instr_ret(self.dut)  # consumes the leading NOP's decode

        # NOP doesn't touch W and reset doesn't clear it, so whatever W
        # holds right now is genuine leftover state, not a model mismatch.
        self.model.w = int(self.dut.work_reg_dbg.value)

        await self.feed(encode_literal("MOVLW", 0x00), "init:MOVLW-0")
        for addr in range(128):
            await self.feed(encode_byte_oriented("CLRF", addr, 1), f"init:CLRF-0x{addr:02x}")

        # stack_ptr is reset to 0, but the 8-deep stack array itself is
        # not -- fill every slot with a model-predictable value (8 CALLs)
        # then unwind it (8 RETURNs) so no stale return address from an
        # earlier test can surface via RETURN/RETLW later in this test.
        for _ in range(8):
            await self.feed(encode_control("CALL", 0x000), "init:CALL-fill-stack")
        for _ in range(8):
            await self.feed(encode_control("RETURN"), "init:RETURN-unwind-stack")

    async def feed(self, opcode: int, label: str):
        while self._probe_queue:
            probe_opcode = self._probe_queue.pop(0)
            await self._feed_now(probe_opcode, "RAM-probe")
        await self._feed_now(opcode, label)

    async def _feed_now(self, opcode: int, label: str):
        self.dut.opcode.value = opcode
        await _wait_for_instr_ret(self.dut)

        was_forced = self.model.force_nop
        info = self.model.step(self._pending_opcode)
        executed_op = "NOP" if was_forced else info["op"]
        self.coverage[executed_op] = self.coverage.get(executed_op, 0) + 1
        self.flags_seen["Z1" if self.model.z else "Z0"] = True
        self.flags_seen["DC1" if self.model.dc else "DC0"] = True
        self.flags_seen["C1" if self.model.c else "C0"] = True

        self._check(self._pending_label)

        if info["writes_mem"] and info["ram_addr"] is not None:
            self._probe_queue.append(encode_byte_oriented("MOVF", info["ram_addr"], 0))

        self._pending_opcode, self._pending_label = opcode, label

    async def flush(self):
        """Feed a trailing NOP so the very last real instruction's effect
        (still pending) gets checked too."""
        await self.feed(0, "trailing-flush")

    def _check(self, ctx: str):
        dut, model = self.dut, self.model
        dut_w = int(dut.work_reg_dbg.value)
        dut_status = int(dut.status.value)
        dut_pc = int(dut.program_counter.value)

        assert dut_w == model.w, f"W mismatch after {ctx}: dut=0x{dut_w:02x} model=0x{model.w:02x}"
        assert dut_status == model.status, (
            f"STATUS mismatch after {ctx}: dut={dut_status:03b} model={model.status:03b}"
        )
        assert dut_pc == model.pc, f"PC mismatch after {ctx}: dut={dut_pc} model={model.pc}"


async def _run_case(dut, steps):
    """steps: ordered [(label, opcode), ...]; every step is checked, not
    just the last one, so setup instructions get coverage too."""
    checker = _PipelinedChecker(dut)
    await checker.start()
    for label, opcode in steps:
        await checker.feed(opcode, label)
    await checker.flush()


# --- One self-contained directed test per opcode (and a couple of extra
# cases for the STATUS@0x03 special case in dpram.vhd) -------------------
# Each list is fully self-contained: _PipelinedChecker.start() always
# brings W and RAM to a known-zero state first, so these don't depend on
# cocotb's test execution order.

DIRECTED_CASES = {
    "MOVLW": [("MOVLW", encode_literal("MOVLW", 0x10))],
    "ADDLW": [("MOVLW", encode_literal("MOVLW", 0x10)), ("ADDLW", encode_literal("ADDLW", 0x05))],
    "MOVWF": [("MOVLW", encode_literal("MOVLW", 0x15)), ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1))],
    "ADDWF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVLW", encode_literal("MOVLW", 0x02)),
        ("ADDWF", encode_byte_oriented("ADDWF", 0x10, 0)),
    ],
    "SUBWF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVLW", encode_literal("MOVLW", 0x02)),
        ("SUBWF", encode_byte_oriented("SUBWF", 0x10, 0)),
    ],
    "ANDLW": [("ANDLW", encode_literal("ANDLW", 0x0F))],
    "IORLW": [("IORLW", encode_literal("IORLW", 0xF0))],
    "XORLW": [("XORLW", encode_literal("XORLW", 0xFF))],
    "SUBLW": [("SUBLW", encode_literal("SUBLW", 0x02))],
    "CLRF": [("MOVLW", encode_literal("MOVLW", 0x15)), ("MOVWF", encode_byte_oriented("MOVWF", 0x11, 1)),
             ("CLRF", encode_byte_oriented("CLRF", 0x11, 1))],
    "CLRW": [("MOVLW", encode_literal("MOVLW", 0x15)), ("CLRW", encode_byte_oriented("CLRW", 0, 0))],
    "COMF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("COMF", encode_byte_oriented("COMF", 0x10, 0)),
    ],
    "INCF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("INCF", encode_byte_oriented("INCF", 0x10, 1)),
    ],
    "DECF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("DECF", encode_byte_oriented("DECF", 0x10, 1)),
    ],
    "MOVF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVF", encode_byte_oriented("MOVF", 0x10, 0)),
    ],
    "RLF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("RLF", encode_byte_oriented("RLF", 0x10, 1)),
    ],
    "RRF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("RRF", encode_byte_oriented("RRF", 0x10, 1)),
    ],
    "SWAPF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("SWAPF", encode_byte_oriented("SWAPF", 0x10, 1)),
    ],
    "XORWF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVLW", encode_literal("MOVLW", 0xFF)),
        ("XORWF", encode_byte_oriented("XORWF", 0x10, 0)),
    ],
    "ANDWF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVLW", encode_literal("MOVLW", 0x0F)),
        ("ANDWF", encode_byte_oriented("ANDWF", 0x10, 0)),
    ],
    "IORWF": [
        ("MOVLW", encode_literal("MOVLW", 0x15)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x10, 1)),
        ("MOVLW", encode_literal("MOVLW", 0xF0)),
        ("IORWF", encode_byte_oriented("IORWF", 0x10, 0)),
    ],
    "BSF": [("BSF", encode_bit_oriented("BSF", 0x12, 3))],
    "BCF": [("BSF", encode_bit_oriented("BSF", 0x12, 3)), ("BCF", encode_bit_oriented("BCF", 0x12, 3))],
    "BTFSS": [
        ("BSF", encode_bit_oriented("BSF", 0x12, 3)),
        ("BTFSS", encode_bit_oriented("BTFSS", 0x12, 3)),
        ("NOP(should-be-skipped)", encode_control("NOP")),
    ],
    "BTFSC": [
        ("BTFSC", encode_bit_oriented("BTFSC", 0x12, 3)),
        ("NOP(should-be-skipped)", encode_control("NOP")),
    ],
    "DECFSZ": [
        ("MOVLW", encode_literal("MOVLW", 0x01)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x13, 1)),
        ("DECFSZ", encode_byte_oriented("DECFSZ", 0x13, 1)),
        ("NOP(should-be-skipped)", encode_control("NOP")),
    ],
    "INCFSZ": [
        ("MOVLW", encode_literal("MOVLW", 0xFF)),
        ("MOVWF", encode_byte_oriented("MOVWF", 0x13, 1)),
        ("INCFSZ", encode_byte_oriented("INCFSZ", 0x13, 1)),
        ("NOP(should-be-skipped)", encode_control("NOP")),
    ],
    "GOTO": [("GOTO", encode_control("GOTO", 0x005))],
    "CALL_RETURN": [("CALL", encode_control("CALL", 0x010)), ("RETURN", encode_control("RETURN"))],
    "RETLW": [("CALL", encode_control("CALL", 0x010)), ("RETLW", encode_literal("RETLW", 0x09))],
    "NOP": [("NOP", encode_control("NOP"))],
    # STATUS lives at file address 0x03 and is special-cased in dpram.vhd:
    # writing elsewhere must fold the ALU's {Z,DC,C} into ram[0x03]
    # without disturbing bits 7:3; writing 0x03 directly replaces the
    # whole byte. These two cases probe both paths (the "other address"
    # fold is also exercised implicitly by every RAM-writing case above,
    # via _PipelinedChecker's automatic MOVF probes).
    "STATUS_direct_write": [
        ("MOVLW", encode_literal("MOVLW", 0xAA)),
        ("MOVWF_STATUS", encode_byte_oriented("MOVWF", 0x03, 1)),
    ],
    "STATUS_flag_fold": [
        ("MOVLW", encode_literal("MOVLW", 0xAA)),
        ("MOVWF_STATUS", encode_byte_oriented("MOVWF", 0x03, 1)),
        ("ADDWF_elsewhere", encode_byte_oriented("ADDWF", 0x20, 0)),  # touches ram[0x03] flags, not addr 0x03
    ],
}


def _make_directed_test(name, steps):
    async def _test(dut):
        await _run_case(dut, steps)

    _test.__name__ = f"test_directed_{name}"
    _test.__qualname__ = _test.__name__
    _test.__doc__ = f"Directed check for {name}: {steps}"
    return cocotb.test()(_test)


for _name, _steps in DIRECTED_CASES.items():
    globals()[f"test_directed_{_name}"] = _make_directed_test(_name, _steps)


# --- Randomized stress test, split into independently-reported chunks so
# a failure names which chunk (and which instruction index within it)
# rather than "somewhere in 2000 instructions". Each chunk is an
# independent reset+run with its own seed; a final test asserts combined
# opcode/flag coverage across all of them. -------------------------------

_chunk_size = max(1, RANDOM_INSTRUCTION_COUNT // RANDOM_CHUNKS)
_aggregate_coverage = {op: 0 for op in ALL_OPS}
_aggregate_flags = {k: False for k in ("Z0", "Z1", "DC0", "DC1", "C0", "C1")}


def _make_random_chunk_test(chunk_index, size, seed):
    async def _test(dut):
        rng = random.Random(seed)
        checker = _PipelinedChecker(dut)
        await checker.start()
        for i in range(size):
            op, opcode = _random_instruction(rng)
            await checker.feed(opcode, f"chunk{chunk_index}#{i}:{op}")
        await checker.flush()

        for op, count in checker.coverage.items():
            _aggregate_coverage[op] += count
        for name, seen in checker.flags_seen.items():
            _aggregate_flags[name] = _aggregate_flags[name] or seen

    _test.__name__ = f"test_random_chunk_{chunk_index}"
    _test.__qualname__ = _test.__name__
    _test.__doc__ = f"Randomized stress chunk {chunk_index} ({size} instructions, seed={seed})."
    return cocotb.test()(_test)


for _i in range(RANDOM_CHUNKS):
    globals()[f"test_random_chunk_{_i}"] = _make_random_chunk_test(_i, _chunk_size, RANDOM_SEED + _i)


@cocotb.test()
async def test_random_coverage_summary(dut):
    """Runs last: asserts every opcode and flag state was exercised by
    the random chunks above, combined."""
    dut._log.info("Opcode coverage (all chunks): %s", _aggregate_coverage)
    dut._log.info("Flag coverage (all chunks): %s", _aggregate_flags)

    missing_ops = [op for op, count in _aggregate_coverage.items() if count == 0]
    missing_flags = [name for name, seen in _aggregate_flags.items() if not seen]

    assert not missing_ops, f"opcodes never exercised across all chunks: {missing_ops}"
    assert not missing_flags, f"flag states never exercised across all chunks: {missing_flags}"
