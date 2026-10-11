<script setup lang="ts">
import type Graph from "graphology";
import type FA2LayoutSupervisor from "graphology-layout-forceatlas2/worker";
import type Sigma from "sigma";
import { nextTick, onBeforeUnmount, ref, watch } from "vue";

import { graphNodeSize, usesLargeNodes } from "../graph/presentation";
import type { WikiGraphEdge, WikiGraphNode } from "../types";

interface NodeAttributes {
  label: string;
  x: number;
  y: number;
  size: number;
  color: string;
  node: WikiGraphNode;
  highlighted?: boolean;
}

interface EdgeAttributes {
  color: string;
  size: number;
  edge: WikiGraphEdge;
}

const props = defineProps<{
  nodes: WikiGraphNode[];
  edges: WikiGraphEdge[];
  focusedId?: string | null;
  smallGraphThreshold: number;
}>();

const emit = defineEmits<{
  open: [node: WikiGraphNode];
  unavailable: [message: string];
}>();

const container = ref<HTMLElement | null>(null);
const positionCache = new Map<string, { x: number; y: number }>();
let renderer: Sigma<NodeAttributes, EdgeAttributes> | null = null;
let graph: Graph<NodeAttributes, EdgeAttributes> | null = null;
let layout: FA2LayoutSupervisor<NodeAttributes, EdgeAttributes> | null = null;
let layoutTimer: ReturnType<typeof setTimeout> | null = null;
let resizeObserver: ResizeObserver | null = null;
let draggedNode: string | null = null;
let nodeMoved = false;
let hoveredNode: string | null = null;
let generation = 0;

const colors: Record<string, string> = {
  entity: "#33d133",
  concept: "#60a5fa",
  topic: "#a78bfa",
  synthesis: "#f59e0b",
  dataset: "#22d3ee",
  markdown: "#94a3b8",
};

function cleanup() {
  generation += 1;
  if (layoutTimer) clearTimeout(layoutTimer);
  layoutTimer = null;
  layout?.kill();
  layout = null;
  resizeObserver?.disconnect();
  resizeObserver = null;
  if (graph) {
    graph.forEachNode((id, attributes) => {
      positionCache.set(id, { x: attributes.x, y: attributes.y });
    });
  }
  renderer?.kill();
  renderer = null;
  graph = null;
  draggedNode = null;
  hoveredNode = null;
}

function initialPosition(index: number, count: number, id: string) {
  const cached = positionCache.get(id);
  if (cached) return cached;
  const angle = (index / Math.max(count, 1)) * Math.PI * 2;
  const hash = [...id].reduce(
    (value, character) => value + character.charCodeAt(0),
    0,
  );
  const radius = 1 + (hash % 17) / 100;
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}

