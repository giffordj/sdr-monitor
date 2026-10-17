// SDR Monitor - in-panel shortwave radio (Hallicrafters S-120 inspired face).
// Controls the live receiver via /sdr/api/radio/ and plays the MP3 stream.
var radioApi = null;
var radioStream = null;
var radioScannerApi = null;
var radioCsrf = "";
var radioPlaying = false;
var radioRecord = false;
var tuneTimer = null;

// Below ~24 MHz the RTL-SDR needs direct sampling (HF). An HF-capable dongle
// (e.g. RTL-SDR Blog V4) covers MW/shortwave; the Nooelec SMArt v5 does not.
var MIN_HZ = 500000;
var MAX_HZ = 1700000000;

// The first four entries are the S-120's dial bands (drawn on the slide-rule
// dial); the rest live in the modern band selector.
var BANDS = [
    {label: "1 - AM broadcast (MW)", dial: 1, min: 530000, max: 1700000, freq: 1000000, mode: "AM"},
    {label: "2 - Shortwave 1.6-4.8", dial: 2, min: 1600000, max: 4800000, freq: 3330000, mode: "AM"},
    {label: "3 - Shortwave 4.8-11", dial: 3, min: 4800000, max: 11000000, freq: 7850000, mode: "AM"},
    {label: "4 - Shortwave 11-30", dial: 4, min: 11000000, max: 30000000, freq: 15000000, mode: "AM"},
    {label: "FM broadcast", min: 88000000, max: 108000000, freq: 101100000, mode: "WFM"},
    {label: "Airband", min: 118000000, max: 137000000, freq: 121500000, mode: "AM"},
    {label: "2m ham", min: 144000000, max: 148000000, freq: 146520000, mode: "FM"},
    {label: "NOAA weather", min: 162400000, max: 162550000, freq: 162550000, mode: "FM"},
    {label: "70cm ham", min: 420000000, max: 450000000, freq: 446000000, mode: "FM"},
    {label: "Public safety", min: 450000000, max: 470000000, freq: 460000000, mode: "FM"},
];

// Decorative dial markings (real shortwave landmarks, like the S-120's cities).
var DIAL_MARKERS = {
    1: [[909000, "London"], [1180000, "Havana"], [1386000, "Moscow"], [1530000, "Vatican"]],
    2: [[1800000, "Police"], [2500000, "Government"], [3330000, "CHU"], [3900000, "Aviation"]],
    3: [[5000000, "WWV"], [5885000, "Vatican City"], [6100000, "Havana"], [7250000, "Moscow"], [7850000, "CHU"], [9410000, "London"]],
    4: [[12030000, "Moscow"], [13800000, "Tokyo"], [14670000, "CHU"], [15000000, "WWV"], [15365000, "London"], [20000000, "WWV"]],
};

var BFO_MODES = ["AM", "USB", "LSB"];

// base = frequency set with the TUNING knob, fine = BAND SPREAD offset (Hz);
// the received frequency is base + fine, like the real bandspread control.
var current = {band: 0, base: BANDS[0].freq, freq: BANDS[0].freq, mode: BANDS[0].mode, fine: 0, volume: 0.8};
var radioDevices = [];
var radioDeviceChosen = false;
var radioScannerRunning = false;

