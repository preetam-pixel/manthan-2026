
"use strict";

/* =========================================================
   MANTHAN 2026 — FRONTEND DASHBOARD
   Member 1: Frontend

   Mock mode:
   http://localhost:5173/?mock=1

   Live mode:
   Uses the proposed bot HTTP API.

   SAFETY:
   - No exchange gateway access.
   - No exchange order submission.
   - No API tokens.
   - Only bot Start, Stop, and Strategy control endpoints.
========================================================= */


/* =========================================================
   1. CONFIGURATION
========================================================= */

const CONFIG = {
    mock: new URLSearchParams(window.location.search).get("mock") === "1",

    apiBase: "",

    pollInterval: 2000,

    offlineThreshold: 6000,

    heartbeatThreshold: 15000,

    maxEvents: 200,

    defaultTicker: "HAVN",

    currency: "INR"
};


/* =========================================================
   2. APPLICATION STATE
========================================================= */

const state = {
    status: null,

    positions: [],

    events: [],

    series: {},

    equity: [],

    orders: [],

    strategies: [],

    news: [],

    riskBlocks: [],

    activeTicker: CONFIG.defaultTicker,

    activeEventFilter: "ALL",

    activeTickerFilter: "ALL",

    activityPaused: false,

    positionSort: {
        key: "ticker",
        direction: "asc"
    },

    lastEventId: null,

    lastSuccessfulFetch: null,

    polling: false,

    strategyChanged: false
};


/* =========================================================
   3. DOM HELPERS
========================================================= */

function $(id) {
    return document.getElementById(id);
}


function setText(id, value) {
    const element = $(id);

    if (!element) return;

    element.textContent =
        value === null ||
        value === undefined ||
        value === ""
            ? "—"
            : String(value);
}


function showElement(id, visible) {
    const element = $(id);

    if (!element) return;

    element.hidden = !visible;
}


function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function safeNumber(value) {
    const number = Number(value);

    return Number.isFinite(number) ? number : null;
}


/* =========================================================
   4. NUMBER FORMATTING
========================================================= */

function formatMoney(value) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(number);
}


function formatNumber(value, decimals = 2) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    return new Intl.NumberFormat("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(number);
}


function formatPercent(value) {
    const number = safeNumber(value);

    if (number === null) {
        return "—";
    }

    const sign = number > 0 ? "+" : "";

    return `${sign}${number.toFixed(2)}%`;
}


function formatDuration(seconds) {
    const value = safeNumber(seconds);

    if (value === null) {
        return "—";
    }

    if (value < 60) {
        return `${value.toFixed(2)} s`;
    }

    const minutes = Math.floor(value / 60);

    const remainingSeconds = Math.floor(value % 60);

    return `${minutes}m ${remainingSeconds}s`;
}


function formatDate(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return date.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });
}


function formatTime(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "—";
    }

    return date.toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });
}


/* =========================================================
   5. API HELPERS
========================================================= */

async function apiGet(endpoint) {
    const response = await fetch(
        `${CONFIG.apiBase}${endpoint}`,
        {
            method: "GET",

            headers: {
                "Accept": "application/json"
            },

            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(
            `GET ${endpoint} failed: ${response.status}`
        );
    }

    return response.json();
}


async function apiPost(endpoint, body = {}) {
    const response = await fetch(
        `${CONFIG.apiBase}${endpoint}`,
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json"
            },

            body: JSON.stringify(body)
        }
    );

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(
            result.error || `Request failed: ${response.status}`
        );
    }

    return result;
}


/* =========================================================
   6. FIXTURE DATA
========================================================= */

async function loadFixture(filename) {
    const response = await fetch(
        `./fixtures/${filename}.json`,
        {
            cache: "no-store"
        }
    );

    if (!response.ok) {
        throw new Error(
            `Fixture not found: ${filename}.json`
        );
    }

    return response.json();
}


async function fetchDashboardData() {

    if (CONFIG.mock) {

                const [
            status,
            positions,
            events,
            equity,
            orders,
            strategies,
            series
        ] = await Promise.all([

            loadFixture("status"),

            loadFixture("positions"),

            loadFixture("events"),

            loadFixture("equity"),

            loadFixture("orders"),

            loadFixture("strategies"),

            loadFixture(`series/${CONFIG.defaultTicker}`)

        ]);

        state.status = status;

        state.positions = positions;

        state.events = events;

        state.equity = equity;

        state.orders = orders;

        state.strategies = strategies;

        state.series[CONFIG.defaultTicker] = series;
        state.lastSuccessfulFetch = Date.now();

        return;
    }


    /* Live API mode */

    const [
        status,
        positions,
        events,
        equity,
        orders,
        strategies,
        series,
        news
    ] = await Promise.all([

        apiGet("/status"),

        apiGet("/positions"),

        apiGet(
            `/events?since=${state.lastEventId ?? 0}`
        ),

        apiGet("/equity"),

        apiGet("/orders"),

        apiGet("/strategies"),

        apiGet("/series"),

        apiGet("/news")

    ]);


    state.status = status;

    if (series && typeof series === "object" && !Array.isArray(series)) {

        state.series = series;

        const known = Object.keys(series);

        if (known.length && !known.includes(state.activeTicker)) {
            state.activeTicker = known[0];
        }

        const tickerSelector = document.getElementById("ticker-selector");

        if (
            tickerSelector &&
            known.length &&
            tickerSelector.options.length !== known.length
        ) {

            tickerSelector.innerHTML = known.map(
                ticker => `<option value="${escapeHTML(ticker)}">${escapeHTML(ticker)}</option>`
            ).join("");

            tickerSelector.value = state.activeTicker;

        }

    }

    state.news = Array.isArray(news)
        ? news
        : [];

    state.positions = Array.isArray(positions)
        ? positions
        : [];

    state.equity = Array.isArray(equity)
        ? equity
        : [];

    state.orders = Array.isArray(orders)
        ? orders
        : [];

    state.strategies = Array.isArray(strategies)
        ? strategies
        : [];


    if (Array.isArray(events)) {

        state.events = [
            ...events,
            ...state.events
        ].slice(0, CONFIG.maxEvents);


        if (events.length > 0) {

            const newestId = Math.max(
                ...events.map(event => safeNumber(event.id) ?? 0)
            );

            state.lastEventId = newestId;

        }

    }


    state.lastSuccessfulFetch = Date.now();
}


