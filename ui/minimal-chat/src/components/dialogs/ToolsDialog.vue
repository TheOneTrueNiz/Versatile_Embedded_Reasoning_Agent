<template>
    <div class="tools-dialog" :class="{ collapsed: collapsed }">
        <div class="tools-header">
            <div class="title">
                <Wrench size="18" />
                <span>Tools</span>
            </div>
            <div class="header-actions">
                <button class="icon-button" @click="emit('toggle-collapse')" :title="collapsed ? 'Expand tools' : 'Collapse tools'">
                    <ChevronRight v-if="collapsed" size="18" />
                    <ChevronLeft v-else size="18" />
                </button>
                <button class="icon-button" @click="emit('close')" title="Close tools">
                    <X size="18" />
                </button>
            </div>
        </div>

        <div v-if="collapsed" class="collapsed-label">
            <span>Tools</span>
            <span class="collapsed-meta">{{ collapsedMcpSummary }}</span>
            <span class="collapsed-meta">{{ collapsedVoiceSummary }}</span>
        </div>

        <div v-if="!collapsed" class="tools-tab-bar">
            <button class="tab-button" :class="{ active: activeTab === 'tools' }" @click="activeTab = 'tools'">
                <Wrench size="16" />
                <span>Tools</span>
            </button>
            <button class="tab-button" :class="{ active: activeTab === 'diagnostics' }" @click="activeTab = 'diagnostics'">
                <Activity size="16" />
                <span>Diagnostics</span>
            </button>
            <button class="tab-button" :class="{ active: activeTab === 'swarm' }" @click="activeTab = 'swarm'">
                <Users size="16" />
                <span>Swarm/Quorum</span>
            </button>
        </div>

        <template v-if="!collapsed && activeTab === 'tools'">
            <div class="tools-actions">
                <button class="primary-btn" @click="refreshAll">
                    <RefreshCcw size="16" />
                    <span>Refresh</span>
                </button>
                <button class="secondary-btn" @click="startStoppedTools">
                    <Play size="16" />
                    <span>Start Stopped</span>
                </button>
                <button class="secondary-btn" @click="restartUnhealthyTools">
                    <RefreshCcw size="16" />
                    <span>Restart Unhealthy</span>
                </button>
                <button class="primary-btn" :disabled="isVerifying" @click="verifyTools">
                    <ShieldCheck size="16" />
                    <span>{{ isVerifying ? 'Verifying...' : 'Verify Tools' }}</span>
                </button>
            </div>

            <div v-if="verifySummary" class="verify-card accordion-card">
                <div class="accordion-header" @click="toggleSection('verify')">
                    <div class="accordion-title">
                        <component :is="expandedSections.verify ? ChevronUp : ChevronDown" size="16" />
                        <span>Verification Summary</span>
                    </div>
                    <span class="accordion-summary">{{ verifySummary.ok }} ok · {{ verifySummary.skipped }} skip · {{ verifySummary.failed }} fail</span>
                </div>
                <div v-show="expandedSections.verify" class="accordion-content">
                    <ul class="verify-list">
                        <li v-for="result in verifyResults" :key="result.server" :class="result.status">
                            <span class="verify-name">{{ result.server }}</span>
                            <span class="verify-status">{{ result.status }}</span>
                            <span v-if="result.detail" class="verify-detail">{{ result.detail }}</span>
                        </li>
                    </ul>
                </div>
            </div>

            <div v-if="toolStatus" class="tool-status-card accordion-card">
                <div class="accordion-header" @click="toggleSection('mcp')">
                    <div class="accordion-title">
                        <component :is="expandedSections.mcp ? ChevronUp : ChevronDown" size="16" />
                        <span>MCP Status</span>
                    </div>
                    <span class="accordion-summary">{{ mcpSummary }}</span>
                </div>
                <div v-show="expandedSections.mcp" class="accordion-content">
                    <ul>
                        <li v-for="(server, name) in toolStatus.mcp.servers" :key="name">
                            <span class="tool-name">{{ name }}</span>
                            <span :class="['tool-state', server.running ? 'ok' : 'warn']">
                                {{ server.running ? 'running' : 'stopped' }}
                            </span>
                            <span v-if="server.health" :class="['tool-badge', server.health === 'healthy' ? 'ok' : 'warn']">
                                {{ server.health }}
                            </span>
                            <span
                                v-if="server.missing_env && server.missing_env.length"
                                class="tool-badge danger"
                                :title="`missing: ${server.missing_env.join(', ')}`"
                            >
                                missing {{ server.missing_env.length }}
                            </span>
                        </li>
                    </ul>
                </div>
            </div>

            <div class="browser-status-card accordion-card">
                <div class="accordion-header" @click="toggleSection('browser')">
                    <div class="accordion-title">
                        <component :is="expandedSections.browser ? ChevronUp : ChevronDown" size="16" />
                        <span>Browser Automation</span>
                    </div>
                    <span :class="['status-pill', browserStatusClass]">{{ browserStatusLabel }}</span>
                </div>
                <div v-show="expandedSections.browser" class="accordion-content">
                    <div v-if="!browserStatus" class="payload-empty">
                        Browser status not loaded yet.
                    </div>
                    <div v-else class="browser-meta">
                        <div><strong>Enabled:</strong> {{ browserStatus.enabled ? 'yes' : 'no' }}</div>
                        <div><strong>Available:</strong> {{ browserStatus.available ? 'yes' : 'no' }}</div>
                        <div><strong>Launched:</strong> {{ browserStatus.launched ? 'yes' : 'no' }}</div>
                        <div v-if="browserStatus.error" class="browser-error">
                            <strong>Error:</strong> {{ browserStatus.error }}
                        </div>
                    </div>
                    <div class="browser-actions">
                        <button
                            class="secondary-btn"
                            :disabled="browserLaunching || !browserStatus?.enabled || !browserStatus?.available || browserStatus?.launched"
                            @click="launchBrowser"
                        >
                            <span>{{ browserLaunching ? 'Launching...' : 'Launch Browser' }}</span>
                        </button>
                        <button
                            class="secondary-btn"
                            :disabled="browserClosing || !browserStatus?.available || !browserStatus?.launched"
                            @click="closeBrowser"
                        >
                            <span>{{ browserClosing ? 'Closing...' : 'Close Browser' }}</span>
                        </button>
                    </div>
                    <div v-if="browserStatus && !browserStatus.enabled" class="browser-note">
                        Enable with VERA_BROWSER=1, install Playwright, then restart VERA.
                    </div>
                </div>
            </div>

            <div class="tool-payload-card accordion-card">
                <div class="accordion-header" @click="toggleSection('payload')">
                    <div class="accordion-title">
                        <component :is="expandedSections.payload ? ChevronUp : ChevronDown" size="16" />
                        <span>Last Tool Payload</span>
                    </div>
                    <span class="accordion-summary">{{ payloadToolCount }} tools</span>
                </div>
                <div v-show="expandedSections.payload" class="accordion-content">
                    <div v-if="!lastPayload" class="payload-empty">
                        No tool payload recorded yet.
                    </div>
                    <div v-else class="payload-meta">
                        <div><strong>Tool routing:</strong> {{ lastPayload.tool_mode || '—' }}</div>
                        <div><strong>Quorum state:</strong> {{ quorumModeLabel }}</div>
                        <div><strong>Tool max:</strong> {{ lastPayload.tool_max ?? '—' }}</div>
                        <div><strong>Router:</strong> {{ lastPayload.router_enabled ? 'on' : 'off' }}</div>
                        <div><strong>Router max:</strong> {{ lastPayload.router_max ?? '—' }}</div>
                        <div><strong>Forced tool:</strong> {{ lastPayload.forced_tool || '—' }}</div>
                        <div><strong>Tool choice:</strong> {{ lastPayload.tool_choice || 'auto' }}</div>
                        <div><strong>Tools used:</strong> {{ payloadToolsUsed }}</div>
                        <div><strong>Servers:</strong> {{ payloadServers }}</div>
                        <div><strong>Native/MCP:</strong> {{ lastPayload.native_included ?? 0 }}/{{ lastPayload.mcp_included ?? 0 }}</div>
                    </div>
                    <details v-if="lastPayload">
                        <summary>Tools ({{ payloadToolCount }})</summary>
                        <div class="tool-list">{{ payloadToolNames }}</div>
                        <div v-if="lastPayload.tool_names_truncated" class="payload-note">
                            Showing {{ lastPayload.tool_names?.length || 0 }} of {{ lastPayload.tool_names_total }} tools.
                        </div>
                    </details>
                    <details v-if="lastPayload?.tools">
                        <summary>Raw payload</summary>
                        <pre class="payload-json">{{ formatJson(lastPayload.tools) }}</pre>
                        <div v-if="lastPayload.tools_truncated" class="payload-note">
                            Raw payload trimmed to {{ lastPayload.tools?.length || 0 }} of {{ lastPayload.tools_total }} entries.
                        </div>
                    </details>
                </div>
            </div>

            <div v-if="toolInventory" class="tool-inventory-card accordion-card">
                <div class="accordion-header" @click="toggleSection('inventory')">
                    <div class="accordion-title">
                        <component :is="expandedSections.inventory ? ChevronUp : ChevronDown" size="16" />
                        <span>Tool Inventory</span>
                    </div>
                    <span class="accordion-summary">{{ inventoryCount }} tools</span>
                </div>
                <div v-show="expandedSections.inventory" class="accordion-content tool-inventory-list">
                    <div v-if="callMeTipVisible" class="inventory-tip">
                        <strong>Call-me tip:</strong> include <code>recipient_name</code> when initiating calls (e.g., “Call Mike”).
                    </div>
                    <div v-for="section in inventorySections" :key="section.label" class="inventory-section">
                        <div class="inventory-section-header">
                            <span>{{ section.label }}</span>
                            <span>{{ section.count }} tools</span>
                        </div>
                        <details v-for="item in section.items" :key="item.name">
                            <summary>{{ item.name }} ({{ item.tools.length }})</summary>
                            <div class="tool-list">
                                {{ item.tools.length ? item.tools.join(', ') : 'No tools reported.' }}
                            </div>
                        </details>
                    </div>
                </div>
            </div>
        </template>

        <template v-if="!collapsed && activeTab === 'diagnostics'">
            <div class="tools-status-card">
                <div class="status-row">
                    <span>WebSocket</span>
                    <span :class="['status-pill', wsStatusClass]">{{ wsStatusLabel }}</span>
                </div>
                <div class="status-row">
                    <span>Last update</span>
                    <span>{{ lastUpdate || '—' }}</span>
                </div>
            </div>

            <div class="tool-status-card oauth-health-card accordion-card">
                <div class="accordion-header" @click="toggleSection('oauth')">
                    <div class="accordion-title">
                        <component :is="expandedSections.oauth ? ChevronUp : ChevronDown" size="16" />
                        <span>OAuth</span>
                    </div>
                    <span :class="['status-pill', googleAuthClass]">{{ googleAuthLabel }}</span>
                </div>
                <div v-show="expandedSections.oauth" class="accordion-content">
                    <div v-if="!googleAuthStatus" class="payload-empty">
                        OAuth status not loaded yet.
                    </div>
                    <div v-else class="oauth-meta">
                        <div><strong>User:</strong> {{ googleAuthStatus.user_email || '—' }}</div>
                        <div v-if="googleAuthReasonLabel"><strong>Reason:</strong> {{ googleAuthReasonLabel }}</div>
                        <div v-if="googleAuthStatus.credentials_file">
                            <strong>Credentials:</strong>
                            <span :title="googleAuthStatus.credentials_file">{{ googleAuthStatus.credentials_file }}</span>
                        </div>
                        <div v-else-if="googleAuthStatus.credentials_dir">
                            <strong>Credentials dir:</strong>
                            <span :title="googleAuthStatus.credentials_dir">{{ googleAuthStatus.credentials_dir }}</span>
                        </div>
                        <div v-if="googleAuthStatus.missing_env && googleAuthStatus.missing_env.length">
                            <strong>Missing env:</strong> {{ googleAuthStatus.missing_env.join(', ') }}
                        </div>
                        <div v-if="googleAuthStatus.oauth_redirect_uri">
                            <strong>Redirect:</strong> {{ googleAuthStatus.oauth_redirect_uri }}
                        </div>
                        <div><strong>Last check:</strong> {{ googleAuthCheckedAt }}</div>
                    </div>
                </div>
            </div>

            <div class="voice-status-card accordion-card">
                <div class="accordion-header" @click="toggleSection('voice')">
                    <div class="accordion-title">
                        <component :is="expandedSections.voice ? ChevronUp : ChevronDown" size="16" />
                        <span>Voice</span>
                    </div>
                    <span :class="['status-pill', voiceStatusClass]">{{ voiceStatusLabel }}</span>
                </div>
                <div v-show="expandedSections.voice" class="accordion-content">
                    <div v-if="!voiceStatus" class="payload-empty">
                        Voice status not loaded yet.
                    </div>
                    <div v-else class="voice-meta">
                        <div><strong>Enabled:</strong> {{ voiceStatus.enabled ? 'yes' : 'no' }}</div>
                        <div><strong>Voice:</strong> {{ voiceStatus.selected_voice || '—' }}</div>
                        <div><strong>Session:</strong> {{ voiceStatus.session_active ? 'active' : 'idle' }}</div>
                        <div><strong>Backend:</strong> {{ voiceStatus.backend || '—' }}</div>
                        <div><strong>WebSockets:</strong> {{ voiceStatus.websockets_available ? 'ok' : 'missing' }}</div>
                        <div><strong>API key:</strong> {{ voiceStatus.api_key_present ? 'set' : 'missing' }}</div>
                        <div v-if="voiceStatus.message"><strong>Note:</strong> {{ voiceStatus.message }}</div>
                        <div v-if="voiceStatus.backend_error" class="voice-error">
                            <strong>Error:</strong> {{ voiceStatus.backend_error }}
                        </div>
                    </div>
                    <button class="secondary-btn" :disabled="!voiceStatus?.enabled || voiceTesting" @click="runVoiceTest">
                        <Mic size="16" />
                        <span>{{ voiceTesting ? 'Testing...' : 'Test Voice' }}</span>
                    </button>
                    <div v-if="voiceTestResult" class="voice-test-result">{{ voiceTestResult }}</div>
                </div>
            </div>

            <div class="memory-stats-card accordion-card">
                <div class="accordion-header" @click="toggleSection('memory')">
                    <div class="accordion-title">
                        <component :is="expandedSections.memory ? ChevronUp : ChevronDown" size="16" />
                        <span>Memory</span>
                    </div>
                    <span class="accordion-summary">{{ memorySummary }}</span>
                </div>
                <div v-show="expandedSections.memory" class="accordion-content">
                    <div v-if="!memoryStats" class="payload-empty">
                        Memory stats not loaded yet.
                    </div>
                    <div v-else class="memory-meta">
                        <div>
                            <strong>Tiers:</strong>
                            S {{ memoryStats.tiers.session }} ·
                            W {{ memoryStats.tiers.working }} ·
                            L {{ memoryStats.tiers.long_term_videos }}
                        </div>
                        <div>
                            <strong>Fast:</strong>
                            {{ formatPercent(memoryStats.fast_network.retention_rate) }} retained ·
                            buffer {{ memoryStats.fast_network.buffer_size }}/{{ memoryStats.fast_network.buffer_capacity }}
                        </div>
                        <div>
                            <strong>Slow:</strong>
                            {{ formatPercent(memoryStats.slow_network.retention_rate) }} retained ·
                            {{ formatPercent(memoryStats.slow_network.archival_rate) }} archived ·
                            long-term {{ memoryStats.slow_network.long_term_size }}
                        </div>
                        <div>
                            <strong>RAG cache:</strong>
                            {{ formatPercent(memoryStats.rag_cache.hit_rate) }} hit ·
                            {{ formatPercent(memoryStats.rag_cache.utilization) }} util
                        </div>
                        <div>
                            <strong>Retrievals:</strong>
                            HSA {{ memoryStats.retrieval.hsa_retrievals }} ·
                            Graph {{ memoryStats.retrieval.graph_retrievals }} ·
                            Global {{ memoryStats.retrieval.global_queries }}
                        </div>
                    </div>
                </div>
            </div>

            <div class="self-improvement-card accordion-card">
                <div class="accordion-header" @click="toggleSection('selfImprove')">
                    <div class="accordion-title">
                        <component :is="expandedSections.selfImprove ? ChevronUp : ChevronDown" size="16" />
                        <span>Self-Improvement Ops</span>
                    </div>
                    <span :class="['status-pill', selfImproveStatusClass]">{{ selfImproveStatusLabel }}</span>
                </div>
                <div v-show="expandedSections.selfImprove" class="accordion-content">
                    <div v-if="!selfImproveStatus" class="payload-empty">
                        Self-improvement status not loaded yet.
                    </div>
                    <div v-else class="self-improve-meta">
                        <div><strong>Running:</strong> {{ selfImproveStatus.running ? 'yes' : 'no' }}</div>
                        <div><strong>Action:</strong> {{ selfImproveStatus.action || '—' }}</div>
                        <div><strong>Started:</strong> {{ formatTimestamp(selfImproveStatus.started_at) }}</div>
                        <div><strong>Finished:</strong> {{ formatTimestamp(selfImproveStatus.finished_at) }}</div>
                        <div v-if="selfImproveStatus.last_error" class="self-improve-error">
                            <strong>Error:</strong> {{ selfImproveStatus.last_error }}
                        </div>
                    </div>
                    <div class="self-improve-controls">
                        <div class="self-improve-row">
                            <button class="primary-btn" :disabled="selfImproveLocked" @click="runRedTeam">
                                Run Red-Team
                            </button>
                            <SliderCheckbox inputId="self-redteam-llm" labelText="Use LLM" v-model="selfImproveUseLlm" />
                        </div>
                        <div class="self-improve-row">
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="runArchitect">
                                Run Architect
                            </button>
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="runMemvidExport">
                                Export Memvid
                            </button>
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="runExportSpecialist">
                                Export Specialist
                            </button>
                        </div>
                        <div class="self-improve-row">
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="runRegression">
                                Run Regression
                            </button>
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="trainRewardModel">
                                Train Reward Model
                            </button>
                            <div class="quorum-select">
                                <label for="self-regression-limit">Limit</label>
                                <input id="self-regression-limit" v-model.number="selfImproveRegressionLimit" type="number" min="0" step="1" />
                            </div>
                            <div class="quorum-select">
                                <label for="self-memvid-limit">Memvid limit</label>
                                <input id="self-memvid-limit" v-model.number="selfImproveMemvidLimit" type="number" min="0" step="1" />
                            </div>
                        </div>
                        <div class="self-improve-row">
                            <div class="quorum-select full-width">
                                <label for="self-simulate-patch">Simulate Patch (JSON array)</label>
                                <textarea
                                    id="self-simulate-patch"
                                    v-model="selfImprovePatchText"
                                    rows="3"
                                    placeholder='[{"op":"replace","path":"/agent_profile/name","value":"Architect"}]'
                                ></textarea>
                            </div>
                            <button class="secondary-btn" :disabled="selfImproveLocked" @click="simulatePatch">
                                Simulate Patch
                            </button>
                        </div>
                        <div v-if="selfImprovePatchResult" class="self-improve-patch-result">
                            <div><strong>Patch valid:</strong> {{ selfImprovePatchResult.valid ? 'yes' : 'no' }}</div>
                            <div v-if="selfImprovePatchResult.errors?.length">
                                <strong>Errors:</strong> {{ selfImprovePatchResult.errors.join('; ') }}
                            </div>
                        </div>
                        <div v-if="selfImproveError" class="self-improve-error">{{ selfImproveError }}</div>
                        <div class="self-improve-note">
                            Budget caps apply to LLM actions. Logs refresh every 5 seconds while this panel is open.
                        </div>
                    </div>
                    <div class="self-improve-log">
                        <div class="self-improve-log-header">
                            <span>Live Log</span>
                            <button class="icon-button small" @click="refreshSelfImproveLogs" :title="'Refresh log'">
                                <RefreshCcw size="14" />
                            </button>
                        </div>
                        <pre class="self-improve-log-output">{{ selfImproveLogs || 'No log output yet.' }}</pre>
                    </div>
                </div>
            </div>

            <div class="self-budget-card accordion-card">
                <div class="accordion-header" @click="toggleSection('selfBudget')">
                    <div class="accordion-title">
                        <component :is="expandedSections.selfBudget ? ChevronUp : ChevronDown" size="16" />
                        <span>Self-Improvement Budget</span>
                    </div>
                    <span :class="['status-pill', selfBudgetStatusClass]">{{ selfBudgetStatusLabel }}</span>
                </div>
                <div v-show="expandedSections.selfBudget" class="accordion-content">
                    <div v-if="!selfBudget" class="payload-empty">
                        Budget status not loaded yet.
                    </div>
                    <div v-else class="budget-meta">
                        <div><strong>Spent:</strong> {{ selfBudgetSpentLabel }}</div>
                        <div><strong>Tokens:</strong> {{ selfBudgetTokenLabel }}</div>
                        <div><strong>Calls:</strong> {{ selfBudgetCallLabel }}</div>
                        <div><strong>Last update:</strong> {{ formatTimestamp(selfBudget.state?.updated_at) }}</div>
                        <div><strong>Config source:</strong> {{ selfBudget.config_source || 'env' }}</div>
                    </div>
                    <div class="budget-form">
                        <SliderCheckbox inputId="self-budget-enabled" labelText="Enabled" v-model="selfBudgetForm.enabled" />
                        <div class="budget-grid">
                            <div class="quorum-select">
                                <label for="self-budget-usd">Daily USD cap</label>
                                <input id="self-budget-usd" v-model.number="selfBudgetForm.daily_budget_usd" type="number" step="0.1" min="-1" />
                            </div>
                            <div class="quorum-select">
                                <label for="self-budget-tokens">Daily token cap</label>
                                <input id="self-budget-tokens" v-model.number="selfBudgetForm.daily_token_budget" type="number" step="100" min="-1" />
                            </div>
                            <div class="quorum-select">
                                <label for="self-budget-calls">Daily call cap</label>
                                <input id="self-budget-calls" v-model.number="selfBudgetForm.daily_call_budget" type="number" step="1" min="-1" />
                            </div>
                            <div class="quorum-select">
                                <label for="self-budget-max-tokens">Max tokens per call</label>
                                <input id="self-budget-max-tokens" v-model.number="selfBudgetForm.max_tokens_per_call" type="number" step="50" min="-1" />
                            </div>
                        </div>
                        <div class="budget-note">Use -1 for unlimited caps.</div>
                        <div class="budget-actions">
                            <button class="primary-btn" :disabled="!selfBudgetDirty || selfBudgetSaving" @click="saveSelfBudget">
                                {{ selfBudgetSaving ? 'Saving...' : 'Apply Budget' }}
                            </button>
                            <span v-if="selfBudgetError" class="budget-error">{{ selfBudgetError }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </template>

        <template v-if="!collapsed && activeTab === 'swarm'">
            <div class="quorum-panel">
                <div class="quorum-hero-card">
                    <div class="tool-status-header">
                        <span>Swarm & Quorum</span>
                        <span :class="['status-pill', quorumStatusClass]">{{ quorumStatusLabel }}</span>
                    </div>
                    <div v-if="!quorumStatus" class="payload-empty">
                        Swarm/quorum status not loaded yet.
                    </div>
                    <div v-else class="quorum-hero">
                        <SwarmIndicator
                            class="quorum-indicator"
                            :status="swarmIndicatorStatus"
                            :intensity="swarmIndicatorIntensity"
                            :active="swarmIndicatorActive"
                            :status-class="quorumStatusClass"
                            :size="72"
                            :sound-enabled="swarmSoundEnabled"
                        />
                        <div class="quorum-hero-meta">
                            <div><strong>Mode:</strong> {{ quorumModeLabel }}</div>
                            <div><strong>Trigger:</strong> {{ quorumTriggerLabel }}</div>
                            <div><strong>Quorum:</strong> {{ quorumState.quorum || '—' }}</div>
                            <div><strong>Agents:</strong> {{ quorumState.agents?.length || 0 }}</div>
                            <div><strong>Decision:</strong> {{ quorumState.decision || '—' }}</div>
                            <div><strong>Consensus:</strong> {{ formatConsensus(quorumState.consensus) }}</div>
                            <div><strong>Started:</strong> {{ formatTimestamp(quorumState.started_at) }}</div>
                            <div><strong>Finished:</strong> {{ formatTimestamp(quorumState.finished_at) }}</div>
                            <div><strong>Latency:</strong> {{ quorumState.latency_ms ? `${quorumState.latency_ms} ms` : '—' }}</div>
                            <div v-if="quorumState.agents?.length" class="quorum-agent-list">
                                <span v-for="agent in quorumState.agents" :key="agent" class="quorum-agent-pill">{{ formatAgentName(agent) }}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="quorum-controls-card">
                    <div class="tool-status-header">
                        <span>Controls</span>
                        <span>{{ quorumUsageLabel }}</span>
                    </div>
                    <div class="quorum-controls">
                        <div class="quorum-toggle">
                            <SliderCheckbox inputId="auto-quorum" labelText="Auto Quorum" v-model="quorumAutoEnabled" />
                            <div class="quorum-note">Allow Vera to consult the quorum during responses.</div>
                        </div>
                        <div class="quorum-toggle">
                            <SliderCheckbox inputId="auto-swarm" labelText="Auto Swarm" v-model="swarmAutoEnabled" />
                            <div class="quorum-note">Allow Vera to coordinate a swarm for complex actions.</div>
                        </div>
                        <div class="quorum-manual">
                            <div class="quorum-manual-header">
                                <span>Manual Run</span>
                                <span v-if="pendingQuorumMode" class="quorum-queued-pill">Queued: {{ pendingModeLabel }}</span>
                            </div>
                            <div class="quorum-select">
                                <label for="quorum-select">Quorum</label>
                                <select id="quorum-select" v-model="selectedQuorumName" :disabled="!availableQuorums.length">
                                    <option value="">Auto (selector)</option>
                                    <option v-for="quorum in availableQuorums" :key="quorum.name" :value="quorum.name" :title="quorum.purpose">
                                        {{ quorum.is_swarm ? `${quorum.name} (Swarm)` : quorum.name }}
                                    </option>
                                </select>
                            </div>
                            <div v-if="selectedQuorumProfile" class="quorum-profile">
                                <div class="quorum-profile-title">{{ selectedQuorumProfile.name }}</div>
                                <div class="quorum-profile-meta">
                                    <span>Mode: {{ selectedQuorumProfile.is_swarm ? 'Swarm' : 'Quorum' }}</span>
                                    <span>Consensus: {{ formatConsensus(selectedQuorumProfile.consensus) }}</span>
                                    <span>Lead: {{ selectedQuorumProfile.lead_agent || '—' }}</span>
                                    <span>Veto: {{ selectedQuorumProfile.veto_agent || '—' }}</span>
                                </div>
                                <div class="quorum-profile-purpose">
                                    Purpose: {{ selectedQuorumProfile.purpose || '—' }}
                                </div>
                                <div class="quorum-profile-agents">
                                    Agents: {{ selectedQuorumProfile.agents?.map(formatAgentName).join(', ') || '—' }}
                                </div>
                            </div>
                            <div class="quorum-manual-actions">
                                <button class="primary-btn" :class="{ active: pendingQuorumMode === 'quorum' }" @click="queueQuorum">
                                    Queue Quorum
                                </button>
                                <button class="secondary-btn" :class="{ active: pendingQuorumMode === 'swarm' }" @click="queueSwarm">
                                    Queue Swarm
                                </button>
                                <button
                                    v-if="pendingQuorumMode"
                                    class="icon-button small"
                                    title="Clear queued mode"
                                    @click="clearQueuedMode"
                                >
                                    <X size="14" />
                                </button>
                            </div>
                            <div class="quorum-note">Queued runs apply to your next message only.</div>
                            <div class="quorum-custom">
                                <div class="quorum-custom-header">Custom Quorum</div>
                                <div class="quorum-select">
                                    <label for="custom-quorum-select">Saved Presets</label>
                                    <select id="custom-quorum-select" v-model="customQuorumPreset">
                                        <option value="">New custom quorum</option>
                                        <option v-for="quorum in customQuorums" :key="quorum.name" :value="quorum.name">
                                            {{ quorum.name }}
                                        </option>
                                    </select>
                                </div>
                                <div class="quorum-select">
                                    <label for="custom-quorum-name">Name</label>
                                    <input id="custom-quorum-name" v-model="customQuorumName" type="text" placeholder="e.g., Architect" />
                                </div>
                                <div class="quorum-select">
                                    <label for="custom-quorum-purpose">Purpose</label>
                                    <input id="custom-quorum-purpose" v-model="customQuorumPurpose" type="text" placeholder="Short intent statement" />
                                </div>
                                <div class="quorum-select">
                                    <label for="custom-quorum-description">Description</label>
                                    <textarea id="custom-quorum-description" v-model="customQuorumDescription" rows="2" placeholder="Optional detail"></textarea>
                                </div>
                                <div class="quorum-select">
                                    <label for="custom-quorum-consensus">Consensus</label>
                                    <select id="custom-quorum-consensus" v-model="customQuorumConsensus">
                                        <option v-for="option in consensusOptions" :key="option.value" :value="option.value">
                                            {{ option.label }}
                                        </option>
                                    </select>
                                </div>
                                <div class="quorum-toggle">
                                    <SliderCheckbox inputId="custom-swarm-mode" labelText="Treat as Swarm" v-model="customQuorumIsSwarm" />
                                    <div class="quorum-note">Uses swarm gating, limits, and cost warnings.</div>
                                </div>
                                <div class="quorum-custom-agents">
                                    <span class="quorum-custom-label">Agents</span>
                                    <div class="agent-grid">
                                        <button
                                            v-for="agent in agentOptions"
                                            :key="agent.name"
                                            type="button"
                                            class="agent-chip"
                                            :class="{ active: customQuorumAgents.includes(agent.name) }"
                                            @click="toggleCustomAgent(agent.name)"
                                        >
                                            {{ agent.label }}
                                        </button>
                                    </div>
                                </div>
                                <div class="quorum-custom-meta">
                                    <div class="quorum-select">
                                        <label for="custom-quorum-lead">Lead</label>
                                        <select id="custom-quorum-lead" v-model="customQuorumLead">
                                            <option value="">None</option>
                                            <option v-for="agent in customQuorumAgents" :key="agent" :value="agent">
                                                {{ agent }}
                                            </option>
                                        </select>
                                    </div>
                                    <div class="quorum-select">
                                        <label for="custom-quorum-veto">Veto</label>
                                        <select id="custom-quorum-veto" v-model="customQuorumVeto">
                                            <option value="">None</option>
                                            <option v-for="agent in customQuorumAgents" :key="agent" :value="agent">
                                                {{ agent }}
                                            </option>
                                        </select>
                                    </div>
                                </div>
                                <div class="quorum-manual-actions">
                                    <button class="primary-btn" :disabled="customQuorumSaving" @click="saveCustomQuorum">
                                        Save Custom
                                    </button>
                                    <button class="secondary-btn" :disabled="!customQuorumPreset" @click="deleteCustomQuorumPreset">
                                        Delete Custom
                                    </button>
                                    <button class="icon-button small" title="Clear custom form" @click="clearCustomForm">
                                        <X size="14" />
                                    </button>
                                </div>
                                <div class="quorum-note">Large quorums increase token usage and latency.</div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="quorum-summary-card">
                    <div class="tool-status-header">
                        <span>Latest Summary</span>
                        <span>{{ formatTimestamp(quorumState.finished_at) }}</span>
                    </div>
                    <div class="quorum-summary">{{ quorumSummaryText }}</div>
                </div>
            </div>
        </template>
    </div>

    <ConfirmationDialog
        v-model:visible="showQueueWarning"
        title="High Cost Operation"
        :message="queueWarningMessage"
        confirm-label="Continue"
        cancel-label="Cancel"
        :is-warning="true"
        @confirm="confirmQueueAction"
    />
    <ConfirmationDialog
        v-model:visible="showCustomQuorumWarning"
        title="Large Quorum Warning"
        :message="customQuorumWarningMessage"
        confirm-label="Continue"
        cancel-label="Cancel"
        :is-warning="true"
        @confirm="confirmLargeCustomQuorum"
    />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { Activity, Wrench, X, RefreshCcw, Play, ShieldCheck, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Mic, Users } from 'lucide-vue-next';
import SliderCheckbox from '@/components/controls/SliderCheckbox.vue';
import SwarmIndicator from '@/components/controls/SwarmIndicator.vue';
import ConfirmationDialog from '@/components/controls/ConfirmationDialog.vue';
import { showToast } from '@/libs/utils/general-utils';
import {
    pendingQuorumMode,
    pendingQuorumName,
    quorumAutoEnabled,
    swarmAutoEnabled,
    quorumUiMode,
    quorumUiActive,
    isLoading,
    voiceAgentVoice,
    a11ySoundEffects,
    a11yAutoPlayMedia
} from '@/libs/state-management/state';
import { playAudio } from '@/libs/utils/audio-utils';

const props = defineProps({
    collapsed: {
        type: Boolean,
        default: false
    },
    requestedTab: {
        type: String,
        default: 'tools'
    },
    requestedSections: {
        type: Array,
        default: () => []
    }
});

const emit = defineEmits(['close', 'toggle-collapse', 'tab-change']);

const collapsed = computed(() => props.collapsed);

const toolStatus = ref(null);
const toolInventory = ref(null);
const googleAuthStatus = ref(null);
const verifySummary = ref(null);
const verifyResults = ref([]);
const isVerifying = ref(false);
const lastPayload = ref(null);
const voiceStatus = ref(null);
const voiceTesting = ref(false);
const voiceTestResult = ref('');
const memoryStats = ref(null);
const browserStatus = ref(null);
const browserLaunching = ref(false);
const browserClosing = ref(false);
const selfImproveStatus = ref(null);
const selfImproveLogs = ref('');
const selfImproveBusy = ref(false);
const selfImproveError = ref('');
const selfImproveUseLlm = ref(true);
const selfImproveRegressionLimit = ref(0);
const selfImproveMemvidLimit = ref(0);
const selfImprovePatchText = ref('');
const selfImprovePatchResult = ref(null);
const selfImproveLogTimer = ref(null);
const quorumStatus = ref(null);
const quorumCatalog = ref([]);
const selfBudget = ref(null);
const selfBudgetSaving = ref(false);
const selfBudgetDirty = ref(false);
const selfBudgetError = ref('');
const selfBudgetReady = ref(false);
const selfBudgetForm = reactive({
    enabled: true,
    daily_budget_usd: 1.0,
    daily_token_budget: 12000,
    daily_call_budget: 6,
    max_tokens_per_call: 2000
});
const quorumSettingsReady = ref(false);
const activeTab = ref(props.requestedTab || 'tools');
const selectedQuorumName = ref('');
const customQuorumName = ref('');
const customQuorumPurpose = ref('');
const customQuorumDescription = ref('');
const customQuorumConsensus = ref('majority_vote');
const customQuorumAgents = ref([]);
const customQuorumLead = ref('');
const customQuorumVeto = ref('');
const customQuorumPreset = ref('');
const customQuorumIsSwarm = ref(false);
const customQuorumSaving = ref(false);
const showCustomQuorumWarning = ref(false);
const pendingCustomQuorumPayload = ref(null);
const customQuorumWarningMessage = ref('');
const showQueueWarning = ref(false);
const queueWarningMessage = ref('');
const pendingQueueAction = ref(null);

// Accordion state - track which sections are expanded
const expandedSections = ref({
    mcp: true,
    oauth: false,
    voice: false,
    memory: false,
    browser: false,
    selfImprove: false,
    selfBudget: false,
    payload: false,
    inventory: false,
    verify: false
});

watch(
    () => props.requestedTab,
    (value) => {
        if (value) {
            activeTab.value = value;
        }
    }
);

watch(
    () => props.requestedSections,
    (sections) => {
        if (!sections || !sections.length) return;
        sections.forEach((section) => {
            if (Object.prototype.hasOwnProperty.call(expandedSections.value, section)) {
                expandedSections.value[section] = true;
            }
        });
    }
);

watch(activeTab, (value) => {
    emit('tab-change', value);
});

const toggleSection = (section) => {
    expandedSections.value[section] = !expandedSections.value[section];
};

const toggleCustomAgent = (agentName) => {
    const current = new Set(customQuorumAgents.value);
    if (current.has(agentName)) {
        current.delete(agentName);
    } else {
        current.add(agentName);
    }
    customQuorumAgents.value = Array.from(current);
};

const clearCustomForm = () => {
    customQuorumName.value = '';
    customQuorumPurpose.value = '';
    customQuorumDescription.value = '';
    customQuorumConsensus.value = 'majority_vote';
    customQuorumAgents.value = [];
    customQuorumLead.value = '';
    customQuorumVeto.value = '';
    customQuorumPreset.value = '';
    customQuorumIsSwarm.value = false;
};

const applyCustomPreset = (preset) => {
    if (!preset) {
        clearCustomForm();
        return;
    }
    customQuorumName.value = preset.name || '';
    customQuorumPurpose.value = preset.purpose || '';
    customQuorumDescription.value = preset.description || '';
    customQuorumConsensus.value = preset.consensus || 'majority_vote';
    customQuorumAgents.value = Array.isArray(preset.agents) ? [...preset.agents] : [];
    customQuorumLead.value = preset.lead_agent || '';
    customQuorumVeto.value = preset.veto_agent || '';
    customQuorumIsSwarm.value = Boolean(preset.is_swarm);
};

const wsStatus = ref('disconnected');
const lastUpdate = ref('');
const wsRef = ref(null);
const wsTimer = ref(null);
const payloadRefreshInFlight = ref(false);
const quorumSyncInFlight = ref(false);

const agentOptions = [
    { name: 'Planner', label: 'Planner' },
    { name: 'Skeptic', label: 'Skeptic' },
    { name: 'Optimizer', label: 'Optimizer' },
    { name: 'Safety', label: 'Safety' },
    { name: 'SafetyLead', label: 'Safety Lead' },
    { name: 'QualityAssurance', label: 'Quality Assurance' },
    { name: 'Researcher', label: 'Researcher' },
    { name: 'Integrator', label: 'Integrator' },
    { name: 'MemoryCurator', label: 'Memory Curator' },
    { name: 'Architect', label: 'Architect' },
    { name: 'SystemArchitect', label: 'System Architect' },
    { name: 'Engineer', label: 'Engineer' },
    { name: 'Programmer', label: 'Programmer' },
    { name: 'Strategist', label: 'Strategist' },
    { name: 'Writer', label: 'Writer' },
    { name: 'Tutor', label: 'Tutor' },
    { name: 'Creative', label: 'Creative' },
    { name: 'Secretary', label: 'Secretary' },
    { name: 'Tasker', label: 'Tasker' },
    { name: 'EventPlanner', label: 'Event Planner' },
    { name: 'Scheduler', label: 'Scheduler' },
    { name: 'Chef', label: 'Chef' },
    { name: 'DealFinder', label: 'Deal Finder' },
];

const consensusOptions = [
    { value: 'majority_vote', label: 'Majority Vote' },
    { value: 'weighted_scoring', label: 'Weighted Scoring' },
    { value: 'synthesis', label: 'Synthesis' },
    { value: 'veto_authority', label: 'Veto Authority' },
];

const wsStatusLabel = computed(() => {
    if (wsStatus.value === 'connected') return 'connected';
    if (wsStatus.value === 'connecting') return 'connecting';
    if (wsStatus.value === 'error') return 'error';
    return 'offline';
});

const wsStatusClass = computed(() => {
    if (wsStatus.value === 'connected') return 'ok';
    if (wsStatus.value === 'connecting') return 'warn';
    return 'danger';
});

const voiceStatusLabel = computed(() => {
    if (!voiceStatus.value) return 'unknown';
    if (!voiceStatus.value.enabled) return 'disabled';
    if (voiceStatus.value.backend_ready && voiceStatus.value.websockets_available && voiceStatus.value.api_key_present) {
        return 'ready';
    }
    return 'degraded';
});

const quorumState = computed(() => quorumStatus.value?.state || {});
const quorumSettings = computed(() => quorumStatus.value?.settings || {});
const availableQuorums = computed(() => (quorumCatalog.value || []).filter((quorum) => !quorum.is_swarm || quorum.source === 'custom'));
const customQuorums = computed(() => (quorumCatalog.value || []).filter((quorum) => quorum.source === 'custom'));
const selectedQuorumProfile = computed(() =>
    availableQuorums.value.find((quorum) => quorum.name === selectedQuorumName.value)
);
const quorumStatusLabel = computed(() => quorumState.value.status || 'idle');
const quorumModeLabel = computed(() => {
    const rawMode = quorumState.value.mode || 'quorum';
    const baseMode = rawMode === 'swarm' ? 'Swarm' : 'Quorum';
    const quorumName = quorumState.value.quorum || '';
    if (quorumName && quorumName !== 'Swarm' && quorumName !== baseMode) {
        return `${baseMode} · ${quorumName}`;
    }
    return baseMode;
});
const quorumTriggerLabel = computed(() => quorumState.value.trigger || 'auto');
const quorumSummaryText = computed(() => quorumState.value.summary || quorumState.value.reason || 'No swarm/quorum activity recorded.');
const quorumUsageLabel = computed(() => {
    if (!quorumStatus.value?.settings) {
        return 'Usage: —';
    }
    const settings = quorumStatus.value.settings;
    const quorumCalls = settings.quorum_calls ?? 0;
    const quorumMax = settings.quorum_max_calls ?? '—';
    const swarmCalls = settings.swarm_calls ?? 0;
    const swarmMax = settings.swarm_max_calls ?? '—';
    return `Quorum ${quorumCalls}/${quorumMax} · Swarm ${swarmCalls}/${swarmMax}`;
});
const quorumStatusClass = computed(() => {
    const status = quorumStatusLabel.value;
    if (status === 'completed') return 'ok';
    if (status === 'running') return 'warn';
    if (status === 'blocked' || status === 'error') return 'danger';
    return 'neutral';
});
const immediateQuorumMode = computed(() => {
    if (!isLoading.value || !quorumUiActive.value) {
        return null;
    }
    return quorumUiMode.value;
});
const swarmIndicatorStatus = computed(() => {
    const status = quorumStatusLabel.value;
    if (status === 'blocked' || status === 'error') {
        return 'error';
    }
    if (status === 'running' || status === 'completed') {
        const mode = String(quorumState.value.mode || 'quorum').toLowerCase();
        return mode === 'swarm' ? 'swarm' : 'quorum';
    }
    if (immediateQuorumMode.value) {
        return immediateQuorumMode.value;
    }
    return 'idle';
});
const swarmIndicatorIntensity = computed(() => {
    if (swarmIndicatorStatus.value === 'swarm') {
        if (quorumStatusLabel.value === 'running' || immediateQuorumMode.value === 'swarm') {
            return 0.9;
        }
        return 0.6;
    }
    if (swarmIndicatorStatus.value === 'quorum') {
        if (quorumStatusLabel.value === 'running' || immediateQuorumMode.value === 'quorum') {
            return 0.7;
        }
        return 0.35;
    }
    return 0.15;
});
const swarmIndicatorActive = computed(() => quorumStatusLabel.value === 'running' || Boolean(immediateQuorumMode.value));
const swarmSoundEnabled = computed(() => a11ySoundEffects.value && a11yAutoPlayMedia.value);
const pendingModeLabel = computed(() => {
    if (pendingQuorumMode.value === 'swarm') {
        return pendingQuorumName.value ? `Swarm · ${pendingQuorumName.value}` : 'Swarm';
    }
    if (pendingQuorumMode.value === 'quorum') {
        return pendingQuorumName.value ? `Quorum · ${pendingQuorumName.value}` : 'Quorum';
    }
    return '';
});

const voiceStatusClass = computed(() => {
    if (!voiceStatus.value) return 'warn';
    if (!voiceStatus.value.enabled) return 'danger';
    if (voiceStatus.value.backend_ready && voiceStatus.value.websockets_available && voiceStatus.value.api_key_present) {
        return 'ok';
    }
    return 'warn';
});

const browserStatusLabel = computed(() => {
    if (!browserStatus.value) return 'unknown';
    if (!browserStatus.value.enabled) return 'disabled';
    if (browserStatus.value.error) return 'error';
    if (browserStatus.value.launched) return 'live';
    if (browserStatus.value.available) return 'ready';
    return 'unavailable';
});

const browserStatusClass = computed(() => {
    if (!browserStatus.value) return 'neutral';
    if (!browserStatus.value.enabled) return 'neutral';
    if (browserStatus.value.error) return 'danger';
    if (browserStatus.value.launched) return 'ok';
    if (browserStatus.value.available) return 'warn';
    return 'danger';
});

const selfImproveStatusLabel = computed(() => {
    if (!selfImproveStatus.value) return 'unknown';
    if (selfImproveStatus.value.running) return 'running';
    if (selfImproveStatus.value.last_error) return 'error';
    return 'idle';
});

const selfImproveStatusClass = computed(() => {
    if (!selfImproveStatus.value) return 'neutral';
    if (selfImproveStatus.value.running) return 'warn';
    if (selfImproveStatus.value.last_error) return 'danger';
    return 'ok';
});

const selfImproveLocked = computed(() => {
    return Boolean(selfImproveBusy.value || selfImproveStatus.value?.running);
});

const googleAuthLabel = computed(() => {
    const status = googleAuthStatus.value?.status;
    if (status === 'authorized') return 'Authorized';
    if (status === 'unauthorized') return 'Unauthorized';
    return 'Unknown';
});

const googleAuthReasonLabel = computed(() => {
    const reason = googleAuthStatus.value?.reason || '';
    if (!reason) return '';
    if (reason === 'missing_user_email') return 'missing user email';
    if (reason === 'missing_oauth_env') return 'missing OAuth env';
    if (reason === 'missing_oauth_client') return 'missing OAuth client';
    if (reason === 'missing_redirect_uri') return 'missing redirect uri';
    if (reason === 'missing_credentials_file') return 'missing credentials';
    return reason.replace(/_/g, ' ');
});

const googleAuthClass = computed(() => {
    const status = googleAuthStatus.value?.status;
    if (status === 'authorized') return 'ok';
    if (status === 'unauthorized') return 'warn';
    return 'neutral';
});

const googleAuthCheckedAt = computed(() => {
    const value = googleAuthStatus.value?.checked_at;
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
});

const inventoryCount = computed(() => {
    if (!toolInventory.value?.tools) return 0;
    return Object.values(toolInventory.value.tools).reduce((sum, tools) => sum + tools.length, 0);
});

const callMeTipVisible = computed(() => {
    const tools = toolInventory.value?.tools || {};
    const callMeTools = tools['call-me'] || [];
    return callMeTools.includes('initiate_call');
});

const inventorySections = computed(() => {
    const tools = toolInventory.value?.tools || {};
    const sections = [];
    const used = new Set();

    const addSection = (label, names) => {
        const items = [];
        let count = 0;
        names.forEach((name) => {
            if (Object.prototype.hasOwnProperty.call(tools, name)) {
                const entry = tools[name] || [];
                items.push({ name, tools: entry });
                count += entry.length;
                used.add(name);
            }
        });
        if (items.length) {
            sections.push({ label, items, count });
        }
    };

    addSection('Core', ['filesystem', 'memory', 'time', 'sequential-thinking']);
    addSection('Search', ['brave-search', 'searxng']);
    addSection('Knowledge', ['wikipedia', 'pdf-reader']);
    addSection('Notes', ['obsidian-vault']);
    addSection('Automation Hub', ['mcp-hub']);
    addSection('Workspace', ['google-workspace']);
    addSection('Dev', ['github']);
    addSection('Media', ['memvid', 'youtube-transcript']);

    const otherNames = Object.keys(tools)
        .filter((name) => !used.has(name))
        .sort();
    if (otherNames.length) {
        const items = otherNames.map((name) => ({ name, tools: tools[name] || [] }));
        const count = items.reduce((sum, item) => sum + item.tools.length, 0);
        sections.push({ label: 'Other', items, count });
    }

    return sections;
});

const mcpSummary = computed(() => {
    const servers = toolStatus.value?.mcp?.servers;
    if (!servers) {
        return '—';
    }
    const entries = Object.values(servers);
    const total = entries.length;
    const running = entries.filter((server) => server.running).length;
    const unhealthy = entries.filter(
        (server) => server.running && server.health && server.health !== 'healthy'
    ).length;
    const missing = entries.filter(
        (server) => server.missing_env && server.missing_env.length
    ).length;

    let summary = `${running}/${total} running`;
    if (unhealthy) {
        summary += ` · ${unhealthy} unhealthy`;
    }
    if (missing) {
        summary += ` · ${missing} missing`;
    }
    return summary;
});

const collapsedMcpSummary = computed(() => {
    const servers = toolStatus.value?.mcp?.servers;
    if (!servers) {
        return 'MCP: —';
    }
    const entries = Object.values(servers);
    const total = entries.length;
    const running = entries.filter((server) => server.running).length;
    const unhealthy = entries.filter(
        (server) => server.running && server.health && server.health !== 'healthy'
    ).length;
    const missing = entries.filter(
        (server) => server.missing_env && server.missing_env.length
    ).length;

    let summary = `MCP: ${running}/${total}`;
    if (unhealthy || missing) {
        summary += ' !';
    }
    return summary;
});

const collapsedVoiceSummary = computed(() => `Voice: ${voiceStatusLabel.value}`);

const payloadToolCount = computed(() => lastPayload.value?.tool_count || 0);

const payloadToolNames = computed(() => {
    const names = lastPayload.value?.tool_names;
    if (!names || !names.length) {
        return 'No tools recorded.';
    }
    const total = lastPayload.value?.tool_names_total || names.length;
    if (lastPayload.value?.tool_names_truncated && total > names.length) {
        return `${names.join(', ')} (+${total - names.length} more)`;
    }
    return names.join(', ');
});

const payloadServers = computed(() => {
    const servers = lastPayload.value?.selected_servers;
    if (!servers || !servers.length) {
        return '—';
    }
    return servers.join(', ');
});

const payloadToolsUsed = computed(() => {
    const tools = lastPayload.value?.last_tools_used;
    if (!tools) {
        return '—';
    }
    if (!tools.length) {
        return 'none';
    }
    return tools.join(', ');
});

const memorySummary = computed(() => {
    const tiers = memoryStats.value?.tiers;
    if (!tiers) {
        return '—';
    }
    return `S:${tiers.session} W:${tiers.working} L:${tiers.long_term_videos}`;
});

const selfBudgetStatusLabel = computed(() => {
    if (!selfBudget.value?.config) return 'unknown';
    return selfBudget.value.config.enabled ? 'enabled' : 'disabled';
});

const selfBudgetStatusClass = computed(() => {
    if (!selfBudget.value?.config) return 'neutral';
    return selfBudget.value.config.enabled ? 'ok' : 'neutral';
});

const formatBudgetLimit = (value, formatFn = (item) => item) => {
    if (value === null || typeof value === 'undefined') {
        return '—';
    }
    if (value < 0) {
        return 'unlimited';
    }
    return formatFn(value);
};

const selfBudgetSpentLabel = computed(() => {
    const config = selfBudget.value?.config;
    const state = selfBudget.value?.state;
    if (!config || !state) {
        return '—';
    }
    const spent = Number(state.spent_usd || 0);
    const cap = formatBudgetLimit(config.daily_budget_usd, (value) => `$${Number(value).toFixed(2)}`);
    return `$${spent.toFixed(2)} / ${cap}`;
});

const selfBudgetTokenLabel = computed(() => {
    const config = selfBudget.value?.config;
    const state = selfBudget.value?.state;
    if (!config || !state) {
        return '—';
    }
    const used = Number(state.tokens_used || 0);
    const cap = formatBudgetLimit(config.daily_token_budget, (value) => String(value));
    return `${used} / ${cap}`;
});

const selfBudgetCallLabel = computed(() => {
    const config = selfBudget.value?.config;
    const state = selfBudget.value?.state;
    if (!config || !state) {
        return '—';
    }
    const used = Number(state.calls || 0);
    const cap = formatBudgetLimit(config.daily_call_budget, (value) => String(value));
    return `${used} / ${cap}`;
});

const formatPercent = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) {
        return '—';
    }
    return `${(value * 100).toFixed(1)}%`;
};