$(document).ready(function () {
    radioApi = $("#radio").data("api-url");
    radioStream = $("#radio").data("stream-url");
    radioScannerApi = $("#radio").data("scanner-url");
    radioCsrf = getCookie("csrftoken");

    BANDS.forEach(function (band, index) {
        $("#radio_band").append(new Option(band.label, index));
    });
    buildDial();

    $("#radio_band").change(function () { applyBand(parseInt($(this).val())); });
    $("#radio_mode").change(function () {
        current.mode = $(this).val();
        $("#radio_mode_label").text(current.mode);
        $("#knob_bfo_val").text(current.mode);
        if (radioPlaying) tuneRemote();
    });
    $("#radio_gain").on("input", function () {
        let gain = parseFloat($(this).val());
        $("#radio_gain_val").text(gain > 0 ? gain + " dB" : "Auto");
        if (radioPlaying) tuneRemote();
    });
    $("#radio_freq_unit").change(function () { renderFreqInput(current.freq); });
    $("#radio_up").click(function () { setBase(current.base + stepHz(), true); });
    $("#radio_down").click(function () { setBase(current.base - stepHz(), true); });
    $("#radio_freq_go").click(gotoFreq);
    $("#radio_freq_input").on("keydown", function (e) {
        if (e.key === "Enter") {
            e.preventDefault();
            gotoFreq();
        }
    });
    $("#radio_record").click(function () { toggleRecord(); });
    $("#radio_scanner_toggle").click(function () { scannerToggle(); });

    // radio dongle selector: switching while listening restarts the receiver
    $("#radio_device").change(function () {
        radioDeviceChosen = true;
        if (radioPlaying) {
            stopRadio().always(function () { setTimeout(startRadio, 500); });
        }
    });

    // band selector buttons (1-4)
    $("#radio_bandsel button").click(function () { applyBand(parseInt($(this).data("band"))); });

    // receive / standby rocker
    $("#radio_receive").click(function () { radioPlaying ? stopRadio() : startRadio(); });
    $("#radio_receive").on("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            radioPlaying ? stopRadio() : startRadio();
        }
    });

    // knobs: drag vertically, wheel, arrow keys; double-click resets where useful
    bindKnob(document.getElementById("knob_tune"), function (units) {
        let band = BANDS[current.band];
        let perUnit = (band.max - band.min) / 400;
        setBase(current.base + units * perUnit, true);
    }, null, stepHz());
    bindKnob(document.getElementById("knob_volume"), function (units) {
        setVolume(current.volume + units * 0.02);
    }, function () { setVolume(0.8); }, 0.02);
    bindKnob(document.getElementById("knob_spread"), function (units) {
        setFine(current.fine + units * 150);
    }, function () { setFine(0); }, 500);
    bindKnob(document.getElementById("knob_bfo"), function () { cycleMode(); }, null, 0, true);

    // band spread strip: drag to trim the fine offset
    bindStrip(document.getElementById("radio_spread"));

    $("#radio_gain_val").text("Auto");
    setVolume(current.volume);
    applyBand(0);
    handleQuery();
    updateReceiveUI();
    statusPoll();
});

function getCookie(name) {
    let match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
}

function toast(message, type) {
    let id = "rt_" + Date.now();
    let html = '<div id="' + id + '" class="toast align-items-center text-bg-' + type + ' border-0" role="alert">' +
        '<div class="d-flex"><div class="toast-body">' + message + '</div>' +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>';
    $("#radio_toast").append(html);
    let el = document.getElementById(id);
    new bootstrap.Toast(el, {delay: 5000}).show();
    el.addEventListener("hidden.bs.toast", function () { el.remove(); });
}

// --- dial -----------------------------------------------------------------

function dialFrequencyLabel(hz) {
    return hz >= 1000000 ? (hz / 1e6).toFixed(hz >= 10000000 ? 0 : 1) : (hz / 1e3).toFixed(0);
}

function buildDial() {
    for (let dial = 1; dial <= 4; dial++) {
        let band = BANDS.filter(function (b) { return b.dial === dial; })[0];
        let track = $("#dial_track_" + dial);
        if (!band || !track.length) {
            continue;
        }
        for (let i = 0; i <= 6; i++) {
            let hz = band.min + (band.max - band.min) * i / 6;
            $("<span>" + dialFrequencyLabel(hz) + "</span>")
                .addClass("tick-label")
                .css("left", (i / 6 * 100) + "%")
                .appendTo(track);
        }
        (DIAL_MARKERS[dial] || []).forEach(function (marker) {
            let hz = marker[0], name = marker[1];
            if (hz < band.min || hz > band.max) {
                return;
            }
            $("<span>" + name + "</span>")
                .addClass("station")
                .css("left", ((hz - band.min) / (band.max - band.min) * 100) + "%")
                .appendTo(track);
        });
    }
}

// --- tuning model ---------------------------------------------------------

function bandForFreq(hz) {
    for (let i = 0; i < BANDS.length; i++) {
        if (hz >= BANDS[i].min && hz <= BANDS[i].max) {
            return i;
        }
    }
    return -1;
}

