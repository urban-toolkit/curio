/**
 * `DataflowThumbnail` with a scenario marked on it, and without.
 *
 * The plain drawing is the Projects page's card thumbnail, which screenshot
 * baselines hold. So the half without a highlight pins it attribute for
 * attribute: the elements it draws, the attributes each one carries and their
 * literal colours, and that none of what a highlight adds is present.
 */
import React from "react";
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";

import DataflowThumbnail from "../../components/DataflowThumbnail";
import { HEAT_PREVIEW } from "../_support/scenarioRows";

const COLOR = "#3567c7";

function svgOf(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector("svg");
  if (!svg) throw new Error("no svg");
  return svg;
}

const names = (el: Element) =>
  el
    .getAttributeNames()
    .map((n) => n.toLowerCase())
    .sort();

/** Each node's group, by node id: the preview's order is the drawing's. */
function nodeGroups(svg: SVGSVGElement): Map<string, SVGGElement> {
  const groups = Array.from(svg.querySelectorAll("g")) as SVGGElement[];
  return new Map(HEAT_PREVIEW.nodes.map((node, i) => [node.id, groups[i]]));
}

describe("DataflowThumbnail without a highlight", () => {
  const plain = () => svgOf(render(<DataflowThumbnail preview={HEAT_PREVIEW} />).container);

  test("draws the background, one line per edge and two boxes per node", () => {
    const svg = plain();
    const nodes = HEAT_PREVIEW.nodes.length;
    const edges = HEAT_PREVIEW.edges.length;
    expect(svg.querySelectorAll("rect")).toHaveLength(1 + 2 * nodes);
    expect(svg.querySelectorAll("line")).toHaveLength(edges);
    expect(svg.querySelectorAll("g")).toHaveLength(nodes);
    expect(svg.querySelectorAll("*")).toHaveLength(1 + edges + 3 * nodes);
  });

  test("every element carries exactly the attributes it always had", () => {
    const svg = plain();
    expect(names(svg)).toEqual(
      ["height", "preserveaspectratio", "style", "viewbox", "width"].sort(),
    );
    const [background, ...boxes] = Array.from(svg.querySelectorAll("rect"));
    expect(names(background)).toEqual(["fill", "height", "width", "x", "y"]);
    expect(background).toHaveAttribute("fill", "#f5f5f5");

    for (const line of Array.from(svg.querySelectorAll("line"))) {
      expect(names(line)).toEqual(["stroke", "stroke-width", "x1", "x2", "y1", "y2"]);
      expect(line).toHaveAttribute("stroke", "#c8c8c8");
      expect(line).toHaveAttribute("stroke-width", "1");
    }

    for (const g of Array.from(svg.querySelectorAll("g"))) {
      expect(names(g)).toEqual([]);
    }

    // Each node: the white box, then its colour bar.
    for (let i = 0; i < boxes.length; i += 2) {
      const [box, bar] = [boxes[i], boxes[i + 1]];
      expect(names(box)).toEqual(
        ["fill", "height", "rx", "stroke", "stroke-width", "width", "x", "y"].sort(),
      );
      expect(box).toHaveAttribute("fill", "#ffffff");
      expect(box).toHaveAttribute("stroke", "#e0e0e0");
      expect(box).toHaveAttribute("stroke-width", "0.5");
      expect(box).toHaveAttribute("rx", "2");
      expect(names(bar)).toEqual(["fill", "height", "rx", "width", "x", "y"]);
      expect(bar).toHaveAttribute("width", "3");
      expect(bar).toHaveAttribute("rx", "1");
    }
  });

  test("carries nothing a highlight adds", () => {
    const svg = plain();
    for (const el of [svg, ...Array.from(svg.querySelectorAll("*"))]) {
      expect(el).not.toHaveAttribute("opacity");
      expect(el).not.toHaveAttribute("fill-opacity");
      expect(el).not.toHaveAttribute("stroke-dasharray");
      expect(el.getAttributeNames().filter((n) => n.startsWith("data-"))).toEqual([]);
    }
  });

  test("a null highlight draws the very same markup", () => {
    const a = render(<DataflowThumbnail preview={HEAT_PREVIEW} />).container.innerHTML;
    const b = render(<DataflowThumbnail preview={HEAT_PREVIEW} highlight={null} />).container
      .innerHTML;
    expect(b).toBe(a);
  });
});

describe("DataflowThumbnail with a highlight", () => {
  const marked = () =>
    svgOf(
      render(
        <DataflowThumbnail
          preview={HEAT_PREVIEW}
          highlight={{ color: COLOR, members: ["year", "filter"], context: ["load"] }}
        />,
      ).container,
    );

  test("draws the same elements as the plain drawing", () => {
    const svg = marked();
    expect(svg).toHaveAttribute("data-thumbnail-highlight", "true");
    expect(svg.querySelectorAll("rect")).toHaveLength(1 + 2 * HEAT_PREVIEW.nodes.length);
    expect(svg.querySelectorAll("line")).toHaveLength(HEAT_PREVIEW.edges.length);
  });

  test("outlines and tints the members in the scenario's colour", () => {
    const groups = nodeGroups(marked());
    for (const id of ["year", "filter"]) {
      const g = groups.get(id)!;
      expect(g).toHaveAttribute("data-thumbnail-role", "member");
      expect(g).not.toHaveAttribute("opacity");
      const box = g.querySelector("rect")!;
      expect(box).toHaveAttribute("stroke", COLOR);
      expect(box).toHaveAttribute("fill", COLOR);
      expect(box).toHaveAttribute("fill-opacity", "0.18");
    }
  });

  test("gives the context a dark dashed outline", () => {
    const g = nodeGroups(marked()).get("load")!;
    expect(g).toHaveAttribute("data-thumbnail-role", "context");
    expect(g).not.toHaveAttribute("opacity");
    const box = g.querySelector("rect")!;
    expect(box).toHaveAttribute("stroke", "#2f3034");
    expect(box).toHaveAttribute("stroke-dasharray");
    expect(box).toHaveAttribute("fill", "#ffffff");
  });

  test("fades every other node", () => {
    const g = nodeGroups(marked()).get("chart")!;
    expect(g).toHaveAttribute("data-thumbnail-role", "faded");
    expect(g).toHaveAttribute("opacity", "0.3");
    expect(g.querySelector("rect")).toHaveAttribute("stroke", "#e0e0e0");
  });

  test("draws an edge between two members in the colour, and fades one to a faded node", () => {
    const lines = Array.from(marked().querySelectorAll("line"));
    const byEnds = new Map(
      HEAT_PREVIEW.edges.map((e, i) => [`${e.source}>${e.target}`, lines[i]]),
    );
    expect(byEnds.get("year>filter")).toHaveAttribute("stroke", COLOR);
    expect(byEnds.get("load>filter")).toHaveAttribute("stroke", "#c8c8c8");
    expect(byEnds.get("load>filter")).not.toHaveAttribute("opacity");
    expect(byEnds.get("filter>chart")).toHaveAttribute("opacity", "0.3");
  });
});