const applySelfBudgetForm = (config) => {
    if (!config) {
        return;
    }
    selfBudgetReady.value = false;
    selfBudgetForm.enabled = Boolean(config.enabled);
    selfBudgetForm.daily_budget_usd = Number(config.daily_budget_usd ?? 0);
    selfBudgetForm.daily_token_budget = Number(config.daily_token_budget ?? 0);
    selfBudgetForm.daily_call_budget = Number(config.daily_call_budget ?? 0);
    selfBudgetForm.max_tokens_per_call = Number(config.max_tokens_per_call ?? 0);
    selfBudgetDirty.value = false;
    selfBudgetReady.value = true;
    selfBudgetError.value = '';
};

const fetchSelfBudget = async () => {
    try {
        const response = await fetch('/api/self_improvement/budget');
        if (!response.ok) {
            throw new Error('Failed to fetch self-improvement budget');
        }
        const data = await response.json();
        selfBudget.value = data;
        applySelfBudgetForm(data?.config || {});
    } catch (error) {
        showToast('Unable to fetch self-improvement budget');
        console.error(error);
    }
};

const saveSelfBudget = async () => {
    if (selfBudgetSaving.value) {
        return;
    }
    selfBudgetSaving.value = true;
    selfBudgetError.value = '';
    try {
        const response = await fetch('/api/self_improvement/budget', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                config: {
                    enabled: Boolean(selfBudgetForm.enabled),
                    daily_budget_usd: Number(selfBudgetForm.daily_budget_usd),
                    daily_token_budget: Number(selfBudgetForm.daily_token_budget),
                    daily_call_budget: Number(selfBudgetForm.daily_call_budget),
                    max_tokens_per_call: Number(selfBudgetForm.max_tokens_per_call)
                }
            })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to update budget');
        }
        selfBudget.value = data;
        applySelfBudgetForm(data?.config || {});
        showToast('Self-improvement budget updated');
    } catch (error) {
        selfBudgetError.value = error.message || 'Unable to update budget';
        showToast(selfBudgetError.value);
        console.error(error);
    } finally {
        selfBudgetSaving.value = false;
    }
};