function applyBand(index, remote) {
    if (!BANDS[index]) {
        return;
    }
    current.band = index;
    let band = BANDS[index];
    $("#radio_band").val(index);
    $("#radio_mode").val(band.mode);
    current.mode = band.mode;
    $("#radio_mode_label").text(band.mode);
    $("#knob_bfo_val").text(band.mode);
    $("#radio_bandsel button").removeClass("on");
    if (band.dial) {
        $("#radio_bandsel button[data-band=" + (band.dial - 1) + "]").addClass("on");
    } else {
        $("#radio_bandsel button").removeClass("on");
    }
    current.fine = 0;
    current.base = band.freq;
    renderFreq();
    if (remote !== false && radioPlaying) {
        tuneRemote();
    }
}

function stepHz() {
    if (current.mode === "WFM" || current.mode === "FM") {
        return 100000;
    }
    return current.freq < 30000000 ? 1000 : 12500;
}

function setBase(hz, remote) {
    let band = BANDS[current.band] || {min: MIN_HZ, max: MAX_HZ};
    current.base = Math.round(Math.max(band.min, Math.min(band.max, hz)));
    renderFreq();
    if (remote && radioPlaying) {
        tuneRemote();
    }
}

function setFine(hz) {
    current.fine = Math.round(Math.max(-10000, Math.min(10000, hz)));
    renderFreq();
    if (radioPlaying) {
        tuneRemote();
    }
}

function setVolume(value) {
    current.volume = Math.max(0, Math.min(1, value));
    let audio = document.getElementById("radio_audio");
    if (audio) {
        audio.volume = current.volume;
    }
    $("#knob_volume_val").text(Math.round(current.volume * 100) + "%");
    setKnobAngle("knob_volume", -135 + current.volume * 270);
}

function cycleMode() {
    let index = (BFO_MODES.indexOf(current.mode) + 1) % BFO_MODES.length;
    current.mode = BFO_MODES[index];
    $("#radio_mode").val(current.mode);
    $("#radio_mode_label").text(current.mode);
    $("#knob_bfo_val").text(current.mode);
    setKnobAngle("knob_bfo", -135 + index / (BFO_MODES.length - 1) * 270);
    if (radioPlaying) {
        tuneRemote();
        toast("B.F.O. " + current.mode, "secondary");
    }
}

function renderFreq() {
    let effective = Math.round(Math.max(MIN_HZ, Math.min(MAX_HZ, current.base + current.fine)));
    current.freq = effective;

    if (effective < 30000000) {
        $("#radio_readout").text((effective / 1000).toFixed(1));
        $("#radio_readout_unit").text("kHz");
    } else {
        $("#radio_readout").text((effective / 1e6).toFixed(4));
        $("#radio_readout_unit").text("MHz");
    }
    renderFreqInput(effective);

    // band spread strip + label
    $("#radio_spread_cursor").css("left", (50 + current.fine / 10000 * 50) + "%");
    $("#radio_spread_label").text(
        current.fine === 0 ? "fine tune" :
            "fine " + (current.fine > 0 ? "+" : "") + (current.fine / 1000).toFixed(2) + " kHz"
    );
    $("#knob_spread_val").text((current.fine > 0 ? "+" : "") + current.fine + " Hz");
    setKnobAngle("knob_spread", -135 + ((current.fine / 10000) + 1) * 135);

    // dial chips + row highlight
    for (let dial = 1; dial <= 4; dial++) {
        let band = BANDS.filter(function (b) { return b.dial === dial; })[0];
        let row = $("#dial_row_" + dial);
        row.removeClass("active");
        if (!band) {
            continue;
        }
        let inBand = effective >= band.min && effective <= band.max;
        if (inBand && BANDS[current.band].dial === dial) {
            row.addClass("active");
            $("#dial_chip_" + dial)
                .text((effective / 1e6).toFixed(4))
                .css("left", ((effective - band.min) / (band.max - band.min) * 100) + "%");
        }
    }

    // tuning knob + value
    let band = BANDS[current.band];
    let pct = (current.base - band.min) / (band.max - band.min);
    setKnobAngle("knob_tune", -135 + Math.max(0, Math.min(1, pct)) * 270);
    $("#knob_tune_val").text(current.base >= 1e6 ? (current.base / 1e6).toFixed(3) + " MHz" : (current.base / 1e3).toFixed(0) + " kHz");
}

function setKnobAngle(id, degrees) {
    let el = document.getElementById(id);
    if (el) {
        el.style.setProperty("--angle", degrees + "deg");
    }
}

