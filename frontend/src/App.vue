<script setup>
import * as echarts from "echarts";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8001";

const fileInput = ref(null);
const selectedFile = ref(null);
const parsedLog = ref(null);
const selectedCurves = ref([]);
const sampleFiles = ref([]);
const loading = ref(false);
const loadingSample = ref("");
const errorMessage = ref("");
const exportMessage = ref("");
const activeTab = ref("samples");
const intervalStart = ref("");
const intervalStop = ref("");
const chartEl = ref(null);
let chart = null;
const RESISTIVITY_CURVES = new Set(["RESD", "RES", "ILD", "LLD", "RT"]);
const GR_SHALE_THRESHOLD = 75;
const sidebarTabs = [
  { id: "samples", label: "Samples" },
  { id: "view", label: "View" },
  { id: "analysis", label: "Analysis" },
  { id: "guide", label: "Guide" },
];
const glossaryItems = [
  {
    term: "LAS",
    definition: "Log ASCII Standard, a text format for well log measurements sampled by depth.",
  },
  {
    term: "Depth",
    definition: "The vertical index of the log. Curves are plotted against depth instead of time.",
  },
  {
    term: "Gamma ray (GR)",
    definition: "A radioactivity measurement often used to separate cleaner rock from shale-rich rock.",
  },
  {
    term: "Resistivity",
    definition: "Electrical resistance of the formation. Higher values can help screen potential hydrocarbon zones.",
  },
  {
    term: "Sonic (DT)",
    definition: "Travel time of sound through the formation, commonly used for rock and porosity interpretation.",
  },
  {
    term: "SP",
    definition: "Spontaneous potential, a natural voltage curve that can help identify permeable beds.",
  },
  {
    term: "Vshale",
    definition: "Estimated shale volume. Lower values usually mean cleaner intervals in this simple screening view.",
  },
  {
    term: "Net/Gross",
    definition: "The share of the interval counted as cleaner rock compared with the whole interval.",
  },
  {
    term: "Nulls",
    definition: "Missing or placeholder values in the LAS file. High nulls make interpretation less reliable.",
  },
  {
    term: "Clean interval",
    definition: "A continuous depth range where estimated Vshale is below the selected cutoff.",
  },
];
const methodNotes = [
  "Vshale is estimated from gamma ray with Vshale = (GR - GRclean) / (GRshale - GRclean), clipped to 0-1.",
  "GRclean and GRshale use the low and high gamma ray percentiles, which is more stable than using raw min/max values.",
  "Net/Gross counts samples with Vshale at or below 35% as cleaner intervals.",
  "Resistivity curves are plotted on a log scale so low and high values can fit in the same track.",
];
const fallbackPublicDatasets = [
  {
    name: "Kansas Geological Survey LAS Database",
    source: "KGS",
    url: "https://www.kgs.ku.edu/Magellan/Logs/",
    data_type: "Searchable LAS files and bulk downloads",
    best_for: "Expanding the sample gallery with many public wells",
    description:
      "Public Kansas well logs that are useful for testing metadata parsing, curve availability, and batch quality checks.",
    tags: ["LAS", "Kansas", "bulk"],
  },
  {
    name: "USGS Drew Point 1 Well Log",
    source: "USGS",
    url: "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/DrewPt1/LAS/DP1LAS.htm",
    data_type: "Single public LAS well",
    best_for: "Testing a richer file with GR, resistivity, sonic, density, and neutron curves",
    description:
      "A public LAS example with several common petrophysical curves, helpful for validating multi-track visualization.",
    tags: ["LAS", "Alaska", "petrophysics"],
  },
  {
    name: "USGS Appalachian Basin LAS Files",
    source: "USGS",
    url: "https://pubs.usgs.gov/of/2007/1142/",
    data_type: "LAS files from multiple wells",
    best_for: "Comparing wells across one public geology collection",
    description:
      "A public collection of well log LAS files that can be used to test curve naming differences and interval analysis.",
    tags: ["LAS", "basin", "multi-well"],
  },
  {
    name: "Equinor Volve Data Village",
    source: "Equinor",
    url: "https://www.equinor.com/energy/volve-data-sharing",
    data_type: "Large open field dataset",
    best_for: "A future full workflow with public subsurface data",
    description:
      "A large open dataset from the Volve field, useful as a next step for realistic public-data workflows.",
    tags: ["open data", "field data", "workflow"],
  },
];
const fallbackPublicSamples = [
  {
    id: "usgs-drew-point-1",
    name: "Drew Point 1",
    filename: "DP1.LAS",
    source: "USGS NPRA",
    dataset: "USGS Drew Point 1 Well Log",
    size_note: "2.2 MB",
    curves_note: "GR, resistivity, sonic, density, neutron",
  },
  {
    id: "usgs-east-simpson-1",
    name: "East Simpson 1",
    filename: "ES1.LAS",
    source: "USGS NPRA",
    dataset: "USGS Alaska Wildcat Wells",
    size_note: "2.1 MB",
    curves_note: "GR, resistivity, sonic, density, neutron",
  },
  {
    id: "usgs-ikpikpuk-1",
    name: "Ikpikpuk 1",
    filename: "IK1.LAS",
    source: "USGS NPRA",
    dataset: "USGS Alaska Wildcat Wells",
    size_note: "4.3 MB",
    curves_note: "GR, resistivity, sonic, density, neutron",
  },
  {
    id: "usgs-inigok-1",
    name: "Inigok 1",
    filename: "IN1.LAS",
    source: "USGS NPRA",
    dataset: "USGS Alaska Wildcat Wells",
    size_note: "7.0 MB",
    curves_note: "GR, resistivity, sonic, density, neutron",
  },
];
const publicDatasets = ref(fallbackPublicDatasets);
const publicSampleFiles = ref(fallbackPublicSamples);
const loadingDatasets = ref(false);
const loadingPublicSample = ref("");

