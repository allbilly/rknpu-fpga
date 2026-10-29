"""Test-only dyadic FP44/FP48 reference, extracted from the donor audit oracle.

Never used to execute or repair an FPGA workload. Nearest/ties-away follows
the selected NVIDIA donor, not a claim of verified RK exceptional behavior.
"""
def signed(value,width):
    value &= (1<<width)-1
    return value-(1<<width) if value>>(width-1) else value

def round_away(value,shift):
    """Quantize nonnegative integer at a binary scale; ties away from zero."""
    if shift<=0:return value<<(-shift)
    q,r=divmod(value,1<<shift)
    return q+(2*r >= 1<<shift)

def normalize(value,scale):
    if not value:return 0
    shift=abs(value).bit_length()-39
    mant=round_away(abs(value),shift)
    scale+=shift
    if mant==1<<39:mant>>=1;scale+=1
    if value<0:
        if mant==1<<38:mant<<=1;scale-=1
        mant=-mant
    expo=scale+101
    assert 0<=expo<255,(value,scale,expo)
    assert (mant<0 and -(1<<39)<=mant<-(1<<38)) or (1<<38)<=mant<(1<<39)
    return (expo<<40)|(mant&((1<<40)-1))

def final(bits):
    expo=bits>>40;mant=signed(bits,40)
    if expo==255:return ((bits>>39&1)<<31)|0x7f800000|(bits>>29&1023)
    if not mant:return 0
    scale=expo-101;shift=abs(mant).bit_length()-24
    significand=round_away(abs(mant),shift);scale+=shift
    if significand==1<<24:significand>>=1;scale+=1
    encoded_exponent=scale+23+127
    assert 0<encoded_exponent<255
    return ((mant<0)<<31)|(encoded_exponent<<23)|(significand&0x7fffff)

def add(data,op,valid):
    if not valid:op=0
    de=data>>38;oe=op>>40
    if oe==255:return (255<<40)|(op&(((1<<11)-1)<<29))
    if de==63:return (255<<40)|((data>>27&2047)<<29)
    dm=signed(data,38);om=signed(op,40)
    assert -(1<<35)<=dm<(1<<35)
    ds,os=de-50,oe-101
    scale=min(ds,os)
    return normalize((dm<<(ds-scale))+(om<<(os-scale)),scale)

def datum(mant,expo):
    assert -(1<<35)<=mant<(1<<35) and 0<=expo<=62
    return (expo<<38)|(mant&((1<<38)-1))
