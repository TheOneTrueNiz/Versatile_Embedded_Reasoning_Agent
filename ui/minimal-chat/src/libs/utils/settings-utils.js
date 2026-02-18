import { ref } from 'vue';
import { isAvatarEnabled, avatarUrl, selectedModel, ttsVoice, whisperTemperature, audioSpeed, ttsModel, useWhisper, pushToTalkMode, higherContrastMessages, isSidebarOpen, systemPrompt, localModelName, localSliderValue, top_P, repetitionPenalty, presencePenalty, maxTokens, localModelEndpoint, localModelKey, selectedAutoSaveOption, browserModelSelection, gptKey, sliderValue, claudeKey, claudeSliderValue, selectedDallEImageCount, selectedDallEImageResolution, availableModels, userAvatarUrl, avatarShape, voiceAgentVoice, uiThemeMode, uiAccentColor, uiThemePreset, uiBackgroundMode, uiBackgroundPreset, uiBackgroundColor, uiBackgroundGradientStart, uiBackgroundGradientEnd, uiBackgroundGradientAngle, uiBackgroundImage, uiBackgroundImageOpacity, uiBackgroundImageBlur, uiSidebarBackgroundMode, uiSidebarBackgroundPreset, uiSidebarBackgroundColor, uiSidebarBackgroundGradientStart, uiSidebarBackgroundGradientEnd, uiSidebarBackgroundGradientAngle, uiSidebarBackgroundImage, uiSidebarBackgroundImageOpacity, uiSidebarBackgroundImageBlur, uiInputBarBackgroundColor, uiInputBarBackgroundOpacity, uiInputBarBorderColor, uiInputBarBorderOpacity, uiInputBarGlow, uiToolCardBackgroundColor, uiToolCardBackgroundOpacity, uiToolCardBorderColor, uiToolCardBorderOpacity, uiToolCardGlow, uiPanelSurfacePresets } from '../state-management/state';
import { removeAPIEndpoints, showToast } from "./general-utils";
import { getOpenAICompatibleAvailableModels } from '../api-access/open-ai-api-standard-access';

export const showGPTConfig = ref(false);
export const showLocalConfig = ref(selectedModel.value.indexOf('open-ai-format') !== -1);
export const showClaudeConfig = ref(false);
export const showBrowserModelConfig = ref(selectedModel.value.indexOf('web-llm') !== -1);

