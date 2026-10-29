"""Record actual native numeric scans; no arithmetic, retries or fabric reset."""
import datetime
import json
from tools.host.native_link import NativeLink


class RecordedNativeLink(NativeLink):
    def __init__(self,trace,*args,**kwargs):
        self.trace=trace;self.scans=0
        super().__init__(*args,**kwargs)

    def reset(self,*,deadline=None):
        self.trace.write(json.dumps(dict(event='TAP_RESET_NOT_FABRIC_RESET',utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))+'\n')
        self.trace.flush()
        return super().reset(deadline=deadline)

    def scan(self,value,bits=640,*,ir=False,deadline=None):
        event=dict(index=self.scans,bits=bits,ir=ir,tdi=f'{value:x}',utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        try:
            result=super().scan(value,bits,ir=ir,deadline=deadline)
            event['tdo']=f'{result:x}'
            return result
        except BaseException as error:
            event['error']=repr(error)
            raise
        finally:
            self.scans+=1;self.trace.write(json.dumps(event,separators=(',',':'))+'\n');self.trace.flush()