/* =========================================================
   7. HEADER STATUS
========================================================= */

function renderHeader() {

    const status = state.status;

    if (!status) return;

    const bot = status.bot || {};

    const sim = status.sim || {};


    const botState = bot.state || "OFFLINE";

    setText("bot-state", botState);

    setText("kafka-status",
        bot.kafka_connected === true
            ? "CONNECTED"
            : bot.kafka_connected === false
                ? "DISCONNECTED"
                : "—"
    );


    setText(
        "heartbeat-status",
        `Seq ${bot.last_heartbeat_seq ?? "—"}`
    );

    setText(
        "heartbeat-time",
        formatTime(bot.last_heartbeat_at)
    );


    setText(
        "simulation-status",
        sim.status || "—"
    );


    setText(
        "simulation-mode",
        sim.is_sandbox === true
            ? "SANDBOX"
            : sim.is_sandbox === false
                ? "LIVE RUN"
                : "—"
    );


    const stateElement = $("bot-state");

    if (stateElement) {

        stateElement.classList.remove(
            "running",
            "stopped",
            "offline"
        );

        if (botState === "RUNNING") {

            stateElement.classList.add("running");

        } else if (botState === "STOPPED") {

            stateElement.classList.add("stopped");

        } else {

            stateElement.classList.add("offline");

        }

    }


    const kafkaElement = $("kafka-status");

    if (kafkaElement) {

        kafkaElement.classList.toggle(
            "connected",
            bot.kafka_connected === true
        );

        kafkaElement.classList.toggle(
            "disconnected",
            bot.kafka_connected !== true
        );

    }


    renderSimulationProgress();

    renderOfflineStatus();

    renderControls();

}


/* =========================================================
   8. SIMULATION PROGRESS
========================================================= */

function renderSimulationProgress() {

    const sim = state.status?.sim || {};

    const completed = safeNumber(sim.days_completed);

    const total = safeNumber(sim.total_days);


    setText(
        "simulation-date",
        sim.current_date || "—"
    );


    setText(
        "days-completed",
        completed ?? "—"
    );


    setText(
        "total-days",
        total ?? "—"
    );


    setText(
        "simulation-stage",
        `Stage: ${sim.stage || "—"}`
    );


    setText(
        "simulation-interval",
        `Interval: ${sim.interval_seconds ?? "—"} s`
    );


    let percentage = 0;

    if (
        completed !== null &&
        total !== null &&
        total > 0
    ) {

        percentage = Math.min(
            100,
            Math.max(0, (completed / total) * 100)
        );

    }


    const fill = $("simulation-progress-fill");

    if (fill) {

        fill.style.width = `${percentage}%`;

    }


    const progress = $("simulation-progress-bar");

    if (progress) {

        progress.setAttribute(
            "aria-valuenow",
            String(percentage)
        );

    }

}


/* =========================================================
   9. OFFLINE STATUS
========================================================= */

function renderOfflineStatus() {

    const bot = state.status?.bot || {};

    const lastSeen = state.lastSuccessfulFetch;

    const elapsed = lastSeen
        ? Math.floor((Date.now() - lastSeen) / 1000)
        : null;


    const isOffline =
        elapsed === null ||
        elapsed > CONFIG.offlineThreshold / 1000;


    showElement(
        "offline-banner",
        isOffline
    );


    if (isOffline) {

        setText(
            "offline-last-seen",
            `Last seen: ${elapsed ?? "—"} s ago`
        );

    }


    const heartbeatAt = bot.last_heartbeat_at;

    if (!heartbeatAt) return;


    const heartbeatAge =
        (Date.now() - new Date(heartbeatAt).getTime()) / 1000;


    const heartbeatElement = $("heartbeat-status");

    if (heartbeatElement) {

        heartbeatElement.classList.toggle(
            "heartbeat-stale",
            heartbeatAge > CONFIG.heartbeatThreshold / 1000
        );

    }

}


/* =========================================================
   10. KPI CARDS
========================================================= */

function renderKPIs() {

    const account = state.status?.account || {};

    const stats = state.status?.stats || {};


    setText(
        "kpi-total-wealth",
        formatMoney(account.total_wealth)
    );


    setText(
        "kpi-cash",
        formatMoney(account.cash)
    );


    setText(
        "kpi-invested",
        formatMoney(account.invested)
    );


    setText(
        "kpi-net-pnl",
        formatMoney(account.net_pnl)
    );


    setText(
        "kpi-net-pnl-percent",
        formatPercent(account.net_pnl_pct)
    );


    /* Account figures are the exchange's own (as on the portal), re-read every few seconds */

    const asOf = account.as_of ? formatTime(account.as_of) : null;

    setText(
        "account-source",
        account.source === "exchange"
            ? `EXCHANGE · AS OF ${asOf || "—"}`
            : account.source === "bot"
                ? "BOT ESTIMATE"
                : "SIMULATED"
    );


    /* Orders: the exchange counts the whole account; the session count restarts with the bot */

    const accountOrders = safeNumber(stats.account_orders);

    const accountRejected = safeNumber(stats.account_rejected);

    setText(
        "kpi-orders-sent",
        accountOrders ?? stats.orders_sent
    );

    /* A reset on the exchange wipes the account's orders; this session's count keeps them */

    const resetAt = stats.account_reset_at ? formatTime(stats.account_reset_at) : null;

    setText(
        "kpi-orders-sent-change",
        accountOrders === null
            ? "Since run start"
            : resetAt
                ? `Account total since reset at ${resetAt} · this session: ${stats.orders_sent ?? 0}`
                : `Account total · this session: ${stats.orders_sent ?? 0}`
    );

    showElement("reset-banner", Boolean(resetAt));

    if (resetAt) {

        setText(
            "reset-banner-text",
            `EXCHANGE ACCOUNT RESET AT ${resetAt} · EARLIER ORDERS ARE NO LONGER ON THE ACCOUNT`
        );

    }


    setText(
        "kpi-orders-rejected",
        accountRejected ?? stats.orders_rejected
    );


    const sent = accountOrders ?? safeNumber(stats.orders_sent);

    const rejected = accountRejected ?? safeNumber(stats.orders_rejected);


    let rejectionRate = null;

    if (
        sent !== null &&
        rejected !== null &&
        sent > 0
    ) {

        /* orders sent already include the rejected ones */
        rejectionRate =
            (rejected / sent) * 100;

    }


    setText(
        "kpi-rejection-rate",
        rejectionRate === null
            ? "Rejection rate: —"
            : `Rejection rate: ${rejectionRate.toFixed(2)}%`
    );


    setText(
        "kpi-latency",
        stats.latency_avg_s === undefined || stats.latency_avg_s === null
            ? "—"
            : `${formatNumber(stats.latency_avg_s, 3)} s`
    );


    setText(
        "kpi-uptime",
        formatDuration(state.status?.bot?.uptime_s)
    );


    const pnl = safeNumber(account.net_pnl);

    const pnlElement = $("kpi-net-pnl");

    if (pnlElement) {

        pnlElement.classList.remove(
            "positive",
            "negative"
        );

        if (pnl !== null && pnl !== 0) {

            pnlElement.classList.add(
                pnl > 0
                    ? "positive"
                    : "negative"
            );

        }

    }

}


