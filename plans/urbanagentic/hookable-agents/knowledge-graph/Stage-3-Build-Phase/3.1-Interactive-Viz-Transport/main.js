// Enhanced Bus Transit Analytics Dashboard - Working Version
// Data with comprehensive dataset for demonstration
const data = [
    { route: '42', day: 'Mon', avg_delay: 8, lat: 41.8781, lon: -87.6298, weather: 'sunny', time_period: 'morning', passengers: 1250 },
    { route: '42', day: 'Tue', avg_delay: 5, lat: 41.8781, lon: -87.6298, weather: 'sunny', time_period: 'morning', passengers: 1180 },
    { route: '42', day: 'Wed', avg_delay: 12, lat: 41.8781, lon: -87.6298, weather: 'rainy', time_period: 'evening', passengers: 1320 },
    { route: '42', day: 'Thu', avg_delay: 7, lat: 41.8781, lon: -87.6298, weather: 'cloudy', time_period: 'morning', passengers: 1200 },
    { route: '42', day: 'Fri', avg_delay: 14, lat: 41.8781, lon: -87.6298, weather: 'rainy', time_period: 'evening', passengers: 1450 },
    { route: '43', day: 'Mon', avg_delay: 15, lat: 41.8881, lon: -87.6598, weather: 'rainy', time_period: 'morning', passengers: 890 },
    { route: '43', day: 'Tue', avg_delay: 12, lat: 41.8881, lon: -87.6598, weather: 'sunny', time_period: 'evening', passengers: 950 },
    { route: '43', day: 'Wed', avg_delay: 18, lat: 41.8881, lon: -87.6598, weather: 'snowy', time_period: 'morning', passengers: 780 },
    { route: '43', day: 'Thu', avg_delay: 13, lat: 41.8881, lon: -87.6598, weather: 'cloudy', time_period: 'evening', passengers: 920 },
    { route: '43', day: 'Fri', avg_delay: 21, lat: 41.8881, lon: -87.6598, weather: 'snowy', time_period: 'morning', passengers: 680 },
    { route: '50', day: 'Mon', avg_delay: 3, lat: 41.9081, lon: -87.6898, weather: 'sunny', time_period: 'midday', passengers: 650 },
    { route: '50', day: 'Tue', avg_delay: 4, lat: 41.9081, lon: -87.6898, weather: 'sunny', time_period: 'midday', passengers: 680 },
    { route: '50', day: 'Wed', avg_delay: 7, lat: 41.9081, lon: -87.6898, weather: 'rainy', time_period: 'evening', passengers: 720 },
    { route: '50', day: 'Thu', avg_delay: 2, lat: 41.9081, lon: -87.6898, weather: 'sunny', time_period: 'midday', passengers: 640 },
    { route: '50', day: 'Fri', avg_delay: 8, lat: 41.9081, lon: -87.6898, weather: 'rainy', time_period: 'evening', passengers: 780 },
    { route: '7', day: 'Mon', avg_delay: 6, lat: 41.8681, lon: -87.6198, weather: 'sunny', time_period: 'morning', passengers: 1100 },
    { route: '7', day: 'Tue', avg_delay: 9, lat: 41.8681, lon: -87.6198, weather: 'rainy', time_period: 'evening', passengers: 1150 },
    { route: '7', day: 'Wed', avg_delay: 11, lat: 41.8681, lon: -87.6198, weather: 'snowy', time_period: 'morning', passengers: 980 },
    { route: '7', day: 'Thu', avg_delay: 5, lat: 41.8681, lon: -87.6198, weather: 'sunny', time_period: 'evening', passengers: 1120 },
    { route: '7', day: 'Fri', avg_delay: 13, lat: 41.8681, lon: -87.6198, weather: 'rainy', time_period: 'morning', passengers: 1050 },
    // Additional weekend data
    { route: '42', day: 'Sat', avg_delay: 4, lat: 41.8781, lon: -87.6298, weather: 'sunny', time_period: 'midday', passengers: 800 },
    { route: '43', day: 'Sat', avg_delay: 6, lat: 41.8881, lon: -87.6598, weather: 'cloudy', time_period: 'midday', passengers: 600 },
    { route: '50', day: 'Sat', avg_delay: 3, lat: 41.9081, lon: -87.6898, weather: 'sunny', time_period: 'evening', passengers: 450 },
    { route: '7', day: 'Sat', avg_delay: 5, lat: 41.8681, lon: -87.6198, weather: 'cloudy', time_period: 'morning', passengers: 700 }
];

// Global variables
let filteredData = [...data];
let selectedRoute = null;
let filterTimeout = null; // For debouncing
let currentFilters = {
    day: 'all',
    weather: 'all',
    time: 'all',
    route: 'all'
};

