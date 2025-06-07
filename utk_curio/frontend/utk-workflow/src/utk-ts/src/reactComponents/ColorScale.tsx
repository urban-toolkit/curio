import { useRef, useEffect, useState } from "react";
// importing draggable to drag the div around the screen
import Draggable from "react-draggable";
import {Row} from 'react-bootstrap';
import * as d3 from "d3";
import * as d3_scale from 'd3-scale-chromatic';
import * as d3_scale_s from 'd3-scale';
// import * as d3_color from 'd3-color';

// drag box css
import './Dragbox.css'
// import the bar component to draw bars

// declaring the types of the props
type ColorScaleProps = {
    id: any,
    x: number,
    y: number,
    range: number[],
    domain: number[],
    cmap: string,
    scale: string,
    disp: boolean,
    keyValue: number
}

export const ColorScaleContainer = ({
    id,
    x,
    y,
    range,
    domain,
    cmap,
    scale,
    disp,
    keyValue
}: ColorScaleProps
) =>{
    const nodeRef = useRef(null);

    useEffect(() => {

        // @ts-ignore
        let interpolator = d3_scale[cmap];

        let colors = [ interpolator(1), interpolator(0) ];

        // @ts-ignore
        let scaleColors = d3_scale_s[scale]()
            .domain([0,100])
            .range(colors);

        let colourArray = d3.range(100).map(function(d) {
            return scaleColors(d)
            });
              
        let svg = d3.select('#'+id)
            .append('svg')
            .attr('width', 70)
            .attr('height', 190);

        let grad = svg.append('defs')
            .append('linearGradient')
            .attr('id', 'grad'+id)
            .attr('x1', '0%')
            .attr('x2', '0%')
            .attr('y1', '0%')
            .attr('y2', '100%');

        grad.selectAll('stop')
            .data(colourArray)
            .enter()
            .append('stop')
            .style('stop-color', function(d){ return d; })
            .attr('offset', function(d,i){
                return 100 * (i / (colourArray.length - 1)) + '%';
            });

        svg.append('rect')
            .attr('x', 10)
            .attr('y', 20)
            .attr('width', 50)
            .attr('height', 150)
            .style('fill', 'url(#grad'+id+')');

        svg.append('text')
            .attr("text-anchor", "middle")
            .attr("x", 35)
            .attr("y", 15)
            .text(domain[1]);

        svg.append('text')
            .attr("text-anchor", "middle")
            .attr("x", 35)
            .attr("y", 190)
            .text(domain[0]);
    }, []);

    return(
        <Draggable nodeRef={nodeRef} key={"drag_colorScale"+keyValue+id} defaultPosition={{x: x, y: y}}>
            <div ref={nodeRef} key={"div_colorScale"+keyValue+id} id={id} className="drag-box" style={{display: disp ? 'block' : 'none', backgroundColor: "white", borderRadius: "8px", padding: "10px", border: "1px solid #dadce0", boxShadow: "0 2px 8px 0 rgba(99,99,99,.2)", overflow: "auto", maxWidth: window.innerWidth/2, maxHeight: window.innerHeight, zIndex: 10}}>
            </div>
        </Draggable>
    )
}