/* =========================================================
   11. POSITIONS TABLE
========================================================= */

function getHoldingClass(heldSince) {

    if (!heldSince) return "—";

    const start = new Date(heldSince);

    const today = new Date(
        state.status?.sim?.current_date ||
        new Date().toISOString().slice(0, 10)
    );


    if (
        Number.isNaN(start.getTime()) ||
        Number.isNaN(today.getTime())
    ) {

        return "—";

    }


    const days = Math.floor(
        (today - start) / (1000 * 60 * 60 * 24)
    );


    return days > 365
        ? "Long-term"
        : "Short-term";

}


function renderPositions() {

    const tbody = $("positions-table-body");

    if (!tbody) return;


    const positions = [...state.positions];


    if (positions.length === 0) {

        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-state">
                    No open positions
                </td>
            </tr>
        `;

        setText("positions-count", "0 positions");

        return;

    }


    const { key, direction } = state.positionSort;


    positions.sort((a, b) => {

        const first = a[key] ?? "";

        const second = b[key] ?? "";


        if (
            typeof first === "number" &&
            typeof second === "number"
        ) {

            return direction === "asc"
                ? first - second
                : second - first;

        }


        return direction === "asc"
            ? String(first).localeCompare(String(second))
            : String(second).localeCompare(String(first));

    });


    tbody.innerHTML = positions.map(position => {

        const pnl = safeNumber(position.unrealized_pnl);

        const pnlClass =
            pnl === null
                ? ""
                : pnl >= 0
                    ? "positive"
                    : "negative";


        const cap = safeNumber(position.cap_used_pct);


        return `
            <tr>

                <td>
                    <strong>
                        ${escapeHTML(position.ticker || "—")}
                    </strong>
                </td>

                <td>
                    ${formatNumber(position.quantity, 0)}
                </td>

                <td>
                    ${formatMoney(position.last_close)}
                </td>

                <td>
                    ${formatMoney(position.value)}
                </td>

                <td>
                    ${formatMoney(position.avg_price)}
                </td>

                <td class="${pnlClass}">
                    ${pnl === null
                        ? "—"
                        : `${pnl > 0 ? "+" : ""}${formatMoney(pnl)}`
                    }
                </td>

                <td>

                    <div class="cap-progress">

                        <span>
                            ${cap === null
                                ? "—"
                                : `${cap.toFixed(2)}%`
                            }
                        </span>

                        <div class="cap-track">

                            <div
                                class="cap-fill"
                                style="width:${Math.min(
                                    100,
                                    Math.max(0, cap ?? 0)
                                )}%">
                            </div>

                        </div>

                    </div>

                </td>

                <td>
                    ${formatDate(position.held_since)}
                </td>

                <td>
                    ${getHoldingClass(position.held_since)}
                </td>

            </tr>
        `;

    }).join("");


    setText(
        "positions-count",
        `${positions.length} positions`
    );

}


/* =========================================================
   12. ORDERS TABLE
========================================================= */

function renderOrders() {

    const tbody = $("orders-table-body");

    if (!tbody) return;


    if (!state.orders.length) {

        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="empty-state">
                    No orders available
                </td>
            </tr>
        `;

        setText("orders-count", "0 orders");

        return;

    }


    tbody.innerHTML = state.orders.map(order => {

        const status = order.status || "—";

        const statusClass =
            status === "REJECTED"
                ? "rejected"
                : status === "UNCERTAIN"
                    ? "uncertain"
                    : status === "FILLED"
                        ? "filled"
                        : "";


        return `
            <tr class="${statusClass}">

                <td>
                    ${formatTime(order.time)}
                </td>

                <td>
                    ${escapeHTML(order.ticker || "—")}
                </td>

                <td>
                    ${escapeHTML(order.action || "—")}
                </td>

                <td>
                    ${formatNumber(order.quantity, 0)}
                </td>

                <td>
                    ${formatMoney(order.price)}
                </td>

                <td>

                    <span class="order-status ${statusClass}">
                        ${escapeHTML(status)}
                    </span>

                </td>

                <td>
                    ${escapeHTML(order.code || "—")}
                </td>

                <td>
                    ${formatMoney(order.fees)}
                </td>

                <td>
                    ${order.latency_s === undefined
                        ? "—"
                        : `${formatNumber(order.latency_s, 3)} s`
                    }
                </td>

            </tr>
        `;

    }).join("");


    setText(
        "orders-count",
        `${state.orders.length} orders`
    );


    const totalFees = state.orders.reduce(
        (sum, order) => {

            const fee = safeNumber(order.fees);

            return fee === null
                ? sum
                : sum + fee;

        },
        0
    );


    setText(
        "orders-total-fees",
        formatMoney(totalFees)
    );

}


/* =========================================================
   13. ACTIVITY FEED
========================================================= */

function getEventIcon(type) {

    const icons = {

        TICK: "●",

        SIGNAL: "↗",

        ORDER: "⇄",

        RISK_BLOCK: "⊘",

        NEWS: "◉",

        ERROR: "!",

        ACCOUNT_RESET: "↺",

        SYSTEM: "⚙"

    };


    return icons[type] || "•";

}


