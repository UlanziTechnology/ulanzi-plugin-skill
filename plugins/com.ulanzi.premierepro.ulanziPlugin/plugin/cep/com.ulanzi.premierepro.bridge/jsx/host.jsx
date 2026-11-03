/* Premiere Pro CEP host. ES3 only: this file runs in ExtendScript, not Node.
 * Project saving, keyboard injection and preference changes are not performed.
 * Media output is written only by an explicitly requested export.
 * All host writes are serialized by the CEP client. See docs/HOST_API_NOTES.md.
 */
(function () {
    var TPS = 254016000000;
    var MATCH = "AE.ADBE Lumetri";
    var PARAMS = {
        exposure: {min: -5, max: 5, names: ["Exposure", "曝光", "曝光度", "Belichtung", "露光量", "Exposição", "Exposición", "노출"]},
        contrast: {min: -100, max: 100, names: ["Contrast", "对比度", "對比", "對比度", "Kontrast", "コントラスト", "Contraste", "대비"]},
        highlights: {min: -100, max: 100, names: ["Highlights", "高光", "亮部", "Lichter", "ハイライト", "Realces", "Iluminaciones", "밝은 영역", "밝은영역"]},
        shadows: {min: -100, max: 100, names: ["Shadows", "阴影", "陰影", "暗部", "Tiefen", "シャドウ", "Sombras", "어두운 영역", "어두운영역"]},
        saturation: {min: 0, max: 200, names: ["Saturation", "饱和度", "飽和度", "Sättigung", "彩度", "Saturação", "Saturación", "채도"]},
        temperature: {min: -100, max: 100, names: ["Temperature", "色温", "色溫", "Temperatur", "色温度", "Temperatura", "온도", "색온도"]},
        tint: {min: -100, max: 100, names: ["Tint", "色彩", "色调", "色調", "Färbung", "Tönung", "色かぶり補正", "Matiz", "Coloração", "Tonalidade", "색조"]},
        whites: {min: -100, max: 100, names: ["Whites", "白色", "白色色階", "Weiß", "Weißtöne", "白レベル", "Brancos", "Blancos", "흰색"]},
        blacks: {min: -100, max: 100, names: ["Blacks", "黑色", "黑色色階", "Schwarz", "Schwarztöne", "黒レベル", "Pretos", "Negros", "검정", "검정색", "검은색"]}
    };
    var ORDER = ["temperature", "tint", "saturation", "exposure", "contrast", "highlights", "shadows", "whites", "blacks"];
    var BASIC = ["Basic Correction", "基本校正", "基本補正", "基本修正", "Einfache Korrektur", "Grundkorrektur", "基本補正", "Correção básica", "Corrección básica", "기본 교정"];
    var CREATIVE = ["Creative", "创意", "創意", "Kreativ", "クリエイティブ", "Criativo", "Creativo", "크리에이티브"];

    function fail(code, message, details) {
        var e = new Error(message);
        e.code = code; e.details = details || {};
        throw e;
    }
    function own(o, key) { return Object.prototype.hasOwnProperty.call(o, key); }
    function count(o) {
        if (!o) { return 0; }
        if (typeof o.numItems === "number") { return o.numItems; }
        if (typeof o.numTracks === "number") { return o.numTracks; }
        return typeof o.length === "number" ? o.length : 0;
    }
    function normal(s) { return String(s).replace(/^\s+|\s+$/g, "").toLowerCase(); }
    function named(s, list) {
        for (var i = 0; i < list.length; i++) { if (normal(s) === normal(list[i])) { return true; } }
        return false;
    }
    function integer(v, field, limit) {
        if (typeof v !== "number" || !isFinite(v) || v !== Math.floor(v) || Math.abs(v) > limit) {
            fail("INVALID_REQUEST", field + " must be a bounded integer.", {field: field});
        }
        return v;
    }
    function scalar(v) { return typeof v === "number" && isFinite(v); }
    function sameClip(a, b) {
        return a === b || (a && b && a.nodeId !== undefined && b.nodeId !== undefined && String(a.nodeId) === String(b.nodeId));
    }

    // Decimal integer arithmetic avoids converting long Premiere tick strings to IEEE doubles.
    function ticks(v) {
        if (v && typeof v.ticks !== "undefined") { v = v.ticks; }
        var s = String(v);
        if (!/^-?\d+$/.test(s)) { fail("INVALID_TIME", "Premiere returned an invalid tick value."); }
        var neg = s.charAt(0) === "-";
        if (neg) { s = s.substring(1); }
        s = s.replace(/^0+(?=\d)/, "");
        return neg && s !== "0" ? "-" + s : s;
    }
    function neg(a) { a = ticks(a); return a === "0" ? a : (a.charAt(0) === "-" ? a.substring(1) : "-" + a); }
    function compareAbs(a, b) { return a.length !== b.length ? (a.length < b.length ? -1 : 1) : (a === b ? 0 : (a < b ? -1 : 1)); }
    function cmp(a, b) {
        a = ticks(a); b = ticks(b);
        var an = a.charAt(0) === "-", bn = b.charAt(0) === "-";
        if (an !== bn) { return an ? -1 : 1; }
        return (an ? -1 : 1) * compareAbs(an ? a.substring(1) : a, bn ? b.substring(1) : b);
    }
    function addAbs(a, b) {
        var i = a.length - 1, j = b.length - 1, carry = 0, result = "", n;
        while (i >= 0 || j >= 0 || carry) {
            n = (i >= 0 ? Number(a.charAt(i--)) : 0) + (j >= 0 ? Number(b.charAt(j--)) : 0) + carry;
            result = String(n % 10) + result; carry = Math.floor(n / 10);
        }
        return result || "0";
    }
    function subAbs(a, b) {
        var i = a.length - 1, j = b.length - 1, borrow = 0, result = "", n;
        while (i >= 0) {
            n = Number(a.charAt(i--)) - borrow - (j >= 0 ? Number(b.charAt(j--)) : 0);
            borrow = n < 0 ? 1 : 0;
            result = String(n < 0 ? n + 10 : n) + result;
        }
        return ticks(result);
    }
    function add(a, b) {
        a = ticks(a); b = ticks(b);
        var an = a.charAt(0) === "-", bn = b.charAt(0) === "-";
        var aa = an ? a.substring(1) : a, bb = bn ? b.substring(1) : b, c;
        if (an === bn) { return ticks((an ? "-" : "") + addAbs(aa, bb)); }
        c = compareAbs(aa, bb);
        if (!c) { return "0"; }
        return c > 0 ? ticks((an ? "-" : "") + subAbs(aa, bb)) : ticks((bn ? "-" : "") + subAbs(bb, aa));
    }
    function sub(a, b) { return add(a, neg(b)); }
    function mul(a, factor) {
        integer(factor, "tick multiplier", 100000000);
        a = ticks(a);
        var negative = (a.charAt(0) === "-") !== (factor < 0);
        if (a.charAt(0) === "-") { a = a.substring(1); }
        factor = Math.abs(factor);
        var carry = 0, s = "", n;
        for (var i = a.length - 1; i >= 0; i--) {
            n = Number(a.charAt(i)) * factor + carry;
            s = String(n % 10) + s; carry = Math.floor(n / 10);
        }
        if (carry) { s = String(carry) + s; }
        return ticks((negative ? "-" : "") + s);
    }
    function div(a, divisor) {
        a = ticks(a);
        if (a.charAt(0) === "-" || divisor < 1 || divisor > TPS) { fail("INVALID_TIME", "Invalid tick divisor."); }
        var result = "", remainder = 0, n;
        for (var i = 0; i < a.length; i++) {
            n = remainder * 10 + Number(a.charAt(i));
            result += String(Math.floor(n / divisor)); remainder = n % divisor;
        }
        return {quotient: ticks(result), remainder: remainder};
    }
    function time(t) { var v = new Time(); v.ticks = ticks(t); return v; }
    function clamp(t, lo, hi) { return cmp(t, lo) < 0 ? ticks(lo) : (cmp(t, hi) > 0 ? ticks(hi) : ticks(t)); }
    function framebase(seq) {
        var tb = ticks(seq.timebase);
        if (cmp(tb, "0") <= 0 || cmp(tb, String(TPS)) > 0) { fail("INVALID_TIMEBASE", "Unsupported sequence timebase."); }
        return tb;
    }
    function frameFloor(t, tb) { return mul(tb, Number(div(t, Number(tb)).quotient)); }
    function sequence() {
        if (!app.project || !app.project.activeSequence) { fail("NO_SEQUENCE", "Open a sequence in Premiere Pro first."); }
        return app.project.activeSequence;
    }
    function rows(seq) {
        var result = [], groups = [seq.videoTracks, seq.audioTracks];
        for (var g = 0; g < 2; g++) {
            for (var t = 0; t < count(groups[g]); t++) {
                var track = groups[g][t];
                for (var c = 0; c < count(track.clips); c++) {
                    result.push({clip: track.clips[c], track: track, trackIndex: t, clipIndex: c, video: g === 0});
                }
            }
        }
        return result;
    }
    function selected(seq, videosOnly) {
        var all = rows(seq), result = [];
        for (var i = 0; i < all.length; i++) {
            if ((!videosOnly || all[i].video) && all[i].clip.isSelected()) { result.push(all[i]); }
        }
        if (!result.length) { fail(videosOnly ? "NO_VIDEO_SELECTION" : "NO_SELECTION", "Select a timeline clip first."); }
        return result;
    }
    function unlocked(track) {
        if (typeof track.isLocked !== "function") { fail("LOCK_STATE_UNAVAILABLE", "This Premiere version does not expose track lock state."); }
        var locked = track.isLocked();
        if (locked !== false && locked !== true && locked !== 0 && locked !== 1) { fail("LOCK_STATE_UNAVAILABLE", "Premiere returned an unknown track lock state."); }
        if (locked) { fail("TRACK_LOCKED", "Unlock the affected track before editing."); }
    }
    function regularClip(clip, strict) {
        if (!clip.projectItem) { fail("UNSUPPORTED_CLIP", "This item is not a supported media clip."); }
        var item = clip.projectItem;
        if ((typeof item.isSequence === "function" && item.isSequence()) ||
            (typeof item.isMulticamClip === "function" && item.isMulticamClip()) ||
            (typeof item.isMergedClip === "function" && item.isMergedClip()) ||
            (typeof clip.isMGT === "function" && clip.isMGT())) {
            fail("UNSUPPORTED_CLIP", "Nested, multicam, merged and MOGRT clips require manual editing.");
        }
        if (typeof item.isOffline === "function" && item.isOffline()) { fail("MEDIA_OFFLINE", "The selected clip is offline."); }
        if (strict) {
            if (typeof clip.getSpeed !== "function" || typeof clip.isSpeedReversed !== "function") {
                fail("SPEED_UNAVAILABLE", "Cannot verify the clip playback speed.");
            }
            if (Math.abs(clip.getSpeed() - 1) > 0.0000001 || clip.isSpeedReversed()) {
                fail("RETIME_UNSUPPORTED", "Retimed and reversed clips require manual editing.");
            }
            var comps = clip.components;
            for (var i = 0; i < count(comps); i++) {
                if (/Time Remapping|TimeRemapping/i.test(String(comps[i].matchName))) {
                    var p = comps[i].properties;
                    for (var j = 0; j < count(p); j++) {
                        if (typeof p[j].isTimeVarying === "function" && p[j].isTimeVarying()) {
                            fail("RETIME_UNSUPPORTED", "Time-remapping animation is not supported.");
                        }
                    }
                }
            }
        }
    }
    function noLinks(clip) {
        if (typeof clip.getLinkedItems !== "function") { fail("LINK_STATE_UNAVAILABLE", "Cannot verify linked clip state."); }
        var linked = clip.getLinkedItems();
        for (var i = 0; i < count(linked); i++) {
            if (!sameClip(linked[i], clip)) {
                fail("LINKED_TRIM_UNSUPPORTED", "Unlink the affected audio/video clips before this safe trim operation.");
            }
        }
    }
    function sameSource(a, b) {
        var x = a.projectItem, y = b.projectItem;
        // Source identity must not be inferred from a file name or media path.
        return x && y && (x === y || (x.nodeId !== undefined && y.nodeId !== undefined &&
            String(x.nodeId) !== "" && String(x.nodeId) === String(y.nodeId)));
    }
    function alignedPair(a, b) {
        return a.video !== b.video && sameSource(a.clip, b.clip) &&
            cmp(a.clip.start, b.clip.start) === 0 && cmp(a.clip.end, b.clip.end) === 0 &&
            cmp(a.clip.inPoint, b.clip.inPoint) === 0 && cmp(a.clip.outPoint, b.clip.outPoint) === 0;
    }
    function hasRow(group, clip) {
        for (var i = 0; i < group.length; i++) { if (sameClip(group[i].clip, clip)) { return true; } }
        return false;
    }
    function rowFor(all, clip) {
        for (var i = 0; i < all.length; i++) { if (sameClip(all[i].clip, clip)) { return all[i]; } }
        fail("LINKED_TRIM_UNSUPPORTED", "A linked item is not in the active sequence.");
    }
    function rippleLinks(row, all) {
        // getLinkedItems can enumerate repeated uses of a source, not just the
        // UI link group. Validate aligned A/V pairs; never trim its entire result.
        if (typeof row.clip.getLinkedItems !== "function") { fail("LINK_STATE_UNAVAILABLE", "Cannot inspect linked items."); }
        var linked = row.clip.getLinkedItems(), others = [], i, j;
        for (i = 0; i < count(linked); i++) {
            if (!sameClip(linked[i], row.clip)) { others.push(rowFor(all, linked[i])); }
        }
        if (!others.length) { return [row]; }
        var peer = null;
        for (i = 0; i < all.length; i++) {
            if (alignedPair(row, all[i])) {
                if (peer) { fail("LINKED_TRIM_UNSUPPORTED", "Only one video and one aligned audio item are supported."); }
                peer = all[i];
            }
        }
        if (!peer || !hasRow(others, peer.clip)) { fail("LINKED_TRIM_UNSUPPORTED", "Select an aligned same-source video/audio pair."); }
        if (typeof peer.clip.getLinkedItems !== "function") { fail("LINK_STATE_UNAVAILABLE", "Cannot inspect the audio/video counterpart."); }
        var reciprocal = peer.clip.getLinkedItems(), found = false;
        for (i = 0; i < count(reciprocal); i++) { if (sameClip(reciprocal[i], row.clip)) { found = true; } }
        if (!found) { fail("LINKED_TRIM_UNSUPPORTED", "The audio/video association is ambiguous."); }
        // Reject custom links, offsets and multi-audio layouts in either direction.
        var candidates = others.slice(0);
        for (i = 0; i < count(reciprocal); i++) { candidates.push(rowFor(all, reciprocal[i])); }
        for (i = 0; i < candidates.length; i++) {
            var candidate = candidates[i], matches = 0;
            if (!sameSource(row.clip, candidate.clip)) { fail("LINKED_TRIM_UNSUPPORTED", "Custom source links are unsupported."); }
            for (j = 0; j < all.length; j++) { if (alignedPair(candidate, all[j])) { matches++; } }
            if (matches !== 1) { fail("LINKED_TRIM_UNSUPPORTED", "Linked items must form unambiguous aligned video/audio pairs."); }
        }
        return [row, peer];
    }
    function noTransitions(track, lo, hi) {
        if (!track.transitions) { fail("TRANSITION_STATE_UNAVAILABLE", "Cannot verify transitions on this track."); }
        for (var i = 0; i < count(track.transitions); i++) {
            var tr = track.transitions[i];
            if (cmp(tr.end, lo) >= 0 && (!hi || cmp(tr.start, hi) <= 0)) {
                fail("TRANSITION_TRIM_UNSUPPORTED", "The affected range contains a transition; trim it in Premiere.");
            }
        }
    }
    function snapshot(row) {
        return {row: row, start: ticks(row.clip.start), end: ticks(row.clip.end),
            inPoint: ticks(row.clip.inPoint), outPoint: ticks(row.clip.outPoint)};
    }
    function stateIs(s) {
        return cmp(s.row.clip.start, s.start) === 0 && cmp(s.row.clip.end, s.end) === 0 &&
            cmp(s.row.clip.inPoint, s.inPoint) === 0 && cmp(s.row.clip.outPoint, s.outPoint) === 0;
    }
    function assign(clip, prop, value) { if (cmp(clip[prop], value) !== 0) { clip[prop] = time(value); } }
    function setBounds(s) {
        var clip = s.row.clip;
        // DOM setters differ among releases; explicitly reconcile and verify all four coordinates.
        assign(clip, "start", s.start);
        assign(clip, "inPoint", s.inPoint);
        assign(clip, "outPoint", s.outPoint);
        assign(clip, "end", s.end);
        if (!stateIs(s)) { fail("TRIM_WRITE_REJECTED", "Premiere did not accept the requested clip boundaries."); }
    }
    function shift(s, delta) {
        if (typeof s.row.clip.move !== "function") { fail("MOVE_UNSUPPORTED", "This Premiere version does not support TrackItem.move."); }
        var expected = {row: s.row, start: add(s.start, delta), end: add(s.end, delta), inPoint: s.inPoint, outPoint: s.outPoint};
        // Some host versions may already move the linked counterpart. Do not
        // apply the delta twice; accept only the exact requested final state.
        if (stateIs(expected)) { return; }
        if (!stateIs(s)) { fail("TRIM_WRITE_REJECTED", "The linked item changed unexpectedly while moving its counterpart."); }
        s.row.clip.move(time(delta));
        if (!stateIs(expected)) { fail("TRIM_WRITE_REJECTED", "Premiere did not move the clip by the requested amount."); }
    }
    function sourceDuration(clip) {
        var item = clip.projectItem;
        if (typeof item.getProjectMetadata !== "function") { fail("MEDIA_BOUNDS_UNAVAILABLE", "Source duration metadata is unavailable."); }
        var xml = String(item.getProjectMetadata());
        var m = /<(?:[\w.-]+:)?Column\.Intrinsic\.MediaDuration[^>]*>([^<]+)<\//.exec(xml);
        var tb = item.interpretedTimebase;
        if (!m || !tb) { fail("MEDIA_BOUNDS_UNAVAILABLE", "Cannot determine the source media boundary; shorten the clip or trim manually."); }
        var tc = /^\s*(\d+):(\d\d):(\d\d)([:;])(\d+)\s*$/.exec(m[1]);
        if (!tc) { fail("MEDIA_BOUNDS_UNAVAILABLE", "The source duration format is not a supported timecode."); }
        tb = ticks(tb);
        var fps = TPS / Number(tb), nominal = Math.round(fps), minutes = Number(tc[1]) * 60 + Number(tc[2]);
        var frames = ((Number(tc[1]) * 3600 + Number(tc[2]) * 60 + Number(tc[3])) * nominal) + Number(tc[5]);
        if (Number(tc[2]) > 59 || Number(tc[3]) > 59 || Number(tc[5]) >= nominal) { fail("MEDIA_BOUNDS_UNAVAILABLE", "Invalid source duration timecode."); }
        if (tc[4] === ";") {
            if (Math.abs(fps - 30000 / 1001) > 0.001 && Math.abs(fps - 60000 / 1001) > 0.001) {
                fail("MEDIA_BOUNDS_UNAVAILABLE", "Unknown drop-frame duration format.");
            }
            frames -= Math.round(nominal / 15) * (minutes - Math.floor(minutes / 10));
        }
        var duration = mul(tb, frames);
        if (cmp(duration, clip.outPoint) < 0) { fail("MEDIA_BOUNDS_UNAVAILABLE", "Source duration metadata disagrees with this clip's bounds."); }
        return duration;
    }
    function jog(req) {
        var seq = sequence(), tb = framebase(seq), delta = integer(req.payload.deltaFrames, "deltaFrames", 100000);
        var before = ticks(seq.getPlayerPosition()), last = frameFloor(ticks(seq.end), tb);
        var base = frameFloor(clamp(before, "0", last), tb), target = clamp(add(base, mul(tb, delta)), "0", last);
        if (cmp(before, target) !== 0) { seq.setPlayerPosition(target); }
        var after = ticks(seq.getPlayerPosition());
        if (cmp(after, target) !== 0) { fail("PLAYHEAD_WRITE_REJECTED", "Premiere did not accept the playhead position."); }
        return {positionTicks: after, frame: Number(div(after, Number(tb)).quotient), deltaFrames: delta, clamped: cmp(target, add(base, mul(tb, delta))) !== 0};
    }
    function linkedRolling(seq, tb, dFrames, selection, all) {
        // Keep linked rolling isolated from the proven ripple and single-item paths.
        if (selection.length !== 2 || !alignedPair(selection[0], selection[1])) {
            fail("TRIM_SELECTION_UNSUPPORTED", "Select only the left aligned same-source video/audio pair.");
        }
        var left = rippleLinks(selection[0], all), right = [], leftOrigins = [], rightOrigins = [],
            leftTargets = [], rightTargets = [], guards = [], i;
        if (left.length !== 2 || !hasRow(selection, left[1].clip)) {
            fail("LINKED_TRIM_UNSUPPORTED", "The selected items are not a supported video/audio pair.");
        }
        for (i = 0; i < left.length; i++) {
            var r = left[i];
            if (r.clipIndex + 1 >= count(r.track.clips)) { fail("NO_ADJACENT_CLIP", "Both video and audio require a following clip."); }
            var n = {clip: r.track.clips[r.clipIndex + 1], track: r.track, trackIndex: r.trackIndex,
                clipIndex: r.clipIndex + 1, video: r.video};
            if (cmp(n.clip.start, r.clip.end) !== 0) { fail("NO_ADJACENT_CLIP", "Both video and audio must be directly adjacent."); }
            right.push(n);
        }
        if (!alignedPair(right[0], right[1])) { fail("LINKED_TRIM_UNSUPPORTED", "The following video/audio pair is not aligned or from one source."); }
        var rightGroup = rippleLinks(right[0], all);
        if (rightGroup.length !== 2 || !hasRow(rightGroup, right[1].clip)) {
            fail("LINKED_TRIM_UNSUPPORTED", "The following items are not a supported video/audio pair.");
        }
        for (i = 0; i < 2; i++) {
            unlocked(left[i].track); unlocked(right[i].track);
            regularClip(left[i].clip, true); regularClip(right[i].clip, true);
            var l = snapshot(left[i]), q = snapshot(right[i]);
            if (cmp(sub(l.end, l.start), sub(l.outPoint, l.inPoint)) !== 0 ||
                cmp(sub(q.end, q.start), sub(q.outPoint, q.inPoint)) !== 0) {
                fail("RETIME_UNSUPPORTED", "Timeline and source duration differ.");
            }
            noTransitions(left[i].track, l.start, q.end);
            leftOrigins.push(l); rightOrigins.push(q);
            leftTargets.push(snapshot(left[i])); rightTargets.push(snapshot(right[i]));
        }
        var delta = mul(tb, dFrames), minimum = neg(sub(sub(leftOrigins[0].end, leftOrigins[0].start), tb)),
            maximum = sub(sub(rightOrigins[0].end, rightOrigins[0].start), tb);
        for (i = 0; i < 2; i++) {
            // All four items must accept the same delta and retain at least one frame.
            var earliest = neg(rightOrigins[i].inPoint);
            if (cmp(earliest, minimum) > 0) { minimum = earliest; }
            if (cmp(delta, "0") > 0) {
                var handle = sub(sourceDuration(left[i].clip), leftOrigins[i].outPoint);
                if (cmp(handle, maximum) < 0) { maximum = handle; }
            }
        }
        if (cmp(minimum, "0") < 0) { minimum = neg(frameFloor(neg(minimum), tb)); }
        if (cmp(maximum, "0") > 0) { maximum = frameFloor(maximum, tb); }
        var applied = clamp(delta, minimum, maximum), limited = cmp(delta, applied) !== 0;
        if (applied === "0") { return {mode: "rollingNext", deltaFrames: 0, boundary: true, changed: false}; }
        for (i = 0; i < 2; i++) {
            leftTargets[i].outPoint = add(leftOrigins[i].outPoint, applied);
            leftTargets[i].end = add(leftOrigins[i].end, applied);
            rightTargets[i].inPoint = add(rightOrigins[i].inPoint, applied);
            rightTargets[i].start = add(rightOrigins[i].start, applied);
        }
        // Source enumeration must never expand the four-item edit target. Detect
        // unexpected host coupling to other uses of either source as well.
        for (i = 0; i < all.length; i++) {
            if (!hasRow(left, all[i].clip) && !hasRow(right, all[i].clip) &&
                (sameSource(left[0].clip, all[i].clip) || sameSource(right[0].clip, all[i].clip))) {
                guards.push(snapshot(all[i]));
            }
        }
        var targets = leftTargets.concat(rightTargets), backups = leftOrigins.concat(rightOrigins, guards);
        try {
            // Shrink an entire A/V pair before extending the other pair.
            var writes = cmp(applied, "0") > 0 ? rightTargets.concat(leftTargets) : leftTargets.concat(rightTargets);
            for (i = 0; i < writes.length; i++) { setBounds(writes[i]); }
            for (i = 0; i < targets.length; i++) {
                if (!stateIs(targets[i])) { fail("TRIM_WRITE_REJECTED", "One of the four clip boundaries changed unexpectedly."); }
            }
            for (i = 0; i < guards.length; i++) {
                if (!stateIs(guards[i])) { fail("TRIM_WRITE_REJECTED", "An unrelated source instance changed unexpectedly."); }
            }
        } catch (error) {
            var restored = true, recovery = cmp(applied, "0") > 0 ?
                leftOrigins.concat(rightOrigins) : rightOrigins.concat(leftOrigins);
            for (i = 0; i < recovery.length; i++) {
                try { setBounds(recovery[i]); } catch (ignored) { restored = false; }
            }
            for (i = 0; i < guards.length; i++) {
                if (!stateIs(guards[i])) { try { setBounds(guards[i]); } catch (ignoredGuard) { restored = false; } }
            }
            for (i = 0; i < backups.length; i++) { if (!stateIs(backups[i])) { restored = false; } }
            fail(restored ? "TRIM_FAILED_RESTORED" : "PARTIAL_MUTATION", restored ?
                "The rolling trim failed and original bounds were restored." :
                "Rolling trim rollback was incomplete. Stop and inspect the timeline.",
                {cause: error.code || "HOST_EXCEPTION", rollbackComplete: restored});
        }
        return {mode: "rollingNext", deltaFrames: Number(applied) / Number(tb), trimmedClips: 4,
            movedClips: 0, boundary: limited, changed: true};
    }
    function trim(req) {
        var seq = sequence(), tb = framebase(seq), dFrames = integer(req.payload.deltaFrames, "deltaFrames", 100000);
        var mode = req.settings.mode;
        if (mode !== "rippleIn" && mode !== "rippleOut" && mode !== "rollingNext") { fail("INVALID_REQUEST", "Unknown trim mode."); }
        var selection = selected(seq, false), all = rows(seq);
        if (mode === "rollingNext" && selection.length === 2) {
            return linkedRolling(seq, tb, dFrames, selection, all);
        }
        if (selection.length !== 1 && (mode === "rollingNext" || selection.length !== 2 || !alignedPair(selection[0], selection[1]))) {
            fail("TRIM_SELECTION_UNSUPPORTED", "Select one unlinked clip, or one aligned same-source video/audio pair for ripple trim.");
        }
        var row = selection[0], clip = row.clip;
        var group = mode === "rollingNext" ? [row] : rippleLinks(row, all), i;
        if (group.length !== selection.length || !hasRow(selection, group[group.length - 1].clip)) {
            fail("TRIM_SELECTION_UNSUPPORTED", "Select both video and audio before ripple trimming a linked pair.");
        }
        var origins = [], targets = [];
        for (i = 0; i < group.length; i++) {
            unlocked(group[i].track); regularClip(group[i].clip, true);
            if (mode === "rollingNext") { noLinks(group[i].clip); }
            if (cmp(sub(group[i].clip.end, group[i].clip.start), sub(group[i].clip.outPoint, group[i].clip.inPoint)) !== 0) {
                fail("RETIME_UNSUPPORTED", "Timeline and source duration differ.");
            }
            origins.push(snapshot(group[i])); targets.push(snapshot(group[i]));
        }
        var delta = mul(tb, dFrames), origin = origins[0], target = targets[0], moves = [], bounds = [], backups = origins.slice(0);
        var minimum = "0", maximum = "0", next, nextOrigin, nextTarget;
        if (mode === "rippleIn") {
            minimum = neg(origin.inPoint); maximum = sub(sub(origin.outPoint, origin.inPoint), tb);
        } else if (mode === "rippleOut") {
            minimum = neg(sub(sub(origin.outPoint, origin.inPoint), tb));
            maximum = cmp(delta, "0") > 0 ? sub(sourceDuration(clip), origin.outPoint) : "0";
            for (i = 1; i < group.length && cmp(delta, "0") > 0; i++) {
                var available = sub(sourceDuration(group[i].clip), origins[i].outPoint);
                if (cmp(available, maximum) < 0) { maximum = available; }
            }
        } else {
            if (row.clipIndex + 1 >= count(row.track.clips)) { fail("NO_ADJACENT_CLIP", "There is no following clip on this track."); }
            next = {clip: row.track.clips[row.clipIndex + 1], track: row.track, trackIndex: row.trackIndex, clipIndex: row.clipIndex + 1, video: row.video};
            if (cmp(next.clip.start, origin.end) !== 0) { fail("NO_ADJACENT_CLIP", "The following clip is separated by a gap or overlap."); }
            regularClip(next.clip, true); noLinks(next.clip);
            nextOrigin = snapshot(next); nextTarget = snapshot(next); backups.push(nextOrigin);
            if (cmp(sub(nextOrigin.end, nextOrigin.start), sub(nextOrigin.outPoint, nextOrigin.inPoint)) !== 0) { fail("RETIME_UNSUPPORTED", "The adjacent clip is retimed."); }
            minimum = neg(sub(sub(origin.outPoint, origin.inPoint), tb));
            if (cmp(neg(nextOrigin.inPoint), minimum) > 0) { minimum = neg(nextOrigin.inPoint); }
            maximum = sub(sub(nextOrigin.outPoint, nextOrigin.inPoint), tb);
            if (cmp(delta, "0") > 0) {
                var handle = sub(sourceDuration(clip), origin.outPoint);
                if (cmp(handle, maximum) < 0) { maximum = handle; }
            }
        }
        // Clamp to full sequence frames, never create zero-length clips or cross a source edge.
        if (cmp(minimum, "0") < 0) { minimum = neg(frameFloor(neg(minimum), tb)); }
        if (cmp(maximum, "0") > 0) { maximum = frameFloor(maximum, tb); }
        var applied = clamp(delta, minimum, maximum), limited = cmp(delta, applied) !== 0;
        if (applied === "0") { return {mode: mode, deltaFrames: 0, boundary: true, changed: false}; }
        for (i = 0; i < group.length; i++) {
            noTransitions(group[i].track, origins[i].start, mode === "rollingNext" ? nextOrigin.end : null);
            if (mode === "rippleIn") { targets[i].inPoint = add(origins[i].inPoint, applied); targets[i].end = sub(origins[i].end, applied); }
            else { targets[i].outPoint = add(origins[i].outPoint, applied); targets[i].end = add(origins[i].end, applied); }
            bounds.push(targets[i]);
        }
        if (mode === "rollingNext") {
            nextTarget.start = add(nextOrigin.start, applied); nextTarget.inPoint = add(nextOrigin.inPoint, applied); bounds.push(nextTarget);
        } else {
            var shiftBy = mode === "rippleIn" ? neg(applied) : applied;
            for (i = 0; i < all.length; i++) {
                var r = all[i];
                if (hasRow(group, r.clip)) { continue; }
                if (cmp(r.clip.start, origin.end) < 0 && cmp(r.clip.end, origin.end) > 0) {
                    fail("CROSSING_CLIP_UNSUPPORTED", "A clip on another track crosses the ripple boundary; trim manually to preserve sync.");
                }
                if (cmp(r.clip.start, origin.end) >= 0) {
                    unlocked(r.track); noTransitions(r.track, r.clip.start, r.clip.end);
                    var laterGroup = rippleLinks(r, all);
                    for (var g = 0; g < laterGroup.length; g++) {
                        if (cmp(laterGroup[g].clip.start, origin.end) < 0) { fail("LINKED_TRIM_UNSUPPORTED", "Linked items cross the ripple boundary."); }
                        if (laterGroup.length > 1) { regularClip(laterGroup[g].clip, true); }
                    }
                    if (typeof r.clip.move !== "function") { fail("MOVE_UNSUPPORTED", "TrackItem.move is unavailable."); }
                    var state = snapshot(r);
                    if (cmp(add(state.start, shiftBy), "0") < 0) { fail("TRIM_COLLISION", "Ripple would move a clip before the sequence start."); }
                    // Respect clips ending before the pivot on every other track.
                    for (var j = 0; j < all.length; j++) {
                        if (all[j].track === r.track && !hasRow(group, all[j].clip) && cmp(all[j].clip.start, origin.end) < 0 &&
                            cmp(all[j].clip.end, add(state.start, shiftBy)) > 0) { fail("TRIM_COLLISION", "Ripple would overlap another clip."); }
                    }
                    moves.push(state); backups.push(state);
                }
            }
            moves.sort(function (a, b) { return cmp(a.start, b.start) * (cmp(shiftBy, "0") > 0 ? -1 : 1); });
        }
        var began = false;
        try {
            began = true;
            if (mode === "rollingNext") {
                // Shrink first, then expand; no transient overlap at the edit point.
                if (cmp(applied, "0") > 0) { setBounds(bounds[1]); setBounds(bounds[0]); }
                else { setBounds(bounds[0]); setBounds(bounds[1]); }
            } else if (cmp(shiftBy, "0") > 0) {
                for (i = 0; i < moves.length; i++) { shift(moves[i], shiftBy); }
                for (i = 0; i < targets.length; i++) { setBounds(targets[i]); }
            } else {
                for (i = 0; i < targets.length; i++) { setBounds(targets[i]); }
                for (i = 0; i < moves.length; i++) { shift(moves[i], shiftBy); }
            }
            // Setters and move may affect linked items implicitly. Check the
            // complete final group after all writes, not only each individual write.
            for (i = 0; i < bounds.length; i++) { if (!stateIs(bounds[i])) { fail("TRIM_WRITE_REJECTED", "A trimmed counterpart changed unexpectedly."); } }
            for (i = 0; i < moves.length; i++) {
                var expectedMove = {row: moves[i].row, start: add(moves[i].start, shiftBy), end: add(moves[i].end, shiftBy),
                    inPoint: moves[i].inPoint, outPoint: moves[i].outPoint};
                if (!stateIs(expectedMove)) { fail("TRIM_WRITE_REJECTED", "A moved counterpart changed unexpectedly."); }
            }
        } catch (error) {
            var restored = true;
            if (began) {
                // Undo in collision-safe order, not simply reverse snapshot order. Never issue global Undo.
                var recovery = [];
                if (mode === "rollingNext") {
                    recovery = cmp(applied, "0") > 0 ? [origin, nextOrigin] : [nextOrigin, origin];
                } else {
                    var restoreMoves = moves.slice(0);
                    restoreMoves.sort(function (a, b) { return cmp(a.start, b.start) * (cmp(shiftBy, "0") > 0 ? 1 : -1); });
                    if (cmp(shiftBy, "0") > 0) { recovery = recovery.concat(origins); }
                    for (i = 0; i < restoreMoves.length; i++) { recovery.push(restoreMoves[i]); }
                    if (cmp(shiftBy, "0") < 0) { recovery = recovery.concat(origins); }
                }
                for (i = 0; i < recovery.length; i++) { try { setBounds(recovery[i]); } catch (ignored) { restored = false; } }
                for (i = 0; i < backups.length; i++) { if (!stateIs(backups[i])) { restored = false; } }
            }
            fail(restored ? "TRIM_FAILED_RESTORED" : "PARTIAL_MUTATION", restored ? "The trim failed and original bounds were restored." :
                "Premiere rejected part of the trim and rollback was incomplete. Stop and inspect the timeline before undoing.", {cause: error.code || "HOST_EXCEPTION", rollbackComplete: restored});
        }
        return {mode: mode, deltaFrames: Number(applied) / Number(tb), trimmedClips: group.length, movedClips: moves.length, boundary: limited, changed: true};
    }
    function lumetri(clip, index) {
        var found = [], components = clip.components;
        for (var i = 0; i < count(components); i++) { if (String(components[i].matchName) === MATCH) { found.push(components[i]); } }
        return {component: index < found.length ? found[index] : null, count: found.length};
    }
    function parameterMap(component) {
        var props = component.properties, map = {}, basic = -1, end = count(props), i, j;
        for (i = 0; i < count(props); i++) {
            if (basic < 0 && named(props[i].displayName, BASIC)) { basic = i; }
            else if (basic >= 0 && named(props[i].displayName, CREATIVE)) { end = i; break; }
        }
        if (basic < 0 || end === count(props)) { fail("LUMETRI_LAYOUT_UNSUPPORTED", "Cannot identify Lumetri Basic Correction safely in this Premiere language/version."); }
        for (i = basic + 1; i < end; i++) {
            for (j = 0; j < ORDER.length; j++) {
                var key = ORDER[j];
                if (named(props[i].displayName, PARAMS[key].names)) {
                    if (own(map, key)) { fail("LUMETRI_LAYOUT_UNSUPPORTED", "Ambiguous Lumetri parameter names."); }
                    map[key] = {param: props[i], index: i};
                }
            }
        }
        for (i = 0; i < ORDER.length; i++) {
            // Premiere 25/26 moved Saturation before Exposure. Names must be
            // unique inside Basic Correction; their relative order is not an API.
            if (!own(map, ORDER[i])) { fail("LUMETRI_LAYOUT_UNSUPPORTED", "Unknown Lumetri Basic Correction layout.", {missingParameter: ORDER[i]}); }
        }
        return map;
    }
    function prepareQE(seq, row) {
        if (typeof app.enableQE !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "Add Lumetri Color in Premiere before using this control."); }
        app.enableQE();
        if (typeof qe === "undefined" || !qe.project || typeof qe.project.getActiveSequence !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "QE is unavailable; add Lumetri Color manually."); }
        var qs = qe.project.getActiveSequence();
        if (!qs || typeof qs.getVideoTrackAt !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "Cannot map the active QE sequence."); }
        // The experimental QE bridge is fail-closed when its sequence identity cannot be confirmed.
        if (typeof qs.guid === "undefined" || String(qs.guid) !== String(seq.sequenceID)) {
            fail("LUMETRI_ADD_UNSUPPORTED", "The QE sequence identity cannot be matched to the active public sequence; add Lumetri manually.");
        }
        // QE indices include gaps/transitions. Never use the public clip index as the QE item index.
        var qt = qs.getVideoTrackAt(row.trackIndex), found = [], qi;
        if (!qt || typeof qt.getItemAt !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "Cannot access the target QE track."); }
        for (var i = 0; i < count(qt); i++) {
            qi = qt.getItemAt(i);
            if (qi && qi.type === "Clip" && qi.start && qi.end && cmp(qi.start, row.clip.start) === 0 && cmp(qi.end, row.clip.end) === 0 && String(qi.name) === String(row.clip.name)) { found.push(qi); }
        }
        if (found.length !== 1 || typeof found[0].addVideoEffect !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "QE could not uniquely identify the selected clip."); }
        if (typeof qe.project.getVideoEffectByName !== "function") { fail("LUMETRI_ADD_UNSUPPORTED", "QE effect lookup is unavailable."); }
        var effect = qe.project.getVideoEffectByName(MATCH, true);
        if (!effect) { fail("LUMETRI_ADD_UNSUPPORTED", "QE could not resolve Lumetri by its stable match name; add it manually."); }
        return {item: found[0], effect: effect};
    }
    function valuePlan(row, component, key, delta, seq, reset) {
        var p = parameterMap(component)[key].param;
        if (typeof p.isTimeVarying !== "function") { fail("PARAMETER_UNSUPPORTED", "This effect parameter does not expose animation state."); }
        var animated = p.isTimeVarying(), at = null, before, hadKey = false;
        if (animated) {
            regularClip(row.clip, true);
            var cti = ticks(seq.getPlayerPosition());
            if (cmp(cti, row.clip.start) < 0 || cmp(cti, row.clip.end) >= 0) { fail("PLAYHEAD_OUTSIDE_CLIP", "Place the playhead inside every selected animated clip."); }
            at = time(add(sub(cti, row.clip.start), row.clip.inPoint));
            if (typeof p.getValueAtTime !== "function" || typeof p.getKeys !== "function" || typeof p.addKey !== "function" ||
                typeof p.setValueAtKey !== "function" || typeof p.removeKey !== "function") { fail("KEYFRAME_UNSUPPORTED", "The parameter cannot be safely keyframed in this Premiere version."); }
            before = p.getValueAtTime(at);
            var keys = p.getKeys();
            for (var k = 0; k < count(keys); k++) { if (cmp(keys[k], at) === 0) { hadKey = true; break; } }
        } else {
            if (typeof p.getValue !== "function" || typeof p.setValue !== "function") { fail("PARAMETER_UNSUPPORTED", "The scalar parameter API is unavailable."); }
            before = p.getValue();
        }
        if (!scalar(before)) { fail("PARAMETER_NOT_SCALAR", "Lumetri returned opaque/non-numeric data; it cannot be safely changed."); }
        var range = PARAMS[key], after = reset ? (key === "saturation" ? 100 : 0) : Math.max(range.min, Math.min(range.max, Math.round((before + delta) * 1000000) / 1000000));
        return {p: p, at: at, animated: animated, hadKey: hadKey, before: before, after: after, touched: false, added: false};
    }
    function color(req) {
        var seq = sequence(), key = req.payload.parameter, reset = req.payload.reset === true, delta = reset ? 0 : req.payload.delta;
        if (!own(PARAMS, key) || (own(req.payload, "reset") && typeof req.payload.reset !== "boolean") || !scalar(delta) || Math.abs(delta) > 10000) { fail("INVALID_REQUEST", "Unknown parameter or invalid adjustment."); }
        // Always reuse the first Lumetri. Legacy per-button switches/indices are ignored.
        var selection = selected(seq, true), plans = [], additions = [], i, addedCount = 0;
        for (i = 0; i < selection.length; i++) {
            var row = selection[i]; unlocked(row.track); regularClip(row.clip, false);
            var l = lumetri(row.clip, 0);
            if (!l.component) {
                // Read probes and resets never create an effect; only adjustments do.
                if (delta === 0) { fail("NO_LUMETRI", "The selected clip has no Lumetri Color effect to read."); }
                additions.push({row: row, qe: prepareQE(seq, row)});
            } else { plans.push(valuePlan(row, l.component, key, delta, seq, reset)); }
        }
        // Multi-clip missing effects cannot be added transactionally through CEP/QE. Do not leave half the selection changed.
        if (additions.length && selection.length !== 1) { fail("LUMETRI_MULTI_ADD_UNSUPPORTED", "For a multi-clip adjustment, add Lumetri to all selected clips first. Automatic adding is available for one clip."); }
        try {
            if (additions.length) {
                additions[0].qe.item.addVideoEffect(additions[0].qe.effect);
                var added = lumetri(additions[0].row.clip, 0);
                if (!added.component || added.count !== 1) { fail("LUMETRI_ADD_FAILED", "Premiere did not confirm the new Lumetri instance."); }
                addedCount = 1;
                plans.push(valuePlan(additions[0].row, added.component, key, delta, seq, reset));
            }
            for (i = 0; i < plans.length; i++) {
                var plan = plans[i];
                if (Math.abs(plan.after - plan.before) < 0.000001) { continue; }
                plan.touched = true;
                if (plan.animated) {
                    if (!plan.hadKey) { plan.added = true; plan.p.addKey(plan.at); }
                    plan.p.setValueAtKey(plan.at, plan.after, 1);
                } else { plan.p.setValue(plan.after, 1); }
                var actual = plan.animated ? plan.p.getValueAtTime(plan.at) : plan.p.getValue();
                if (!scalar(actual) || Math.abs(actual - plan.after) > 0.0001) { fail("PARAMETER_WRITE_REJECTED", "Premiere did not accept the parameter value."); }
            }
        } catch (error) {
            var restored = true;
            for (i = plans.length - 1; i >= 0; i--) {
                var undo = plans[i];
                if (!undo.touched) { continue; }
                try {
                    if (undo.animated && undo.added) { undo.p.removeKey(undo.at); }
                    else if (undo.animated) { undo.p.setValueAtKey(undo.at, undo.before, 1); }
                    else { undo.p.setValue(undo.before, 1); }
                    var readBack = undo.animated ? undo.p.getValueAtTime(undo.at) : undo.p.getValue();
                    if (!scalar(readBack) || Math.abs(readBack - undo.before) > 0.0001) { restored = false; }
                    if (undo.animated && undo.added) {
                        var remainingKeys = undo.p.getKeys();
                        for (var ki = 0; ki < count(remainingKeys); ki++) { if (cmp(remainingKeys[ki], undo.at) === 0) { restored = false; } }
                    }
                } catch (ignored) { restored = false; }
            }
            // Effect creation has no public, transaction-safe inverse. Never call a global undo, which could undo user work.
            if (additions.length) {
                try { addedCount = lumetri(additions[0].row.clip, 0).count; } catch (ignored2) { addedCount = 1; }
            }
            if (addedCount || !restored) { fail("PARTIAL_MUTATION", "The adjustment failed. A new effect or partial edit may remain; inspect the selected clip before continuing.", {cause: error.code || "HOST_EXCEPTION", rollbackComplete: restored && !addedCount, addedEffects: addedCount}); }
            fail(error.code || "PARAMETER_WRITE_FAILED", error.message || "The adjustment failed.", {rollbackComplete: restored});
        }
        var values = [], animatedCount = 0;
        for (i = 0; i < plans.length; i++) { values.push(plans[i].after); if (plans[i].animated) { animatedCount++; } }
        return {parameter: key, value: values[0], values: values, clipCount: plans.length, animatedClips: animatedCount, addedEffects: addedCount,
            mixed: values.length > 1 && Math.min.apply(Math, values) !== Math.max.apply(Math, values)};
    }
    function exportInfo(req) {
        var seq = sequence(), path = req.settings.presetPath;
        if (typeof path !== "string" || !/\.epr$/i.test(path)) { fail("PRESET_REQUIRED", "Choose an Adobe export preset (.epr) first."); }
        var preset = new File(path);
        if (!preset.exists) { fail("PRESET_MISSING", "The selected export preset does not exist."); }
        if (typeof seq.getExportFileExtension !== "function") { fail("EXPORT_UNSUPPORTED", "This Premiere version cannot determine the preset's file extension."); }
        var extension = String(seq.getExportFileExtension(preset.fsName)).replace(/^\./, "");
        if (!/^[a-zA-Z0-9]{1,16}$/.test(extension)) { fail("PRESET_INVALID", "Premiere could not identify a usable export preset."); }
        return {sequenceName: String(seq.name), sequenceId: String(seq.sequenceID), extension: extension};
    }
    function prepareExport(req) {
        var info = exportInfo(req), seq = sequence(), settings = req.settings;
        if (settings.expectedSequenceId && String(settings.expectedSequenceId) !== String(seq.sequenceID)) { fail("SEQUENCE_CHANGED", "The active sequence changed while export was being prepared."); }
        if (typeof settings.outputPath !== "string" || !settings.outputPath.length) { fail("OUTPUT_REQUIRED", "Choose an output folder first."); }
        var output = new File(settings.outputPath);
        if (!output.parent || !output.parent.exists) { fail("OUTPUT_MISSING", "The output folder does not exist."); }
        if (output.exists) { fail("OUTPUT_EXISTS", "The output file already exists; refusing to overwrite it."); }
        if (normal(output.name).slice(-(info.extension.length + 1)) !== "." + normal(info.extension)) { fail("OUTPUT_EXTENSION", "Output extension does not match the selected preset."); }
        if (settings.range !== "entire" && settings.range !== "inOut") { fail("INVALID_REQUEST", "Unknown export range."); }
        if (settings.range === "inOut") {
            if (typeof seq.getInPointAsTime !== "function" || typeof seq.getOutPointAsTime !== "function") { fail("EXPORT_RANGE_UNAVAILABLE", "Cannot verify sequence in/out points."); }
            var start = seq.getInPointAsTime(), end = seq.getOutPointAsTime();
            if (cmp(start, "0") < 0 || cmp(end, start) <= 0 || cmp(end, seq.end) > 0) { fail("EXPORT_RANGE_INVALID", "Set valid in and out points in the active sequence."); }
        }
        return {info: info, seq: seq, settings: settings, output: output};
    }
    function queueExport(req) {
        var plan = prepareExport(req), seq = plan.seq, settings = plan.settings, output = plan.output;
        if (!app.encoder || typeof app.encoder.encodeSequence !== "function" || typeof app.encoder.launchEncoder !== "function") { fail("AME_UNAVAILABLE", "Install a compatible Adobe Media Encoder version."); }
        if (app.encoder.launchEncoder() === false) { fail("AME_UNAVAILABLE", "Adobe Media Encoder could not be launched."); }
        var range = settings.range === "inOut" ? app.encoder.ENCODE_IN_TO_OUT : app.encoder.ENCODE_ENTIRE;
        if (typeof range !== "number") { fail("EXPORT_UNSUPPORTED", "Encoder range constants are unavailable."); }
        var job = app.encoder.encodeSequence(seq, output.fsName, new File(settings.presetPath).fsName, range, 0, settings.startQueue === true);
        if (!job || String(job) === "0") { fail("EXPORT_QUEUE_REJECTED", "Media Encoder did not return a queue job ID. Do not retry until you inspect its queue."); }
        return {jobId: String(job), queued: true, started: settings.startQueue === true};
    }
    function directExport(req) {
        var plan = prepareExport(req), seq = plan.seq, settings = plan.settings;
        if (typeof seq.exportAsMediaDirect !== "function") { fail("DIRECT_EXPORT_UNSUPPORTED", "This Premiere version does not expose direct media export."); }
        var result;
        try {
            // The direct exporter blocks until Premiere returns. It does not
            // launch AME; the public range values are entire=0 and in/out=1.
            result = seq.exportAsMediaDirect(plan.output.fsName, new File(settings.presetPath).fsName, settings.range === "inOut" ? 1 : 0);
        } catch (error) {
            fail("RESULT_UNKNOWN", "Premiere did not confirm direct export. Inspect the output folder before trying again.", {renderer: "premiere", outputPath: plan.output.fsName});
        }
        var status = String(result).replace(/^\s+|\s+$/g, ""), written = new File(plan.output.fsName);
        if (/^error\b/i.test(status) || result === false) {
            fail("DIRECT_EXPORT_FAILED", "Premiere reported a direct export failure. Check the preset and output folder before trying again.", {hostResult: status.slice(0, 256), outputExists: written.exists});
        }
        if ((status !== "0" && status !== "No Error") || !written.exists || !(written.length > 0)) {
            fail("RESULT_UNKNOWN", "Direct export could not be confirmed. Inspect the output file before trying again.", {renderer: "premiere", hostResult: status.slice(0, 256), outputExists: written.exists, outputPath: plan.output.fsName});
        }
        return {renderer: "premiere", queued: false, completed: true, outputPath: written.fsName, bytes: written.length};
    }

    // CEP hosts do not consistently provide JSON. This small parser never evaluates script input.
    function parse(text) {
        if (typeof JSON !== "undefined" && typeof JSON.parse === "function") { return JSON.parse(text); }
        var s = String(text), at = 0, depth = 0;
        function ws() { while (/\s/.test(s.charAt(at)) && at < s.length) { at++; } }
        function str() {
            var result = "", ch; at++;
            while (at < s.length) {
                ch = s.charAt(at++);
                if (ch === '"') { return result; }
                if (ch === "\\") {
                    ch = s.charAt(at++);
                    if (ch === "u") { var hex = s.substr(at, 4); if (!/^[0-9a-f]{4}$/i.test(hex)) { throw new Error("Invalid JSON escape"); } result += String.fromCharCode(parseInt(hex, 16)); at += 4; }
                    else { var escapes = {'"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t"}; if (!own(escapes, ch)) { throw new Error("Invalid JSON escape"); } result += escapes[ch]; }
                } else { if (ch.charCodeAt(0) < 32) { throw new Error("Invalid JSON string"); } result += ch; }
            }
            throw new Error("Unterminated JSON string");
        }
        function val() {
            ws(); if (++depth > 30) { throw new Error("JSON nesting limit"); }
            var ch = s.charAt(at), result, key, match;
            if (ch === '"') { result = str(); }
            else if (ch === "{" || ch === "[") {
                var object = ch === "{"; result = object ? {} : []; at++; ws();
                if (s.charAt(at) !== (object ? "}" : "]")) {
                    while (true) {
                        ws();
                        if (object) { if (s.charAt(at) !== '"') { throw new Error("Invalid JSON key"); } key = str(); if (key === "__proto__" || key === "constructor" || key === "prototype") { throw new Error("Unsafe JSON key"); } ws(); if (s.charAt(at++) !== ":") { throw new Error("Missing colon"); } result[key] = val(); }
                        else { result.push(val()); }
                        ws(); if (s.charAt(at) !== ",") { break; } at++;
                    }
                }
                if (s.charAt(at++) !== (object ? "}" : "]")) { throw new Error("Invalid JSON close"); }
            } else {
                match = /^(true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(s.substring(at));
                if (!match) { throw new Error("Invalid JSON value"); } at += match[0].length;
                result = match[0] === "true" ? true : (match[0] === "false" ? false : (match[0] === "null" ? null : Number(match[0])));
            }
            depth--; return result;
        }
        var result = val(); ws(); if (at !== s.length) { throw new Error("Trailing JSON data"); } return result;
    }
    function stringify(v) {
        if (typeof JSON !== "undefined" && typeof JSON.stringify === "function") { return JSON.stringify(v); }
        function quote(s) {
            return '"' + String(s).replace(/[\\"\x00-\x1f\u2028\u2029]/g, function (c) {
                if (c === '"' || c === "\\") { return "\\" + c; }
                var code = c.charCodeAt(0).toString(16); return "\\u" + ("0000" + code).slice(-4);
            }) + '"';
        }
        if (v === null || v === undefined) { return "null"; }
        if (typeof v === "string") { return quote(v); }
        if (typeof v === "number") { return isFinite(v) ? String(v) : "null"; }
        if (typeof v === "boolean") { return String(v); }
        var array = Object.prototype.toString.call(v) === "[object Array]", parts = [], k;
        if (array) { for (k = 0; k < v.length; k++) { parts.push(stringify(v[k])); } }
        else { for (k in v) { if (own(v, k) && typeof v[k] !== "function" && v[k] !== undefined) { parts.push(quote(k) + ":" + stringify(v[k])); } } }
        return (array ? "[" : "{") + parts.join(",") + (array ? "]" : "}");
    }
    function exportPresets(req) {
        if (!app.encoder || typeof app.encoder.getExporters !== "function") { return {supported: false, presets: [], nextOffset: null}; }
        var offset = req.payload.offset || 0;
        integer(offset, "preset offset", 5000);
        if (offset < 0) { fail("INVALID_REQUEST", "Preset offset must be positive."); }
        var exporters = app.encoder.getExporters(), result = [], index = 0;
        for (var i = 0; i < count(exporters); i++) {
            var exporter = exporters[i];
            if (!exporter || typeof exporter.getPresets !== "function") { continue; }
            var presets = exporter.getPresets();
            for (var j = 0; j < count(presets); j++) {
                var preset = presets[j];
                if (!preset) { continue; }
                if (index++ < offset) { continue; }
                if (result.length >= 20) { return {supported: true, presets: result, nextOffset: offset + result.length}; }
                result.push({name: String(preset.name || "").slice(0, 192), matchName: String(preset.matchName || "").slice(0, 512), format: String(exporter.name || "").slice(0, 96)});
            }
        }
        return {supported: true, presets: result, nextOffset: null};
    }
    function capabilities() {
        return {host: "PPRO", version: String(app.version || "unknown"), protocol: 1,
            timelineJog: true, queueExport: !!app.encoder, directExport: !!(app.project && app.project.activeSequence && typeof app.project.activeSequence.exportAsMediaDirect === "function"), parameterDial: true,
            trimControl: {modes: ["rippleIn", "rippleOut", "rollingNext"], guarded: true},
            timelineZoom: false, timelineZoomReason: "ZOOM_UNSUPPORTED", autoAddLumetri: "single-clip-qe-experimental"};
    }
    var handlers = {capabilities: capabilities, exportPresets: exportPresets, timelineJog: jog, trimControl: trim, parameterDial: color,
        exportInfo: exportInfo, queueExport: queueExport, directExport: directExport,
        timelineZoom: function () { sequence(); fail("ZOOM_UNSUPPORTED", "Premiere CEP has no supported timeline zoom command. Configure the explicit shortcut fallback or use Premiere's zoom controls."); }};
    $._ulanziPremiere = {
        dispatch: function (requestJson) {
            var req = null;
            try {
                if (typeof requestJson !== "string" || requestJson.length > 65536) { fail("INVALID_REQUEST", "Invalid request size."); }
                try { req = parse(requestJson); } catch (parseError) { fail("INVALID_REQUEST", "Invalid request JSON."); }
                if (!req || typeof req !== "object" || typeof req.action !== "string" || !own(handlers, req.action)) { fail("UNKNOWN_ACTION", "Unknown host action."); }
                req.settings = req.settings || {}; req.payload = req.payload || {};
                return stringify({ok: true, id: req.id, result: handlers[req.action](req)});
            } catch (error) {
                return stringify({ok: false, id: req && req.id, error: {code: error.code || "HOST_EXCEPTION", message: error.code ? error.message : "Premiere could not complete the operation.", details: error.details || {}}});
            }
        }
    };
}());
