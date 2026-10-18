// Scanner configuration UI.
//
// Configuration is loaded and saved through the Django API
// (/sdr/api/config/) - the browser no longer connects to the MQTT broker, so
// no broker credentials are exposed and the page is usable while the scanner
// is offline (it then edits the saved config file).
var scanners = {};
// Frequencies/bandwidths are Hz on the wire (the scanner expects Hz) but are
// shown and entered as MHz in the UI.
var MHZ = 1000000;
// The scanner splits every scanned range into ~1 MHz windows and builds a full
// GNU Radio processing chain per window (rtl-sdr-scanner-cpp splitRanges()).
// Too many windows overload the SDR/USB and make auto_sdr overflow or SIGSEGV,
// so warn before saving a configuration that would build a lot of processors.
var MAX_SCAN_PROCESSORS = 35;

var apiUrl = null;
var selectedScannerId = null;
var dirty = false;

$(document).ready(function () {
    apiUrl = $("#config").data("api-url");
    $("#save").click(saveConfig);
    // Track unsaved changes for the "you have unsaved changes" guard. Scanner
    // and device selector radios only change what is being edited, not the
    // configuration itself, so they are ignored.
    $("#config_page").on("change input", "input, select", function () {
        if ($(this).is("[name=scanner_selector],[name=device_selector]")) {
            return;
        }
        dirty = true;
        updateSaveButton();
    });
    window.addEventListener("beforeunload", function (e) {
        if (dirty) {
            e.preventDefault();
            e.returnValue = "";
            return "";
        }
    });
    loadConfig();
});

function getCookie(name) {
    let match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? match.pop() : "";
}

function toast(message, type) {
    let id = "toast_" + Date.now() + Math.floor(Math.random() * 1000);
    let html =
        '<div id="' + id + '" class="toast align-items-center text-bg-' + type + ' border-0" role="alert" aria-live="assertive" aria-atomic="true">' +
        '<div class="d-flex"><div class="toast-body">' + message + "</div>" +
        '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div></div>';
    $("#toast_container").append(html);
    let element = document.getElementById(id);
    let t = new bootstrap.Toast(element, {delay: type === "danger" ? 10000 : 5000});
    t.show();
    element.addEventListener("hidden.bs.toast", function () {
        element.remove();
    });
}

function updateSaveButton() {
    $("#save").prop("disabled", !dirty || selectedScannerId === null);
}

function markClean() {
    dirty = false;
    $("#save").html("Save");
    updateSaveButton();
}

function renderStatusBanner(online) {
    let banner = $("#scanner_status_banner");
    if (online) {
        banner.html('<div class="alert alert-success py-2 mb-0">Scanner online &mdash; showing live settings. Changes apply immediately.</div>');
    } else {
        banner.html('<div class="alert alert-warning py-2 mb-0">Scanner offline &mdash; editing the saved configuration. Changes are stored and applied when the scanner next starts.</div>');
    }
}

function loadConfig() {
    $.ajax({url: apiUrl, dataType: "json"})
        .done(function (data) {
            $("#loading_section").hide();
            renderStatusBanner(data.online);
            let count = 0;
            for (const [scanner_id, scanner] of Object.entries(data.scanners || {})) {
                scanners[scanner_id] = scanner;
                addScanner(scanner, scanner_id);
                count += 1;
                if (selectedScannerId === null) {
                    selectScanner(scanner, scanner_id);
                }
            }
            if (count === 0) {
                $("#scanner_selector").html('<div class="alert alert-warning mb-0">No scanner configuration found.</div>');
            }
            markClean();
        })
        .fail(function () {
            $("#loading_section").hide();
            $("#scanner_selector").html('<div class="alert alert-danger mb-0">Failed to load the configuration.</div>');
        });
}

function saveConfig() {
    let problems = scanRangeProblems();
    if (problems.errors.length > 0) {
        toast("Cannot save, invalid scanned ranges:<br>" + problems.errors.join("<br>"), "danger");
        return;
    }
    if (problems.warnings.length > 0) {
        if (!window.confirm("The configuration has warnings:\n\n" + problems.warnings.join("\n") + "\n\nSave anyway?")) {
            return;
        }
    }
    let scanner = scanners[selectedScannerId];
    if (!scanner) {
        return;
    }
    $("#save").prop("disabled", true).html('<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span role="status"> Saving...</span>');
    fetch(apiUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken")},
        body: JSON.stringify({scanner_id: selectedScannerId, config: scanner}),
    })
        .then(function (response) {
            return response.json().then(function (data) {
                return {ok: response.ok, data: data};
            });
        })
        .then(function (result) {
            if (result.ok && result.data.success) {
                markClean();
                toast("Configuration saved" + (result.data.applied ? " and applied." : " (scanner offline; applied on next start)."), "success");
            } else {
                $("#save").html("Save");
                updateSaveButton();
                toast((result.data.errors || ["Failed to save the configuration."]).join("<br>"), "danger");
            }
        })
        .catch(function () {
            $("#save").html("Save");
            updateSaveButton();
            toast("Failed to save the configuration.", "danger");
        });
}