const setUpdateTimestamp = () => {
    lastUpdate.value = new Date().toLocaleTimeString();
};

const fetchToolStatus = async () => {
    try {
        const response = await fetch('/api/tools');
        if (!response.ok) {
            throw new Error('Failed to fetch tool status');
        }
        toolStatus.value = await response.json();
        setUpdateTimestamp();
    } catch (error) {
        showToast('Unable to fetch tool status');
        console.error(error);
    }
};

const fetchGoogleAuthStatus = async () => {
    try {
        const response = await fetch('/api/google/auth/status');
        if (!response.ok) {
            throw new Error('Failed to fetch Google auth status');
        }
        googleAuthStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch Google auth status');
        console.error(error);
    }
};

const fetchToolInventory = async () => {
    try {
        const response = await fetch('/api/tools/list');
        if (!response.ok) {
            throw new Error('Failed to fetch tool inventory');
        }
        toolInventory.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch tool inventory');
        console.error(error);
    }
};

const fetchLastPayload = async (silent = false) => {
    if (payloadRefreshInFlight.value) {
        return;
    }
    payloadRefreshInFlight.value = true;
    try {
        const response = await fetch('/api/tools/last_payload');
        if (!response.ok) {
            throw new Error('Failed to fetch tool payload');
        }
        const data = await response.json();
        const payload = data.payload || data || null;
        if (payload && Object.keys(payload).length === 0) {
            lastPayload.value = null;
        } else {
            lastPayload.value = payload;
        }
    } catch (error) {
        if (!silent) {
            showToast('Unable to fetch last tool payload');
            console.error(error);
        }
    } finally {
        payloadRefreshInFlight.value = false;
    }
};

