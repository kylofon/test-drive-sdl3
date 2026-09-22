// Headless post-script: sets up the Amiga Test Drive image (work/amiga/td.bin, Aztec C small model) in Ghidra
// and writes a decompile of every function, globals named D_xxxx (offset into the data hunk, the D:xxxx of
// port/amiga/README.md) and functions FUN_<address>.
//
// Rerun (from the repository root, Git Bash; the project is recreated, nothing else is touched):
//
//   python tools/hunk.py work/amiga/disk/td image work/amiga/td.bin        # if work/amiga/td.bin is missing
//   _tools/ghidra_12.1.3_PUBLIC/support/analyzeHeadless.bat _tools/ghidra_proj_amiga TestDriveAmiga \
//       -import work/amiga/td.bin -overwrite -noanalysis \
//       -loader BinaryLoader -loader-baseAddr 0x10000 -processor 68000:BE:32:default \
//       -scriptPath tools/ghidra \
//       -postScript AmigaTd.java port/amiga/td_functions.json port/amiga/decomp/td.c [timeout_s]
//
// (JAVA_HOME=_tools/jdk-21* if Ghidra cannot find a JDK.) Writes port/amiga/decomp/td.c and
// port/amiga/decomp/td_globals_xref.txt (next to td.c). Open the project afterwards with ghidraRun.bat.
//
// What the script does to the program (the raw import is one block "ram" at 0x10000-0x26F1F):
//  * splits it into the hunks (hunk0_root, hunk1_data, hunk2_bss, hunk3_ovl1, hunk4_ovl2; the gaps between
//    hunks are small padding blocks), data/bss not executable;
//  * A4 = 0x1FC0E as a register value over the code hunks, except the hand-written disk/protection module
//    0x11954-0x11DD3, which uses A4 as a pointer to its own structure;
//  * the four "saved A4" longs in code (lea x(pc),a0 ; move.l a4,(a0), read back by the VBL/input
//    handlers with movea.l x(pc),a4) are patched to 0x0001FC0E in the program (the runtime value; they are
//    0 in the file) and marked constant, so the handlers' globals resolve too;
//  * string literals referenced by the index (code hunks, and D:xxxx strings in the data hunk) become
//    terminated strings; code-hunk ones are marked constant so the decompiler prints them inline;
//  * call table: the 107 "jmp abs.l" slots become thunk functions jt_<target>; the 23 overlay stubs
//    ("bsr ovlmgr ; dc.w node<<8, offset") are disassembled, labelled jt_<target> and get a data reference
//    to target = overlay hunk base + offset; the final "jmp 0x168A4" is jt_ovlmgr. Every jsr d16(A4)
//    gets a CALL_OVERRIDE_UNCONDITIONAL reference to the real target, so decompiled calls read FUN_<target>;
//  * globals: label D_xxxx at every A4-relative address the index lists (reads/writes);
//  * a prototype "__aztec" (stack arguments at 4(sp), 2-byte aligned: Aztec pushes 16-bit ints as words;
//    result in D0; D0/D1/A0/A1 scratch) is added as a spec extension and set on every function;
//  * volatile blocks lowmem (0-0x3FF), cia (0xBFD000-0xBFEFFF) and custom (0xDFF000-0xDFF1FF) with the
//    register names (AbsExecBase, DMACON, COLOR00, ciaa_pra, ...);
//  * every "jmp d16(A6)" (the library glue's tail calls) gets a CALL_RETURN flow override;
//  * parameters: a first decompile pass commits each function's own view of its stack arguments (library
//    glue gets them from its loads off SP; functions taking the address of an argument are varargs);
//  * functions at every start in td_functions.json, plus the overlay manager 0x168A4 and EXTRA_STARTS (the
//    interrupt servers and callbacks the index misses); A1 = A4 at the two servers that load A4 from is_Data;
//    D:0B2A (only ever holds A4) is patched and marked constant like the saved-A4 longs.
// Note: Ghidra's 68000 data organization has a 4-byte int; the decompile's "short" is Aztec's int.
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.database.SpecExtension;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.data.DataUtilities;
import ghidra.program.model.data.DWordDataType;
import ghidra.program.model.data.MutabilitySettingsDefinition;
import ghidra.program.model.data.TerminatedStringDataType;
import ghidra.program.model.data.WordDataType;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class AmigaTd extends GhidraScript {
    static final long BASE = 0x10000;
    static final long DATA = 0x17C10, DATA_END = 0x1AEB4, BSS = 0x1AEC0, BSS_END = 0x1AEC4;
    static final long A4 = DATA + 0x7FFE;               // 0x1FC0E
    static final long OVL1 = 0x1AED0, OVL2 = 0x1C900, IMAGE_END = 0x26F1C;
    static final long[][] CODE = {{0x10000, 0x17C0C}, {OVL1, 0x1C8F8}, {OVL2, IMAGE_END}};
    static final long PROT_START = 0x11954, PROT_END = 0x11DD4; // A4 is not the data base here
    static final long OVLMGR = 0x168A4;
    // Code reached only through an address (lea/pea d16(pc)), so not in the index: the VBL servers
    // "Ticks" 0x118B2, "Sfx" 0x12616 / 0x126AE, "Song" 0x12A54, the input handler 0x15698, the RawDoFmt
    // character routine 0x15CAC, the TDScroller callback 0x1C820 and the "Road Drawer" 0x24F9A.
    static final long[] EXTRA_STARTS = {0x118B2, 0x12616, 0x126AE, 0x12A54, 0x15698, 0x15CAC, 0x1C820, 0x24F9A};
    // Servers entered with A1 = is_Data = A4 (set from D:1E9A / D:1EB6, which hold A4): movea.l a1,a4
    static final long[] A1_IS_A4 = {0x126AE, 0x12A54};

    static final String AZTEC_PROTO =
        "<prototype name=\"__aztec\" extrapop=\"4\" stackshift=\"4\">" +
        "<input><pentry minsize=\"1\" maxsize=\"500\" align=\"2\"><addr offset=\"4\" space=\"stack\"/></pentry></input>" +
        "<output><pentry minsize=\"1\" maxsize=\"4\"><register name=\"D0\"/></pentry></output>" +
        "<unaffected><register name=\"D2\"/><register name=\"D3\"/><register name=\"D4\"/><register name=\"D5\"/>" +
        "<register name=\"D6\"/><register name=\"D7\"/><register name=\"A2\"/><register name=\"A3\"/>" +
        "<register name=\"A4\"/><register name=\"A5\"/><register name=\"A6\"/><register name=\"SP\"/></unaffected>" +
        "<killedbycall><register name=\"D0\"/><register name=\"D1\"/><register name=\"A0\"/><register name=\"A1\"/></killedbycall>" +
        "</prototype>";

    Address ad(long a) { return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }

    boolean inCode(long a) {
        for (long[] r : CODE) if (a >= r[0] && a < r[1]) return true;
        return false;
    }

    static String hunkName(int h) {
        switch (h) { case 0: return "hunk 0 (root)"; case 3: return "hunk 3 (overlay 1)"; case 4: return "hunk 4 (overlay 2)"; }
        return "hunk " + h;
    }

    static int hunkOf(long a) {
        if (a >= 0x10000 && a < 0x17C0C) return 0;
        if (a >= DATA && a < DATA_END) return 1;
        if (a >= OVL1 && a < 0x1C8F8) return 3;
        if (a >= OVL2 && a < IMAGE_END) return 4;
        return -1;
    }

    void splitBlocks() throws Exception {
        Memory mem = currentProgram.getMemory();
        long[] cuts = {0x17C0C, DATA, DATA_END, BSS, BSS_END, OVL1, 0x1C8F8, OVL2, IMAGE_END};
        for (long c : cuts) {
            MemoryBlock b = mem.getBlock(ad(c));
            if (b != null && !b.getStart().equals(ad(c))) mem.split(b, ad(c));
        }
        String[][] names = {{"10000", "hunk0_root"}, {"17c0c", "pad0"}, {"17c10", "hunk1_data"}, {"1aeb4", "pad1"},
            {"1aec0", "hunk2_bss"}, {"1aec4", "pad2"}, {"1aed0", "hunk3_ovl1"}, {"1c8f8", "pad3"}, {"1c900", "hunk4_ovl2"},
            {"26f1c", "pad4"}};
        for (String[] n : names) {
            MemoryBlock b = mem.getBlock(ad(Long.parseLong(n[0], 16)));
            if (b == null) continue;
            b.setName(n[1]);
            boolean code = n[1].contains("root") || n[1].contains("ovl");
            b.setExecute(code || n[1].equals("hunk1_data")); // the call table in the data hunk is code
            b.setWrite(true);
        }
    }

    Data makeData(long a, ghidra.program.model.data.DataType t, boolean constant) throws Exception {
        Data d = DataUtilities.createData(currentProgram, ad(a), t, -1,
            DataUtilities.ClearDataMode.CLEAR_ALL_UNDEFINED_CONFLICT_DATA);
        if (constant) MutabilitySettingsDefinition.DEF.setChoice(d, MutabilitySettingsDefinition.CONSTANT);
        return d;
    }

    void label(long a, String name) throws Exception {
        Symbol s = getSymbolAt(ad(a));
        if (s != null && s.getName().equals(name)) return;
        createLabel(ad(a), name, true, SourceType.USER_DEFINED);
    }

    void disasm(long a) {
        if (getInstructionAt(ad(a)) == null) new DisassembleCommand(ad(a), null, true).applyTo(currentProgram, monitor);
    }

    static final String[] CUSTOM = {
        "000 BLTDDAT", "002 DMACONR", "004 VPOSR", "006 VHPOSR", "008 DSKDATR", "00A JOY0DAT", "00C JOY1DAT",
        "00E CLXDAT", "010 ADKCONR", "012 POT0DAT", "014 POT1DAT", "016 POTGOR", "018 SERDATR", "01A DSKBYTR",
        "01C INTENAR", "01E INTREQR", "020 DSKPTH", "024 DSKLEN", "026 DSKDAT", "028 REFPTR", "02A VPOSW",
        "02C VHPOSW", "02E COPCON", "030 SERDAT", "032 SERPER", "034 POTGO", "036 JOYTEST", "040 BLTCON0",
        "042 BLTCON1", "044 BLTAFWM", "046 BLTALWM", "048 BLTCPTH", "04C BLTBPTH", "050 BLTAPTH", "054 BLTDPTH",
        "058 BLTSIZE", "060 BLTCMOD", "062 BLTBMOD", "064 BLTAMOD", "066 BLTDMOD", "070 BLTCDAT", "072 BLTBDAT",
        "074 BLTADAT", "07E DSKSYNC", "080 COP1LCH", "084 COP2LCH", "088 COPJMP1", "08A COPJMP2", "08E DIWSTRT",
        "090 DIWSTOP", "092 DDFSTRT", "094 DDFSTOP", "096 DMACON", "098 CLXCON", "09A INTENA", "09C INTREQ",
        "09E ADKCON", "100 BPLCON0", "102 BPLCON1", "104 BPLCON2", "108 BPL1MOD", "10A BPL2MOD"};
    static final String[] CIA = {"pra", "prb", "ddra", "ddrb", "talo", "tahi", "tblo", "tbhi", "todlow", "todmid",
        "todhi", "unused", "sdr", "icr", "cra", "crb"};

    /** Volatile blocks for low memory, the CIAs and the custom chips, with the register names. */
    void hardware() throws Exception {
        Memory mem = currentProgram.getMemory();
        Object[][] blocks = {{"lowmem", 0x0L, 0x400L}, {"cia", 0xBFD000L, 0x2000L}, {"custom", 0xDFF000L, 0x200L}};
        for (Object[] b : blocks) {
            MemoryBlock mb = mem.createUninitializedBlock((String) b[0], ad((Long) b[1]), (Long) b[2], false);
            mb.setRead(true); mb.setWrite(true); mb.setExecute(false); mb.setVolatile(true);
        }
        hw(4, "AbsExecBase", 4);
        for (int v = 1; v <= 7; v++) hw(0x60 + 4 * v, "vec_level" + v + "_autovector", 4);
        for (String r : CUSTOM) hw(0xDFF000 + Long.parseLong(r.substring(0, 3), 16), r.substring(4),
            r.contains("PTH") || r.contains("LCH") ? 4 : 2);
        for (int ch = 0; ch < 4; ch++) {
            long b = 0xDFF0A0 + 0x10 * ch;
            hw(b, "AUD" + ch + "LCH", 4); hw(b + 4, "AUD" + ch + "LEN", 2); hw(b + 6, "AUD" + ch + "PER", 2);
            hw(b + 8, "AUD" + ch + "VOL", 2); hw(b + 10, "AUD" + ch + "DAT", 2);
        }
        for (int p = 0; p < 6; p++) hw(0xDFF0E0 + 4 * p, "BPL" + (p + 1) + "PTH", 4);
        for (int p = 0; p < 6; p++) hw(0xDFF110 + 2 * p, "BPL" + (p + 1) + "DAT", 2);
        for (int sp = 0; sp < 8; sp++) {
            hw(0xDFF120 + 4 * sp, "SPR" + sp + "PTH", 4);
            long b = 0xDFF140 + 8 * sp;
            hw(b, "SPR" + sp + "POS", 2); hw(b + 2, "SPR" + sp + "CTL", 2); hw(b + 4, "SPR" + sp + "DATA", 2);
            hw(b + 6, "SPR" + sp + "DATB", 2);
        }
        for (int c = 0; c < 32; c++) hw(0xDFF180 + 2 * c, String.format("COLOR%02d", c), 2);
        for (int r = 0; r < 16; r++) {
            hw(0xBFE001 + 0x100 * r, "ciaa_" + CIA[r], 1);
            hw(0xBFD000 + 0x100 * r, "ciab_" + CIA[r], 1);
        }
    }

    /** A named hardware register: label plus a data item of its width, so the decompiler uses the name. */
    void hw(long a, String name, int size) throws Exception {
        label(a, name);
        ghidra.program.model.data.DataType t = size == 4 ? DWordDataType.dataType
            : size == 2 ? WordDataType.dataType : ghidra.program.model.data.ByteDataType.dataType;
        try { makeData(a, t, false); } catch (Exception ex) { println("hw " + name + ": " + ex.getMessage()); }
    }

    ghidra.program.model.listing.Variable param(int i, int size) throws Exception {
        ghidra.program.model.data.DataType t = size == 4 ? ghidra.program.model.data.Undefined4DataType.dataType
            : size == 2 ? ghidra.program.model.data.Undefined2DataType.dataType
            : ghidra.program.model.data.Undefined.getUndefinedDataType(size);
        return new ghidra.program.model.listing.ParameterImpl("param_" + (i + 1), t, currentProgram);
    }

    /** Stack offset -> size of every load from SP+offset before the first instruction that changes SP or
     *  transfers control (the entry of a library glue routine: movea.l 4(a7),a1 / movem.l 4(a7),d1-d2 ...). */
    TreeMap<Integer, Integer> entryStackLoads(Function f) {
        TreeMap<Integer, Integer> loads = new TreeMap<>();
        Register sp = currentProgram.getRegister("SP");
        Instruction ins = getInstructionAt(f.getEntryPoint());
        while (ins != null && f.getBody().contains(ins.getAddress())) {
            java.util.HashMap<ghidra.program.model.pcode.Varnode, Integer> fromSp = new java.util.HashMap<>();
            boolean spWritten = false;
            for (ghidra.program.model.pcode.PcodeOp op : ins.getPcode()) {
                int opc = op.getOpcode();
                ghidra.program.model.pcode.Varnode out = op.getOutput();
                if (opc == ghidra.program.model.pcode.PcodeOp.INT_ADD || opc == ghidra.program.model.pcode.PcodeOp.COPY) {
                    ghidra.program.model.pcode.Varnode in0 = op.getInput(0);
                    int base = -1;
                    if (in0.isRegister() && in0.getAddress().equals(sp.getAddress())) base = 0;
                    else if (fromSp.containsKey(in0)) base = fromSp.get(in0);
                    if (base >= 0) {
                        if (opc == ghidra.program.model.pcode.PcodeOp.COPY) { if (out != null) fromSp.put(out, base); }
                        else if (op.getInput(1).isConstant() && out != null) fromSp.put(out, base + (int) op.getInput(1).getOffset());
                    }
                } else if (opc == ghidra.program.model.pcode.PcodeOp.LOAD) {
                    Integer o = fromSp.get(op.getInput(1));
                    if (o != null && out != null) loads.merge(o, out.getSize(), Math::max);
                }
                if (out != null && out.isRegister() && out.getAddress().equals(sp.getAddress())) spWritten = true;
            }
            if (spWritten || ins.getFlowType().isJump() || ins.getFlowType().isCall() || ins.getFlowType().isTerminal()) break;
            ins = ins.getNext();
        }
        return loads;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String jsonPath = args[0], outPath = args[1];
        int timeout = args.length > 2 ? Integer.parseInt(args[2]) : 300;

        // ---- index
        JsonArray funcs = JsonParser.parseReader(new FileReader(jsonPath)).getAsJsonArray();
        TreeMap<Long, JsonObject> index = new TreeMap<>();
        for (JsonElement e : funcs) {
            JsonObject o = e.getAsJsonObject();
            index.put(Long.parseLong(o.get("start").getAsString(), 16), o);
        }
        println("index: " + index.size() + " functions");

        splitBlocks();
        hardware();
        Memory mem = currentProgram.getMemory();

        // ---- prototype
        new SpecExtension(currentProgram).addReplaceCompilerSpecExtension(AZTEC_PROTO, monitor);

        // ---- saved-A4 longs in code: lea d(pc),a0 (41FA dddd) ; move.l a4,(a0) (208C)
        int savedA4 = 0;
        for (long[] r : CODE) {
            for (long a = r[0]; a + 6 <= r[1]; a += 2) {
                if ((mem.getShort(ad(a)) & 0xFFFF) == 0x41FA && (mem.getShort(ad(a + 4)) & 0xFFFF) == 0x208C) {
                    long slot = a + 2 + mem.getShort(ad(a + 2));
                    if (!inCode(slot) || mem.getInt(ad(slot)) != 0) continue;
                    mem.setInt(ad(slot), (int) A4);
                    makeData(slot, DWordDataType.dataType, true);
                    label(slot, String.format("saved_a4_%05X", slot));
                    setEOLComment(ad(slot), "A4 saved here at run time by " + String.format("0x%05X", a) + " (0 in the file)");
                    savedA4++;
                }
            }
        }
        println("saved-A4 slots: " + savedA4);

        // ---- strings (before disassembly so flows don't run into them)
        int strs = 0;
        TreeSet<Long> globals = new TreeSet<>();
        for (JsonObject o : index.values()) {
            for (Map.Entry<String, JsonElement> s : o.getAsJsonObject("strings").entrySet()) {
                String k = s.getKey();
                try {
                    if (k.startsWith("D:")) {
                        long off = Long.parseLong(k.substring(2), 16);
                        if (getDataAt(ad(DATA + off)) == null) makeData(DATA + off, TerminatedStringDataType.dataType, false);
                        globals.add(off);
                    } else {
                        long a = Long.parseLong(k, 16);
                        if (getDataAt(ad(a)) == null) makeData(a, TerminatedStringDataType.dataType, true);
                    }
                    strs++;
                } catch (Exception ex) {
                    println("string " + k + ": " + ex.getMessage());
                }
            }
        }
        println("strings: " + strs);

        // ---- D:0B2A holds A4 (written by 0x1C840, read back by the TDScroller callback 0x1C820)
        mem.setInt(ad(DATA + 0xB2A), (int) A4);
        makeData(DATA + 0xB2A, DWordDataType.dataType, true);
        setEOLComment(ad(DATA + 0xB2A), "holds A4 at run time (move.l a4 at 0x1C840); 0 in the file");

        // ---- A4 over the code (not the protection module)
        Register a4 = currentProgram.getRegister("A4");
        BigInteger a4v = BigInteger.valueOf(A4);
        for (long[] r : CODE) {
            if (r[0] <= PROT_START && PROT_END <= r[1]) {
                currentProgram.getProgramContext().setValue(a4, ad(r[0]), ad(PROT_START - 1), a4v);
                currentProgram.getProgramContext().setValue(a4, ad(PROT_END), ad(r[1] - 1), a4v);
            } else {
                currentProgram.getProgramContext().setValue(a4, ad(r[0]), ad(r[1] - 1), a4v);
            }
        }

        Register a1 = currentProgram.getRegister("A1");
        for (long x : A1_IS_A4) currentProgram.getProgramContext().setValue(a1, ad(x), ad(x + 1), a4v);

        // ---- functions (descending, so a flow never swallows a later start)
        ArrayList<Long> starts = new ArrayList<>(index.keySet());
        starts.add(OVLMGR);
        for (long x : EXTRA_STARTS) starts.add(x);
        Collections.sort(starts, Collections.reverseOrder());
        for (long s : starts) disasm(s);
        int created = 0, failedCreate = 0;
        for (long s : starts) {
            Function f = getFunctionAt(ad(s));
            if (f == null) f = createFunction(ad(s), null);
            if (f == null) { println(String.format("could not create function at %05X", s)); failedCreate++; continue; }
            created++;
        }
        Function om = getFunctionAt(ad(OVLMGR));
        // direct call targets (bsr / jsr d16(pc)) inside the new servers that have no function yet
        for (int round = 0; round < 5; round++) {
            int more = 0;
            for (Instruction ins : currentProgram.getListing().getInstructions(true)) {
                if (!inCode(ins.getAddress().getOffset()) || !ins.getFlowType().isCall()) continue;
                for (Address t : ins.getFlows()) {
                    if (!inCode(t.getOffset()) || getFunctionAt(t) != null) continue;
                    disasm(t.getOffset());
                    if (createFunction(t, null) != null) { more++; created++; }
                }
            }
            if (more == 0) break;
        }
        println("functions: " + created + " (failed " + failedCreate + ")");

        // ---- more code-hunk literals: pea d16(pc) / lea d16(pc),An aimed at a zero-terminated printable run
        // that is neither code nor data yet (short ones such as "%d" or "r" that the index does not list)
        int pcStrs = 0;
        for (Instruction ins : currentProgram.getListing().getInstructions(true)) {
            long ia = ins.getAddress().getOffset();
            if (!inCode(ia)) continue;
            int op = mem.getShort(ins.getAddress()) & 0xFFFF;
            if (op != 0x487A && (op & 0xF1FF) != 0x41FA) continue;
            long t = ia + 2 + mem.getShort(ad(ia + 2));
            if (!inCode(t) || getInstructionContaining(ad(t)) != null || getDataContaining(ad(t)) != null
                && getDataContaining(ad(t)).isDefined()) continue;
            int n = 0;
            boolean ok = false;
            while (n < 200) {
                int c = mem.getByte(ad(t + n)) & 0xFF;
                if (c == 0) { ok = n > 0; break; }
                if (!(c >= 0x20 && c < 0x7F || c == '\n' || c == '\t' || c == '\r')) break;
                n++;
            }
            if (!ok) continue;
            try { makeData(t, TerminatedStringDataType.dataType, true); pcStrs++; } catch (Exception ex) { }
        }
        println("pc-relative strings added: " + pcStrs);

        // ---- call table
        TreeMap<Long, Long> jt = new TreeMap<>();
        long a = DATA;
        int thunks = 0;
        while ((mem.getShort(ad(a)) & 0xFFFF) == 0x4EF9) {
            long t = mem.getInt(ad(a + 2)) & 0xFFFFFFFFL;
            jt.put(a, t);
            disasm(a);
            Function tf = getFunctionAt(ad(t));
            if (tf == null) { disasm(t); tf = createFunction(ad(t), null); }
            Function sf = getFunctionAt(ad(a));
            if (sf == null) sf = currentProgram.getFunctionManager().createFunction(
                String.format("jt_%05X", t), ad(a), new AddressSet(ad(a), ad(a + 5)), SourceType.USER_DEFINED);
            if (tf != null) { sf.setThunkedFunction(tf); thunks++; }
            sf.setName(String.format("jt_%05X", t), SourceType.USER_DEFINED);
            a += 6;
        }
        long plainEnd = a;
        a += 2;
        int stubs = 0;
        ReferenceManager rm = currentProgram.getReferenceManager();
        while ((mem.getShort(ad(a)) & 0xFFFF) == 0x6100) {
            int node = mem.getByte(ad(a + 4)) & 0xFF;
            int off = mem.getShort(ad(a + 6)) & 0xFFFF;
            long t = (node == 1 ? OVL1 : OVL2) + off;
            jt.put(a, t);
            makeData(a + 4, WordDataType.dataType, false);
            makeData(a + 6, WordDataType.dataType, false);
            disasm(a);
            label(a, String.format("jt_%05X", t));
            rm.addMemoryReference(ad(a + 4), ad(t), RefType.DATA, SourceType.USER_DEFINED, 0);
            setEOLComment(ad(a), String.format("overlay %d stub -> 0x%05X (hunk base + 0x%X)", node, t, off));
            stubs++;
            a += 8;
        }
        // "jmp ovlmgr" after the stubs
        if ((mem.getShort(ad(a)) & 0xFFFF) == 0x4EF9) {
            disasm(a);
            Function sf = currentProgram.getFunctionManager().createFunction("jt_ovlmgr", ad(a),
                new AddressSet(ad(a), ad(a + 5)), SourceType.USER_DEFINED);
            if (om != null) sf.setThunkedFunction(om);
            sf.setName("jt_ovlmgr", SourceType.USER_DEFINED);
        }
        println(String.format("call table: %d jmp slots (%d thunks) up to %05X, %d overlay stubs, ovlmgr jmp at %05X",
            jt.size() - stubs, thunks, plainEnd, stubs, a));

        // ---- calling convention on every function
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.isThunk()) continue;
            try { f.setCallingConvention("__aztec"); } catch (Exception ex) { println("cc " + f.getName() + ": " + ex.getMessage()); }
        }

        // ---- jsr d16(A4) (4EAC dddd) -> real target
        int overrides = 0, unresolved = 0, libTail = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            long ia = ins.getAddress().getOffset();
            if (!inCode(ia) || (ia >= PROT_START && ia < PROT_END)) continue;
            int op = mem.getShort(ins.getAddress()) & 0xFFFF;
            if (op == 0x4EEE) { ins.setFlowOverride(FlowOverride.CALL_RETURN); libTail++; continue; }
            if (op != 0x4EAC) continue;
            long slot = A4 + mem.getShort(ad(ia + 2));
            Long t = jt.get(slot);
            if (t == null) { println(String.format("jsr d16(A4) at %05X hits %05X, not a slot", ia, slot)); unresolved++; continue; }
            for (Reference r : rm.getReferencesFrom(ins.getAddress())) rm.delete(r);
            Reference r = rm.addMemoryReference(ins.getAddress(), ad(t), RefType.CALL_OVERRIDE_UNCONDITIONAL,
                SourceType.USER_DEFINED, 0);
            rm.setPrimary(r, true);
            overrides++;
        }
        println("jsr d16(A4) overrides: " + overrides + " (unresolved " + unresolved + "); jmp d16(A6) as call-return: " + libTail);

        // ---- globals
        TreeMap<Long, TreeSet<String>> idxUse = new TreeMap<>();
        for (JsonObject o : index.values()) {
            long s = Long.parseLong(o.get("start").getAsString(), 16);
            if (s >= PROT_START && s < PROT_END) continue;
            for (String k : new String[] {"reads", "writes"}) {
                for (JsonElement g : o.getAsJsonArray(k)) {
                    long off = Long.parseLong(g.getAsString().substring(2), 16);
                    if (DATA + off >= BSS_END) continue;
                    globals.add(off);
                    idxUse.computeIfAbsent(off, x -> new TreeSet<>()).add(String.format("FUN_%05X", s));
                }
            }
        }
        int labelled = 0;
        for (long off : globals) {
            long ga = DATA + off;
            if (jt.containsKey(ga)) continue;
            Symbol s = getSymbolAt(ad(ga));
            if (s != null && s.getName().startsWith("jt_")) continue;
            label(ga, String.format("D_%04X", off));
            labelled++;
        }
        println("globals labelled: " + labelled);

        // ---- decompile
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        opts.grabFromProgram(currentProgram);
        decomp.setOptions(opts);
        decomp.toggleCCode(true);
        decomp.toggleSyntaxTree(true);
        decomp.openProgram(currentProgram);

        // ---- pass 1: parameters. The decompiler guesses a callee's stack arguments from the caller's pushes
        // (a pushed long reads as two shorts with the 2-byte alignment), so first commit what each function
        // reads itself, as Ghidra's "Decompiler Parameter ID" does. Library glue (no link, calls through A6)
        // passes its stack arguments on in registers, which the decompiler cannot see: its parameters are
        // taken from the loads off SP at its entry instead. Functions that take the address of a stack
        // argument (Aztec varargs: lea/pea d(a5) with d >= 8) are marked varargs, so calls keep every push.
        int committed = 0, glue = 0, varargs = 0;
        TreeSet<Long> pass1 = new TreeSet<>(index.keySet());
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long e = f.getEntryPoint().getOffset();
            if (!f.isThunk() && inCode(e)) pass1.add(e);
        }
        for (long e : pass1) {
            Function f = getFunctionAt(ad(e));
            if (f == null || f.isThunk()) continue;
            boolean link = (mem.getShort(ad(e)) & 0xFFFF) == 0x4E55;
            boolean libcall = false, va = false;
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                int op = mem.getShort(ins.getAddress()) & 0xFFFF;
                if (op == 0x4EAE || op == 0x4EEE) libcall = true;
                if ((op & 0xF1FF) == 0x41ED || op == 0x486D) {
                    if (mem.getShort(ins.getAddress().add(2)) >= 8) va = true;
                }
            }
            try {
                if (!link && libcall) {
                    TreeMap<Integer, Integer> loads = entryStackLoads(f);
                    ArrayList<ghidra.program.model.listing.Variable> ps = new ArrayList<>();
                    int off = 4;
                    for (Map.Entry<Integer, Integer> l : loads.entrySet()) {
                        if (l.getKey() < off) continue;
                        while (off + 4 <= l.getKey()) { ps.add(param(ps.size(), 4)); off += 4; }
                        if (off < l.getKey()) { ps.add(param(ps.size(), l.getKey() - off)); off = l.getKey(); }
                        ps.add(param(ps.size(), l.getValue()));
                        off += l.getValue();
                    }
                    f.updateFunction("__aztec", null, ps, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS,
                        true, SourceType.ANALYSIS);
                    glue++;
                } else {
                    DecompileResults r = decomp.decompileFunction(f, timeout, monitor);
                    if (r != null && r.decompileCompleted() && r.getHighFunction() != null) {
                        ghidra.program.model.pcode.HighFunctionDBUtil.commitParamsToDatabase(r.getHighFunction(), true,
                            ghidra.program.model.pcode.HighFunctionDBUtil.ReturnCommitOption.NO_COMMIT, SourceType.ANALYSIS);
                        committed++;
                    }
                }
                if (va) { f.setVarArgs(true); varargs++; }
            } catch (Exception ex) {
                println(String.format("params %05X: %s", e, ex.getMessage()));
            }
        }
        println("parameters: " + committed + " committed from the decompiler, " + glue + " library glue, " + varargs + " varargs");
        decomp.flushCache();

        Pattern funRe = Pattern.compile("FUN_000([12][0-9a-f]{4})\\b");
        Pattern datRe = Pattern.compile("\\b[A-Za-z]*?_?(?:DAT_|Ram|LAB_)0001([0-9a-f]{4})\\b");
        Pattern dRe = Pattern.compile("\\bD_([0-9A-F]{4})\\b");
        TreeMap<Long, TreeSet<String>> use = new TreeMap<>(idxUse);
        int ok = 0, failed = 0;
        ArrayList<String> failures = new ArrayList<>();

        TreeSet<Long> all = new TreeSet<>(index.keySet());
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long e = f.getEntryPoint().getOffset();
            if (!f.isThunk() && inCode(e)) all.add(e);
        }
        new File(outPath).getAbsoluteFile().getParentFile().mkdirs();
        try (PrintWriter out = new PrintWriter(outPath, "UTF-8")) {
            out.println("// Test Drive (Amiga) `td` decompilation: Ghidra 12.1.3 headless, tools/ghidra/AmigaTd.java.");
            out.println("// Image base 0x10000 (work/amiga/td.bin), A4 = 0x1FC0E. Globals D_xxxx = D:xxxx, offset into the data hunk");
            out.println("// (address 0x17C10 + xxxx). Calls through the A4 call table are resolved to FUN_<target>. \"short\" is");
            out.println("// Aztec's 16-bit int. Not reviewed: see port/amiga/README.md and the index port/amiga/td_functions.json.");
            for (long e : all) {
                Function f = getFunctionAt(ad(e));
                String name = String.format("FUN_%05X", e);
                JsonObject o = index.get(e);
                String extra = o == null ? "  (not in td_functions.json)" : "";
                String end = o == null ? "" : String.format("-0x%s", o.get("end").getAsString().replaceFirst("^0", "").toUpperCase());
                out.printf("%n// ==== %s  0x%05X%s  %s%s ====%n", name, e, end, hunkName(hunkOf(e)), extra);
                if (f == null) {
                    out.println("// no function (creation failed)");
                    failures.add(name + ": no function");
                    failed++;
                    continue;
                }
                DecompileResults r = decomp.decompileFunction(f, timeout, monitor);
                if (r == null || !r.decompileCompleted() || r.getDecompiledFunction() == null) {
                    String msg = r == null ? "null" : r.getErrorMessage().trim();
                    out.println("// decompile failed: " + msg);
                    failures.add(name + ": " + msg);
                    failed++;
                    continue;
                }
                String c = r.getDecompiledFunction().getC();
                Matcher m = funRe.matcher(c);
                StringBuffer sb = new StringBuffer();
                while (m.find()) m.appendReplacement(sb, "FUN_" + m.group(1).toUpperCase());
                m.appendTail(sb);
                c = sb.toString();
                m = datRe.matcher(c);
                sb = new StringBuffer();
                while (m.find()) {
                    long ga = 0x10000 + Long.parseLong(m.group(1), 16);
                    if (ga >= DATA && ga < BSS_END) m.appendReplacement(sb, String.format("D_%04X", ga - DATA));
                    else m.appendReplacement(sb, Matcher.quoteReplacement(m.group(0)));
                }
                m.appendTail(sb);
                // "_D_xxxx": Ghidra marks a global accessed wider than the symbol at its address with a leading '_'
                c = sb.toString().replaceAll("\\b_D_([0-9A-F]{4})\\b", "D_$1");
                // after the D_ renaming the '_'-prefixed names are gone, and so is the point of this warning
                c = c.replaceAll("(?m)^/\\* WARNING: Globals starting with .*\\R", "");
                if (c.contains("WARNING")) {
                    for (String line : c.split("\n")) if (line.contains("WARNING")) failures.add(name + " warns: " + line.trim());
                }
                out.print(c);
                m = dRe.matcher(c);
                while (m.find()) use.computeIfAbsent(Long.parseLong(m.group(1), 16), x -> new TreeSet<>()).add(name);
                ok++;
            }
        }
        decomp.dispose();

        File xref = new File(new File(outPath).getAbsoluteFile().getParentFile(), "td_globals_xref.txt");
        try (PrintWriter out = new PrintWriter(xref, "UTF-8")) {
            out.println("# D:xxxx global (offset into the data hunk, address 0x17C10 + xxxx) -> functions using it.");
            out.println("# Union of the decompile (D_xxxx in td.c) and the index (td_functions.json reads/writes).");
            for (Map.Entry<Long, TreeSet<String>> g : use.entrySet()) {
                out.printf("D:%04X  %3d fns  %s%n", g.getKey(), g.getValue().size(), String.join(" ", g.getValue()));
            }
        }
        println("decompiled " + ok + " functions, " + failed + " failed; globals in xref: " + use.size());
        for (String s : failures) println("  " + s);
    }
}
