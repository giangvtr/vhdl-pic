# PIC16F84A Soft Core (VHDL)

> A synthesizable VHDL implementation of the Microchip PIC16F84A 8-bit microcontroller CPU core, complete with a file-driven GHDL testbench.

[PIC16F84A Datasheet (PDF)](pic16f84a_datasheet.pdf) — the ISA reference this core is built against.

## Overview

This project implements the datapath and control logic of the **PIC16F84A** RISC microcontroller in VHDL. It decodes the full 35-instruction PIC opcode set, executes each instruction through a classic multi-cycle fetch/read/execute/write state machine, and maintains the architectural state (Working register, STATUS flags, program counter, hardware stack, and file-register RAM) exactly as the real silicon does.

It was built as a learning/reference project for computer architecture and digital design: the goal was to take a well-documented commercial ISA (the [PIC16F84A datasheet](pic16f84a_datasheet.pdf) is included in this repo) and reproduce its behavior cycle-accurately at the RTL level. It's aimed at students and hobbyists interested in CPU design, VHDL, and how a real microcontroller decodes and executes instructions.

The design mirrors the actual PIC microarchitecture — a 14-bit instruction word, an 8-level deep hardware call stack, a Harvard-style memory split, and a synchronous file-register RAM whose STATUS location is partially driven by the ALU rather than by writes.

---

## Key Features

* **Full PIC16F84A instruction set** — all 35 instructions across byte-oriented, bit-oriented, and literal/control groups are decoded and executed.
* **Multi-cycle control** — a four-state machine (iFetch → Mread → Execute → Mwrite) sequences each instruction and signals completion via `instruction_return`.
* **Complete architectural state** — 8-bit W register, {Z, DC, C} STATUS flags, 13-bit program counter, and an 8-level hardware stack for `CALL`/`RETURN`.
* **Synchronous file-register RAM** — a 128 × 8 dual-port RAM with special handling for the STATUS register so ALU-generated flags are preserved.
* **File-driven testbench** — reads binary opcodes from `input.txt`, runs them through the core, and writes the resulting program-counter trace to `output.txt`.

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
                   │ (35 ops)│  │ 128x8   │
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

## Technical Highlights

### Handling the STATUS register in RAM

**Problem:** On the PIC, the STATUS register lives at file address `0x03` and is memory-mapped, but its Z/DC/C bits are updated by the ALU as a side effect of most instructions — not just by explicit writes. A naive RAM would clobber those flags on every unrelated write.

**Approach considered:** Keeping STATUS entirely outside the RAM, versus keeping it in RAM but special-casing address `0x03`.

**Chosen:** `dpram.vhd` treats `STATUS_ADDR = 3` specially: normal writes update the addressed byte, but the ALU-provided `d_status` bits are folded in so that Z/DC/C survive writes to other locations. The top-level `PIC` process also maintains its own `status_reg` copy for control decisions like conditional skips.

**Result:** Instructions that both write a file register and affect flags (e.g. `ADDWF`, `SUBWF`) behave correctly, and the flag state stays consistent between the ALU, RAM, and control logic.

### Multi-cycle state machine with registered decode

Rather than a single-cycle design, the control uses a four-phase machine so memory reads and writes get their own clock edges. Instruction fields (`op`, `addr`, `jump_addr`, `lit`, `bit_sel`) are decoded once and **registered**, and a `force_nop` input lets the core inject a NOP to flush the pipeline after branches (`GOTO`/`CALL`/`RETURN`) so a stale instruction isn't executed at the branch target.

---

## Results / Performance

Running the included test program produces a clean program-counter trace, including a correct `GOTO 0x005` branch:

| Metric                 | Result                          |
| ---------------------- | ------------------------------- |
| Instructions supported | 35 (full PIC16F84A set)         |
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
│   ├── alu.vhd                 # alu_pkg (35-op enum) + combinatorial ALU
│   ├── dpram.vhd               # 128x8 file-register RAM (STATUS special-cased)
│   ├── state_machine.vhd       # opcode decode + 4-state control
│   ├── pic.vhd                 # top-level core: W, STATUS, PC, stack
│   ├── toplevel_alu_mem.vhd    # standalone ALU+RAM datapath wiring
│   └── tb_pic.vhd              # file-driven testbench
├── simulation/PIC/
│   ├── Makefile                # GHDL analyze/elaborate/run/view flow
│   ├── input.txt               # program opcodes (one 14-bit word per line)
│   └── output.txt              # generated PC trace
└── pic16f84a_datasheet.pdf     # ISA reference used for the implementation
```

Note that `alu.vhd` also defines `alu_pkg`, the package holding the `alu_op` enumeration shared across the decoder, ALU, and datapath.

---

## Security

Not applicable — this is a hardware description / simulation project with no network, filesystem, or user-input attack surface beyond the local testbench, which reads a plain-text opcode file. If synthesized to real hardware, standard FPGA/ASIC toolchain and bitstream integrity considerations would apply.

## Contributing

Contributions are welcome. A typical flow:

```bash
git checkout -b feature/my-feature
git commit -m "Add my feature"
git push origin feature/my-feature
```

Then open a pull request. Please keep new VHDL consistent with the existing style and add matching opcodes to `input.txt` (or a new testbench) to demonstrate the change.

---

## License

No license file is currently included. Add one (e.g. the [MIT License](LICENSE)) before distributing.
