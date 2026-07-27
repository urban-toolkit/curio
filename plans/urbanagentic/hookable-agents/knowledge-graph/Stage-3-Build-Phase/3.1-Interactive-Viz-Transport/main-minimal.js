// Minimal Bus Transit Analytics Dashboard - Under 500 Lines
// Focused on minimum requirements: 2+ visual encodings, color encoding, brushing & linking, details-on-demand

const data = [
    { route: '42', day: 'Mon', avg_delay: 8, weather: 'sunny', passengers: 1250 },
    { route: '42', day: 'Tue', avg_delay: 5, weather: 'sunny', passengers: 1180 },
    { route: '42', day: 'Wed', avg_delay: 12, weather: 'rainy', passengers: 1320 },
    { route: '42', day: 'Thu', avg_delay: 7, weather: 'cloudy', passengers: 1200 },
    { route: '42', day: 'Fri', avg_delay: 14, weather: 'rainy', passengers: 1450 },
    { route: '43', day: 'Mon', avg_delay: 15, weather: 'rainy', passengers: 890 },
    { route: '43', day: 'Tue', avg_delay: 12, weather: 'sunny', passengers: 950 },
    { route: '43', day: 'Wed', avg_delay: 18, weather: 'snowy', passengers: 780 },
    { route: '43', day: 'Thu', avg_delay: 13, weather: 'cloudy', passengers: 920 },
    { route: '43', day: 'Fri', avg_delay: 21, weather: 'snowy', passengers: 680 },
    { route: '50', day: 'Mon', avg_delay: 3, weather: 'sunny', passengers: 650 },
    { route: '50', day: 'Tue', avg_delay: 4, weather: 'sunny', passengers: 680 },
    { route: '50', day: 'Wed', avg_delay: 7, weather: 'rainy', passengers: 720 },
    { route: '50', day: 'Thu', avg_delay: 2, weather: 'sunny', passengers: 640 },
    { route: '50', day: 'Fri', avg_delay: 8, weather: 'rainy', passengers: 780 },
    { route: '7', day: 'Mon', avg_delay: 6, weather: 'sunny', passengers: 1100 },
    { route: '7', day: 'Tue', avg_delay: 9, weather: 'rainy', passengers: 1150 },
    { route: '7', day: 'Wed', avg_delay: 11, weather: 'snowy', passengers: 980 },
    { route: '7', day: 'Thu', avg_delay: 5, weather: 'sunny', passengers: 1120 },
    { route: '7', day: 'Fri', avg_delay: 13, weather: 'rainy', passengers: 1050 }
];

// Global variables for brushing & linking
let selectedRoute = null;
let hoveredData = null;

// Chart dimensions
const margin = { top: 30, right: 30, bottom: 50, left: 60 };
const width = 400;
const height = 250;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Starting minimal dashboard...');
    initializeBarChart();
    initializeScatterPlot();
    console.log('✅ Dashboard ready');
});