function renderActivity() {

    const feed = $("activity-feed");

    if (!feed) return;


    if (state.activityPaused) return;


    let events = [...state.events];


    if (state.activeEventFilter !== "ALL") {

        events = events.filter(
            event => event.type === state.activeEventFilter
        );

    }


    if (state.activeTickerFilter !== "ALL") {

        events = events.filter(
            event => event.ticker === state.activeTickerFilter
        );

    }


    events = events.slice(0, CONFIG.maxEvents);


    setText(
        "activity-count",
        `${events.length} events`
    );


    if (!events.length) {

        feed.innerHTML = `
            <div class="empty-state">
                No matching events
            </div>
        `;

        return;

    }


    feed.innerHTML = events.map(event => {

        const type = event.type || "SYSTEM";


        return `

            <details class="activity-row ${escapeHTML(type)}">

                <summary>

                    <span class="activity-icon">
                        ${getEventIcon(type)}
                    </span>

                    <span class="activity-time">
                        ${formatTime(event.time)}
                    </span>

                    <span class="activity-type">
                        ${escapeHTML(type)}
                    </span>

                    <span class="activity-ticker">
                        ${escapeHTML(event.ticker || "—")}
                    </span>

                    <span class="activity-message">
                        ${escapeHTML(event.message || "—")}
                    </span>

                </summary>


                <div class="activity-details">

                    <p>
                        <strong>Simulated Date:</strong>
                        ${escapeHTML(event.simulated_date || "—")}
                    </p>

                    <p>
                        <strong>Reason:</strong>
                        ${escapeHTML(event.reason || "—")}
                    </p>

                    <pre>${escapeHTML(
                        JSON.stringify(event.data ?? {}, null, 2)
                    )}</pre>

                </div>

            </details>

        `;

    }).join("");

}


/* =========================================================
   14. NEWS PANEL
========================================================= */

function renderNews() {

    const container = $("news-list");

    if (!container) return;


    if (!state.news.length) {

        container.innerHTML = `
            <div class="empty-state">
                No news available
            </div>
        `;

        return;

    }


    container.innerHTML = state.news.map(item => {

        const score = safeNumber(item.keyword_score);


        return `

            <article class="news-item">

                <div class="news-header">

                    <span class="news-ticker">
                        ${escapeHTML(item.ticker || "—")}
                    </span>

                    <span class="news-date">
                        ${escapeHTML(item.simulated_date || "—")}
                    </span>

                </div>


                <h3>
                    ${escapeHTML(item.headline || "—")}
                </h3>


                <p class="news-score">

                    Keyword Score:

                    ${score === null
                        ? "—"
                        : `${score > 0 ? "+" : ""}${score}`
                    }

                </p>


                <span class="informational-badge">
                    NOT USED FOR TRADING
                </span>

            </article>

        `;

    }).join("");

}


/* =========================================================
   15. STRATEGY SELECTOR
========================================================= */

function renderStrategies() {

    const selector = $("strategy-selector");

    if (!selector) return;


    const currentStrategy =
        state.status?.bot?.strategy || "sma_band";


    if (!state.strategies.length) {

        selector.innerHTML = `
            <option value="sma_band">
                SMA8 ±1.5%
            </option>
        `;

        return;

    }


    selector.innerHTML = state.strategies.map(strategy => {

        const comingSoon = strategy.available === false;

        return `

            <option
                value="${escapeHTML(strategy.id)}"
                ${strategy.id === currentStrategy ? "selected" : ""}
                ${comingSoon ? "disabled" : ""}>

                ${escapeHTML(strategy.name || strategy.id)}
                ${comingSoon ? " — Coming Soon" : ""}

            </option>

        `;

    }).join("");


    const selected = state.strategies.find(
        strategy => strategy.id === currentStrategy
    );


    setText(
        "strategy-description",
        selected?.description || "—"
    );


    const params = selected?.params;


    setText(
        "strategy-parameters",
        params
            ? JSON.stringify(params, null, 2)
            : "—"
    );


    selector.value = currentStrategy;

}


/* =========================================================
   16. BOT CONTROLS
========================================================= */

function renderControls() {

    const bot = state.status?.bot || {};

    const botState = bot.state || "OFFLINE";


    const isOffline = botState === "OFFLINE";

    const isStopped = botState === "STOPPED";

    const isRunning = botState === "RUNNING";


    const startButton = $("start-trading-button");

    const stopButton = $("stop-trading-button");

    const strategySelector = $("strategy-selector");


    if (startButton) {

        startButton.disabled =
            isOffline ||
            isRunning;

    }


    if (stopButton) {

        stopButton.disabled =
            isOffline ||
            isStopped;

    }


    if (strategySelector) {

        strategySelector.disabled =
            isOffline ||
            !isStopped;

    }


    setText(
        "control-bot-state",
        botState
    );


    setText(
        "control-disabled-reason",
        isOffline
            ? "Controls disabled: bot is offline."
            : isRunning
                ? "Bot is running. Stop it before changing strategy."
                : isStopped
                    ? "Bot is stopped. Ready for configuration."
                    : "—"
    );


    setText(
        "strategy-disabled-reason",
        isOffline
            ? "Strategy selection disabled: bot is offline."
            : !isStopped
                ? "Strategy can only be changed while STOPPED."
                : "Strategy selection available."
    );

}


/* =========================================================
   17. STRATEGY CHANGE
========================================================= */

async function changeStrategy(strategyId) {

    if (!strategyId) return;


    const botState = state.status?.bot?.state;


    if (botState !== "STOPPED") {

        alert(
            "Strategy can only be changed while the bot is STOPPED."
        );

        renderStrategies();

        return;

    }


    const selectedStrategy = state.strategies.find(
        strategy => strategy.id === strategyId
    );


    if (selectedStrategy?.available === false) {

        alert(
            "This strategy is coming soon."
        );

        renderStrategies();

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    strategy: strategyId

                }

            };

        } else {

            result = await apiPost(
                "/control/strategy",
                {
                    id: strategyId
                }
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (result.bot) {

            state.status.bot = result.bot;

        } else if (result.strategy) {

            state.status.bot = {
                ...state.status.bot,
                strategy: result.strategy
            };

        } else {

            throw new Error(
                "Strategy API response did not contain the resulting bot state."
            );

        }


        state.strategyChanged = true;


        showElement(
            "strategy-change-banner",
            true
        );


        renderStrategies();

        renderControls();


    } catch (error) {

        console.error(
            "Strategy change failed:",
            error.message
        );

        alert(
            `Strategy change failed: ${error.message}`
        );

        renderStrategies();

    }

}


