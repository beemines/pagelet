"""Controlled process for CLI contract tests; never contacts a book service."""
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
if args[0] == 'mcp':
    import runpy
    runpy.run_path(str(Path(__file__).with_name('fixture_mcp.py')),run_name='__main__')
elif args[0] == 'search':
    query = args[1]
    if os.environ.get('FIXTURE_COUNTER_FILE'):
        with open(os.environ['FIXTURE_COUNTER_FILE'],'a',encoding='utf-8') as counter:counter.write('search\n')
    if os.environ.get('FIXTURE_DEMO'):
        time.sleep(2)
    if query == 'fail':
        print('session expired or was revoked', file=sys.stderr)
        sys.exit(3)
    if query == 'timeout':
        time.sleep(3)
    books=[{'id': '42:abc', 'name': query, 'authors': ['测试作者'],
                               'extension': 'epub', 'language': 'Chinese', 'cover':'',
                               'url':'https://example.com/book/42/abc'}]
    if os.environ.get('FIXTURE_DEMO'):
        books += [{'id':'43:pdf','name':'PDF 示例 · '+query,'authors':['测试作者'],'extension':'pdf'},
                  {'id':'44:unknown','name':'未知大小示例','authors':['测试作者'],'extension':'mobi'}]
    print(json.dumps({'books': books,
                      'page': int(args[args.index('--page') + 1]), 'total_pages': 2}, ensure_ascii=False))
elif args[0] == 'doctor':
    print(json.dumps([{'domain': 'https://example.com', 'final_url': 'https://example.com/eapi/info/domains', 'status': 'healthy'}]))
elif args[0] == 'profile':
    print(json.dumps({'name': 'Fixture', 'quota_known': True, 'daily_remaining': 5, 'daily_allowed': 10}))
elif args[0] == 'config':
    print(json.dumps([{'key': 'ZLIB_DOMAIN', 'value': os.environ.get('FIXTURE_DEFAULT_DOMAIN', '')}]))
elif args[0] == 'download':
    time.sleep(.2)
    if args[1] == '99:bad':
        print('download quota exceeded https://example.com/file?token=signed-secret', file=sys.stderr)
        sys.exit(1)
    partial=Path(args[args.index('--dir')+1])/'.zlib-fixture.part'
    partial.write_bytes(b'incomplete fixture')
    if args[1] in ('45:hang','46:hang'):
        time.sleep(5)
    print('Downloading: fixture',file=sys.stderr,flush=True)
    if args[1] == '44:unknown':
        print('  5.0 MB',file=sys.stderr,flush=True)
        if os.environ.get('FIXTURE_DEMO'):time.sleep(4)
    else:
        for percent in [10,40,80,100]:
            print(f'  {percent}% ({percent/10:.1f} MB / 10.0 MB)',file=sys.stderr,flush=True)
            time.sleep(1.7 if os.environ.get('FIXTURE_DEMO') else .08)
    target = Path(args[args.index('--dir') + 1]) / 'fixture.epub'
    target.write_bytes(b'fixture book')
    partial.unlink(missing_ok=True)
    print(json.dumps({'id': args[1], 'path': str(target), 'size': 12}))
else:
    sys.exit(2)