// BAR CHART: Visual Encoding 1 - Position + Color for delay values
function initializeBarChart() {
    const svg = d3.select('#bar-chart')
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom);

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    // Aggregate data by route
    const routeData = Array.from(d3.rollup(
        data,
        v => ({
            route: v[0].route,
            avgDelay: d3.mean(v, d => d.avg_delay),
            totalPassengers: d3.sum(v, d => d.passengers)
        }),
        d => d.route
    ), ([key, value]) => value).sort((a, b) => a.route.localeCompare(b.route));

    // Scales
    const xScale = d3.scaleBand()
        .domain(routeData.map(d => d.route))
        .range([0, width - margin.left - margin.right])
        .padding(0.2);

    const yScale = d3.scaleLinear()
        .domain([0, d3.max(routeData, d => d.avgDelay) * 1.1])
        .range([height - margin.top - margin.bottom, 0]);

    // COLOR ENCODING: Red-Yellow-Green scale for delay (requirement)
    const colorScale = d3.scaleSequential(d3.interpolateRdYlGn)
        .domain([d3.max(routeData, d => d.avgDelay), 0]);

    // Axes
    g.append('g')
        .attr('transform', `translate(0,${height - margin.top - margin.bottom})`)
        .call(d3.axisBottom(xScale));

    g.append('g')
        .call(d3.axisLeft(yScale));

    // Axis labels
    g.append('text')
        .attr('text-anchor', 'middle')
        .attr('x', (width - margin.left - margin.right) / 2)
        .attr('y', height - margin.top - margin.bottom + 40)
        .style('font-size', '12px')
        .text('Bus Route');

    g.append('text')
        .attr('text-anchor', 'middle')
        .attr('transform', 'rotate(-90)')
        .attr('x', -(height - margin.top - margin.bottom) / 2)
        .attr('y', -40)
        .style('font-size', '12px')
        .text('Average Delay (minutes)');

    // Chart title
    g.append('text')
        .attr('x', (width - margin.left - margin.right) / 2)
        .attr('y', -10)
        .attr('text-anchor', 'middle')
        .style('font-weight', 'bold')
        .text('Average Delays by Route');

    // Bars with color encoding
    const bars = g.selectAll('.bar')
        .data(routeData)
        .enter()
        .append('rect')
        .attr('class', 'bar')
        .attr('x', d => xScale(d.route))
        .attr('width', xScale.bandwidth())
        .attr('y', d => yScale(d.avgDelay))
        .attr('height', d => height - margin.top - margin.bottom - yScale(d.avgDelay))
        .attr('fill', d => colorScale(d.avgDelay))
        .attr('stroke', 'none')
        .style('cursor', 'pointer');

    // BRUSHING & LINKING: Click to select route (requirement)
    bars.on('click', function(event, d) {
        selectedRoute = selectedRoute === d.route ? null : d.route;
        updateChartSelection();
        updateScatterPlot(); // Link to scatter plot
    });

    // DETAILS-ON-DEMAND: Hover for tooltip (requirement)
    bars.on('mouseover', function(event, d) {
        d3.select(this).attr('stroke', '#333').attr('stroke-width', 2);
        showTooltip(event, `
            <strong>Route ${d.route}</strong><br/>
            Avg Delay: ${d.avgDelay.toFixed(1)} min<br/>
            Total Passengers: ${d.totalPassengers.toLocaleString()}<br/>
            Performance: ${d.avgDelay <= 5 ? '🟢 Good' : d.avgDelay <= 10 ? '🟡 Fair' : '🔴 Poor'}
        `);
    });

    bars.on('mouseout', function(event, d) {
        if (selectedRoute !== d.route) {
            d3.select(this).attr('stroke', 'none');
        }
        hideTooltip();
    });

    // Update selection styling
    function updateChartSelection() {
        bars.attr('stroke', d => selectedRoute === d.route ? '#1f2937' : 'none')
            .attr('stroke-width', d => selectedRoute === d.route ? 3 : 0)
            .style('opacity', d => selectedRoute === null || selectedRoute === d.route ? 1 : 0.5);
    }
}

