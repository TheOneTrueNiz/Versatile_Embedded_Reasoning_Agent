const steps = ["welcome", "llm", "optional", "google", "summary"];
let currentStep = 0;

const state = {
  llmMode: "xai",
  toggles: {
    brave: false,
    github: false,
    searxng: false,
    obsidian: false,
    hub: false,
    browser: false,
    telegram: false,
    whatsapp: false,
    discord: false,
  },
};

const parseStoredJson = (value, fallback) => {
  if (!value) {
    return fallback;
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch (error) {
    return fallback;
  }
};

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const normalizeHex = (value) => {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed.startsWith("#")) return "";
  if (trimmed.length === 4) {
    return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}`;
  }
  if (trimmed.length === 5) {
    return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}${trimmed[4]}${trimmed[4]}`;
  }
  if (trimmed.length === 7 || trimmed.length === 9) {
    return trimmed.slice(0, 7);
  }
  return "";
};

const hexToRgb = (hex) => {
  const normalized = normalizeHex(hex);
  if (!normalized) return null;
  const raw = normalized.slice(1, 7);
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  if ([r, g, b].some((value) => Number.isNaN(value))) {
    return null;
  }
  return { r, g, b };
};

const adjustColor = (hex, amount) => {
  const rgb = hexToRgb(hex);
  if (!rgb) return "";
  const mix = (channel) => clamp(Math.round(channel + (255 - channel) * amount), 0, 255);
  const shift = (channel) => clamp(Math.round(channel * (1 + amount)), 0, 255);
  const r = amount >= 0 ? mix(rgb.r) : shift(rgb.r);
  const g = amount >= 0 ? mix(rgb.g) : shift(rgb.g);
  const b = amount >= 0 ? mix(rgb.b) : shift(rgb.b);
  return `#${[r, g, b].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
};

const readCssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const applyThemeOverrides = () => {
  const root = document.documentElement;
  const overrides = parseStoredJson(localStorage.getItem("uiThemeOverrides"), {});
  const overrideKeys = new Set(Object.keys(overrides || {}));

  Object.entries(overrides).forEach(([key, value]) => {
    if (typeof key === "string" && typeof value === "string") {
      root.style.setProperty(key, value);
    }
  });

  const accent = readCssVar("--vera-accent");
  const accentRgb = hexToRgb(accent);
  if (accentRgb && !overrideKeys.has("--vera-accent-rgb")) {
    root.style.setProperty("--vera-accent-rgb", `${accentRgb.r}, ${accentRgb.g}, ${accentRgb.b}`);
  }
  if (accent && !overrideKeys.has("--vera-accent-strong")) {
    const strongAccent = adjustColor(accent, 0.12);
    if (strongAccent) {
      root.style.setProperty("--vera-accent-strong", strongAccent);
    }
  }

  const secondary = readCssVar("--vera-secondary");
  const secondaryRgb = hexToRgb(secondary);
  if (secondaryRgb && !overrideKeys.has("--vera-secondary-rgb")) {
    root.style.setProperty("--vera-secondary-rgb", `${secondaryRgb.r}, ${secondaryRgb.g}, ${secondaryRgb.b}`);
  }
};

applyThemeOverrides();

const stepEls = document.querySelectorAll(".step");
const stepperEls = document.querySelectorAll(".stepper li");

const toggleCards = document.querySelectorAll(".toggle-card");
const optionalBlocks = document.querySelectorAll("[data-optional]");
const llmBlocks = document.querySelectorAll("[data-llm]");

const summaryCard = document.getElementById("summaryCard");
const statusText = document.getElementById("statusText");
const wizardToast = document.getElementById("wizardToast");
let mainUrl = "http://127.0.0.1:8788";

function setStep(index) {
  currentStep = Math.max(0, Math.min(index, steps.length - 1));
  const stepName = steps[currentStep];

  stepEls.forEach((el) => {
    el.classList.toggle("active", el.dataset.step === stepName);
  });
  stepperEls.forEach((el) => {
    el.classList.toggle("active", el.dataset.step === stepName);
  });

  if (stepName === "summary") {
    buildSummary();
  }
}

function showLLMMode() {
  llmBlocks.forEach((block) => {
    block.classList.toggle("hidden", block.dataset.llm !== state.llmMode);
  });
}

function toggleOptional(key, value) {
  state.toggles[key] = value;
  toggleCards.forEach((card) => {
    if (card.dataset.toggle === key) {
      card.classList.toggle("active", value);
      const btn = card.querySelector("[data-toggle-btn]");
      if (btn) btn.textContent = value ? "On" : "Off";
    }
  });
  optionalBlocks.forEach((block) => {
    if (block.dataset.optional === key) {
      block.classList.toggle("hidden", !value);
    }
  });
}

function buildSummary() {
  const lines = [];
  const xaiKey = document.getElementById("xaiKey").value.trim();
  const localBase = document.getElementById("localBaseUrl").value.trim();

  if (state.llmMode === "xai") {
    lines.push(`LLM: xAI API key ${xaiKey ? "set" : "missing"}`);
  } else {
    lines.push(`LLM: Local endpoint ${localBase || "missing"}`);
  }

  lines.push(`Brave: ${state.toggles.brave ? "enabled" : "skipped"}`);
  lines.push(`GitHub: ${state.toggles.github ? "enabled" : "skipped"}`);
  lines.push(`Searxng: ${state.toggles.searxng ? "enabled" : "skipped"}`);

  const obsidianPath = document.getElementById("obsidianPath").value.trim();
  lines.push(`Obsidian: ${state.toggles.obsidian ? obsidianPath || "missing" : "skipped"}`);

  const hubCommand = document.getElementById("hubCommand").value.trim();
  lines.push(`Hub: ${state.toggles.hub ? hubCommand || "missing" : "skipped"}`);

  lines.push(`Browser automation: ${state.toggles.browser ? "enabled" : "skipped"}`);

  const telegramToken = document.getElementById("telegramToken").value.trim();
  lines.push(`Telegram: ${state.toggles.telegram ? (telegramToken ? "enabled" : "missing token") : "skipped"}`);

  const whatsappToken = document.getElementById("whatsappAccessToken").value.trim();
  const whatsappPhoneId = document.getElementById("whatsappPhoneId").value.trim();
  const whatsappOk = whatsappToken && whatsappPhoneId;
  lines.push(`WhatsApp: ${state.toggles.whatsapp ? (whatsappOk ? "enabled" : "missing token/phone id") : "skipped"}`);

  const discordToken = document.getElementById("discordToken").value.trim();
  lines.push(`Discord: ${state.toggles.discord ? (discordToken ? "enabled" : "missing token") : "skipped"}`);

  const googleEmail = document.getElementById("googleEmail").value.trim();
  const googleId = document.getElementById("googleClientId").value.trim();
  const googleSecret = document.getElementById("googleClientSecret").value.trim();
  const googleOk = googleEmail && googleId && googleSecret;
  lines.push(`Google Workspace: ${googleOk ? "configured" : "skipped"}`);

  summaryCard.innerHTML = lines.map((line) => `<p>${line}</p>`).join("");
}

function showWizardToast(message) {
  if (!wizardToast) return;
  wizardToast.textContent = message;
  wizardToast.classList.add("show");
  clearTimeout(showWizardToast._timer);
  showWizardToast._timer = setTimeout(() => {
    wizardToast.classList.remove("show");
  }, 5200);
}

async function fetchConfig() {
  try {
    const response = await fetch("/api/setup/config");
    if (!response.ok) return;
    const data = await response.json();
    if (data?.main_url) {
      mainUrl = data.main_url;
    }
    if (data?.defaults) {
      applyDefaults(data.defaults);
    }
  } catch (error) {
    console.error(error);
  }
}

async function waitForHealth() {
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${mainUrl}/api/health`, { cache: "no-store" });
      if (response.ok) {
        return true;
      }
    } catch (error) {
      // ignore during startup
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  return false;
}

