
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
        attribute vec2 aVertexPosition;
        
        varying vec2 v_uv;

        void main() {
            v_uv = aVertexPosition * 0.5 + 0.5;
            gl_Position = vec4(aVertexPosition, 0.0, 1.0);
        }
    `;
    const vertexShader = loadShader(gl, gl.VERTEX_SHADER, vsSource);

    const fsSource = `
        precision highp float;
        varying vec2 v_uv;

        void main() {
            // possible parameters
            float borderRadius = 0.5;

            // fragment to border coords
            vec2 p = v_uv * 2.0 - 1.0;  // scale to [-1,1]
            vec2 p2 = (abs(p) - (1.0 - borderRadius)) * (1.0 / borderRadius);  // translate and scale absolute p such that everything between borders is negative and on borders is in [0,1] (independent x and y coords)
            vec2 p3 = max(p2, 0.0);  // clip negatives to 0
            vec2 p4 = sign(p) * p3;  // reintroduce sign

            float borderDistance = dot(p4, p4);  // how far along the width of the border is the fragment

            float borderAngle = degrees(acos(dot(p4, vec2(1.0, 0.0)) / length(p4)));  // angle in which direction the outer edge of the border is facing
            borderAngle = borderAngle / 180.0;  // scale to [0,1]
            borderAngle = borderAngle * sign(p[1]);  // add y sign of fragment position to differentiate all angle in full rotation
            borderAngle = borderAngle * 0.5 + 0.5;  // bring back to [0,1] for viz

            //gl_FragColor = vec4(borderDistance, borderDistance, borderDistance, 1.0);
            gl_FragColor = vec4(borderAngle, borderAngle, borderAngle, 1.0);
            //gl_FragColor = vec4(p, 0.0, 1.0);
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
