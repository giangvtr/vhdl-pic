"""Python reference model of the real PIC16F84A ISA.

This is a *datasheet-accurate* golden model, not a mirror of whatever the
RTL in ../../vhdl/PIC happens to do: the opcode decode table and
bit-field layout follow state_machine.vhd exactly (that part is purely
structural and not spec-relevant), but every "Status Affected" decision
in _alu() is taken from the PIC16F84A datasheet's Table 7-2 (Instruction
Set Summary), e.g. DECFSZ/INCFSZ affect no STATUS bits -- only the ALU
result is used for the skip test -- even though it would be easy to
assume they behave like DECF/INCF.

CLRWDT, SLEEP, RETFIE, OPTION and TRIS are intentionally absent: this
core's alu_pkg (vhdl/PIC/alu.vhd) doesn't implement them, and the
datasheet itself deprecates OPTION/TRIS for newer parts.
"""

from dataclasses import dataclass, field

RAM_SIZE = 128
STATUS_ADDR = 3
STACK_DEPTH = 8
MASK8 = 0xFF
MASK13 = 0x1FFF

# The 32 alu_op values actually defined in alu_pkg (vhdl/PIC/alu.vhd).
# The README advertises "35 instructions"; CLRWDT/SLEEP/RETFIE/OPTION/TRIS
# are not modeled by this core, so they are intentionally absent here too.
ALL_OPS = [
    "ADDWF", "ANDWF", "CLRF", "CLRW", "COMF", "DECF",
    "DECFSZ", "INCF", "INCFSZ", "IORWF", "MOVF", "MOVWF",
    "RLF", "RRF", "SUBWF", "SWAPF", "XORWF",
    "BCF", "BSF", "BTFSC", "BTFSS",
    "ADDLW", "ANDLW", "IORLW", "MOVLW", "SUBLW", "XORLW",
    "GOTO", "CALL", "RETURN", "RETLW", "NOP",
]

_NEEDS_MEMREAD = {
    "ADDWF", "ANDWF", "CLRF", "COMF", "DECF", "DECFSZ", "INCF", "INCFSZ",
    "IORWF", "MOVF", "MOVWF", "RLF", "RRF", "SUBWF", "SWAPF", "XORWF",
    "BCF", "BSF", "BTFSC", "BTFSS",
}

_LITERAL_ALU_IN = {"MOVLW", "ADDLW", "SUBLW", "ANDLW", "IORLW", "XORLW", "RETLW"}

_WRITES_W_UNCONDITIONALLY = {
    "MOVLW", "ADDLW", "ANDLW", "IORLW", "SUBLW", "XORLW", "RETLW", "CLRW",
}
_WRITES_MEM_UNCONDITIONALLY = {"MOVWF", "CLRF", "BCF", "BSF"}
_WRITES_PER_D = {
    "ADDWF", "ANDWF", "COMF", "DECF", "INCF", "IORWF", "MOVF",
    "RLF", "RRF", "SUBWF", "SWAPF", "XORWF", "DECFSZ", "INCFSZ",
}


def decode_op(inst: int) -> str:
    """Reproduce decode_op() from state_machine.vhd bit-for-bit."""
    msbs = (inst >> 8) & 0x3F
    b1312 = (inst >> 12) & 0x3
    b1311 = (inst >> 11) & 0x7
    b1310 = (inst >> 10) & 0xF
    b118 = (inst >> 8) & 0xF
    bit7 = (inst >> 7) & 0x1

    if msbs == 0b000111:
        return "ADDWF"
    if msbs == 0b000101:
        return "ANDWF"
    if msbs == 0b000000 and bit7 == 1:
        return "MOVWF"
    if msbs == 0b000001 and bit7 == 1:
        return "CLRF"
    if msbs == 0b000001 and bit7 == 0:
        return "CLRW"
    if msbs == 0b001001:
        return "COMF"
    if msbs == 0b000011:
        return "DECF"
    if msbs == 0b001011:
        return "DECFSZ"
    if msbs == 0b001010:
        return "INCF"
    if msbs == 0b001111:
        return "INCFSZ"
    if msbs == 0b000100:
        return "IORWF"
    if msbs == 0b001000:
        return "MOVF"
    if msbs == 0b001101:
        return "RLF"
    if msbs == 0b001100:
        return "RRF"
    if msbs == 0b000010:
        return "SUBWF"
    if msbs == 0b001110:
        return "SWAPF"
    if msbs == 0b000110:
        return "XORWF"

    if b1310 == 0b0100:
        return "BCF"
    if b1310 == 0b0101:
        return "BSF"
    if b1310 == 0b0110:
        return "BTFSC"
    if b1310 == 0b0111:
        return "BTFSS"

    if b1312 == 0b11:
        if b118 in (0b1110, 0b1111):
            return "ADDLW"
        if b118 == 0b1001:
            return "ANDLW"
        if b118 == 0b1000:
            return "IORLW"
        if b118 in (0b0000, 0b0001, 0b0010, 0b0011):
            return "MOVLW"
        if b118 in (0b0100, 0b0101, 0b0110, 0b0111):
            return "RETLW"
        if b118 in (0b1100, 0b1101):
            return "SUBLW"
        if b118 == 0b1010:
            return "XORLW"
        return "NOP"

    if b1311 == 0b101:
        return "GOTO"
    if b1311 == 0b100:
        return "CALL"
    if inst == 0b00000000001000:
        return "RETURN"
    return "NOP"


