import json
from collections import Counter

def main():
    with open('cache.json') as fh:
        data = json.load(fh)

    svcs = set()
    svc_map = {}
    for c in data:
        for s in c['service_changes']:
            svcs.add((s['name'], s['title']))
            svc_map[s['name']] = ''

#    import pprint
#    pprint.pprint(sorted(svcs))
#    print(len(svcs))

    print(json.dumps({s: '' for s in sorted(svc_map)}, indent=2))

if __name__ == '__main__':
    main()