// Performance cache
const dataCache = new Map();
const CACHE_KEY_PREFIX = 'dashboard_cache_';

// Dimensions and configuration - Optimized for new layout
const margin = { top: 20, right: 30, bottom: 50, left: 60 };
const width = 300;   // Adjusted for smaller chart containers
const height = 220;  // Good height for visibility
const mapWidth = 450;  // Larger for map
const mapHeight = 320;

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 Dashboard starting...');
    
    try {
        // Hide loading indicators and show charts
        setTimeout(() => {
            d3.selectAll('.loading').style('display', 'none');
        }, 500);
        
        // Initialize all components
        updateStatistics();
        initializeFilters();
        populateRouteFilter(); // Add route options dynamically
        initializeBarChart();
        initializeLineChart();
        initializeMapChart();
        
        // Initialize filter presets
        initializePresets();
        
        console.log('✅ Dashboard loaded successfully');
    } catch (error) {
        console.error('❌ Error:', error);
        showError('Failed to load dashboard');
    }
});

// Update statistics panel - Optimized with better calculations
function updateStatistics() {
    if (filteredData.length === 0) {
        d3.select('#total-routes').text('0');
        d3.select('#avg-delay').text('--');
        d3.select('#worst-route').text('--');
        d3.select('#on-time-rate').text('--');
        return;
    }
    
    const routes = new Set(filteredData.map(d => d.route));
    const avgDelay = d3.mean(filteredData, d => d.avg_delay) || 0;
    
    // Find worst route more efficiently
    const routeStats = d3.rollup(
        filteredData,
        v => ({
            avgDelay: d3.mean(v, d => d.avg_delay),
            count: v.length
        }),
        d => d.route
    );
    
    let worstRoute = '';
    let maxAvg = 0;
    routeStats.forEach((stats, route) => {
        if (stats.avgDelay > maxAvg) {
            maxAvg = stats.avgDelay;
            worstRoute = route;
        }
    });
    
    const onTimeRate = (filteredData.filter(d => d.avg_delay <= 5).length / filteredData.length) * 100;
    
    // Animate number changes
    animateValue('#total-routes', routes.size);
    animateValue('#avg-delay', avgDelay.toFixed(1));
    animateText('#worst-route', worstRoute || 'N/A');
    animateValue('#on-time-rate', onTimeRate.toFixed(0) + '%');
}

// Animate value changes for better UX
function animateValue(selector, newValue) {
    const element = d3.select(selector);
    const currentValue = element.text();
    
    if (currentValue !== newValue.toString()) {
        element.style('transform', 'scale(1.1)')
            .style('color', '#667eea')
            .transition()
            .duration(200)
            .style('transform', 'scale(1)')
            .style('color', '#333')
            .tween('text', function() {
                const node = this;
                const isNumber = !isNaN(parseFloat(currentValue));
                
                if (isNumber && !newValue.toString().includes('%')) {
                    const i = d3.interpolateNumber(parseFloat(currentValue) || 0, parseFloat(newValue));
                    return function(t) {
                        node.textContent = i(t).toFixed(1);
                    };
                } else {
                    return function(t) {
                        if (t > 0.5) node.textContent = newValue;
                    };
                }
            });
    }
}

// Animate text changes
function animateText(selector, newText) {
    const element = d3.select(selector);
    const currentText = element.text();
    
    if (currentText !== newText) {
        element.style('opacity', 0.5)
            .transition()
            .duration(150)
            .style('opacity', 1)
            .text(newText);
    }
}

// Initialize filter controls - Enhanced with performance optimization
function initializeFilters() {
    // Debounced filter function for better performance
    const debouncedApplyFilters = debounce(applyFilters, 150);
    
    // Day filter
    d3.select('#day-filter').on('change', function() {
        currentFilters.day = this.value;
        debouncedApplyFilters();
    });
    
    // Weather filter
    d3.select('#weather-filter').on('change', function() {
        currentFilters.weather = this.value;
        debouncedApplyFilters();
    });
    
    // Time filter
    d3.select('#time-filter').on('change', function() {
        currentFilters.time = this.value;
        debouncedApplyFilters();
    });
    
    // Route filter
    d3.select('#route-filter').on('change', function() {
        currentFilters.route = this.value;
        selectedRoute = this.value === 'all' ? null : this.value;
        debouncedApplyFilters();
    });
    
    // Reset button
    d3.select('#reset-filters').on('click', resetAllFilters);
}

// Populate route filter dynamically
function populateRouteFilter() {
    const routes = [...new Set(data.map(d => d.route))].sort();
    const routeSelect = d3.select('#route-filter');
    
    routes.forEach(route => {
        routeSelect.append('option')
            .attr('value', route)
            .text(`Route ${route}`);
    });
}