function tuneRemote() {
    clearTimeout(tuneTimer);
    tuneTimer = setTimeout(function () {
        api("tune", {mode: current.mode, frequency: current.freq, gain: parseFloat($("#radio_gain").val())});
    }, 300);
}

function api(action, extra) {
    return $.ajax({
        url: radioApi,
        type: "POST",
        contentType: "application/json",
        headers: {"X-CSRFToken": radioCsrf},
        data: JSON.stringify(Object.assign({action: action}, extra || {})),
    });
}

function unitMult() {
    return {Hz: 1, kHz: 1000, MHz: 1000000}[$("#radio_freq_unit").val()] || 1000;
}

function renderFreqInput(hz) {
    let unit = $("#radio_freq_unit").val();
    let value;
    if (unit === "MHz") {
        value = (hz / 1e6).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
    } else if (unit === "kHz") {
        value = (hz / 1e3).toFixed(1).replace(/\.0$/, "");
    } else {
        value = String(hz);
    }
    $("#radio_freq_input").val(value);
}

function gotoFreq() {
    let value = parseFloat($("#radio_freq_input").val());
    if (isNaN(value)) {
        toast("Enter a frequency.", "warning");
        return;
    }
    let hz = Math.round(value * unitMult());
    let band = bandForFreq(hz);
    if (band >= 0) {
        applyBand(band, false);
        setBase(hz, true);
    } else {
        toast("Outside the tunable range (0.5 MHz - 1700 MHz).", "warning");
    }
}

// --- knobs ----------------------------------------------------------------

function bindKnob(el, onDelta, onReset, step, clickOnly) {
    if (!el) {
        return;
    }
    let dragging = false;
    let lastY = 0;
    el.addEventListener("pointerdown", function (e) {
        dragging = true;
        lastY = e.clientY;
        el.setPointerCapture(e.pointerId);
        e.preventDefault();
    });
    el.addEventListener("pointermove", function (e) {
        if (!dragging || clickOnly) {
            return;
        }
        let dy = lastY - e.clientY;
        if (dy) {
            lastY = e.clientY;
            onDelta(dy);
        }
    });
    el.addEventListener("pointerup", function (e) {
        dragging = false;
        try {
            el.releasePointerCapture(e.pointerId);
        } catch (err) {}
    });
    el.addEventListener("click", function () {
        if (clickOnly) {
            onDelta(1);
        }
    });
    el.addEventListener("wheel", function (e) {
        e.preventDefault();
        onDelta(e.deltaY < 0 ? 1 : -1);
    }, {passive: false});
    el.addEventListener("keydown", function (e) {
        if (e.key === "ArrowUp" || e.key === "ArrowRight") {
            e.preventDefault();
            onDelta(1);
        } else if (e.key === "ArrowDown" || e.key === "ArrowLeft") {
            e.preventDefault();
            onDelta(-1);
        } else if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (clickOnly) {
                onDelta(1);
            }
        }
    });
    el.addEventListener("dblclick", function () {
        if (onReset) {
            onReset();
        }
    });
}

function bindStrip(el) {
    if (!el) {
        return;
    }
    let dragging = false;
    function applyAt(clientX) {
        let rect = el.getBoundingClientRect();
        let pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        setFine((pct - 0.5) * 2 * 10000);
    }
    el.addEventListener("pointerdown", function (e) {
        dragging = true;
        el.setPointerCapture(e.pointerId);
        applyAt(e.clientX);
        e.preventDefault();
    });
    el.addEventListener("pointermove", function (e) {
        if (dragging) {
            applyAt(e.clientX);
        }
    });
    el.addEventListener("pointerup", function (e) {
        dragging = false;
        try {
            el.releasePointerCapture(e.pointerId);
        } catch (err) {}
    });
    el.addEventListener("dblclick", function () { setFine(0); });
}

// --- receiver control -----------------------------------------------------

function scannerToggle() {
    let on = !radioScannerRunning;
    $("#radio_scanner_toggle").prop("disabled", true);
    $.ajax({
        url: radioScannerApi,
        type: "POST",
        contentType: "application/json",
        headers: {"X-CSRFToken": radioCsrf},
        data: JSON.stringify({action: on ? "start" : "stop"}),
    })
        .done(function (res) {
            renderStatus(res.status || {});
            toast(on ? "Scanner started." : "Scanner stopped.", "success");
        })
        .fail(function (xhr) {
            let message = "Scanner control failed.";
            try {
                message = JSON.parse(xhr.responseText).errors.join(" ");
            } catch (e) {}
            toast(message, "danger");
        })
        .always(function () { $("#radio_scanner_toggle").prop("disabled", false); });
}

