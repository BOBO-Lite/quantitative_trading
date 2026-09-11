"""Normalize UI log duplication, validating every packet before releasing to runner."""
import ast, hashlib, json, sys
from pathlib import Path
from import_supermind_minute_probe import LINE, decode_packets
from simple_minute_cache import Cache

root=Path(__file__).resolve().parent
index=sys.argv[1]
source=root/f'raw_platform_log_{index}.txt'
raw=source.read_text(encoding='utf8')
assert 'TECH1_ENTRY_MINUTE_EXPORT_DONE' in raw
parts={};duplicates=[]
for line in raw.splitlines():
    line=line.strip().removeprefix('- generic: ')
    match=LINE.fullmatch(line)
    if not match:continue
    key=(match[1],match[2])
    if key in parts:
        assert parts[key]==line, 'Conflicting duplicate packet'
        duplicates.append(key)
    parts[key]=line
clean='\n'.join(parts.values())+'\nTECH1_ENTRY_MINUTE_EXPORT_DONE\n'
packets=decode_packets(clean)
tree=ast.parse((root/f'minute_probe_{index}.py').read_text(encoding='utf8'))
wanted=set(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REQUESTS' for t in n.targets)))
assert wanted=={(v['symbol'],v['date']) for k,v in packets.items() if k.startswith('minute_')}
assert {s for s,d in wanted}=={v['symbol'] for k,v in packets.items() if k.startswith('daily_')}
cache=Cache(packets)
audit=dict(raw_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),normalized_sha256=hashlib.sha256(clean.encode()).hexdigest(),duplicates=duplicates,packets=len(packets),stock_days=len(cache.minutes),method='Strip UI generic prefixes; remove exact packet-index duplicates; reject conflicts; validate packet hashes, request sets and daily/minute data')
(root/f'data_normalization_{index}.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
temp=root/f'minute_export_{index}.tmp';temp.write_text(clean,encoding='utf8');temp.replace(root/f'minute_export_{index}.txt')
print(json.dumps(dict(stock_days=len(cache.minutes),duplicates=len(duplicates))))
