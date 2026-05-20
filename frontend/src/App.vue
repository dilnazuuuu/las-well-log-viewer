<script setup>
import * as echarts from "echarts";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8001";

const fileInput = ref(null);
const selectedFile = ref(null);
const parsedLog = ref(null);
const selectedCurves = ref([]);
const loading = ref(false);
const errorMessage = ref("");
const chartEl = ref(null);
let chart = null;
const RESISTIVITY_CURVES = new Set(["RESD", "RES", "ILD", "LLD", "RT"]);
const GR_SHALE_THRESHOLD = 75;

const curveOptions = computed(() => parsedLog.value?.curves || []);
const wellName = computed(() => parsedLog.value?.well?.WELL?.value || "Untitled well");
const location = computed(() => parsedLog.value?.well?.LOC?.value || "-");
const apiNumber = computed(() => parsedLog.value?.well?.API?.value || "-");
const depthLabel = computed(() => {
  const depth = parsedLog.value?.depth;
  if (!depth) return "Depth";
  return depth.unit ? `${depth.mnemonic} (${depth.unit})` : depth.mnemonic;
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

function formatWithUnit(value, unit) {
  if (value === undefined || value === null || value === "") return null;
  return unit ? `${value} ${unit}` : `${value}`;
}

function formatDepthRange(depth) {
  const unit = depth.unit || "";
  const start = depth.start ?? depth.values?.[0];
  const stop = depth.stop ?? depth.values?.[depth.values.length - 1];
  if (start === undefined || stop === undefined) return null;
  return `${start} - ${stop}${unit ? ` ${unit}` : ""}`;
}

function isResistivityCurve(mnemonic) {
  return RESISTIVITY_CURVES.has(String(mnemonic).toUpperCase());
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
    parsedLog.value = payload;
    selectedCurves.value = payload.curves.slice(0, 4).map((curve) => curve.mnemonic);
    await nextTick();
    renderChart();
  } catch (error) {
    errorMessage.value = error.message || "Request failed.";
  } finally {
    loading.value = false;
  }
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
    const isGammaRay = curve.mnemonic.toUpperCase() === "GR";

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
        <p>{{ parsedLog ? parsedLog.filename : "Upload a Log ASCII Standard file" }}</p>
      </div>
      <a class="api-link" :href="`${apiUrl}/health`" target="_blank">API</a>
    </header>

    <section class="workspace">
      <aside class="sidebar">
        <div class="panel">
          <label class="file-picker">
            <input ref="fileInput" type="file" accept=".las" @change="onFileChange" />
            <span>{{ selectedFile ? selectedFile.name : "Choose .las file" }}</span>
          </label>
          <button class="primary-button" type="button" :disabled="loading" @click="parseFile">
            {{ loading ? "Parsing..." : "Parse LAS" }}
          </button>
          <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
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
                <strong>{{ curve.mnemonic }}</strong>
                <small>{{ curve.unit || "unitless" }}</small>
              </span>
            </label>
          </div>
        </div>
      </aside>

      <section class="viewer">
        <div v-if="parsedLog" class="viewer-toolbar">
          <div>
            <strong>{{ wellName }}</strong>
            <span>{{ location }} · {{ apiNumber }}</span>
          </div>
          <button type="button" @click="resetZoom">Reset zoom</button>
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
