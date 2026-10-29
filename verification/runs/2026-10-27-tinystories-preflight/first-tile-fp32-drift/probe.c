#define TESTING
#include "run.c"
int main(int argc,char**argv){if(argc!=2)return 2;Transformer t;build_transformer(&t,argv[1]);float x[64],y[32];rmsnorm(x,t.weights.token_embedding_table+64,t.weights.rms_att_weight,64);matmul(y,x,t.weights.wq,64,32);int ok=fwrite(y,sizeof(float),32,stdout)==32;free_transformer(&t);return ok?0:3;}