// Initialize filter presets
function initializePresets() {
    d3.selectAll('.preset-btn').on('click', function() {
        const preset = this.dataset.preset;
        applyPreset(preset);
        
        // Visual feedback
        d3.selectAll('.preset-btn').classed('active', false);
        d3.select(this).classed('active', true);
        
        setTimeout(() => {
            d3.select(this).classed('active', false);
        }, 2000);
    });
}

// Apply filter presets
function applyPreset(preset) {
    resetAllFilters();
    
    switch(preset) {
        case 'peak-hours':
            d3.select('#time-filter').node().value = 'morning';
            currentFilters.time = 'morning';
            showSuccess('Showing morning rush hour data');
            break;
        case 'bad-weather':
            d3.select('#weather-filter').node().value = 'rainy';
            currentFilters.weather = 'rainy';
            showSuccess('Showing rainy weather data');
            break;
        case 'weekend':
            d3.select('#day-filter').node().value = 'Sat';
            currentFilters.day = 'Sat';
            showSuccess('Showing weekend data');
            break;
    }
    
    applyFilters();
}

// Reset all filters
function resetAllFilters() {
    currentFilters = {
        day: 'all',
        weather: 'all',
        time: 'all',
        route: 'all'
    };
    
    d3.select('#day-filter').node().value = 'all';
    d3.select('#weather-filter').node().value = 'all';
    d3.select('#time-filter').node().value = 'all';
    d3.select('#route-filter').node().value = 'all';
    
    selectedRoute = null;
    
    // Clear cache when resetting
    dataCache.clear();
    
    applyFilters();
    showSuccess('All filters reset');
}

// Apply all filters to data - Optimized with caching
function applyFilters() {
    // Create cache key from current filters
    const cacheKey = CACHE_KEY_PREFIX + JSON.stringify(currentFilters);
    
    // Check cache first
    if (dataCache.has(cacheKey)) {
        filteredData = dataCache.get(cacheKey);
    } else {
        // Filter data
        filteredData = data.filter(d => {
            return (currentFilters.day === 'all' || d.day === currentFilters.day) &&
                   (currentFilters.weather === 'all' || d.weather === currentFilters.weather) &&
                   (currentFilters.time === 'all' || d.time_period === currentFilters.time) &&
                   (currentFilters.route === 'all' || d.route === currentFilters.route);
        });
        
        // Cache the result
        dataCache.set(cacheKey, filteredData);
    }
    
    // Reset route selection if it's not in filtered data
    if (selectedRoute && !filteredData.some(d => d.route === selectedRoute)) {
        selectedRoute = null;
        d3.select('#route-filter').node().value = 'all';
        currentFilters.route = 'all';
    }
    
    // Update filter status
    updateFilterStatus();
    
    // Update all visualizations with performance optimization
    requestAnimationFrame(() => {
        updateStatistics();
        updateBarChart();
        updateLineChart();
        updateMapChart();
    });
}

// Update filter status display
function updateFilterStatus() {
    const totalRecords = data.length;
    const filteredRecords = filteredData.length;
    
    let statusText = 'All data shown';
    if (filteredRecords < totalRecords) {
        const activeFilters = [];
        if (currentFilters.day !== 'all') activeFilters.push('Day');
        if (currentFilters.weather !== 'all') activeFilters.push('Weather');
        if (currentFilters.time !== 'all') activeFilters.push('Time');
        if (currentFilters.route !== 'all') activeFilters.push('Route');
        
        statusText = `Filtered by: ${activeFilters.join(', ')}`;
    }
    
    d3.select('#filter-count').text(statusText);
    d3.select('#data-count').text(`${filteredRecords} of ${totalRecords} records`);
}

// Debounce utility function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Initialize Bar Chart
function initializeBarChart() {
    const svg = d3.select('#bar-svg');
    svg.selectAll('*').remove();
    
    // Set SVG dimensions
    svg.attr('viewBox', `0 0 ${width} ${height}`)
       .attr('preserveAspectRatio', 'xMidYMid meet');
    
    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);
    
    // Add axes groups
    g.append('g').attr('class', 'x-axis');
    g.append('g').attr('class', 'y-axis');
    
    // Add axis labels
    g.append('text')
        .attr('class', 'axis-label')
        .attr('text-anchor', 'middle')
        .attr('x', (width - margin.left - margin.right) / 2)
        .attr('y', height - margin.top - margin.bottom + 40)
        .style('font-size', '12px')
        .style('fill', '#666')
        .text('Bus Route');
    
    g.append('text')
        .attr('class', 'axis-label')
        .attr('text-anchor', 'middle')
        .attr('transform', 'rotate(-90)')
        .attr('x', -(height - margin.top - margin.bottom) / 2)
        .attr('y', -40)
        .style('font-size', '12px')
        .style('fill', '#666')
        .text('Average Delay (minutes)');
    
    updateBarChart();
}

