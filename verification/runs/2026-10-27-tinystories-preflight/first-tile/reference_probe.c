#define TESTING
#include "run.c"
int main(int argc,char**argv) {
 if(argc!=2)return 2; Transformer t; build_transformer(&t,argv[1]);
 if(t.config.dim!=64||t.config.n_layers!=5)return 3; float values[64];
 rmsnorm(values,t.weights.token_embedding_table+64,t.weights.rms_att_weight,64);
 int ok=fwrite(values,sizeof(float),64,stdout)==64; free_transformer(&t);return ok?0:4; }