function validateLLM() {
  if (state.llmMode === "xai") {
    const key = document.getElementById("xaiKey").value.trim();
    if (!key) {
      statusText.textContent = "Enter your XAI API key to continue.";
      return false;
    }
  } else {
    const base = document.getElementById("localBaseUrl").value.trim();
    if (!base) {
      statusText.textContent = "Enter a local base URL to continue.";
      return false;
    }
  }
  statusText.textContent = "";
  return true;
}

function validateChannels() {
  if (state.toggles.telegram) {
    const token = document.getElementById("telegramToken").value.trim();
    if (!token) {
      statusText.textContent = "Telegram is enabled but the bot token is missing.";
      setStep(2);
      return false;
    }
  }
  if (state.toggles.whatsapp) {
    const token = document.getElementById("whatsappAccessToken").value.trim();
    const phoneId = document.getElementById("whatsappPhoneId").value.trim();
    if (!token || !phoneId) {
      statusText.textContent = "WhatsApp is enabled but access token or phone number ID is missing.";
      setStep(2);
      return false;
    }
  }
  if (state.toggles.discord) {
    const token = document.getElementById("discordToken").value.trim();
    if (!token) {
      statusText.textContent = "Discord is enabled but the bot token is missing.";
      setStep(2);
      return false;
    }
  }
  return true;
}