// Mirrors getRangeSplitSampleRate() from the scanner, used to estimate how many
// processing chains a configuration will create.
function getRangeSplitSampleRate(sampleRate) {
    let roundDown = function (value, step) {
        return Math.floor(value / step) * step;
    };
    if (sampleRate >= 10000000) {
        return roundDown(sampleRate, 1000000);
    }
    else if (sampleRate >= 1000000) {
        return roundDown(sampleRate, 500000);
    }
    else if (sampleRate >= 100000) {
        return roundDown(sampleRate, 100000);
    }
    return sampleRate;
}

// Counts the split ranges the scanner will create for a device, splitting each
// scanned range the way splitRange() does.
function countScanProcessors(device) {
    let split = getRangeSplitSampleRate(device['sample_rate']);
    let result = { total: 0, invalid: [] };
    (device['ranges'] || []).forEach(function (range, index) {
        if (!(range['start'] < range['stop'])) {
            result.invalid.push(index + 1);
        }
        else if (range['stop'] - range['start'] <= split) {
            result.total += 1;
        }
        else {
            result.total += Math.ceil((range['stop'] - range['start']) / split);
        }
    });
    return result;
}

// Returns validation problems for the current scanner configurations. Invalid
// ranges are hard errors; too many windows is a warning the user can override.
function scanRangeProblems() {
    let problems = { errors: [], warnings: [] };
    for (const [scanner_id, scanner] of Object.entries(scanners)) {
        (scanner['devices'] || []).forEach(function (device) {
            let label = scannerLabel(scanner, scanner_id) + " (" + device['serial'] + ")";
            // The alias becomes part of the MQTT topic the scanner publishes on
            // (sdr/spectrogram/<scanner>/<alias>): a slash adds a topic level
            // and spaces used to truncate the device name, both of which
            // silently hid data until the readers were fixed (2026-10-15).
            // The readers cope now - keep new aliases plain ("Blog-V4-HF") so
            // every other path (scheduler, third-party tools) stays simple.
            let alias = String(device['alias'] || "");
            if (alias && (alias.includes("/") || /\s/.test(alias))) {
                problems.warnings.push(label + ": alias '" + alias + "' contains spaces or slashes - prefer e.g. 'Blog-V4-HF'");
            }
            let counts = countScanProcessors(device);
            if (counts.invalid.length > 0) {
                problems.errors.push(label + ": scanned range(s) " + counts.invalid.join(", ") + " have start >= stop");
            }
            if (counts.total > MAX_SCAN_PROCESSORS) {
                problems.warnings.push(label + ": " + counts.total + " scan windows (safe limit " + MAX_SCAN_PROCESSORS + ")");
            }
        });
    }
    return problems;
}

function updateRangeWarning(device) {
    let warning = $("#scan_range_warning");
    if (warning.length === 0) {
        return;
    }
    let counts = countScanProcessors(device);
    let messages = [];
    if (counts.invalid.length > 0) {
        messages.push("Range " + counts.invalid.join(", ") + ": start must be lower than stop.");
    }
    if (counts.total > MAX_SCAN_PROCESSORS) {
        messages.push(counts.total + " scan windows (&gt; " + MAX_SCAN_PROCESSORS + "). Reduce or split the scanned ranges to avoid overloading the SDR.");
    }
    if (messages.length > 0) {
        warning.html(messages.join("<br>")).show();
    }
    else {
        warning.hide();
    }
}

function scannerLabel(scanner, scanner_id) {
    // Identify a scanner by its devices instead of the per-boot raw id.
    let names = (scanner['devices'] || []).map(function (device) {
        return device['alias'] || device['driver'] + "_" + device['serial'];
    }).filter(function (name) { return name; });
    return names.length ? names.join(" + ") : "scanner #" + scanner_id;
}

