from concurrent.futures import ThreadPoolExecutor
import json,urllib.request,urllib.parse
symbols=['^TNX','CL=F','^KS11','005930.KS','000660.KS','603004.SS','BTC-USD','XAUUSD=X','XAGUSD=X']
def probe(s):
 try:
  url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(s,safe='')+'?interval=1m&range=1d&includePrePost=true'
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=8) as r: d=json.load(r)['chart']['result'][0]['meta']
  return {k:d.get(k) for k in ['symbol','shortName','instrumentType','exchangeTimezoneName','currency','regularMarketPrice']}
 except Exception as e: return {'symbol':s,'error':str(e)}
with ThreadPoolExecutor(max_workers=4) as pool:
 for result in pool.map(probe,symbols): print(json.dumps(result,ensure_ascii=False))