export function update(field, value) {
  if (field === 'model') {
    showGPTConfig.value = false;
    showLocalConfig.value = value.indexOf('open-ai-format') !== -1;
    showClaudeConfig.value = false;
    showBrowserModelConfig.value = value.indexOf('web-llm') !== -1;
    selectedModel.value = value;

    return;
  }

  if (field === 'systemPrompt') {
    systemPrompt.value = value;
    saveSystemPrompt(value);

    return;
  }

  if (['localModelName', 'localSliderValue', 'top_P', 'repetitionPenalty', 'presencePenalty', 'maxTokens', 'localModelEndpoint', 'localModelKey'].includes(field)) {
    if (field === 'localModelName') localModelName.value = value;
    if (field === 'localSliderValue') localSliderValue.value = value;
    if (field === 'top_P') top_P.value = value;
    if (field === 'repetitionPenalty') repetitionPenalty.value = value;
    if (field === 'presencePenalty') presencePenalty.value = value;
    if (field === 'maxTokens') maxTokens.value = value;
    if (field === 'localModelEndpoint') localModelEndpoint.value = value;
    if (field === 'localModelKey') localModelKey.value = value;

    if (selectedCustomConfigIndex.value !== null || !customConfigs.value.length) {
      saveCustomConfig();
    }

    return;
  }

  if (field === 'selectedAutoSaveOption') selectedAutoSaveOption.value = value;
  if (field === 'browserModelSelection') browserModelSelection.value = value;
  if (field === 'gptKey') gptKey.value = value;
  if (field === 'sliderValue') sliderValue.value = value;
  if (field === 'claudeKey') claudeKey.value = value;
  if (field === 'claudeSliderValue') claudeSliderValue.value = value;
  if (field === 'selectedDallEImageCount') selectedDallEImageCount.value = value;
  if (field === 'selectedDallEImageResolution') selectedDallEImageResolution.value = value;
  if (field === 'customConfigs') customConfigs.value = value;
  if (field === 'systemPrompts') systemPrompts.value = value;
  if (field === 'higherContrastMessages') higherContrastMessages.value = value;
  if (field === 'use-push-to-talk') pushToTalkMode.value = value;
  if (field === 'use-whisper') useWhisper.value = value;
  if (field === 'audio-speed') audioSpeed.value = value;
  if (field === 'tts-model') ttsModel.value = value;
  if (field === 'tts-voice') ttsVoice.value = value;
  if (field === 'whisper-temperature') whisperTemperature.value = value;
  if (field === 'isAvatarEnabled') isAvatarEnabled.value = value;
  if (field === 'avatarUrl') avatarUrl.value = value;
  if (field === 'userAvatarUrl') userAvatarUrl.value = value;
  if (field === 'avatarShape') avatarShape.value = value;
  if (field === 'voiceAgentVoice') voiceAgentVoice.value = value;
  if (field === 'uiThemeMode') uiThemeMode.value = value;
  if (field === 'uiAccentColor') uiAccentColor.value = value;
  if (field === 'uiThemePreset') uiThemePreset.value = value;
  if (field === 'uiBackgroundMode') uiBackgroundMode.value = value;
  if (field === 'uiBackgroundPreset') uiBackgroundPreset.value = value;
  if (field === 'uiBackgroundColor') uiBackgroundColor.value = value;
  if (field === 'uiBackgroundGradientStart') uiBackgroundGradientStart.value = value;
  if (field === 'uiBackgroundGradientEnd') uiBackgroundGradientEnd.value = value;
  if (field === 'uiBackgroundGradientAngle') uiBackgroundGradientAngle.value = value;
  if (field === 'uiBackgroundImage') uiBackgroundImage.value = value;
  if (field === 'uiBackgroundImageOpacity') uiBackgroundImageOpacity.value = value;
  if (field === 'uiBackgroundImageBlur') uiBackgroundImageBlur.value = value;
  if (field === 'uiSidebarBackgroundMode') uiSidebarBackgroundMode.value = value;
  if (field === 'uiSidebarBackgroundPreset') uiSidebarBackgroundPreset.value = value;
  if (field === 'uiSidebarBackgroundColor') uiSidebarBackgroundColor.value = value;
  if (field === 'uiSidebarBackgroundGradientStart') uiSidebarBackgroundGradientStart.value = value;
  if (field === 'uiSidebarBackgroundGradientEnd') uiSidebarBackgroundGradientEnd.value = value;
  if (field === 'uiSidebarBackgroundGradientAngle') uiSidebarBackgroundGradientAngle.value = value;
  if (field === 'uiSidebarBackgroundImage') uiSidebarBackgroundImage.value = value;
  if (field === 'uiSidebarBackgroundImageOpacity') uiSidebarBackgroundImageOpacity.value = value;
  if (field === 'uiSidebarBackgroundImageBlur') uiSidebarBackgroundImageBlur.value = value;
  if (field === 'uiInputBarBackgroundColor') uiInputBarBackgroundColor.value = value;
  if (field === 'uiInputBarBackgroundOpacity') uiInputBarBackgroundOpacity.value = value;
  if (field === 'uiInputBarBorderColor') uiInputBarBorderColor.value = value;
  if (field === 'uiInputBarBorderOpacity') uiInputBarBorderOpacity.value = value;
  if (field === 'uiInputBarGlow') uiInputBarGlow.value = value;
  if (field === 'uiToolCardBackgroundColor') uiToolCardBackgroundColor.value = value;
  if (field === 'uiToolCardBackgroundOpacity') uiToolCardBackgroundOpacity.value = value;
  if (field === 'uiToolCardBorderColor') uiToolCardBorderColor.value = value;
  if (field === 'uiToolCardBorderOpacity') uiToolCardBorderOpacity.value = value;
  if (field === 'uiToolCardGlow') uiToolCardGlow.value = value;
  if (field === 'uiPanelSurfacePresets') uiPanelSurfacePresets.value = Array.isArray(value) ? value : [];
}


export const systemPrompts = ref([]);
export const selectedSystemPromptIndex = ref(null);

export function saveSystemPrompt(prompt) {
  if (prompt !== '') {
    const trimmedPrompt = prompt.trim();
    if (!systemPrompts.value.includes(trimmedPrompt)) {
      systemPrompts.value.push(trimmedPrompt);
      localStorage.setItem('system-prompts', JSON.stringify(systemPrompts.value));
      selectedSystemPromptIndex.value = systemPrompts.value.length - 1;
      showToast('Added New System Prompt');
    }
  } else {
    selectedSystemPromptIndex.value = -1;
  }
}