function applyDefaults(defaults) {
  if (!defaults) return;

  const setValue = (id, value) => {
    const el = document.getElementById(id);
    if (el && value) {
      el.value = value;
    }
  };

  if (defaults.XAI_API_KEY && !defaults.VERA_LLM_BASE_URL) {
    state.llmMode = "xai";
    document.querySelector('input[name="llm-mode"][value="xai"]').checked = true;
  } else if (defaults.VERA_LLM_BASE_URL) {
    state.llmMode = "local";
    document.querySelector('input[name="llm-mode"][value="local"]').checked = true;
  }

  setValue("xaiKey", defaults.XAI_API_KEY);
  setValue("localBaseUrl", defaults.VERA_LLM_BASE_URL);
  setValue("localApiKey", defaults.VERA_LLM_API_KEY);
  setValue("localModelId", defaults.VERA_MODEL);
  setValue("braveKey", defaults.BRAVE_API_KEY);
  setValue("githubToken", defaults.GITHUB_PERSONAL_ACCESS_TOKEN);
  setValue("searxngUrl", defaults.SEARXNG_BASE_URL);
  setValue("obsidianPath", defaults.OBSIDIAN_VAULT_PATH);
  setValue("hubCommand", defaults.MCP_HUB_COMMAND);
  setValue("hubArgs", defaults.MCP_HUB_ARGS);
  setValue("composioKey", defaults.COMPOSIO_API_KEY);
  setValue("googleEmail", defaults.GOOGLE_WORKSPACE_USER_EMAIL);
  setValue("googleClientId", defaults.GOOGLE_OAUTH_CLIENT_ID);
  setValue("googleClientSecret", defaults.GOOGLE_OAUTH_CLIENT_SECRET);
  setValue("googleRedirectUri", defaults.GOOGLE_OAUTH_REDIRECT_URI);

  setValue("telegramToken", defaults.TELEGRAM_BOT_TOKEN);
  setValue("telegramChats", defaults.TELEGRAM_ALLOWED_CHATS);
  setValue("telegramUsers", defaults.TELEGRAM_ALLOWED_USERS);
  setValue("telegramPrefix", defaults.TELEGRAM_COMMAND_PREFIX);

  setValue("whatsappAccessToken", defaults.WHATSAPP_ACCESS_TOKEN);
  setValue("whatsappPhoneId", defaults.WHATSAPP_PHONE_NUMBER_ID);
  setValue("whatsappVerifyToken", defaults.WHATSAPP_VERIFY_TOKEN);
  setValue("whatsappAppSecret", defaults.WHATSAPP_APP_SECRET);
  setValue("whatsappAllowedNumbers", defaults.WHATSAPP_ALLOWED_NUMBERS);
  setValue("whatsappGraphVersion", defaults.WHATSAPP_GRAPH_VERSION);

  setValue("discordToken", defaults.DISCORD_BOT_TOKEN);
  setValue("discordGuilds", defaults.DISCORD_ALLOWED_GUILDS);
  setValue("discordUsers", defaults.DISCORD_ALLOWED_USERS);
  setValue("discordPrefix", defaults.DISCORD_COMMAND_PREFIX);

  if (defaults.BRAVE_API_KEY) toggleOptional("brave", true);
  if (defaults.GITHUB_PERSONAL_ACCESS_TOKEN) toggleOptional("github", true);
  if (defaults.SEARXNG_BASE_URL) toggleOptional("searxng", true);
  if (defaults.OBSIDIAN_VAULT_PATH) toggleOptional("obsidian", true);
  if (defaults.MCP_HUB_COMMAND || defaults.COMPOSIO_API_KEY) toggleOptional("hub", true);
  if (defaults.VERA_BROWSER && defaults.VERA_BROWSER !== "0") toggleOptional("browser", true);
  if (defaults.TELEGRAM_BOT_TOKEN) toggleOptional("telegram", true);
  if (defaults.WHATSAPP_ACCESS_TOKEN || defaults.WHATSAPP_PHONE_NUMBER_ID) toggleOptional("whatsapp", true);
  if (defaults.DISCORD_BOT_TOKEN) toggleOptional("discord", true);

  showLLMMode();
}