/* =========================================================
   18. START TRADING
========================================================= */

async function startTrading() {

    const botState = state.status?.bot?.state;


    if (botState !== "STOPPED") {

        alert(
            "Bot must be STOPPED before starting."
        );

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    state: "RUNNING"

                }

            };

        } else {

            result = await apiPost(
                "/control/start"
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (!result.bot) {

            throw new Error(
                "Start API response did not contain the resulting bot state."
            );

        }


        state.status.bot = result.bot;


        renderHeader();

        renderControls();


    } catch (error) {

        console.error(
            "Start failed:",
            error.message
        );

        alert(
            `Unable to start trading: ${error.message}`
        );

    }

}


/* =========================================================
   19. STOP TRADING
========================================================= */

async function stopTrading() {

    const botState = state.status?.bot?.state;


    if (botState !== "RUNNING") {

        alert(
            "Bot is not currently running."
        );

        return;

    }


    try {

        let result;


        if (CONFIG.mock) {

            result = {

                bot: {

                    ...state.status.bot,

                    state: "STOPPED"

                }

            };

        } else {

            result = await apiPost(
                "/control/stop"
            );

        }


        if (result.error) {

            throw new Error(result.error);

        }


        if (!result.bot) {

            throw new Error(
                "Stop API response did not contain the resulting bot state."
            );

        }


        state.status.bot = result.bot;


        renderHeader();

        renderControls();


    } catch (error) {

        console.error(
            "Stop failed:",
            error.message
        );

        alert(
            `Unable to stop trading: ${error.message}`
        );

    }

}


/* =========================================================
   20. SORTABLE POSITIONS
========================================================= */

function initializePositionSorting() {

    document.querySelectorAll(
        "#positions-table .sort-button"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                const key = button.dataset.sort;


                if (state.positionSort.key === key) {

                    state.positionSort.direction =
                        state.positionSort.direction === "asc"
                            ? "desc"
                            : "asc";

                } else {

                    state.positionSort.key = key;

                    state.positionSort.direction = "asc";

                }


                renderPositions();

            }
        );

    });

}


/* =========================================================
   21. ACTIVITY FILTERS
========================================================= */

function initializeActivityFilters() {

    document.querySelectorAll(
        ".filter-chip"
    ).forEach(button => {

        button.addEventListener(
            "click",
            () => {

                document.querySelectorAll(
                    ".filter-chip"
                ).forEach(chip => {

                    chip.classList.remove("active");

                });


                button.classList.add("active");


                state.activeEventFilter =
                    button.dataset.filter || "ALL";


                renderActivity();

            }
        );

    });


    const tickerFilter = $("activity-ticker-filter");


    if (tickerFilter) {

        tickerFilter.addEventListener(
            "change",
            event => {

                state.activeTickerFilter =
                    event.target.value;


                renderActivity();

            }
        );

    }


    const pauseCheckbox = $("pause-activity-feed");


    if (pauseCheckbox) {

        pauseCheckbox.addEventListener(
            "change",
            event => {

                state.activityPaused =
                    event.target.checked;


                if (!state.activityPaused) {

                    renderActivity();

                }

            }
        );

    }

}


/* =========================================================
   22. TICKER SELECTOR
========================================================= */

function initializeTickerSelector() {

    const selector = $("ticker-selector");

    if (!selector) return;


    selector.addEventListener(
        "change",
        event => {

            state.activeTicker =
                event.target.value;


            renderCharts();

        }
    );

}


/* =========================================================
   23. STRATEGY SELECTOR EVENT
========================================================= */

function initializeStrategySelector() {

    const selector = $("strategy-selector");

    if (!selector) return;


    selector.addEventListener(
        "change",
        event => {

            changeStrategy(
                event.target.value
            );

        }
    );

}


/* =========================================================
   24. CONTROL BUTTON EVENTS
========================================================= */

function initializeControls() {

    const startButton = $("start-trading-button");

    const stopButton = $("stop-trading-button");


    const dialog = $("start-confirmation-dialog");


    const confirmButton = $("confirm-start-button");

    const cancelButton = $("cancel-start-button");


    if (startButton && dialog) {

        startButton.addEventListener(
            "click",
            () => {

                if (
                    state.status?.bot?.state !== "STOPPED"
                ) {

                    return;

                }


                dialog.showModal();

            }
        );

    }


    if (confirmButton && dialog) {

        confirmButton.addEventListener(
            "click",
            async () => {

                dialog.close();

                await startTrading();

            }
        );

    }


    if (cancelButton && dialog) {

        cancelButton.addEventListener(
            "click",
            () => {

                dialog.close();

            }
        );

    }


    if (stopButton) {

        stopButton.addEventListener(
            "click",
            async () => {

                await stopTrading();

            }
        );

    }

}


/* =========================================================
   25. CHARTS
   Drawn with the shared kit in charts.js (window.QCharts):
   light theme, in-place updates, crosshair, reference lines.
========================================================= */

const Q = window.QCharts;

const BAND_PCT = 1.5;


/* Close, SMA8 and band for the dates around a decision, plus fills */

function pointsFor(ticker, limit) {

    const data = state.series[ticker];

    const points = Array.isArray(data?.points) ? data.points : [];

    return limit ? points.slice(-limit) : points;

}


/* =========================================================
   26. PRICE CHART: candles, SMA8 band, fills, volume
========================================================= */