export function handleSaveSystemPrompt(prompt) {
  saveSystemPrompt(prompt);
}

export function deleteSystemPrompt(index) {
  systemPrompts.value.splice(index, 1);
  localStorage.setItem('system-prompts', JSON.stringify(systemPrompts.value));
  showToast('Deleted System Prompt');
}

export function selectSystemPrompt(index) {
  selectedSystemPromptIndex.value = index;
  systemPrompt.value = systemPrompts.value[index];
}

export const customConfigs = ref([]);
export const selectedCustomConfigIndex = ref(null);

export function saveCustomConfig() {
  if (localModelEndpoint.value.trim() === '') {
    return;
  }

  const newConfig = {
    endpoint: localModelEndpoint.value,
    apiKey: localModelKey.value,
    modelName: localModelName.value,
    maxTokens: maxTokens.value,
    temperature: localSliderValue.value,
    top_P: top_P.value,
    repetitionPenalty: repetitionPenalty.value,
    presencePenalty: presencePenalty.value,
  };

  const existingConfigIndex = customConfigs.value.findIndex((config) => config.endpoint === newConfig.endpoint);

  if (existingConfigIndex !== -1) {
    customConfigs.value[existingConfigIndex] = newConfig;
  } else {
    customConfigs.value.push(newConfig);
    selectedCustomConfigIndex.value = customConfigs.value.length - 1;
    showToast('Saved New Custom Config');
  }

  localStorage.setItem('saved-custom-configs', JSON.stringify(customConfigs.value));
}

export function deleteCustomConfig(index) {
  customConfigs.value.splice(index, 1);
  localStorage.setItem('saved-custom-configs', JSON.stringify(customConfigs.value));
  showToast('Deleted Custom Config');
}

export async function selectCustomConfig(index) {
  selectedCustomConfigIndex.value = index;
  const config = customConfigs.value[index];
  localModelEndpoint.value = config.endpoint;
  localModelKey.value = config.apiKey;
  localModelName.value = config.modelName;
  maxTokens.value = config.maxTokens;
  localSliderValue.value = config.temperature;
  top_P.value = config.top_P;
  repetitionPenalty.value = config.repetitionPenalty;
  presencePenalty.value = config.presencePenalty ?? presencePenalty.value;
  selectedModel.value = "open-ai-format";

  try {
    if (localModelEndpoint.value.trim() !== '') {
      const models = await getOpenAICompatibleAvailableModels(removeAPIEndpoints(localModelEndpoint.value));
      availableModels.value = models;
    }
  } catch (error) {
    console.error('Error fetching available models:', error);
  }
}

export function handleExportSettings(settingsData, exportFn = exportSettingsToFile) {
  const data = settingsData || {
    isSidebarOpen: isSidebarOpen.value,
    selectedModel: selectedModel.value,
    localModelName: localModelName.value,
    localModelEndpoint: localModelEndpoint.value,
    localModelKey: localModelKey.value,
    localSliderValue: localSliderValue.value,
    gptKey: gptKey.value,
    sliderValue: sliderValue.value,
    claudeKey: claudeKey.value,
    claudeSliderValue: claudeSliderValue.value,
    selectedDallEImageCount: selectedDallEImageCount.value,
    selectedDallEImageResolution: selectedDallEImageResolution.value,
    selectedAutoSaveOption: selectedAutoSaveOption.value,
    browserModelSelection: browserModelSelection.value,
    maxTokens: maxTokens.value,
    top_P: top_P.value,
    repetitionPenalty: repetitionPenalty.value,
    presencePenalty: presencePenalty.value,
    systemPrompt: systemPrompt.value,
    voiceAgentVoice: voiceAgentVoice.value,
    uiThemeMode: uiThemeMode.value,
    uiAccentColor: uiAccentColor.value,
    uiThemePreset: uiThemePreset.value,
    uiBackgroundMode: uiBackgroundMode.value,
    uiBackgroundPreset: uiBackgroundPreset.value,
    uiBackgroundColor: uiBackgroundColor.value,
    uiBackgroundGradientStart: uiBackgroundGradientStart.value,
    uiBackgroundGradientEnd: uiBackgroundGradientEnd.value,
    uiBackgroundGradientAngle: uiBackgroundGradientAngle.value,
    uiBackgroundImage: uiBackgroundImage.value,
    uiBackgroundImageOpacity: uiBackgroundImageOpacity.value,
    uiBackgroundImageBlur: uiBackgroundImageBlur.value,
    uiSidebarBackgroundMode: uiSidebarBackgroundMode.value,
    uiSidebarBackgroundPreset: uiSidebarBackgroundPreset.value,
    uiSidebarBackgroundColor: uiSidebarBackgroundColor.value,
    uiSidebarBackgroundGradientStart: uiSidebarBackgroundGradientStart.value,
    uiSidebarBackgroundGradientEnd: uiSidebarBackgroundGradientEnd.value,
    uiSidebarBackgroundGradientAngle: uiSidebarBackgroundGradientAngle.value,
    uiSidebarBackgroundImage: uiSidebarBackgroundImage.value,
    uiSidebarBackgroundImageOpacity: uiSidebarBackgroundImageOpacity.value,
    uiSidebarBackgroundImageBlur: uiSidebarBackgroundImageBlur.value,
    uiInputBarBackgroundColor: uiInputBarBackgroundColor.value,
    uiInputBarBackgroundOpacity: uiInputBarBackgroundOpacity.value,
    uiInputBarBorderColor: uiInputBarBorderColor.value,
    uiInputBarBorderOpacity: uiInputBarBorderOpacity.value,
    uiInputBarGlow: uiInputBarGlow.value,
    uiToolCardBackgroundColor: uiToolCardBackgroundColor.value,
    uiToolCardBackgroundOpacity: uiToolCardBackgroundOpacity.value,
    uiToolCardBorderColor: uiToolCardBorderColor.value,
    uiToolCardBorderOpacity: uiToolCardBorderOpacity.value,
    uiToolCardGlow: uiToolCardGlow.value,
    uiPanelSurfacePresets: uiPanelSurfacePresets.value,
    customConfigs: customConfigs.value,
    systemPrompts: systemPrompts.value
  };

  exportFn(data);
}

