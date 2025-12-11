
const containers = document.querySelectorAll('[name="fx"]');

containers.forEach(container => {
    if (!container) return;

    container.classList = container.classList + ' highlight-container';

    // Create inner containers to put the canvas behind the content.
    const content_container = document.createElement('div');
    content_container.style.display = 'inline-block';
    content_container.style.zIndex = 2;

    const canvas_container = document.createElement('div');
    canvas_container.classList = 'canvas-container';

    // Create the canvas.
    const canvas = document.createElement('canvas');
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;

    // Move the current container content to an inner container.
    while (container.firstChild) {
        const content_element = container.firstChild;
        container.removeChild(content_element);
        content_container.appendChild(content_element);
    }
    
    // Nest inner containers and append to outer container.
    canvas_container.appendChild(canvas);
    container.appendChild(content_container);
    container.appendChild(canvas_container);
});
