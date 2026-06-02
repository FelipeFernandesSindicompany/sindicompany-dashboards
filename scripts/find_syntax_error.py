import sys, re, subprocess, tempfile, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = __file__.replace('scripts\\find_syntax_error.py', '')

with open(ROOT + 'docs/Dashboard_Financeiro_VibraButanta.html', encoding='utf-8') as f:
    c = f.read()

scripts = re.findall(r'<script(?![^>]*\bsrc\b)[^>]*>([\s\S]*?)</script>', c, re.IGNORECASE)
combined = '\n'.join(scripts)

# Write to temp file
tmp_path = os.path.join(tempfile.gettempdir(), 'vibra_check.js')
with open(tmp_path, 'w', encoding='utf-8') as f:
    f.write('var window={onload:null,addEventListener:function(){},innerWidth:1200};\n')
    f.write('var document={getElementById:function(){return{innerHTML:"",style:{},classList:{add:function(){},remove:function(){}},appendChild:function(){},querySelectorAll:function(){return[];}};},querySelector:function(){return null;},querySelectorAll:function(){return[];},createElement:function(){return{};},addEventListener:function(){}};\n')
    f.write('var Chart=function(){};\n')
    f.write('var setTimeout=function(){};\n')
    f.write(combined)

node = r'C:\Program Files\nodejs\node.exe'
result = subprocess.run([node, '--check', tmp_path], capture_output=True, text=True)
if result.returncode != 0:
    print('SYNTAX ERROR:')
    print(result.stderr[:800])

    # Find line number from error
    line_match = re.search(r'vibra_check\.js:(\d+)', result.stderr)
    if line_match:
        line_num = int(line_match.group(1))
        lines = open(tmp_path, encoding='utf-8').read().split('\n')
        start = max(0, line_num - 6)
        end = min(len(lines), line_num + 3)
        print(f'\nContext around error line {line_num}:')
        for i in range(start, end):
            marker = '>>>' if i == line_num-1 else '   '
            print(f'{marker} L{i+1}: {lines[i][:120]}')
else:
    print('No syntax errors found!')

os.unlink(tmp_path)
