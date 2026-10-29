#!/usr/bin/env python3
"""Source-bounded fixed-lut-v2 literal empty-output import/checker candidate.

Keep fixed-lut-v1/default import behavior. For v2, preserve only a plain LUT's
literal, annotated [] output as a null-net PORT_OUT. Missing, unknown, constant,
multi-bit, malformed, wrong-direction or unannotated live outputs fail. No
net/driver/sink, parameters, LUT function, placement or connected port changes.
This is a build candidate, not native qualification or full-route admission.
"""
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_imported_placement_checker as builder

PROFILE = 'fixed-lut-v2'
FRONTEND = builder.TAG_SOURCE.parents[3] / 'frontend/json_frontend.cc'
FRONTEND_OBJECT = builder.CMAKE / '__/frontend/json_frontend.cc.o'
HOOK = '    GenericFrontend<JsonFrontendImpl>(ctx, JsonFrontendImpl(root), /*split_io=*/true)();\n'
PRE_IMPORT = '''    // Opt-in verification profile: preserve literal empty output metadata,
    // not a new circuit connection. Reuse this reader's existing JSON DOM.
    const bool rknpu_empty_output_profile =
            ctx->args.options.count("rknpu-check-imported-placement") &&
            ctx->args.options.at("rknpu-check-imported-placement").as<std::string>() == "fixed-lut-v2";
    std::vector<std::pair<std::string, std::string>> rknpu_empty_outputs;
    if (rknpu_empty_output_profile) {
        if (ctx->args.device != "xc7k480tffg1156-2" || root.object_items().size() != 1)
            log_error("RKNPU empty-output import: requires one flat exact-target module.\\n");
        const auto &module = root.object_items().begin()->second;
        for (const auto &entry : module["cells"].object_items()) {
            const auto &cell = entry.second;
            if (cell["type"].string_value() != "SLICE_LUTX")
                continue;
            const auto &attrs = cell["attributes"];
            std::string kind = attrs["X_ORIG_TYPE"].string_value();
            if (kind.size() != 4 || kind.substr(0, 3) != "LUT" || kind[3] < '1' || kind[3] > '6' ||
                attrs.object_items().count("X_LUT_AS_DRAM") || attrs.object_items().count("X_LUT_AS_SRL"))
                log_error("RKNPU empty-output import: unsupported logical LUT resource.\\n");
            int logical_outputs = 0;
            for (const std::string pin : {"O5", "O6"}) {
                auto connection = cell["connections"].object_items().find(pin);
                auto annotation = attrs.object_items().find("X_ORIG_PORT_" + pin);
                bool mapped = annotation != attrs.object_items().end() && annotation->second.string_value() == "O";
                if (annotation != attrs.object_items().end() && !mapped)
                    log_error("RKNPU empty-output import: invalid literal LUT output mapping.\\n");
                if (connection == cell["connections"].object_items().end()) {
                    if (mapped)
                        log_error("RKNPU empty-output import: missing literal LUT output declaration.\\n");
                    continue;
                }
                const auto &bits = connection->second;
                if (!bits.is_array() || cell["port_directions"][pin].string_value() != "output" ||
                    bits.array_items().size() > 1 ||
                    (!bits.array_items().empty() &&
                     (!mapped || !bits[0].is_number() || bits[0].number_value() != bits[0].int_value() ||
                      bits[0].int_value() < 2)))
                    log_error("RKNPU empty-output import: invalid literal LUT output declaration.\\n");
                if (mapped) {
                    ++logical_outputs;
                    if (bits.array_items().empty())
                        rknpu_empty_outputs.emplace_back(entry.first, pin);
                }
            }
            if (logical_outputs != 1)
                log_error("RKNPU empty-output import: requires one annotated logical LUT output.\\n");
        }
    }
'''
POST_IMPORT = '''    if (rknpu_empty_output_profile) {
        for (const auto &declaration : rknpu_empty_outputs) {
            auto imported = ctx->cells.find(ctx->id(declaration.first));
            if (imported == ctx->cells.end() || imported->second->type != ctx->id("SLICE_LUTX"))
                log_error("RKNPU empty-output import: changed flat cell identity.\\n");
            CellInfo *ci = imported->second.get();
            IdString pin = ctx->id(declaration.second);
            if (ci->ports.count(pin))
                log_error("RKNPU empty-output import: unexpectedly existing empty output port.\\n");
            ci->addOutput(pin);
            if (ci->getPort(pin) || ci->ports.at(pin).type != PORT_OUT)
                log_error("RKNPU empty-output import: changed empty output contract.\\n");
        }
        log_info("RKNPU empty-output import: preserved %zu literal disconnected LUT outputs; connected graph unchanged.\\n",
                 rknpu_empty_outputs.size());
    }
'''
OLD_PROFILE = '''        if (ctx->args.options.at("rknpu-check-imported-placement").as<std::string>() != "fixed-lut-v1")
'''
NEW_PROFILE = '''        const std::string imported_profile =
                ctx->args.options.at("rknpu-check-imported-placement").as<std::string>();
        if (imported_profile != "fixed-lut-v1" && imported_profile != "fixed-lut-v2")
'''
OLD_OUTPUT = '''                if (!ci->getPort(output) || ci->ports.at(output).type != PORT_OUT || out == ci->attrs.end() ||
                    out->second.as_string() != "O")
'''
NEW_OUTPUT = '''                // Only v2's literal JSON import preserves declared [] ports.
                // Its reader rejects absent, unknown and non-array declarations.
                bool declared_empty = imported_profile == "fixed-lut-v2" && !ci->getPort(output) &&
                                      ci->ports.count(output) && ci->ports.at(output).type == PORT_OUT;
                if ((!ci->getPort(output) && !declared_empty) || !ci->ports.count(output) ||
                    ci->ports.at(output).type != PORT_OUT || out == ci->attrs.end() || out->second.as_string() != "O")
'''
OLD_CARRY = '                    if (local_carry && di_feed->users.entries() == 1) {\n'
NEW_CARRY = '                    if (local_carry && di_feed && di_feed->users.entries() == 1) {\n'


