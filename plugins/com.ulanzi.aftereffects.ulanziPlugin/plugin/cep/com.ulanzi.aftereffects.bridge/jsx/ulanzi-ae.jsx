/*
 * Ulanzi After Effects Bridge - ExtendScript execution layer.
 * This file intentionally uses ES3-compatible syntax for broad AE support.
 */
var UlanziAE = (function () {
    var GRID_POINTS = {
        topLeft: [0, 0],
        topCenter: [0.5, 0],
        topRight: [1, 0],
        middleLeft: [0, 0.5],
        center: [0.5, 0.5],
        middleRight: [1, 0.5],
        bottomLeft: [0, 1],
        bottomCenter: [0.5, 1],
        bottomRight: [1, 1]
    };
    var REFERENCE_LAYER_PREFIXES = [
        "reference",
        "ref",
        "参考",
        "參考",
        "参照",
        "Referenz",
        "참조",
        "referência",
        "referencia"
    ];

    function quote(text) {
        return '"' + String(text)
            .replace(/\\/g, "\\\\")
            .replace(/"/g, '\\"')
            .replace(/\r/g, "\\r")
            .replace(/\n/g, "\\n")
            .replace(/\t/g, "\\t") + '"';
    }

    function stringify(value) {
        if (value === null) return "null";
        var type = typeof value;
        if (type === "string") return quote(value);
        if (type === "number") return isFinite(value) ? String(value) : "null";
        if (type === "boolean") return value ? "true" : "false";
        if (value instanceof Array) {
            var arrayParts = [];
            for (var i = 0; i < value.length; i++) arrayParts.push(stringify(value[i]));
            return "[" + arrayParts.join(",") + "]";
        }
        if (type === "object") {
            var objectParts = [];
            for (var key in value) {
                if (value.hasOwnProperty(key) && typeof value[key] !== "undefined" && typeof value[key] !== "function") {
                    objectParts.push(quote(key) + ":" + stringify(value[key]));
                }
            }
            return "{" + objectParts.join(",") + "}";
        }
        return "null";
    }

    function ok(messageKey, data) {
        return { ok: true, messageKey: messageKey, data: data || {} };
    }

    function fail(errorCode, messageKey, data) {
        return { ok: false, errorCode: errorCode, messageKey: messageKey, data: data || {} };
    }

    function activeComp() {
        var item = app.project ? app.project.activeItem : null;
        return item && item instanceof CompItem ? item : null;
    }

    function isReferenceLayerName(name) {
        var normalizedName = String(name || "").toLowerCase();
        for (var i = 0; i < REFERENCE_LAYER_PREFIXES.length; i++) {
            if (normalizedName.indexOf(REFERENCE_LAYER_PREFIXES[i].toLowerCase()) === 0) return true;
        }
        return false;
    }

    function referenceSetEnabled(payload) {
        var comp = activeComp();
        if (!comp) return fail("NO_ACTIVE_COMP", "error.no_active_comp");
        var matches = [];
        for (var i = 1; i <= comp.numLayers; i++) {
            var layer = comp.layer(i);
            if (isReferenceLayerName(layer.name)) matches.push({ layer: layer, enabled: layer.enabled });
        }
        if (matches.length === 0) return fail("NO_REFERENCE_LAYERS", "error.no_reference_layers");

        app.beginUndoGroup(payload.enabled ? "Ulanzi - Enable Reference Layers" : "Ulanzi - Disable Reference Layers");
        try {
            for (var j = 0; j < matches.length; j++) matches[j].layer.enabled = !!payload.enabled;
        } catch (error) {
            for (var k = 0; k < matches.length; k++) {
                try { matches[k].layer.enabled = matches[k].enabled; } catch (ignore) {}
            }
            app.endUndoGroup();
            return fail("REFERENCE_UPDATE_FAILED", "error.operation_failed", { reason: error.toString() });
        }
        app.endUndoGroup();
        return ok(payload.enabled ? "result.reference_enabled" : "result.reference_disabled", { count: matches.length });
    }

    function maskBounds(layer, time) {
        var masks = layer.property("ADBE Mask Parade");
        if (!masks || masks.numProperties === 0) return null;
        var minX = Infinity;
        var minY = Infinity;
        var maxX = -Infinity;
        var maxY = -Infinity;
        var found = false;
        for (var i = 1; i <= masks.numProperties; i++) {
            var shapeProperty = masks.property(i).property("ADBE Mask Shape");
            if (!shapeProperty) continue;
            var shape = shapeProperty.valueAtTime(time, false);
            var vertices = shape ? shape.vertices : null;
            if (!vertices) continue;
            for (var j = 0; j < vertices.length; j++) {
                minX = Math.min(minX, vertices[j][0]);
                minY = Math.min(minY, vertices[j][1]);
                maxX = Math.max(maxX, vertices[j][0]);
                maxY = Math.max(maxY, vertices[j][1]);
                found = true;
            }
        }
        return found ? { left: minX, top: minY, width: maxX - minX, height: maxY - minY } : null;
    }

    function layerBounds(layer, time) {
        var bounds = maskBounds(layer, time);
        if (bounds) return bounds;
        if (typeof layer.sourceRectAtTime !== "function") return null;
        try {
            return layer.sourceRectAtTime(time, false);
        } catch (error) {
            return null;
        }
    }

    function snapshotProperty(property) {
        var snapshot = { property: property, keys: [], value: null };
        if (property.numKeys > 0) {
            for (var i = 1; i <= property.numKeys; i++) snapshot.keys.push(property.keyValue(i));
        } else {
            snapshot.value = property.value;
        }
        return snapshot;
    }

    function restoreProperty(snapshot) {
        if (snapshot.keys.length > 0) {
            for (var i = 1; i <= snapshot.keys.length; i++) snapshot.property.setValueAtKey(i, snapshot.keys[i - 1]);
        } else {
            snapshot.property.setValue(snapshot.value);
        }
    }

    function add2(value, delta) {
        var output = value instanceof Array ? value.slice(0) : [value[0], value[1]];
        output[0] += delta[0];
        output[1] += delta[1];
        return output;
    }

    function compensationAt(layer, transform, localDelta, time) {
        var scaleProperty = transform.property("ADBE Scale");
        var rotationProperty = transform.property("ADBE Rotate Z");
        var scale = scaleProperty ? scaleProperty.valueAtTime(time, false) : [100, 100];
        var rotation = rotationProperty ? rotationProperty.valueAtTime(time, false) : 0;
        var x = localDelta[0] * scale[0] / 100;
        var y = localDelta[1] * scale[1] / 100;
        var radians = rotation * Math.PI / 180;
        return [
            x * Math.cos(radians) - y * Math.sin(radians),
            x * Math.sin(radians) + y * Math.cos(radians)
        ];
    }

    function prepareAnchorOperation(layer, point, time) {
        if (layer.locked) return fail("LAYER_LOCKED", "error.layer_locked", { layerName: layer.name });
        if (layer.threeDLayer) return fail("UNSUPPORTED_3D_LAYER", "error.unsupported_3d_layer", { layerName: layer.name });
        var transform = layer.property("ADBE Transform Group");
        var anchor = transform ? transform.property("ADBE Anchor Point") : null;
        var position = transform ? transform.property("ADBE Position") : null;
        if (!anchor || !position) return fail("MISSING_TRANSFORM", "error.missing_transform", { layerName: layer.name });
        if (position.dimensionsSeparated) return fail("SEPARATED_POSITION", "error.separated_position", { layerName: layer.name });
        var skew = transform.property("ADBE Skew");
        if (skew) {
            if (Math.abs(skew.valueAtTime(time, false)) > 0.0001) return fail("UNSUPPORTED_SKEW_LAYER", "error.unsupported_skew_layer", { layerName: layer.name });
            for (var skewKey = 1; skewKey <= skew.numKeys; skewKey++) {
                if (Math.abs(skew.keyValue(skewKey)) > 0.0001) return fail("UNSUPPORTED_SKEW_LAYER", "error.unsupported_skew_layer", { layerName: layer.name });
            }
        }
        var bounds = layerBounds(layer, time);
        if (!bounds) return fail("NO_LAYER_BOUNDS", "error.no_layer_bounds", { layerName: layer.name });
        var ratio = GRID_POINTS[point];
        var oldAnchor = anchor.valueAtTime(time, false);
        var target = [bounds.left + bounds.width * ratio[0], bounds.top + bounds.height * ratio[1]];
        return {
            ok: true,
            layer: layer,
            transform: transform,
            anchor: anchor,
            position: position,
            delta: [target[0] - oldAnchor[0], target[1] - oldAnchor[1]],
            anchorSnapshot: snapshotProperty(anchor),
            positionSnapshot: snapshotProperty(position)
        };
    }

    function applyAnchorOperation(operation, currentTime) {
        var anchor = operation.anchor;
        var position = operation.position;
        var delta = operation.delta;
        var i;
        if (anchor.numKeys > 0) {
            for (i = 1; i <= anchor.numKeys; i++) anchor.setValueAtKey(i, add2(anchor.keyValue(i), delta));
        } else {
            anchor.setValue(add2(anchor.value, delta));
        }
        if (position.numKeys > 0) {
            for (i = 1; i <= position.numKeys; i++) {
                position.setValueAtKey(i, add2(position.keyValue(i), compensationAt(operation.layer, operation.transform, delta, position.keyTime(i))));
            }
        } else {
            position.setValue(add2(position.value, compensationAt(operation.layer, operation.transform, delta, currentTime)));
        }
    }

    function anchorSetGridPoint(payload) {
        var comp = activeComp();
        if (!comp) return fail("NO_ACTIVE_COMP", "error.no_active_comp");
        var point = payload.point;
        if (!GRID_POINTS[point]) return fail("INVALID_ANCHOR_POINT", "error.invalid_anchor_point");
        var layers = comp.selectedLayers;
        if (!layers || layers.length === 0) return fail("NO_SELECTED_LAYER", "error.no_selected_layer");
        var operations = [];
        for (var i = 0; i < layers.length; i++) {
            var operation = prepareAnchorOperation(layers[i], point, comp.time);
            if (!operation.ok) return operation;
            operations.push(operation);
        }

        app.beginUndoGroup("Ulanzi - Anchor Point Grid");
        try {
            for (var j = 0; j < operations.length; j++) applyAnchorOperation(operations[j], comp.time);
        } catch (error) {
            for (var k = 0; k < operations.length; k++) {
                try {
                    restoreProperty(operations[k].anchorSnapshot);
                    restoreProperty(operations[k].positionSnapshot);
                } catch (ignore) {}
            }
            app.endUndoGroup();
            return fail("ANCHOR_UPDATE_FAILED", "error.operation_failed", { reason: error.toString() });
        }
        app.endUndoGroup();
        return ok("result.anchor_updated", { count: operations.length, point: point });
    }

    function findEffectByName(layer, name) {
        var effects = layer.property("ADBE Effect Parade");
        if (!effects) return null;
        for (var i = 1; i <= effects.numProperties; i++) {
            if (effects.property(i).name === name) return effects.property(i);
        }
        return null;
    }

    function expressionException(errorCode, messageKey, data, reason) {
        var error = new Error(reason || messageKey);
        error.errorCode = errorCode;
        error.messageKey = messageKey;
        error.data = data || {};
        return error;
    }

    function ensureController(layer, name, matchName, defaultValue, createdEffects) {
        var existing = findEffectByName(layer, name);
        if (existing) {
            if (existing.matchName !== matchName) {
                throw expressionException("CONTROLLER_NAME_CONFLICT", "error.controller_name_conflict", {
                    controllerName: name
                });
            }
            return existing;
        }
        var effects = layer.property("ADBE Effect Parade");
        if (!effects || !effects.canAddProperty(matchName)) {
            throw expressionException("CONTROLLER_UNAVAILABLE", "error.controller_unavailable", {
                controllerName: name
            });
        }
        try {
            var effect = effects.addProperty(matchName);
            createdEffects.push(effect);
            effect.name = name;
            effect.property(1).setValue(defaultValue);
            return effect;
        } catch (error) {
            throw expressionException("CONTROLLER_CREATE_FAILED", "error.controller_create_failed", {
                controllerName: name,
                reason: error.toString()
            });
        }
    }

    function replaceAll(text, token, value) {
        return String(text).split(token).join(value);
    }

    function propertyControllerSuffix(property) {
        return property.matchName || property.name || "Property";
    }

    function propertyControllerName(prefix, property) {
        return prefix + propertyControllerSuffix(property);
    }

    function payloadControllerName(payload, key, fallback) {
        var names = payload.controllerNames || {};
        var name = names[key];
        return name && /\S/.test(String(name)) ? String(name) : fallback;
    }

    function isNumericExpressionProperty(property) {
        var valueType = property.propertyValueType;
        return valueType === PropertyValueType.OneD ||
            valueType === PropertyValueType.TwoD ||
            valueType === PropertyValueType.TwoD_SPATIAL ||
            valueType === PropertyValueType.ThreeD ||
            valueType === PropertyValueType.ThreeD_SPATIAL ||
            valueType === PropertyValueType.COLOR;
    }

    function validateExpressionTargets(targets, expressionType) {
        for (var i = 0; i < targets.length; i++) {
            var target = targets[i];
            var detail = { layerName: target.layer.name, propertyName: target.property.name };
            if (target.layer.locked) return fail("EXPRESSION_LAYER_LOCKED", "error.expression_layer_locked", detail);
            if (expressionType === "loop") {
                if (!isNumericExpressionProperty(target.property)) {
                    return fail("LOOP_PROPERTY_UNSUPPORTED", "error.loop_property_unsupported", detail);
                }
                if (target.property.numKeys < 2) {
                    return fail("LOOP_NEEDS_KEYFRAMES", "error.loop_needs_keyframes", detail);
                }
            } else if (expressionType === "wiggle" && !isNumericExpressionProperty(target.property)) {
                return fail("WIGGLE_PROPERTY_UNSUPPORTED", "error.wiggle_property_unsupported", detail);
            } else if (expressionType === "stutter" && !isNumericExpressionProperty(target.property)) {
                return fail("STUTTER_PROPERTY_UNSUPPORTED", "error.stutter_property_unsupported", detail);
            }
        }
        return { ok: true, targets: targets };
    }

    function expressionTargets(comp, expressionType) {
        var targets = [];
        var layers = comp.selectedLayers;
        if (!layers || layers.length === 0) return fail("NO_SELECTED_LAYER", "error.no_selected_layer");
        var countdown = expressionType === "countdownNumber";
        if (countdown) {
            for (var i = 0; i < layers.length; i++) {
                if (!(layers[i] instanceof TextLayer)) return fail("COUNTDOWN_TEXT_ONLY", "error.countdown_text_only", { layerName: layers[i].name });
                var textProperty = layers[i].property("ADBE Text Properties").property("ADBE Text Document");
                if (!textProperty || !textProperty.canSetExpression) return fail("EXPRESSION_NOT_SUPPORTED", "error.expression_not_supported", { layerName: layers[i].name });
                targets.push({ layer: layers[i], property: textProperty });
            }
            return validateExpressionTargets(targets, expressionType);
        }

        for (var j = 0; j < layers.length; j++) {
            var selected = layers[j].selectedProperties || [];
            for (var k = 0; k < selected.length; k++) {
                if (selected[k].canSetExpression) targets.push({ layer: layers[j], property: selected[k] });
            }
        }
        if (targets.length === 0) return fail("NO_SELECTED_PROPERTY", "error.no_selected_property");
        return validateExpressionTargets(targets, expressionType);
    }

    function prepareExpression(target, payload, createdEffects) {
        var type = payload.expressionType;
        var text = String(payload.expressionText || "");
        if (!text || !/\S/.test(text)) {
            throw expressionException("EXPRESSION_EMPTY", "error.expression_empty");
        }
        if (type === "wiggle") {
            var frequencyPrefix = payloadControllerName(payload, "wiggleFrequencyPrefix", "ulanzi_Wiggle_Frequency_");
            var amplitudePrefix = payloadControllerName(payload, "wiggleAmplitudePrefix", "ulanzi_Wiggle_Amplitude_");
            var frequencyName = propertyControllerName(frequencyPrefix, target.property);
            var amplitudeName = propertyControllerName(amplitudePrefix, target.property);
            ensureController(target.layer, frequencyName, "ADBE Slider Control", 5, createdEffects);
            ensureController(target.layer, amplitudeName, "ADBE Slider Control", 20, createdEffects);
            text = replaceAll(text, "{{FREQUENCY_CONTROLLER}}", frequencyName);
            text = replaceAll(text, "{{AMPLITUDE_CONTROLLER}}", amplitudeName);
        } else if (type === "stutter") {
            var stutterPrefix = payloadControllerName(payload, "stutterFrequencyPrefix", "ulanzi_Stutter_Frequency_");
            var stutterName = propertyControllerName(stutterPrefix, target.property);
            ensureController(target.layer, stutterName, "ADBE Slider Control", 2, createdEffects);
            text = replaceAll(text, "{{FREQUENCY_CONTROLLER}}", stutterName);
        } else if (type === "loop") {
            text = replaceAll(text, "{{LOOP_TYPE}}", payload.loopType || "cycle");
        } else if (type === "countdownNumber") {
            var countdownValueName = payloadControllerName(payload, "countdownValue", "ulanzi_Countdown_Value");
            var countdownDecimalPlacesName = payloadControllerName(payload, "countdownDecimalPlaces", "ulanzi_Countdown_Decimals");
            ensureController(target.layer, countdownValueName, "ADBE Slider Control", 100, createdEffects);
            ensureController(target.layer, countdownDecimalPlacesName, "ADBE Slider Control", 1, createdEffects);
            text = replaceAll(text, "{{COUNTDOWN_VALUE_CONTROLLER}}", countdownValueName);
            text = replaceAll(text, "{{COUNTDOWN_DECIMALS_CONTROLLER}}", countdownDecimalPlacesName);
        } else if (type === "custom") {
            return text;
        } else {
            throw expressionException("EXPRESSION_TYPE_UNKNOWN", "error.expression_type_unknown");
        }
        var unresolvedToken = text.match(/\{\{[^}]+\}\}/);
        if (unresolvedToken) {
            throw expressionException("EXPRESSION_TOKEN_UNRESOLVED", "error.expression_token_unresolved", {
                token: unresolvedToken[0]
            });
        }
        return text;
    }

    function countdownKeyframeTiming(comp) {
        var totalFrames = Math.round(comp.duration / comp.frameDuration);
        if (!isFinite(totalFrames) || totalFrames < 2) return null;
        return {
            firstTime: 0,
            lastTime: (totalFrames - 1) * comp.frameDuration,
            frameDuration: comp.frameDuration,
            totalFrames: totalFrames
        };
    }

    function applyCountdownKeyframes(layer, timing, snapshots, controllerName) {
        var effect = findEffectByName(layer, controllerName);
        var counter = effect && effect.property(1);
        if (!counter) {
            throw expressionException("COUNTDOWN_KEYFRAME_FAILED", "error.countdown_keyframe_failed", {
                layerName: layer.name,
                controllerName: controllerName
            });
        }
        if (counter.numKeys > 0) return false;
        try {
            if (counter.canSetExpression && counter.expression && /\S/.test(counter.expression)) return false;
        } catch (ignore) {}

        var originalValue;
        try {
            originalValue = counter.value;
            snapshots.push({ property: counter, value: originalValue });
            counter.setValuesAtTimes(
                [timing.firstTime, timing.lastTime],
                [originalValue, 0]
            );
            var firstKey = counter.nearestKeyIndex(timing.firstTime);
            var lastKey = counter.nearestKeyIndex(timing.lastTime);
            var epsilon = Math.max(timing.frameDuration * 0.001, 0.0000001);
            if (Math.abs(counter.keyTime(firstKey) - timing.firstTime) > epsilon ||
                Math.abs(counter.keyTime(lastKey) - timing.lastTime) > epsilon) {
                throw new Error("Countdown keyframe time mismatch");
            }
            counter.setInterpolationTypeAtKey(firstKey, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
            counter.setInterpolationTypeAtKey(lastKey, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
            return true;
        } catch (error) {
            throw expressionException("COUNTDOWN_KEYFRAME_FAILED", "error.countdown_keyframe_failed", {
                layerName: layer.name,
                controllerName: controllerName,
                reason: error.toString()
            });
        }
    }

    function restoreCountdownController(snapshot) {
        try {
            for (var i = snapshot.property.numKeys; i >= 1; i--) snapshot.property.removeKey(i);
            snapshot.property.setValue(snapshot.value);
            return true;
        } catch (ignore) {
            return false;
        }
    }

    function restoreExpression(snapshot) {
        try {
            snapshot.property.expression = snapshot.expression;
            snapshot.property.expressionEnabled = snapshot.enabled;
            return true;
        } catch (ignore) {
            return false;
        }
    }

    function expressionApply(payload) {
        var comp = activeComp();
        if (!comp) return fail("NO_ACTIVE_COMP", "error.no_active_comp");
        var countdownTiming = null;
        if (payload.expressionType === "countdownNumber") {
            countdownTiming = countdownKeyframeTiming(comp);
            if (!countdownTiming) return fail("COUNTDOWN_COMP_TOO_SHORT", "error.countdown_comp_too_short");
        }
        var targetResult = expressionTargets(comp, payload.expressionType);
        if (!targetResult.ok) return targetResult;
        var targets = targetResult.targets;
        var snapshots = [];
        for (var i = 0; i < targets.length; i++) {
            snapshots.push({
                property: targets[i].property,
                expression: targets[i].property.expression || "",
                enabled: targets[i].property.expressionEnabled
            });
        }
        var createdEffects = [];
        var countdownSnapshots = [];
        var autoKeyframedCount = 0;
        var currentTarget = null;
        app.beginUndoGroup("Ulanzi - Apply Expression");
        try {
            for (var j = 0; j < targets.length; j++) {
                currentTarget = targets[j];
                var expressionText = prepareExpression(currentTarget, payload, createdEffects);
                try {
                    currentTarget.property.expression = expressionText;
                    currentTarget.property.expressionEnabled = true;
                } catch (writeError) {
                    throw expressionException("EXPRESSION_WRITE_FAILED", "error.expression_write_failed", {
                        reason: writeError.toString()
                    });
                }
                if (currentTarget.property.expressionError) {
                    throw expressionException("EXPRESSION_EVALUATION_FAILED", "error.expression_evaluation_failed", {
                        reason: currentTarget.property.expressionError
                    });
                }
                var countdownControllerName = payloadControllerName(payload, "countdownValue", "ulanzi_Countdown_Value");
                if (countdownTiming && applyCountdownKeyframes(currentTarget.layer, countdownTiming, countdownSnapshots, countdownControllerName)) {
                    autoKeyframedCount++;
                }
            }
        } catch (error) {
            var rollbackIncomplete = false;
            for (var k = 0; k < snapshots.length; k++) {
                if (!restoreExpression(snapshots[k])) rollbackIncomplete = true;
            }
            for (var c = 0; c < countdownSnapshots.length; c++) {
                if (!restoreCountdownController(countdownSnapshots[c])) rollbackIncomplete = true;
            }
            for (var e = createdEffects.length - 1; e >= 0; e--) {
                try { createdEffects[e].remove(); } catch (ignore) { rollbackIncomplete = true; }
            }
            app.endUndoGroup();
            var detail = error.data || {};
            if (currentTarget) {
                if (!detail.layerName) detail.layerName = currentTarget.layer.name;
                if (!detail.propertyName) detail.propertyName = currentTarget.property.name;
            }
            if (rollbackIncomplete) {
                if (!detail.reason) detail.reason = error.toString();
                return fail("EXPRESSION_ROLLBACK_INCOMPLETE", "error.expression_rollback_incomplete", detail);
            }
            if (!error.errorCode && !detail.reason) detail.reason = error.toString();
            return fail(
                error.errorCode || "EXPRESSION_INVALID",
                error.messageKey || "error.expression_invalid",
                detail
            );
        }
        app.endUndoGroup();
        return ok("result.expression_applied", {
            count: targets.length,
            expressionType: payload.expressionType,
            autoKeyframedCount: autoKeyframedCount
        });
    }

    function markerAdd() {
        var comp = activeComp();
        if (!comp) return fail("NO_ACTIVE_COMP", "error.no_active_comp");
        var markers = comp.markerProperty;
        var epsilon = Math.max(comp.frameDuration * 0.45, 0.000001);
        for (var i = 1; i <= markers.numKeys; i++) {
            if (Math.abs(markers.keyTime(i) - comp.time) < epsilon) return fail("MARKER_EXISTS", "error.marker_exists");
        }
        var used = {};
        for (var j = 1; j <= markers.numKeys; j++) {
            var name = markers.keyValue(j).comment;
            if (/^\d+$/.test(name)) {
                var number = parseInt(name, 10);
                if (number > 0) used[number] = true;
            }
        }
        var next = 1;
        while (used[next]) next++;
        app.beginUndoGroup("Ulanzi - Add Composition Marker");
        try {
            markers.setValueAtTime(comp.time, new MarkerValue(String(next)));
        } catch (error) {
            app.endUndoGroup();
            return fail("MARKER_ADD_FAILED", "error.operation_failed", { reason: error.toString() });
        }
        app.endUndoGroup();
        return ok("result.marker_added", { markerName: String(next), time: comp.time });
    }

    function positiveModulo(value, divisor) {
        return ((value % divisor) + divisor) % divisor;
    }

    function markerNavigate(payload) {
        var comp = activeComp();
        if (!comp) return fail("NO_ACTIVE_COMP", "error.no_active_comp");
        var markers = comp.markerProperty;
        var count = markers.numKeys;
        if (count === 0) return fail("NO_MARKERS", "error.no_markers");
        var steps = parseInt(payload.steps, 10);
        if (!steps) return ok("result.marker_unchanged", {});
        var epsilon = Math.max(comp.frameDuration * 0.45, 0.000001);
        var index;
        var i;
        if (steps > 0) {
            index = 1;
            for (i = 1; i <= count; i++) {
                if (markers.keyTime(i) > comp.time + epsilon) { index = i; break; }
                if (i === count) index = 1;
            }
            index = positiveModulo((index - 1) + (steps - 1), count) + 1;
        } else {
            index = count;
            for (i = count; i >= 1; i--) {
                if (markers.keyTime(i) < comp.time - epsilon) { index = i; break; }
                if (i === 1) index = count;
            }
            index = positiveModulo((index - 1) - ((-steps) - 1), count) + 1;
        }
        comp.time = markers.keyTime(index);
        var markerName = markers.keyValue(index).comment || String(index);
        return ok("result.marker_navigated", { markerName: markerName, time: comp.time, index: index });
    }

    function dispatch(request) {
        if (!request || !request.command) return fail("INVALID_REQUEST", "status.communication_failed");
        var payload = request.payload || {};
        if (request.command === "reference.setEnabled") return referenceSetEnabled(payload);
        if (request.command === "anchor.setGridPoint") return anchorSetGridPoint(payload);
        if (request.command === "expression.apply") return expressionApply(payload);
        if (request.command === "marker.add") return markerAdd();
        if (request.command === "marker.navigate") return markerNavigate(payload);
        return fail("UNKNOWN_COMMAND", "status.communication_failed", { command: request.command });
    }

    function dispatchEncoded(encoded) {
        try {
            var request = eval("(" + decodeURIComponent(encoded) + ")");
            return stringify(dispatch(request));
        } catch (error) {
            return stringify(fail("SCRIPT_EXCEPTION", "error.operation_failed", { reason: error.toString() }));
        }
    }

    return { dispatchEncoded: dispatchEncoded };
})();