// Update Bar Chart with current data - Performance optimized
function updateBarChart() {
    const svg = d3.select('#bar-svg');
    const g = svg.select('g');
    
    // Aggregate data by route
    const routeData = Array.from(d3.rollup(
        filteredData,
        v => ({
            route: v[0].route,
            avgDelay: d3.mean(v, d => d.avg_delay),
            totalPassengers: d3.sum(v, d => d.passengers)
        }),
        d => d.route
    ), ([key, value]) => value).sort((a, b) => a.route.localeCompare(b.route));
    
    if (routeData.length === 0) {
        g.selectAll('.bar').remove();
        return;
    }
    
    // Create scales
    const xScale = d3.scaleBand()
        .domain(routeData.map(d => d.route))
        .range([0, width - margin.left - margin.right])
        .padding(0.1);
    
    const yScale = d3.scaleLinear()
        .domain([0, d3.max(routeData, d => d.avgDelay) * 1.1])
        .range([height - margin.top - margin.bottom, 0]);
    
    const colorScale = d3.scaleSequential(d3.interpolateRdYlGn)
        .domain([d3.max(routeData, d => d.avgDelay), 0]);
    
    // Update axes with improved styling
    g.select('.x-axis')
        .attr('transform', `translate(0,${height - margin.top - margin.bottom})`)
        .transition()
        .duration(500)
        .call(d3.axisBottom(xScale))
        .selectAll('text')
        .style('font-size', '12px')
        .style('font-weight', '500');
    
    g.select('.y-axis')
        .transition()
        .duration(500)
        .call(d3.axisLeft(yScale).ticks(6))
        .selectAll('text')
        .style('font-size', '12px');
    
    // Update bars with improved animations
    const bars = g.selectAll('.bar')
        .data(routeData, d => d.route);
    
    bars.exit()
        .transition()
        .duration(500)
        .attr('height', 0)
        .attr('y', yScale(0))
        .style('opacity', 0)
        .remove();
    
    const barsEnter = bars.enter()
        .append('rect')
        .attr('class', 'bar')
        .attr('x', d => xScale(d.route))
        .attr('width', xScale.bandwidth())
        .attr('y', yScale(0))
        .attr('height', 0)
        .style('cursor', 'pointer')
        .style('opacity', 0);
    
    bars.merge(barsEnter)
        .classed('selected', d => d.route === selectedRoute)
        .transition()
        .duration(750)
        .ease(d3.easeBackOut.overshoot(1.2))
        .attr('x', d => xScale(d.route))
        .attr('width', xScale.bandwidth())
        .attr('y', d => yScale(d.avgDelay))
        .attr('height', d => height - margin.top - margin.bottom - yScale(d.avgDelay))
        .attr('fill', d => colorScale(d.avgDelay))
        .style('opacity', 1)
        .attr('stroke', d => d.route === selectedRoute ? '#1f2937' : 'none')
        .attr('stroke-width', d => d.route === selectedRoute ? 2 : 0);
    
    // Add event handlers with improved interactions
    g.selectAll('.bar')
        .on('click', function(event, d) {
            selectedRoute = selectedRoute === d.route ? null : d.route;
            currentFilters.route = selectedRoute || 'all';
            d3.select('#route-filter').node().value = currentFilters.route;
            
            // Visual feedback
            d3.select(this)
                .transition()
                .duration(100)
                .attr('transform', 'scale(1.05)')
                .transition()
                .duration(100)
                .attr('transform', 'scale(1)');
            
            updateBarChart();
            updateLineChart();
            updateMapChart();
        })
        .on('mouseover', function(event, d) {
            d3.select(this)
                .transition()
                .duration(150)
                .attr('stroke', '#374151')
                .attr('stroke-width', 1)
                .style('filter', 'brightness(1.1)');
                
            showTooltip(event, `
                <strong>Route ${d.route}</strong><br/>
                Avg Delay: <span style="color: ${d.avgDelay <= 5 ? '#10b981' : d.avgDelay <= 10 ? '#f59e0b' : '#ef4444'}">${d.avgDelay.toFixed(1)} min</span><br/>
                Passengers: ${d.totalPassengers.toLocaleString()}<br/>
                <em>Click to ${selectedRoute === d.route ? 'deselect' : 'filter by this route'}</em>
            `);
        })
        .on('mouseout', function(event, d) {
            if (d.route !== selectedRoute) {
                d3.select(this)
                    .transition()
                    .duration(150)
                    .attr('stroke', 'none')
                    .attr('stroke-width', 0)
                    .style('filter', 'none');
            }
            hideTooltip();
        });
}