function collectPayload() {
  return {
    XAI_API_KEY: document.getElementById("xaiKey").value.trim(),
    VERA_LLM_BASE_URL: document.getElementById("localBaseUrl").value.trim(),
    VERA_LLM_API_KEY: document.getElementById("localApiKey").value.trim(),
    VERA_MODEL: document.getElementById("localModelId").value.trim(),
    BRAVE_API_KEY: state.toggles.brave ? document.getElementById("braveKey").value.trim() : "",
    GITHUB_PERSONAL_ACCESS_TOKEN: state.toggles.github ? document.getElementById("githubToken").value.trim() : "",
    SEARXNG_BASE_URL: state.toggles.searxng ? document.getElementById("searxngUrl").value.trim() : "",
    OBSIDIAN_VAULT_PATH: state.toggles.obsidian ? document.getElementById("obsidianPath").value.trim() : "",
    MCP_HUB_COMMAND: state.toggles.hub ? document.getElementById("hubCommand").value.trim() : "",
    MCP_HUB_ARGS: state.toggles.hub ? document.getElementById("hubArgs").value.trim() : "",
    COMPOSIO_API_KEY: state.toggles.hub ? document.getElementById("composioKey").value.trim() : "",
    VERA_BROWSER: state.toggles.browser ? "1" : "0",
    ENABLE_TELEGRAM: state.toggles.telegram ? "1" : "0",
    TELEGRAM_BOT_TOKEN: state.toggles.telegram ? document.getElementById("telegramToken").value.trim() : "",
    TELEGRAM_ALLOWED_CHATS: state.toggles.telegram ? document.getElementById("telegramChats").value.trim() : "",
    TELEGRAM_ALLOWED_USERS: state.toggles.telegram ? document.getElementById("telegramUsers").value.trim() : "",
    TELEGRAM_COMMAND_PREFIX: state.toggles.telegram ? document.getElementById("telegramPrefix").value.trim() : "",
    ENABLE_WHATSAPP: state.toggles.whatsapp ? "1" : "0",
    WHATSAPP_ACCESS_TOKEN: state.toggles.whatsapp ? document.getElementById("whatsappAccessToken").value.trim() : "",
    WHATSAPP_PHONE_NUMBER_ID: state.toggles.whatsapp ? document.getElementById("whatsappPhoneId").value.trim() : "",
    WHATSAPP_VERIFY_TOKEN: state.toggles.whatsapp ? document.getElementById("whatsappVerifyToken").value.trim() : "",
    WHATSAPP_APP_SECRET: state.toggles.whatsapp ? document.getElementById("whatsappAppSecret").value.trim() : "",
    WHATSAPP_ALLOWED_NUMBERS: state.toggles.whatsapp ? document.getElementById("whatsappAllowedNumbers").value.trim() : "",
    WHATSAPP_GRAPH_VERSION: state.toggles.whatsapp ? document.getElementById("whatsappGraphVersion").value.trim() : "",
    ENABLE_DISCORD: state.toggles.discord ? "1" : "0",
    DISCORD_BOT_TOKEN: state.toggles.discord ? document.getElementById("discordToken").value.trim() : "",
    DISCORD_ALLOWED_GUILDS: state.toggles.discord ? document.getElementById("discordGuilds").value.trim() : "",
    DISCORD_ALLOWED_USERS: state.toggles.discord ? document.getElementById("discordUsers").value.trim() : "",
    DISCORD_COMMAND_PREFIX: state.toggles.discord ? document.getElementById("discordPrefix").value.trim() : "",
    GOOGLE_WORKSPACE_USER_EMAIL: document.getElementById("googleEmail").value.trim(),
    GOOGLE_OAUTH_CLIENT_ID: document.getElementById("googleClientId").value.trim(),
    GOOGLE_OAUTH_CLIENT_SECRET: document.getElementById("googleClientSecret").value.trim(),
    GOOGLE_OAUTH_REDIRECT_URI: document.getElementById("googleRedirectUri").value.trim(),
  };
}

