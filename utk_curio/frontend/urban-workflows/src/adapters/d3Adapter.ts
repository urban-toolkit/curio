
import * as d3 from "d3";
import { GrammarAdapter, registerGrammarAdapter } from "../registry/grammarAdapter";
import { parseDataframe, parseGeoDataframe } from "../utils/parsing";
import { fetchData } from "../services/api";
  
// Types

type D3FunctionSpec = (ctx: { d3: typeof d3; container: HTMLElement; data: any[] }) => SVGElement | HTMLElement | void;

type D3JsonSpec = {
  chartType?: string;
  width?: number;
  height?: number;
  title?: string;
  xField?: string;
  yField?: string;
  labelField?: string;
  valueField?: string;
  nameField?: string;
  childrenField?: string;
  colorScheme?: string;
  [key: string]: any;
};

type ChartRenderer = (container: HTMLElement, spec: D3JsonSpec, data: any[]) => void;

// Data parsing

async function parseInputData(input: any): Promise<any[]> {
  if (!input || input === "") {
    return [
      { category: "A", value: 10 },
      { category: "B", value: 25 },
      { category: "C", value: 18 },
      { category: "D", value: 35 },
    ];
  }

  const parserMap: Record<string, (data: any) => any> = {
    dataframe: parseDataframe,
    geodataframe: parseGeoDataframe,
  };

  const parser = parserMap[input.dataType];

  if (!parser) {
    return Array.isArray(input.data) ? input.data : [];
  }

  if (input.path) {
    const fetched = await fetchData(input.path);
    return parser(fetched.data);
  }

  return parser(input.data);
}

// ─────────────────────────────────────────────
// Spec parsing
// ─────────────────────────────────────────────

function getDefaultSpec(): D3JsonSpec {
  return { chartType: "bar", width: 500, height: 300, xField: "category", yField: "value" };
}

function parseSpec(spec: unknown): D3JsonSpec | D3FunctionSpec {
  if (!spec || spec === "") return getDefaultSpec();
  if (typeof spec === "function") return spec as D3FunctionSpec;
  if (typeof spec === "object") return spec as D3JsonSpec;

  if (typeof spec === "string") {
    const trimmed = spec.trim();
    if (!trimmed) return getDefaultSpec();

    // Try JSON first
    try {
      return JSON.parse(trimmed) as D3JsonSpec;
    } catch {}

    // Try function string (Observable-style)
    try {
      const fn = new Function(`return (${trimmed});`)();
      if (typeof fn === "function") return fn as D3FunctionSpec;
    } catch (error) {
      throw new Error("Invalid D3 grammar: must be valid JSON or a valid function string.");
    }
  }

  throw new Error("Invalid D3 grammar: unsupported spec type.");
}

// Helpers

function normalizeRows(data: any[]): any[] {
  if (!Array.isArray(data) || data.length === 0) {
    return [{ category: "A", value: 10 }, { category: "B", value: 25 }, { category: "C", value: 18 }];
  }

  return data.map((row: any, index: number) => {
    if (typeof row === "number") return { category: String(index + 1), value: row };
    if (Array.isArray(row)) return { category: String(row[0] ?? index + 1), value: Number(row[1] ?? 0) };
    if (typeof row === "object") return row;
    return { category: String(index + 1), value: Number(row) || 0 };
  });
}

function resolveColorScheme(name?: string): readonly string[] {
  const schemes: Record<string, readonly string[]> = {
    tableau10: d3.schemeTableau10,
    category10: d3.schemeCategory10,
    set2: d3.schemeSet2,
    set3: d3.schemeSet3,
    pastel1: d3.schemePastel1,
    dark2: d3.schemeDark2,
  };
  return schemes[name ?? "tableau10"] ?? d3.schemeTableau10;
}

// Chart renderers registry

