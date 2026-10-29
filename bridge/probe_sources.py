import json,urllib.request
urls={
'yahoo':'https://query1.finance.yahoo.com/v8/finance/chart/WDC?interval=1m&range=1d&includePrePost=true',
'robinhood':'https://api.robinhood.com/quotes/WDC/',
'cnbc':'https://quote.cnbc.com/quote-html-webservice/quote.htm?symbols=WDC&requestMethod=itv&noform=1&fund=1&exthrs=1&output=json'}
for name,url in urls.items():
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
  with urllib.request.urlopen(req,timeout=15) as r: data=json.load(r)
  with open('runtime/probe-'+name+'.json','w') as f: json.dump(data,f)
  if name=='yahoo': print(name,json.dumps(data['chart']['result'][0]['meta']))
  else: print(name,json.dumps(data)[:4500])
 except Exception as e: print(name,type(e).__name__,str(e))
