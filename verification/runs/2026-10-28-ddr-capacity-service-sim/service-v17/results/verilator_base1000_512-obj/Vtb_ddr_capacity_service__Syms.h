// Verilated -*- C++ -*-
// DESCRIPTION: Verilator output: Symbol table internal header
//
// Internal details; most calling programs do not need this header,
// unless using verilator public meta comments.

#ifndef VERILATED_VTB_DDR_CAPACITY_SERVICE__SYMS_H_
#define VERILATED_VTB_DDR_CAPACITY_SERVICE__SYMS_H_  // guard

#include "verilated.h"

// INCLUDE MODEL CLASS

#include "Vtb_ddr_capacity_service.h"

// INCLUDE MODULE CLASSES
#include "Vtb_ddr_capacity_service___024root.h"

// SYMS CLASS (contains all model state)
class alignas(VL_CACHE_LINE_BYTES) Vtb_ddr_capacity_service__Syms final : public VerilatedSyms {
  public:
    // INTERNAL STATE
    Vtb_ddr_capacity_service* const __Vm_modelp;
    VlDeleter __Vm_deleter;
    bool __Vm_didInit = false;

    // MODULE INSTANCE STATE
    Vtb_ddr_capacity_service___024root TOP;

    // CONSTRUCTORS
    Vtb_ddr_capacity_service__Syms(VerilatedContext* contextp, const char* namep, Vtb_ddr_capacity_service* modelp);
    ~Vtb_ddr_capacity_service__Syms();

    // METHODS
    const char* name() const { return TOP.vlNamep; }
};

#endif  // guard