// Initialize Line Chart
function initializeLineChart() {
    const svg = d3.select('#line-svg');
    svg.selectAll('*').remove();
    
    // Set SVG dimensions
    svg.attr('viewBox', `0 0 ${width} ${height}`)
       .attr('preserveAspectRatio', 'xMidYMid meet');
    
    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);
    
    // Add axes groups
    g.append('g').attr('class', 'x-axis');
    g.append('g').attr('class', 'y-axis');
    
    // Add axis labels
    g.append('text')
        .attr('class', 'axis-label')
        .attr('text-anchor', 'middle')
        .attr('x', (width - margin.left - margin.right) / 2)
        .attr('y', height - margin.top - margin.bottom + 40)
        .style('font-size', '12px')
        .style('fill', '#666')
        .text('Day of Week');
    
    g.append('text')
        .attr('class', 'axis-label')
        .attr('text-anchor', 'middle')
        .attr('transform', 'rotate(-90)')
        .attr('x', -(height - margin.top - margin.bottom) / 2)
        .attr('y', -40)
        .style('font-size', '12px')
        .style('fill', '#666')
        .text('Delay (minutes)');
    
    updateLineChart();
}

// Update Line Chart with current data
function updateLineChart() {
    const svg = d3.select('#line-svg');
    const g = svg.select('g');
    
    // Filter data for selected route or show aggregated data
    let lineData = filteredData;
    if (selectedRoute) {
        lineData = filteredData.filter(d => d.route === selectedRoute);
    }
    
    if (lineData.length === 0) {
        g.selectAll('.line, .dot').remove();
        return;
    }
    
    // Aggregate by day if showing all routes
    if (!selectedRoute) {
        const dayAgg = d3.rollup(
            lineData,
            v => d3.mean(v, d => d.avg_delay),
            d => d.day
        );
        lineData = Array.from(dayAgg, ([day, avg_delay]) => ({ day, avg_delay }));
    }
    
    // Sort by day order
    const dayOrder = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    lineData.sort((a, b) => dayOrder.indexOf(a.day) - dayOrder.indexOf(b.day));
    
    // Create scales
    const xScale = d3.scaleBand()
        .domain(dayOrder)
        .range([0, width - margin.left - margin.right])
        .padding(0.1);
    
    const yScale = d3.scaleLinear()
        .domain([0, d3.max(lineData, d => d.avg_delay) * 1.1])
        .range([height - margin.top - margin.bottom, 0]);
    
    // Update axes
    g.select('.x-axis')
        .attr('transform', `translate(0,${height - margin.top - margin.bottom})`)
        .call(d3.axisBottom(xScale))
        .selectAll('text')
        .style('font-size', '12px');
    
    g.select('.y-axis')
        .call(d3.axisLeft(yScale))
        .selectAll('text')
        .style('font-size', '12px');
    
    // Line generator
    const line = d3.line()
        .x(d => xScale(d.day) + xScale.bandwidth() / 2)
        .y(d => yScale(d.avg_delay))
        .curve(d3.curveMonotoneX);
    
    // Update line
    const linePath = g.selectAll('.line')
        .data([lineData]);
    
    linePath.exit().remove();
    
    linePath.enter()
        .append('path')
        .attr('class', 'line')
        .merge(linePath)
        .transition()
        .duration(750)
        .attr('d', line)
        .attr('fill', 'none')
        .attr('stroke', selectedRoute ? '#2563eb' : '#667eea')
        .attr('stroke-width', 3)
        .attr('stroke-linejoin', 'round')
        .attr('stroke-linecap', 'round');
    
    // Update dots
    const dots = g.selectAll('.dot')
        .data(lineData);
    
    dots.exit().remove();
    
    dots.enter()
        .append('circle')
        .attr('class', 'dot')
        .attr('r', 0)
        .merge(dots)
        .transition()
        .duration(750)
        .attr('cx', d => xScale(d.day) + xScale.bandwidth() / 2)
        .attr('cy', d => yScale(d.avg_delay))
        .attr('r', 5)
        .attr('fill', selectedRoute ? '#2563eb' : '#667eea')
        .attr('stroke', 'white')
        .attr('stroke-width', 2)
        .style('cursor', 'pointer');
    
    // Add event handlers to dots
    g.selectAll('.dot')
        .on('mouseover', function(event, d) {
            const originalData = filteredData.find(fd => fd.day === d.day && (selectedRoute ? fd.route === selectedRoute : true));
            const tooltipContent = selectedRoute 
                ? `
                    <strong>${d.day} - Route ${selectedRoute}</strong><br/>
                    Delay: ${d.avg_delay} min<br/>
                    Weather: ${originalData?.weather || 'N/A'}<br/>
                    Passengers: ${originalData?.passengers?.toLocaleString() || 'N/A'}
                  `
                : `
                    <strong>${d.day} - All Routes</strong><br/>
                    Avg Delay: ${d.avg_delay.toFixed(1)} min
                  `;
            showTooltip(event, tooltipContent);
        })
        .on('mouseout', hideTooltip);
}