function addSelectorTab(container, label, badgeHtml, onSelect) {
    // Scanner/device selection as tabs (same format as the settings tabs)
    // instead of small radio dots. The container is a Bootstrap .nav.nav-tabs.
    let item = document.createElement("div");
    $(item).addClass("nav-item");

    let b = document.createElement("button");
    $(b).addClass("nav-link");
    $(b).prop("type", "button");
    $(b).text(label);
    if (badgeHtml) {
        $(b).append(badgeHtml);
    }
    $(b).click(function () {
        $(container).find(".nav-link").removeClass("active");
        $(b).addClass("active");
        onSelect();
    });

    $(item).append(b);
    $(container).append(item);
    return b;
}

function addScanner(scanner, scanner_id) {
    let b = addSelectorTab("#scanner_selector", scannerLabel(scanner, scanner_id), null, function () {
        selectScanner(scanner, scanner_id);
    });
    $(b).attr("data-scanner-id", scanner_id);
}

function selectScanner(scanner, scanner_id) {
    selectedScannerId = scanner_id;
    $("#scanner_selector").find(".nav-link").removeClass("active");
    $("#scanner_selector").find("[data-scanner-id='" + scanner_id + "']").addClass("active");
    updateInput(scanner, '#transmission_tunning_step', ['recording', 'step']);
    updateInput(scanner, '#transmission_max_noise_time_ms', ['recording', 'max_noise_time_ms']);
    updateInput(scanner, "#transmission_min_time_ms", ['recording', 'min_time_ms']);
    updateInput(scanner, "#transmission_sample_rate", ['recording', 'min_sample_rate']);
    updateInput(scanner, "#color_log_enabled", ['output', 'color_log_enabled'], 'bool');
    updateInput(scanner, "#console_log_level", ['output', 'console_log_level'], 'string');
    updateInput(scanner, "#file_log_level", ['output', 'file_log_level'], 'string');
    updateInput(scanner, "#workers", ['workers']);
    updateInput(scanner, '#latitude', ['position', 'latitude'], 'string');
    updateInput(scanner, '#longitude', ['position', 'longitude'], 'string');
    updateInput(scanner, '#altitude', ['position', 'altitude']);

    $("#device_selector").empty();
    $("#ignored_frequencies").find("tr:gt(0)").remove();
    let devices = scanner['devices'] || [];
    devices.forEach(function (device) {
        addDevice(scanner, device);
    });
    if (devices.length > 0) {
        selectDevice(scanner, devices[0]);
    }
    (scanner['ignored_frequencies'] || []).forEach(function (range) {
        addIgnoredFrequency(scanner['ignored_frequencies'], range);
    });
    $("#new_ignored_frequency").unbind("click");
    $("#new_ignored_frequency").click(function () {
        scanner['ignored_frequencies'].push({ 'frequency': 0, 'bandwidth': 0 });
        let range = scanner['ignored_frequencies'][scanner['ignored_frequencies'].length - 1];
        addIgnoredFrequency(scanner['ignored_frequencies'], range);
    });
    updateSaveButton();
}

function addDevice(scanner, device) {
    let name = (device["driver"] ? device["driver"] + " - " : "") + device["serial"];
    if (device["alias"]) {
        name += " (" + device["alias"] + ")";
    }
    let badge = device['connected']
        ? '<span class="badge bg-success ms-2">connected</span>'
        : '<span class="badge bg-secondary ms-2">not connected</span>';
    let b = addSelectorTab("#device_selector", name, badge, function () {
        selectDevice(scanner, device);
    });
    $(b).attr("data-device-serial", device["serial"]);
}

function setValue(element, keys, value) {
    let current = element;
    for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        if (!(key in current) || typeof current[key] !== 'object' || current[key] === null) {
            current[key] = {};
        }
        current = current[key];
    }
    current[keys[keys.length - 1]] = value;
}

function updateInput(element, element_id, keys, type = 'integer') {
    let value = element;
    keys.forEach(function (key) {
        value = (value === null || value === undefined) ? value : value[key];
    });
    $(element_id).val(value);
    // Rebind instead of adding a handler: this is called every time a scanner or
    // device is selected, and stacking handlers made changes fire repeatedly.
    $(element_id).off("change").on("change", function () {
        setValue(element, keys, parseValue($(this).val(), type));
    });
}