const fetchVoiceStatus = async () => {
    try {
        const response = await fetch('/api/voice/status');
        if (!response.ok) {
            throw new Error('Failed to fetch voice status');
        }
        voiceStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch voice status');
        console.error(error);
    }
};

const fetchQuorumStatus = async () => {
    try {
        const response = await fetch('/api/quorum/status');
        if (!response.ok) {
            throw new Error('Failed to fetch quorum status');
        }
        const data = await response.json();
        quorumStatus.value = data;
        if (!quorumSettingsReady.value && data?.settings) {
            quorumAutoEnabled.value = Boolean(data.settings.quorum_auto_enabled);
            swarmAutoEnabled.value = Boolean(data.settings.swarm_auto_enabled);
            quorumSettingsReady.value = true;
        }
    } catch (error) {
        console.error(error);
    }
};

const fetchQuorumCatalog = async () => {
    try {
        const response = await fetch('/api/quorum/list');
        if (!response.ok) {
            throw new Error('Failed to fetch quorum catalog');
        }
        const data = await response.json();
        quorumCatalog.value = data.quorums || [];
        if (selectedQuorumName.value) {
            const names = new Set((data.quorums || []).map((quorum) => quorum.name));
            if (!names.has(selectedQuorumName.value)) {
                selectedQuorumName.value = '';
            }
        }
    } catch (error) {
        showToast('Unable to fetch quorum catalog');
        console.error(error);
    }
};

