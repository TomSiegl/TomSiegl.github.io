
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
        #define PI 3.1415926538

        precision highp float;

        uniform vec2 uMouse;
        uniform float uAspectRatio;

        varying vec2 v_uv;

        vec2 applyAspectRatio(vec2 point) {
            return vec2(point[0] * uAspectRatio, point[1]);
        }

        vec2 removeAspectRatio(vec2 point) {
            return vec2(point[0] / uAspectRatio, point[1]);
        }

        vec2 collapseRectangle(vec2 point, float width, float height) {

            vec2 p2 = (abs(point) + vec2(width, height) - 1.0) * (1.0 / vec2(width, height));  // translate and scale absolute p such that everything between borders is negative and on borders is in [0,1] (independent x and y coords)
            vec2 p3 = max(p2, 0.0);  // clip negatives to 0
            vec2 p4 = sign(point) * p3;  // reintroduce sign
            return p4;
        }
        
        vec2 toPolarCoords(vec2 point, float exp) {
            float distance = pow(pow(abs(point[0]), exp) + pow(abs(point[1]), exp), 1.0 / exp);
            float direction = acos(distance * -1.0 + 1.0);

            return vec2(distance, direction);
        }

        vec3 rodriguesRotation(vec3 v, vec3 k, float theta) {
            return v * cos(theta) + cross(k, v) * sin(theta) + k * dot(k, v) * (1.0 - cos(theta));
        }
        
        float band(float x, float centerL, float centerR, float widthL, float widthR) {
            return smoothstep(centerL - widthL, centerL, x) *
                (1.0 - smoothstep(centerR, centerR + widthR, x));
        }

        vec4 mixColorBands(float bandPosition) {
            vec3 c0 = vec3(0.95, 0.95, 0.95);
            vec3 c1 = vec3(0.9, 0.4, 0.2);
            vec3 c2 = vec3(0.4, 0.4, 0.9);
            vec3 c3 = vec3(0.98, 0.98, 0.98);

            // left band center edges
            float al0 = 0.44;
            float al1 = 0.46;
            float al2 = 0.48;
            float al3 = 0.5;

            // right band center edges
            float ar0 = 0.44;
            float ar1 = 0.47;
            float ar2 = 0.49;
            float ar3 = 1.0;

            // left band half-widths
            float wl0 = 0.44;
            float wl1 = 0.01;
            float wl2 = 0.01;
            float wl3 = 0.01;

            // left band half-widths
            float wr0 = 0.01;
            float wr1 = 0.01;
            float wr2 = 0.01;
            float wr3 = 0.01;

            float m0 = band(bandPosition, al0, ar0, wl0, wr0);
            float m1 = band(bandPosition, al1, ar1, wl1, wr1);
            float m2 = band(bandPosition, al2, ar2, wl2, wr2);
            float m3 = band(bandPosition, al3, ar3, wl3, wr3);

            // normalize weights to avoid energy blowup
            float sum = m0 + m1 + m2 + m3;
            sum = max(sum, 1e-4);

            vec3 bandColor = (m0 * c0 + m1 * c1 + m2 * c2 + m3 * c3) / sum;

            return vec4(bandColor, sum);
        }
        
        float specularReflection(vec3 surfacePoint, vec3 surfaceNormal, vec3 lightSourcePoint) {
            vec3 viewRay = vec3(0.0, 0.0, 1.0);  // orthogonal projection
            vec3 viewRayReflected = reflect(viewRay, surfaceNormal);

            vec3 surfaceToLightSource = normalize(lightSourcePoint - surfacePoint);

            float reflectionIntensity = 0.0;

            if (dot(surfaceNormal, surfaceToLightSource) > 0.0) {
                float reflectionAngle = acos(clamp(dot(viewRayReflected, surfaceToLightSource), 0.0, 1.0));  // angle between the reflected view vector and the light vector

                reflectionIntensity = 2.0 * reflectionAngle / PI;
                reflectionIntensity = reflectionIntensity * -1.0 + 1.0;
            }
            
            return reflectionIntensity;
        }
        
        float extendedSpecularReflection(vec3 surfacePoint, vec3 surfaceNormal, vec3 lightSourcePoint) {
            vec3 viewRay = vec3(0.0, 0.0, 1.0);  // orthogonal projection
            vec3 viewRayReflected = reflect(viewRay, surfaceNormal);

            vec3 surfaceToLightSource = normalize(lightSourcePoint - surfacePoint);

            float reflectionIntensity = 0.0;

            if (dot(surfaceNormal, surfaceToLightSource) <= 0.0) {
                float reflectionAngle = acos(dot(viewRayReflected, surfaceToLightSource)) - 0.5 * PI;  // angle between the reflected view vector and the light vector

                reflectionIntensity = 2.0 * reflectionAngle / PI;
                reflectionIntensity = reflectionIntensity * -1.0 + 1.0;
            }
            
            return reflectionIntensity;
        }

        void main() {
            // possible parameters
            float borderRadius = 0.3;
            vec3 lightSource = vec3(uMouse, -1.0);

            vec2 p = v_uv * 2.0 - 1.0;  // scale to [-1,1]

            // creative transform on fragment point
            //vec2 pTransformed = collapseRectangle(p, borderRadius / uAspectRatio, borderRadius);
            //vec2 pTransformed = applyAspectRatio(p);
            vec2 pTransformed = p;

            // polar coords
            float distExp = 8.0;
            vec2 pPolar = toPolarCoords(p, distExp);
            vec2 pPolarTransformed = toPolarCoords(pTransformed, distExp);
            float polarDistance = pPolar[0];
            float polarDistanceTransformed = pPolarTransformed[0];

            if (polarDistanceTransformed > 1.0) {  // cutoff at polar distance 1
                gl_FragColor = vec4(1.0);
                return;
            }

            // get axis to tilt away from the coordinate origin
            vec3 normalTiltingAxis = normalize(vec3(p[1], -p[0], 0.0));
            vec3 normalTiltingAxisTransformed = normalize(vec3(pTransformed[1], -pTransformed[0], 0.0));

            vec3 normal = vec3(0.0, 0.0, -1.0);
            //if (polarDistanceTransformed > 0.0) {  // only rotate when the axis is not the zero vector
            //    normal = rodriguesRotation(normal, normalTiltingAxisTransformed, polarDistanceTransformed);
            //}

            normal = rodriguesRotation(normal, normalTiltingAxis, toPolarCoords(p, 2.0)[0] * 0.1 - pow(polarDistance, 10.0));

            float reflectionIntensity = specularReflection(vec3(p, 1.0), normal, lightSource);
            float reflectionIntensityExtended = extendedSpecularReflection(vec3(p, 1.0), normal, lightSource);

            // specular reflection color
            vec4 mixReturn = mixColorBands(reflectionIntensity);
            vec3 bandColor = vec3(mixReturn[0], mixReturn[1], mixReturn[2]);
            float sum = mixReturn[3];
            float iridescenceStrength = clamp(sum, 0.0, 1.0);

            // blend with base albedo
            float albedoBrightness = 0.8;
            vec3 albedo = vec3(albedoBrightness);
            vec3 finalColor = mix(albedo, bandColor, iridescenceStrength);

            //gl_FragColor = vec4(normal, 1.0);
            //gl_FragColor = vec4(reflectionIntensity, reflectionIntensity, reflectionIntensity, 1.0);
            gl_FragColor = vec4(finalColor, 1.0);
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
            },
            uniformLocations: {
                uMouseLoc: gl.getUniformLocation(shaderProgram, "uMouse"),
                uAspectRatio: gl.getUniformLocation(shaderProgram, "uAspectRatio"),
            },
        };

        const buffers = initBuffers(gl);

        // Capture mouse movement
        const mouse = { x: 0, y: 0 };
        document.addEventListener("mousemove", e => {
            const rect = canvas.getBoundingClientRect();
            mouse.x = 2.0 * ((e.clientX - rect.left) / rect.width) - 1.0;
            mouse.y = 2.0 * (1.0 - (e.clientY - rect.top) / rect.height) - 1.0;

            requestAnimationFrame(render);
        });

        const aspect_ratio = canvas.width / canvas.height;

        function render() {
            drawScene(gl, programInfo, buffers, mouse, aspect_ratio);
        }

        requestAnimationFrame(render);
    }
});