function renderPriceChart() {

    const ticker = state.activeTicker;

    const points = pointsFor(ticker, 120);

    if (!points.length) {

        Q.empty("price-chart", "Waiting for prices...");

        Q.empty("volume-chart", "");

        return;

    }


    const c = Q.colors();

    const labels = points.map(point => point.date);

    const rising = point => (point.close ?? 0) >= (point.open ?? point.close ?? 0);

    const markers = Array.isArray(state.series[ticker]?.markers) ? state.series[ticker].markers : [];

    const fillsOn = action => {
        const byDate = {};
        markers.filter(m => m.action === action).forEach(m => { byDate[m.date] = m; });
        return byDate;
    };

    const buys = fillsOn("BUY");

    const sells = fillsOn("SELL");

    const money = value => Q.inr(value, 2);


    Q.upsert("price-chart", {
        type: "bar",
        data: {
            labels,
            datasets: [
                {
                    type: "line", label: "Upper band", data: points.map(p => p.upper ?? null),
                    borderColor: Q.alpha(c.neutral, 0.7), borderWidth: 1, borderDash: [4, 4],
                    backgroundColor: Q.alpha(c.c1, 0.07), fill: "+1", tension: 0.2, order: 6
                },
                {
                    type: "line", label: "Lower band", data: points.map(p => p.lower ?? null),
                    borderColor: Q.alpha(c.neutral, 0.7), borderWidth: 1, borderDash: [4, 4],
                    fill: false, tension: 0.2, order: 6
                },
                {
                    type: "line", label: "SMA8", data: points.map(p => p.sma8 ?? null),
                    borderColor: c.c2, borderWidth: 2, tension: 0.25, order: 2
                },
                {
                    label: "High–low", data: points.map(p => [p.low, p.high]),
                    backgroundColor: points.map(p => rising(p) ? c.good : c.bad),
                    barThickness: 1.5, borderRadius: 0, order: 4
                },
                {
                    label: "Candle", data: points.map(p => [Math.min(p.open, p.close), Math.max(p.open, p.close)]),
                    backgroundColor: points.map(p => rising(p) ? c.surface : c.bad),
                    borderColor: points.map(p => rising(p) ? c.good : c.bad),
                    borderWidth: 1.25, borderSkipped: false, borderRadius: 1,
                    barPercentage: 0.72, categoryPercentage: 0.9, order: 3
                },
                {
                    type: "line", label: "BUY", data: labels.map(d => buys[d]?.price ?? null),
                    showLine: false, pointStyle: "triangle", pointRadius: 8, pointHoverRadius: 10,
                    backgroundColor: c.good, borderColor: c.surface, borderWidth: 2, order: 0
                },
                {
                    type: "line", label: "SELL", data: labels.map(d => sells[d]?.price ?? null),
                    showLine: false, pointStyle: "triangle", rotation: 180, pointRadius: 8, pointHoverRadius: 10,
                    backgroundColor: c.bad, borderColor: c.surface, borderWidth: 2, order: 0
                }
            ]
        },
        options: Q.axes({
            scales: {
                x: { offset: true, grid: { display: false }, ticks: { maxTicksLimit: 8 } },
                y: { beginAtZero: false, grace: "4%", position: "right", ticks: { callback: v => "₹" + v } }
            },
            plugins: {
                tooltip: {
                    filter: item => item.dataset.label === "Candle",
                    callbacks: {
                        label: item => {
                            const p = points[item.dataIndex];
                            const gap = p.sma8 ? ((p.close / p.sma8) - 1) * 100 : null;
                            return [
                                `Open ${money(p.open)}   Close ${money(p.close)}`,
                                `High ${money(p.high)}   Low ${money(p.low)}`,
                                `SMA8 ${money(p.sma8)}  (close ${gap === null ? "—" : (gap > 0 ? "+" : "") + gap.toFixed(2) + "%"})`
                            ];
                        },
                        afterBody: items => {
                            const date = labels[items[0]?.dataIndex];
                            return [buys[date], sells[date]].filter(Boolean)
                                .map(m => `${m.action} ${m.quantity} @ ${money(m.price)}`);
                        }
                    }
                }
            }
        })
    });


    Q.upsert("volume-chart", {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Volume", data: points.map(p => p.volume ?? null),
                backgroundColor: points.map(p => Q.alpha(rising(p) ? c.good : c.bad, 0.35)),
                borderRadius: 2, barPercentage: 0.72, categoryPercentage: 0.9
            }]
        },
        options: Q.axes({
            scales: {
                x: { offset: true, display: false },
                y: { position: "right", ticks: { maxTicksLimit: 3, callback: v => (v / 1e6).toFixed(1) + "M" } }
            },
            plugins: { tooltip: { callbacks: { label: item => `Volume ${Number(item.raw).toLocaleString("en-IN")}` } } }
        })
    });

}


/* =========================================================
   27. EQUITY CURVE + DRAWDOWN
========================================================= */

function renderEquityChart() {

    const rows = state.equity.filter(row => Q.num(row.total_wealth) !== null);

    if (rows.length < 2) {

        Q.empty("equity-chart", "Equity curve appears after the first few days");

        Q.empty("drawdown-chart", "");

        return;

    }


    const c = Q.colors();

    const labels = rows.map(row => row.date);

    const wealth = rows.map(row => row.total_wealth);

    const start = Q.num(state.status?.account?.initial_capital) ?? wealth[0];

    let peak = -Infinity;

    const drawdown = wealth.map(value => {
        peak = Math.max(peak, value);
        return (value / peak - 1) * 100;
    });

    const last = wealth.at(-1);

    const maxDrawdown = Math.min(...drawdown);


    setText("equity-return-chip", `${last >= start ? "+" : ""}${((last / start - 1) * 100).toFixed(1)}% vs start`);

    setText("equity-dd-chip", `Max drawdown ${maxDrawdown.toFixed(1)}%`);


    Q.upsert("equity-chart", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Total wealth", data: wealth, borderColor: c.c1, borderWidth: 2.25,
                backgroundColor: Q.fade(c.c1, 0.24), fill: "origin", pointHoverBackgroundColor: c.c1,
                pointHoverBorderColor: c.surface
            }]
        },
        options: Q.axes({
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: false, grace: "6%", ticks: { callback: v => Q.inrShort(v) } }
            },
            plugins: {
                qRefLines: { lines: [{ axis: "y", value: start, color: c.subtle, label: `Start ${Q.inrShort(start)}` }] },
                tooltip: {
                    callbacks: {
                        label: item => `Wealth ${Q.inr(item.raw, 0)}`,
                        afterLabel: item => `${item.raw >= start ? "+" : ""}${((item.raw / start - 1) * 100).toFixed(2)}% since start`
                    }
                }
            }
        })
    });


    Q.upsert("drawdown-chart", {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Drawdown", data: drawdown, borderColor: c.bad, borderWidth: 1.5,
                backgroundColor: Q.alpha(c.bad, 0.12), fill: "origin", tension: 0.15
            }]
        },
        options: Q.axes({
            scales: {
                x: { display: false },
                y: { max: 0, ticks: { maxTicksLimit: 3, callback: v => v.toFixed(0) + "%" } }
            },
            plugins: { tooltip: { callbacks: { label: item => `${item.raw.toFixed(2)}% below the peak` } } }
        })
    });

}