const syncQuorumSettings = async () => {
    if (quorumSyncInFlight.value) {
        return;
    }
    quorumSyncInFlight.value = true;
    try {
        const response = await fetch('/api/quorum/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                quorum_auto_enabled: Boolean(quorumAutoEnabled.value),
                swarm_auto_enabled: Boolean(swarmAutoEnabled.value)
            })
        });
        if (!response.ok) {
            throw new Error('Failed to update quorum settings');
        }
        const data = await response.json();
        if (data?.settings) {
            quorumAutoEnabled.value = Boolean(data.settings.quorum_auto_enabled);
            swarmAutoEnabled.value = Boolean(data.settings.swarm_auto_enabled);
        }
    } catch (error) {
        showToast('Unable to update quorum settings');
        console.error(error);
    } finally {
        quorumSyncInFlight.value = false;
    }
};

const requestQueueConfirmation = (message, action) => {
    queueWarningMessage.value = message;
    pendingQueueAction.value = action;
    showQueueWarning.value = true;
};

const confirmQueueAction = () => {
    if (pendingQueueAction.value) {
        pendingQueueAction.value();
    }
    pendingQueueAction.value = null;
};

const queueQuorum = () => {
    const targetName = selectedQuorumName.value || '';
    const profile = availableQuorums.value.find((quorum) => quorum.name === targetName);
    const agentCount = profile?.agents?.length || 0;
    const isSwarmSelection = Boolean(profile?.is_swarm);
    const proceed = () => {
        pendingQuorumMode.value = isSwarmSelection ? 'swarm' : 'quorum';
        pendingQuorumName.value = targetName;
        const label = pendingQuorumName.value
            ? `${isSwarmSelection ? 'Swarm' : 'Quorum'} · ${pendingQuorumName.value}`
            : (isSwarmSelection ? 'Swarm' : 'Quorum');
        showToast(`Next message will use ${label}`);
    };
    if (isSwarmSelection) {
        requestQueueConfirmation(
            'Custom swarm uses swarm gating/limits and can be expensive. Continue?',
            proceed
        );
        return;
    }
    if (agentCount >= 5) {
        requestQueueConfirmation(
            `This quorum uses ${agentCount} agents. Large quorums increase token usage and latency. Continue?`,
            proceed
        );
        return;
    }
    proceed();
};