// Initialize Map Chart
function initializeMapChart() {
    const svg = d3.select('#map-svg');
    svg.selectAll('*').remove();
    
    // Set SVG dimensions for map
    svg.attr('viewBox', `0 0 ${mapWidth} ${mapHeight}`)
       .attr('preserveAspectRatio', 'xMidYMid meet');
    
    const g = svg.append('g')
        .attr('transform', 'translate(20,20)');
    
    // Add background city grid - larger dimensions for map
    const gridGroup = g.append('g').attr('class', 'city-grid');
    
    // Create city blocks (grid pattern) - larger for map
    const blockSize = 30;
    const gridWidth = 400;
    const gridHeight = 260;
    
    // Vertical streets
    for (let x = 0; x <= gridWidth; x += blockSize) {
        gridGroup.append('line')
            .attr('x1', x).attr('y1', 0)
            .attr('x2', x).attr('y2', gridHeight)
            .attr('stroke', '#e5e7eb')
            .attr('stroke-width', x % (blockSize * 2) === 0 ? 1.5 : 0.8)
            .attr('opacity', 0.6);
    }
    
    // Horizontal streets
    for (let y = 0; y <= gridHeight; y += blockSize) {
        gridGroup.append('line')
            .attr('x1', 0).attr('y1', y)
            .attr('x2', gridWidth).attr('y2', y)
            .attr('stroke', '#e5e7eb')
            .attr('stroke-width', y % (blockSize * 2) === 0 ? 1.5 : 0.8)
            .attr('opacity', 0.6);
    }
    
    // Add some city landmarks - repositioned for larger map
    const landmarks = [
        { x: 80, y: 60, type: 'park', label: 'Central Park' },
        { x: 220, y: 90, type: 'building', label: 'Downtown' },
        { x: 150, y: 180, type: 'station', label: 'Transit Hub' },
        { x: 320, y: 160, type: 'building', label: 'Business District' }
    ];
    
    const landmarkGroup = g.append('g').attr('class', 'landmarks');
    
    landmarks.forEach(landmark => {
        const landmarkG = landmarkGroup.append('g')
            .attr('transform', `translate(${landmark.x}, ${landmark.y})`);
        
        if (landmark.type === 'park') {
            landmarkG.append('circle')
                .attr('r', 15)
                .attr('fill', '#10b981')
                .attr('opacity', 0.3);
        } else if (landmark.type === 'building') {
            landmarkG.append('rect')
                .attr('x', -10).attr('y', -10)
                .attr('width', 20).attr('height', 20)
                .attr('fill', '#6b7280')
                .attr('opacity', 0.4);
        } else if (landmark.type === 'station') {
            landmarkG.append('circle')
                .attr('r', 12)
                .attr('fill', '#3b82f6')
                .attr('opacity', 0.5);
        }
        
        landmarkG.append('text')
            .attr('x', 0).attr('y', 30)
            .attr('text-anchor', 'middle')
            .style('font-size', '11px')
            .style('fill', '#6b7280')
            .style('font-weight', '500')
            .text(landmark.label);
    });
    
    // Add title
    g.append('text')
        .attr('x', gridWidth / 2)
        .attr('y', -5)
        .attr('text-anchor', 'middle')
        .style('font-size', '12px')
        .style('font-weight', 'bold')
        .style('fill', '#333')
        .text('City Transit Network Map');
    
    updateMapChart();
}

