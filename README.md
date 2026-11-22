# PIC16F84A Soft Core (VHDL)

[![PIC16F84A testbenches](https://github.com/giangvtr/vhdl-pic/actions/workflows/tests.yml/badge.svg)](https://github.com/giangvtr/vhdl-pic/actions/workflows/tests.yml)

> A synthesizable VHDL implementation of the Microchip PIC16F84A 8-bit microcontroller CPU core, with both a file-driven GHDL testbench and a automated cocotb verification environment.

[PIC16F84A Datasheet (PDF)](pic16f84a_datasheet.pdf): the ISA reference this core is built against.

## Overview
- 32/35 instructions implemented (SLEEP, CLRWDT, RETFIE excluded)
- Fixed size 14-bit instruction, Harvard-style memory split (separate program and data memory)
- Sequential: each instruction through a classic multi-cycle fetch/read/execute/write state machine, 
- 8-bit W register, {Z, DC, C} STATUS flags, 13-bit program counter, and an 8-level hardware stack for CALL/RETURN.
* File-driven testbench: reads binary opcodes from `input.txt`, runs them through the core, and writes the resulting program-counter trace to `output.txt`.
* cocotb: a Python reference model (built from the datasheet's instruction set, not the RTL) drives the same GHDL simulation, comparing W/STATUS/PC/RAM after every instruction, with randomized sequences and opcode/flag coverage. 38 individual tests — see [`cocotb/`](cocotb/).

A learning project for hobbyists



---

## Architecture

The core is composed of a decoder/control state machine, an ALU, and a file-register RAM, all orchestrated by the top-level `PIC` entity.

```text
                 ┌──────────────────────┐
   opcode  ───▶  │    state_machine     │  (decode + 4-state control)
                 └──────────┬───────────┘
                            │ op, addr, lit, bit_sel,
                            │ we/re, instr_ret
                            ▼
                 ┌──────────────────────┐
                 │         PIC          │  (W reg, STATUS, PC, stack)
                 └───────┬──────────┬───┘
                         │          │
                         ▼          ▼
                   ┌─────────┐  ┌─────────┐
                   │   alu   │  │  dpram  │
                   │ (32 ops)│  │ 128x8   │
                   └─────────┘  └─────────┘
```

`toplevel_alu_mem.vhd` is a smaller standalone wiring of the ALU and RAM used for isolated datapath experiments; the full processor lives in `pic.vhd`.

### Tech Stack

| Layer          | Technology              |
| -------------- | ----------------------- |
| HDL            | VHDL (IEEE 1076-2008)   |
| Simulation     | GHDL (`--std=08`)       |
| Waveform view  | GTKWave                 |
| Build          | GNU Make                |
| Reference      | PIC16F84A datasheet     |

---

---

## Results / Performance

Running the included test program produces a clean program-counter trace, including a correct `GOTO 0x005` branch:

| Metric                 | Result                          |
| ---------------------- | ------------------------------- |
| Instructions supported | 32 of 35 (`SLEEP`, `CLRWDT`, `RETFIE` not implemented) |
| Cycles per instruction | 4 (fetch/read/execute/write)    |
| File-register RAM      | 128 × 8-bit                     |
| Hardware stack depth   | 8 levels × 13-bit               |
| Simulation stop time   | 10 µs                           |

Sample `output.txt`:

```text
OPCODE=11000000010000 PC=1   # MOVLW 0x10
OPCODE=11111000000101 PC=2   # ADDLW 0x05
OPCODE=00000010001100 PC=3   # MOVWF 0x0C
OPCODE=00000110001100 PC=4   # CLRF  0x0C
OPCODE=10100000000101 PC=5   # GOTO  0x005
```

---

## Testing

Testing is done through the GHDL simulation flow. The `tb_pic` testbench reads opcodes from `input.txt`, drives them into the core one at a time (waiting for `instruction_return`), and logs the resulting PC to `output.txt`.

```bash
# From simulation/PIC, compile + run + open the waveform
make TESTBENCH=tb_pic

# Just clean the work directory
make clean
```

Edit `simulation/PIC/input.txt` to run a different program — each line is a 14-bit binary opcode, and lines starting with `#` are treated as comments.

---

## Verification (cocotb)

`cocotb/` adds a testbench that drives the same GHDL simulation through cocotb instead of a VHDL stimulus file:

* `cocotb/model/pic_model.py`: a Python model of the **datasheet's** instruction set (Table 7-2, Instruction Set Summary)
* `cocotb/tests/test_pic.py`: 33 directed tests (one per opcode, plus the `STATUS`@`0x03` RAM special case) and 4 chunks of randomized instruction sequences (2000 total by default), each compared against the model instruction-by-instruction. RAM content is verified by inserting a `MOVF` after any instruction the model predicts writes memory. A final test asserts that every opcode and every flag state (Z/DC/C, both 0 and 1) was actually exercised.


```bash
cd cocotb
pip install -r requirements.txt
make
```

`PIC_RANDOM_INSTRUCTIONS`, `PIC_RANDOM_CHUNKS` and `PIC_RANDOM_SEED` (env vars) tune the randomized run. Results are also written to `cocotb/results.xml` (JUnit format) and checked on every push/PR via GitHub Actions (badge above), or manually from the Actions tab (`workflow_dispatch`).

---

## Getting Started

### Prerequisites
* [GHDL](https://github.com/ghdl/ghdl) (with `--std=08` support)
* GTKWave *(optional, for viewing waveforms)*
* GNU Make

### Installation

```bash
git clone <REPO_URL>
cd pic_project
```

### Run the Simulation

```bash
cd simulation/PIC
make TESTBENCH=tb_pic
```

This compiles all VHDL sources, elaborates the `tb_pic` testbench, runs it for 10 µs, and opens the resulting waveform in GTKWave. The instruction trace is written to `simulation/PIC/output.txt`.

---

## Project Structure

```text
pic_project/
├── vhdl/PIC/
│   ├── alu.vhd                 # alu_pkg (32-op enum) + combinatorial ALU
│   ├── dpram.vhd               # 128x8 file-register RAM (STATUS special-cased)
│   ├── state_machine.vhd       # opcode decode + 4-state control
│   ├── pic.vhd                 # top-level core: W, STATUS, PC, stack
│   ├── toplevel_alu_mem.vhd    # standalone ALU+RAM datapath wiring
│   └── tb_pic.vhd              # file-driven testbench
├── simulation/PIC/
│   ├── Makefile                # GHDL analyze/elaborate/run/view flow
│   ├── input.txt               # program opcodes (one 14-bit word per line)
│   └── output.txt              # generated PC trace
├── cocotb/
│   ├── Makefile                 # cocotb/GHDL flow (`make` from this dir)
│   ├── requirements.txt
│   ├── model/pic_model.py       # datasheet-accurate Python reference model
│   └── tests/test_pic.py        # directed + randomized self-checking tests
├── .github/workflows/tests.yml  # CI: both testbenches, on push/PR/manual
└── pic16f84a_datasheet.pdf      # ISA reference used for the implementation
```

Note that `alu.vhd` also defines `alu_pkg`, the package holding the `alu_op` enumeration shared across the decoder, ALU, and datapath.


## Contributing

Contributions are welcome. A typical flow:

```bash
git checkout -b feature/my-feature
git commit -m "Add my feature"
git push origin feature/my-feature
```

Then open a pull request. Please keep new VHDL consistent with the existing style and add matching opcodes to `input.txt` (or a new testbench) to demonstrate the change.