const queueSwarm = () => {
    requestQueueConfirmation(
        'Swarm uses the full multi-agent stack and can be expensive. Continue?',
        () => {
            pendingQuorumMode.value = 'swarm';
            pendingQuorumName.value = '';
            showToast('Next message will use Swarm');
        }
    );
};

const clearQueuedMode = () => {
    pendingQuorumMode.value = null;
    pendingQuorumName.value = '';
};

const buildCustomQuorumPayload = () => {
    const name = customQuorumName.value.trim();
    const purpose = customQuorumPurpose.value.trim();
    const description = customQuorumDescription.value.trim();
    const agents = customQuorumAgents.value.map((agent) => ({
        name: agent,
        is_lead: agent === customQuorumLead.value,
        veto_authority: agent === customQuorumVeto.value,
        weight: 1.0
    }));

    if (!name) {
        showToast('Custom quorum name is required.');
        return null;
    }
    if (!purpose) {
        showToast('Add a short purpose for the custom quorum.');
        return null;
    }
    if (agents.length < 2) {
        showToast('Select at least two agents.');
        return null;
    }
    if (customQuorumConsensus.value === 'veto_authority' && !customQuorumVeto.value) {
        showToast('Select a veto agent for veto authority.');
        return null;
    }

    return {
        name,
        purpose,
        description,
        consensus: customQuorumConsensus.value,
        agents,
        is_swarm: Boolean(customQuorumIsSwarm.value)
    };
};

const saveCustomQuorum = async () => {
    const payload = buildCustomQuorumPayload();
    if (!payload) {
        return;
    }
    if (payload.is_swarm || payload.agents.length >= 5) {
        pendingCustomQuorumPayload.value = payload;
        customQuorumWarningMessage.value = payload.is_swarm
            ? 'Custom swarm will use swarm gating/limits and can be expensive. Continue?'
            : 'This custom quorum has many agents and may consume more tokens and time. Continue?';
        showCustomQuorumWarning.value = true;
        return;
    }
    await submitCustomQuorum(payload);
};

const submitCustomQuorum = async (payload) => {
    if (customQuorumSaving.value) {
        return;
    }
    customQuorumSaving.value = true;
    try {
        const response = await fetch('/api/quorum/custom', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to save custom quorum');
        }
        await fetchQuorumCatalog();
        customQuorumPreset.value = payload.name;
        showToast(`Saved custom quorum: ${payload.name}`);
    } catch (error) {
        showToast(error.message || 'Unable to save custom quorum');
        console.error(error);
    } finally {
        customQuorumSaving.value = false;
        pendingCustomQuorumPayload.value = null;
    }
};

const confirmLargeCustomQuorum = () => {
    if (pendingCustomQuorumPayload.value) {
        submitCustomQuorum(pendingCustomQuorumPayload.value);
    }
};

const deleteCustomQuorumPreset = async () => {
    const name = customQuorumPreset.value || customQuorumName.value;
    if (!name) {
        showToast('Select a custom quorum to delete.');
        return;
    }
    try {
        const response = await fetch('/api/quorum/custom/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to delete custom quorum');
        }
        await fetchQuorumCatalog();
        if (customQuorumPreset.value === name) {
            clearCustomForm();
        }
        showToast(`Deleted custom quorum: ${name}`);
    } catch (error) {
        showToast(error.message || 'Unable to delete custom quorum');
        console.error(error);
    }
};

const formatTimestamp = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatConsensus = (value) => {
    if (!value) return '—';
    return value.replace(/_/g, ' ');
};

const formatAgentName = (value) => {
    if (!value) return value;
    return value.replace(/(?<!^)(?=[A-Z])/g, ' ');
};

const fetchMemoryStats = async () => {
    try {
        const response = await fetch('/api/memory/stats');
        if (!response.ok) {
            throw new Error('Failed to fetch memory stats');
        }
        const data = await response.json();
        memoryStats.value = data.stats || null;
    } catch (error) {
        showToast('Unable to fetch memory stats');
        console.error(error);
    }
};

const fetchBrowserStatus = async () => {
    try {
        const response = await fetch('/api/browser/status');
        if (!response.ok) {
            throw new Error('Failed to fetch browser status');
        }
        browserStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch browser status');
        console.error(error);
    }
};

const fetchSelfImproveStatus = async () => {
    try {
        const response = await fetch('/api/self_improvement/status');
        if (!response.ok) {
            throw new Error('Failed to fetch self-improvement status');
        }
        selfImproveStatus.value = await response.json();
    } catch (error) {
        showToast('Unable to fetch self-improvement status');
        console.error(error);
    }
};

const fetchSelfImproveLogs = async () => {
    try {
        const response = await fetch('/api/self_improvement/logs?lines=200');
        if (!response.ok) {
            throw new Error('Failed to fetch self-improvement logs');
        }
        const data = await response.json();
        selfImproveLogs.value = data.log || '';
    } catch (error) {
        console.error(error);
    }
};

const refreshSelfImproveLogs = async () => {
    await fetchSelfImproveLogs();
};

const runSelfImprove = async (action, params = {}) => {
    if (selfImproveBusy.value) {
        return;
    }
    selfImproveBusy.value = true;
    selfImproveError.value = '';
    try {
        const response = await fetch('/api/self_improvement/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, params })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to start self-improvement task');
        }
        selfImproveStatus.value = data.status || selfImproveStatus.value;
        await fetchSelfImproveLogs();
        showToast(`Started ${action}`);
    } catch (error) {
        selfImproveError.value = error.message || 'Unable to start task';
        showToast(selfImproveError.value);
        console.error(error);
    } finally {
        selfImproveBusy.value = false;
    }
};

const runRedTeam = async () => {
    await runSelfImprove('red_team', { use_llm: Boolean(selfImproveUseLlm.value) });
};

const runArchitect = async () => {
    await runSelfImprove('architect', {});
};

const runRegression = async () => {
    const limit = Number(selfImproveRegressionLimit.value || 0);
    await runSelfImprove('regression', { limit });
};

const trainRewardModel = async () => {
    await runSelfImprove('train_reward_model', {});
};

const runMemvidExport = async () => {
    const limit = Number(selfImproveMemvidLimit.value || 0);
    const params = {};
    if (limit > 0) {
        params.limit = limit;
    }
    await runSelfImprove('memvid_export', params);
};

const runExportSpecialist = async () => {
    const limit = Number(selfImproveMemvidLimit.value || 0);
    const params = {};
    if (limit > 0) {
        params.memvid_limit = limit;
    }
    await runSelfImprove('export_specialist', params);
};