def frontend_source(original):
    assert original == FRONTEND.read_text() and original.count(HOOK) == 1
    modified = original.replace(HOOK, PRE_IMPORT + HOOK + POST_IMPORT)
    assert modified.replace(PRE_IMPORT + HOOK + POST_IMPORT, HOOK) == original
    assert modified.count('NPNR_ASSERT') == original.count('NPNR_ASSERT')
    for forbidden in ('connectPort', 'disconnectPort', 'ctx->nets[', '->attrs[', '->params[', 'bindBel', 'unbindBel'):
        assert forbidden not in PRE_IMPORT + POST_IMPORT
    return modified


def checker_template(original):
    result = original
    for old, new in ((OLD_PROFILE, NEW_PROFILE), (OLD_OUTPUT, NEW_OUTPUT), (OLD_CARRY, NEW_CARRY)):
        assert result.count(old) == 1, 'Unpinned qualified checker source'
        result = result.replace(old, new)
    restored = result
    for old, new in ((OLD_PROFILE, NEW_PROFILE), (OLD_OUTPUT, NEW_OUTPUT), (OLD_CARRY, NEW_CARRY)):
        restored = restored.replace(new, old)
    assert restored == original
    builder.checked_source(builder.TAG_SOURCE.read_text(), result)
    return result


def literal_outputs(cell):
    """Software model of new source declaration validation; never an input fixup."""
    assert cell['type'] == 'SLICE_LUTX'
    attrs = cell['attributes']
    assert re.fullmatch('LUT[1-6]', attrs['X_ORIG_TYPE'])
    assert not {'X_LUT_AS_DRAM', 'X_LUT_AS_SRL'} & set(attrs)
    empties, outputs = [], 0
    for pin in ('O5', 'O6'):
        key = 'X_ORIG_PORT_' + pin
        mapped = attrs.get(key) == 'O'
        assert key not in attrs or mapped
        if pin not in cell['connections']:
            assert not mapped
            continue
        bits = cell['connections'][pin]
        assert type(bits) is list and len(bits) <= 1 and cell['port_directions'].get(pin) == 'output'
        assert not bits or (mapped and type(bits[0]) is int and bits[0] >= 2)
        if mapped:
            outputs += 1
            if not bits: empties.append(pin)
    assert outputs == 1
    return empties