def _fields(inst: int) -> dict:
    return {
        "addr": inst & 0x7F,
        "jump_addr": inst & 0x7FF,
        "lit": inst & 0xFF,
        "bit_sel": (inst >> 7) & 0x7,
        "d": (inst >> 7) & 0x1,
    }


# --- Encoders: exact inverse of decode_op's bit patterns -------------------

def encode_byte_oriented(op: str, f: int, d: int) -> int:
    msbs = {
        "ADDWF": 0b000111, "ANDWF": 0b000101, "MOVWF": 0b000000,
        "CLRF": 0b000001, "CLRW": 0b000001, "COMF": 0b001001,
        "DECF": 0b000011, "DECFSZ": 0b001011, "INCF": 0b001010,
        "INCFSZ": 0b001111, "IORWF": 0b000100, "MOVF": 0b001000,
        "RLF": 0b001101, "RRF": 0b001100, "SUBWF": 0b000010,
        "SWAPF": 0b001110, "XORWF": 0b000110,
    }[op]
    if op == "MOVWF" or op == "CLRF":
        d = 1
    elif op == "CLRW":
        d = 0
        f = 0
    return (msbs << 8) | ((d & 1) << 7) | (f & 0x7F)


def encode_bit_oriented(op: str, f: int, bit_sel: int) -> int:
    pattern = {"BCF": 0b0100, "BSF": 0b0101, "BTFSC": 0b0110, "BTFSS": 0b0111}[op]
    return (pattern << 10) | ((bit_sel & 0x7) << 7) | (f & 0x7F)


def encode_literal(op: str, k: int) -> int:
    b118 = {
        "ADDLW": 0b1110, "ANDLW": 0b1001, "IORLW": 0b1000,
        "MOVLW": 0b0000, "RETLW": 0b0100, "SUBLW": 0b1100, "XORLW": 0b1010,
    }[op]
    return (0b11 << 12) | (b118 << 8) | (k & 0xFF)


def encode_control(op: str, addr: int = 0) -> int:
    if op == "GOTO":
        return (0b101 << 11) | (addr & 0x7FF)
    if op == "CALL":
        return (0b100 << 11) | (addr & 0x7FF)
    if op == "RETURN":
        return 0b00000000001000
    if op == "NOP":
        return 0
    raise ValueError(op)