const simulatePatch = async () => {
    selfImprovePatchResult.value = null;
    selfImproveError.value = '';
    let patchOps = null;
    try {
        patchOps = JSON.parse(selfImprovePatchText.value || '[]');
    } catch (error) {
        selfImproveError.value = 'Patch JSON is invalid.';
        return;
    }
    try {
        const response = await fetch('/api/self_improvement/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ patch: patchOps })
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Simulation failed');
        }
        selfImprovePatchResult.value = data;
    } catch (error) {
        selfImproveError.value = error.message || 'Simulation failed';
    }
};
const launchBrowser = async () => {
    if (browserLaunching.value) {
        return;
    }
    browserLaunching.value = true;
    try {
        const response = await fetch('/api/browser/launch', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to launch browser');
        }
        await fetchBrowserStatus();
        showToast('Browser launched');
    } catch (error) {
        showToast(error.message || 'Unable to launch browser');
        console.error(error);
    } finally {
        browserLaunching.value = false;
    }
};

const closeBrowser = async () => {
    if (browserClosing.value) {
        return;
    }
    browserClosing.value = true;
    try {
        const response = await fetch('/api/browser/close', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data?.error || 'Failed to close browser');
        }
        await fetchBrowserStatus();
        showToast('Browser closed');
    } catch (error) {
        showToast(error.message || 'Unable to close browser');
        console.error(error);
    } finally {
        browserClosing.value = false;
    }
};

const startSelfImprovePolling = () => {
    if (selfImproveLogTimer.value) {
        return;
    }
    selfImproveLogTimer.value = setInterval(() => {
        fetchSelfImproveStatus();
        fetchSelfImproveLogs();
    }, 5000);
};

const stopSelfImprovePolling = () => {
    if (selfImproveLogTimer.value) {
        clearInterval(selfImproveLogTimer.value);
        selfImproveLogTimer.value = null;
    }
};

const refreshAll = async () => {
    await fetchToolStatus();
    await fetchToolInventory();
    await fetchLastPayload();
    await fetchGoogleAuthStatus();
    await fetchVoiceStatus();
    await fetchMemoryStats();
    await fetchBrowserStatus();
    await fetchSelfImproveStatus();
    await fetchSelfImproveLogs();
    await fetchSelfBudget();
    await fetchQuorumStatus();
    await fetchQuorumCatalog();
};

const startStoppedTools = async () => {
    if (!toolStatus.value) {
        await fetchToolStatus();
    }
    const servers = Object.entries(toolStatus.value?.mcp?.servers || {})
        .filter(([, server]) => !server.running && (!server.missing_env || server.missing_env.length === 0))
        .map(([name]) => name);

    if (!servers.length) {
        showToast('No stopped MCP servers without missing credentials');
        return;
    }
    try {
        const response = await fetch('/api/tools/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ servers })
        });
        if (!response.ok) {
            throw new Error('Failed to start tools');
        }
        await refreshAll();
        showToast('Started stopped MCP servers');
    } catch (error) {
        showToast('Unable to start tools');
        console.error(error);
    }
};

const restartUnhealthyTools = async () => {
    if (!toolStatus.value) {
        await fetchToolStatus();
    }
    const servers = Object.entries(toolStatus.value?.mcp?.servers || {})
        .filter(([, server]) => server.running && server.health && server.health !== 'healthy')
        .map(([name]) => name);

    if (!servers.length) {
        showToast('No unhealthy MCP servers to restart');
        return;
    }
    try {
        const response = await fetch('/api/tools/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ servers })
        });
        if (!response.ok) {
            throw new Error('Failed to restart tools');
        }
        await refreshAll();
        showToast('Restarted unhealthy MCP servers');
    } catch (error) {
        showToast('Unable to restart tools');
        console.error(error);
    }
};

const verifyTools = async () => {
    isVerifying.value = true;
    verifySummary.value = null;
    verifyResults.value = [];
    try {
        const response = await fetch('/api/tools/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timeout: 30, memvid_timeout: 120 })
        });
        if (!response.ok) {
            throw new Error('Verification failed');
        }
        const data = await response.json();
        verifySummary.value = data.summary || null;
        verifyResults.value = data.results || [];
        expandedSections.value.verify = true; // Auto-expand verification results
        await refreshAll();
        showToast('Tool verification complete');
    } catch (error) {
        showToast('Tool verification failed');
        console.error(error);
    } finally {
        isVerifying.value = false;
    }
};

const runVoiceTest = async () => {
    voiceTesting.value = true;
    voiceTestResult.value = '';
    try {
        const selectedVoice = voiceAgentVoice.value || voiceStatus.value?.selected_voice;
        const response = await fetch('/api/voice/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_audio: true, voice: selectedVoice })
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'Voice test failed');
        }
        voiceTestResult.value = `Handshake ok (session ${data.session_id || 'unknown'})`;
        if (data.audio_b64) {
            const binary = atob(data.audio_b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) {
                bytes[i] = binary.charCodeAt(i);
            }
            const blob = new Blob([bytes], { type: data.audio_format || 'audio/wav' });
            playAudio(blob);
        }
        showToast('Voice test succeeded');
    } catch (error) {
        voiceTestResult.value = `Handshake failed: ${error.message || error}`;
        showToast('Voice test failed');
        console.error(error);
    } finally {
        voiceTesting.value = false;
    }
};

const sendToolsRequest = () => {
    if (!wsRef.value || wsRef.value.readyState !== WebSocket.OPEN) {
        return;
    }
    wsRef.value.send(JSON.stringify({ type: 'tools' }));
    wsRef.value.send(JSON.stringify({ type: 'quorum' }));
};

