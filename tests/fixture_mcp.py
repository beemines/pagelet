"""Synthetic stdio server for the book-details adapter; no network."""
import json
import sys
import time
import os

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
initialized = False
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}}}),flush=True)
    elif request.get('method') == 'notifications/initialized':
        initialized = True
    elif request.get('method') == 'tools/call':
        if os.environ.get('FIXTURE_COUNTER_FILE'):
            with open(os.environ['FIXTURE_COUNTER_FILE'],'a',encoding='utf-8') as counter:counter.write('details\n')
        assert initialized
        assert request['params']['name'] == 'get_book'
        ref = request['params']['arguments']['id']
        if ref == '99:timeout':
            time.sleep(5)
        elif ref == '98:error':
            result = {'isError':True,'content':[{'type':'text','text':'not logged in'}]}
        else:
            result = {'structuredContent':{'id':ref,'name':'测试图书','description':'<p>简介第一段。</p><script>evil()</script><p>第二段 &amp; 目录</p>','isbn':'9780000000000','pages':'240'},'content':[]}
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result},ensure_ascii=False),flush=True)
