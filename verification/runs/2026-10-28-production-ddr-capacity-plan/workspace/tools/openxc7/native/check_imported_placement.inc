    // Isolated verification-only addition. The ordinary placer, tags, graph,
    // routing and FASM code are unchanged when this opt-in check is absent.
    if (ctx->args.options.count("rknpu-check-imported-placement")) {
        if (ctx->args.options.at("rknpu-check-imported-placement").as<std::string>() != "fixed-lut-v1")
            log_error("RKNPU imported placement scan: unsupported profile.\n");
        if (!rknpu_imported_placement || ctx->args.device != "xc7k480tffg1156-2")
            log_error("RKNPU imported placement scan: requires an imported exact-target placement.\n");
        if (ctx->settings.count(ctx->id("route")) && ctx->settings.at(ctx->id("route")).as_int64() != 0)
            log_error("RKNPU imported placement scan: routed exports are not checkpoint inputs.\n");
        ctx->check();
        log_info("RKNPU imported placement scan: begin before clock/general routing.\n");
        int checked_cells = 0, checked_pairs = 0;
        {
            // Restore every tag and invalidate validity caches even if a
            // check throws. Never disconnect or rewrite a circuit port.
            struct VerificationTags {
                XilinxImpl *self;
                std::vector<XilinxCellTags> saved;
                explicit VerificationTags(XilinxImpl *p) : self(p), saved(p->cell_tags) {}
                ~VerificationTags()
                {
                    self->cell_tags.swap(saved);
                    for (auto &ts : self->tile_status) {
                        if (!ts.lts)
                            continue;
                        for (auto &e : ts.lts->eights)
                            e.dirty = true;
                        for (auto &h : ts.lts->halfs)
                            h.dirty = true;
                    }
                }
            } verification(this);
            NetInfo *vcc = nullptr;
            auto vcc_entry = ctx->nets.find(ctx->id("$PACKER_VCC_NET"));
            if (vcc_entry != ctx->nets.end())
                vcc = vcc_entry->second.get();
            if (!vcc || !vcc->driver.cell || vcc->driver.cell->type != ctx->id("PSEUDO_VCC") ||
                vcc->driver.port != ctx->id("Y"))
                log_error("RKNPU imported placement scan: missing actual VCC pseudo-driver.\n");
            auto check_logical_lut = [&](CellInfo *ci, IdString output) {
                auto original = ci->attrs.find(ctx->id("X_ORIG_TYPE"));
                if (original == ci->attrs.end())
                    log_error("RKNPU imported placement scan: missing logical LUT kind.\n");
                std::string kind = original->second.as_string();
                if (kind.size() != 4 || kind.substr(0, 3) != "LUT" || kind[3] < '1' || kind[3] > '5')
                    log_error("RKNPU imported placement scan: unsupported paired logical LUT kind.\n");
                int width = kind[3] - '0';
                std::set<std::string> logical;
                for (IdString pin : {id_A1, id_A2, id_A3, id_A4, id_A5}) {
                    auto annotation = ci->attrs.find(ctx->idf("X_ORIG_PORT_%s", pin.c_str(ctx)));
                    NetInfo *net = ci->getPort(pin);
                    if (!net) {
                        if (annotation != ci->attrs.end() && !annotation->second.as_string().empty())
                            log_error("RKNPU imported placement scan: annotated disconnected input.\n");
                        continue;
                    }
                    if (!ci->ports.count(pin) || ci->ports.at(pin).type != PORT_IN || annotation == ci->attrs.end())
                        log_error("RKNPU imported placement scan: missing logical input annotation/direction.\n");
                    std::vector<std::string> tokens;
                    boost::split(tokens, annotation->second.as_string(), boost::is_any_of(" "), boost::token_compress_on);
                    for (const auto &token : tokens) {
                        if (token.size() != 2 || token[0] != 'I' || token[1] < '0' || token[1] >= '0' + width ||
                            !logical.insert(token).second)
                            log_error("RKNPU imported placement scan: invalid/repeated logical input mapping.\n");
                    }
                }
                if (int(logical.size()) != width)
                    log_error("RKNPU imported placement scan: incomplete logical input mapping.\n");
                auto out = ci->attrs.find(ctx->idf("X_ORIG_PORT_%s", output.c_str(ctx)));
                if (!ci->getPort(output) || ci->ports.at(output).type != PORT_OUT || out == ci->attrs.end() ||
                    out->second.as_string() != "O")
                    log_error("RKNPU imported placement scan: changed logical output mapping.\n");
            };
            for (auto &ts : tile_status) {
                if (!ts.lts)
                    continue;
                auto &lt = *ts.lts;
                for (int z = 0; z < 8; ++z) {
                    CellInfo *lower = lt.cells[(z << 4) | BEL_5LUT];
                    if (!lower)
                        continue;
                    auto &l5 = cell_tags.at(lower->flat_index).lut;
                    if (lower->type != id_SLICE_LUTX || l5.is_memory || l5.is_srl)
                        log_error("RKNPU imported placement scan: unsupported 5LUT resource profile.\n");
                    if (lower->getPort(id_A6))
                        log_error("RKNPU imported placement scan: connected 5LUT A6.\n");
                    CellInfo *upper = lt.cells[(z << 4) | BEL_6LUT];
                    if (!upper)
                        continue;
                    auto &l6 = cell_tags.at(upper->flat_index).lut;
                    if (upper->type != id_SLICE_LUTX || l6.is_memory || l6.is_srl)
                        log_error("RKNPU imported placement scan: unsupported paired resource profile.\n");
                    check_logical_lut(lower, id_O5);
                    check_logical_lut(upper, id_O6);
                    if (lower->getPort(id_O6) || upper->getPort(id_O5) ||
                        upper->getPort(id_A6) != vcc || !upper->ports.count(id_A6) ||
                        upper->ports.at(id_A6).type != PORT_IN || upper->attrs.count(ctx->id("X_ORIG_PORT_A6")))
                        log_error("RKNPU imported placement scan: wrong paired output/A6 mode contract.\n");
                    std::set<NetInfo *> shared;
                    for (IdString pin : {id_A1, id_A2, id_A3, id_A4, id_A5}) {
                        NetInfo *a = lower->getPort(pin), *b = upper->getPort(pin);
                        if (a && b && a != b)
                            log_error("RKNPU imported placement scan: different nets on a shared physical pin.\n");
                        if (a)
                            shared.insert(a);
                        if (b)
                            shared.insert(b);
                    }
                    if (shared.size() > 5)
                        log_error("RKNPU imported placement scan: more than five shared physical inputs.\n");
                    // A6 is the verified physical mode selector, not a sixth
                    // shared signal. Change this tag's input view ONLY; all
                    // other fields, lower tags and actual wires stay intact.
                    l6.input_count = 0;
                    for (IdString pin : {id_A1, id_A2, id_A3, id_A4, id_A5}) {
                        NetInfo *net = upper->getPort(pin);
                        if (net)
                            l6.input_sigs[l6.input_count++] = net;
                    }
                    for (int i = l6.input_count; i < 6; ++i)
                        l6.input_sigs[i] = nullptr;
                    ++checked_pairs;
                }
                for (auto &e : lt.eights)
                    e.dirty = true;
                for (auto &h : lt.halfs)
                    h.dirty = true;
            }
            for (auto &entry : ctx->cells) {
                CellInfo *ci = entry.second.get();
                if (ci->bel == BelId() || ctx->getBoundBelCell(ci->bel) != ci)
                    log_error("RKNPU imported placement scan: unbound/mismatched cell.\n");
                if (!isBelLocationValid(ci->bel, true))
                    log_error("RKNPU imported placement scan: native BEL legality rejected %s.\n", ci->name.c_str(ctx));
                ++checked_cells;
            }
        }
        ctx->check();
        log_info("RKNPU imported placement scan: passed %d bound cells and %d fixed logic pairs; "
                 "original tags restored and caches invalidated.\n", checked_cells, checked_pairs);
    }