// Update Map Chart with current data
function updateMapChart() {
    const svg = d3.select('#map-svg');
    const g = svg.select('g');
    
    // Get unique routes from filtered data
    const routes = Array.from(new Set(filteredData.map(d => d.route))).sort();
    
    if (routes.length === 0) {
        g.selectAll('.route-path, .route-station, .route-label').remove();
        return;
    }
    
    // Calculate route statistics
    const routeStats = routes.map(route => {
        const routeData = filteredData.filter(d => d.route === route);
        return {
            route,
            avgDelay: d3.mean(routeData, d => d.avg_delay) || 0,
            totalPassengers: d3.sum(routeData, d => d.passengers) || 0,
            dataPoints: routeData.length
        };
    });
    
    // Define route paths with realistic city coordinates - larger layout
    const routePaths = {
        '7': [
            { x: 60, y: 70 }, { x: 130, y: 90 }, { x: 200, y: 110 }, { x: 270, y: 130 }, { x: 350, y: 150 }
        ],
        '42': [
            { x: 90, y: 210 }, { x: 160, y: 190 }, { x: 230, y: 170 }, { x: 300, y: 150 }, { x: 380, y: 130 }
        ],
        '43': [
            { x: 40, y: 120 }, { x: 100, y: 140 }, { x: 160, y: 160 }, { x: 220, y: 180 }, { x: 280, y: 200 }
        ],
        '50': [
            { x: 120, y: 50 }, { x: 140, y: 100 }, { x: 160, y: 150 }, { x: 180, y: 200 }, { x: 200, y: 240 }
        ]
    };
    
    const maxDelay = d3.max(routeStats, d => d.avgDelay) || 10;
    const colorScale = d3.scaleSequential(d3.interpolateRdYlGn)
        .domain([maxDelay, 0]);
    
    const thicknessScale = d3.scaleLinear()
        .domain([0, d3.max(routeStats, d => d.totalPassengers) || 1000])
        .range([4, 12]);
    
    // Create route group
    const routeGroup = g.selectAll('.route-group')
        .data(routeStats, d => d.route);
    
    routeGroup.exit().remove();
    
    const routeEnter = routeGroup.enter()
        .append('g')
        .attr('class', 'route-group');
    
    const routeMerge = routeEnter.merge(routeGroup);
    
    // Draw route paths
    routeMerge.each(function(d) {
        const group = d3.select(this);
        const path = routePaths[d.route] || [];
        
        if (path.length < 2) return;
        
        // Remove existing paths
        group.selectAll('.route-path').remove();
        
        // Create line generator
        const line = d3.line()
            .x(p => p.x)
            .y(p => p.y)
            .curve(d3.curveCardinal);
        
        // Add route path
        group.append('path')
            .attr('class', 'route-path')
            .attr('d', line(path))
            .attr('fill', 'none')
            .attr('stroke', colorScale(d.avgDelay))
            .attr('stroke-width', thicknessScale(d.totalPassengers))
            .attr('stroke-linecap', 'round')
            .attr('stroke-linejoin', 'round')
            .attr('opacity', selectedRoute === d.route ? 1 : 0.7)
            .style('cursor', 'pointer')
            .style('filter', selectedRoute === d.route ? 'drop-shadow(2px 2px 4px rgba(0,0,0,0.3))' : 'none');
        
        // Add stations (circles at path points)
        const stations = group.selectAll('.route-station')
            .data(path);
        
        stations.exit().remove();
        
        stations.enter()
            .append('circle')
            .attr('class', 'route-station')
            .merge(stations)
            .attr('cx', p => p.x)
            .attr('cy', p => p.y)
            .attr('r', selectedRoute === d.route ? 6 : 4)
            .attr('fill', 'white')
            .attr('stroke', colorScale(d.avgDelay))
            .attr('stroke-width', 2)
            .style('cursor', 'pointer')
            .style('filter', 'drop-shadow(1px 1px 2px rgba(0,0,0,0.2))');
        
        // Add route label at the end of the path
        const lastPoint = path[path.length - 1];
        group.selectAll('.route-label').remove();
        
        group.append('text')
            .attr('class', 'route-label')
            .attr('x', lastPoint.x + 15)
            .attr('y', lastPoint.y + 5)
            .style('font-size', '12px')
            .style('font-weight', 'bold')
            .style('fill', selectedRoute === d.route ? '#1f2937' : '#6b7280')
            .style('cursor', 'pointer')
            .style('text-shadow', '1px 1px 2px white')
            .text(`Route ${d.route}`);
        
        // Add performance indicator
        group.append('circle')
            .attr('class', 'performance-indicator')
            .attr('cx', lastPoint.x + 35)
            .attr('cy', lastPoint.y - 8)
            .attr('r', 5)
            .attr('fill', d.avgDelay <= 5 ? '#10b981' : d.avgDelay <= 10 ? '#f59e0b' : '#ef4444')
            .style('cursor', 'pointer');
    });
    
    // Add event handlers to entire route group
    routeMerge.selectAll('.route-path, .route-station, .route-label, .performance-indicator')
        .on('click', function(event, d) {
            const routeData = d3.select(this.parentNode).datum();
            selectedRoute = selectedRoute === routeData.route ? null : routeData.route;
            updateBarChart();
            updateLineChart();
            updateMapChart();
        })
        .on('mouseover', function(event, d) {
            const routeData = d3.select(this.parentNode).datum();
            const performance = routeData.avgDelay <= 5 ? 'Excellent' : 
                              routeData.avgDelay <= 10 ? 'Good' : 'Needs Improvement';
            showTooltip(event, `
                <strong>Route ${routeData.route}</strong><br/>
                Performance: <span style="color: ${routeData.avgDelay <= 5 ? '#10b981' : routeData.avgDelay <= 10 ? '#f59e0b' : '#ef4444'}">${performance}</span><br/>
                Avg Delay: ${routeData.avgDelay.toFixed(1)} min<br/>
                Total Passengers: ${routeData.totalPassengers.toLocaleString()}<br/>
                Data Points: ${routeData.dataPoints}<br/>
                <em>Click to ${selectedRoute === routeData.route ? 'deselect' : 'select'}</em>
            `);
        })
        .on('mouseout', hideTooltip);
    
    // Add legend - positioned for larger map
    const legend = g.selectAll('.map-legend').data([1]);
    const legendEnter = legend.enter()
        .append('g')
        .attr('class', 'map-legend')
        .attr('transform', 'translate(15, 220)');
    
    legendEnter.append('rect')
        .attr('width', 140)
        .attr('height', 50)
        .attr('fill', 'white')
        .attr('stroke', '#d1d5db')
        .attr('rx', 4)
        .attr('opacity', 0.9);
    
    legendEnter.append('text')
        .attr('x', 70)
        .attr('y', 15)
        .attr('text-anchor', 'middle')
        .style('font-size', '11px')
        .style('font-weight', 'bold')
        .style('fill', '#374151')
        .text('Performance');
    
    const legendItems = [
        { color: '#10b981', label: 'Excellent (≤5 min)', y: 27 },
        { color: '#f59e0b', label: 'Good (6-10 min)', y: 37 },
        { color: '#ef4444', label: 'Poor (>10 min)', y: 47 }
    ];
    
    legendItems.forEach(item => {
        legendEnter.append('circle')
            .attr('cx', 15)
            .attr('cy', item.y)
            .attr('r', 4)
            .attr('fill', item.color);
        
        legendEnter.append('text')
            .attr('x', 25)
            .attr('y', item.y + 3)
            .style('font-size', '9px')
            .style('fill', '#6b7280')
            .text(item.label);
    });
}

