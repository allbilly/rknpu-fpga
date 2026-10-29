// NVDLA Open Source Project
// Copyright(c) 2016 - 2017 NVIDIA Corporation. Licensed under the
// NVDLA Open Hardware License; see LICENSE.NVDLA.
// cal_fp16_booth below is extracted unchanged. Only this standalone driver
// and includes/macros replace the surrounding SystemC class infrastructure.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#define LOG_DETAIL 0
#define FAIL(x) throw std::runtime_error("donor FAIL")
    inline void cal_fp16_booth(uint32_t res_sign, uint32_t wt_mts, uint32_t dat_mts, uint32_t sum_exp_sft, int32_t *mts_product) {
        int32_t     booth_code;
        int32_t     code_rev;
        uint32_t    booth_pp[8];
        int32_t     booth_inv[8];
        uint32_t    csa_pp[10];
        uint32_t    csa_sum, csa_carry;
        int32_t     i, j, k;
        int32_t     cur_pp, cur_group, st;
        uint32_t    sign_comp;
        int64_t     sum;

        *mts_product = 0;
#if LOG_DETAIL
        cslDebug((70, "[FP16_BOOTH]: wt_mts = 0x%04x, dat_mts = 0x%04x, sign = %d, sum_exp_sft = %d\n", wt_mts, dat_mts, res_sign, sum_exp_sft));
#endif

        if(sum_exp_sft >= 32) {
#if LOG_DETAIL
            cslDebug((70, "[FP16_BOOTH]: pp_0_sft = 0x00000000, pp_1_sft = 0x00000000\n"));
            cslDebug((70, "[FP16_MUL]: Booth result = 0x00000000, sign_comp = 0x00000000\n"));
#endif
            return;
        }

        code_rev = res_sign ? 0x7 : 0x0;
        wt_mts = wt_mts << 1;
        for(i = 0; i < 8; i ++) {
            booth_code = (wt_mts & 0x7) ^ code_rev;
            wt_mts = wt_mts >> 2;
            switch(booth_code) {
                case 0:
                case 7:
                    booth_pp[i] = 0x10000;
                    booth_inv[i] = 0;
                    break;

                case 1:
                case 2:
                    booth_pp[i] = dat_mts | 0x10000;
                    booth_inv[i] = 0;
                    break;

                case 3:
                    booth_pp[i] = (dat_mts << 1) | 0x10000;
                    booth_inv[i] = 0;
                    break;

                case 4:
                    booth_pp[i] = ~(dat_mts << 1) & 0xffff;
                    booth_inv[i] = 1;
                    break;

                case 5:
                case 6:
                    booth_pp[i] = ~dat_mts & 0xffff;
                    booth_inv[i] = 1;
                    break;

                default:
                    FAIL(("Invalid case when booth coding, booth_code = %d\n", booth_code)); 
            }
#if LOG_DETAIL
            //cslDebug((50, "[FP16_BOOTH]: booth_code[%02d] = %x, booth_pp[%02d] = %08x, booth_inv[%02d] = %d\n", i, booth_code, i, booth_pp[i], i, booth_inv[i]));
#endif
        }

        csa_pp[0] = booth_pp[0];
        csa_pp[1] = (booth_pp[1] << 2) | (booth_inv[0] << 0);
        csa_pp[2] = (booth_pp[2] << 4) | (booth_inv[1] << 2);
        csa_pp[3] = (booth_pp[3] << 6) | (booth_inv[2] << 4);
        csa_pp[4] = (booth_inv[3] << 6);
        csa_pp[5] = (booth_pp[4] << 8);
        csa_pp[6] = (booth_pp[5] << 10) | (booth_inv[4] << 8);
        csa_pp[7] = (booth_pp[6] << 12) | (booth_inv[5] << 10);
        csa_pp[8] = (booth_pp[7] << 14) | (booth_inv[6] << 12);
        csa_pp[9] = (booth_inv[7] << 14);

#if LOG_DETAIL
        //for(i = 0; i < 10; i ++) {
        //    cslDebug((50, "[FP16_BOOTH]: csa_pp[%02d] = %08x\n", i, csa_pp[i]));
        //}
#endif

        for(i = 0; i < 3; i ++) {
            if(i == 0) {
                cur_pp = 5;
                st = 0;
            } else if(i == 1) {
                cur_pp = 5;
                st = 5;
            } else {
                csa_pp[2] = csa_pp[5];
                csa_pp[3] = csa_pp[6];
                cur_pp = 4;
                st = 0;
            }

            while(cur_pp >= 3) {
                cur_group = int(cur_pp / 3);
                for(j = 0; j < cur_group; j ++) {
                    csa_sum = csa_pp[st+j*3] ^ csa_pp[st+j*3+1] ^ csa_pp[st+j*3+2];
                    csa_carry = (csa_pp[st+j*3] & csa_pp[st+j*3+1]) |
                                (csa_pp[st+j*3+1] & csa_pp[st+j*3+2]) |
                                (csa_pp[st+j*3+0] & csa_pp[st+j*3+2]);
                    csa_carry = (csa_carry << 1);
                    csa_pp[st+j*2] = csa_sum;
                    csa_pp[st+j*2+1] = csa_carry;
                }
                for(j = cur_group*3; j < cur_pp; j ++) {
                    k = j - cur_group;
                    csa_pp[st+k] = csa_pp[st+j];
                }
                cur_pp -= cur_group;
            }
        }

#if LOG_DETAIL
        //cslDebug((50, "[FP16_BOOTH]: pp_0 = 0x%08x, pp_1 = 0x%08x\n", csa_pp[0], csa_pp[1]));
#endif
        csa_pp[0] = (csa_pp[0] >> sum_exp_sft);
        csa_pp[1] = (csa_pp[1] >> sum_exp_sft);

        if(sum_exp_sft > 28) {
            sign_comp = 0;
        } else if(sum_exp_sft == 28) {
            sign_comp = 0xfffffffb;
        } else if(sum_exp_sft == 24) {
            sign_comp = 0xffffffab;
        } else if(sum_exp_sft == 20) {
            sign_comp = 0xfffffaab;
        } else if(sum_exp_sft == 16) {
            sign_comp = 0xffffaaab;
        } else if(sum_exp_sft == 12) {
            sign_comp = 0xfffaaab0;
        } else if(sum_exp_sft == 8) {
            sign_comp = 0xffaaab00;
        } else if(sum_exp_sft == 4) {
            sign_comp = 0xfaaab000;
        } else if(sum_exp_sft == 0) {
            sign_comp = 0xaaab0000;
        } else {
            FAIL(("FP16 shift error! sum_exp_sft = %d\n", sum_exp_sft)); 
        }

#if LOG_DETAIL
        cslDebug((70, "[FP16_BOOTH]: pp_0_sft = 0x%08x, pp_1_sft = 0x%08x\n", csa_pp[0], csa_pp[1]));
        cslDebug((70, "[FP16_MUL]: Booth result = 0x%08x, sign_comp = 0x%08x\n", (csa_pp[0]+csa_pp[1]), sign_comp));
#endif
        sum = csa_pp[0] + csa_pp[1] + sign_comp;
        sum = sum & 0x00000000ffffffff;

        if(sum >= 0x80000000) {
            sum = sum - 0x100000000;
        }
        *mts_product = sum;
    }


int main() {
    uint32_t sign,weight,data,shift;
    while (std::cin >> sign >> weight >> data >> shift) {
        int32_t result;
        cal_fp16_booth(sign,weight,data,shift,&result);
        std::cout << result << '\n';
    }
    if (!std::cin.eof()) return 2;
}
