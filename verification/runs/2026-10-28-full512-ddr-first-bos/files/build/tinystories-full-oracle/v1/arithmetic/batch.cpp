
#include "donor.cpp"
extern "C" int rknpu_booth_batch(const uint32_t* tuples,uint32_t count,int32_t* output) {
    try {
        for(uint32_t i=0;i<count;i++) {
            const uint32_t* t=tuples+4*i;
            if(t[0]>1 || (t[3]<32 && t[3]%4!=0)) return 1;
            cal_fp16_booth(t[0],t[1],t[2],t[3],output+i);
        }
    } catch(...) {return 2;}
    return 0;
}