async function renderGraph() {
  cleanup();
  await nextTick();
  if (!container.value || !props.nodes.length) return;
  const currentGeneration = generation;
  try {
    const [
      { default: Graphology },
      { default: SigmaRenderer },
      { default: ForceAtlas2 },
      { drawDiscNodeHover },
    ] = await Promise.all([
      import("graphology"),
      import("sigma"),
      import("graphology-layout-forceatlas2/worker"),
      import("sigma/rendering"),
    ]);
    if (currentGeneration !== generation || !container.value) return;
    const nextGraph = new Graphology<NodeAttributes, EdgeAttributes>({
      type: "directed",
      multi: false,
      allowSelfLoops: true,
    });
    const largeNodes = usesLargeNodes(
      props.nodes.length,
      props.smallGraphThreshold,
    );
    props.nodes.forEach((node, index) => {
      const position = initialPosition(index, props.nodes.length, node.id);
      nextGraph.addNode(node.id, {
        label: node.title,
        x: position.x,
        y: position.y,
        size: graphNodeSize(
          node.degree,
          props.nodes.length,
          props.smallGraphThreshold,
        ),
        color: colors[node.document_type] ?? colors.markdown,
        node,
        highlighted: node.id === props.focusedId,
      });
    });
    props.edges.forEach((edge) => {
      if (!nextGraph.hasNode(edge.source) || !nextGraph.hasNode(edge.target))
        return;
      nextGraph.addDirectedEdgeWithKey(edge.id, edge.source, edge.target, {
        color: "#52625d",
        size: 0.7,
        edge,
      });
    });
    graph = nextGraph;
    const nextRenderer = new SigmaRenderer<NodeAttributes, EdgeAttributes>(
      nextGraph,
      container.value,
      {
        defaultNodeColor: "#94a3b8",
        defaultEdgeColor: "#52625d",
        labelColor: { color: "#e8f0ed" },
        defaultDrawNodeHover: (context, data, settings) =>
          drawDiscNodeHover(context, data, {
            ...settings,
            labelColor: { color: "#17221f" },
          }),
        labelFont: "Outfit, sans-serif",
        labelSize: 12,
        labelDensity: largeNodes ? 1 : 0.75,
        labelGridCellSize: 120,
        labelRenderedSizeThreshold: largeNodes ? 0 : 5,
        hideLabelsOnMove: true,
        hideEdgesOnMove: false,
        minCameraRatio: 0.05,
        maxCameraRatio: 5,
        zIndex: true,
        nodeReducer: (id, data) => {
          if (!hoveredNode) return data;
          const related =
            id === hoveredNode || nextGraph.areNeighbors(id, hoveredNode);
          return related
            ? { ...data, highlighted: id === hoveredNode, zIndex: 2 }
            : { ...data, color: "#33413d", label: "", zIndex: 0 };
        },
        edgeReducer: (id, data) => {
          if (!hoveredNode) return data;
          const source = nextGraph.source(id);
          const target = nextGraph.target(id);
          return source === hoveredNode || target === hoveredNode
            ? { ...data, color: "#33d133", size: 1.5, zIndex: 2 }
            : { ...data, color: "#26312e", size: 0.35, zIndex: 0 };
        },
      },
    );
    renderer = nextRenderer;
    renderer.on("enterNode", ({ node }) => {
      hoveredNode = node;
      renderer?.refresh({ schedule: true });
    });
    renderer.on("leaveNode", () => {
      hoveredNode = null;
      renderer?.refresh({ schedule: true });
    });
    renderer.on("downNode", ({ node, event }) => {
      draggedNode = node;
      nodeMoved = false;
      layout?.stop();
      renderer?.getCamera().disable();
      event.preventSigmaDefault();
    });
    renderer.getMouseCaptor().on("mousemovebody", (event) => {
      if (!draggedNode || !renderer || !graph) return;
      nodeMoved = true;
      const position = renderer.viewportToGraph(event);
      graph.mergeNodeAttributes(draggedNode, position);
      event.preventSigmaDefault();
    });
    renderer.getMouseCaptor().on("mouseup", () => {
      renderer?.getCamera().enable();
      draggedNode = null;
    });
    renderer.on("clickNode", ({ node }) => {
      if (nodeMoved || !graph) {
        nodeMoved = false;
        return;
      }
      emit("open", graph.getNodeAttribute(node, "node"));
    });
    resizeObserver = new ResizeObserver(() => renderer?.scheduleRefresh());
    resizeObserver.observe(container.value);
    startLayout(ForceAtlas2);
    if (props.focusedId) focusNode(props.focusedId);
  } catch (reason) {
    cleanup();
    emit(
      "unavailable",
      reason instanceof Error
        ? reason.message
        : "WebGL graph rendering is unavailable in this browser.",
    );
  }
}

function startLayout(Layout: typeof FA2LayoutSupervisor) {
  if (!graph || graph.order < 2 || graph.size === 0) return;
  layout?.kill();
  layout = new Layout<NodeAttributes, EdgeAttributes>(graph, {
    settings: {
      barnesHutOptimize: graph.order > 200,
      gravity: 1,
      scalingRatio: graph.order > 500 ? 8 : 4,
      slowDown: 4,
    },
  });
  layout.start();
  layoutTimer = setTimeout(
    () => {
      layout?.stop();
      layoutTimer = null;
      graph?.forEachNode((id, attributes) => {
        positionCache.set(id, { x: attributes.x, y: attributes.y });
      });
    },
    Math.min(2_500, 900 + graph.order * 2),
  );
}

async function fit() {
  await renderer?.getCamera().animatedReset({ duration: 350 });
}

async function focusNode(id: string) {
  if (!renderer || !graph?.hasNode(id)) return;
  const display = renderer.getNodeDisplayData(id);
  if (!display) return;
  await renderer
    .getCamera()
    .animate({ x: display.x, y: display.y, ratio: 0.22 }, { duration: 350 });
}

async function reset() {
  if (!graph) return;
  positionCache.clear();
  graph.nodes().forEach((id, index) => {
    graph?.mergeNodeAttributes(id, initialPosition(index, graph.order, id));
  });
  const { default: Layout } =
    await import("graphology-layout-forceatlas2/worker");
  startLayout(Layout);
  await fit();
}

watch(
  () => [props.nodes, props.edges, props.smallGraphThreshold] as const,
  () => void renderGraph(),
  { immediate: true },
);

watch(
  () => props.focusedId,
  (id) => {
    if (id) void focusNode(id);
  },
);

onBeforeUnmount(cleanup);
defineExpose({ fit, focusNode, reset });
</script>

<template>
  <div
    ref="container"
    class="second-brain-canvas min-h-[570px] w-full flex-1 [background:radial-gradient(circle_at_center,_rgb(51_209_51_/_4%),_transparent_55%),_#13201c] mobile:min-h-[560px]"
    role="img"
    :aria-label="`Interactive knowledge graph with ${nodes.length} pages and ${edges.length} links`"
  ></div>
</template>
