// Enhanced navigation highlighting for Jekyll site with minimal-mistakes theme
document.addEventListener('DOMContentLoaded', function() {
    console.log('Navigation highlighting script loaded');
    
    // Get current page URL
    const currentPath = window.location.pathname;
    console.log('Current path:', currentPath);
    
    // Find all navigation links (both regular links and span elements)
    const navLinks = document.querySelectorAll('.nav__list a');
    const navSubTitles = document.querySelectorAll('.nav__list .nav__sub-title');
    
    // Remove any existing highlighting
    navLinks.forEach(link => {
        link.classList.remove('current', 'stage-current');
    });
    navSubTitles.forEach(span => {
        span.classList.remove('current', 'stage-current');
        span.parentElement.classList.remove('current', 'stage-current');
    });
    
    // Find exact page match first
    let exactMatch = false;
    navLinks.forEach(function(link) {
        const linkPath = link.getAttribute('href');
        
        if (linkPath) {
            // Clean paths for comparison
            const linkPathClean = linkPath.replace(/\/$/, '');
            const currentPathClean = currentPath.replace(/\/$/, '').replace(/\.html$/, '');
            
            // Check for exact match
            if (currentPathClean === linkPathClean || 
                currentPathClean + '/' === linkPath ||
                currentPath === linkPath) {
                
                link.classList.add('current');
                exactMatch = true;
                console.log('Exact match found:', linkPath);
                
                // If this is a sub-page, also highlight the parent stage
                const stageMatch = linkPath.match(/\/(Stage-(\d+))/);
                if (stageMatch) {
                    highlightStage(stageMatch[2]);
                }
            }
        }
    });
    
    // If no exact match, try to find stage match
    if (!exactMatch) {
        const stageMatch = currentPath.match(/\/(Stage-(\d+))/);
        if (stageMatch) {
            const stageNumber = stageMatch[2];
            console.log('Stage match found:', stageNumber);
            highlightStage(stageNumber);
        }
    }
    
    // Function to highlight stage title
    function highlightStage(stageNumber) {
        navSubTitles.forEach(function(span) {
            const spanText = span.textContent.trim();
            
            // Check if this is the correct stage title
            if (spanText.includes(`Stage ${stageNumber}:`)) {
                span.classList.add('stage-current');
                span.parentElement.classList.add('stage-current');
                console.log('Highlighted stage:', spanText);
                
                // Make sure the stage section is expanded
                const parentLi = span.closest('li');
                if (parentLi) {
                    const childList = parentLi.querySelector('ul');
                    if (childList) {
                        childList.style.display = 'block';
                    }
                }
            }
        });
    }
    
    // Special handling for root page
    if (currentPath === '/' || currentPath === '/index.html' || currentPath === '') {
        console.log('Root page detected - no specific highlighting');
    }
    
    console.log('Navigation highlighting complete');
});
