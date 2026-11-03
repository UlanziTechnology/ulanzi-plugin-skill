import { PHOTO_PARAMETER_GROUPS, PHOTO_PARAMETERS, normalizePhotoSettings } from '../../shared/photoParameters.js';

let settings = normalizePhotoSettings();
let form;
const groups = [];
const parameterInputs = new Map();
const t = key => $UD.t(key);

function addOptions(parent, parameters) {
    const list = document.createElement('div');
    list.className = 'parameter-options';
    for (const parameter of parameters) {
        const label = document.createElement('label');
        label.className = 'parameter-option';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = parameter.value;
        input.addEventListener('change', () => changeSelection([parameter.value], input.checked));
        label.append(input, document.createTextNode(t(parameter.label)));
        list.append(label);
        parameterInputs.set(parameter.value, input);
    }
    parent.append(list);
}

function renderGroups() {
    const container = document.querySelector('#parameter-groups');
    for (const group of PHOTO_PARAMETER_GROUPS) {
        const parameters = group.parameters || group.sections.flatMap(section => section.parameters);
        const details = document.createElement('details');
        details.className = 'parameter-group';
        const summary = document.createElement('summary');
        const count = document.createElement('span');
        count.className = 'group-count';
        summary.append(document.createTextNode(`${t(group.label)} `), count);
        const label = document.createElement('label');
        label.className = 'group-toggle';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.addEventListener('change', () => changeSelection(parameters.map(item => item.value), input.checked));
        label.append(input, document.createTextNode(t('photoSelectGroup')));
        details.append(summary, label);
        if (group.sections) {
            for (const section of group.sections) {
                const heading = document.createElement('p');
                heading.className = 'parameter-section';
                heading.textContent = t(section.label);
                details.append(heading);
                addOptions(details, section.parameters);
            }
        } else {
            addOptions(details, parameters);
        }
        groups.push({ parameters, input, count });
        container.append(details);
    }
}

function changeSelection(values, checked) {
    const selected = new Set(settings.selectedParameters);
    for (const value of values) checked ? selected.add(value) : selected.delete(value);
    const empty = selected.size === 0;
    document.querySelector('#selection-warning').classList.toggle('hidden', !empty);
    if (!empty) {
        settings = normalizePhotoSettings({ ...settings, selectedParameters: [...selected] });
        $UD.setSettings(settings);
    }
    renderSettings();
}

function renderSettings() {
    const selected = new Set(settings.selectedParameters);
    const select = form.elements.press;
    select.replaceChildren();
    for (const group of PHOTO_PARAMETER_GROUPS) {
        const optionGroup = document.createElement('optgroup');
        optionGroup.label = t(group.label);
        const parameters = group.parameters || group.sections.flatMap(section => section.parameters);
        for (const parameter of parameters.filter(item => selected.has(item.value))) {
            const option = document.createElement('option');
            option.value = parameter.value;
            option.textContent = t(parameter.label);
            optionGroup.append(option);
        }
        if (optionGroup.children.length) select.append(optionGroup);
    }
    select.value = settings.press;
    form.elements.stepSize.value = settings.stepSize;
    form.elements.exposureStepSize.value = settings.exposureStepSize;
    document.querySelector('#step-value').textContent = settings.stepSize;
    document.querySelector('#exposure-value').textContent = settings.exposureStepSize;
    document.querySelector('#step-row').classList.toggle('hidden', settings.press === 'EXPOSURE');
    document.querySelector('#exposure-row').classList.toggle('hidden', settings.press !== 'EXPOSURE');
    document.querySelector('#selection-count').textContent = `${selected.size} / ${PHOTO_PARAMETERS.length}`;
    for (const [value, input] of parameterInputs) {
        input.checked = selected.has(value);
        input.disabled = selected.size === 1 && input.checked;
    }
    for (const group of groups) {
        const count = group.parameters.filter(item => selected.has(item.value)).length;
        group.count.textContent = `(${count}/${group.parameters.length})`;
        group.input.checked = count === group.parameters.length;
        group.input.indeterminate = count > 0 && count < group.parameters.length;
    }
}

$UD.connect();
$UD.onConnected(async () => {
    await $UD.localizeUI();
    form = document.querySelector('#photo-settings');
    renderGroups();
    renderSettings();
    document.querySelector('.uspi-wrapper').classList.remove('hidden');
    form.addEventListener('input', event => {
        if (!['press', 'stepSize', 'exposureStepSize'].includes(event.target.name)) return;
        settings = normalizePhotoSettings({ ...settings, [event.target.name]: event.target.value });
        renderSettings();
        $UD.setSettings(settings);
    });
});

function receiveSettings(value) {
    settings = normalizePhotoSettings(value);
    if (form) renderSettings();
}

$UD.onParamFromApp(event => receiveSettings(event.param || {}));
$UD.onDidReceiveSettings(event => {
    if ($UD.actionid !== event.actionid || !event.settings) return;
    receiveSettings(event.settings);
});
$UD.on('sendToPropertyInspector', event => {
    const status = event.payload?.connectStatus;
    if (!status) return;
    const element = document.querySelector('#connect-status');
    element.textContent = t(status);
    element.className = `tip ${{ Connected: 'success', Disconnected: 'error', Installed: 'info', NotInstalled: 'warn', Connecting: 'info', Updated: 'info' }[status] || 'info'}`;
});