const curveOptions = computed(() => parsedLog.value?.curves || []);
const wellName = computed(() => parsedLog.value?.well?.WELL?.value || "Untitled well");
const location = computed(() => parsedLog.value?.well?.LOC?.value || "-");
const apiNumber = computed(() => parsedLog.value?.well?.API?.value || "-");
const displayFilename = computed(() =>
  parsedLog.value ? cleanLasFilename(parsedLog.value.filename) : "Upload a Log ASCII Standard file",
);
const qualitySummary = computed(() => parsedLog.value?.quality_summary || null);
const vshaleSummary = computed(() => parsedLog.value?.petrophysics?.vshale || null);
const depthLabel = computed(() => {
  const depth = parsedLog.value?.depth;
  if (!depth) return "Depth";
  return depth.unit ? `${depth.mnemonic} (${depth.unit})` : depth.mnemonic;
});
const qualityCards = computed(() => {
  if (!parsedLog.value) return [];
  const quality = qualitySummary.value;
  const vshale = vshaleSummary.value;
  const depthUnit = quality?.depth_unit || parsedLog.value.depth?.unit || "";
  return [
    ["Rows", formatNumber(parsedLog.value.row_count, 0)],
    ["Curves", formatNumber(quality?.curve_count ?? curveOptions.value.length, 0)],
    [
      "Key curves",
      quality ? `${quality.detected_key_curve_count}/${quality.key_curves.length}` : "-",
    ],
    [
      "Net/Gross",
      vshale?.available ? formatFractionPercent(vshale.net_to_gross) : "No GR",
    ],
    [
      "Net thickness",
      vshale?.available ? formatWithUnit(formatNumber(vshale.net_thickness), depthUnit) : "-",
    ],
  ];
});
const interpretationSummary = computed(() => {
  if (!parsedLog.value) {
    return [
      "No LAS file is loaded yet. Choose one of the sample wells or upload another LAS file to inspect curves by depth.",
      "For broader testing, the public dataset links point to larger well-log collections with different basins, curve names, and data quality patterns.",
    ];
  }

  const quality = qualitySummary.value;
  const vshale = vshaleSummary.value;
  const depthRange = formatDepthRange(parsedLog.value.depth || {}) || "an unknown depth range";
  const measuredCurves =
    quality?.curve_count ?? curveOptions.value.filter((curve) => !curve.synthetic).length;
  const keyCurves = quality?.key_curves || [];
  const detected = keyCurves
    .filter((curve) => curve.present)
    .map((curve) => `${curve.label} (${curve.mnemonic})`);
  const missing = keyCurves.filter((curve) => !curve.present).map((curve) => curve.label);
  const messages = [
    `${wellName.value} covers ${depthRange} with ${formatNumber(parsedLog.value.row_count, 0)} rows and ${formatNumber(measuredCurves, 0)} measured curves.`,
  ];

  if (detected.length) {
    let curveMessage = `Detected key measurements: ${detected.join(", ")}.`;
    if (missing.length) {
      curveMessage += ` Missing: ${missing.join(", ")}.`;
    }
    messages.push(curveMessage);
  } else {
    messages.push("No standard key measurements were detected, so interpretation should start with curve-name review.");
  }

  if (vshale?.available) {
    const netThickness = formatWithUnit(formatNumber(vshale.net_thickness), vshale.depth_unit) || "-";
    messages.push(
      `The gamma ray Vshale screen marks ${formatFractionPercent(vshale.net_to_gross)} of the interval as cleaner rock, about ${netThickness} net thickness at a ${formatFractionPercent(vshale.clean_cutoff)} cutoff.`,
    );
  } else {
    messages.push(`Vshale was not computed: ${vshale?.reason || "gamma ray data is not available."}`);
  }

  if (quality?.warnings?.length) {
    messages.push(`Quality note: ${quality.warnings[0]}`);
  }

  return messages;
});
const metadataRows = computed(() => {
  if (!parsedLog.value) return [];
  const well = parsedLog.value.well || {};
  const params = parsedLog.value.parameters || {};
  const depth = parsedLog.value.depth || {};
  return [
    ["Well", well.WELL?.value],
    ["Operator", well.COMP?.value],
    ["Location", well.LOC?.value],
    ["API / UWI", well.API?.value],
    ["State", well.STAT?.value],
    ["County", well.CNTY?.value],
    ["Depth range", formatDepthRange(depth)],
    ["Rows", parsedLog.value.row_count],
    ["KB elevation", formatWithUnit(params.EKB?.value, params.EKB?.unit)],
    ["Bottom-hole temp", formatWithUnit(params.BHT?.value, params.BHT?.unit)],
    ["Mud filtrate R", formatWithUnit(params.RMF?.value, params.RMF?.unit)],
    ["RMF temp", formatWithUnit(params.RMFT?.value, params.RMFT?.unit)],
    ["Section", params.SECT?.value],
    ["Township", params.TOWN?.value],
    ["Range", params.RANG?.value],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
});
const vshaleRows = computed(() => {
  const summary = vshaleSummary.value;
  if (!summary?.available) return [];
  return [
    ["Source", summary.source_curve],
    ["GR clean / shale", `${formatNumber(summary.gr_clean)} / ${formatNumber(summary.gr_shale)}`],
    ["Avg Vshale", formatFractionPercent(summary.average)],
    ["Clean cutoff", formatFractionPercent(summary.clean_cutoff)],
    ["Clean intervals", summary.clean_interval_count],
  ];
});
const visibleCleanIntervals = computed(() => {
  if (!vshaleSummary.value?.available) return [];
  return vshaleSummary.value.clean_intervals || [];
});
const depthBounds = computed(() => {
  if (!parsedLog.value) return null;
  const depths = validNumbers(parsedLog.value.depth?.values || []);
  if (!depths.length) return null;
  return {
    min: Math.min(...depths),
    max: Math.max(...depths),
    unit: parsedLog.value.depth?.unit || qualitySummary.value?.depth_unit || "",
    step: Number(qualitySummary.value?.depth_step) || estimateDepthStep(depths),
  };
});
const intervalStats = computed(() => {
  if (!parsedLog.value || !depthBounds.value) return null;
  const depthValues = parsedLog.value.depth.values || [];
  const fromInput = Number(intervalStart.value);
  const toInput = Number(intervalStop.value);
  const from = Number.isFinite(fromInput) ? fromInput : depthBounds.value.min;
  const to = Number.isFinite(toInput) ? toInput : depthBounds.value.max;
  const low = Math.min(from, to);
  const high = Math.max(from, to);
  const rowIndexes = [];

  depthValues.forEach((depth, index) => {
    if (typeof depth === "number" && Number.isFinite(depth) && depth >= low && depth <= high) {
      rowIndexes.push(index);
    }
  });

  const step = depthBounds.value.step;
  const grossThickness = rowIndexes.length
    ? intervalThickness(
        depthValues[rowIndexes[0]],
        depthValues[rowIndexes[rowIndexes.length - 1]],
        rowIndexes.length,
        step,
      )
    : 0;
  const vshMnemonic = vshaleSummary.value?.curve_mnemonic || "VSH";
  const vshSeries = parsedLog.value.series?.[vshMnemonic] || [];
  const cutoff = Number(vshaleSummary.value?.clean_cutoff ?? 0.35);
  const cleanIndexes = rowIndexes.filter((index) => {
    const value = vshSeries[index];
    return typeof value === "number" && Number.isFinite(value) && value <= cutoff;
  });
  const cleanIntervals = buildCleanIntervals(cleanIndexes, depthValues, step);
  const netThickness = step
    ? cleanIndexes.length * step
    : cleanIntervals.reduce((total, interval) => total + interval.thickness, 0);
  const netToGross = grossThickness > 0 ? netThickness / grossThickness : null;
  const averages = [
    curveAverageRow("GR", keyCurveMnemonic("gamma_ray"), rowIndexes),
    curveAverageRow("Resistivity", keyCurveMnemonic("resistivity"), rowIndexes),
    curveAverageRow("Sonic", keyCurveMnemonic("sonic"), rowIndexes),
    curveAverageRow("Vshale", vshMnemonic, rowIndexes, true),
  ].filter(Boolean);

  return {
    from: low,
    to: high,
    unit: depthBounds.value.unit,
    rowCount: rowIndexes.length,
    grossThickness,
    netThickness,
    netToGross,
    cleanIntervalCount: cleanIntervals.length,
    cleanIntervals: cleanIntervals.slice(0, 6),
    averages,
  };
});
const intervalRows = computed(() => {
  if (!intervalStats.value) return [];
  return [
    ["Rows", formatNumber(intervalStats.value.rowCount, 0)],
    ["Gross", formatWithUnit(formatNumber(intervalStats.value.grossThickness), intervalStats.value.unit)],
    ["Net", formatWithUnit(formatNumber(intervalStats.value.netThickness), intervalStats.value.unit)],
    ["Net/Gross", formatFractionPercent(intervalStats.value.netToGross)],
    ["Clean intervals", intervalStats.value.cleanIntervalCount],
  ];
});

function formatWithUnit(value, unit) {
  if (value === undefined || value === null || value === "") return null;
  if (value === "-") return value;
  return unit ? `${value} ${unit}` : `${value}`;
}

function formatNumber(value, digits = 3) {
  if (value === undefined || value === null || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return `${value}`;
  return number.toLocaleString(undefined, {
    maximumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value === undefined || value === null || value === "") return "-";
  return `${formatNumber(value, 1)}%`;
}

function formatFractionPercent(value) {
  if (value === undefined || value === null || value === "") return "-";
  return `${formatNumber(Number(value) * 100, 1)}%`;
}

function formatDepthRange(depth) {
  const unit = depth.unit || "";
  const start = depth.start ?? depth.values?.[0];
  const stop = depth.stop ?? depth.values?.[depth.values.length - 1];
  if (start === undefined || stop === undefined) return null;
  return `${start} - ${stop}${unit ? ` ${unit}` : ""}`;
}

function cleanLasFilename(name) {
  return String(name || "").replace(/\s*\(\d+\)(?=\.las$)/i, "");
}

function sampleLabel(sample) {
  return cleanLasFilename(sample.name).replace(/\.las$/i, "");
}

function safeFilename(name) {
  return String(name || "las-export")
    .replace(/\.[^.]+$/, "")
    .replace(/[^A-Za-z0-9_.-]+/g, "_")
    .replace(/^_+|_+$/g, "") || "las-export";
}

function normalizeMnemonic(mnemonic) {
  return String(mnemonic || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function isResistivityCurve(mnemonic) {
  return RESISTIVITY_CURVES.has(normalizeMnemonic(mnemonic));
}

function sanitizeCurveValue(mnemonic, value) {
  if (value === null || value === undefined) return null;
  if (isResistivityCurve(mnemonic) && value <= 0) {
    return 0.01;
  }
  return value;
}

function validNumbers(values) {
  return values.filter((value) => typeof value === "number" && Number.isFinite(value));
}

function estimateDepthStep(values) {
  const diffs = [];
  values.forEach((value, index) => {
    if (index === 0) return;
    const previous = values[index - 1];
    if (typeof previous === "number" && Number.isFinite(previous) && value !== previous) {
      diffs.push(Math.abs(value - previous));
    }
  });
  if (!diffs.length) return null;
  diffs.sort((left, right) => left - right);
  return diffs[Math.floor(diffs.length / 2)];
}

function intervalThickness(from, to, sampleCount, step) {
  if (step) return sampleCount * step;
  return Math.abs(to - from);
}

function keyCurveMnemonic(key) {
  return qualitySummary.value?.key_curves?.find((curve) => curve.key === key)?.mnemonic || null;
}

function curveAverageRow(label, mnemonic, rowIndexes, asFraction = false) {
  if (!mnemonic || !parsedLog.value?.series?.[mnemonic]) return null;
  const curve = curveOptions.value.find((item) => item.mnemonic === mnemonic);
  const values = rowIndexes
    .map((index) => parsedLog.value.series[mnemonic][index])
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  if (!values.length) return null;
  const average = values.reduce((total, value) => total + value, 0) / values.length;
  return {
    label,
    mnemonic,
    value: asFraction ? formatFractionPercent(average) : formatWithUnit(formatNumber(average), curve?.unit),
  };
}

function buildCleanIntervals(indexes, depthValues, step) {
  const intervals = [];
  let active = null;
  indexes.forEach((index, position) => {
    const depth = depthValues[index];
    const previousIndex = indexes[position - 1];
    const isContinuous = position > 0 && previousIndex === index - 1;
    if (!active || !isContinuous) {
      if (active) intervals.push(active);
      active = { from: depth, to: depth, sampleCount: 1 };
    } else {
      active.to = depth;
      active.sampleCount += 1;
    }
  });
  if (active) intervals.push(active);
  return intervals.map((interval) => ({
    ...interval,
    thickness: intervalThickness(interval.from, interval.to, interval.sampleCount, step),
  }));
}

function buildGammaRayBands(depthValues, grValues, xMin, xMax) {
  const bands = [];
  let active = null;
  for (let index = 0; index < grValues.length; index += 1) {
    const depth = depthValues[index];
    const value = grValues[index];
    if (depth === null || value === null) continue;

    const kind = value < GR_SHALE_THRESHOLD ? "clean" : "shale";
    if (!active || active.kind !== kind) {
      if (active) bands.push(active);
      active = { kind, from: depth, to: depth };
    } else {
      active.to = depth;
    }
  }
  if (active) bands.push(active);

  return bands.map((band) => [
    {
      xAxis: xMin,
      yAxis: band.from,
      itemStyle: {
        color: band.kind === "clean" ? "rgba(250, 204, 21, 0.12)" : "rgba(120, 113, 108, 0.10)",
      },
      label: { show: false },
    },
    {
      xAxis: xMax,
      yAxis: band.to,
    },
  ]);
}

function onFileChange(event) {
  const [file] = event.target.files || [];
  selectedFile.value = file || null;
  errorMessage.value = "";
}

async function fetchSamples() {
  try {
    const response = await fetch(`${apiUrl}/api/samples`);
    if (!response.ok) return;
    const payload = await response.json();
    sampleFiles.value = payload.samples || [];
  } catch {
    sampleFiles.value = [];
  }
}

async function fetchPublicDatasets() {
  loadingDatasets.value = true;
  try {
    const response = await fetch(`${apiUrl}/api/public-datasets`);
    if (!response.ok) return;
    const payload = await response.json();
    publicDatasets.value = payload.datasets?.length ? payload.datasets : fallbackPublicDatasets;
  } catch {
    publicDatasets.value = fallbackPublicDatasets;
  } finally {
    loadingDatasets.value = false;
  }
}

async function fetchPublicSamples() {
  try {
    const response = await fetch(`${apiUrl}/api/public-samples`);
    if (!response.ok) return;
    const payload = await response.json();
    publicSampleFiles.value = payload.samples?.length ? payload.samples : fallbackPublicSamples;
  } catch {
    publicSampleFiles.value = fallbackPublicSamples;
  }
}

function defaultSelectedCurves(curves) {
  const selected = [];
  const priority = ["GR", "RESD", "RT", "DT", "VSH"];
  priority.forEach((wanted) => {
    const curve = curves.find((item) => normalizeMnemonic(item.mnemonic) === wanted);
    if (curve && !selected.includes(curve.mnemonic)) {
      selected.push(curve.mnemonic);
    }
  });
  curves.forEach((curve) => {
    if (selected.length >= 4) return;
    if (!selected.includes(curve.mnemonic)) {
      selected.push(curve.mnemonic);
    }
  });
  return selected;
}

async function parseFile() {
  if (!selectedFile.value) {
    errorMessage.value = "Select a .las file first.";
    return;
  }

  const formData = new FormData();
  formData.append("file", selectedFile.value);

  loading.value = true;
  errorMessage.value = "";

  try {
    const response = await fetch(`${apiUrl}/api/parse-las`, {
      method: "POST",
      body: formData,
    });
    const rawText = await response.text();
    const payload = rawText ? JSON.parse(rawText) : {};
    if (!response.ok) {
      throw new Error(payload.detail || "Could not parse LAS file.");
    }
    await applyParsedPayload(payload);
    activeTab.value = "view";
  } catch (error) {
    errorMessage.value = error.message || "Request failed.";
  } finally {
    loading.value = false;
  }
}

async function loadSample(sample) {
  loading.value = true;
  loadingSample.value = sample.name;
  errorMessage.value = "";
  exportMessage.value = "";

  try {
    const response = await fetch(`${apiUrl}/api/samples/${encodeURIComponent(sample.name)}/parse`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Could not load sample LAS file.");
    }
    selectedFile.value = null;
    await applyParsedPayload(payload);
    activeTab.value = "view";
  } catch (error) {
    errorMessage.value = error.message || "Sample request failed.";
  } finally {
    loading.value = false;
    loadingSample.value = "";
  }
}

async function loadPublicSample(sample) {
  loading.value = true;
  loadingPublicSample.value = sample.id;
  errorMessage.value = "";
  exportMessage.value = "";

  try {
    const response = await fetch(`${apiUrl}/api/public-samples/${encodeURIComponent(sample.id)}/parse`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Could not load public LAS file.");
    }
    selectedFile.value = null;
    await applyParsedPayload(payload);
    activeTab.value = "view";
  } catch (error) {
    errorMessage.value = error.message || "Public sample request failed.";
  } finally {
    loading.value = false;
    loadingPublicSample.value = "";
  }
}

async function applyParsedPayload(payload) {
  parsedLog.value = payload;
  selectedCurves.value = defaultSelectedCurves(payload.curves || []);
  resetIntervalRange(payload);
  await nextTick();
  renderChart();
}

function resetIntervalRange(payload = parsedLog.value) {
  if (!payload) return;
  const quality = payload.quality_summary || {};
  const depthValues = payload.depth?.values || [];
  const depths = validNumbers(depthValues);
  intervalStart.value = quality.depth_start ?? (depths.length ? Math.min(...depths) : "");
  intervalStop.value = quality.depth_stop ?? (depths.length ? Math.max(...depths) : "");
}

function zoomToInterval() {
  if (!chart || !intervalStats.value || !parsedLog.value) return;
  const depths = validNumbers(parsedLog.value.depth?.values || []);
  if (!depths.length) return;
  const min = Math.min(...depths);
  const max = Math.max(...depths);
  const total = max - min || 1;
  const start = ((intervalStats.value.from - min) / total) * 100;
  const end = ((intervalStats.value.to - min) / total) * 100;
  chart.dispatchAction({
    type: "dataZoom",
    start: Math.max(0, Math.min(100, start)),
    end: Math.max(0, Math.min(100, end)),
  });
}

function toggleCurve(mnemonic) {
  if (selectedCurves.value.includes(mnemonic)) {
    selectedCurves.value = selectedCurves.value.filter((item) => item !== mnemonic);
  } else {
    selectedCurves.value = [...selectedCurves.value, mnemonic];
  }
}

function buildChartOption() {
  if (!parsedLog.value || !selectedCurves.value.length) {
    return {
      title: {
        text: "No curves selected",
        left: "center",
        top: "middle",
        textStyle: { color: "#64748b", fontSize: 14, fontWeight: 500 },
      },
    };
  }

  const depthValues = parsedLog.value.depth.values;
  const validDepths = validNumbers(depthValues);
  const depthMin = Math.min(...validDepths);
  const depthMax = Math.max(...validDepths);
  const curves = selectedCurves.value
    .map((mnemonic) => parsedLog.value.curves.find((curve) => curve.mnemonic === mnemonic))
    .filter(Boolean);
  const trackWidth = 100 / curves.length;
  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const series = [];

  curves.forEach((curve, index) => {
    const left = `${index * trackWidth + 2}%`;
    const width = `${Math.max(8, trackWidth - 4)}%`;
    const values = parsedLog.value.series[curve.mnemonic] || [];
    const data = values
      .map((value, rowIndex) => {
        const depth = depthValues[rowIndex];
        const cleanValue = sanitizeCurveValue(curve.mnemonic, value);
        if (cleanValue === null || depth === null) return null;
        return [cleanValue, depth];
      })
      .filter(Boolean);
    const curveValues = data.map(([value]) => value);
    const xMin = curveValues.length ? Math.min(...curveValues) : 0;
    const xMax = curveValues.length ? Math.max(...curveValues) : 1;
    const isResistivity = isResistivityCurve(curve.mnemonic);
    const isGammaRay = normalizeMnemonic(curve.mnemonic) === "GR";

    grids.push({
      left,
      width,
      top: 72,
      bottom: 54,
      containLabel: true,
    });
    xAxes.push({
      type: isResistivity ? "log" : "value",
      logBase: 10,
      gridIndex: index,
      position: "top",
      name: isResistivity
        ? `${curve.mnemonic} (${curve.unit || "log scale"})`
        : curve.unit || curve.mnemonic,
      nameLocation: "middle",
      nameGap: 26,
      min: isResistivity ? Math.max(0.01, xMin * 0.8) : undefined,
      max: isResistivity ? xMax * 1.2 : undefined,
      axisLabel: { fontSize: 10, color: "#475569" },
      splitLine: { lineStyle: { color: "#e2e8f0" } },
      minorTick: { show: isResistivity },
      minorSplitLine: {
        show: isResistivity,
        lineStyle: { color: "#f1f5f9" },
      },
    });
    yAxes.push({
      type: "value",
      gridIndex: index,
      inverse: true,
      min: depthMin,
      max: depthMax,
      name: index === 0 ? depthLabel.value : "",
      nameGap: 36,
      axisLabel: { fontSize: 10, color: "#475569" },
      splitLine: { lineStyle: { color: "#e2e8f0" } },
    });
    series.push({
      name: curve.mnemonic,
      type: "line",
      xAxisIndex: index,
      yAxisIndex: index,
      data,
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 1.5 },
      emphasis: { focus: "series" },
      markArea: isGammaRay
        ? {
            silent: true,
            data: buildGammaRayBands(
              depthValues,
              values.map((value) => sanitizeCurveValue(curve.mnemonic, value)),
              xMin,
              xMax,
            ),
          }
        : undefined,
    });
  });

  return {
    animation: false,
    color: ["#0f766e", "#2563eb", "#c2410c", "#7c3aed", "#be123c", "#4d7c0f"],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      valueFormatter: (value) => (typeof value === "number" ? value.toFixed(3) : value),
    },
    legend: {
      top: 8,
      type: "scroll",
      textStyle: { color: "#334155" },
    },
    axisPointer: {
      link: [{ yAxisIndex: "all" }],
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      {
        type: "inside",
        yAxisIndex: curves.map((_, index) => index),
        filterMode: "none",
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
      },
      {
        type: "slider",
        yAxisIndex: curves.map((_, index) => index),
        right: 8,
        top: 78,
        bottom: 62,
        width: 16,
        filterMode: "none",
      },
    ],
    series,
  };
}

function renderChart() {
  if (!chartEl.value) return;
  if (!chart) {
    chart = echarts.init(chartEl.value);
  }
  chart.setOption(buildChartOption(), true);
}

function resizeChart() {
  chart?.resize();
}

function resetZoom() {
  chart?.dispatchAction({
    type: "dataZoom",
    start: 0,
    end: 100,
  });
}

function csvCell(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function downloadText(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportCsv() {
  if (!parsedLog.value) return;
  const depth = parsedLog.value.depth || {};
  const curveNames = curveOptions.value.map((curve) => curve.mnemonic);
  const header = [depth.mnemonic || "DEPTH", ...curveNames];
  const rowCount = depth.values?.length || 0;
  const rows = [header.map(csvCell).join(",")];
  for (let index = 0; index < rowCount; index += 1) {
    rows.push(
      [
        depth.values[index],
        ...curveNames.map((mnemonic) => parsedLog.value.series?.[mnemonic]?.[index] ?? ""),
      ]
        .map(csvCell)
        .join(","),
    );
  }
  downloadText(`${safeFilename(parsedLog.value.filename)}_curves.csv`, rows.join("\n"), "text/csv");
  exportMessage.value = "CSV exported.";
}

function exportQualityJson() {
  if (!parsedLog.value) return;
  const payload = {
    filename: parsedLog.value.filename,
    quality_summary: parsedLog.value.quality_summary,
    petrophysics: parsedLog.value.petrophysics,
    interval: intervalStats.value,
  };
  downloadText(
    `${safeFilename(parsedLog.value.filename)}_quality.json`,
    JSON.stringify(payload, null, 2),
    "application/json",
  );
  exportMessage.value = "JSON exported.";
}

function exportChartPng() {
  if (!chart || !parsedLog.value) return;
  const url = chart.getDataURL({
    type: "png",
    pixelRatio: 2,
    backgroundColor: "#ffffff",
  });
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safeFilename(parsedLog.value.filename)}_chart.png`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  exportMessage.value = "Chart exported.";
}

onMounted(() => {
  fetchSamples();
  fetchPublicDatasets();
  fetchPublicSamples();
});
watch(selectedCurves, () => nextTick(renderChart));
watch(parsedLog, () => nextTick(renderChart));

window.addEventListener("resize", resizeChart);
onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  chart?.dispose();
});
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>LAS Well Log Viewer</h1>
        <p>{{ displayFilename }}</p>
      </div>
      <a class="api-link" :href="`${apiUrl}/health`" target="_blank">API</a>
    </header>

    <section class="workspace">
      <aside class="sidebar">
        <nav class="sidebar-tabs" aria-label="LAS workspace sections">
          <button
            v-for="tab in sidebarTabs"
            :key="tab.id"
            type="button"
            :class="{ active: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </nav>

        <section v-show="activeTab === 'samples'" class="sidebar-tab-content">
          <div class="panel">
            <h2>Upload LAS</h2>
            <label class="file-picker">
              <input ref="fileInput" type="file" accept=".las" @change="onFileChange" />
              <span>{{ selectedFile ? selectedFile.name : "Choose .las file" }}</span>
            </label>
            <button class="primary-button" type="button" :disabled="loading" @click="parseFile">
              {{ loading ? "Parsing..." : "Parse LAS" }}
            </button>
          </div>

          <div v-if="sampleFiles.length" class="panel">
            <h2>Project samples</h2>
            <div class="sample-list">
              <button
                v-for="sample in sampleFiles"
                :key="sample.name"
                type="button"
                :disabled="loading"
                @click="loadSample(sample)"
              >
                {{ loadingSample === sample.name ? "Loading..." : sampleLabel(sample) }}
              </button>
            </div>
          </div>

          <div class="panel">
            <h2>Public samples</h2>
            <div class="public-sample-list">
              <article v-for="sample in publicSampleFiles" :key="sample.id" class="public-sample-item">
                <div>
                  <strong>{{ sample.name }}</strong>
                  <small>{{ sample.source }} · {{ sample.filename }} · {{ sample.size_note }}</small>
                  <p>{{ sample.curves_note }}</p>
                </div>
                <button type="button" :disabled="loading" @click="loadPublicSample(sample)">
                  {{ loadingPublicSample === sample.id ? "Loading..." : "Load" }}
                </button>
              </article>
            </div>
          </div>

          <div class="panel">
            <div class="panel-title-row">
              <h2>More public datasets</h2>
              <span v-if="loadingDatasets">Loading</span>
            </div>
            <p class="muted-text">
              For more wells, open these public sources and download LAS files to upload here.
            </p>
            <div class="dataset-list">
              <article v-for="dataset in publicDatasets" :key="dataset.name" class="dataset-item">
                <div>
                  <strong>{{ dataset.name }}</strong>
                  <small>{{ dataset.source }} · {{ dataset.data_type }}</small>
                  <p>{{ dataset.description }}</p>
                  <span>{{ dataset.best_for }}</span>
                  <div v-if="dataset.tags?.length" class="dataset-tags">
                    <em v-for="tag in dataset.tags" :key="tag">{{ tag }}</em>
                  </div>
                </div>
                <a :href="dataset.url" target="_blank" rel="noreferrer">Open</a>
              </article>
            </div>
          </div>

          <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        </section>

        <section v-show="activeTab === 'view'" class="sidebar-tab-content">
          <div v-if="!parsedLog" class="panel">
            <h2>View</h2>
            <p class="muted-text">Load a LAS file to review metadata, data quality, and visible curves.</p>
          </div>

          <div v-if="parsedLog" class="panel">
            <h2>Well metadata</h2>
            <dl class="meta-list">
              <div v-for="[label, value] in metadataRows" :key="label">
                <dt>{{ label }}</dt>
                <dd>{{ value }}</dd>
              </div>
            </dl>
          </div>

          <div v-if="qualitySummary" class="panel">
            <h2>Quality summary</h2>
            <dl class="meta-list">
              <div>
                <dt>Depth step</dt>
                <dd>{{ formatWithUnit(formatNumber(qualitySummary.depth_step), qualitySummary.depth_unit) }}</dd>
              </div>
              <div>
                <dt>Key curves</dt>
                <dd>{{ qualitySummary.detected_key_curve_count }} / {{ qualitySummary.key_curves.length }}</dd>
              </div>
            </dl>
            <div class="key-curve-list">
              <span
                v-for="curve in qualitySummary.key_curves"
                :key="curve.key"
                :class="['key-curve-chip', { missing: !curve.present }]"
              >
                {{ curve.label }}: {{ curve.mnemonic || "missing" }}
              </span>
            </div>
            <ul v-if="qualitySummary.warnings.length" class="warning-list">
              <li v-for="warning in qualitySummary.warnings" :key="warning">{{ warning }}</li>
            </ul>
          </div>

          <div v-if="curveOptions.length" class="panel">
            <h2>Curves</h2>
            <div class="curve-list">
              <label v-for="curve in curveOptions" :key="curve.mnemonic" class="curve-item">
                <input
                  type="checkbox"
                  :checked="selectedCurves.includes(curve.mnemonic)"
                  @change="toggleCurve(curve.mnemonic)"
                />
                <span>
                  <strong>{{ curve.mnemonic }}<em v-if="curve.synthetic">computed</em></strong>
                  <small>{{ curve.unit || "unitless" }} · {{ formatPercent(curve.null_percent) }} null</small>
                </span>
              </label>
            </div>
          </div>
        </section>

        <section v-show="activeTab === 'analysis'" class="sidebar-tab-content">
          <div v-if="!parsedLog" class="panel">
            <h2>Analysis</h2>
            <p class="muted-text">Load a LAS file to calculate Vshale, interval statistics, and clean intervals.</p>
          </div>

          <div v-if="vshaleSummary" class="panel">
            <h2>Vshale</h2>
            <p v-if="!vshaleSummary.available" class="muted-text">{{ vshaleSummary.reason }}</p>
            <template v-else>
              <dl class="meta-list">
                <div v-for="[label, value] in vshaleRows" :key="label">
                  <dt>{{ label }}</dt>
                  <dd>{{ value }}</dd>
                </div>
              </dl>
              <div v-if="visibleCleanIntervals.length" class="interval-list">
                <div v-for="interval in visibleCleanIntervals" :key="`${interval.from}-${interval.to}`">
                  <span>{{ interval.from }} - {{ interval.to }} {{ vshaleSummary.depth_unit }}</span>
                  <strong>{{ formatWithUnit(formatNumber(interval.thickness), vshaleSummary.depth_unit) }}</strong>
                </div>
              </div>
            </template>
          </div>

          <div v-if="parsedLog && intervalStats" class="panel">
            <h2>Interval analysis</h2>
            <div class="interval-controls">
              <label>
                <span>Start</span>
                <input v-model="intervalStart" type="number" step="any" />
              </label>
              <label>
                <span>Stop</span>
                <input v-model="intervalStop" type="number" step="any" />
              </label>
            </div>
            <div class="button-row">
              <button type="button" @click="zoomToInterval">Zoom</button>
              <button type="button" @click="resetIntervalRange()">Full range</button>
            </div>
            <dl class="meta-list compact">
              <div v-for="[label, value] in intervalRows" :key="label">
                <dt>{{ label }}</dt>
                <dd>{{ value }}</dd>
              </div>
            </dl>
            <div v-if="intervalStats.averages.length" class="metric-grid">
              <article v-for="item in intervalStats.averages" :key="item.label">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ item.mnemonic }}</small>
              </article>
            </div>
            <div v-if="intervalStats.cleanIntervals.length" class="interval-list">
              <div v-for="interval in intervalStats.cleanIntervals" :key="`${interval.from}-${interval.to}`">
                <span>{{ interval.from }} - {{ interval.to }} {{ intervalStats.unit }}</span>
                <strong>{{ formatWithUnit(formatNumber(interval.thickness), intervalStats.unit) }}</strong>
              </div>
            </div>
          </div>
        </section>

        <section v-show="activeTab === 'guide'" class="sidebar-tab-content">
          <div class="panel">
            <h2>Plain summary</h2>
            <div class="summary-list">
              <p v-for="message in interpretationSummary" :key="message">{{ message }}</p>
            </div>
          </div>

          <div class="panel">
            <h2>Measurements guide</h2>
            <div class="glossary-list">
              <div v-for="item in glossaryItems" :key="item.term">
                <strong>{{ item.term }}</strong>
                <p>{{ item.definition }}</p>
              </div>
            </div>
          </div>

          <div class="panel">
            <h2>Method notes</h2>
            <ul class="method-list">
              <li v-for="note in methodNotes" :key="note">{{ note }}</li>
            </ul>
          </div>
        </section>
      </aside>

      <section class="viewer">
        <div v-if="parsedLog" class="viewer-toolbar">
          <div>
            <strong>{{ wellName }}</strong>
            <span>{{ location }} · {{ apiNumber }}</span>
          </div>
          <div class="toolbar-actions">
            <button type="button" @click="resetZoom">Reset zoom</button>
            <button type="button" @click="exportCsv">CSV</button>
            <button type="button" @click="exportQualityJson">JSON</button>
            <button type="button" @click="exportChartPng">PNG</button>
          </div>
        </div>
        <p v-if="exportMessage" class="export-message">{{ exportMessage }}</p>
        <div v-if="parsedLog" class="summary-cards">
          <article v-for="[label, value] in qualityCards" :key="label">
            <span>{{ label }}</span>
            <strong>{{ value }}</strong>
          </article>
        </div>
        <div v-if="parsedLog" class="plain-summary-strip">
          <span>Plain summary</span>
          <p>{{ interpretationSummary[0] }}</p>
        </div>
        <div v-if="!parsedLog" class="empty-state">
          <h2>No log loaded</h2>
          <p>Select one of the sample LAS files or upload another well log.</p>
        </div>
        <div v-show="parsedLog" ref="chartEl" class="chart"></div>
      </section>
    </section>
  </main>
</template>