/* =========================================================
   28. POSITION SIZE vs THE PER-STOCK CAP
========================================================= */

function renderExposureChart() {

    const account = state.status?.account || {};

    const wealth = Q.num(account.total_wealth);

    const cash = Q.num(account.cash);

    setText(
        "exposure-chip",
        wealth && cash !== null ? `Cash ${(cash / wealth * 100).toFixed(0)}% · Invested ${(100 - cash / wealth * 100).toFixed(0)}%` : "—"
    );


    const rows = state.positions
        .filter(position => Q.num(position.value) !== null)
        .sort((a, b) => b.value - a.value);

    if (!rows.length) {

        Q.empty("exposure-chart", "No open positions — all cash");

        return;

    }


    const c = Q.colors();

    const capOf = position => position.cap_used_pct ? position.value / (position.cap_used_pct / 100) : null;

    const cap = rows.map(capOf).find(value => value) ?? null;


    Q.upsert("exposure-chart", {
        type: "bar",
        data: {
            labels: rows.map(position => position.ticker),
            datasets: [{
                label: "Position value", data: rows.map(position => position.value),
                backgroundColor: c.c1,
                borderRadius: 4, barPercentage: 0.7, categoryPercentage: 0.85
            }]
        },
        options: Q.axes({
            indexAxis: "y",
            interaction: { mode: "nearest", axis: "y", intersect: false },
            scales: {
                x: { beginAtZero: true, suggestedMax: cap ? cap * 1.08 : undefined, ticks: { callback: v => Q.inrShort(v) } },
                y: { grid: { display: false }, ticks: { color: c.text, font: { weight: "600" } } }
            },
            plugins: {
                qCrosshair: false,
                qRefLines: cap ? { lines: [{ axis: "x", value: cap, color: c.bad, label: `Cap ${Q.inrShort(cap)}` }] } : {},
                tooltip: {
                    callbacks: {
                        label: item => {
                            const p = rows[item.dataIndex];
                            return [`Value ${Q.inr(p.value, 0)}  ·  ${p.quantity} shares`,
                                    `Unrealised ${Q.inr(p.unrealized_pnl, 0)}  ·  cap used ${Q.num(p.cap_used_pct)?.toFixed(0) ?? "—"}%`];
                        }
                    }
                }
            }
        })
    });

}


/* =========================================================
   29. LATENCY DISTRIBUTION
========================================================= */

function renderLatencyChart() {

    const stats = state.status?.stats || {};

    const seconds = value => Q.num(value) === null ? "—" : `${formatNumber(value, 3)} s`;

    setText("latency-avg", seconds(stats.latency_avg_s));

    setText("latency-p95", seconds(stats.latency_p95_s));

    setText("latency-max", seconds(stats.latency_max_s));


    const latencies = state.orders.map(order => Q.num(order.latency_s)).filter(value => value !== null);

    if (!latencies.length) {

        Q.empty("latency-chart", "No orders yet");

        return;

    }


    const edges = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1, 2, 3];

    const labels = edges.map((edge, i) => i === edges.length - 1 ? `≥${edge}s` : `${edge}–${edges[i + 1]}s`);

    const counts = edges.map((edge, i) =>
        latencies.filter(v => v >= edge && (i === edges.length - 1 || v < edges[i + 1])).length);

    const c = Q.colors();


    Q.upsert("latency-chart", {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: "Orders", data: counts,
                backgroundColor: edges.map(edge => edge >= 1 ? c.c2 : c.c1),
                borderRadius: 4, barPercentage: 0.86, categoryPercentage: 0.92
            }]
        },
        options: Q.axes({
            scales: {
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { beginAtZero: true, ticks: { precision: 0 } }
            },
            plugins: {
                qCrosshair: false,
                tooltip: {
                    callbacks: {
                        title: items => `Latency ${items[0].label}`,
                        label: item => `${item.raw} of the last ${latencies.length} orders`
                    }
                }
            }
        })
    });

}


/* =========================================================
   30. RISK BLOCKS BY REASON
========================================================= */

function blockReason(reason) {

    const text = String(reason || "Unknown");

    if (text.startsWith("news veto")) return "Skipped: bad news";

    if (text.startsWith("trading stopped")) return "Trading stopped";

    if (text.includes("cap")) return "Position cap";

    if (text.includes("cash")) return "Not enough cash";

    return text.length > 32 ? text.slice(0, 31) + "…" : text;

}


function renderRiskChart() {

    const counts = {};

    state.events
        .filter(event => event.type === "RISK_BLOCK")
        .forEach(event => {
            const reason = blockReason(event.reason);
            counts[reason] = (counts[reason] || 0) + 1;
        });

    const reasons = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

    if (!reasons.length) {

        Q.empty("risk-block-chart", "No orders blocked in the recent events");

        return;

    }


    const c = Q.colors();

    Q.upsert("risk-block-chart", {
        type: "bar",
        data: {
            labels: reasons,
            datasets: [{
                label: "Blocked", data: reasons.map(reason => counts[reason]), backgroundColor: c.c1,
                borderRadius: 4, barPercentage: 0.6, categoryPercentage: 0.85
            }]
        },
        options: Q.axes({
            indexAxis: "y",
            interaction: { mode: "nearest", axis: "y", intersect: false },
            scales: {
                x: { beginAtZero: true, ticks: { precision: 0 } },
                y: { grid: { display: false }, ticks: { color: c.text } }
            },
            plugins: { qCrosshair: false, tooltip: { callbacks: { label: item => `${item.raw} orders not sent` } } }
        })
    });

}


