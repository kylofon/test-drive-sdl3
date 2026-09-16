// Headless post-script: applies merged port symbols to the Ghidra program.
// args: <symbols_ghidra.txt> <dgroup segment hex, e.g. C9A>
// Lines: "func 2054 road_render" (image offset) or "global 18C5 player_x" (DS offset).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

import java.nio.file.Files;
import java.nio.file.Paths;

public class ApplySymbols extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        long dgroup = Long.parseLong(args[1], 16) << 4;
        Address base = currentProgram.getMinAddress();
        int funcs = 0, globals = 0, failed = 0;
        for (String line : Files.readAllLines(Paths.get(args[0]))) {
            String[] p = line.trim().split("\\s+");
            if (p.length < 3) continue;
            long off = Long.parseLong(p[1], 16);
            try {
                if (p[0].equals("func")) {
                    Address a = base.add(off);
                    Function f = getFunctionAt(a);
                    if (f == null) f = createFunction(a, p[2]);
                    if (f != null) { f.setName(p[2], SourceType.USER_DEFINED); funcs++; } else failed++;
                } else {
                    Address a = base.add(dgroup + off);
                    Symbol s = getSymbolAt(a);
                    if (s != null && s.getSource() == SourceType.USER_DEFINED) s.setName(p[2], SourceType.USER_DEFINED);
                    else createLabel(a, p[2], true, SourceType.USER_DEFINED);
                    globals++;
                }
            } catch (Exception e) {
                println("skip " + line + ": " + e.getMessage());
                failed++;
            }
        }
        println("applied " + funcs + " function names, " + globals + " global names, " + failed + " failed");
    }
}
