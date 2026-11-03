import { BASIC_KEYPAD_PARAMS } from '../plugin/actions/params.js';

export const PHOTO_PARAMETER_GROUPS = [
    { label: 'Basic', parameters: BASIC_KEYPAD_PARAMS.slice(0, 13) },
    { label: 'Tone Curve', parameters: BASIC_KEYPAD_PARAMS.slice(13, 17) },
    { label: 'HSL', sections: [
        { label: 'Hue', parameters: BASIC_KEYPAD_PARAMS.slice(17, 25) },
        { label: 'Saturation', parameters: BASIC_KEYPAD_PARAMS.slice(25, 33) },
        { label: 'Luminance', parameters: BASIC_KEYPAD_PARAMS.slice(33, 41) }
    ] }
];

export const PHOTO_PARAMETERS = PHOTO_PARAMETER_GROUPS.flatMap(group =>
    group.parameters || group.sections.flatMap(section => section.parameters));

export function normalizePhotoSettings(settings = {}) {
    const requested = Array.isArray(settings.selectedParameters) ? settings.selectedParameters : PHOTO_PARAMETERS.map(item => item.value);
    let selectedParameters = PHOTO_PARAMETERS.filter(item => requested.includes(item.value)).map(item => item.value);
    if (!selectedParameters.length) selectedParameters = ['TEMPERATURE'];
    const stepSize = Number(settings.stepSize);
    const exposureStepSize = Number(settings.exposureStepSize);
    return {
        ...settings,
        selectedParameters,
        press: selectedParameters.includes(settings.press) ? settings.press : selectedParameters[0],
        stepSize: Number.isInteger(stepSize) && stepSize >= 1 && stepSize <= 100 ? stepSize : 1,
        exposureStepSize: Number.isFinite(exposureStepSize) && exposureStepSize >= 0.01 && exposureStepSize <= 1 ? exposureStepSize : 0.1,
        rCW: 'Increase', rCCW: 'Decrease', prCW: 'SwitchDown', prCCW: 'SwitchUp'
    };
}

export function getPhotoParameterKey(parameter) {
    return parameter.includes('_') ? parameter.replaceAll('_', ':') : `BASIC:${parameter}`;
}