const chartRenderers: Record<string, ChartRenderer> = {

  // ── Bar chart ─────────────────────────────
  bar(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 500;
    const height = spec.height ?? 300;
    const xField = spec.xField ?? "category";
    const yField = spec.yField ?? "value";
    const margin = { top: 30, right: 20, bottom: 40, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const color = d3.scaleOrdinal(resolveColorScheme(spec.colorScheme));

    const svg = d3.select(container).append("svg")
      .attr("width", width).attr("height", height);

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand()
      .domain(rows.map((d) => String(d[xField])))
      .range([0, innerW]).padding(0.3);

    const y = d3.scaleLinear()
      .domain([0, d3.max(rows, (d) => Number(d[yField])) ?? 1]).nice()
      .range([innerH, 0]);

    g.selectAll("rect").data(rows).enter().append("rect")
      .attr("x", (d) => x(String(d[xField]))!)
      .attr("y", (d) => y(Number(d[yField])))
      .attr("width", x.bandwidth())
      .attr("height", (d) => innerH - y(Number(d[yField])))
      .attr("fill", (_, i) => color(String(i)));

    g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x));
    g.append("g").call(d3.axisLeft(y));

    if (spec.title) {
      svg.append("text").attr("x", width / 2).attr("y", 18)
        .attr("text-anchor", "middle").attr("font-size", 14).text(spec.title);
    }
  },

  // ── Horizontal bar chart ──────────────────
  barH(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 500;
    const height = spec.height ?? Math.max(200, rows.length * 30);
    const xField = spec.xField ?? "value";
    const yField = spec.yField ?? "category";
    const margin = { top: 30, right: 20, bottom: 30, left: 100 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const color = d3.scaleOrdinal(resolveColorScheme(spec.colorScheme));

    const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const y = d3.scaleBand()
      .domain(rows.map((d) => String(d[yField]))).range([0, innerH]).padding(0.3);
    const x = d3.scaleLinear()
      .domain([0, d3.max(rows, (d) => Number(d[xField])) ?? 1]).nice().range([0, innerW]);

    g.selectAll("rect").data(rows).enter().append("rect")
      .attr("y", (d) => y(String(d[yField]))!)
      .attr("x", 0)
      .attr("height", y.bandwidth())
      .attr("width", (d) => x(Number(d[xField])))
      .attr("fill", (_, i) => color(String(i)));

    g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x));
    g.append("g").call(d3.axisLeft(y));

    if (spec.title) {
      svg.append("text").attr("x", width / 2).attr("y", 18)
        .attr("text-anchor", "middle").attr("font-size", 14).text(spec.title);
    }
  },

  // ── Line chart ────────────────────────────
  line(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 500;
    const height = spec.height ?? 300;
    const xField = spec.xField ?? "category";
    const yField = spec.yField ?? "value";
    const margin = { top: 30, right: 20, bottom: 40, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    // Try numeric x-axis first, fall back to point scale
    const xValues = rows.map((d) => d[xField]);
    const allNumeric = xValues.every((v) => !isNaN(Number(v)));

    const x = allNumeric
      ? d3.scaleLinear().domain(d3.extent(xValues.map(Number)) as [number, number]).range([0, innerW])
      : d3.scalePoint().domain(xValues.map(String)).range([0, innerW]);

    const y = d3.scaleLinear()
      .domain([0, d3.max(rows, (d) => Number(d[yField])) ?? 1]).nice().range([innerH, 0]);

    const line = d3.line<any>()
      .x((d) => (x as any)(allNumeric ? Number(d[xField]) : String(d[xField])))
      .y((d) => y(Number(d[yField])));

    g.append("path").datum(rows)
      .attr("fill", "none").attr("stroke", "steelblue").attr("stroke-width", 2)
      .attr("d", line);

    g.selectAll("circle").data(rows).enter().append("circle")
      .attr("cx", (d) => (x as any)(allNumeric ? Number(d[xField]) : String(d[xField])))
      .attr("cy", (d) => y(Number(d[yField])))
      .attr("r", 4).attr("fill", "steelblue");

    g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x as any));
    g.append("g").call(d3.axisLeft(y));

    if (spec.title) {
      svg.append("text").attr("x", width / 2).attr("y", 18)
        .attr("text-anchor", "middle").attr("font-size", 14).text(spec.title);
    }
  },

  // ── Area chart ────────────────────────────
  area(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 500;
    const height = spec.height ?? 300;
    const xField = spec.xField ?? "category";
    const yField = spec.yField ?? "value";
    const margin = { top: 30, right: 20, bottom: 40, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const xValues = rows.map((d) => d[xField]);
    const allNumeric = xValues.every((v) => !isNaN(Number(v)));

    const x = allNumeric
      ? d3.scaleLinear().domain(d3.extent(xValues.map(Number)) as [number, number]).range([0, innerW])
      : d3.scalePoint().domain(xValues.map(String)).range([0, innerW]);

    const y = d3.scaleLinear()
      .domain([0, d3.max(rows, (d) => Number(d[yField])) ?? 1]).nice().range([innerH, 0]);

    const xVal = (d: any) => (x as any)(allNumeric ? Number(d[xField]) : String(d[xField]));

    const area = d3.area<any>().x(xVal).y0(innerH).y1((d) => y(Number(d[yField])));
    const line = d3.line<any>().x(xVal).y((d) => y(Number(d[yField])));

    g.append("path").datum(rows)
      .attr("fill", "steelblue").attr("fill-opacity", 0.3).attr("d", area);
    g.append("path").datum(rows)
      .attr("fill", "none").attr("stroke", "steelblue").attr("stroke-width", 2).attr("d", line);

    g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x as any));
    g.append("g").call(d3.axisLeft(y));

    if (spec.title) {
      svg.append("text").attr("x", width / 2).attr("y", 18)
        .attr("text-anchor", "middle").attr("font-size", 14).text(spec.title);
    }
  },

  // ── Pie / Donut chart ─────────────────────
  pie(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 400;
    const height = spec.height ?? 400;
    const nameField = spec.nameField ?? spec.xField ?? "category";
    const valueField = spec.valueField ?? spec.yField ?? "value";
    const innerRadius = spec.chartType === "donut" ? Math.min(width, height) / 4 : 0;
    const outerRadius = Math.min(width, height) / 2 - 20;

    const color = d3.scaleOrdinal(resolveColorScheme(spec.colorScheme))
      .domain(rows.map((d) => String(d[nameField])));

    const svg = d3.select(container).append("svg")
      .attr("width", width).attr("height", height)
      .append("g").attr("transform", `translate(${width / 2},${height / 2})`);

    const pie = d3.pie<any>().value((d) => Number(d[valueField]));
    const arc = d3.arc<any>().innerRadius(innerRadius).outerRadius(outerRadius);
    const labelArc = d3.arc<any>().innerRadius(outerRadius * 0.7).outerRadius(outerRadius * 0.7);

    const arcs = svg.selectAll("arc").data(pie(rows)).enter().append("g");

    arcs.append("path")
      .attr("d", arc)
      .attr("fill", (d) => color(String(d.data[nameField])))
      .attr("stroke", "white").attr("stroke-width", 2);

    arcs.append("text")
      .attr("transform", (d) => `translate(${labelArc.centroid(d)})`)
      .attr("text-anchor", "middle").attr("font-size", 11)
      .text((d) => String(d.data[nameField]));
  },

  // donut is just pie with inner radius
  donut(...args) { chartRenderers.pie(...args); },

  // ── Scatter plot ──────────────────────────
  scatter(container, spec, data) {
    const rows = normalizeRows(data);
    const width = spec.width ?? 500;
    const height = spec.height ?? 300;
    const xField = spec.xField ?? "x";
    const yField = spec.yField ?? "y";
    const labelField = spec.labelField;
    const margin = { top: 30, right: 20, bottom: 40, left: 50 };
    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const color = d3.scaleOrdinal(resolveColorScheme(spec.colorScheme));

    const svg = d3.select(container).append("svg").attr("width", width).attr("height", height);
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const x = d3.scaleLinear()
      .domain(d3.extent(rows, (d) => Number(d[xField])) as [number, number]).nice().range([0, innerW]);
    const y = d3.scaleLinear()
      .domain(d3.extent(rows, (d) => Number(d[yField])) as [number, number]).nice().range([innerH, 0]);

    g.selectAll("circle").data(rows).enter().append("circle")
      .attr("cx", (d) => x(Number(d[xField])))
      .attr("cy", (d) => y(Number(d[yField])))
      .attr("r", spec.radius ?? 5)
      .attr("fill", (_, i) => color(String(i)))
      .attr("fill-opacity", 0.7);

    if (labelField) {
      g.selectAll("text.label").data(rows).enter().append("text")
        .attr("x", (d) => x(Number(d[xField])) + 7)
        .attr("y", (d) => y(Number(d[yField])) + 4)
        .attr("font-size", 10).text((d) => String(d[labelField]));
    }

    g.append("g").attr("transform", `translate(0,${innerH})`).call(d3.axisBottom(x));
    g.append("g").call(d3.axisLeft(y));

    if (spec.title) {
      svg.append("text").attr("x", width / 2).attr("y", 18)
        .attr("text-anchor", "middle").attr("font-size", 14).text(spec.title);
    }
  },

  // ── Collapsible tree ──────────────────────
  // Supports Observable-style hierarchical data: { name, children: [...] }
  tree(container, spec, data) {
    // data can be a hierarchy object OR an array with one root element
    const hierarchyData = Array.isArray(data) && data.length === 1 ? data[0] : data;

    const width = spec.width ?? 928;
    const marginTop = 10, marginRight = 10, marginBottom = 10, marginLeft = 40;

    const root = d3.hierarchy(hierarchyData as any);
    const dx = spec.nodeSpacing ?? 10;
    const dy = (width - marginRight - marginLeft) / (1 + root.height);

    const tree = d3.tree<any>().nodeSize([dx, dy]);
    const diagonal = d3.linkHorizontal<any, any>().x((d) => d.y).y((d) => d.x);

    const svg = d3.select(container).append("svg")
      .attr("width", width).attr("height", dx)
      .attr("viewBox", [-marginLeft, -marginTop, width, dx] as any)
      .attr("style", "max-width: 100%; height: auto; font: 10px sans-serif; user-select: none;");

    const gLink = svg.append("g")
      .attr("fill", "none").attr("stroke", "#555")
      .attr("stroke-opacity", 0.4).attr("stroke-width", 1.5);

    const gNode = svg.append("g")
      .attr("cursor", "pointer").attr("pointer-events", "all");

    function update(source: any) {
      const nodes = root.descendants().reverse();
      const links = root.links();
      tree(root);

      let left = root as any;
      let right = root as any;
      root.eachBefore((node: any) => {
        if (node.x < left.x) left = node;
        if (node.x > right.x) right = node;
      });

      const height = right.x - left.x + marginTop + marginBottom;
      const transition = svg.transition().duration(250)
        .attr("height", height)
        .attr("viewBox", [-marginLeft, left.x - marginTop, width, height] as any);

      const node = gNode.selectAll<SVGGElement, any>("g").data(nodes, (d) => d.id);

      const nodeEnter = node.enter().append("g")
        .attr("transform", () => `translate(${source.y0},${source.x0})`)
        .attr("fill-opacity", 0).attr("stroke-opacity", 0)
        .on("click", (_, d:any) => {
          d.children = d.children ? null : d._children;
          update(d);
        });

      nodeEnter.append("circle").attr("r", 2.5)
        .attr("fill", (d: any) => d._children ? "#555" : "#999").attr("stroke-width", 10);

      nodeEnter.append("text").attr("dy", "0.31em")
        .attr("x", (d: any) => d._children ? -6 : 6)
        .attr("text-anchor", (d: any) => d._children ? "end" : "start")
        .text((d: any) => d.data.name ?? d.data[spec.nameField ?? "name"])
        .attr("stroke-linejoin", "round").attr("stroke-width", 3)
        .attr("stroke", "white").attr("paint-order", "stroke");

      node.merge(nodeEnter).transition(transition as any)
        .attr("transform", (d: any) => `translate(${d.y},${d.x})`)
        .attr("fill-opacity", 1).attr("stroke-opacity", 1);

      node.exit().transition(transition as any).remove()
        .attr("transform", () => `translate(${source.y},${source.x})`)
        .attr("fill-opacity", 0).attr("stroke-opacity", 0);

      const link = gLink.selectAll<SVGPathElement, any>("path").data(links, (d) => d.target.id);

      const linkEnter = link.enter().append("path")
        .attr("d", () => { const o = { x: source.x0, y: source.y0 }; return diagonal({ source: o, target: o }); });

      link.merge(linkEnter).transition(transition as any).attr("d", diagonal);
      link.exit().transition(transition as any).remove()
        .attr("d", () => { const o = { x: source.x, y: source.y }; return diagonal({ source: o, target: o }); });

      root.eachBefore((d: any) => { d.x0 = d.x; d.y0 = d.y; });
    }

    (root as any).x0 = dy / 2;
    (root as any).y0 = 0;
    root.descendants().forEach((d: any, i) => {
      d.id = i;
      d._children = d.children;
      // collapse nodes with depth > 0 whose name isn't 7 chars (Observable default behaviour)
      if (d.depth && d.data.name?.length !== 7) d.children = null;
    });

    update(root);
  },

};

