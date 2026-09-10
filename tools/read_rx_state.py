import iio,json
contexts=iio.scan_contexts();print(contexts)
uri=next((u for u in contexts if u.startswith('ip:')),next(iter(contexts),None))
if uri:
    ctx=iio.Context(uri);ctx.set_timeout(1200)
    dev=ctx.find_device('ad9361-phy')
    out={}
    for name,output,attrs in [('voltage0',False,['hardwaregain','gain_control_mode','rf_bandwidth','rf_port_select','sampling_frequency','rssi']),('altvoltage0',True,['frequency'])]:
        ch=dev.find_channel(name,output)
        out[name]={a:ch.attrs[a].value for a in attrs if a in ch.attrs}
    print(json.dumps(out,indent=2))
