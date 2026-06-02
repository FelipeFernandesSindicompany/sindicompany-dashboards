"""
Fix Vibra Butantã: remove abr26 from inside window.onload and place correctly in BAL.
Then update EVO arrays and other required arrays.
"""
import sys, re, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = __file__.replace('scripts\\fix_vibra_abr26.py', '')

DASH = ROOT + 'docs/Dashboard_Financeiro_VibraButanta.html'
with open(DASH, encoding='utf-8') as f:
    c = f.read()

# Step 1: Find and extract the wrongly placed abr26 entry
# It's at: "buildCharts();,\n    abr26: {...}\n  }"
# We need to:
# a) Remove the comma+abr26 from window.onload
# b) Close window.onload properly
# c) Find the real BAL block and append abr26 there

# Find abr26 with its full content (it's after the buildCharts call)
bad_pattern = re.search(
    r'(buildCharts\(\);),\s*\n(\s+abr26:\s*\{[\s\S]*?\})\s*\n(\s*\})',
    c
)

if bad_pattern:
    print("Found wrongly placed abr26!")
    print("Group 1 (buildCharts):", bad_pattern.group(1))
    print("Group 2 (abr26 entry):", bad_pattern.group(2)[:80])
    print("Group 3 (closing):", repr(bad_pattern.group(3)))

    abr26_content = bad_pattern.group(2).strip()  # The abr26 entry

    # Remove abr26 from window.onload - restore proper function closure
    old_str = bad_pattern.group(0)
    new_str = bad_pattern.group(1) + '\n' + bad_pattern.group(3)
    c = c.replace(old_str, new_str, 1)
    print("\nRemoved from window.onload")

    # Now find the BAL block and insert abr26 at the end
    # BAL block ends with \n}; or \n  };
    bal_close = re.search(r'(var\s+BAL\s*=\s*\{)(.*?)(\n\s*\};)', c, re.DOTALL)
    if bal_close:
        bal_content = bal_close.group(2)
        sep = ",\n" if not bal_content.rstrip().endswith(',') else "\n"
        new_bal = bal_close.group(1) + bal_content + sep + "    " + abr26_content + bal_close.group(3)
        c = c.replace(bal_close.group(0), new_bal, 1)
        print("Inserted abr26 into BAL")
    else:
        print("ERROR: BAL block not found!")
        sys.exit(1)
else:
    print("Pattern not found - checking alternative...")
    # Try finding abr26 directly
    idx = c.find('buildCharts();,')
    if idx >= 0:
        print(f"Found 'buildCharts();,' at {idx}")
        print("Context:", repr(c[idx:idx+150]))
    else:
        print("buildCharts();, not found either")
        # Check if abr26 is already in BAL correctly
        bal_start = c.find('var BAL = {')
        if bal_start < 0: bal_start = c.find('var BAL={')
        bal_end = c.find('};', bal_start) + 2
        bal = c[bal_start:bal_end]
        if 'abr26:' in bal:
            print("abr26 already correctly in BAL!")
        else:
            print("abr26 NOT in BAL")
    sys.exit(0)

# Step 2: Fix EVO_V if needed (remove extra entries)
evo_l = re.search(r'(var EVO_L=\[)([^\]]+)(\])', c)
evo_v = re.search(r'(var EVO_V=\[)([^\]]+)(\])', c)
if evo_l and evo_v:
    n_labels = len([x for x in evo_l.group(2).split(',') if x.strip()])
    vals = [v.strip() for v in evo_v.group(2).split(',') if v.strip()]
    if len(vals) != n_labels:
        print(f"\nFixing EVO_V: {len(vals)} -> {n_labels}")
        correct = vals[:n_labels]
        c = c.replace(evo_v.group(0), evo_v.group(1) + ','.join(correct) + evo_v.group(3), 1)

# Step 3: Update MESES to include abr26
meses_m = re.search(r'var MESES=(\[[^\]]+\])', c)
if meses_m:
    try:
        current = json.loads(meses_m.group(1))
        mo = {v:k+1 for k,v in enumerate(['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'])}
        # Get all BAL keys
        bal_start = c.find('var BAL = {')
        if bal_start < 0: bal_start = c.find('var BAL={')
        bal_end = c.find('};', bal_start) + 2
        bal = c[bal_start:bal_end]
        all_keys = re.findall(r'\b([a-z]{3}\d{2})\s*:', bal)
        unique_keys = list(dict.fromkeys([k for k in all_keys if k[:3] in mo]))
        unique_keys.sort(key=lambda k: int(k[3:])*12 + mo.get(k[:3],0))
        new_meses = 'var MESES=' + json.dumps(unique_keys)
        c = c.replace('var MESES=' + meses_m.group(1), new_meses, 1)
        print(f"\nMESES updated: {unique_keys}")
    except Exception as e:
        print(f"MESES update failed: {e}")

# Save
with open(DASH, 'w', encoding='utf-8') as f:
    f.write(c)
print("\nDashboard saved!")