function addIgnoredFrequency(ranges, range) {
    let tr = document.createElement("tr");
    $(tr).append(createInput(range['frequency'], function (value) {
        range['frequency'] = value;
    }, 'float', MHZ));
    $(tr).append(createInput(range['bandwidth'], function (value) {
        range['bandwidth'] = value;
    }, 'float', MHZ));
    $(tr).append(createButton("Delete", function () {
        let index = Array.prototype.indexOf.call($(tr).parent().children(), tr) - 1;
        ranges.splice(index, 1);
        tr.remove();
    }));
    $("#ignored_frequencies").append(tr);
}

function selectDevice(scanner, device) {
    $("#device_selector").find(".nav-link").removeClass("active");
    $("#device_selector").find("[data-device-serial='" + device["serial"] + "']").addClass("active");
    // The device section is always available in the "SDR device settings" tab;
    // the badge already communicates connection state.
    let setInputsEnabled = function (enabled) {
        if (enabled)
            $("#device_settings").show();
        else
            $("#device_settings").hide();
    }

    $("#device_enabled").prop("checked", device["enabled"]);
    $("#device_enabled").unbind("click");
    $("#device_enabled").click(function () {
        device['enabled'] = $(this).is(':checked');
        setInputsEnabled($(this).is(':checked'));
    });

    $("#device_sample_rate").unbind("change");
    $("#device_sample_rate").empty();
    (device['sample_rates'] || [device['sample_rate']]).forEach(function (sample_rate) {
        $("#device_sample_rate").append(new Option(sample_rate, sample_rate));
    });
    $("#device_sample_rate").val(device['sample_rate']);
    $("#device_sample_rate").change(function () {
        device['sample_rate'] = parseInt($(this).val());
    });

    $("#devices").find("tr:gt(0)").remove();
    $("#satellites").find("tr:gt(1)").remove();
    $("#gains").find("tr:gt(0)").remove();
    $("#crontab").find("tr:gt(1)").remove();

    (device['ranges'] || []).forEach(function (range) {
        addScannedFrequency(device, range);
    });
    updateRangeWarning(device);
    (device['satellites'] || []).forEach(function (satellite) {
        addSatellite(device['satellites'], satellite);
    });
    (device['gains'] || []).forEach(function (gain) {
        addGain(gain);
    });
    (device['crontabs'] || []).forEach(function (crontab) {
        addCrontab(device['crontabs'], crontab);
    });

    $("#new_scanned_frequency").unbind("click");
    $("#new_scanned_frequency").click(function () {
        device['ranges'].push({ 'start': 0, 'stop': 0 });
        let range = device['ranges'][device['ranges'].length - 1];
        addScannedFrequency(device, range);
        updateRangeWarning(device);
    });

    $("#new_satellite").unbind("click");
    $("#new_satellite").click(function () {
        device['satellites'].push({ 'id': 0, 'name': '', frequency: 0, bandwidth: 0, modulation: '' });
        let satellite = device['satellites'][device['satellites'].length - 1];
        addSatellite(device['satellites'], satellite);
    });
    $("#preview_satellites").unbind("click");
    $("#preview_satellites").click(function () {
        previewSatellites(scanner, device);
    });

    $("#new_crontab").unbind("click");
    $("#new_crontab").click(function () {
        device['crontabs'].push({ 'name': '', 'expression': '0 0 * * *', duration: 60, frequency: 0, bandwidth: 0, modulation: '' });
        let crontab = device['crontabs'][device['crontabs'].length - 1];
        addCrontab(device['crontabs'], crontab);
    });

    updateInput(device, '#start_recording_level', ['start_recording_level']);
    updateInput(device, '#stop_recording_level', ['stop_recording_level']);
    setInputsEnabled(device["enabled"]);
}

function addScannedFrequency(device, range) {
    let tr = document.createElement("tr");
    $(tr).append(createInput(range['start'], function (value) {
        range['start'] = value;
        updateRangeWarning(device);
    }, 'float', MHZ));
    $(tr).append(createInput(range['stop'], function (value) {
        range['stop'] = value;
        updateRangeWarning(device);
    }, 'float', MHZ));
    $(tr).append(createButton("Delete", function () {
        let index = Array.prototype.indexOf.call($(tr).parent().children(), tr) - 1;
        device['ranges'].splice(index, 1);
        tr.remove();
        updateRangeWarning(device);
    }));
    $("#devices").append(tr);
}

