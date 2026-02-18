/**
 * WebSocket client for receiving VERA's thinking events.
 * Connects to the /ws endpoint and streams thinking events to the UI.
 */

import { thinkingEvents } from '@/libs/state-management/state';
import { showToast } from '@/libs/utils/general-utils';

let websocket = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY = 1000;
const CONNECTION_TIMEOUT = 3000; // 3 second timeout for WebSocket connection
const innerLifeListeners = new Set();

/**
 * Get the WebSocket URL based on the current page location
 * @returns {string} The WebSocket URL
 */
function getWebSocketUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}/ws`;
}

/**
 * Connect to the VERA WebSocket endpoint for thinking events.
 * Automatically clears previous thinking events on connect.
 * @returns {Promise<WebSocket>} The connected WebSocket
 */
export function connectThinkingWebSocket() {
    return new Promise((resolve, reject) => {
        // Clear previous thinking events
        thinkingEvents.value = [];

        // Close existing connection if any
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.close();
        }

        const url = getWebSocketUrl();
        let timeoutId = null;
        let settled = false;

        // Helper to prevent double-settling the promise
        const settle = (fn) => {
            if (!settled) {
                settled = true;
                if (timeoutId) clearTimeout(timeoutId);
                fn();
            }
        };

        try {
            websocket = new WebSocket(url);

            // Set connection timeout
            timeoutId = setTimeout(() => {
                settle(() => {
                    if (websocket) {
                        websocket.close();
                        websocket = null;
                    }
                    reject(new Error('WebSocket connection timeout'));
                });
            }, CONNECTION_TIMEOUT);

            websocket.onopen = () => {
                settle(() => {
                    reconnectAttempts = 0;
                    resolve(websocket);
                });
            };

            websocket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    // Handle thinking events
                    if (data.type === 'thinking') {
                        const newEvent = {
                            event_type: data.event_type,
                            message: data.message,
                            timestamp: data.timestamp,
                            metadata: data.metadata || {}
                        };
                        thinkingEvents.value = [...thinkingEvents.value, newEvent];
                    }
                    else if (data.type === 'confirmation') {
                        const status = data?.data?.status || '';
                        if (status === 'declined') {
                            showToast('Confirmation cancelled');
                        } else if (status === 'declined_missing') {
                            showToast('Confirmation cancelled (no pending action)');
                        } else if (status === 'accepted') {
                            showToast('Confirmation accepted · executing');
                        }
                    }
                    else if (data.type === 'innerlife') {
                        const payload = data.event || data;
                        innerLifeListeners.forEach((listener) => {
                            try {
                                listener(payload);
                            } catch (error) {
                                console.warn('[ThinkingWS] Inner life listener failed:', error);
                            }
                        });
                    }
                    // Handle errors
                    else if (data.type === 'error') {
                        console.error('[ThinkingWS] Server error:', data.message);
                    }
                } catch (parseError) {
                    console.warn('[ThinkingWS] Failed to parse message:', event.data);
                }
            };

            websocket.onerror = (error) => {
                settle(() => {
                    console.error('[ThinkingWS] Error:', error);
                    reject(error);
                });
            };

            websocket.onclose = () => {
                websocket = null;
            };

        } catch (error) {
            settle(() => {
                console.error('[ThinkingWS] Failed to create WebSocket:', error);
                reject(error);
            });
        }
    });
}

/**
 * Ensure the WebSocket is connected without forcing a reconnect.
 * @returns {Promise<WebSocket>}
 */
export function ensureThinkingWebSocket() {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        return Promise.resolve(websocket);
    }
    return connectThinkingWebSocket();
}

/**
 * Register a listener for inner life events.
 * @param {function} listener
 * @returns {function} unsubscribe
 */
export function addInnerLifeListener(listener) {
    if (typeof listener !== 'function') return () => {};
    innerLifeListeners.add(listener);
    return () => innerLifeListeners.delete(listener);
}

/**
 * Send a message through the WebSocket connection
 * @param {string} text - The message text to send
 * @returns {Promise<void>}
 */
export async function sendThinkingMessage(text) {
    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        try {
            await connectThinkingWebSocket();
        } catch (error) {
            console.error('[ThinkingWS] Failed to connect:', error);
            return;
        }
    }

    const message = {
        type: 'message',
        text: text
    };

    websocket.send(JSON.stringify(message));
}

/**
 * Disconnect the WebSocket
 */
export function disconnectThinkingWebSocket() {
    if (websocket) {
        websocket.close();
        websocket = null;
    }
}

/**
 * Clear all thinking events
 */
export function clearThinkingEvents() {
    thinkingEvents.value = [];
}

/**
 * Check if the WebSocket is connected
 * @returns {boolean}
 */
export function isThinkingConnected() {
    return websocket && websocket.readyState === WebSocket.OPEN;
}