/* =========================================================
   31. DISTANCE FROM TRIGGER (close / SMA8 − 1)
========================================================= */

function renderTriggerHeatmap() {

    const held = new Set(state.positions.map(position => position.ticker));

    const rows = Object.keys(state.series)
        .map(ticker => {
            const latest = pointsFor(ticker).at(-1);
            const close = Q.num(latest?.close);
            const sma = Q.num(latest?.sma8);
            return { ticker, distance: close !== null && sma ? (close / sma - 1) * 100 : null, close, sma };
        })
        .filter(row => row.distance !== null)
        .sort((a, b) => b.distance - a.distance);

    if (!rows.length) {

        Q.empty("trigger-heatmap", "No trigger data yet");

        return;

    }


    const c = Q.colors();

    const zone = d => d >= BAND_PCT ? c.good : d <= -BAND_PCT ? c.bad : c.neutral;

    const next = row => {
        if (row.distance >= BAND_PCT) return held.has(row.ticker) ? "held, above the band" : "buy signal";
        if (row.distance <= -BAND_PCT) return held.has(row.ticker) ? "sell signal" : "below the band, not held";
        return held.has(row.ticker) ? "held, inside the band" : "inside the band";
    };


    Q.upsert("trigger-heatmap", {
        type: "bar",
        data: {
            labels: rows.map(row => held.has(row.ticker) ? `${row.ticker} ●` : row.ticker),
            datasets: [{
                label: "Close vs SMA8", data: rows.map(row => row.distance),
                backgroundColor: rows.map(row => zone(row.distance)),
                borderRadius: 4, barPercentage: 0.66, categoryPercentage: 0.88
            }]
        },
        options: Q.axes({
            indexAxis: "y",
            interaction: { mode: "nearest", axis: "y", intersect: false },
            scales: {
                x: { suggestedMin: -BAND_PCT * 2, suggestedMax: BAND_PCT * 2, ticks: { callback: v => `${v > 0 ? "+" : ""}${v}%` } },
                y: { grid: { display: false }, ticks: { color: c.text, font: { weight: "600" } } }
            },
            plugins: {
                qCrosshair: false,
                qRefLines: {
                    lines: [
                        { axis: "x", value: BAND_PCT, color: c.good, label: `Buy +${BAND_PCT}%` },
                        { axis: "x", value: -BAND_PCT, color: c.bad, label: `Sell −${BAND_PCT}%` },
                        { axis: "x", value: 0, color: c.axis, dash: [] }
                    ]
                },
                tooltip: {
                    callbacks: {
                        title: items => rows[items[0].dataIndex].ticker,
                        label: item => {
                            const row = rows[item.dataIndex];
                            return [`Close ${Q.inr(row.close)}  ·  SMA8 ${Q.inr(row.sma)}`,
                                    `${row.distance > 0 ? "+" : ""}${row.distance.toFixed(2)}% → ${next(row)}`];
                        }
                    }
                }
            }
        })
    });

}


/* KPI sparklines: the last stretch of the equity history, as tiny inline SVGs */

function sparkline(values, color) {

    const clean = values.filter(value => Q.num(value) !== null);

    if (clean.length < 2) return "";

    const min = Math.min(...clean), max = Math.max(...clean), span = max - min || 1;

    const w = 120, h = 34;

    const xy = clean.map((value, i) =>
        `${(i / (clean.length - 1) * w).toFixed(1)},${(h - 2 - (value - min) / span * (h - 4)).toFixed(1)}`);

    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
        <polygon points="0,${h} ${xy.join(" ")} ${w},${h}" fill="${Q.alpha(color, 0.12)}"/>
        <polyline points="${xy.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
    </svg>`;

}


function renderKpiSparklines() {

    const rows = state.equity.slice(-90);

    const c = Q.colors();

    const start = Q.num(state.status?.account?.initial_capital);

    const pairs = [
        ["kpi-wealth-spark", rows.map(row => row.total_wealth), c.c1],
        ["kpi-cash-spark", rows.map(row => row.cash), c.neutral],
        ["kpi-invested-spark", rows.map(row => row.invested), c.c1],
        ["kpi-pnl-spark", rows.map(row => start === null ? null : row.total_wealth - start), c.good]
    ];

    pairs.forEach(([id, values, color]) => {
        const element = $(id);
        if (element) element.innerHTML = sparkline(values, color);
    });

}


/* =========================================================
   32. RENDER ALL CHARTS
========================================================= */

function renderCharts() {

    renderPriceChart();

    renderEquityChart();

    renderExposureChart();

    renderLatencyChart();

    renderRiskChart();

    renderTriggerHeatmap();

    renderKpiSparklines();

}


/* =========================================================
   33. UPDATE FOOTER
========================================================= */

function renderFooter() {

    setText(
        "last-updated",
        `Last updated: ${new Date().toLocaleTimeString("en-IN")}`
    );


    setText(
        "connection-status",
        CONFIG.mock
            ? "Fixture mode"
            : "Connected to bot API"
    );


    showElement(
        "fixture-banner",
        CONFIG.mock
    );

}


/* =========================================================
   34. RENDER DASHBOARD
========================================================= */

function renderDashboard() {

    renderHeader();

    renderKPIs();

    renderPositions();

    renderOrders();

    renderActivity();

    renderNews();

    renderStrategies();

    renderControls();

    renderCharts();

    renderFooter();

}


/* =========================================================
   35. POLLING
========================================================= */

async function pollDashboard() {

    if (state.polling) return;


    state.polling = true;


    try {

        await fetchDashboardData();


        renderDashboard();


    } catch (error) {

        console.error(
            "Dashboard polling failed:",
            error.message
        );


        setText(
            "connection-status",
            "Connection error"
        );


        if (!state.lastSuccessfulFetch) {

            showElement(
                "offline-banner",
                true
            );

        }


    } finally {

        state.polling = false;

    }

}


/* =========================================================
   36. INITIALIZATION
========================================================= */

function initializeDashboard() {

    initializePositionSorting();

    initializeActivityFilters();

    initializeTickerSelector();

    initializeStrategySelector();

    initializeControls();


    pollDashboard();


    setInterval(
        pollDashboard,
        CONFIG.pollInterval
    );

}


/* =========================================================
   37. START APPLICATION
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    initializeDashboard
);
