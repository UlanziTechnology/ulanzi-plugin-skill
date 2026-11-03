const DEFAULT_STEPS = { stepSize: 1, exposureStepSize: 0.1 };

function isParameterSwitch(action) {
    return action.uuidName === 'basic'
        && ['SwitchUp', 'SwitchDown', 'switchParameters'].includes(action.settings.action);
}

function normalizeSteps(settings = {}) {
    const stepSize = Number(settings.stepSize);
    const exposureStepSize = Number(settings.exposureStepSize);
    return {
        stepSize: Number.isInteger(stepSize) && stepSize >= 1 && stepSize <= 100
            ? stepSize : DEFAULT_STEPS.stepSize,
        exposureStepSize: Number.isFinite(exposureStepSize) && exposureStepSize >= 0.01 && exposureStepSize <= 1
            ? Math.round(exposureStepSize * 100) / 100 : DEFAULT_STEPS.exposureStepSize
    };
}

// The shortcut context owns the steps; encoder settings only mirror the selection.
export default class SelectedSliderState {
    constructor($UD) {
        this.$UD = $UD;
        this.actions = new Map();
        this.selectedContext = '';
        this.selectionChanged = false;
    }

    register(action) {
        this.actions.set(action.context, action);
        this.syncSwitchButton(action);
        if (action.uuidName === 'general') this.syncEncoder(action);
        if (action.context === this.selectedContext) this.syncEncoders();
    }

    restore(settings) {
        // A late startup response must not undo a button the user just pressed.
        if (this.selectionChanged) return;
        this.selectedContext = settings.currentParameterContext || '';
        this.$UD.lastKaypad = settings.currentParameter || 'TEMPERATURE';
        this.syncEncoders();
    }

    select(action, parameter) {
        this.selectionChanged = true;
        this.selectedContext = action.context;
        this.$UD.lastKaypad = parameter;
        this.syncEncoders();
        this.saveSelection();
    }

    saveSelection() {
        this.$UD.setGlobalSettings({
            currentParameter: this.$UD.lastKaypad || 'TEMPERATURE',
            currentParameterContext: this.selectedContext
        });
    }

    getSelectedAction() {
        const action = this.actions.get(this.selectedContext);
        return action?.uuidName === 'basic' && action.settings.keypad ? action : null;
    }

    getSteps(encoder) {
        const selected = this.getSelectedAction();
        return normalizeSteps(selected ? selected.settings.selectedSliderSteps : encoder.settings);
    }

    receiveSettings(action, settings, saveSteps = true) {
        const previousSteps = action.uuidName === 'general' ? this.getSteps(action) : null;
        action.settings = settings;
        if (isParameterSwitch(action)) {
            // Switch buttons mirror the global selection. Delayed settings
            // echoes and PI snapshots must not restore a previous parameter.
            this.syncSwitchButton(action);
            this.syncEncoders();
        } else if (action.uuidName === 'general') {
            // Input snapshots carry their original owner even when delivery is delayed.
            const edit = settings.selectedSliderStepEdit;
            const owner = this.actions.get(edit?.context);
            if (saveSteps && owner?.uuidName === 'basic' && owner.settings.keypad === edit.parameter
                && ['stepSize', 'exposureStepSize'].includes(edit.name)) {
                const steps = normalizeSteps({ ...normalizeSteps(owner.settings.selectedSliderSteps), [edit.name]: edit.value });
                const previous = owner.settings.selectedSliderSteps;
                if (!previous || previous.stepSize !== steps.stepSize || previous.exposureStepSize !== steps.exposureStepSize) {
                    owner.settings = { ...owner.settings, selectedSliderSteps: steps };
                    this.$UD.setSettings(owner.settings, owner.context);
                }
            } else if (edit?.context) {
                // A deleted/reconfigured button cannot restore a pending old edit.
                action.settings = { ...settings, ...previousSteps };
            }
            this.syncEncoders();
        } else if (action.context === this.selectedContext) {
            this.$UD.lastKaypad = settings.keypad || 'TEMPERATURE';
            this.syncEncoders();
            this.saveSelection();
        }
    }

    syncEncoder(encoder) {
        const { selectedSliderStepEdit, ...encoderSettings } = encoder.settings;
        const settings = {
            ...encoderSettings,
            ...this.getSteps(encoder),
            currentParameter: this.$UD.lastKaypad || 'TEMPERATURE',
            currentParameterContext: this.selectedContext
        };
        const changed = selectedSliderStepEdit !== undefined || ['stepSize', 'exposureStepSize', 'currentParameter', 'currentParameterContext']
            .some(key => encoder.settings[key] !== settings[key]);
        encoder.settings = settings;
        if (changed) this.$UD.setSettings(settings, encoder.context);
        if (this.$UD.lastContext === encoder.context) {
            this.$UD.sendToPropertyInspector(settings, encoder.context);
        }
    }

    syncEncoders() {
        const selected = this.getSelectedAction();
        if (selected && !isParameterSwitch(selected)) this.$UD.lastKaypad = selected.settings.keypad;
        for (const action of this.actions.values()) {
            this.syncSwitchButton(action);
            if (action.uuidName === 'general') this.syncEncoder(action);
        }
    }

    syncSwitchButton(action) {
        if (!isParameterSwitch(action)) return;
        const keypad = this.$UD.lastKaypad || 'TEMPERATURE';
        if (action.settings.keypad === keypad) return;
        action.settings = { ...action.settings, keypad };
        this.$UD.setSettings(action.settings, action.context);
    }

    remove(context) {
        const action = this.actions.get(context);
        if (action) delete action.settings.selectedSliderSteps;
        this.actions.delete(context);
        if (this.$UD.lastContext === context) this.$UD.lastContext = '';
        if (this.selectedContext === context) {
            this.selectionChanged = true;
            this.selectedContext = '';
            this.$UD.lastKaypad = 'TEMPERATURE';
            for (const encoder of this.actions.values()) {
                if (encoder.uuidName === 'general') Object.assign(encoder.settings, DEFAULT_STEPS);
            }
            this.syncEncoders();
            this.saveSelection();
        }
    }
}
