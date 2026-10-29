// SPDX-License-Identifier: ISC
// Diagnostic-only replacement entrypoint. The production archcheck is not
// edited. Report the first failure in each category and ALWAYS fail this
// partial diagnostic: it must never qualify a chip database for routing.
#include "log.h"
#include "nextpnr.h"
#include <exception>

NEXTPNR_NAMESPACE_BEGIN
void Context::archcheck() const
{
    log_info("PARTIAL_NAME_AUDIT: diagnostic only, never an integrity pass.\n");
    unsigned long long checked = 0;
    for (BelId bel : getBels()) {
        ++checked;
        IdString name = getBelName(bel);
        BelId found = getBelByName(name);
        if (bel != found) {
            log_info("AUDIT_BEL_FAILURE after=%llu name=%s enumerated=(%d,%d) lookup=(%d,%d)\n",
                     checked, name.c_str(this), bel.tile, bel.index, found.tile, found.index);
            break;
        }
    }
    log_info("AUDIT_BEL_EXAMINED=%llu\n", checked);
    checked = 0;
    for (WireId wire : getWires()) {
        ++checked;
        IdString name = getWireName(wire);
        try {
            WireId found = getWireByName(name);
            if (wire != found) {
                log_info("AUDIT_WIRE_FAILURE after=%llu name=%s enumerated=(%d,%d) lookup=(%d,%d)\n",
                         checked, name.c_str(this), wire.tile, wire.index, found.tile, found.index);
                break;
            }
        } catch (const std::exception &error) {
            log_info("AUDIT_WIRE_EXCEPTION after=%llu name=%s reason=%s\n", checked, name.c_str(this), error.what());
            break;
        }
    }
    log_info("AUDIT_WIRE_EXAMINED=%llu\n", checked);
    checked = 0;
    for (PipId pip : getPips()) {
        ++checked;
        IdString name = getPipName(pip);
        try {
            PipId found = getPipByName(name);
            if (pip != found) {
                log_info("AUDIT_PIP_FAILURE after=%llu name=%s enumerated=(%d,%d) lookup=(%d,%d)\n",
                         checked, name.c_str(this), pip.tile, pip.index, found.tile, found.index);
                break;
            }
        } catch (const std::exception &error) {
            log_info("AUDIT_PIP_EXCEPTION after=%llu name=%s reason=%s\n", checked, name.c_str(this), error.what());
            break;
        }
    }
    log_info("AUDIT_PIP_EXAMINED=%llu\n", checked);
    checked = 0;
    for (BelId bel : getBels()) {
        ++checked;
        Loc loc = getBelLocation(bel);
        BelId found = getBelByLocation(loc);
        if (bel != found) {
            log_info("AUDIT_LOCATION_FAILURE after=%llu name=%s loc=(%d,%d,%d) enumerated=(%d,%d) lookup=(%d,%d)\n",
                     checked, getBelName(bel).c_str(this), loc.x, loc.y, loc.z,
                     bel.tile, bel.index, found.tile, found.index);
            break;
        }
    }
    log_info("AUDIT_LOCATION_EXAMINED=%llu\n", checked);
    log_error("PARTIAL_NAME_AUDIT_COMPLETE: not an architecture integrity pass.\n");
}
NEXTPNR_NAMESPACE_END
