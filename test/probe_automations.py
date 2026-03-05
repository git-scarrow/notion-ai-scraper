#!/usr/bin/env python3
"""Dump all automations and actions for a Notion database via loadPageChunk."""
import sys, json, urllib.request, urllib.error
sys.path.insert(0, 'cli')
from cookie_extract import get_token_v2

token = get_token_v2()
space_id = 'f04bc8a1-18df-42d1-ba9f-961c491cdc1b'
db_page_id = '9280bc78-8c6b-4133-bd7e-0feab27eb5c0'

def post(endpoint, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f'https://www.notion.so/api/v3/{endpoint}',
        data=data,
        headers={'Content-Type': 'application/json', 'Cookie': f'token_v2={token}',
                 'notion-client-name': 'web'})
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        return (json.loads(raw) if raw else {}), e.code

r, s = post('loadPageChunk', {
    'pageId': db_page_id,
    'limit': 100,
    'cursor': {'stack': []},
    'chunkNumber': 0,
    'verticalColumns': False,
})

automations = r.get('recordMap', {}).get('automation', {})
actions = r.get('recordMap', {}).get('automation_action', {})

print(f'Found {len(automations)} automation(s), {len(actions)} action(s)\n')

for aid, arec in automations.items():
    av = arec.get('value', {})
    print(f'── Automation: {aid}')
    print(f'   enabled:     {av.get("enabled")}')
    print(f'   trigger:     {json.dumps(av.get("trigger"), indent=6)}')
    # Find actions belonging to this automation
    my_actions = [v['value'] for v in actions.values()
                  if v.get('value', {}).get('parent_id') == aid]
    print(f'   actions ({len(my_actions)}):')
    for act in my_actions:
        print(f'     [{act.get("type")}]  id={act.get("id")}')
        print(f'       config: {json.dumps(act.get("config"), indent=9)}')
    print()