function updateReceiveUI() {
    $("#radio_receive").toggleClass("on", radioPlaying).attr("aria-checked", radioPlaying ? "true" : "false");
    $("#radio_receive_label").text(radioPlaying ? "Receive" : "Standby");
}

function startRadio() {
    api("start", {
        mode: current.mode,
        frequency: current.freq,
        gain: parseFloat($("#radio_gain").val()),
        device: $("#radio_device").val() || null,
    })
        .done(function (st) {
            radioPlaying = !!st.active;
            let audio = document.getElementById("radio_audio");
            audio.src = radioStream + "?_=" + Date.now();
            audio.volume = current.volume;
            audio.play().catch(function () { toast("Playback was blocked - press RECEIVE again.", "warning"); });
            $("#radio_record").prop("disabled", false);
            updateReceiveUI();
            renderStatus(st);
        })
        .fail(function () { toast("Could not start the radio.", "danger"); });
}

function stopRadio() {
    return api("stop").done(function (st) {
        radioPlaying = false;
        radioRecord = false;
        let audio = document.getElementById("radio_audio");
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        $("#radio_record").prop("disabled", true).removeClass("btn-danger").addClass("btn-outline-danger").text("Record");
        updateReceiveUI();
        renderStatus(st);
    });
}

function toggleRecord() {
    if (!radioPlaying) {
        return;
    }
    let on = !radioRecord;
    api("record", {on: on}).done(function (st) {
        radioRecord = !!st.record;
        $("#radio_record").toggleClass("btn-danger", radioRecord).toggleClass("btn-outline-danger", !radioRecord);
        $("#radio_record").text(radioRecord ? "Recording..." : "Record");
        toast(radioRecord ? "Recording started." : "Recording saved to transmissions.", "success");
    });
}

function renderStatus(st) {
    if (!st) {
        return;
    }
    $("#radio_scanner").text(st.scanner || "?");
    $("#radio_mode_label").text(st.mode || current.mode);
    radioScannerRunning = (st.scanner === "RUNNING");
    $("#radio_scanner_toggle")
        .text("Scanner: " + (radioScannerRunning ? "on" : "off"))
        .toggleClass("btn-success", radioScannerRunning)
        .toggleClass("btn-outline-secondary", !radioScannerRunning);
    if (st.devices && st.devices.length && !radioDevices.length) {
        radioDevices = st.devices;
        st.devices.forEach(function (device) {
            $("#radio_device").append(new Option(device.label + (device.hf ? " (HF)" : ""), device.serial));
        });
        if (st.device) {
            $("#radio_device").val(st.device);
        }
    }
    if (!radioDeviceChosen && st.device) {
        $("#radio_device").val(st.device);
    }
    if (st.active) {
        $("#radio_status").text(st.record ? "listening - recording" : "listening");
    } else if (!radioPlaying) {
        $("#radio_status").text("idle");
    }
    let pct = Math.max(0, Math.min(1, (st.rms || 0) * 8));
    $("#radio_meter_needle").css("left", (pct * 100) + "%");
}

function statusPoll() {
    $.ajax({url: radioApi}).done(renderStatus).always(function () {
        setTimeout(statusPoll, 1200);
    });
}

function handleQuery() {
    let params = new URLSearchParams(window.location.search);
    let mode = params.get("mode");
    let freq = params.get("f");
    if (mode) {
        mode = mode.toUpperCase();
        if (["WFM", "FM", "AM", "USB", "LSB"].indexOf(mode) >= 0) {
            current.mode = mode;
            $("#radio_mode").val(mode);
            $("#radio_mode_label").text(mode);
            $("#knob_bfo_val").text(mode);
        }
    }
    if (freq) {
        let hz = parseInt(freq, 10);
        if (!isNaN(hz)) {
            let band = bandForFreq(hz);
            if (band >= 0) {
                applyBand(band, false);
                if (mode) {
                    current.mode = mode;
                    $("#radio_mode").val(mode);
                }
                setBase(hz, false);
            }
        }
    }
}