// ─────────────────────────────────────────────
// Dispatch JSON spec to a registered renderer
// ─────────────────────────────────────────────

function renderFromJsonSpec(container: HTMLElement, spec: D3JsonSpec, data: any[]): void {
  const chartType = (spec.chartType ?? "bar").toLowerCase();
  const renderer = chartRenderers[chartType];

  if (!renderer) {
    throw new Error(
      `[D3Adapter] Unknown chartType "${chartType}". ` +
      `Supported types: ${Object.keys(chartRenderers).join(", ")}`
    );
  }

  renderer(container, spec, data);
}

// ─────────────────────────────────────────────
// Register a custom chart renderer at runtime
// ─────────────────────────────────────────────

export function registerD3ChartRenderer(type: string, renderer: ChartRenderer): void {
  chartRenderers[type.toLowerCase()] = renderer;
}

// ─────────────────────────────────────────────
// Adapter
// ─────────────────────────────────────────────

export const d3Adapter: GrammarAdapter = {
  grammarId: "d3",

  validate(spec: unknown): boolean {
    if (!spec || spec === "") return true;
    if (typeof spec === "function") return true;
    if (typeof spec === "object") return true;
    if (typeof spec === "string") return true;
    return false;
  },

  render: async (container: HTMLElement, spec: unknown, data?: unknown): Promise<void> => {
    try {
      container.innerHTML = "";

      const parsedData = await parseInputData(data);
      const parsedSpec = parseSpec(spec);

      // ── Function-based spec (Observable-style) ──────────────────────────
      // The function receives { d3, container, data } and may either:
      //   a) return an SVG/HTML element → we append it to the container
      //   b) mutate the container directly → nothing extra needed
      if (typeof parsedSpec === "function") {
        const result = parsedSpec({ d3, container, data: parsedData });
        if (result instanceof Element && !container.contains(result)) {
          container.appendChild(result);
        }
        return;
      }

      // ── JSON spec → dispatch to registered renderer ─────────────────────
      renderFromJsonSpec(container, parsedSpec, parsedData);

    } catch (error) {
      console.error("[D3Adapter] Render failed", error);
      container.innerHTML = `
        <div style="color: red; padding: 12px; border: 1px solid red; border-radius: 4px;">
          <strong>D3 Render Error</strong><br/>
          ${error instanceof Error ? error.message : String(error)}
        </div>
      `;
      throw error;
    }
  },
};

registerGrammarAdapter(d3Adapter);