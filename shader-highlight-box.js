
import { initBuffers } from "./init-buffers.js";
import { drawScene } from "./draw-scene.js";

function loadShader(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.log('Shade compile failed');
        gl.deleteShader(shader);
        return null;
    }

    return shader;
}

function initShaderProgram(gl) {
    const vsSource = `
        attribute vec4 aVertexPosition;
        attribute vec4 aVertexColor;

        uniform mat4 uModelViewMatrix;
        uniform mat4 uProjectionMatrix;

        varying lowp vec4 vColor;

        void main() {
            gl_Position = uProjectionMatrix * uModelViewMatrix * aVertexPosition;
            vColor = aVertexColor;
        }
    `;
    const vertexShader = loadShader(gl, gl.VERTEX_SHADER, vsSource);

    const fsSource = `
        varying lowp vec4 vColor;

        void main() {
            gl_FragColor = vColor;
        }
    `;
    const fragmentShader = loadShader(gl, gl.FRAGMENT_SHADER, fsSource);

    const shaderProgram = gl.createProgram();
    gl.attachShader(shaderProgram, vertexShader);
    gl.attachShader(shaderProgram, fragmentShader);
    gl.linkProgram(shaderProgram);

    if (!gl.getProgramParameter(shaderProgram, gl.LINK_STATUS)) {
        console.log('Shader init failed');
        return null;
    }

    return shaderProgram;
}

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

    const gl = canvas.getContext('webgl');

    if (!gl) {
        container.removeChild(canvas_container);
    } else {
        const shaderProgram = initShaderProgram(gl);

        const programInfo = {
            program: shaderProgram,
            attribLocations: {
                vertexPosition: gl.getAttribLocation(shaderProgram, "aVertexPosition"),
                vertexColor: gl.getAttribLocation(shaderProgram, "aVertexColor"),
            },
            uniformLocations: {
                projectionMatrix: gl.getUniformLocation(shaderProgram, "uProjectionMatrix"),
                modelViewMatrix: gl.getUniformLocation(shaderProgram, "uModelViewMatrix"),
            },
        };

        const buffers = initBuffers(gl);

        let squareRotation = 0.0;
        let deltaTime = 0;

        let last = 0;

        function render(timestamp) {
            timestamp *= 0.001; // convert to seconds
            deltaTime = timestamp - last;
            last = timestamp;

            squareRotation += deltaTime;

            drawScene(gl, programInfo, buffers, squareRotation);
            
            requestAnimationFrame(render);
        }

        requestAnimationFrame(render);
    }
});
