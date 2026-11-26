"""Post-run cost correction audit; no controller imports or target execution."""
import argparse
import hashlib
import json
from pathlib import Path

def read(path): return json.loads(path.read_text(encoding='utf-8'))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',required=True); a=p.parse_args(); root=Path(a.root)
    first=read(root/'attempt2/analysis1/report.json'); final=read(root/'attempt3/analysis1/report.json')
    checks=[]
    def check(ok,label):
        checks.append(dict(check=label,passed=bool(ok)))
        assert ok,label
    check([(x['case'],x['method'],x['confirmed'],x['rows']) for x in first['details']]==
          [(x['case'],x['method'],x['confirmed'],x['rows']) for x in final['details']],'all 40 task outcomes unchanged')
    f2=read(root/'attempt2/freeze.json'); f3=read(root/'attempt3/freeze.json')
    check(f2['cases']==f3['cases'] and f2['methods']==f3['methods'] and f2['budget']==f3['budget'],'same conditions/methods/budget')
    for name in ['tool_v0_2/lifecycle.py','scripts/u02_native.py','scripts/u02_worker.py','scripts/verify_u02.py']:
        check(f2['files'][name]==f3['files'][name],'unchanged implementation '+name)
    # Check exact baseline patch, to exclude any additional query/retry logic.
    s2=(root/'attempt2/snapshots/scripts/u02_controllers.py').read_text(encoding='utf-8')
    s3=(root/'attempt3/snapshots/scripts/u02_controllers_r3.py').read_text(encoding='utf-8')
    old="action='wait' if len(events)<budget and host.capabilities()['executor_handle'] else 'pause'"
    new="action='wait' if len(events)<budget and host.capabilities()['executor_handle'] and not (events and events[-1]['body'].get('members') and all(m['terminal'] for m in events[-1]['body']['members'])) else 'pause'"
    check(s2.replace(old,new)==s3,'only ordinary waiting stop condition changed')
    for case in f3['cases']:
        key=case['id']+'_wait'; events=read(root/'attempt3'/key/'result.json')['events']
        for event in events[:-1]:
            members=event['body']['members']
            check(not members or not all(m['terminal'] for m in members),'no redundant wait after terminal '+key+str(event['seq']))
    check(first['methods']['wait']['actions']==28 and final['methods']['wait']['actions']==13,'corrected waiting cost')
    check(all(first['methods'][m]==final['methods'][m] for m in f3['methods'] if m!='wait'),'all other method metrics unchanged')
    out=root/'attempt3/analysis1/r3_comparison.json'
    with out.open('x',encoding='utf-8') as stream: json.dump(dict(passed=True,checks=checks),stream,indent=2); stream.write('\n')
    print(len(checks),'R3 comparison checks passed')

if __name__=='__main__': main()