export async function fetchAvailableModels() {
  try {
      if (localModelEndpoint.value.trim() !== '') {
          const models = await getOpenAICompatibleAvailableModels(removeAPIEndpoints(localModelEndpoint.value));
          availableModels.value = models;
      }
  } catch (error) {
      console.error('Error fetching available models:', error);
  }
}

export function exportSettingsToFile(settingsData) {
  const filename = 'vera-settings.json';
  const text = JSON.stringify(settingsData, null, 2); // Pretty print JSON

  let element = document.createElement('a');
  element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(text));
  element.setAttribute('download', filename);
  element.style.display = 'none';
  document.body.appendChild(element);

  element.click();

  document.body.removeChild(element);
}

export function handleImportSettings(event, importSettings) {
  const file = event.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = function (e) {
      const settingsData = JSON.parse(e.target.result);
      importSettings(settingsData);

      selectedModel.value = "open-ai-format";
      saveCustomConfig();
    };
    reader.readAsText(file);
  }
}

export function importSettings(settingsData, update2) {
  for (const key in settingsData) {
    if (Object.prototype.hasOwnProperty.call(settingsData, key)) {
      update(key, settingsData[key]);
    }
  }
}

export function handleDeleteSystemPrompt(index) {
  deleteSystemPrompt(index, showToast);
}

export function handleSelectSystemPrompt(index) {
  selectSystemPrompt(index, systemPrompt);
}

// Custom Configs
export function handleDeleteCustomConfig(index) {
  deleteCustomConfig(index, showToast);
}

export function handleUpdate(field, value) {
  update(field, value);
}


export function updateGptSliderValue(value) {
  handleUpdate('sliderValue', parseFloat(value));
}

export function updateWhisperSlider(value) {
  handleUpdate('whisper-temperature', parseFloat(value));
}

export function updateLocalSliderValue(value) {
  handleUpdate('localSliderValue', parseFloat(value));
}

export function updateClaudeSliderValue(value) {
  handleUpdate('claudeSliderValue', parseFloat(value));
}

export function updateTopPSliderValue(value) {
  handleUpdate('top_P', parseFloat(value));
}

export function updateMaxTokensSliderValue(value) {
  handleUpdate('maxTokens', parseFloat(value));
}

export function updateRepetitionSliderValue(value) {
  handleUpdate('repetitionPenalty', parseFloat(value));
}

export function updatePresenceSliderValue(value) {
  handleUpdate('presencePenalty', parseFloat(value));
}

export function handleSelectCustomConfig(index) {
  selectCustomConfig(index, localModelEndpoint, localModelKey, localModelName, maxTokens, localSliderValue, top_P, repetitionPenalty);
}