@dataclass
class PicModel:
    """Architectural state. `status` packs {Z,DC,C} as bit2=Z, bit1=DC, bit0=C,
    matching pic.vhd's status_reg / the `status` output port layout."""

    w: int = 0
    z: int = 0
    dc: int = 0
    c: int = 0
    pc: int = 0
    ram: list = field(default_factory=lambda: [0] * RAM_SIZE)
    stack: list = field(default_factory=lambda: [0] * STACK_DEPTH)
    stack_ptr: int = 0
    force_nop: bool = False

    @property
    def status(self) -> int:
        return (self.z << 2) | (self.dc << 1) | self.c

    def _apply_status(self, z: int, dc: int, c: int):
        self.z, self.dc, self.c = z, dc, c

    def _ram_write(self, addr: int, value: int, z: int, dc: int, c: int):
        """Mirrors dpram.vhd: a write to any address other than STATUS_ADDR
        also folds the ALU's {Z,DC,C} into ram[STATUS_ADDR]'s low 3 bits."""
        value &= MASK8
        if addr == STATUS_ADDR:
            self.ram[STATUS_ADDR] = value
        else:
            self.ram[addr] = value
            flags = (z << 2) | (dc << 1) | c
            self.ram[STATUS_ADDR] = (self.ram[STATUS_ADDR] & ~0x7 & MASK8) | flags

    def step(self, raw_opcode: int):
        """Advance by one instruction slot.

        raw_opcode is whatever value sits on the `opcode` bus for this slot.
        If the previous instruction set force_nop, it is ignored and NOP is
        executed instead, exactly like state_machine.vhd's iFetch stage.
        """
        if self.force_nop:
            op = "NOP"
            fields = _fields(0)
        else:
            op = decode_op(raw_opcode)
            fields = _fields(raw_opcode)

        f_addr = fields["addr"]
        d = fields["d"]
        bit_sel = fields["bit_sel"]

        f_in = self.ram[f_addr] if op in _NEEDS_MEMREAD else 0
        if op in _LITERAL_ALU_IN:
            f_in = fields["lit"]

        result, z, dc, c = self._alu(op, self.w, f_in, bit_sel)
        writes_mem, writes_w = self._writeback_targets(op, d)

        if writes_w:
            self.w = result & MASK8
            self._apply_status(z, dc, c)
        if writes_mem:
            self._ram_write(f_addr, result, z, dc, c)
            self._apply_status(z, dc, c)

        self._advance_pc(op, result, fields, f_addr)

        return {"op": op, "writes_mem": writes_mem, "ram_addr": f_addr if writes_mem else None}

    def _writeback_targets(self, op: str, d: int):
        if op in _WRITES_W_UNCONDITIONALLY:
            return False, True
        if op in _WRITES_MEM_UNCONDITIONALLY:
            return True, False
        if op in _WRITES_PER_D:
            return (d == 1), (d == 0)
        return False, False

    def _alu(self, op: str, w_in: int, f_in: int, bit_sel: int):
        """Returns (result, z, dc, c). Defaults to the current flags
        unchanged, matching alu.vhd's `v_status := status_in` default."""
        z, dc, c = self.z, self.dc, self.c

        if op in ("ADDWF", "ADDLW"):
            total = w_in + f_in
            dc_sum = (w_in & 0xF) + (f_in & 0xF)
            res = total & MASK8
            c = 1 if total > MASK8 else 0
            dc = 1 if dc_sum > 0xF else 0
            z = 1 if res == 0 else 0

        elif op in ("SUBWF", "SUBLW"):
            total = f_in - w_in
            dc_sum = (f_in & 0xF) - (w_in & 0xF)
            res = total & MASK8
            c = 0 if total < 0 else 1          # borrow -> C cleared (inverted)
            dc = 0 if dc_sum < 0 else 1
            z = 1 if res == 0 else 0

        elif op in ("ANDWF", "ANDLW"):
            res = w_in & f_in
            z = 1 if res == 0 else 0

        elif op in ("IORWF", "IORLW"):
            res = w_in | f_in
            z = 1 if res == 0 else 0

        elif op in ("XORWF", "XORLW"):
            res = w_in ^ f_in
            z = 1 if res == 0 else 0

        elif op in ("CLRF", "CLRW"):
            res = 0
            z = 1

        elif op == "MOVF":
            res = f_in
            z = 1 if res == 0 else 0

        elif op == "MOVWF":
            res = w_in

        elif op == "MOVLW":
            res = f_in

        elif op == "COMF":
            res = (~f_in) & MASK8
            z = 1 if res == 0 else 0

        elif op == "INCF":
            res = (f_in + 1) & MASK8
            z = 1 if res == 0 else 0

        elif op == "INCFSZ":
            # Status Affected: None (datasheet Table 7-2) -- the skip test
            # in _advance_pc() uses this result directly, not Z.
            res = (f_in + 1) & MASK8

        elif op == "DECF":
            res = (f_in - 1) & MASK8
            z = 1 if res == 0 else 0

        elif op == "DECFSZ":
            # Status Affected: None (datasheet Table 7-2).
            res = (f_in - 1) & MASK8

        elif op == "BCF":
            res = f_in & (~(1 << bit_sel) & MASK8)

        elif op == "BSF":
            res = f_in | (1 << bit_sel)

        elif op in ("BTFSC", "BTFSS"):
            res = f_in  # unused: these never write back

        elif op == "RLF":
            res = ((f_in << 1) | self.c) & MASK8
            c = (f_in >> 7) & 1

        elif op == "RRF":
            res = ((f_in >> 1) | (self.c << 7)) & MASK8
            c = f_in & 1

        elif op == "SWAPF":
            res = ((f_in & 0xF) << 4) | ((f_in >> 4) & 0xF)

        elif op == "RETLW":
            res = f_in

        else:  # GOTO, CALL, RETURN, NOP
            res = 0

        return res, z, dc, c

    def _advance_pc(self, op: str, result: int, fields: dict, f_addr: int):
        if op == "GOTO":
            self.pc = fields["jump_addr"] & MASK13
            self.force_nop = False

        elif op == "CALL":
            self.stack[self.stack_ptr] = (self.pc + 1) & MASK13
            self.stack_ptr = (self.stack_ptr + 1) % STACK_DEPTH
            self.pc = fields["jump_addr"] & MASK13
            self.force_nop = False

        elif op in ("RETURN", "RETLW"):
            self.stack_ptr = (self.stack_ptr - 1) % STACK_DEPTH
            self.pc = self.stack[self.stack_ptr]
            self.force_nop = False

        elif op in ("DECFSZ", "INCFSZ") and (result & MASK8) == 0:
            self.force_nop = True
            self.pc = (self.pc + 2) & MASK13

        elif op == "BTFSC":
            bit = (self.ram[f_addr] >> fields["bit_sel"]) & 1
            if bit == 0:
                self.force_nop = True
                self.pc = (self.pc + 2) & MASK13
            else:
                self.force_nop = False
                self.pc = (self.pc + 1) & MASK13

        elif op == "BTFSS":
            bit = (self.ram[f_addr] >> fields["bit_sel"]) & 1
            if bit == 1:
                self.force_nop = True
                self.pc = (self.pc + 2) & MASK13
            else:
                self.force_nop = False
                self.pc = (self.pc + 1) & MASK13

        else:
            self.force_nop = False
            self.pc = (self.pc + 1) & MASK13