function addSatellite(satellites, satellite) {
    let tr = document.createElement("tr");
    $(tr).append(createInput(satellite['id'], function (value) {
        satellite['id'] = value;
    }));
    $(tr).append(createInput(satellite['name'], function (value) {
        satellite['name'] = value;
    }, "string"));
    $(tr).append(createInput(satellite['frequency'], function (value) {
        satellite['frequency'] = value;
    }, 'float', MHZ));
    $(tr).append(createInput(satellite['bandwidth'], function (value) {
        satellite['bandwidth'] = value;
    }, 'float', MHZ));
    $(tr).append(createInputSelect(satellite['modulation'], function (value) {
        satellite['modulation'] = value;
    }, "", ["AM", "FM", "Other"], "string"));
    $(tr).append(createButton("Delete", function () {
        let index = Array.prototype.indexOf.call($(tr).parent().children(), tr) - 1;
        index -= 1; // because help
        satellites.splice(index, 1);
        tr.remove();
    }));
    $("#satellites").append(tr);
}

function addGain(gain) {
    let tr = document.createElement("tr");
    $(tr).append(createLabel(gain["name"]));
    $(tr).append(createInput(gain["value"], function (value) {
        gain['value'] = value;
    }, 'float'));
    $(tr).append(createLabel(gain["min"]));
    $(tr).append(createLabel(gain["max"]));
    $(tr).append(createLabel(gain["step"]));
    $("#gains").append(tr);
}

function addCrontab(objects, object) {
    let tr = document.createElement("tr");
    $(tr).append(createInput(object['name'], function (value) {
        object['name'] = value;
    }, "string"));
    $(tr).append(createInput(object['expression'], function (value) {
        object['expression'] = value;
    }, "string"));
    $(tr).append(createInput(object['duration'], function (value) {
        object['duration'] = value;
    }, "integer"));
    $(tr).append(createInput(object['frequency'], function (value) {
        object['frequency'] = value;
    }, 'float', MHZ));
    $(tr).append(createInput(object['bandwidth'], function (value) {
        object['bandwidth'] = value;
    }, 'float', MHZ));
    $(tr).append(createInputSelect(object['modulation'], function (value) {
        object['modulation'] = value;
    }, "", ["AM", "FM", "Other"], "string"));
    $(tr).append(createButton("Delete", function () {
        let index = Array.prototype.indexOf.call($(tr).parent().children(), tr) - 1;
        index -= 1; // because help
        objects.splice(index, 1);
        tr.remove();
    }));
    $("#crontab").append(tr);
}

function createLabel(value) {
    let td = document.createElement("td");
    td.append(value);
    return td;
}

function createInput(value, callback, type = 'integer', scale = 1) {
    let td = document.createElement("td");
    let i = document.createElement("input");
    $(i).addClass("form-control");
    if (type !== 'string') {
        $(i).attr("type", "number");
        $(i).attr("step", "any");
    }
    if (scale !== 1 && value !== null && value !== undefined && value !== "") {
        $(i).val(parseFloat(value) / scale);
    } else {
        $(i).val(value);
    }
    $(i).change(function () {
        let parsed = parseValue($(this).val(), type);
        callback(scale === 1 ? parsed : parsed * scale);
    });
    td.append(i);
    return td;
}

function createInputSelect(value, callback, label, options, type = 'integer') {
    let td = document.createElement("td");
    let i = document.createElement("select");
    let labelOption = document.createElement("option");
    $(labelOption).html(label);
    $(labelOption).attr('selected', '');
    $(labelOption).attr('disabled', '');
    $(labelOption).attr('hidden', '');
    i.append(labelOption);
    options.forEach(function (option) {
        let o = document.createElement("option");
        $(o).html(option);
        $(o).val(option);
        i.append(o);
    });
    $(i).val(value);
    $(i).addClass("form-select");
    $(i).addClass("form-control");
    $(i).change(function () {
        callback(parseValue($(this).val(), type));
    });
    td.append(i);
    return td;
}

function createButton(value, callback) {
    let td = document.createElement("td");
    let b = document.createElement("button");
    $(b).addClass("btn");
    $(b).addClass("btn-danger");
    $(b).attr("type", "button");
    $(b).append(value);
    $(b).click(callback);
    td.append(b)
    return td;
}

function previewSatellites(scanner, device) {
    let satellites = $.map(device['satellites'], function (value) {
        return value['id'] + ";" + value['name'];
    });
    $.ajax({
        dataType: "html",
        data: {
            "latitude": scanner['position']['latitude'],
            "longitude": scanner['position']['longitude'],
            "altitude": scanner['position']['altitude'],
            "satellites": satellites.join(","),
        },
        url: "/sdr/satellites/",
        success: function (data) {
            $("#preview_flights_content").html(data);
            $('#preview_flights').modal('show');
        }
    });
}