const connectWebSocket = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws`;
    wsStatus.value = 'connecting';
    wsRef.value = new WebSocket(wsUrl);

    wsRef.value.addEventListener('open', () => {
        wsStatus.value = 'connected';
        sendToolsRequest();
        wsTimer.value = setInterval(sendToolsRequest, 10000);
    });

    wsRef.value.addEventListener('message', (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (payload.type === 'tools') {
                toolStatus.value = { mcp: payload.data, native: toolStatus.value?.native || { tools: [], errors: {} } };
                setUpdateTimestamp();
                return;
            }
            if (payload.type === 'tool_payload') {
                lastPayload.value = payload.data || null;
                setUpdateTimestamp();
            }
            if (payload.type === 'quorum') {
                quorumStatus.value = payload.data || null;
                if (!quorumSettingsReady.value && payload.data?.settings) {
                    quorumAutoEnabled.value = Boolean(payload.data.settings.quorum_auto_enabled);
                    swarmAutoEnabled.value = Boolean(payload.data.settings.swarm_auto_enabled);
                    quorumSettingsReady.value = true;
                }
                setUpdateTimestamp();
            }
        } catch (error) {
            console.error(error);
        }
    });

    wsRef.value.addEventListener('close', () => {
        wsStatus.value = 'disconnected';
        if (wsTimer.value) {
            clearInterval(wsTimer.value);
            wsTimer.value = null;
        }
    });

    wsRef.value.addEventListener('error', () => {
        wsStatus.value = 'error';
    });
};

onMounted(async () => {
    await refreshAll();
    connectWebSocket();
});

onBeforeUnmount(() => {
    if (wsTimer.value) {
        clearInterval(wsTimer.value);
    }
    if (wsRef.value) {
        wsRef.value.close();
    }
    stopSelfImprovePolling();
});

const formatJson = (value) => JSON.stringify(value, null, 2);

watch([quorumAutoEnabled, swarmAutoEnabled], () => {
    if (!quorumSettingsReady.value) {
        return;
    }
    syncQuorumSettings();
});

watch(customQuorumAgents, (agents) => {
    if (!agents.includes(customQuorumLead.value)) {
        customQuorumLead.value = '';
    }
    if (!agents.includes(customQuorumVeto.value)) {
        customQuorumVeto.value = '';
    }
});

watch(selfBudgetForm, () => {
    if (!selfBudgetReady.value) {
        return;
    }
    selfBudgetDirty.value = true;
}, { deep: true });

watch(() => expandedSections.value.selfImprove, (open) => {
    if (open) {
        fetchSelfImproveStatus();
        fetchSelfImproveLogs();
        startSelfImprovePolling();
    } else {
        stopSelfImprovePolling();
    }
});

watch(customQuorumPreset, (value) => {
    const preset = customQuorums.value.find((item) => item.name === value);
    if (preset) {
        applyCustomPreset(preset);
    } else if (!value) {
        clearCustomForm();
    }
});
</script>

<style scoped lang="scss">
$bg-card: var(--vera-tool-card-bg);
$border: var(--vera-tool-card-border);
$text-muted: var(--vera-text-muted);
$ok: var(--vera-success);
$warn: var(--vera-warning);
$danger: var(--vera-danger);

.tools-dialog {
    position: relative;
    inset: 0;
    width: 100%;
    height: 100%;
    max-height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    border-radius: 0;
    border: none;
    background: transparent;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    box-shadow: 0 18px 40px rgba(var(--vera-shadow-rgb), 0.35);

    // Ensure cards don't overflow horizontally
    > * {
        flex-shrink: 0;
        min-width: 0;
        max-width: 100%;
    }
}

.tools-dialog.collapsed {
    align-items: center;
    padding: 12px 8px;
}

.tools-dialog.collapsed .tools-header {
    flex-direction: column;
    gap: 6px;
    overflow: visible;
}

.tools-dialog.collapsed .header-actions {
    gap: 2px;
}

.tools-dialog.collapsed .title span {
    display: none;
}

.tools-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
}

.tools-header .title {
    display: flex;
    align-items: center;
    gap: 8px;
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
}

.icon-button {
    background: transparent;
    border: none;
    color: inherit;
    cursor: pointer;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.collapsed-label {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: $text-muted;
}

.collapsed-meta {
    font-size: 0.6875rem;
    text-transform: none;
    letter-spacing: 0.02em;
}

// Accordion card styles
.accordion-card {
    padding: 0 !important;

    .accordion-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 12px;
        cursor: pointer;
        user-select: none;
        transition: background-color 0.15s ease;
        border-radius: 11px;

        &:hover {
            background: rgba(var(--vera-contrast-rgb), 0.04);
        }
    }

    .accordion-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.8125rem;
        font-weight: 500;
        color: $text-muted;

        svg {
            opacity: 0.7;
            flex-shrink: 0;
        }
    }

    .accordion-summary {
        font-size: 0.75rem;
        color: $text-muted;
        opacity: 0.85;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 50%;
        text-align: right;
    }

    .accordion-content {
        padding: 0 12px 12px;

        ul {
            margin: 0;
            padding: 0;
        }
    }
}

.tools-status-card,
.tool-status-card,
.tool-inventory-card,
.verify-card,
.tool-payload-card,
.voice-status-card,
.memory-stats-card,
.browser-status-card,
.self-improvement-card,
.self-budget-card,
.quorum-hero-card,
.quorum-controls-card,
.quorum-summary-card {
    background: $bg-card;
    border-radius: 12px;
    padding: 12px;
    border: 1px solid $border;
    box-shadow: var(--vera-panel-shadow), inset 0 1px 0 var(--vera-panel-edge), var(--vera-panel-inner-glow), var(--vera-panel-bevel), var(--vera-tool-card-glow);
    --vera-glow-base: var(--vera-tool-card-glow);
    --vera-glow-peak: 0 0 20px var(--vera-effect-glow-color);
    animation: var(--vera-glow-animation);
    animation-delay: var(--vera-glow-delay, 0s);
    overflow: hidden;

    // Ensure text content respects card boundaries
    span, code, .tool-name, .verify-name, .verify-detail {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
    }
}

.status-row,
.verify-header,
.tool-status-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8125rem;
    color: $text-muted;
    margin-bottom: 6px;
}

.tool-badge {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    background: var(--vera-panel-alt);
    color: $text-muted;
}

.tool-badge.ok {
    background: var(--vera-accent-faint);
    color: $ok;
}

.tool-badge.warn {
    background: var(--vera-accent-faint);
    color: $warn;
}

.tool-badge.danger {
    background: var(--vera-accent-faint);
    color: $danger;
}

.inventory-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.inventory-section + .inventory-section {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(var(--vera-contrast-rgb), 0.08);
}

.inventory-section-header {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: $text-muted;
}

.status-pill {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.status-pill.ok {
    background: var(--vera-success-20);
    color: $ok;
}

.status-pill.warn {
    background: var(--vera-warning-20);
    color: $warn;
}

.status-pill.danger {
    background: var(--vera-error-20);
    color: $danger;
}

.status-pill.neutral {
    background: var(--vera-panel-alt);
    color: $text-muted;
}

.tools-tab-bar {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    padding: 6px;
    border-radius: 999px;
    border: 1px solid $border;
    background: var(--vera-panel-alt);
    box-shadow: inset 0 0 0 1px rgba(var(--vera-contrast-rgb), 0.04);
}

.tab-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 999px;
    border: none;
    background: transparent;
    color: $text-muted;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
}

.tab-button.active {
    background: var(--vera-accent-faint);
    color: var(--vera-text);
    box-shadow: 0 0 18px var(--vera-accent-soft);
}

.tools-actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 8px;
}

.primary-btn,
.secondary-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 10px;
    border-radius: 10px;
    border: none;
    cursor: pointer;
    font-weight: 600;
    font-size: 0.8125rem;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.primary-btn {
    background: linear-gradient(135deg, var(--vera-accent), var(--vera-accent-strong));
    color: var(--vera-text);
}

.secondary-btn {
    background: var(--vera-accent-faint);
    color: var(--vera-text);
    border: 1px solid var(--vera-accent-soft);
}

.primary-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}

.primary-btn.active {
    box-shadow: 0 0 14px var(--vera-accent-soft);
}

.secondary-btn.active {
    background: var(--vera-accent-soft);
    color: var(--vera-text);
}

.icon-button.small {
    padding: 4px;
    border-radius: 8px;
    background: rgba(var(--vera-contrast-rgb), 0.06);
}

.tool-status-card ul,
.verify-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.tool-status-card li,
.verify-list li {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--vera-accent-12);
    border-radius: 10px;
    background: var(--vera-panel-alt);
}

.tool-status-card li:last-child,
.verify-list li:last-child {
    border-bottom: none;
}

.tool-name {
    font-weight: 600;
}

.tool-state.ok,
.tool-health.ok {
    color: $ok;
}

.tool-state.warn,
.tool-health.warn {
    color: $warn;
}

.tool-missing {
    color: $danger;
    font-size: 0.75rem;
}

.verify-list li.ok .verify-status {
    color: $ok;
}

.verify-list li.fail .verify-status {
    color: $danger;
}

.verify-list li.skip .verify-status {
    color: $warn;
}

.verify-detail {
    font-size: 0.75rem;
    color: $text-muted;
}

.tool-inventory-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.tool-inventory-list summary {
    cursor: pointer;
    font-weight: 600;
}

.inventory-tip {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    margin-bottom: 12px;
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid rgba(var(--vera-info-rgb, 80, 140, 255), 0.3);
    background: rgba(var(--vera-info-rgb, 80, 140, 255), 0.12);
    color: var(--vera-text);
    font-size: 0.82rem;
}

.inventory-tip code {
    font-family: "JetBrains Mono", "SFMono-Regular", ui-monospace, monospace;
    font-size: 0.78rem;
    padding: 2px 6px;
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.3);
    color: inherit;
}

.tool-list {
    margin-top: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    line-height: 1.4;
}

.payload-note {
    margin-top: 6px;
    font-size: 0.6875rem;
    color: $text-muted;
}

.payload-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    margin-bottom: 10px;
}

.payload-empty {
    font-size: 0.75rem;
    color: $text-muted;
}

.payload-json {
    font-size: 0.6875rem;
    color: $text-muted;
    background: rgba(var(--vera-shadow-rgb), 0.2);
    border-radius: 8px;
    padding: 10px;
    white-space: pre-wrap;
    max-height: 200px;
    overflow: auto;
}

.voice-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    margin-bottom: 8px;
}

.voice-error {
    color: $danger;
}

.voice-test-result {
    font-size: 0.75rem;
    color: $text-muted;
    margin-top: 6px;
}

.memory-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
}

.oauth-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    overflow: hidden;

    > div {
        display: flex;
        gap: 4px;
        min-width: 0;

        > span {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    }
}

.quorum-panel {
    display: grid;
    gap: 12px;
}

.quorum-hero {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 16px;
    align-items: center;
}

.quorum-indicator {
    width: 72px;
    height: 72px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.quorum-hero-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
}

.quorum-agent-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
}

.quorum-agent-pill {
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--vera-accent-15);
    border: 1px solid var(--vera-accent-25);
    color: var(--vera-text);
    font-size: 0.6875rem;
    letter-spacing: 0.02em;
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
}

.quorum-controls {
    display: grid;
    gap: 12px;
}

.quorum-toggle,
.quorum-manual {
    display: grid;
    gap: 8px;
    padding: 10px;
    border-radius: 12px;
    background: var(--vera-panel-alt);
    border: 1px solid var(--vera-accent-soft);
}

.quorum-toggle :deep(.p-togglebutton) {
    background: var(--vera-panel-alt);
    border: 1px solid var(--vera-glass-border);
    color: var(--vera-text);
}

.quorum-toggle :deep(.p-togglebutton:not(.p-highlight):hover) {
    background: var(--vera-accent-faint);
}

.quorum-toggle :deep(.p-togglebutton.p-highlight) {
    background: var(--vera-accent-soft);
    border-color: var(--vera-accent);
    color: var(--vera-text);
    box-shadow: var(--vera-glow-soft);
}

.quorum-toggle :deep(.p-togglebutton.p-highlight:hover) {
    background: var(--vera-accent-soft);
}

.quorum-toggle :deep(.control-checkbox label) {
    font-size: 0.875rem;
    color: var(--vera-text);
}

.quorum-note {
    font-size: 0.75rem;
    color: $text-muted;
}

.quorum-manual-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.75rem;
    color: $text-muted;
}

.quorum-queued-pill {
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--vera-accent-soft);
    color: var(--vera-text-muted);
    font-size: 0.6875rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.quorum-manual-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
}

.quorum-select {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
}

.quorum-select label {
    font-weight: 600;
    color: var(--vera-text-muted);
}

.quorum-select select {
    width: 100%;
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid var(--vera-glass-border);
    background: var(--vera-panel-alt);
    color: var(--vera-text);
    font-size: 0.75rem;
}

.quorum-select input,
.quorum-select textarea {
    width: 100%;
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid var(--vera-glass-border);
    background: var(--vera-panel-alt);
    color: var(--vera-text);
    font-size: 0.75rem;
    resize: vertical;
}

.quorum-custom {
    display: grid;
    gap: 10px;
    padding-top: 4px;
    border-top: 1px solid var(--vera-accent-12);
}

.quorum-custom-header {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--vera-text);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.quorum-custom-agents {
    display: grid;
    gap: 8px;
}

.quorum-custom-label {
    font-size: 0.75rem;
    color: var(--vera-text-muted);
    font-weight: 600;
}

.agent-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.agent-chip {
    border: 1px solid var(--vera-accent-soft);
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 0.6875rem;
    color: var(--vera-text);
    background: rgba(var(--vera-contrast-rgb), 0.04);
    cursor: pointer;
    transition: all 0.2s ease;
}

.agent-chip.active {
    background: var(--vera-accent-faint);
    border-color: var(--vera-accent);
    color: var(--vera-text);
    box-shadow: var(--vera-glow-soft);
}

.quorum-custom-meta {
    display: grid;
    gap: 10px;
}

.quorum-profile {
    display: grid;
    gap: 6px;
    padding: 10px;
    border-radius: 10px;
    border: 1px solid var(--vera-accent-soft);
    background: rgba(var(--vera-shadow-rgb), 0.2);
    font-size: 0.75rem;
    color: $text-muted;
}

.quorum-profile-title {
    font-weight: 600;
    color: var(--vera-text);
}

.quorum-profile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.quorum-profile-meta span {
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
}

.quorum-profile-agents {
    font-size: 0.75rem;
    color: $text-muted;
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
}

.quorum-profile-purpose {
    font-size: 0.75rem;
    color: $text-muted;
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
}

.quorum-summary {
    font-size: 0.75rem;
    color: $text-muted;
    background: var(--vera-panel-alt);
    border-radius: 10px;
    padding: 10px;
    white-space: pre-wrap;
    border: 1px solid var(--vera-accent-soft);
}

.budget-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    margin-bottom: 10px;
}

.budget-form {
    display: grid;
    gap: 12px;
}

.budget-grid {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
}

.budget-note {
    font-size: 0.6875rem;
    color: $text-muted;
}

.budget-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.budget-error {
    font-size: 0.75rem;
    color: $danger;
}

.browser-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    margin-bottom: 8px;
}

.browser-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 6px;
}

.browser-error {
    color: $danger;
}

.browser-note {
    font-size: 0.6875rem;
    color: $text-muted;
}

.self-improve-meta {
    display: grid;
    gap: 6px;
    font-size: 0.75rem;
    color: $text-muted;
    margin-bottom: 10px;
}

.self-improve-controls {
    display: grid;
    gap: 10px;
    margin-bottom: 12px;
}

.self-improve-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
}

.self-improve-log {
    display: grid;
    gap: 6px;
}

.self-improve-log-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.75rem;
    color: $text-muted;
}

.self-improve-log-output {
    background: rgba(var(--vera-shadow-rgb), 0.35);
    border: 1px solid var(--vera-accent-soft);
    border-radius: 8px;
    padding: 8px;
    max-height: 180px;
    overflow: auto;
    font-size: 0.6875rem;
    color: $text-muted;
    white-space: pre-wrap;
    transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.self-improve-error {
    font-size: 0.75rem;
    color: $danger;
}

.self-improve-patch-result {
    font-size: 0.75rem;
    color: $text-muted;
}

.self-improve-note {
    font-size: 0.6875rem;
    color: $text-muted;
}

.quorum-select.full-width {
    width: 100%;
}

.self-improvement-card .status-pill.warn {
    animation: selfImprovePulse 1.8s ease-in-out infinite;
}

@keyframes selfImprovePulse {
    0% {
        box-shadow: 0 0 0 rgba(var(--vera-warning-rgb), 0);
    }
    50% {
        box-shadow: 0 0 12px rgba(var(--vera-warning-rgb), 0.35);
    }
    100% {
        box-shadow: 0 0 0 rgba(var(--vera-warning-rgb), 0);
    }
}

</style>