async function saveAndLaunch() {
  if (!validateLLM()) {
    setStep(1);
    return;
  }
  if (!validateChannels()) {
    return;
  }
  statusText.textContent = "Saving credentials...";
  const payload = collectPayload();
  const response = await fetch("/api/setup/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    statusText.textContent = data.error || "Unable to save credentials.";
    return;
  }
  await fetch("/api/setup/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delay_seconds: 8 }),
  });

  statusText.textContent = "Launching Vera...";
  showWizardToast("Vera is starting. Handshake in progress.");

  const ready = await waitForHealth();
  if (!ready) {
    statusText.textContent =
      "Vera is still starting. You can keep this tab open or close it when ready.";
    showWizardToast("Still booting. You'll know when Vera appears.");
    return;
  }

  let countdown = 5;
  statusText.textContent = `Vera is online. Opening in ${countdown}s...`;
  showWizardToast("Handshake complete. Vera is online.");

  const timer = setInterval(() => {
    countdown -= 1;
    if (countdown <= 0) {
      clearInterval(timer);
      statusText.textContent = "Opening Vera...";
      setTimeout(() => {
        window.location.replace(mainUrl);
      }, 250);
      return;
    }
    statusText.textContent = `Vera is online. Opening in ${countdown}s...`;
  }, 1000);
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (target.matches("[data-next]")) {
    if (steps[currentStep] === "llm" && !validateLLM()) {
      return;
    }
    setStep(currentStep + 1);
  }
  if (target.matches("[data-back]")) {
    setStep(currentStep - 1);
  }
  if (target.matches("[data-toggle-btn]")) {
    const card = target.closest(".toggle-card");
    if (!card) return;
    const key = card.dataset.toggle;
    toggleOptional(key, !state.toggles[key]);
  }
});

document.getElementById("launchBtn").addEventListener("click", saveAndLaunch);

document.querySelectorAll('input[name="llm-mode"]').forEach((input) => {
  input.addEventListener("change", (event) => {
    state.llmMode = event.target.value;
    showLLMMode();
  });
});

showLLMMode();
toggleOptional("brave", false);
toggleOptional("github", false);
toggleOptional("searxng", false);
toggleOptional("obsidian", false);
toggleOptional("hub", false);
toggleOptional("browser", false);
toggleOptional("telegram", false);
toggleOptional("whatsapp", false);
toggleOptional("discord", false);
setStep(0);
fetchConfig();