// Tooltip functions
function showTooltip(event, content) {
    const tooltip = d3.select('#tooltip');
    tooltip.style('opacity', 1)
        .html(content)
        .style('left', (event.pageX + 10) + 'px')
        .style('top', (event.pageY - 10) + 'px');
}

function hideTooltip() {
    d3.select('#tooltip').style('opacity', 0);
}

// Error handling and loading states
function showError(message) {
    const container = d3.select('.container');
    
    // Remove existing error banners
    container.selectAll('.error-banner').remove();
    
    container.append('div')
        .attr('class', 'error-banner')
        .style('background', 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)')
        .style('color', 'white')
        .style('padding', '15px 20px')
        .style('margin', '20px 0')
        .style('border-radius', '8px')
        .style('text-align', 'center')
        .style('font-weight', '500')
        .style('box-shadow', '0 4px 12px rgba(239, 68, 68, 0.3)')
        .style('animation', 'slideIn 0.3s ease-out')
        .html(`
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 8px; vertical-align: middle;">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            ${message}
        `);
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        container.selectAll('.error-banner')
            .transition()
            .duration(300)
            .style('opacity', 0)
            .style('transform', 'translateY(-20px)')
            .remove();
    }, 5000);
}

// Success notification
function showSuccess(message) {
    const container = d3.select('.container');
    
    container.append('div')
        .attr('class', 'success-banner')
        .style('background', 'linear-gradient(135deg, #10b981 0%, #059669 100%)')
        .style('color', 'white')
        .style('padding', '12px 20px')
        .style('margin', '10px 0')
        .style('border-radius', '6px')
        .style('text-align', 'center')
        .style('font-weight', '500')
        .style('font-size', '0.875rem')
        .style('box-shadow', '0 2px 8px rgba(16, 185, 129, 0.3)')
        .style('animation', 'slideIn 0.3s ease-out')
        .html(`
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 6px; vertical-align: middle;">
                <polyline points="20,6 9,17 4,12"/>
            </svg>
            ${message}
        `);
    
    // Auto-hide after 3 seconds
    setTimeout(() => {
        container.selectAll('.success-banner')
            .transition()
            .duration(300)
            .style('opacity', 0)
            .style('transform', 'translateY(-20px)')
            .remove();
    }, 3000);
}

// Loading state management
function setLoadingState(chartId, isLoading) {
    const chart = d3.select(`#${chartId}`);
    const loading = chart.select('.loading');
    const svg = chart.select('svg');
    
    if (isLoading) {
        loading.style('display', 'flex');
        svg.style('opacity', 0.3);
    } else {
        loading.style('display', 'none');
        svg.transition().duration(300).style('opacity', 1);
    }
}