// SCATTER PLOT: Visual Encoding 2 - Position (X/Y) + Size + Color for multiple variables
function initializeScatterPlot() {
    const svg = d3.select('#scatter-chart')
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom);

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    updateScatterPlot();

    function updateScatterPlot() {
        // Filter data based on selected route (brushing & linking)
        const plotData = selectedRoute ? 
            data.filter(d => d.route === selectedRoute) : 
            data;

        // Clear previous plot
        g.selectAll('*').remove();

        // Scales
        const xScale = d3.scaleLinear()
            .domain(d3.extent(data, d => d.avg_delay))
            .range([0, width - margin.left - margin.right]);

        const yScale = d3.scaleLinear()
            .domain(d3.extent(data, d => d.passengers))
            .range([height - margin.top - margin.bottom, 0]);

        // SIZE ENCODING: Circle size represents passengers (visual encoding technique)
        const sizeScale = d3.scaleSqrt()
            .domain(d3.extent(data, d => d.passengers))
            .range([4, 20]);

        // COLOR ENCODING: Weather conditions (another color encoding)
        const weatherColors = {
            'sunny': '#fbbf24',    // Yellow
            'rainy': '#3b82f6',    // Blue  
            'snowy': '#e5e7eb',    // Light gray
            'cloudy': '#6b7280'    // Dark gray
        };

        // Axes
        g.append('g')
            .attr('transform', `translate(0,${height - margin.top - margin.bottom})`)
            .call(d3.axisBottom(xScale));

        g.append('g')
            .call(d3.axisLeft(yScale));

        // Axis labels
        g.append('text')
            .attr('text-anchor', 'middle')
            .attr('x', (width - margin.left - margin.right) / 2)
            .attr('y', height - margin.top - margin.bottom + 40)
            .style('font-size', '12px')
            .text('Average Delay (minutes)');

        g.append('text')
            .attr('text-anchor', 'middle')
            .attr('transform', 'rotate(-90)')
            .attr('x', -(height - margin.top - margin.bottom) / 2)
            .attr('y', -40)
            .style('font-size', '12px')
            .text('Passengers');

        // Chart title
        const title = selectedRoute ? 
            `Route ${selectedRoute} - Delay vs Passengers` : 
            'All Routes - Delay vs Passengers by Weather';
        
        g.append('text')
            .attr('x', (width - margin.left - margin.right) / 2)
            .attr('y', -10)
            .attr('text-anchor', 'middle')
            .style('font-weight', 'bold')
            .text(title);

        // CIRCLES: Multiple visual encodings (position X/Y, size, color)
        const circles = g.selectAll('.circle')
            .data(plotData)
            .enter()
            .append('circle')
            .attr('class', 'circle')
            .attr('cx', d => xScale(d.avg_delay))
            .attr('cy', d => yScale(d.passengers))
            .attr('r', d => sizeScale(d.passengers))
            .attr('fill', d => weatherColors[d.weather])
            .attr('stroke', '#333')
            .attr('stroke-width', 1)
            .style('opacity', 0.8)
            .style('cursor', 'pointer');

        // DETAILS-ON-DEMAND: Hover interactions (requirement)
        circles.on('mouseover', function(event, d) {
            d3.select(this)
                .attr('stroke-width', 3)
                .style('opacity', 1);
            
            showTooltip(event, `
                <strong>Route ${d.route} - ${d.day}</strong><br/>
                Delay: ${d.avg_delay} minutes<br/>
                Passengers: ${d.passengers.toLocaleString()}<br/>
                Weather: ${d.weather.charAt(0).toUpperCase() + d.weather.slice(1)}<br/>
                Status: ${d.avg_delay <= 5 ? '✅ On Time' : '⚠️ Delayed'}
            `);
        });

        circles.on('mouseout', function() {
            d3.select(this)
                .attr('stroke-width', 1)
                .style('opacity', 0.8);
            hideTooltip();
        });

        // Add weather legend
        const legend = g.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(${width - margin.left - margin.right - 100}, 20)`);

        const weatherTypes = Object.keys(weatherColors);
        const legendItems = legend.selectAll('.legend-item')
            .data(weatherTypes)
            .enter()
            .append('g')
            .attr('class', 'legend-item')
            .attr('transform', (d, i) => `translate(0, ${i * 20})`);

        legendItems.append('circle')
            .attr('r', 6)
            .attr('fill', d => weatherColors[d])
            .attr('stroke', '#333');

        legendItems.append('text')
            .attr('x', 12)
            .attr('y', 4)
            .style('font-size', '11px')
            .text(d => d.charAt(0).toUpperCase() + d.slice(1));
    }

    // Expose update function for brushing & linking
    window.updateScatterPlot = updateScatterPlot;
}

// TOOLTIP FUNCTIONS: Details-on-demand implementation
function showTooltip(event, content) {
    let tooltip = d3.select('#tooltip');
    if (tooltip.empty()) {
        tooltip = d3.select('body')
            .append('div')
            .attr('id', 'tooltip')
            .style('position', 'absolute')
            .style('background', 'rgba(0, 0, 0, 0.9)')
            .style('color', 'white')
            .style('padding', '12px')
            .style('border-radius', '6px')
            .style('font-size', '12px')
            .style('pointer-events', 'none')
            .style('opacity', 0)
            .style('z-index', 1000);
    }
    
    tooltip.style('opacity', 1)
        .html(content)
        .style('left', (event.pageX + 10) + 'px')
        .style('top', (event.pageY - 10) + 'px');
}

function hideTooltip() {
    d3.select('#tooltip').style('opacity', 0);
}

// Initialize dashboard when ready
console.log('📊 Bus Transit Dashboard Ready');
console.log('✅ Requirements: Visual encodings, Color channels, Brushing & linking, Details-on-demand');
